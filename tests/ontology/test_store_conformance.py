"""Shared store-conformance, determinism, and no-network/no-LLM suite (task 6.2).

This module is the cross-adapter conformance and reproducibility gate for the
ontology engine. It has three parts:

1. **Parametrized store conformance** (Req 9.3, 9.4, 9.5, 9.6) — a single set of
   scenario *bodies* run against BOTH :class:`InMemorySegmentStore` and
   :class:`FilesystemSegmentStore` via a pytest-parametrized ``store`` factory
   (the filesystem adapter uses ``tmp_path``). The same assertions therefore
   exercise both adapters; there is no copy-pasted second suite. Covered:
   validation-rejection on ``put``, id-conflict rejection (no overwrite),
   per-axis OR / cross-axis AND queries, empty-filter-returns-all, deterministic
   (by-id) listing order, and ``resolve_cross_links``.

2. **Determinism** (Req 11.2, 11.4) — repeated invocations on identical inputs
   yield equal / byte-identical results for ``load_vocabulary`` (and the
   ``vocabulary_to_config`` round-trip), ``validate_segment``, ``emit_tags``,
   ``store.query``, and ``build_role_view``.

3. **No network / no LLM** (Req 11.1, 11.2, 11.3) — importing every
   ``docuharnessx.ontology.*`` module fresh pulls in no network/LLM library as a
   transitive import; the only third-party package permitted is ``yaml``.
"""

from __future__ import annotations

import importlib
import pkgutil
import subprocess
import sys

import pytest

import docuharnessx.ontology as ontology_pkg
from docuharnessx.ontology.model import AxisTerm, Subject
from docuharnessx.ontology.schema import Segment
from docuharnessx.ontology.store import (
    AxisFilter,
    FilesystemSegmentStore,
    InMemorySegmentStore,
)
from docuharnessx.ontology.tags import emit_tags
from docuharnessx.ontology.validation import validate_segment
from docuharnessx.ontology.views import build_role_view
from docuharnessx.ontology.vocabulary import (
    Vocabulary,
    default_profile,
    load_vocabulary,
    vocabulary_to_config,
)


VOCAB = default_profile()


def _subject(raw: str) -> Subject:
    return Subject.parse(raw, frozenset(VOCAB.subject_prefixes))


def _segment(
    seg_id: str,
    *,
    roles=("developer",),
    intent="install",
    subjects=("component:core",),
    related=(),
) -> Segment:
    return Segment(
        id=seg_id,
        title=f"Title {seg_id}",
        roles=list(roles),
        subjects=[_subject(s) for s in subjects],
        intent=intent,
        related=list(related),
    )


# --------------------------------------------------------------------------- #
# Parametrized store factory: the SAME test bodies exercise BOTH adapters.     #
# --------------------------------------------------------------------------- #


@pytest.fixture(params=["in_memory", "filesystem"])
def store(request, tmp_path):
    """Yield a fresh, empty :class:`SegmentStore` for each adapter under test.

    Parametrized so every test using this fixture runs once against the
    in-memory adapter and once against the filesystem adapter (the latter backed
    by the test's ``tmp_path``). Both are bound to the default-profile vocabulary,
    so identical scenarios drive identical contracts.
    """
    if request.param == "in_memory":
        return InMemorySegmentStore(VOCAB)
    return FilesystemSegmentStore(tmp_path / "segments", VOCAB)


# --------------------------------------------------------------------------- #
# Conformance: validation-rejection on put (Req 9.2)                           #
# --------------------------------------------------------------------------- #


def test_put_rejects_invalid_segment_and_stores_nothing(store):
    from docuharnessx.ontology.errors import OntologyError

    bad = _segment("bad", roles=("not-a-real-role",))
    with pytest.raises(OntologyError):
        store.put(bad)
    assert store.list_segments() == ()


# --------------------------------------------------------------------------- #
# Conformance: id-conflict rejection, no overwrite (Req 9.7)                   #
# --------------------------------------------------------------------------- #


def test_put_rejects_id_conflict_without_overwriting(store):
    from docuharnessx.ontology.errors import IdConflictError

    store.put(_segment("dup", intent="install"))
    with pytest.raises(IdConflictError) as exc:
        store.put(_segment("dup", intent="configure"))
    assert exc.value.segment_id == "dup"
    # Original retained, not overwritten.
    (stored,) = store.list_segments()
    assert stored.id == "dup"
    assert stored.intent == "install"


# --------------------------------------------------------------------------- #
# Conformance: query semantics (Req 9.3, 9.4)                                  #
# --------------------------------------------------------------------------- #


def test_empty_filter_returns_all(store):
    store.put(_segment("a"))
    store.put(_segment("b", roles=("manager",), intent="use"))
    result = store.query(AxisFilter())
    assert {s.id for s in result} == {"a", "b"}


def test_single_axis_multi_value_is_or(store):
    store.put(_segment("dev", roles=("developer",)))
    store.put(_segment("mgr", roles=("manager",)))
    store.put(_segment("res", roles=("researcher",)))
    result = store.query(AxisFilter(roles=("developer", "manager")))
    assert {s.id for s in result} == {"dev", "mgr"}


def test_subject_axis_multi_value_is_or(store):
    store.put(_segment("core", subjects=("component:core",)))
    store.put(_segment("cli", subjects=("component:cli",)))
    store.put(_segment("py", subjects=("tech:python",)))
    where = AxisFilter(
        subjects=(_subject("component:core"), _subject("component:cli"))
    )
    result = store.query(where)
    assert {s.id for s in result} == {"core", "cli"}


def test_cross_axis_is_and(store):
    store.put(_segment("hit", roles=("developer",), intent="install"))
    store.put(_segment("wrong-intent", roles=("developer",), intent="use"))
    store.put(_segment("wrong-role", roles=("manager",), intent="install"))
    result = store.query(AxisFilter(roles=("developer",), intents=("install",)))
    assert {s.id for s in result} == {"hit"}


def test_cross_axis_and_with_subject(store):
    store.put(
        _segment("hit", roles=("developer",), subjects=("component:core",))
    )
    store.put(
        _segment("wrong-subj", roles=("developer",), subjects=("tech:python",))
    )
    where = AxisFilter(
        roles=("developer",), subjects=(_subject("component:core"),)
    )
    result = store.query(where)
    assert {s.id for s in result} == {"hit"}


# --------------------------------------------------------------------------- #
# Conformance: deterministic listing order (Req 9.5, 9.6)                      #
# --------------------------------------------------------------------------- #


def test_list_segments_deterministic_by_id(store):
    for seg_id in ("c", "a", "b"):
        store.put(_segment(seg_id))
    first = [s.id for s in store.list_segments()]
    second = [s.id for s in store.list_segments()]
    assert first == second == ["a", "b", "c"]


def test_query_results_are_tuple_in_by_id_order(store):
    for seg_id in ("z", "y", "x"):
        store.put(_segment(seg_id))
    result = store.query(AxisFilter())
    assert isinstance(result, tuple)
    assert [s.id for s in result] == ["x", "y", "z"]


# --------------------------------------------------------------------------- #
# Conformance: resolve_cross_links (Req 7.3 via the store seam)                #
# --------------------------------------------------------------------------- #


def test_resolve_cross_links_returns_declared_targets(store):
    store.put(_segment("a", related=("b", "c")))
    store.put(_segment("b"))
    store.put(_segment("c"))
    result = store.resolve_cross_links("a")
    assert isinstance(result, tuple)
    assert [s.id for s in result] == ["b", "c"]


def test_resolve_cross_links_skips_self_and_unknown(store):
    store.put(_segment("a", related=("a", "missing", "b")))
    store.put(_segment("b"))
    assert [s.id for s in store.resolve_cross_links("a")] == ["b"]


def test_resolve_cross_links_unknown_segment_returns_empty(store):
    store.put(_segment("a"))
    assert store.resolve_cross_links("nope") == ()


# --------------------------------------------------------------------------- #
# Determinism: identical inputs -> equal / byte-identical results (Req 11.2)   #
# --------------------------------------------------------------------------- #


def test_load_vocabulary_is_deterministic_and_round_trips():
    # load_vocabulary on the same parsed mapping yields equal Vocabularies.
    config = vocabulary_to_config(VOCAB)
    first = load_vocabulary(config)
    second = load_vocabulary(vocabulary_to_config(VOCAB))
    assert first == second == VOCAB

    # The config dict itself is byte-identical across repeated serialization.
    assert vocabulary_to_config(VOCAB) == vocabulary_to_config(VOCAB)

    # Round-trip holds for a custom-built vocabulary too (Req 1.9, 11.4).
    custom = Vocabulary(
        roles=(AxisTerm("custom-role", "Custom Role", "A custom role."),),
        intents=(
            AxisTerm("custom-intent", "Custom Intent", "A custom intent."),
        ),
        subject_prefixes=("widget:", "gadget:"),
    )
    assert load_vocabulary(vocabulary_to_config(custom)) == custom


def test_load_vocabulary_from_file_is_deterministic(tmp_path):
    import yaml

    config = vocabulary_to_config(VOCAB)
    path = tmp_path / "ontology.yaml"
    path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")

    first = load_vocabulary(path)
    second = load_vocabulary(path)
    assert first == second == VOCAB


def test_validate_segment_is_deterministic():
    seg = _segment(
        "multi-fault",
        roles=("developer", "not-a-role"),
        intent="not-an-intent",
        subjects=("component:core",),
    )
    first = validate_segment(seg, VOCAB)
    second = validate_segment(seg, VOCAB)

    # Same validity verdict and same ordered error tuple across runs.
    assert first.is_valid == second.is_valid
    assert tuple(type(e) for e in first.errors) == tuple(
        type(e) for e in second.errors
    )
    assert repr(first.errors) == repr(second.errors)


def test_emit_tags_is_deterministic_and_byte_identical():
    seg = _segment(
        "tagged",
        roles=("developer", "manager"),
        intent="install",
        subjects=("component:core", "tech:python"),
    )
    first = emit_tags(seg, VOCAB)
    second = emit_tags(seg, VOCAB)
    assert first == second
    assert list(first) == [
        "role:developer",
        "role:manager",
        "intent:install",
        "subject:component:core",
        "subject:tech:python",
    ]


def test_store_query_is_deterministic_across_adapters_and_runs(tmp_path):
    segments = [
        _segment("seg-3", roles=("developer", "manager"), intent="install",
                 subjects=("component:core", "tech:python")),
        _segment("seg-1", roles=("manager",), intent="configure",
                 subjects=("topic:overview",)),
        _segment("seg-2", roles=("developer",), intent="use",
                 subjects=("artifact:guide",)),
    ]
    mem = InMemorySegmentStore(VOCAB)
    fs = FilesystemSegmentStore(tmp_path / "seg", VOCAB)
    for seg in segments:
        mem.put(seg)
        fs.put(seg)

    where = AxisFilter(roles=("developer",))
    mem_first = [s.id for s in mem.query(where)]
    mem_second = [s.id for s in mem.query(where)]
    fs_first = [s.id for s in fs.query(where)]

    # Repeated runs are identical, and both adapters agree (Req 9.6 parity).
    assert mem_first == mem_second
    assert mem_first == fs_first


def test_build_role_view_is_deterministic():
    store = InMemorySegmentStore(VOCAB)
    store.put(_segment("use-1", roles=("developer",), intent="use"))
    store.put(_segment("install-1", roles=("developer",), intent="install"))
    store.put(_segment("install-2", roles=("developer",), intent="install"))
    store.put(_segment("other", roles=("manager",), intent="install"))

    first = [s.id for s in build_role_view(store, "developer", VOCAB)]
    second = [s.id for s in build_role_view(store, "developer", VOCAB)]
    assert first == second
    # Ordered by intent order (install before use), tie-broken by id.
    assert first == ["install-1", "install-2", "use-1"]


def test_build_role_view_empty_when_no_segment_for_role():
    store = InMemorySegmentStore(VOCAB)
    store.put(_segment("only", roles=("developer",)))
    assert build_role_view(store, "researcher", VOCAB) == ()


# --------------------------------------------------------------------------- #
# No network / no LLM: the ontology package pulls in no network/LLM library    #
# (Req 11.1, 11.2, 11.3). Only third-party import permitted is ``yaml``.       #
# --------------------------------------------------------------------------- #


#: Network / LLM client libraries that MUST NOT be a transitive import of the
#: ontology package (pure deterministic library code; no LLM calls).
_FORBIDDEN_TOP_LEVEL_MODULES = frozenset(
    {
        "requests",
        "httpx",
        "urllib3",
        "aiohttp",
        "httpcore",
        "openai",
        "anthropic",
        "cohere",
        "google",  # google.generativeai et al.
        "langchain",
        "litellm",
        "tiktoken",
    }
)


def _ontology_module_names() -> list[str]:
    """Every importable ``docuharnessx.ontology.*`` submodule name."""
    names = [ontology_pkg.__name__]
    for info in pkgutil.iter_modules(
        ontology_pkg.__path__, ontology_pkg.__name__ + "."
    ):
        names.append(info.name)
    return names


def test_ontology_imports_no_network_or_llm_library():
    """Import every ontology module in a fresh interpreter and assert that no
    network/LLM library ends up in ``sys.modules`` as a transitive import.

    Run in a subprocess so the assertion is unaffected by libraries pytest, the
    test session, or other test modules may have already imported into this
    interpreter's ``sys.modules``.
    """
    module_names = _ontology_module_names()
    forbidden = sorted(_FORBIDDEN_TOP_LEVEL_MODULES)
    program = (
        "import sys\n"
        f"for name in {module_names!r}:\n"
        "    __import__(name)\n"
        f"forbidden = {forbidden!r}\n"
        "leaked = sorted(\n"
        "    m for m in sys.modules\n"
        "    if any(m == f or m.startswith(f + '.') for f in forbidden)\n"
        ")\n"
        "print('\\n'.join(leaked))\n"
    )
    completed = subprocess.run(
        [sys.executable, "-c", program],
        capture_output=True,
        text=True,
        check=True,
    )
    leaked = [line for line in completed.stdout.splitlines() if line.strip()]
    assert leaked == [], f"network/LLM modules leaked into sys.modules: {leaked}"


def test_ontology_third_party_imports_limited_to_yaml():
    """The only third-party (non-stdlib, non-docuharnessx) top-level package the
    ontology engine imports is ``yaml`` (Req 11.1, 11.3).

    Computed in a fresh interpreter by diffing ``sys.modules`` before and after
    importing the whole ontology package, and filtering out the standard library
    and the project's own package. ``cython_runtime`` is tolerated: it is a
    pseudo-module the LibYAML C extension (Cython) injects as a side effect of
    importing ``yaml``, not an independent dependency.
    """
    module_names = _ontology_module_names()
    program = (
        "import sys\n"
        "baseline = set(sys.modules)\n"
        f"for name in {module_names!r}:\n"
        "    __import__(name)\n"
        "added = set(sys.modules) - baseline\n"
        "tops = sorted({m.split('.')[0] for m in added})\n"
        "stdlib = set(getattr(sys, 'stdlib_module_names', set()))\n"
        "allowed = {'docuharnessx', 'cython_runtime'}\n"
        "third_party = sorted(\n"
        "    t for t in tops\n"
        "    if t not in stdlib\n"
        "    and t not in allowed\n"
        "    and not t.startswith('_')\n"
        ")\n"
        "print('\\n'.join(third_party))\n"
    )
    completed = subprocess.run(
        [sys.executable, "-c", program],
        capture_output=True,
        text=True,
        check=True,
    )
    third_party = [
        line for line in completed.stdout.splitlines() if line.strip()
    ]
    assert third_party == ["yaml"], (
        f"unexpected third-party imports beyond yaml: {third_party}"
    )


def test_every_ontology_module_is_importable():
    """Sanity: importlib can fresh-import every discovered ontology submodule."""
    for name in _ontology_module_names():
        module = importlib.import_module(name)
        assert module is not None
