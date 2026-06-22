"""Tests for the real Ingest stage (task 5.1 boundary: IngestStage).

The Ingest stage replaces the Wave 0 no-op stub in place. It must keep the
harness contract stable (module path, ``STAGE_NAME``, ``IngestStage`` class,
``make_ingest_stage`` factory) while doing real work as a side effect of the
content-free ``step_end`` lifecycle event (Req 8.1):

* read the target-repository path from the run context (``SLOT_TARGET_REPO``),
  walk it with the deterministic scanner, and publish the resulting
  ``FileInventory`` to the inter-stage handoff slot (``SLOT_FILE_INVENTORY``)
  (Req 1.1, 1.7);
* raise an identifiable :class:`IngestError` that halts the run — producing no
  partial inventory — when the repo slot is unset or its path is missing / not a
  directory (Req 1.2, 8.4);
* record participation plus a bounded scan summary in the journal and yield the
  ``StepEndEvent`` unchanged, exactly as the no-op base does (Req 8.2, 8.3,
  10.1, 10.3).

The stage is a ``MultiHookProcessor`` driven once per lifecycle hook. The live
run ``State`` is carried on :class:`TaskStartEvent.state`; the stage captures it
there and uses it from ``on_step_end`` (``StepEndEvent`` is content-free and
carries no live state). These tests drive the realistic lifecycle — ``on_task_start``
then ``on_step_end`` — synchronously via ``asyncio.run``.

The hooks are driven *directly* (not through ``MultiHookProcessor.process``)
because ``process`` swallows non-control exceptions and yields the event through;
the stage's fatal :class:`IngestError` is raised from ``on_step_end`` itself, so
driving the hook directly is what surfaces the run-halting cause (Req 8.4).
"""

from __future__ import annotations

import asyncio
import os

import pytest

from harnessx.core.events import (
    ProcessorTriggerEvent,
    StepEndEvent,
    TaskStartEvent,
)
from harnessx.core.processor import Processor
from harnessx.core.state import State

from docuharnessx.analysis.errors import IngestError
from docuharnessx.analysis.scanner import FileInventory
from docuharnessx.context import RunContext
from docuharnessx.stages.base import NoOpStage
from docuharnessx.stages.ingest import (
    STAGE_NAME,
    IngestStage,
    make_ingest_stage,
)
from docuharnessx.types import SLOT_FILE_INVENTORY


# --------------------------------------------------------------------------- #
# Sync drivers + a recording tracer                                            #
# --------------------------------------------------------------------------- #


def _drive_process(processor: Processor, event: object) -> list[object]:
    """Run a Processor's async ``process`` generator to completion synchronously."""

    async def _collect() -> list[object]:
        return [out async for out in processor.process(event)]

    return asyncio.run(_collect())


def _drive_hook(gen) -> list[object]:
    """Run an async-generator hook (``on_task_start``/``on_step_end``) to completion.

    Driven directly so a fatal :class:`IngestError` raised inside the hook
    propagates (``process`` would otherwise swallow it).
    """

    async def _collect() -> list[object]:
        return [out async for out in gen]

    return asyncio.run(_collect())


class _RecordingTracer:
    """Minimal tracer capturing every event a stage emits to the journal.

    Mirrors the run-tracer surface ``NoOpStage`` reaches via ``_resolve_tracer``
    (a ``tracer`` with an async ``on_event``), so a directly-driven stage can have
    its participation/summary record captured without a live harness.
    """

    def __init__(self) -> None:
        self.events: list[object] = []

    async def on_event(self, event: object) -> None:
        self.events.append(event)


class _Runtime:
    """A stand-in for the live ``_HarnessRuntime`` carrying just the tracer."""

    def __init__(self, tracer: object) -> None:
        self.tracer = tracer


def _step_end_event() -> StepEndEvent:
    return StepEndEvent(run_id="run-ingest", step_id=1)


def _task_start_event(state: State) -> TaskStartEvent:
    return TaskStartEvent(run_id="run-ingest", step_id=0, state=state)


def _bind_state(stage: IngestStage, state: State, tracer: object | None = None) -> None:
    """Drive ``on_task_start`` so the stage captures the live run ``State``.

    Optionally binds a runtime/tracer the way ``Harness.__init__`` would, so the
    stage's participation/summary record is captured.
    """
    if tracer is not None:
        stage._bind_runtime(_Runtime(tracer))
    _drive_hook(stage.on_task_start(_task_start_event(state)))


def _make_repo(tmp_path) -> str:
    """Write a tiny, deterministic fixture repo and return its path."""
    (tmp_path / "main.go").write_text(
        "package main\n\nfunc main() {\n\tprintln(\"hi\")\n}\n"
    )
    (tmp_path / "README.md").write_text("# demo\n")
    sub = tmp_path / "internal"
    sub.mkdir()
    (sub / "util.go").write_text("package internal\n\nfunc Helper() {}\n")
    return str(tmp_path)


# --------------------------------------------------------------------------- #
# Harness-contract stability (Req 8.1)                                         #
# --------------------------------------------------------------------------- #


def test_stage_name_is_stable() -> None:
    assert STAGE_NAME == "ingest"
    assert IngestStage.stage_name == "ingest"


def test_factory_returns_ingest_processor() -> None:
    proc = make_ingest_stage()
    assert isinstance(proc, Processor)
    assert isinstance(proc, IngestStage)
    assert "ingest" in type(proc).__name__.lower()


def test_factory_returns_fresh_instances() -> None:
    assert make_ingest_stage() is not make_ingest_stage()


def test_ingest_stage_subclasses_the_noop_base() -> None:
    # The real stage keeps the base participation/journaling lifecycle.
    assert issubclass(IngestStage, NoOpStage)


def test_module_path_is_stable() -> None:
    assert IngestStage.__module__ == "docuharnessx.stages.ingest"


# --------------------------------------------------------------------------- #
# Real scan + handoff publication (Req 1.1, 1.7)                               #
# --------------------------------------------------------------------------- #


def test_valid_repo_populates_file_inventory_slot(tmp_path) -> None:
    repo = _make_repo(tmp_path)
    state = State(run_id="run-ingest")
    RunContext(state).set_target_repo(repo)

    stage = make_ingest_stage()
    _bind_state(stage, state)

    event = _step_end_event()
    out = _drive_hook(stage.on_step_end(event))

    # Pure pass-through on the content-free lifecycle event.
    assert len(out) == 1
    assert out[0] is event

    inventory = RunContext(state).file_inventory()
    assert isinstance(inventory, FileInventory)
    # The fixture's three source/doc files are all present, sorted by path.
    paths = [e.path for e in inventory.entries]
    assert paths == sorted(paths)
    assert "main.go" in paths
    assert "README.md" in paths
    assert "internal/util.go" in paths
    # Provenance: the inventory records the scanned root realpath.
    assert inventory.repo_path == os.path.realpath(repo)


def test_scan_is_deterministic_across_two_runs(tmp_path) -> None:
    repo = _make_repo(tmp_path)

    def _scan_once() -> FileInventory:
        state = State(run_id="run-ingest")
        RunContext(state).set_target_repo(repo)
        stage = make_ingest_stage()
        _bind_state(stage, state)
        _drive_hook(stage.on_step_end(_step_end_event()))
        return RunContext(state).file_inventory()

    first = _scan_once()
    second = _scan_once()
    assert first == second


# --------------------------------------------------------------------------- #
# Journal: participation + bounded scan summary (Req 8.2, 8.3, 10.1, 10.3)     #
# --------------------------------------------------------------------------- #


def test_emits_participation_trigger_with_bounded_summary(tmp_path) -> None:
    repo = _make_repo(tmp_path)
    state = State(run_id="run-ingest")
    RunContext(state).set_target_repo(repo)

    tracer = _RecordingTracer()
    stage = make_ingest_stage()
    _bind_state(stage, state, tracer=tracer)

    _drive_hook(stage.on_step_end(_step_end_event()))

    triggers = [e for e in tracer.events if isinstance(e, ProcessorTriggerEvent)]
    assert len(triggers) == 1
    trigger = triggers[0]
    assert trigger.processor == "IngestStage"
    assert trigger.action == "stage_participated"

    detail = trigger.detail
    assert detail["stage"] == "ingest"
    # A bounded scan summary — counts + primary language + limit flag (Req 10.1).
    assert detail["files"] == 3
    assert detail["primary_language"] == "Go"
    assert detail["limit_reached"] is False
    # The full inventory must NOT be written to the trace (Req 10.3): only
    # summary-level scalar fields, never the entries themselves.
    for value in detail.values():
        assert isinstance(value, (str, int, bool))


# --------------------------------------------------------------------------- #
# Fatal preconditions raise IngestError, no partial inventory (Req 1.2, 8.4)   #
# --------------------------------------------------------------------------- #


def test_unset_repo_slot_raises_ingest_error() -> None:
    state = State(run_id="run-ingest")  # no target repo set
    stage = make_ingest_stage()
    _bind_state(stage, state)

    with pytest.raises(IngestError):
        _drive_hook(stage.on_step_end(_step_end_event()))

    # No partial inventory was published.
    assert RunContext(state).file_inventory() is None


def test_nonexistent_path_raises_ingest_error(tmp_path) -> None:
    missing = str(tmp_path / "does-not-exist")
    state = State(run_id="run-ingest")
    RunContext(state).set_target_repo(missing)
    stage = make_ingest_stage()
    _bind_state(stage, state)

    with pytest.raises(IngestError) as excinfo:
        _drive_hook(stage.on_step_end(_step_end_event()))
    # The message names the offending path so the cause is identifiable.
    assert missing in str(excinfo.value)
    assert RunContext(state).file_inventory() is None


def test_file_path_not_a_directory_raises_ingest_error(tmp_path) -> None:
    a_file = tmp_path / "a-file.txt"
    a_file.write_text("not a dir\n")
    state = State(run_id="run-ingest")
    RunContext(state).set_target_repo(str(a_file))
    stage = make_ingest_stage()
    _bind_state(stage, state)

    with pytest.raises(IngestError):
        _drive_hook(stage.on_step_end(_step_end_event()))
    assert RunContext(state).file_inventory() is None


# --------------------------------------------------------------------------- #
# task_start capture is a transparent pass-through                             #
# --------------------------------------------------------------------------- #


def test_task_start_is_pass_through() -> None:
    state = State(run_id="run-ingest")
    stage = make_ingest_stage()
    event = _task_start_event(state)
    out = _drive_hook(stage.on_task_start(event))
    assert len(out) == 1
    assert out[0] is event


def test_task_start_via_process_still_passes_through() -> None:
    # Through the full MultiHookProcessor dispatch, on_task_start must remain a
    # transparent pass-through (the stage only captures state; it changes nothing).
    state = State(run_id="run-ingest")
    stage = make_ingest_stage()
    event = _task_start_event(state)
    out = _drive_process(stage, event)
    assert len(out) == 1
    assert out[0] is event
    # And the live state was captured for on_step_end to use.
    assert stage._run_state is state
