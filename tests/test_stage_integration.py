"""Integration tests for the Ingest -> Analyze stage pair (task 6.2).

Where the per-stage suites (``test_stage_ingest.py``, ``test_stage_analyze.py``;
tasks 5.1/5.2) exercise each stage in isolation, this suite drives **both real
stages over one shared harness ``State``** so the inter-stage handoff is the real
seam under test (design "System Flows": Ingest writes the file inventory, Analyze
reads it and publishes ``RepoAnalysis``). It asserts the end-to-end behavior task
6.2 pins:

* driving Ingest then Analyze over a single ``State`` populates the
  ``SLOT_FILE_INVENTORY`` handoff slot and then the ``SLOT_REPO_ANALYSIS`` output
  slot (Req 1.7, 7.2, 7.4);
* both stages emit a ``stage_participated`` trigger into the run journal (Req 8.3,
  10.1, 10.3);
* a missing target repo halts at Ingest with :class:`IngestError`, and a missing
  inventory (Ingest skipped/failed) halts at Analyze with :class:`AnalyzeError`,
  in both cases with **no** ``RepoAnalysis`` published (Req 8.4);
* the enrichment gate is honored from the stage layer: disabled (the default)
  yields a result equal to the deterministic core, and a simulated enrichment
  failure still publishes the complete core (Req 9.3, 9.4, 9.5);
* ``make_docgen`` still composes with the canonical eight-stage order unchanged
  and the six non-ingest/analyze stages remaining genuine no-ops (Req 8.1, 8.2,
  10.1).

These tests are credential-free and network-free: enrichment is exercised only
with the local :class:`tests._fakes.FakeProvider`, never a real provider. The
stages are driven the way ``Harness.__init__`` + the run loop drive them — bind a
runtime carrying the run tracer via ``_bind_runtime``, hand the live ``State`` to
each stage through a ``TaskStartEvent`` (``on_task_start``), then drive the
content-free ``step_end`` hook (``on_step_end``). The hooks are driven *directly*
(not through ``MultiHookProcessor.process``) so a fatal stage error propagates
rather than being swallowed by ``process``.
"""

from __future__ import annotations

import asyncio
import dataclasses
import importlib
import os
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
from docuharnessx.analysis.errors import AnalyzeError, IngestError
from docuharnessx.analysis.model import RepoAnalysis
from docuharnessx.analysis.scanner import FileInventory
from docuharnessx.context import RunContext
from docuharnessx.stages.analyze import AnalyzeStage, make_analyze_stage
from docuharnessx.stages.base import STAGE_PARTICIPATION_ACTION
from docuharnessx.stages.ingest import IngestStage, make_ingest_stage
from docuharnessx.types import (
    SLOT_FILE_INVENTORY,
    SLOT_REPO_ANALYSIS,
    SLOT_TARGET_REPO,
    STAGE_NAMES,
)

from tests._fakes import FakeProvider

REFERENCE_REPO = "/home/mc/Source/malware_hashes"


# --------------------------------------------------------------------------- #
# Harness-faithful drivers + a recording run tracer                            #
# --------------------------------------------------------------------------- #


class _RecordingTracer:
    """A stand-in run tracer capturing every event a stage emits to ``on_event``.

    The real run tracer is a HarnessJournal; the stages only ever call its
    ``on_event`` coroutine, so this records each stage's participation across a
    shared run without a live harness.
    """

    def __init__(self) -> None:
        self.events: list[Any] = []

    async def on_event(self, event: Any) -> None:
        self.events.append(event)


class _Runtime:
    """Minimal ``_HarnessRuntime`` stand-in carrying just the run ``tracer``."""

    def __init__(self, tracer: Any | None) -> None:
        self.tracer = tracer


class _ModelConfig:
    """A tiny ``ModelConfig`` stand-in exposing only ``.main`` (the provider).

    ``AnalyzeStage._enrichment_model`` reads the bound model from
    ``self._model_config.main``; this mirrors that one attribute so enrichment can
    be driven with the credential-free :class:`FakeProvider`.
    """

    def __init__(self, provider: Any) -> None:
        self._provider = provider

    @property
    def main(self) -> Any:
        return self._provider


def _drive_hook(gen) -> list[Any]:
    """Run an async-generator hook to completion, propagating any raised error.

    Driven directly (not via ``MultiHookProcessor.process``) so a fatal
    :class:`IngestError`/:class:`AnalyzeError` raised inside the hook propagates;
    ``process`` would otherwise swallow non-control exceptions.
    """

    async def _collect() -> list[Any]:
        return [out async for out in gen]

    return asyncio.run(_collect())


def _step_end_event(run_id: str, step_id: int) -> StepEndEvent:
    return StepEndEvent(run_id=run_id, step_id=step_id)


def _bind_and_start(stage: Processor, state: State, tracer: Any | None) -> None:
    """Bind the run tracer and hand the live ``State`` to *stage* via task_start.

    Reproduces the run lifecycle: ``Harness.__init__`` binds the runtime onto each
    ``MultiHookProcessor`` (``_bind_runtime``), and the run loop drives a
    ``TaskStartEvent`` carrying ``event.state`` once per task (``on_task_start``),
    which is how the stage reaches the run ``State`` (``StepEndEvent`` is
    content-free).
    """
    stage._bind_runtime(_Runtime(tracer))
    _drive_hook(stage.on_task_start(TaskStartEvent(run_id=state.run_id, step_id=0, state=state)))


def _run_ingest(
    state: State, tracer: Any | None = None, *, step_id: int = 1
) -> list[Any]:
    """Drive the real Ingest stage's ``step_end`` over *state* (shared run)."""
    stage = make_ingest_stage()
    _bind_and_start(stage, state, tracer)
    return _drive_hook(stage.on_step_end(_step_end_event(state.run_id, step_id)))


def _run_analyze(
    state: State,
    tracer: Any | None = None,
    *,
    enrich_enabled: bool = False,
    model: Any | None = None,
    step_id: int = 2,
) -> list[Any]:
    """Drive the real Analyze stage's ``step_end`` over *state* (shared run)."""
    stage = make_analyze_stage()
    if enrich_enabled:
        stage.enrich_enabled = True
    if model is not None:
        stage._model_config = _ModelConfig(model)
    _bind_and_start(stage, state, tracer)
    return _drive_hook(stage.on_step_end(_step_end_event(state.run_id, step_id)))


def _make_repo(tmp_path) -> str:
    """Write a small deterministic Go fixture repo and return its path."""
    (tmp_path / "main.go").write_text(
        'package main\n\nfunc main() {\n\tprintln("hi")\n}\n'
    )
    (tmp_path / "go.mod").write_text("module example.com/demo\n\ngo 1.22\n")
    (tmp_path / "README.md").write_text("# Demo\n\nA demo repo.\n")
    pkg = tmp_path / "internal" / "core"
    pkg.mkdir(parents=True)
    (pkg / "core.go").write_text("package core\n\nfunc Run() {}\n")
    (pkg / "core_test.go").write_text(
        'package core\n\nimport "testing"\n\nfunc TestRun(t *testing.T) {}\n'
    )
    return str(tmp_path)


def _participation_triggers(tracer: _RecordingTracer) -> list[ProcessorTriggerEvent]:
    return [
        e
        for e in tracer.events
        if isinstance(e, ProcessorTriggerEvent)
        and e.action == STAGE_PARTICIPATION_ACTION
    ]


# --------------------------------------------------------------------------- #
# End-to-end: Ingest -> Analyze over one shared State populates both slots     #
# (Req 1.7, 7.2, 7.4)                                                          #
# --------------------------------------------------------------------------- #


def test_ingest_then_analyze_populates_both_slots(tmp_path) -> None:
    repo = _make_repo(tmp_path)
    state = State(run_id="run-integration")
    rc = RunContext(state)
    rc.set_target_repo(repo)

    # Before either stage runs, both handoff/output slots are explicitly unset.
    assert rc.file_inventory() is None
    assert rc.repo_analysis() is None

    # Stage 1: Ingest writes the inventory to the handoff slot.
    out_ingest = _run_ingest(state)
    assert len(out_ingest) == 1  # content-free pass-through
    inventory = rc.file_inventory()
    assert isinstance(inventory, FileInventory)

    # Stage 2: Analyze reads that same inventory from the shared State and
    # publishes the RepoAnalysis to its output slot.
    out_analyze = _run_analyze(state)
    assert len(out_analyze) == 1
    published = rc.repo_analysis()
    assert isinstance(published, RepoAnalysis)


def test_handoff_inventory_is_the_one_analyze_consumes(tmp_path) -> None:
    # The inventory Ingest publishes is exactly what Analyze analyzes — proving the
    # inter-stage handoff slot is the real seam (not a re-walk). The published
    # analysis equals analyze() over the handed-off inventory (Req 1.7, 7.2).
    repo = _make_repo(tmp_path)
    state = State(run_id="run-handoff")
    rc = RunContext(state)
    rc.set_target_repo(repo)

    _run_ingest(state)
    handed_off = rc.file_inventory()
    _run_analyze(state)

    assert rc.repo_analysis() == analyze(handed_off)


def test_published_analysis_reflects_the_scanned_repo(tmp_path) -> None:
    repo = _make_repo(tmp_path)
    state = State(run_id="run-reflect")
    rc = RunContext(state)
    rc.set_target_repo(repo)

    _run_ingest(state)
    _run_analyze(state)
    published = rc.repo_analysis()

    # The Go fixture is reflected end-to-end: Go is the primary language, the
    # go.mod build file and the test file are detected, the README is present.
    assert "Go" in published.primary_languages
    assert any(bf.kind == "go_mod" for bf in published.build_files)
    assert published.tests.present is True
    assert published.docs.has_readme is True
    # Core path attaches no enrichment region by default (Req 9.4).
    assert published.enrichment is None


def test_analysis_published_through_named_output_slot(tmp_path) -> None:
    repo = _make_repo(tmp_path)
    state = State(run_id="run-slot")
    RunContext(state).set_target_repo(repo)
    _run_ingest(state)
    _run_analyze(state)

    slot = state.get_slot(SLOT_REPO_ANALYSIS)
    assert slot is not None
    assert isinstance(slot.content, RepoAnalysis)


def test_pipeline_is_deterministic_across_two_runs(tmp_path) -> None:
    repo = _make_repo(tmp_path)

    def _publish() -> RepoAnalysis:
        state = State(run_id="run-det")
        RunContext(state).set_target_repo(repo)
        _run_ingest(state)
        _run_analyze(state)
        return RunContext(state).repo_analysis()

    assert _publish() == _publish()


# --------------------------------------------------------------------------- #
# Both stages emit participation triggers into one shared journal               #
# (Req 8.3, 10.1, 10.3)                                                        #
# --------------------------------------------------------------------------- #


def test_both_stages_emit_participation_into_shared_journal(tmp_path) -> None:
    repo = _make_repo(tmp_path)
    state = State(run_id="run-journal")
    RunContext(state).set_target_repo(repo)
    tracer = _RecordingTracer()  # one tracer shared across the run

    _run_ingest(state, tracer)
    _run_analyze(state, tracer)

    triggers = _participation_triggers(tracer)
    processors = {t.processor for t in triggers}
    stages = {t.detail["stage"] for t in triggers}
    assert processors == {"IngestStage", "AnalyzeStage"}
    assert stages == {"ingest", "analyze"}


def test_participation_summaries_are_bounded_scalars(tmp_path) -> None:
    # The journal must stay bounded for large repos: each stage's detail carries
    # only summary-level scalars/lists — never the per-file inventory (Req 10.3).
    repo = _make_repo(tmp_path)
    state = State(run_id="run-bounded")
    RunContext(state).set_target_repo(repo)
    tracer = _RecordingTracer()

    _run_ingest(state, tracer)
    _run_analyze(state, tracer)

    for trig in _participation_triggers(tracer):
        for value in trig.detail.values():
            assert isinstance(value, (str, int, bool, list))
        # No per-file path leaks into the summary detail.
        flat = repr(trig.detail)
        assert "main.go" not in flat
        assert "core_test.go" not in flat


def test_ingest_summary_reports_primary_language_and_count(tmp_path) -> None:
    repo = _make_repo(tmp_path)
    state = State(run_id="run-ingsum")
    RunContext(state).set_target_repo(repo)
    tracer = _RecordingTracer()
    _run_ingest(state, tracer)

    ingest_trig = next(
        t for t in _participation_triggers(tracer) if t.processor == "IngestStage"
    )
    assert ingest_trig.detail["primary_language"] == "Go"
    assert ingest_trig.detail["files"] == len(RunContext(state).file_inventory().entries)
    assert ingest_trig.detail["limit_reached"] is False


# --------------------------------------------------------------------------- #
# Fatal preconditions halt the run with the right stage error, no partial      #
# RepoAnalysis (Req 8.4)                                                       #
# --------------------------------------------------------------------------- #


def test_missing_repo_halts_at_ingest_no_analysis() -> None:
    # Repo slot unset: Ingest halts the run before any inventory is produced, so
    # the downstream RepoAnalysis is never written (Req 1.2, 8.4).
    state = State(run_id="run-norepo")  # SLOT_TARGET_REPO never set
    with pytest.raises(IngestError):
        _run_ingest(state)
    rc = RunContext(state)
    assert rc.file_inventory() is None
    assert rc.repo_analysis() is None


def test_missing_inventory_halts_at_analyze_no_analysis() -> None:
    # Ingest skipped/failed: the handoff inventory slot is unset, so Analyze halts
    # with an identifiable AnalyzeError and writes no partial analysis (Req 8.4).
    state = State(run_id="run-noinv")  # SLOT_FILE_INVENTORY never set
    with pytest.raises(AnalyzeError):
        _run_analyze(state)
    assert RunContext(state).repo_analysis() is None


def test_invalid_repo_path_halts_at_ingest(tmp_path) -> None:
    missing = str(tmp_path / "does-not-exist")
    state = State(run_id="run-badpath")
    RunContext(state).set_target_repo(missing)
    with pytest.raises(IngestError) as excinfo:
        _run_ingest(state)
    # The message names the offending path so the run-halting cause is auditable.
    assert missing in str(excinfo.value)
    assert RunContext(state).file_inventory() is None


# --------------------------------------------------------------------------- #
# Enrichment gate honored end-to-end through the stage layer                   #
# (Req 9.3, 9.4, 9.5)                                                          #
# --------------------------------------------------------------------------- #


def test_enrichment_disabled_equals_core_end_to_end(tmp_path) -> None:
    # Default gate (off) — even with a model reachable, the published analysis is
    # exactly the deterministic core and carries no enrichment region (Req 9.4).
    repo = _make_repo(tmp_path)
    state = State(run_id="run-enrich-off")
    rc = RunContext(state)
    rc.set_target_repo(repo)

    _run_ingest(state)
    handed_off = rc.file_inventory()
    _run_analyze(state, enrich_enabled=False, model=FakeProvider("ignored summary"))

    published = rc.repo_analysis()
    assert published == analyze(handed_off)
    assert published.enrichment is None


def test_enrichment_enabled_attaches_region_without_altering_core(tmp_path) -> None:
    repo = _make_repo(tmp_path)
    state = State(run_id="run-enrich-on")
    rc = RunContext(state)
    rc.set_target_repo(repo)

    _run_ingest(state)
    handed_off = rc.file_inventory()
    _run_analyze(state, enrich_enabled=True, model=FakeProvider("A small Go CLI."))

    published = rc.repo_analysis()
    assert published.enrichment is not None
    assert published.enrichment.architecture_summary == "A small Go CLI."
    # Every deterministic core field is identical to the model-free core (Req 9.3).
    assert dataclasses.replace(published, enrichment=None) == analyze(handed_off)


def test_enrichment_failure_still_publishes_complete_core(tmp_path) -> None:
    # A simulated enrichment failure must not halt the run nor degrade the core:
    # the complete deterministic analysis is still published (Req 9.5).
    repo = _make_repo(tmp_path)
    state = State(run_id="run-enrich-boom")
    rc = RunContext(state)
    rc.set_target_repo(repo)

    class _BoomProvider:
        model = "boom"

        async def complete(self, messages, tools, stream_callback=None):
            raise RuntimeError("simulated enrichment failure")

    _run_ingest(state)
    handed_off = rc.file_inventory()
    out = _run_analyze(state, enrich_enabled=True, model=_BoomProvider())

    assert len(out) == 1  # the run is not halted by enrichment failure
    published = rc.repo_analysis()
    assert published == analyze(handed_off)
    assert published.enrichment is None


def test_enrichment_enabled_sets_enriched_flag_in_journal(tmp_path) -> None:
    repo = _make_repo(tmp_path)
    state = State(run_id="run-enrich-flag")
    RunContext(state).set_target_repo(repo)
    tracer = _RecordingTracer()

    _run_ingest(state, tracer)
    _run_analyze(state, tracer, enrich_enabled=True, model=FakeProvider("Summary."))

    analyze_trig = next(
        t for t in _participation_triggers(tracer) if t.processor == "AnalyzeStage"
    )
    assert analyze_trig.detail["enriched"] is True


def test_enrichment_disabled_sets_enriched_false_in_journal(tmp_path) -> None:
    repo = _make_repo(tmp_path)
    state = State(run_id="run-enrich-flag-off")
    RunContext(state).set_target_repo(repo)
    tracer = _RecordingTracer()

    _run_ingest(state, tracer)
    _run_analyze(state, tracer)  # default gate off

    analyze_trig = next(
        t for t in _participation_triggers(tracer) if t.processor == "AnalyzeStage"
    )
    assert analyze_trig.detail["enriched"] is False


# --------------------------------------------------------------------------- #
# make_docgen still composes; canonical order preserved; six stages no-ops     #
# (Req 8.1, 8.2)                                                               #
# --------------------------------------------------------------------------- #


# The canonical stage class names in pipeline order. Reuses the same ordering the
# bundle smoke test pins, asserted here from the integration boundary.
_CANONICAL_STAGE_CLASSES: tuple[str, ...] = (
    "IngestStage",
    "AnalyzeStage",
    "ClassifyStage",
    "PlanStage",
    "WriteStage",
    "ReviewStage",
    "AssembleStage",
    "DeployStage",
)

# The six stages that must remain untouched no-op stubs after this spec.
_NOOP_STAGE_NAMES: tuple[str, ...] = (
    "classify",
    "plan",
    "write",
    "review",
    "assemble",
    "deploy",
)


def _is_stage_target(target: str) -> bool:
    if not target.startswith("docuharnessx.stages."):
        return False
    module_path, _, class_name = target.rpartition(".")
    return module_path != "docuharnessx.stages.base" and class_name.endswith("Stage")


def test_make_docgen_still_composes_with_canonical_order_unchanged() -> None:
    # The real Ingest/Analyze stages drop in without disturbing composition: the
    # bundle still builds and the eight stages keep the canonical pipeline order
    # (single-stage replaceability; Req 8.1).
    from docuharnessx.bundle import make_docgen

    config = make_docgen(journal_dir="/tmp/dhx-integration-out")
    stage_classes = [
        p["_target_"].rsplit(".", 1)[1]
        for p in config.processors
        if isinstance(p, dict) and _is_stage_target(p.get("_target_", ""))
    ]
    assert stage_classes == list(_CANONICAL_STAGE_CLASSES)
    # And STAGE_NAMES (the canonical-order source of truth) is unchanged by the
    # append-only seam extension this spec made (Req 7.1, 8.2).
    assert STAGE_NAMES == (
        "ingest",
        "analyze",
        "classify",
        "plan",
        "write",
        "review",
        "assemble",
        "deploy",
    )


def test_six_other_stages_remain_pass_through_noops() -> None:
    # The six stages this spec does not own must still be genuine pass-throughs:
    # driving each yields the same content-free event unchanged (Req 8.2).
    event = _step_end_event("run-noop", 1)

    async def _collect(proc: Processor) -> list[Any]:
        return [out async for out in proc.process(event)]

    for stage_name in _NOOP_STAGE_NAMES:
        module = importlib.import_module(f"docuharnessx.stages.{stage_name}")
        factory = getattr(module, f"make_{stage_name}_stage")
        proc = factory()
        out = asyncio.run(_collect(proc))
        assert len(out) == 1, f"{stage_name} yielded {len(out)} events, expected 1"
        assert out[0] is event, f"{stage_name} mutated/replaced the lifecycle event"


def test_only_ingest_and_analyze_are_real_stages() -> None:
    # Defensive: the two owned stages are the real processors; the other six remain
    # the no-op base subclasses (they do no slot I/O), confirming the spec touched
    # exactly two modules (design "Modified Files").
    from docuharnessx.stages.base import NoOpStage

    assert issubclass(IngestStage, NoOpStage)
    assert issubclass(AnalyzeStage, NoOpStage)
    # The owned stages override on_step_end (real work); the six others do not.
    assert "on_step_end" in vars(IngestStage)
    assert "on_step_end" in vars(AnalyzeStage)
    for stage_name in _NOOP_STAGE_NAMES:
        module = importlib.import_module(f"docuharnessx.stages.{stage_name}")
        cls = getattr(module, f"{stage_name.capitalize()}Stage")
        assert "on_step_end" not in vars(cls), (
            f"{stage_name} unexpectedly overrides on_step_end (should stay a no-op)"
        )


# --------------------------------------------------------------------------- #
# Reference repository: full Ingest -> Analyze over a real polyglot Go CLI      #
# (Req 1.7, 7.2, 9.2)                                                          #
# --------------------------------------------------------------------------- #


@pytest.mark.skipif(
    not os.path.isdir(REFERENCE_REPO),
    reason="reference repo not present in this environment",
)
def test_reference_repo_end_to_end_through_both_stages() -> None:
    state = State(run_id="run-ref")
    rc = RunContext(state)
    rc.set_target_repo(REFERENCE_REPO)
    tracer = _RecordingTracer()

    _run_ingest(state, tracer)
    inventory = rc.file_inventory()
    assert isinstance(inventory, FileInventory)
    assert inventory.stats.files_scanned > 0

    _run_analyze(state, tracer)
    published = rc.repo_analysis()
    assert isinstance(published, RepoAnalysis)
    # The stage publishes the deterministic core verbatim over the handed-off
    # inventory (Req 7.2): Go is a detected language of this real Go CLI.
    assert published == analyze(inventory)
    assert "Go" in {stat.language for stat in published.languages}

    # Both stages participated in the shared run journal.
    processors = {t.processor for t in _participation_triggers(tracer)}
    assert processors == {"IngestStage", "AnalyzeStage"}
