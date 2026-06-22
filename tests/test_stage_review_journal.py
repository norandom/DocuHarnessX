"""Tests for the bounded Review-stage journal summary (quality-review-gate task 4.2).

Task 4.2 makes :meth:`ReviewStage.on_step_end` emit a single, bounded
``ProcessorTriggerEvent`` to the run tracer (reusing the ``NoOpStage`` tracer
resolution) carrying a *summary-level* detail only: the stage name, the ``judged``,
``accepted``, ``rejected``, and ``unavailable`` counts, a *capped* list of the
top-priority accepted segment ids, and a ``judge_source`` breakdown marker
(``model``/``fake``/``unavailable`` -> count). It never includes full segment bodies or
full judge prose, and it is a no-op when no tracer is bound (Req 9.1-9.3).

These tests are credential-free and harness-free: ``on_step_end`` is driven directly with
a tiny capturing-tracer runtime stub bound via ``_bind_runtime`` (exactly like
``tests/test_stage_write_journal.py``). The review-input slots are seeded on a real run
``State`` and captured through :meth:`ReviewStage.on_task_start`. No network, no real
model resolver: a model is bound only via the in-test duck-typed provider stub.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any

from harnessx.core.events import ProcessorTriggerEvent, StepEndEvent, TaskStartEvent
from harnessx.core.state import State

from docuharnessx.composition import segment_id
from docuharnessx.context import RunContext
from docuharnessx.ontology import (
    InMemorySegmentStore,
    Segment,
    Subject,
    default_profile,
)
from docuharnessx.planning import COVERAGE_PLAN_SCHEMA_VERSION, CoveragePlan
from docuharnessx.planning.model import EvidenceRef, PlannedSegment
from docuharnessx.review import COBESY_CRITERIA
from docuharnessx.stages.base import STAGE_PARTICIPATION_ACTION
from docuharnessx.stages.review import STAGE_NAME, ReviewStage


# --------------------------------------------------------------------------- #
# Harness-free drivers + a minimal runtime / model-config / provider stub       #
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


def _passing_verdict_json() -> str:
    """A clean, passing per-criterion JSON verdict the deterministic parser accepts."""
    return json.dumps(
        {
            "criteria": {
                name: {"score": 1.0, "passed": True, "reason": "ok"}
                for name in COBESY_CRITERIA
            },
            "passed": True,
            "reason": "all criteria met",
        }
    )


class _PassingJudge:
    """A duck-typed provider whose ``complete`` returns a passing COBESY verdict."""

    def __init__(self) -> None:
        self.calls = 0

    async def complete(
        self, messages: Any, tools: Any, stream_callback: Any = None
    ) -> Any:
        self.calls += 1

        class _Resp:
            content = _passing_verdict_json()

        return _Resp()

    def count_tokens(self, messages: Any) -> int:
        return 1


def _sample_event() -> StepEndEvent:
    return StepEndEvent(
        run_id="run-review",
        step_id=9,
        step_summary="prior summary",
        tool_call_summary="readFile(a)",
        cumulative_tokens=10,
        cumulative_cost_usd=0.1,
    )


def _drive(stage: ReviewStage, event: StepEndEvent) -> list[Any]:
    async def _collect() -> list[Any]:
        return [out async for out in stage.on_step_end(event)]

    return asyncio.run(_collect())


def _start_task(stage: ReviewStage, state: State) -> None:
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
) -> ReviewStage:
    stage = ReviewStage()
    stage._bind_runtime(_RuntimeStub(tracer))
    if model is not None:
        stage._bind_model_config(_ModelConfigStub(model))
    _start_task(stage, state)
    return stage


# --------------------------------------------------------------------------- #
# Fixtures: realistic written segments + plan + a real InMemorySegmentStore     #
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


def _valid_planned() -> tuple[PlannedSegment, ...]:
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


def _segment_for(planned: PlannedSegment) -> Segment:
    """A wired ontology Segment matching a planned segment (same id the writer derives).

    Mirrors :func:`docuharnessx.composition.wiring.wire_segment`: the non-body fields are
    copied from ``planned`` (fresh ``roles``/``subjects`` lists of the typed values) and the
    id is the deterministic :func:`segment_id` the writer derives.
    """
    return Segment(
        id=segment_id(planned),
        title=f"{planned.intent} {planned.subjects[0].local}",
        roles=list(planned.roles),
        subjects=list(planned.subjects),  # the typed Subject values, like wire_segment
        intent=planned.intent,
        summary=f"Summary for {planned.subjects[0].local}.",
        related=[],
        body=f"# Body for {planned.subjects[0].local}\n\nDetailed prose grounding.",
    )


def _seed_state(
    planned: tuple[PlannedSegment, ...],
) -> tuple[State, InMemorySegmentStore, list[Segment]]:
    """Seed a run State with a written set + plan + vocab + store the Review stage reads."""
    vocab = default_profile()
    store = InMemorySegmentStore(vocab)
    segments = [_segment_for(p) for p in planned]
    for seg in segments:
        store.put(seg)

    state = State(run_id="run-review")
    rc = RunContext(state)
    rc.set_coverage_plan(_plan(planned))
    rc.set_vocabulary(vocab)
    rc.set_segment_store(store)

    # Publish the written set directly (the boundary under test is the Review stage; the
    # writer is faithfully simulated by the wired segments seeded into the store).
    from docuharnessx.composition.model import WrittenSegments

    rc.set_written_segments(
        WrittenSegments(
            segments=tuple(segments),
            flags=(),
            total_planned=len(planned),
        )
    )
    return state, store, segments


def _triggers(tracer: _CapturingTracer) -> list[ProcessorTriggerEvent]:
    return [e for e in tracer.events if isinstance(e, ProcessorTriggerEvent)]


def _review_trigger(tracer: _CapturingTracer) -> ProcessorTriggerEvent:
    triggers = [
        e
        for e in _triggers(tracer)
        if e.action == STAGE_PARTICIPATION_ACTION
        and e.detail.get("stage") == STAGE_NAME
    ]
    assert len(triggers) == 1, f"expected exactly one Review trigger, got {triggers!r}"
    return triggers[0]


# --------------------------------------------------------------------------- #
# Records one bounded Review-stage trigger with the four counts (Req 9.1, 9.2)  #
# --------------------------------------------------------------------------- #


def test_records_one_bounded_review_trigger_with_counts() -> None:
    state, _store, segments = _seed_state(_valid_planned())
    tracer = _CapturingTracer()
    stage = _bound_stage(state, tracer=tracer, model=_PassingJudge())

    _drive(stage, _sample_event())

    trigger = _review_trigger(tracer)
    # A real participation trigger bound to the pipeline hook + this processor.
    assert trigger.processor == "ReviewStage"
    assert trigger.run_id == "run-review"
    assert trigger.step_id == 9

    detail = trigger.detail
    assert detail["stage"] == STAGE_NAME
    assert detail["judged"] == len(segments)
    assert detail["accepted"] == len(segments)  # passing judge accepts all
    assert detail["rejected"] == 0
    assert detail["unavailable"] == 0


def test_counts_match_published_report_aggregate() -> None:
    state, _store, segments = _seed_state(_valid_planned())
    tracer = _CapturingTracer()
    stage = _bound_stage(state, tracer=tracer, model=_PassingJudge())

    _drive(stage, _sample_event())

    report = RunContext(state).review_report()
    detail = _review_trigger(tracer).detail
    # The bounded summary counts are exactly the published aggregate counts.
    assert detail["judged"] == report.aggregate.judged
    assert detail["accepted"] == report.aggregate.accepted
    assert detail["rejected"] == report.aggregate.rejected
    assert detail["unavailable"] == report.aggregate.unavailable


# --------------------------------------------------------------------------- #
# Capped top-priority accepted ids, in written/accepted order (Req 9.2)         #
# --------------------------------------------------------------------------- #


def test_top_accepted_ids_are_capped_and_in_accepted_order() -> None:
    # More accepted segments than the cap so the list is genuinely truncated.
    planned = tuple(
        _planned(
            key=f"developer__extend__component-mod{i:02d}",
            roles=("developer",),
            intent="extend",
            subject_local=f"mod{i:02d}",
            priority=100 - i,
        )
        for i in range(10)
    )
    state, _store, segments = _seed_state(planned)
    tracer = _CapturingTracer()
    stage = _bound_stage(state, tracer=tracer, model=_PassingJudge())

    _drive(stage, _sample_event())

    report = RunContext(state).review_report()
    top_ids = _review_trigger(tracer).detail["top_accepted_ids"]

    assert isinstance(top_ids, list)
    # Capped: never the full accepted list for a large run.
    assert 0 < len(top_ids) < len(report.accepted)
    # The head of the accepted (written-order) set, in order.
    expected_head = [s.id for s in report.accepted][: len(top_ids)]
    assert top_ids == expected_head
    assert top_ids[0] == segment_id(planned[0])


def test_top_accepted_ids_empty_when_nothing_accepted() -> None:
    # No model bound -> fail-closed default-reject for every segment -> empty accepted set.
    state, _store, segments = _seed_state(_valid_planned())
    tracer = _CapturingTracer()
    stage = _bound_stage(state, tracer=tracer)  # no model

    _drive(stage, _sample_event())

    detail = _review_trigger(tracer).detail
    assert detail["accepted"] == 0
    assert detail["rejected"] == len(segments)
    assert detail["unavailable"] == len(segments)
    assert detail["top_accepted_ids"] == []


# --------------------------------------------------------------------------- #
# judge_source breakdown marker (Req 9.3)                                       #
# --------------------------------------------------------------------------- #


def test_judge_source_breakdown_is_model_when_passing_judge() -> None:
    state, _store, segments = _seed_state(_valid_planned())
    tracer = _CapturingTracer()
    stage = _bound_stage(state, tracer=tracer, model=_PassingJudge())

    _drive(stage, _sample_event())

    breakdown = _review_trigger(tracer).detail["judge_source"]
    assert breakdown == {"model": len(segments)}


def test_judge_source_breakdown_is_unavailable_when_no_model() -> None:
    state, _store, segments = _seed_state(_valid_planned())
    tracer = _CapturingTracer()
    stage = _bound_stage(state, tracer=tracer)  # no model -> fail closed

    _drive(stage, _sample_event())

    breakdown = _review_trigger(tracer).detail["judge_source"]
    assert breakdown == {"unavailable": len(segments)}


# --------------------------------------------------------------------------- #
# Bounded: no full bodies or judge prose leak into the detail (Req 9.2)          #
# --------------------------------------------------------------------------- #


def test_journal_detail_carries_no_full_bodies_or_prose() -> None:
    state, _store, segments = _seed_state(_valid_planned())
    tracer = _CapturingTracer()
    stage = _bound_stage(state, tracer=tracer, model=_PassingJudge())

    _drive(stage, _sample_event())

    detail = _review_trigger(tracer).detail
    serialized = repr(detail)
    # No full segment bodies leaked.
    bodies = {s.body for s in segments}
    assert bodies
    for body in bodies:
        assert body not in serialized
    # No segment objects; every value is a scalar / short list of strs / scalar-valued dict.
    for value in detail.values():
        if isinstance(value, list):
            assert all(isinstance(item, str) for item in value)
        elif isinstance(value, dict):
            assert all(isinstance(k, str) for k in value)
            assert all(isinstance(v, int) for v in value.values())
        else:
            assert isinstance(value, (str, int, bool))


# --------------------------------------------------------------------------- #
# Empty written set still records a bounded trigger (Req 9.1, 6.5)              #
# --------------------------------------------------------------------------- #


def test_empty_written_set_still_records_a_bounded_trigger() -> None:
    state, _store, _segments = _seed_state(())
    tracer = _CapturingTracer()
    stage = _bound_stage(state, tracer=tracer, model=_PassingJudge())

    _drive(stage, _sample_event())

    detail = _review_trigger(tracer).detail
    assert detail["judged"] == 0
    assert detail["accepted"] == 0
    assert detail["rejected"] == 0
    assert detail["unavailable"] == 0
    assert detail["top_accepted_ids"] == []
    # No segments judged -> empty breakdown.
    assert detail["judge_source"] == {}


# --------------------------------------------------------------------------- #
# No tracer bound: no journal emission, no error (Req 9.1)                       #
# --------------------------------------------------------------------------- #


def test_no_op_when_no_tracer_is_bound() -> None:
    state, _store, _segments = _seed_state(_valid_planned())
    stage = _bound_stage(state, model=_PassingJudge())  # runtime bound with tracer=None

    out = _drive(stage, _sample_event())
    assert len(out) == 1  # event forwarded unchanged, no raise
    # The report is still published; only the journal emission is a no-op.
    assert RunContext(state).review_report() is not None


def test_no_op_when_no_runtime_bound_at_all() -> None:
    state, _store, _segments = _seed_state(_valid_planned())
    stage = ReviewStage()  # never _bind_runtime'd
    _start_task(stage, state)

    out = _drive(stage, _sample_event())
    assert len(out) == 1  # forwarded unchanged, journal is a graceful no-op
    assert RunContext(state).review_report() is not None
