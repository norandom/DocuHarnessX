"""Tests for the bounded Write-stage journal summary (cobesy-writer task 3.3).

Task 3.3 makes :meth:`WriteStage.on_step_end` emit a single, bounded
``ProcessorTriggerEvent`` to the run tracer (reusing the ``NoOpStage`` tracer
resolution) carrying a *summary-level* detail only: the stage name, ``total_planned``,
``written_count``, ``flagged_count``, a *capped* list of the top-priority written segment
ids, and a ``prose_source`` marker (``model``/``fallback``/``fake``). It never includes
full segment bodies/segments, and it is a no-op when no tracer is bound (Req 8.1-8.3).

These tests are credential-free and harness-free: ``on_step_end`` is driven directly with
a tiny capturing-tracer runtime stub bound via ``_bind_runtime`` (exactly like
``tests/test_stage_write_orchestration.py``). No network, no real model.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from harnessx.core.events import ProcessorTriggerEvent, StepEndEvent, TaskStartEvent
from harnessx.core.state import State

from docuharnessx.composition import segment_id
from docuharnessx.context import RunContext
from docuharnessx.ontology import (
    InMemorySegmentStore,
    Subject,
    default_profile,
)
from docuharnessx.planning import COVERAGE_PLAN_SCHEMA_VERSION, CoveragePlan
from docuharnessx.planning.model import EvidenceRef, PlannedSegment
from docuharnessx.stages.base import STAGE_PARTICIPATION_ACTION
from docuharnessx.stages.write import STAGE_NAME, WriteStage


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
    def __init__(self, main: Any) -> None:
        self.main = main


class _RecordingModel:
    """A duck-typed provider whose ``complete`` returns a canned content string."""

    def __init__(self, content: Any) -> None:
        self._content = content
        self.calls = 0

    async def complete(
        self, messages: Any, tools: Any, stream_callback: Any = None
    ) -> Any:
        self.calls += 1

        class _Resp:
            content = self._content

        return _Resp()

    def count_tokens(self, messages: Any) -> int:
        return 1


def _sample_event() -> StepEndEvent:
    return StepEndEvent(
        run_id="run-write",
        step_id=7,
        step_summary="prior summary",
        tool_call_summary="readFile(a)",
        cumulative_tokens=10,
        cumulative_cost_usd=0.1,
    )


def _drive(stage: WriteStage, event: StepEndEvent) -> list[Any]:
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
# Fixtures: realistic planned segments + plans + a real InMemorySegmentStore    #
# --------------------------------------------------------------------------- #


def _planned(
    *,
    key: str,
    roles: tuple[str, ...],
    intent: str,
    subject_local: str,
    priority: int,
    evidence: tuple[EvidenceRef, ...] = (),
) -> PlannedSegment:
    return PlannedSegment(
        segment_key=key,
        roles=roles,
        intent=intent,
        subjects=(Subject(prefix="component", local=subject_local),),
        priority=priority,
        evidence=evidence,
    )


def _valid_segments() -> tuple[PlannedSegment, ...]:
    return (
        _planned(
            key="developer__extend__component-scanner",
            roles=("developer",),
            intent="extend",
            subject_local="scanner",
            priority=20,
            evidence=(EvidenceRef(kind="entrypoint", detail="scanner/registry.py"),),
        ),
        _planned(
            key="contributor__contribute__component-core",
            roles=("contributor",),
            intent="contribute",
            subject_local="core",
            priority=10,
        ),
    )


def _plan(segments: tuple[PlannedSegment, ...]) -> CoveragePlan:
    return CoveragePlan(
        schema_version=COVERAGE_PLAN_SCHEMA_VERSION,
        repo_path="/repo/x",
        vocabulary_fingerprint="fp",
        segments=segments,
    )


def _state_with(
    plan: CoveragePlan,
    *,
    store: InMemorySegmentStore | None = None,
) -> tuple[State, InMemorySegmentStore]:
    vocab = default_profile()
    store = store if store is not None else InMemorySegmentStore(vocab)
    state = State(run_id="r-write")
    rc = RunContext(state)
    rc.set_coverage_plan(plan)
    rc.set_vocabulary(vocab)
    rc.set_segment_store(store)
    return state, store


def _triggers(tracer: _CapturingTracer) -> list[ProcessorTriggerEvent]:
    return [e for e in tracer.events if isinstance(e, ProcessorTriggerEvent)]


def _write_trigger(tracer: _CapturingTracer) -> ProcessorTriggerEvent:
    triggers = [
        e
        for e in _triggers(tracer)
        if e.action == STAGE_PARTICIPATION_ACTION
        and e.detail.get("stage") == STAGE_NAME
    ]
    assert len(triggers) == 1, f"expected exactly one Write trigger, got {triggers!r}"
    return triggers[0]


# --------------------------------------------------------------------------- #
# Records one bounded Write-stage trigger with the counts (Req 8.1, 8.2)        #
# --------------------------------------------------------------------------- #


def test_records_one_bounded_write_trigger_with_counts() -> None:
    plan = _plan(_valid_segments())
    state, _store = _state_with(plan)
    tracer = _CapturingTracer()
    stage = _bound_stage(state, tracer=tracer)

    _drive(stage, _sample_event())

    trigger = _write_trigger(tracer)
    # It is a real participation trigger bound to the pipeline hook + this processor.
    assert trigger.processor == "WriteStage"
    assert trigger.run_id == "run-write"
    assert trigger.step_id == 7

    detail = trigger.detail
    assert detail["stage"] == STAGE_NAME
    assert detail["total_planned"] == len(plan.segments)
    assert detail["written_count"] == len(plan.segments)
    assert detail["flagged_count"] == 0


def test_top_written_ids_are_capped_and_in_plan_order() -> None:
    # More segments than the cap so the list is genuinely truncated.
    segs = tuple(
        _planned(
            key=f"developer__extend__component-mod{i:02d}",
            roles=("developer",),
            intent="extend",
            subject_local=f"mod{i:02d}",
            priority=100 - i,
        )
        for i in range(10)
    )
    plan = _plan(segs)
    state, _store = _state_with(plan)
    tracer = _CapturingTracer()
    stage = _bound_stage(state, tracer=tracer)

    _drive(stage, _sample_event())

    written = RunContext(state).written_segments()
    detail = _write_trigger(tracer).detail
    top_ids = detail["top_written_ids"]

    assert isinstance(top_ids, list)
    # Capped: never the full written list for a large plan.
    assert 0 < len(top_ids) < len(written.segments)
    # The head of the (priority-desc) written set, in order.
    expected_head = [s.id for s in written.segments][: len(top_ids)]
    assert top_ids == expected_head
    # Each id is a deterministic, plan-derived segment id (not a full body).
    assert top_ids[0] == segment_id(segs[0])


def test_journal_detail_carries_no_full_bodies() -> None:
    plan = _plan(_valid_segments())
    state, _store = _state_with(plan)
    tracer = _CapturingTracer()
    stage = _bound_stage(state, tracer=tracer)

    _drive(stage, _sample_event())

    written = RunContext(state).written_segments()
    detail = _write_trigger(tracer).detail

    # Every value is scalar / a short list of scalars — no Segment objects, no bodies.
    bodies = {s.body for s in written.segments}
    assert bodies  # the run did produce bodies
    serialized = repr(detail)
    for body in bodies:
        assert body not in serialized
    # No nested Segment/ProseResult objects leaked into the detail.
    for value in detail.values():
        if isinstance(value, list):
            assert all(isinstance(item, str) for item in value)
        else:
            assert isinstance(value, (str, int, bool))


# --------------------------------------------------------------------------- #
# prose_source marker: fallback / fake / model (Req 8.3)                        #
# --------------------------------------------------------------------------- #


def test_prose_source_marker_is_fallback_when_no_model() -> None:
    plan = _plan(_valid_segments())
    state, _store = _state_with(plan)
    tracer = _CapturingTracer()
    stage = _bound_stage(state, tracer=tracer)  # no model bound at all

    _drive(stage, _sample_event())

    assert _write_trigger(tracer).detail["prose_source"] == "fallback"


def test_prose_source_marker_is_model_for_clean_response() -> None:
    plan = _plan(_valid_segments())
    state, _store = _state_with(plan)
    tracer = _CapturingTracer()
    model = _RecordingModel("# A real body\n\nGenerated prose from the model.")
    stage = _bound_stage(state, tracer=tracer, model=model)

    _drive(stage, _sample_event())

    assert _write_trigger(tracer).detail["prose_source"] == "model"


def test_prose_source_marker_is_fake_when_model_response_unusable() -> None:
    plan = _plan(_valid_segments())
    state, _store = _state_with(plan)
    tracer = _CapturingTracer()
    # A bound model whose response is empty -> generate_prose returns None -> the
    # deterministic fallback renders with source="fake" (a model *was* consulted).
    model = _RecordingModel("   \n  ")
    stage = _bound_stage(state, tracer=tracer, model=model)

    _drive(stage, _sample_event())

    assert _write_trigger(tracer).detail["prose_source"] == "fake"


# --------------------------------------------------------------------------- #
# Flagged segments are counted; empty plan still journals (Req 8.1, 8.2)        #
# --------------------------------------------------------------------------- #


def test_flagged_count_is_recorded() -> None:
    invalid = _planned(
        key="ghost__extend__component-scanner",
        roles=("not-a-real-role",),
        intent="extend",
        subject_local="scanner",
        priority=30,
    )
    valid = _valid_segments()[1]
    plan = _plan((invalid, valid))
    state, _store = _state_with(plan)
    tracer = _CapturingTracer()
    stage = _bound_stage(state, tracer=tracer)

    _drive(stage, _sample_event())

    detail = _write_trigger(tracer).detail
    assert detail["total_planned"] == 2
    assert detail["written_count"] == 1
    assert detail["flagged_count"] == 1
    # The flagged segment is not surfaced as a "written" id.
    assert segment_id(invalid) not in detail["top_written_ids"]


def test_empty_plan_still_records_a_bounded_trigger() -> None:
    plan = _plan(())
    state, _store = _state_with(plan)
    tracer = _CapturingTracer()
    stage = _bound_stage(state, tracer=tracer)

    _drive(stage, _sample_event())

    detail = _write_trigger(tracer).detail
    assert detail["total_planned"] == 0
    assert detail["written_count"] == 0
    assert detail["flagged_count"] == 0
    assert detail["top_written_ids"] == []
    # No prose was generated at all; the marker is the model-less default.
    assert detail["prose_source"] == "fallback"


# --------------------------------------------------------------------------- #
# No tracer bound: no journal emission, no error (Req 8.1)                       #
# --------------------------------------------------------------------------- #


def test_no_op_when_no_tracer_is_bound() -> None:
    plan = _plan(_valid_segments())
    state, _store = _state_with(plan)
    stage = _bound_stage(state)  # runtime bound with tracer=None

    out = _drive(stage, _sample_event())
    assert len(out) == 1  # event still forwarded unchanged, no raise


def test_no_op_when_no_runtime_bound_at_all() -> None:
    plan = _plan(_valid_segments())
    state, _store = _state_with(plan)
    stage = WriteStage()  # never _bind_runtime'd
    _start_task(stage, state)

    out = _drive(stage, _sample_event())
    assert len(out) == 1  # forwarded unchanged, journal is a graceful no-op
