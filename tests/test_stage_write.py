"""Tests for the real Write stage adapter shell (cobesy-writer task 3.1).

Task 3.1 replaces the no-op ``write`` stub with a thin HarnessX adapter over the pure
composition core, keeping ``STAGE_NAME``/``WriteStage``/``make_write_stage`` and the
module path stable so the stage registry and ``make_docgen`` need no edits (Req 1.1).
The adapter:

* subclasses :class:`~docuharnessx.stages.base.NoOpStage` and attaches to
  :data:`PIPELINE_HOOK` (Req 1.2);
* captures the live run ``State`` in ``on_task_start`` (a pure pass-through), does its
  work in ``on_step_end``, and yields the lifecycle event unchanged (Req 1.4);
* driven outside a harness (no bound ``State``) forwards the event and writes nothing
  (Req 1.3);
* with a bound ``State`` reads the four input slots through the typed ``RunContext``
  accessors, pins ``COVERAGE_PLAN_SCHEMA_VERSION``, and raises :class:`WriterInputError`
  naming the cause on an unsupported plan version or a missing plan/vocabulary/store
  slot, producing no partial output (Req 2.1-2.4).

These tests pin only the **adapter shell + input boundary** (task 3.1). The per-segment
write orchestration and the ``SLOT_WRITTEN_SEGMENTS`` publishing land in task 3.2; this
suite intentionally does not assert stored segments.

Harness-free, like ``tests/test_stage_plan.py``: ``on_step_end`` is driven directly with
a tiny runtime stub bound via ``_bind_runtime``, and ``on_task_start`` with a
``TaskStartEvent`` carrying the run ``State``. No credentials, no network.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from typing import Any

import pytest

from harnessx.core.events import StepEndEvent, TaskStartEvent
from harnessx.core.processor import Processor
from harnessx.core.state import State

from docuharnessx.composition import WriterInputError
from docuharnessx.context import RunContext
from docuharnessx.ontology import default_profile
from docuharnessx.planning import COVERAGE_PLAN_SCHEMA_VERSION, CoveragePlan
from docuharnessx.stages.base import NoOpStage, PIPELINE_HOOK
from docuharnessx.stages.write import (
    STAGE_NAME,
    WriteStage,
    make_noop_stage,
    make_write_stage,
)
from tests._fakes import FakeProvider


# --------------------------------------------------------------------------- #
# Harness-free drivers + a minimal runtime / model-config stub                 #
# --------------------------------------------------------------------------- #


@dataclass
class _CapturingTracer:
    events: list[Any]

    def __init__(self) -> None:
        self.events = []

    async def on_event(self, event: Any) -> None:
        self.events.append(event)


class _RuntimeStub:
    def __init__(self, tracer: _CapturingTracer | None) -> None:
        self.tracer = tracer


class _ModelConfigStub:
    """A ``ModelConfig`` stand-in exposing a ``main`` provider (mirrors PlanStage)."""

    def __init__(self, main: Any) -> None:
        self.main = main


def _sample_event() -> StepEndEvent:
    return StepEndEvent(
        run_id="run-write",
        step_id=7,
        step_summary="prior summary",
        tool_call_summary="readFile(a)",
        cumulative_tokens=10,
        cumulative_cost_usd=0.1,
    )


def _drive(stage: Processor, event: StepEndEvent) -> list[Any]:
    async def _collect() -> list[Any]:
        return [out async for out in stage.on_step_end(event)]

    return asyncio.run(_collect())


def _start_task(stage: WriteStage, state: State) -> None:
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
    model: Any | None = None,
) -> WriteStage:
    stage = WriteStage()
    stage._bind_runtime(_RuntimeStub(tracer))
    if model is not None:
        stage._bind_model_config(_ModelConfigStub(model))
    _start_task(stage, state)
    return stage


# --------------------------------------------------------------------------- #
# Fixtures: a minimal valid CoveragePlan + a store handle                       #
# --------------------------------------------------------------------------- #


class _InMemoryStore:
    """A tiny SegmentStore-shaped handle (only ``put`` exercised here)."""

    def __init__(self) -> None:
        self.put_calls: list[Any] = []

    def put(self, segment: Any) -> None:  # pragma: no cover - not driven in 3.1
        self.put_calls.append(segment)


def _empty_plan() -> CoveragePlan:
    return CoveragePlan(
        schema_version=COVERAGE_PLAN_SCHEMA_VERSION,
        repo_path="/repo/x",
        vocabulary_fingerprint="fp",
        segments=(),
    )


def _state_with_inputs(
    *,
    plan: CoveragePlan | None,
    with_vocab: bool = True,
    with_store: bool = True,
) -> State:
    """A run State pre-loaded with the writer's input slots (selectively present)."""
    state = State(run_id="r-write")
    rc = RunContext(state)
    if plan is not None:
        rc.set_coverage_plan(plan)
    if with_vocab:
        rc.set_vocabulary(default_profile())
    if with_store:
        rc.set_segment_store(_InMemoryStore())
    return state


# --------------------------------------------------------------------------- #
# Contract stability (Req 1.1): names/factory/module path/hook unchanged        #
# --------------------------------------------------------------------------- #


def test_stage_name_is_stable() -> None:
    assert STAGE_NAME == "write"
    assert WriteStage.stage_name == "write"


def test_factory_returns_a_fresh_write_stage() -> None:
    proc = make_write_stage()
    assert isinstance(proc, Processor)
    assert isinstance(proc, WriteStage)
    assert make_write_stage() is not make_write_stage()


def test_write_stage_subclasses_noop_base_on_pipeline_hook() -> None:
    assert issubclass(WriteStage, NoOpStage)
    assert WriteStage._hook == PIPELINE_HOOK


def test_module_path_is_stable() -> None:
    assert WriteStage.__module__ == "docuharnessx.stages.write"


def test_module_still_reexports_shared_noop_factory() -> None:
    from docuharnessx.stages import base as base_module

    assert make_noop_stage is base_module.make_noop_stage


def test_all_is_stable() -> None:
    import docuharnessx.stages.write as write_module

    assert set(write_module.__all__) == {
        "STAGE_NAME",
        "WriteStage",
        "make_write_stage",
        "make_noop_stage",
    }


# --------------------------------------------------------------------------- #
# Driven outside a harness: graceful content-neutral pass-through (Req 1.3)     #
# --------------------------------------------------------------------------- #


def test_pass_through_when_no_runtime_bound() -> None:
    stage = WriteStage()  # never bound, no task_start
    event = _sample_event()

    async def _collect() -> list[Any]:
        return [out async for out in stage.process(event)]

    out = asyncio.run(_collect())
    assert len(out) == 1
    assert out[0] is event  # same object, no mutation


def test_pass_through_writes_nothing_without_state() -> None:
    stage = WriteStage()
    out = _drive(stage, _sample_event())
    assert len(out) == 1


# --------------------------------------------------------------------------- #
# Event forwarded unchanged with a bound, valid state (Req 1.4)                 #
# --------------------------------------------------------------------------- #


def test_event_forwarded_unchanged_on_valid_inputs() -> None:
    state = _state_with_inputs(plan=_empty_plan())
    stage = _bound_stage(state)
    event = _sample_event()
    out = _drive(stage, event)
    assert len(out) == 1
    assert out[0] is event


def test_empty_plan_completes_without_error() -> None:
    # An empty plan is a valid, well-formed input: the stage must not raise (Req 6.5).
    state = _state_with_inputs(plan=_empty_plan())
    stage = _bound_stage(state)
    out = _drive(stage, _sample_event())
    assert len(out) == 1


def test_valid_inputs_with_fake_provider_do_not_raise() -> None:
    # A bound (fake) model must not change the input-boundary behavior (credential-free).
    state = _state_with_inputs(plan=_empty_plan())
    stage = _bound_stage(state, model=FakeProvider())
    out = _drive(stage, _sample_event())
    assert len(out) == 1


# --------------------------------------------------------------------------- #
# Input errors halt the run with an identifiable cause (Req 2.2-2.4)            #
# --------------------------------------------------------------------------- #


def test_missing_coverage_plan_raises_writer_input_error() -> None:
    state = _state_with_inputs(plan=None)  # vocab + store present, no plan
    stage = _bound_stage(state)
    with pytest.raises(WriterInputError) as excinfo:
        _drive(stage, _sample_event())
    assert "coverage_plan" in str(excinfo.value).lower()


def test_missing_vocabulary_raises_writer_input_error() -> None:
    state = _state_with_inputs(plan=_empty_plan(), with_vocab=False)
    stage = _bound_stage(state)
    with pytest.raises(WriterInputError) as excinfo:
        _drive(stage, _sample_event())
    assert "vocabulary" in str(excinfo.value).lower()


def test_missing_segment_store_raises_writer_input_error() -> None:
    state = _state_with_inputs(plan=_empty_plan(), with_store=False)
    stage = _bound_stage(state)
    with pytest.raises(WriterInputError) as excinfo:
        _drive(stage, _sample_event())
    assert "store" in str(excinfo.value).lower()


def test_unsupported_plan_version_raises_writer_input_error() -> None:
    bad_plan = replace(_empty_plan(), schema_version=COVERAGE_PLAN_SCHEMA_VERSION + 99)
    state = _state_with_inputs(plan=bad_plan)
    stage = _bound_stage(state)
    with pytest.raises(WriterInputError) as excinfo:
        _drive(stage, _sample_event())
    msg = str(excinfo.value)
    # The message names the offending version so the run halts with a clear cause.
    assert str(COVERAGE_PLAN_SCHEMA_VERSION + 99) in msg


def test_missing_plan_produces_no_partial_output() -> None:
    state = _state_with_inputs(plan=None)
    stage = _bound_stage(state)
    with pytest.raises(WriterInputError):
        _drive(stage, _sample_event())
    # No written-segments seam published on the fatal input path (no partial output).
    assert RunContext(state).written_segments() is None


# --------------------------------------------------------------------------- #
# Model access mirrors PlanStage._relevance_model (named per-instance attr)     #
# --------------------------------------------------------------------------- #


def test_writer_model_returns_none_without_model_config() -> None:
    stage = WriteStage()  # no _bind_model_config
    assert stage._writer_model() is None


def test_writer_model_returns_bound_main_provider() -> None:
    stage = WriteStage()
    provider = FakeProvider()
    stage._bind_model_config(_ModelConfigStub(provider))
    assert stage._writer_model() is provider


def test_writer_model_degrades_to_none_on_broken_config() -> None:
    class _Broken:
        @property
        def main(self) -> Any:
            raise RuntimeError("boom")

    stage = WriteStage()
    stage._bind_model_config(_Broken())
    # A misconfigured model must never gate the writer — degrade to None.
    assert stage._writer_model() is None
