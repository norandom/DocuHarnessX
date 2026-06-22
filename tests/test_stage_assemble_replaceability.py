"""Stable-replaceability + reproducibility tests for the Assemble stage (mkdocs-site-assembler task 6.3).

Task 6.3 pins the two halves of the Assemble stage's *stability* contract — the same real
:class:`~docuharnessx.stages.assemble.AssembleStage` task 5.1 wired, exercised here for the
properties a downstream consumer (``github-pages-deploy``) and a maintainer rely on
(Req 1.1, 1.2, 8.2). It is the direct analog of ``tests/test_stage_review_replaceability.py``
(quality-review-gate task 5.2) for the Assemble slot.

Stable replaceability (Req 1.1, 1.2)
------------------------------------
The real stage drops into the exact slot the no-op ``assemble`` stub occupied, so the stage
registry and ``make_docgen`` need **zero edits**:

* the public surface is unchanged — the ``STAGE_NAME`` constant (``"assemble"``), the
  :class:`AssembleStage` class name, the :func:`make_assemble_stage` factory name, the
  ``docuharnessx/stages/assemble.py`` module path, and the ``__all__`` export set are all
  stable, and ``make_noop_stage`` is still re-exported (Req 1.1);
* the canonical eight-stage registry (:data:`docuharnessx.stages.STAGES`) and
  :func:`~docuharnessx.stages.register_stages` still bind ``assemble`` to
  :func:`make_assemble_stage` at its canonical (7th) position with **no edit to the list**,
  ``stage_class_for("assemble")`` resolves to the real class, and ``make_docgen`` still
  composes the canonical pipeline order with ``AssembleStage`` at its stable ``_target_``
  module path (Req 1.1, 1.2);
* a Wave 3+ spec can swap a *single* stage factory in :data:`STAGES` — proven with the
  importable :class:`tests._fakes.ReplacementStage` — without disturbing the other seven
  entries or mutating the global registry, confirming the registry is a single-stage-
  replaceable list (Req 1.1);
* driven **outside a harness** (no run ``State`` bound — no ``task_start`` to capture one)
  an :meth:`AssembleStage.on_step_end` / ``process`` direct drive forwards the lifecycle
  event *unchanged* and produces **no site**, exactly like the no-op base it replaced
  (Req 1.2/1.3).

Reproducibility (Req 8.2)
-------------------------
Two assemble runs over an **equal** :class:`~docuharnessx.review.model.ReviewReport` and an
**equal** target identity produce an **equal** :class:`~docuharnessx.assembler.model.AssembledSite`
(equal identity, equal page/role-page counts, equal *relative* path layout) and an **equal**
emitted site tree byte-for-byte. The two runs write into distinct output dirs (so the absolute
``site_dir`` / ``docs_dir`` / ``mkdocs_yml_path`` differ only by the output-dir prefix); the
test relativizes both the seam paths and the on-disk tree to the run's ``site/`` root before
comparing, so it asserts genuine byte-reproducibility of the *layout + content* rather than the
output-dir prefix.

Reproducibility is exercised across the two target-identity shapes the stage resolves through
the real :func:`~docuharnessx.assembler.identity.resolve_site_identity`:

* the **no-remote fallback** (``tmp_path`` is not a git repo; the same target-dir basename on
  both runs yields the same per-target ``site_name`` + root base-path); and
* a **GitHub-project identity** (``read_origin_remote`` patched to return the same fixed remote
  on both runs — network-free, host-git-independent — yielding the same ``/<repo>/`` base-path
  and project Pages ``site_url``).

These tests are credential-free and harness-free (except the bundle-composition assertions,
which only *compose* ``make_docgen`` — they never run it): ``on_task_start`` + ``on_step_end``
are driven directly over a seeded run ``State`` with a tiny runtime stub bound via
``_bind_runtime`` (mirroring ``tests/test_stage_assemble_integration.py``). No network, no real
model resolver, and no dependence on the host's git remotes.
"""

from __future__ import annotations

import asyncio
import importlib
from pathlib import Path
from typing import Any

import pytest
from harnessx.core.events import StepEndEvent, TaskStartEvent
from harnessx.core.state import State

import docuharnessx.stages.assemble as assemble_module
from docuharnessx.assembler.model import (
    ASSEMBLED_SITE_SCHEMA_VERSION,
    AssembledSite,
    SiteIdentity,
)
from docuharnessx.context import RunContext
from docuharnessx.ontology import (
    Segment,
    Subject,
    Vocabulary,
    default_profile,
)
from docuharnessx.review.model import (
    REVIEW_REPORT_SCHEMA_VERSION,
    ReviewAggregate,
    ReviewReport,
)
from docuharnessx.stages.assemble import (
    STAGE_NAME,
    AssembleStage,
    make_assemble_stage,
)


# --------------------------------------------------------------------------- #
# Harness-free drivers + a minimal runtime stub                                #
# (mirrors tests/test_stage_assemble_integration.py)                           #
# --------------------------------------------------------------------------- #


class _RuntimeStub:
    def __init__(self, tracer: Any | None = None) -> None:
        self.tracer = tracer


def _start_task(stage: AssembleStage, state: State) -> None:
    async def _collect() -> None:
        async for _ in stage.on_task_start(
            TaskStartEvent(run_id=state.run_id, step_id=0, state=state)
        ):
            pass

    asyncio.run(_collect())


def _bound_stage(state: State) -> AssembleStage:
    stage = AssembleStage()
    stage._bind_runtime(_RuntimeStub())
    _start_task(stage, state)
    return stage


def _sample_event() -> StepEndEvent:
    return StepEndEvent(
        run_id="run-assemble-repro",
        step_id=11,
        step_summary="prior summary",
        tool_call_summary="readFile(a)",
        cumulative_tokens=10,
        cumulative_cost_usd=0.1,
    )


def _drive(stage: AssembleStage, event: StepEndEvent) -> list[Any]:
    async def _collect() -> list[Any]:
        return [out async for out in stage.on_step_end(event)]

    return asyncio.run(_collect())


# --------------------------------------------------------------------------- #
# Fixtures: a seeded accepted set + report                                     #
# --------------------------------------------------------------------------- #


def _segment(
    seg_id: str,
    *,
    title: str,
    roles: list[str],
    intent: str,
    related: list[str] | None = None,
) -> Segment:
    return Segment(
        id=seg_id,
        title=title,
        roles=roles,
        subjects=[Subject(prefix="component", local=seg_id)],
        intent=intent,
        summary=f"Summary {seg_id}.",
        related=list(related or []),
        body=f"Body of {seg_id}.\n",
    )


def _accepted_segments() -> tuple[Segment, ...]:
    """Several roles + intents + a cross-link (and one dangling ref) so the layout is rich.

    A fresh tuple of fresh :class:`Segment` instances per call, so two seeded runs are
    independent — the site equality across them is genuine reproducibility over equal
    *content*, not a shared mutable object.
    """
    return (
        _segment(
            "scanner",
            title="Scanner",
            roles=["developer"],
            intent="extend",
            related=["core", "ghost-ref"],  # ghost-ref is dangling -> dropped
        ),
        _segment("core", title="Core", roles=["contributor"], intent="contribute"),
        _segment("runner", title="Runner", roles=["developer"], intent="operate"),
    )


def _report(*accepted: Segment) -> ReviewReport:
    return ReviewReport(
        schema_version=REVIEW_REPORT_SCHEMA_VERSION,
        entries=(),
        accepted=tuple(accepted),
        aggregate=ReviewAggregate(
            judged=len(accepted),
            accepted=len(accepted),
            rejected=0,
            unavailable=0,
            criterion_tally=(),
        ),
    )


def _seed_state(
    *,
    run_id: str,
    out_dir: str,
    target_repo: str,
    report: ReviewReport,
    vocab: Vocabulary,
) -> State:
    """Seed a fresh run State with the assemble-input slots the stage reads.

    A *fresh* ``State`` per call so two seeded runs are independent — the AssembledSite
    equality across them is genuine reproducibility over equal content.
    """
    state = State(run_id=run_id)
    rc = RunContext(state)
    rc.set_review_report(report)
    rc.set_vocabulary(vocab)
    rc.set_output_dir(out_dir)
    rc.set_target_repo(target_repo)
    return state


def _run_assemble(
    *,
    run_id: str,
    out_dir: str,
    target_repo: str,
    vocab: Vocabulary,
) -> AssembledSite:
    """Drive one full AssembleStage ``on_step_end`` over a freshly seeded State; return site."""
    report = _report(*_accepted_segments())
    state = _seed_state(
        run_id=run_id,
        out_dir=out_dir,
        target_repo=target_repo,
        report=report,
        vocab=vocab,
    )
    stage = _bound_stage(state)
    out = _drive(stage, _sample_event())
    assert len(out) == 1  # event forwarded unchanged (Req 1.2/1.4)
    site = RunContext(state).assembled_site()
    assert site is not None
    return site


def _read_tree(site_dir: Path) -> dict[str, bytes]:
    """Return a ``{relative-posix-path: bytes}`` map of every file under ``site_dir``."""
    out: dict[str, bytes] = {}
    for path in sorted(site_dir.rglob("*")):
        if path.is_file():
            out[path.relative_to(site_dir).as_posix()] = path.read_bytes()
    return out


def _relative_layout(site: AssembledSite, out_dir: str) -> dict[str, str]:
    """The seam's path layout *relative to the run output dir* (prefix-independent).

    Two runs in distinct output dirs share an identical relative layout when reproducible;
    this strips the only legitimate difference (the absolute output-dir prefix).
    """
    base = Path(out_dir).resolve()
    return {
        "site_dir": Path(site.site_dir).resolve().relative_to(base).as_posix(),
        "docs_dir": Path(site.docs_dir).resolve().relative_to(base).as_posix(),
        "mkdocs_yml_path": Path(site.mkdocs_yml_path)
        .resolve()
        .relative_to(base)
        .as_posix(),
    }


# =========================================================================== #
# Stable replaceability: unchanged public surface (Req 1.1)                     #
# =========================================================================== #


def test_public_surface_names_are_stable() -> None:
    # The stage-name constant, the class name, the factory name, and the module path are all
    # unchanged from the no-op stub, so the registry/bundle bind it identically (Req 1.1).
    assert STAGE_NAME == "assemble"
    assert AssembleStage.__name__ == "AssembleStage"
    assert AssembleStage.stage_name == "assemble"
    assert make_assemble_stage.__name__ == "make_assemble_stage"
    assert assemble_module.__name__ == "docuharnessx.stages.assemble"
    # The factory returns a real AssembleStage instance (the slot the stub occupied).
    instance = make_assemble_stage()
    assert isinstance(instance, AssembleStage)
    assert type(instance).__name__ == "AssembleStage"


def test_module_re_exports_make_noop_stage_and_canonical_names() -> None:
    # The no-op re-export is retained in __all__ so the registry/bundle's import surface is
    # untouched (design "Modified Files": __all__ retains make_noop_stage) (Req 1.1).
    assert "make_noop_stage" in assemble_module.__all__
    assert hasattr(assemble_module, "make_noop_stage")
    # The canonical names are exported too — the full, stable export set.
    for name in ("STAGE_NAME", "AssembleStage", "make_assemble_stage"):
        assert name in assemble_module.__all__
    # The export set is exactly the stable four (no accidental surface change).
    assert set(assemble_module.__all__) == {
        "STAGE_NAME",
        "AssembleStage",
        "make_assemble_stage",
        "make_noop_stage",
    }


def test_assemble_stage_subclasses_the_shared_noop_base() -> None:
    # Subclassing the shared no-op base is what lets the registry bind it identically to the
    # other stages (Req 1.2); confirmed here so the replaceability contract is structural.
    from docuharnessx.stages.base import NoOpStage

    assert issubclass(AssembleStage, NoOpStage)


# =========================================================================== #
# Stable replaceability: registry + bundle need no edits (Req 1.1, 1.2)         #
# =========================================================================== #


def test_registry_binds_assemble_to_its_factory_at_canonical_position() -> None:
    # The canonical eight-stage STAGES list still binds "assemble" to make_assemble_stage at
    # its canonical (7th) position with no edit to the list (Req 1.1).
    from docuharnessx.stages import STAGES

    names = [name for name, _factory in STAGES]
    assert names == [
        "ingest",
        "analyze",
        "classify",
        "plan",
        "write",
        "review",
        "assemble",
        "deploy",
    ]
    # Canonical position is the 7th entry (index 6).
    assert names.index("assemble") == 6
    assemble_entry = dict(STAGES)["assemble"]
    assert assemble_entry is make_assemble_stage
    assert assemble_entry().__class__ is AssembleStage


def test_stage_class_for_assemble_is_assemble_stage() -> None:
    # The registry's name->class map resolves "assemble" to the real AssembleStage (the module-
    # level class HarnessX serializes to an importable _target_) (Req 1.1).
    from docuharnessx.stages import stage_class_for

    assert stage_class_for("assemble") is AssembleStage


def test_make_docgen_composes_with_assemble_stage_in_canonical_order() -> None:
    # make_docgen still composes the canonical eight-stage pipeline with AssembleStage in the
    # assemble slot — no bundle edit needed for the real stage to drop in (Req 1.1, 1.2).
    from docuharnessx.bundle import make_docgen

    config = make_docgen(journal_dir="/tmp/dhx-assemble-repro-out")

    def _is_stage_target(target: str) -> bool:
        if not target.startswith("docuharnessx.stages."):
            return False
        module_path, _, class_name = target.rpartition(".")
        return module_path != "docuharnessx.stages.base" and class_name.endswith(
            "Stage"
        )

    stage_classes = [
        p["_target_"].rsplit(".", 1)[1]
        for p in config.processors
        if isinstance(p, dict) and _is_stage_target(p.get("_target_", ""))
    ]
    assert stage_classes == [
        "IngestStage",
        "AnalyzeStage",
        "ClassifyStage",
        "PlanStage",
        "WriteStage",
        "ReviewStage",
        "AssembleStage",
        "DeployStage",
    ]
    # AssembleStage's _target_ resolves to this stable module path (unchanged from the stub).
    assemble_targets = [
        p["_target_"]
        for p in config.processors
        if isinstance(p, dict) and p.get("_target_", "").endswith(".AssembleStage")
    ]
    assert assemble_targets == ["docuharnessx.stages.assemble.AssembleStage"]


def test_a_single_stage_factory_swap_flows_through_unchanged() -> None:
    # Single-stage replaceability: swapping ONE entry's factory in STAGES (here the assemble
    # slot, with the importable _fakes.ReplacementStage) leaves the other seven entries
    # untouched and the list a single-stage-replaceable surface (Req 1.1). We swap on a COPY
    # so the global registry is not mutated.
    from docuharnessx.stages import STAGES
    from tests._fakes import ReplacementStage, make_replacement_stage

    swapped = [
        (name, make_replacement_stage if name == "assemble" else factory)
        for name, factory in STAGES
    ]
    # Exactly one factory changed; the names/order are identical.
    assert [n for n, _ in swapped] == [n for n, _ in STAGES]
    assert dict(swapped)["assemble"] is make_replacement_stage
    assert isinstance(dict(swapped)["assemble"](), ReplacementStage)
    # Every other stage still resolves to its original factory (only assemble was swapped).
    for (name, orig), (sname, new) in zip(STAGES, swapped):
        assert name == sname
        if name != "assemble":
            assert orig is new
    # The real global registry was not mutated by the local swap.
    assert dict(STAGES)["assemble"] is make_assemble_stage


# =========================================================================== #
# Stable replaceability: out-of-harness pass-through (Req 1.2/1.3)              #
# =========================================================================== #


def test_out_of_harness_drive_forwards_event_and_produces_nothing() -> None:
    # Driven outside a harness (no task_start -> no run State captured) the stage forwards the
    # lifecycle event UNCHANGED and writes no site, exactly like the no-op base (Req 1.3).
    stage = make_assemble_stage()  # never task_start'd, no runtime bound
    event = _sample_event()
    out = _drive(stage, event)
    assert len(out) == 1
    assert out[0] is event  # the same event object, unmodified


def test_process_entrypoint_is_a_passthrough_off_harness() -> None:
    # The base `process` dispatcher (the way the run loop actually invokes the stage) is also a
    # pure pass-through off-harness — no site, same event (Req 1.3).
    stage = make_assemble_stage()
    event = _sample_event()

    async def _collect() -> list[Any]:
        return [out async for out in stage.process(event)]

    out = asyncio.run(_collect())
    assert len(out) == 1
    assert out[0] is event


# =========================================================================== #
# Reproducibility: equal report + equal target identity -> equal site (Req 8.2) #
# =========================================================================== #


def test_no_remote_run_is_reproducible_equal_site_and_bytes(tmp_path) -> None:
    # No-remote fallback: tmp_path holds no git repo, and both runs target an equally-named
    # directory, so resolve_site_identity yields the same per-target identity (target basename
    # site_name, root base-path) on both runs. Two assemble runs over an equal report + equal
    # target identity produce an EQUAL AssembledSite (identity + counts + relative layout) and
    # a byte-identical emitted tree (Req 8.2).
    vocab = default_profile()
    out_a = str(tmp_path / "run-a")
    out_b = str(tmp_path / "run-b")
    # Distinct (but identically-named) target dirs so the no-remote fallback derives the same
    # per-target site_name on both runs.
    target_a = tmp_path / "ta" / "widgets"
    target_b = tmp_path / "tb" / "widgets"
    target_a.mkdir(parents=True)
    target_b.mkdir(parents=True)

    s1 = _run_assemble(
        run_id="run-norem-a", out_dir=out_a, target_repo=str(target_a), vocab=vocab
    )
    s2 = _run_assemble(
        run_id="run-norem-b", out_dir=out_b, target_repo=str(target_b), vocab=vocab
    )

    # Equal identity (the per-target value), equal counts, equal schema version.
    assert s1.identity == s2.identity
    assert s1.identity.site_name == "widgets"  # target-dir basename
    assert s1.identity.base_path == "/"
    assert s1.page_count == s2.page_count
    assert s1.role_page_count == s2.role_page_count
    assert s1.schema_version == s2.schema_version == ASSEMBLED_SITE_SCHEMA_VERSION

    # Equal *relative* path layout (absolute paths differ only by the run output-dir prefix).
    assert _relative_layout(s1, out_a) == _relative_layout(s2, out_b)

    # Equal site bytes: the whole emitted site/ tree is byte-for-byte identical.
    tree1 = _read_tree(Path(s1.site_dir))
    tree2 = _read_tree(Path(s2.site_dir))
    assert tree1.keys() == tree2.keys()
    assert tree1 == tree2


def test_github_identity_run_is_reproducible_equal_site_and_bytes(
    tmp_path, monkeypatch
) -> None:
    # GitHub-project identity: read_origin_remote is patched (in the assemble module's import
    # namespace) to return the SAME fixed remote on both runs — network-free and independent of
    # the host's git config — so the stage resolves the same /<repo>/ base-path + project Pages
    # site_url on both runs. Two runs over an equal report + this equal target identity produce
    # an EQUAL AssembledSite and a byte-identical tree (Req 8.2, 3.2).
    remote = "https://github.com/norandom/malware_hashes.git"
    monkeypatch.setattr(
        assemble_module, "read_origin_remote", lambda _target: remote
    )

    vocab = default_profile()
    out_a = str(tmp_path / "run-a")
    out_b = str(tmp_path / "run-b")
    target = str(tmp_path / "malware_hashes")  # path is irrelevant once remote is fixed

    s1 = _run_assemble(
        run_id="run-gh-a", out_dir=out_a, target_repo=target, vocab=vocab
    )
    s2 = _run_assemble(
        run_id="run-gh-b", out_dir=out_b, target_repo=target, vocab=vocab
    )

    # The patched remote resolves to the per-target project Pages identity on both runs.
    assert s1.identity == s2.identity
    assert s1.identity.repo_name == "norandom/malware_hashes"
    assert s1.identity.base_path == "/malware_hashes/"
    assert s1.identity.site_url == "https://norandom.github.io/malware_hashes/"

    assert s1.page_count == s2.page_count
    assert s1.role_page_count == s2.role_page_count

    # Equal relative layout and byte-identical site tree.
    assert _relative_layout(s1, out_a) == _relative_layout(s2, out_b)
    tree1 = _read_tree(Path(s1.site_dir))
    tree2 = _read_tree(Path(s2.site_dir))
    assert tree1 == tree2
    # The per-target base-path is reflected verbatim into the emitted mkdocs.yml on both runs.
    assert b"norandom.github.io/malware_hashes/" in tree1["mkdocs.yml"]


def test_reproducible_runs_use_distinct_site_objects_yet_equal(tmp_path) -> None:
    # Reproducibility is genuine: two independent runs build DISTINCT AssembledSite object
    # identities (fresh State/report/segments each), yet the frozen value objects compare equal
    # on identity + counts because they are frozen value objects (Req 8.2). The absolute paths
    # differ by output-dir, so the relative layout is the comparable part.
    vocab = default_profile()
    out_a = str(tmp_path / "run-a")
    out_b = str(tmp_path / "run-b")
    target = tmp_path / "proj"
    target.mkdir()

    s1 = _run_assemble(
        run_id="run-dist-a", out_dir=out_a, target_repo=str(target), vocab=vocab
    )
    s2 = _run_assemble(
        run_id="run-dist-b", out_dir=out_b, target_repo=str(target), vocab=vocab
    )

    # Distinct object identities (separate runs)...
    assert s1 is not s2
    assert isinstance(s1, AssembledSite) and isinstance(s2, AssembledSite)
    # ...but value-equal identity + counts, and equal relative layout + bytes.
    assert s1.identity == s2.identity
    assert isinstance(s1.identity, SiteIdentity)
    assert (s1.page_count, s1.role_page_count) == (s2.page_count, s2.role_page_count)
    assert _relative_layout(s1, out_a) == _relative_layout(s2, out_b)
    assert _read_tree(Path(s1.site_dir)) == _read_tree(Path(s2.site_dir))


def test_repeated_assembly_into_the_same_out_dir_is_byte_stable(tmp_path) -> None:
    # Re-running assembly into the SAME output dir over an equal report + identity overwrites
    # the tree with byte-identical content (idempotent, byte-stable) — the strongest form of
    # determinism: identical absolute paths AND identical bytes on a re-run (Req 8.2).
    vocab = default_profile()
    out_dir = str(tmp_path / "run")
    target = tmp_path / "proj"
    target.mkdir()

    s1 = _run_assemble(
        run_id="run-same-a", out_dir=out_dir, target_repo=str(target), vocab=vocab
    )
    before = _read_tree(Path(s1.site_dir))

    s2 = _run_assemble(
        run_id="run-same-b", out_dir=out_dir, target_repo=str(target), vocab=vocab
    )
    after = _read_tree(Path(s2.site_dir))

    # Same out dir -> identical absolute seam paths AND identical bytes (fully idempotent).
    assert s1.site_dir == s2.site_dir
    assert s1.docs_dir == s2.docs_dir
    assert s1.mkdocs_yml_path == s2.mkdocs_yml_path
    assert s1.identity == s2.identity
    assert s1.page_count == s2.page_count
    assert s1.role_page_count == s2.role_page_count
    assert before == after


# --------------------------------------------------------------------------- #
# Cross-check: the importable replacement stage is a real, single-hook stub     #
# (the registry-swap test above relies on it being importable + pass-through)   #
# --------------------------------------------------------------------------- #


def test_replacement_stage_is_importable_and_pass_through() -> None:
    # The single-stage-swap test relies on _fakes.ReplacementStage being a real, importable,
    # module-level pass-through stage (so HarnessX can serialize it to a _target_). Confirm the
    # contract here so the swap test's premise is pinned.
    module = importlib.import_module("tests._fakes")
    assert hasattr(module, "ReplacementStage")
    assert hasattr(module, "make_replacement_stage")
    stage = module.make_replacement_stage()
    event = _sample_event()

    async def _collect() -> list[Any]:
        return [out async for out in stage.process(event)]

    out = asyncio.run(_collect())
    assert len(out) == 1
    assert out[0] is event
