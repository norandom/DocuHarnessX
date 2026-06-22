"""Tests for the real Analyze stage adapter (task 5.2 boundary: AnalyzeStage).

The Analyze stage replaces the no-op stub in ``docuharnessx/stages/analyze.py``
with a thin HarnessX adapter that does the real analysis as a side effect of the
content-free ``step_end`` lifecycle event (design "AnalyzeStage", "Why work
happens as a step_end side effect"):

* it reaches the run ``State`` through the runtime bound at ``_bind_runtime``
  (the same handle :class:`NoOpStage` captures), wraps it in a ``RunContext``;
* reads the file inventory from ``SLOT_FILE_INVENTORY``; if unset (Ingest did not
  run / did not publish) it raises :class:`AnalyzeError`, halting the run with a
  clear cause and **no** partial analysis (Req 8.4);
* otherwise runs the deterministic ``analyze()`` core (no model, no network —
  Req 9.1), applies the optional gated ``enrich()`` (off by default — Req 9.4),
  writes the produced ``RepoAnalysis`` into ``SLOT_REPO_ANALYSIS`` (Req 7.2),
  emits a participation ``ProcessorTriggerEvent`` plus a bounded analysis summary
  to the journal (Req 8.2, 8.3, 10.1, 10.3), and yields the ``StepEndEvent``
  unchanged.

The class name ``AnalyzeStage``, the factory ``make_analyze_stage``, the
``STAGE_NAME`` constant, and the module path are kept stable so the stage
registry and ``make_docgen`` need no edits (Req 8.1).

These tests are harness-free: they drive ``on_step_end`` directly with a tiny
runtime stub (carrying ``state`` and a capturing ``tracer``) bound via
``_bind_runtime``, the same mechanism ``Harness.__init__`` uses. No credentials
and no network are involved — the optional enrichment is exercised with a local
fake provider only (reusing ``tests/_fakes.FakeProvider``).
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from typing import Any

import pytest

from harnessx.core.events import (
    ProcessorTriggerEvent,
    StepEndEvent,
    TaskStartEvent,
)
from harnessx.core.processor import Processor
from harnessx.core.state import State

from docuharnessx.analysis import analyze, scan
from docuharnessx.analysis.errors import AnalysisError, AnalyzeError
from docuharnessx.analysis.model import RepoAnalysis
from docuharnessx.context import RunContext
from docuharnessx.stages.analyze import (
    STAGE_NAME,
    AnalyzeStage,
    make_analyze_stage,
)
from docuharnessx.stages.base import (
    NoOpStage,
    PIPELINE_HOOK,
    STAGE_PARTICIPATION_ACTION,
)
from docuharnessx.types import SLOT_REPO_ANALYSIS

from tests._fakes import FakeProvider

REFERENCE_REPO = "/home/mc/Source/malware_hashes"


# --------------------------------------------------------------------------- #
# Harness-free drivers and a minimal runtime stub                              #
# --------------------------------------------------------------------------- #


@dataclass
class _CapturingTracer:
    """A stand-in run tracer that records every event emitted to ``on_event``.

    The real run tracer is a HarnessJournal; the base stage only ever calls its
    ``on_event`` coroutine, so a tiny async-capturing stub is enough to assert the
    stage journals its participation + summary without a live harness.
    """

    events: list[Any]

    def __init__(self) -> None:
        self.events = []

    async def on_event(self, event: Any) -> None:
        self.events.append(event)


class _RuntimeStub:
    """Minimal ``_HarnessRuntime`` stand-in carrying the run ``tracer``.

    ``Harness.__init__`` binds the live runtime onto every ``MultiHookProcessor``
    via ``_bind_runtime``; the base stage reaches the journal tracer through it.
    The live run ``State`` is *not* carried here — the stage captures it from the
    ``TaskStartEvent`` (see :func:`_bound_stage`), the proven mechanism the Ingest
    stage uses.
    """

    def __init__(self, tracer: _CapturingTracer | None) -> None:
        self.tracer = tracer


def _sample_event() -> StepEndEvent:
    """A representative content-free lifecycle event the stage must not mutate."""
    return StepEndEvent(
        run_id="run-test",
        step_id=7,
        step_summary="prior summary",
        tool_call_summary="readFile(a)",
        cumulative_tokens=10,
        cumulative_cost_usd=0.1,
    )


def _drive(stage: Processor, event: StepEndEvent) -> list[Any]:
    """Run the stage's async ``on_step_end`` generator to completion."""

    async def _collect() -> list[Any]:
        return [out async for out in stage.on_step_end(event)]

    return asyncio.run(_collect())


def _start_task(stage: AnalyzeStage, state: State) -> None:
    """Drive ``on_task_start`` so the stage captures the live run ``State``.

    Mirrors how the harness drives a ``MultiHookProcessor`` once per task with a
    ``TaskStartEvent`` that carries ``event.state`` — the mechanism the stage uses
    to reach the run ``State`` (``StepEndEvent`` is content-free).
    """

    async def _collect() -> None:
        async for _ in stage.on_task_start(
            TaskStartEvent(run_id=state.run_id, step_id=0, state=state)
        ):
            pass

    asyncio.run(_collect())


def _bound_stage(
    state: State,
    *,
    tracer: _CapturingTracer | None = None,
    enrich_enabled: bool = False,
    model: Any | None = None,
) -> AnalyzeStage:
    """Build an ``AnalyzeStage`` with the run State captured and a tracer bound.

    Binds the tracer-carrying runtime (as ``Harness.__init__`` does) and drives
    ``on_task_start`` so the stage captures the live ``State`` — exactly the
    lifecycle a real run produces before ``step_end``.
    """
    stage = AnalyzeStage()
    if enrich_enabled:
        stage.enrich_enabled = True
    if model is not None:
        stage._model_config = _MC(model)
    stage._bind_runtime(_RuntimeStub(tracer))
    _start_task(stage, state)
    return stage


class _MC:
    """A tiny ModelConfig stand-in exposing only ``.main`` (the provider)."""

    def __init__(self, provider: Any) -> None:
        self._provider = provider

    @property
    def main(self) -> Any:
        return self._provider


# --------------------------------------------------------------------------- #
# Fixtures: a deterministic inventory from a crafted tree + reference repo     #
# --------------------------------------------------------------------------- #


def _crafted_inventory(tmp_path):
    """A small, deterministic repo fixture scanned into a FileInventory."""
    (tmp_path / "main.go").write_text(
        'package main\n\nfunc main() {\n\tprintln("hi")\n}\n'
    )
    (tmp_path / "go.mod").write_text("module example.com/demo\n\ngo 1.22\n")
    (tmp_path / "README.md").write_text("# Demo\n\nA demo repo.\n")
    pkg = tmp_path / "internal" / "core"
    pkg.mkdir(parents=True)
    (pkg / "core.go").write_text("package core\n\nfunc Run() {}\n")
    (pkg / "core_test.go").write_text(
        "package core\n\nimport \"testing\"\n\nfunc TestRun(t *testing.T) {}\n"
    )
    return scan(str(tmp_path))


# --------------------------------------------------------------------------- #
# Contract stability (Req 8.1): names/factory/module path/hook unchanged       #
# --------------------------------------------------------------------------- #


def test_stage_name_is_stable() -> None:
    assert STAGE_NAME == "analyze"
    assert AnalyzeStage.stage_name == "analyze"


def test_factory_returns_a_fresh_analyze_stage() -> None:
    proc = make_analyze_stage()
    assert isinstance(proc, Processor)
    assert isinstance(proc, AnalyzeStage)
    assert make_analyze_stage() is not make_analyze_stage()


def test_analyze_stage_subclasses_noop_base_on_pipeline_hook() -> None:
    # Still a NoOpStage subclass on the single PIPELINE_HOOK, so the registry and
    # make_docgen wire it exactly as before (Req 8.1, 8.2).
    assert issubclass(AnalyzeStage, NoOpStage)
    assert AnalyzeStage._hook == PIPELINE_HOOK


def test_module_path_is_stable() -> None:
    assert AnalyzeStage.__module__ == "docuharnessx.stages.analyze"


# --------------------------------------------------------------------------- #
# No model required for the core path (Req 8.5, 9.1)                           #
# --------------------------------------------------------------------------- #


def test_core_path_publishes_repo_analysis_without_any_model(tmp_path) -> None:
    inv = _crafted_inventory(tmp_path)
    state = State(run_id="r1")
    RunContext(state).set_file_inventory(inv)

    stage = _bound_stage(state)  # no model bound, enrichment off
    out = _drive(stage, _sample_event())

    # Exactly one event out (the pass-through is asserted in its own test below).
    assert len(out) == 1

    published = RunContext(state).repo_analysis()
    assert isinstance(published, RepoAnalysis)
    # It equals the deterministic core analyze() over the same inventory (Req 9.1).
    assert published == analyze(inv)
    # Core path attaches no enrichment region (Req 9.4).
    assert published.enrichment is None


def test_event_is_forwarded_unchanged(tmp_path) -> None:
    inv = _crafted_inventory(tmp_path)
    state = State(run_id="r1b")
    RunContext(state).set_file_inventory(inv)
    stage = _bound_stage(state)

    event = _sample_event()
    out = _drive(stage, event)
    assert len(out) == 1
    assert out[0] is event  # same object, not mutated/replaced (content-neutral)


def test_published_analysis_written_through_named_slot(tmp_path) -> None:
    inv = _crafted_inventory(tmp_path)
    state = State(run_id="r1c")
    RunContext(state).set_file_inventory(inv)
    _drive(_bound_stage(state), _sample_event())

    slot = state.get_slot(SLOT_REPO_ANALYSIS)
    assert slot is not None
    assert isinstance(slot.content, RepoAnalysis)


# --------------------------------------------------------------------------- #
# Missing inventory halts the run with an identifiable error (Req 8.4)         #
# --------------------------------------------------------------------------- #


def test_missing_inventory_raises_analyze_error() -> None:
    state = State(run_id="r2")  # SLOT_FILE_INVENTORY never set
    stage = _bound_stage(state)

    with pytest.raises(AnalyzeError):
        _drive(stage, _sample_event())


def test_analyze_error_is_an_analysis_error() -> None:
    # The stage error is in the analysis family so a boundary can catch the family.
    assert issubclass(AnalyzeError, AnalysisError)


def test_missing_inventory_does_not_publish_partial_analysis() -> None:
    state = State(run_id="r2b")
    stage = _bound_stage(state)
    with pytest.raises(AnalyzeError):
        _drive(stage, _sample_event())
    # No partial RepoAnalysis was written (Req 8.4).
    assert RunContext(state).repo_analysis() is None


def test_analyze_error_message_names_the_offending_slot() -> None:
    state = State(run_id="r2c")
    stage = _bound_stage(state)
    with pytest.raises(AnalyzeError) as excinfo:
        _drive(stage, _sample_event())
    assert SLOT_REPO_ANALYSIS.rsplit(".", 1)[-1] in str(excinfo.value) or (
        "file_inventory" in str(excinfo.value)
    )


# --------------------------------------------------------------------------- #
# Driven outside a harness (no runtime bound): stays a graceful pass-through   #
# --------------------------------------------------------------------------- #


def test_pass_through_when_no_runtime_bound() -> None:
    # The shared stage suite drives every stage's process() with NO runtime bound
    # and asserts a pure pass-through. The real Analyze stage must keep that:
    # with no bound State it cannot do work, so it journals nothing and forwards
    # the event unchanged rather than raising.
    stage = AnalyzeStage()  # never _bind_runtime'd
    event = _sample_event()

    async def _collect() -> list[Any]:
        return [out async for out in stage.process(event)]

    out = asyncio.run(_collect())
    assert len(out) == 1
    assert out[0] is event


# --------------------------------------------------------------------------- #
# Journal participation + bounded summary (Req 8.2, 8.3, 10.1, 10.3)           #
# --------------------------------------------------------------------------- #


def test_emits_participation_trigger_with_bounded_summary(tmp_path) -> None:
    inv = _crafted_inventory(tmp_path)
    state = State(run_id="r3")
    RunContext(state).set_file_inventory(inv)
    tracer = _CapturingTracer()

    _drive(_bound_stage(state, tracer=tracer), _sample_event())

    triggers = [e for e in tracer.events if isinstance(e, ProcessorTriggerEvent)]
    assert len(triggers) == 1
    trig = triggers[0]
    assert trig.processor == "AnalyzeStage"
    assert trig.hook == PIPELINE_HOOK
    assert trig.action == STAGE_PARTICIPATION_ACTION
    # Bounded summary detail: stage + summary-level counts/flags only (Req 10.1).
    detail = trig.detail
    assert detail["stage"] == "analyze"
    analysis = analyze(inv)
    assert detail["total_loc"] == analysis.total_loc
    assert detail["total_files"] == analysis.total_files
    assert detail["primary_languages"] == list(analysis.primary_languages)
    assert detail["components"] == len(analysis.components)
    assert detail["enriched"] is False


def test_summary_does_not_embed_full_inventory(tmp_path) -> None:
    # The journal must stay bounded: no per-file inventory entries in the detail
    # (only summary-level fields), so a large repo cannot bloat the trace (Req 10.3).
    inv = _crafted_inventory(tmp_path)
    state = State(run_id="r3b")
    RunContext(state).set_file_inventory(inv)
    tracer = _CapturingTracer()
    _drive(_bound_stage(state, tracer=tracer), _sample_event())

    detail = [
        e for e in tracer.events if isinstance(e, ProcessorTriggerEvent)
    ][0].detail
    # No detail value should carry the per-file paths.
    flat = repr(detail)
    assert "main.go" not in flat
    assert "core_test.go" not in flat
    # Every detail value is a small scalar/list — not a RepoAnalysis or inventory.
    for value in detail.values():
        assert isinstance(value, (str, int, bool, list))


def test_works_without_a_bound_tracer(tmp_path) -> None:
    # When no tracer is reachable (driven outside a journaling harness) the stage
    # still does its work and forwards the event; it just records no trigger.
    inv = _crafted_inventory(tmp_path)
    state = State(run_id="r3c")
    RunContext(state).set_file_inventory(inv)
    stage = _bound_stage(state, tracer=None)

    out = _drive(stage, _sample_event())
    assert len(out) == 1
    assert isinstance(RunContext(state).repo_analysis(), RepoAnalysis)


# --------------------------------------------------------------------------- #
# Optional, gated enrichment (Req 9.3, 9.4, 9.5)                               #
# --------------------------------------------------------------------------- #


def test_enrichment_off_by_default_equals_core(tmp_path) -> None:
    inv = _crafted_inventory(tmp_path)
    state = State(run_id="r4")
    RunContext(state).set_file_inventory(inv)
    # Enrichment disabled (default) even if a model is reachable — gate is the flag.
    stage = _bound_stage(state, enrich_enabled=False, model=FakeProvider("ignored"))
    _drive(stage, _sample_event())

    published = RunContext(state).repo_analysis()
    assert published == analyze(inv)
    assert published.enrichment is None


def test_enrichment_enabled_attaches_region_without_altering_core(tmp_path) -> None:
    inv = _crafted_inventory(tmp_path)
    state = State(run_id="r5")
    RunContext(state).set_file_inventory(inv)
    stage = _bound_stage(
        state, enrich_enabled=True, model=FakeProvider("A small Go CLI.")
    )
    _drive(stage, _sample_event())

    published = RunContext(state).repo_analysis()
    core = analyze(inv)
    assert published.enrichment is not None
    assert published.enrichment.architecture_summary == "A small Go CLI."
    # Every deterministic core field is byte-for-byte identical to the core (Req 9.3).
    import dataclasses

    assert dataclasses.replace(published, enrichment=None) == core


def test_enrichment_enabled_sets_enriched_flag_in_summary(tmp_path) -> None:
    inv = _crafted_inventory(tmp_path)
    state = State(run_id="r5b")
    RunContext(state).set_file_inventory(inv)
    tracer = _CapturingTracer()
    stage = _bound_stage(
        state, tracer=tracer, enrich_enabled=True, model=FakeProvider("Summary.")
    )
    _drive(stage, _sample_event())

    trig = [e for e in tracer.events if isinstance(e, ProcessorTriggerEvent)][0]
    assert trig.detail["enriched"] is True


def test_enrichment_failure_still_emits_complete_core(tmp_path) -> None:
    inv = _crafted_inventory(tmp_path)
    state = State(run_id="r6")
    RunContext(state).set_file_inventory(inv)

    class _BoomProvider:
        model = "boom"

        async def complete(self, messages, tools, stream_callback=None):
            raise RuntimeError("simulated enrichment failure")

    stage = _bound_stage(state, enrich_enabled=True, model=_BoomProvider())
    out = _drive(stage, _sample_event())

    # The run is not halted by enrichment failure; the complete core is published.
    assert len(out) == 1
    published = RunContext(state).repo_analysis()
    assert published == analyze(inv)
    assert published.enrichment is None


def test_enrichment_enabled_without_model_returns_core(tmp_path) -> None:
    inv = _crafted_inventory(tmp_path)
    state = State(run_id="r6b")
    RunContext(state).set_file_inventory(inv)
    # enabled flag set, but no model reachable -> core unchanged, not an error.
    stage = _bound_stage(state, enrich_enabled=True, model=None)
    out = _drive(stage, _sample_event())
    assert len(out) == 1
    assert RunContext(state).repo_analysis() == analyze(inv)


# --------------------------------------------------------------------------- #
# Determinism end-to-end through the stage (Req 9.1, 9.2)                       #
# --------------------------------------------------------------------------- #


def test_two_runs_publish_equal_analysis(tmp_path) -> None:
    inv = _crafted_inventory(tmp_path)

    def _publish() -> RepoAnalysis:
        state = State(run_id="rdet")
        RunContext(state).set_file_inventory(inv)
        _drive(_bound_stage(state), _sample_event())
        return RunContext(state).repo_analysis()

    assert _publish() == _publish()


# --------------------------------------------------------------------------- #
# Reference repository (real polyglot Go CLI) (Req 7.2, 9.1, 9.2)              #
# --------------------------------------------------------------------------- #


@pytest.mark.skipif(
    not os.path.isdir(REFERENCE_REPO),
    reason="reference repo not present in this environment",
)
def test_reference_repo_publishes_go_primary_analysis() -> None:
    inv = scan(REFERENCE_REPO)
    state = State(run_id="rref")
    RunContext(state).set_file_inventory(inv)
    _drive(_bound_stage(state), _sample_event())

    published = RunContext(state).repo_analysis()
    assert isinstance(published, RepoAnalysis)
    # The stage publishes the deterministic core verbatim (Req 7.2, 9.1) — the
    # language ranking is the analyzer's call (validated in its own suite); the
    # stage's job is only to publish it faithfully. Go is a detected language of
    # this real Go CLI.
    assert published == analyze(inv)
    assert "Go" in {stat.language for stat in published.languages}
    assert published.scan_stats.files_scanned > 0
