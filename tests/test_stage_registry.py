"""Tests for the stage-registration contract and canonical ordering (task 3.1).

These cover ``docuharnessx.stages.__init__`` (boundary: StageRegistry):

* :data:`docuharnessx.stages.STAGES` — the ordered ``(StageName, factory)`` list
  in canonical pipeline order ingest → analyze → classify → plan → write →
  review → assemble → deploy (Req 5.2, 5.4).
* :func:`docuharnessx.stages.register_stages` — appends each stage processor on
  :data:`docuharnessx.stages.base.PIPELINE_HOOK` using append-don't-replace
  semantics, so processors already present on that hook are retained ahead of the
  stages (Req 5.1, 5.5, 5.6).

The registry attaches stages by giving each a monotonically increasing ``order``
on a single hook; HarnessX's ``HarnessBuilder`` then materialises them in that
order within the hook. The tests therefore assert on the builder's resolved
per-hook ordering (via ``_topological_sort_entries``) rather than guessing at
internal list positions.
"""

from __future__ import annotations

from harnessx.core.builder import HarnessBuilder, _topological_sort_entries
from harnessx.core.processor import Processor

from docuharnessx.stages.base import PIPELINE_HOOK


# Canonical pipeline order — the single source of truth the registry must mirror.
CANONICAL_ORDER: tuple[str, ...] = (
    "ingest",
    "analyze",
    "classify",
    "plan",
    "write",
    "review",
    "assemble",
    "deploy",
)


def _hook_order(builder: HarnessBuilder) -> list[object]:
    """Return the processors on PIPELINE_HOOK in their resolved execution order."""
    entries = [e for e in builder._entries if e.hook == PIPELINE_HOOK]
    return [e.processor for e in _topological_sort_entries(entries)]


def _stage_name(proc: object) -> str | None:
    """Best-effort stage identity: the no-op stub carries a ``stage_name``."""
    return getattr(proc, "stage_name", None)


def test_stages_list_is_canonical_order() -> None:
    from docuharnessx.stages import STAGES

    assert [name for name, _ in STAGES] == list(CANONICAL_ORDER)


def test_stages_list_pairs_names_with_callable_factories() -> None:
    from docuharnessx.stages import STAGES

    assert len(STAGES) == 8
    for name, factory in STAGES:
        assert callable(factory), f"{name} factory is not callable"
        proc = factory()
        assert isinstance(proc, Processor), f"{name} factory did not return a Processor"
        # Each call builds a fresh instance so a Wave 1+ swap shares no state.
        assert factory() is not factory()


def test_register_stages_returns_a_builder() -> None:
    from docuharnessx.stages import register_stages

    out = register_stages(HarnessBuilder())
    assert isinstance(out, HarnessBuilder)


def test_register_stages_appends_eight_stages_in_canonical_order() -> None:
    from docuharnessx.stages import register_stages

    builder = register_stages(HarnessBuilder())
    procs = _hook_order(builder)

    assert len(procs) == 8, f"expected 8 stage processors, got {len(procs)}"
    assert [_stage_name(p) for p in procs] == list(CANONICAL_ORDER)
    # Every registered stage sits on the single pipeline hook (Req 5.1).
    for entry in builder._entries:
        assert entry.hook == PIPELINE_HOOK


def test_register_stages_preserves_a_preexisting_hook_processor_ahead() -> None:
    from docuharnessx.stages import register_stages

    class _PreExisting:
        _hook = PIPELINE_HOOK
        stage_name = "preexisting"

        async def process(self, event):  # pragma: no cover - never driven here
            yield event

    pre = _PreExisting()
    builder = register_stages(HarnessBuilder().add(pre))
    procs = _hook_order(builder)

    # The pre-existing processor is retained (append-don't-replace, Req 5.5) and
    # ranks ahead of all eight stages (Req 5.5 "retained AHEAD of the stages").
    assert pre in procs
    assert procs[0] is pre
    assert [_stage_name(p) for p in procs[1:]] == list(CANONICAL_ORDER)
    assert len(procs) == 9


def test_register_stages_does_not_mutate_the_input_builder() -> None:
    from docuharnessx.stages import register_stages

    original = HarnessBuilder()
    register_stages(original)

    # HarnessBuilder is immutable: registration must not add entries to the input.
    assert [e for e in original._entries if e.hook == PIPELINE_HOOK] == []


def test_stages_list_factories_match_per_stage_module_exports() -> None:
    import importlib

    from docuharnessx.stages import STAGES

    for name, factory in STAGES:
        module = importlib.import_module(f"docuharnessx.stages.{name}")
        assert factory is getattr(module, f"make_{name}_stage"), (
            f"STAGES entry for {name} must reference the per-stage module factory "
            "so a Wave 1+ swap of that module's factory changes only that stage"
        )
