"""Tests for the per-segment write orchestration (cobesy-writer task 3.2).

Task 3.2 wires the per-segment write into :meth:`WriteStage.on_step_end`: for each
``PlannedSegment`` in plan order it builds the deterministic COBESY blueprint, assembles
the prompt, runs the gated prose step (off the run loop when a model is consulted), falls
back to the deterministic renderer when prose is unavailable, wires the ontology
``Segment``, validates it against the loaded ``Vocabulary``, and either stores it (and
adds it to the ordered written set) or records a deterministic ``WriteFlag`` and
continues. It then publishes an ordered ``WrittenSegments`` to ``SLOT_WRITTEN_SEGMENTS``
(same ``Segment`` identities as stored, plan order); an empty plan publishes an empty
written set and completes without error (Req 2.5, 2.6, 5.1-5.5, 6.1-6.6, 7.1, 7.4, 7.5).

These tests are credential-free and harness-free: ``on_step_end`` is driven directly with
a tiny runtime stub bound via ``_bind_runtime``, and ``on_task_start`` with a
``TaskStartEvent`` carrying the run ``State`` — exactly like ``tests/test_stage_plan.py``
and ``tests/test_stage_write.py``. No network, no real model.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from typing import Any

from harnessx.core.events import StepEndEvent, TaskStartEvent
from harnessx.core.state import State

from docuharnessx.composition import WriteFlag, WrittenSegments, segment_id
from docuharnessx.context import RunContext
from docuharnessx.ontology import (
    IdConflictError,
    InMemorySegmentStore,
    Subject,
    default_profile,
    validate_segment,
)
from docuharnessx.planning import COVERAGE_PLAN_SCHEMA_VERSION, CoveragePlan
from docuharnessx.planning.model import EvidenceRef, PlannedSegment
from docuharnessx.stages.write import WriteStage


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


class _NoneModel:
    """A duck-typed provider whose ``complete`` returns unusable (empty) content.

    Drives the gated prose step to ``None`` while a model *is* bound, so the stage marks
    the deterministic fallback ``source="fake"`` (a model was consulted) rather than
    ``"fallback"`` (no model at all).
    """

    def __init__(self) -> None:
        self.calls = 0

    async def complete(
        self, messages: Any, tools: Any, stream_callback: Any = None
    ) -> Any:
        self.calls += 1

        class _Resp:
            content = "   \n  "  # empty/unparseable -> generate_prose returns None

        return _Resp()


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


def _empty_plan() -> CoveragePlan:
    return _plan(())


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


# --------------------------------------------------------------------------- #
# Happy path: one valid stored Segment per planned segment (Req 6.1, 7.4)       #
# --------------------------------------------------------------------------- #


def test_writes_one_valid_segment_per_planned_segment_no_model() -> None:
    plan = _plan(_valid_segments())
    state, store = _state_with(plan)
    stage = _bound_stage(state)  # no model -> deterministic fallback

    out = _drive(stage, _sample_event())
    assert len(out) == 1  # event forwarded unchanged

    stored = store.list_segments()
    assert len(stored) == len(plan.segments)

    vocab = default_profile()
    for seg in stored:
        assert validate_segment(seg, vocab).is_valid


def test_written_segments_published_and_consistent_with_store() -> None:
    plan = _plan(_valid_segments())
    state, store = _state_with(plan)
    stage = _bound_stage(state)

    _drive(stage, _sample_event())

    written = RunContext(state).written_segments()
    assert isinstance(written, WrittenSegments)
    assert written.total_planned == len(plan.segments)
    assert len(written.flags) == 0
    assert len(written.segments) == len(plan.segments)

    # Same identities as stored (Req 7.4): the written-set Segment objects are the
    # exact objects handed to store.put.
    stored_by_id = {s.id: s for s in store.list_segments()}
    for seg in written.segments:
        assert seg.id in stored_by_id
        assert stored_by_id[seg.id] is seg


def test_written_segments_in_plan_order() -> None:
    plan = _plan(_valid_segments())
    state, _store = _state_with(plan)
    stage = _bound_stage(state)

    _drive(stage, _sample_event())

    written = RunContext(state).written_segments()
    expected_ids = [segment_id(ps) for ps in plan.segments]
    assert [s.id for s in written.segments] == expected_ids


# --------------------------------------------------------------------------- #
# Agentic prose: no repo path => deterministic fallback, no run (Req 2.6, 5.4)  #
# --------------------------------------------------------------------------- #


def test_bound_model_without_repo_path_falls_back_without_a_run() -> None:
    # The agentic writer (task 3.1) runs the per-segment agent ONLY when a model is bound AND
    # the target-repository path resolves to a real directory. Here a model is bound but no
    # SLOT_TARGET_REPO is seeded, so the stage must NOT attempt a run: it renders the
    # deterministic fallback for the segment and never consults the bound model (Req 2.6, 5.4).
    plan = _plan(_valid_segments()[:1])
    state, store = _state_with(plan)
    model = _RecordingModel("# A real body\n\nGenerated prose from the model.")
    stage = _bound_stage(state, model=model)

    _drive(stage, _sample_event())

    assert model.calls == 0  # no agentic run attempted without a repo path
    stored = store.list_segments()
    assert len(stored) == 1
    # The deterministic fallback body (leads with the blueprint title), not the model's text.
    assert stored[0].body.startswith("# ")
    assert "Generated prose from the model." not in stored[0].body


def test_none_model_falls_back_deterministically() -> None:
    plan = _plan(_valid_segments()[:1])
    state, store = _state_with(plan)
    stage = _bound_stage(state)  # no model bound at all

    _drive(stage, _sample_event())

    stored = store.list_segments()
    assert len(stored) == 1
    # The deterministic fallback body honors the blueprint (leads with the title).
    assert stored[0].body.startswith("# ")


# --------------------------------------------------------------------------- #
# Failure handling: invalid + id conflict are flagged, not fatal (Req 6.2, 6.4) #
# --------------------------------------------------------------------------- #


def test_invalid_segment_is_flagged_and_others_still_written() -> None:
    # An unknown role makes the first segment invalid under the default vocabulary; the
    # second valid segment must still be written, and the invalid one flagged (Req 6.2).
    invalid = _planned(
        key="ghost__extend__component-scanner",
        roles=("not-a-real-role",),
        intent="extend",
        subject_local="scanner",
        priority=30,
    )
    valid = _valid_segments()[1]
    plan = _plan((invalid, valid))
    state, store = _state_with(plan)
    stage = _bound_stage(state)

    _drive(stage, _sample_event())

    written = RunContext(state).written_segments()
    assert written.total_planned == 2
    assert len(written.segments) == 1
    assert written.segments[0].id == segment_id(valid)

    assert len(written.flags) == 1
    flag = written.flags[0]
    assert isinstance(flag, WriteFlag)
    assert flag.segment_key == invalid.segment_key
    assert flag.cause  # a non-empty, deterministic cause message

    # Only the valid segment was stored.
    assert [s.id for s in store.list_segments()] == [segment_id(valid)]


def test_id_conflict_is_flagged_not_fatal() -> None:
    vocab = default_profile()
    store = InMemorySegmentStore(vocab)
    planned = _valid_segments()[0]
    plan = _plan((planned,))
    state, store = _state_with(plan, store=store)

    # Pre-seed the store with a segment whose id collides with the planned segment's id,
    # so store.put raises IdConflictError for the writer's segment (Req 6.4).
    from docuharnessx.composition import (
        ProseResult,
        build_blueprint,
        render_fallback_body,
        render_fallback_summary,
        wire_segment,
    )

    bp = build_blueprint(planned, None, vocab)
    pre = wire_segment(
        planned,
        bp,
        ProseResult(
            body=render_fallback_body(bp),
            summary=render_fallback_summary(bp),
            source="fallback",
        ),
    )
    store.put(pre)  # occupies the id the writer will derive

    stage = _bound_stage(state)
    out = _drive(stage, _sample_event())
    assert len(out) == 1  # not fatal: event still forwarded

    written = RunContext(state).written_segments()
    assert written.total_planned == 1
    assert len(written.segments) == 0
    assert len(written.flags) == 1
    assert written.flags[0].segment_key == planned.segment_key
    # The pre-seeded segment is the only one in the store (no overwrite).
    assert len(store.list_segments()) == 1


def test_every_planned_segment_is_in_segments_or_flags() -> None:
    invalid = _planned(
        key="ghost__extend__component-scanner",
        roles=("not-a-real-role",),
        intent="extend",
        subject_local="scanner",
        priority=30,
    )
    valid_a, valid_b = _valid_segments()
    plan = _plan((invalid, valid_a, valid_b))
    state, _store = _state_with(plan)
    stage = _bound_stage(state)

    _drive(stage, _sample_event())

    written = RunContext(state).written_segments()
    covered = len(written.segments) + len(written.flags)
    assert covered == written.total_planned == 3


# --------------------------------------------------------------------------- #
# Empty plan: empty written set, no error (Req 6.5)                             #
# --------------------------------------------------------------------------- #


def test_empty_plan_publishes_empty_written_set() -> None:
    plan = _empty_plan()
    state, store = _state_with(plan)
    stage = _bound_stage(state)

    out = _drive(stage, _sample_event())
    assert len(out) == 1

    written = RunContext(state).written_segments()
    assert isinstance(written, WrittenSegments)
    assert written.total_planned == 0
    assert written.segments == ()
    assert written.flags == ()
    assert store.list_segments() == ()


# --------------------------------------------------------------------------- #
# Reproducibility: two model-free runs over an equal plan are byte-equal         #
# --------------------------------------------------------------------------- #


def test_two_model_free_runs_are_byte_equal() -> None:
    plan = _plan(_valid_segments())

    def _run() -> WrittenSegments:
        state, _store = _state_with(plan)
        stage = _bound_stage(state)
        _drive(stage, _sample_event())
        return RunContext(state).written_segments()

    w1 = _run()
    w2 = _run()

    assert w1.total_planned == w2.total_planned
    assert [s.id for s in w1.segments] == [s.id for s in w2.segments]
    assert [s.title for s in w1.segments] == [s.title for s in w2.segments]
    assert [s.body for s in w1.segments] == [s.body for s in w2.segments]
    assert [s.summary for s in w1.segments] == [s.summary for s in w2.segments]
    assert w1.flags == w2.flags


# --------------------------------------------------------------------------- #
# Read-only inputs: the consumed plan is never mutated (Req 2.6)                #
# --------------------------------------------------------------------------- #


def test_consumed_plan_is_not_mutated() -> None:
    plan = _plan(_valid_segments())
    before = replace(plan)
    state, _store = _state_with(plan)
    stage = _bound_stage(state)

    _drive(stage, _sample_event())

    assert plan == before  # frozen value object unchanged
