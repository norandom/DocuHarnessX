"""Integration tests for the agentic Write-stage prose swap (agentic-codebase-writer task 3.1).

Task 3.1 (boundary: *WriteStage*) replaces the Write stage's per-segment single-shot
``generate_prose`` call with the bounded :class:`~docuharnessx.composition.AgenticProseRunner`
over a read-only ``Workspace`` rooted at the target repository, gating the agent's body
through the deterministic structure gate and rendering the existing deterministic fallback on
any miss. The stable stage contract (``STAGE_NAME``/``WriteStage``/``make_write_stage``/module
path), the plan-order iteration, the validate/store/flag logic, the bounded journal, and the
frozen ``WrittenSegments`` output seam are all preserved (Req 1.x, 2.6, 4.5, 5.4, 5.5,
6.1-6.6, 7.1-7.4).

These tests drive :meth:`WriteStage.on_step_end` directly with a tiny runtime stub (exactly
like ``tests/test_stage_write_orchestration.py``), but additionally seed the
``SLOT_TARGET_REPO`` slot at a throwaway copy of the crafted fixture repository
(``tests/fixtures/agentic_repo``) and bind the offline :class:`ScriptedAgentProvider`, so the
stage drives the REAL HarnessX run loop and the REAL read/grep tools with no network and no
credentials (Req 9.1, 9.2). The fixture is copied into ``tmp_path`` because
``Harness.run`` writes a ``harness_config.yaml`` runtime snapshot into the workspace root.
"""

from __future__ import annotations

import asyncio
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from harnessx.core.events import StepEndEvent, TaskStartEvent
from harnessx.core.state import State

from docuharnessx.composition import WrittenSegments, segment_id, validate_agent_body
from docuharnessx.context import RunContext
from docuharnessx.ontology import (
    InMemorySegmentStore,
    Subject,
    default_profile,
    validate_segment,
)
from docuharnessx.planning import COVERAGE_PLAN_SCHEMA_VERSION, CoveragePlan
from docuharnessx.planning.model import EvidenceRef, PlannedSegment
from docuharnessx.stages.write import WriteStage

from tests._fakes import SCRIPTED_AGENT_BODY, FakeProvider, ScriptedAgentProvider

_FIXTURE_REPO = Path(__file__).parent / "fixtures" / "agentic_repo"


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
# Fixtures: planned segments naming the fixture files + the crafted repo        #
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
            key="developer__extend__component-app",
            roles=("developer",),
            intent="extend",
            subject_local="app",
            priority=20,
            evidence=(EvidenceRef(kind="entrypoint", detail="app.py"),),
        ),
        _planned(
            key="contributor__contribute__component-engine",
            roles=("contributor",),
            intent="contribute",
            subject_local="engine",
            priority=10,
            evidence=(EvidenceRef(kind="module", detail="engine.py"),),
        ),
    )


def _plan(segments: tuple[PlannedSegment, ...]) -> CoveragePlan:
    return CoveragePlan(
        schema_version=COVERAGE_PLAN_SCHEMA_VERSION,
        repo_path="/repo/x",
        vocabulary_fingerprint="fp",
        segments=segments,
    )


def _rooted_copy(tmp_path: Path) -> str:
    """Copy the pristine fixture into *tmp_path* so the run can root there cleanly.

    ``Harness.run`` writes a ``harness_config.yaml`` runtime snapshot into the workspace
    root, so rooting at a throwaway copy keeps the committed fixture clean.
    """
    tmp_path.mkdir(parents=True, exist_ok=True)
    dest = tmp_path / "agentic_repo"
    shutil.copytree(_FIXTURE_REPO, dest)
    return str(dest)


def _state_with(
    plan: CoveragePlan,
    *,
    repo_path: str | None = None,
    store: InMemorySegmentStore | None = None,
) -> tuple[State, InMemorySegmentStore]:
    vocab = default_profile()
    store = store if store is not None else InMemorySegmentStore(vocab)
    state = State(run_id="r-write")
    rc = RunContext(state)
    rc.set_coverage_plan(plan)
    rc.set_vocabulary(vocab)
    rc.set_segment_store(store)
    if repo_path is not None:
        rc.set_target_repo(repo_path)
    return state, store


# --------------------------------------------------------------------------- #
# Happy path: bound model + valid repo path -> real run loop, grounded body     #
# (Req 3.1-3.5, 4.5, 5.5, 7.1, 7.4, 9.1-9.3)                                    #
# --------------------------------------------------------------------------- #


def test_agentic_run_produces_grounded_body_with_mermaid_and_citations(tmp_path) -> None:
    plan = _plan(_valid_segments()[:1])
    state, store = _state_with(plan, repo_path=_rooted_copy(tmp_path))
    stage = _bound_stage(state, model=ScriptedAgentProvider())

    out = _drive(stage, _sample_event())
    assert len(out) == 1  # event forwarded unchanged

    stored = store.list_segments()
    assert len(stored) == 1
    body = stored[0].body
    # The accepted body is the agent's final answer verbatim (Req 4.5).
    assert body == SCRIPTED_AGENT_BODY
    # It clears the structure gate: a Mermaid fence + >= MIN_CITED_FILES citations.
    assert validate_agent_body(body).accepted
    assert "```mermaid" in body
    assert "app.py:11" in body

    # The segment is valid under the loaded vocabulary (the validate gate ran unchanged).
    assert validate_segment(stored[0], default_profile()).is_valid


def test_agentic_run_marks_prose_source_model_in_journal(tmp_path) -> None:
    plan = _plan(_valid_segments()[:1])
    state, _store = _state_with(plan, repo_path=_rooted_copy(tmp_path))
    tracer = _CapturingTracer()
    stage = _bound_stage(state, tracer=tracer, model=ScriptedAgentProvider())

    _drive(stage, _sample_event())

    from docuharnessx.stages.base import STAGE_PARTICIPATION_ACTION

    triggers = [
        e
        for e in tracer.events
        if getattr(e, "action", None) == STAGE_PARTICIPATION_ACTION
        and getattr(e, "detail", {}).get("stage") == "write"
    ]
    assert len(triggers) == 1
    assert triggers[0].detail["prose_source"] == "model"


def test_agentic_run_drove_the_real_tools(tmp_path) -> None:
    # The scripted provider counts complete calls (one per step): three scripted tool-call
    # turns + the final end-turn body proves the real run loop executed the read/grep turns.
    plan = _plan(_valid_segments()[:1])
    provider = ScriptedAgentProvider()
    state, _store = _state_with(plan, repo_path=_rooted_copy(tmp_path))
    stage = _bound_stage(state, model=provider)

    _drive(stage, _sample_event())

    assert provider.complete_calls == 4


# --------------------------------------------------------------------------- #
# No repo path: deterministic fallback for every segment, never crashes (Req 2.6)#
# --------------------------------------------------------------------------- #


def test_missing_repo_path_falls_back_for_every_segment() -> None:
    # No SLOT_TARGET_REPO seeded; a model IS bound. The stage must not attempt a run; it
    # renders the deterministic fallback for every segment and never crashes (Req 2.6).
    plan = _plan(_valid_segments())
    state, store = _state_with(plan, repo_path=None)
    stage = _bound_stage(state, model=ScriptedAgentProvider())

    out = _drive(stage, _sample_event())
    assert len(out) == 1

    stored = store.list_segments()
    assert len(stored) == len(plan.segments)
    for seg in stored:
        # The deterministic fallback leads with the blueprint title (a Markdown heading)
        # and carries NO agent Mermaid fence.
        assert seg.body.startswith("# ")
        assert "```mermaid" not in seg.body
        assert validate_segment(seg, default_profile()).is_valid

    written = RunContext(state).written_segments()
    assert written.total_planned == len(plan.segments)
    assert len(written.segments) == len(plan.segments)
    assert len(written.flags) == 0


def test_invalid_repo_path_falls_back_for_every_segment(tmp_path) -> None:
    # A SLOT_TARGET_REPO pointing at a non-existent directory cannot root a workspace; the
    # stage falls back deterministically for every segment and never crashes (Req 2.6).
    missing = str(tmp_path / "does-not-exist")
    plan = _plan(_valid_segments())
    state, store = _state_with(plan, repo_path=missing)
    stage = _bound_stage(state, model=ScriptedAgentProvider())

    out = _drive(stage, _sample_event())
    assert len(out) == 1

    stored = store.list_segments()
    assert len(stored) == len(plan.segments)
    for seg in stored:
        assert "```mermaid" not in seg.body


def test_missing_repo_path_marks_prose_source_fallback() -> None:
    plan = _plan(_valid_segments())
    state, _store = _state_with(plan, repo_path=None)
    tracer = _CapturingTracer()
    stage = _bound_stage(state, tracer=tracer, model=ScriptedAgentProvider())

    _drive(stage, _sample_event())

    from docuharnessx.stages.base import STAGE_PARTICIPATION_ACTION

    triggers = [
        e
        for e in tracer.events
        if getattr(e, "action", None) == STAGE_PARTICIPATION_ACTION
        and getattr(e, "detail", {}).get("stage") == "write"
    ]
    assert len(triggers) == 1
    # No agentic run was attempted (no repo path), so the run-level marker is "fallback".
    assert triggers[0].detail["prose_source"] == "fallback"


# --------------------------------------------------------------------------- #
# No model: deterministic fallback for every segment without a run (Req 5.4, 6.3)#
# --------------------------------------------------------------------------- #


def test_no_model_falls_back_for_every_segment(tmp_path) -> None:
    plan = _plan(_valid_segments())
    # A valid repo path is present, but NO model is bound: the stage must not attempt a run.
    state, store = _state_with(plan, repo_path=_rooted_copy(tmp_path))
    stage = _bound_stage(state)  # no model bound at all

    out = _drive(stage, _sample_event())
    assert len(out) == 1

    stored = store.list_segments()
    assert len(stored) == len(plan.segments)
    for seg in stored:
        assert seg.body.startswith("# ")
        assert "```mermaid" not in seg.body

    written = RunContext(state).written_segments()
    assert len(written.segments) == len(plan.segments)


# --------------------------------------------------------------------------- #
# Rejected agent body -> deterministic fallback (Req 6.1)                        #
# --------------------------------------------------------------------------- #


def test_rejected_agent_body_falls_back(tmp_path) -> None:
    # A bound model that ends the turn immediately with a body failing the structure gate
    # (no Mermaid, no citations) -> the runner returns None -> the stage falls back (Req 6.1).
    plan = _plan(_valid_segments()[:1])
    state, store = _state_with(plan, repo_path=_rooted_copy(tmp_path))
    stage = _bound_stage(state, model=FakeProvider("Just prose, no mermaid, no citations."))

    out = _drive(stage, _sample_event())
    assert len(out) == 1

    stored = store.list_segments()
    assert len(stored) == 1
    # The fallback body, not the rejected agent answer.
    assert stored[0].body.startswith("# ")
    assert "```mermaid" not in stored[0].body


# --------------------------------------------------------------------------- #
# The frozen output seam (type + slot) is unchanged (Req 7.1, 7.4)              #
# --------------------------------------------------------------------------- #


def test_output_seam_type_and_slot_unchanged(tmp_path) -> None:
    plan = _plan(_valid_segments()[:1])
    state, store = _state_with(plan, repo_path=_rooted_copy(tmp_path))
    stage = _bound_stage(state, model=ScriptedAgentProvider())

    _drive(stage, _sample_event())

    written = RunContext(state).written_segments()
    # Same frozen value type at the same slot the review gate consumes.
    assert isinstance(written, WrittenSegments)
    # Same identities as stored, in plan order.
    stored_by_id = {s.id: s for s in store.list_segments()}
    assert {s.id for s in written.segments} == set(stored_by_id)
    assert [s.id for s in written.segments] == [segment_id(ps) for ps in plan.segments]
    for seg in written.segments:
        assert stored_by_id[seg.id] is seg
