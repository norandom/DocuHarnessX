"""Stage integration + gating tests for the Review stage (quality-review-gate task 5.1).

Task 5.1 is the credential-free validation of the :class:`~docuharnessx.stages.review.ReviewStage`
gating behaviour, verifying (Req 5.4, 5.5, 6.2, 6.3, 6.4, 6.5) that:

* **every written segment gets exactly one report entry** and the accepted set is consistent
  with the per-segment verdicts and references the same stored ``Segment`` identities;
* a **stub fake provider returning a clean passing verdict** produces accepted passes, while a
  **model-less / plain-``FakeProvider`` run** produces fail-closed default-reject entries with
  ``judge_source="unavailable"`` and an empty accepted set;
* a **mixed** judge (some segments pass, some fail per the deterministic all-of rule) yields an
  accepted set that is exactly the pass entries — in written order, with the stored identities;
* an **injected raising / timing-out / unparseable judge default-rejects only that segment**
  while the run completes without aborting and the other segments are still judged; and
* an **empty written set** yields a well-formed empty report with no error.

Two complementary drivers are used, both credential-free / network-free:

1. **Bundle-driven** (``_drive_via_bundle``) — binds the test-scoped, no-network
   :class:`tests._fakes.FakeProvider` (or a passing-verdict subclass) onto the composed
   ``make_docgen`` bundle exactly as the ``dhx`` CLI does (``ModelConfig(main=provider).agentic
   (make_docgen(...))``), seeds the *writer's* inputs, and lets the real Write stage produce the
   written set the Review stage then judges over the live ``step_end`` hook. This pins the
   accept path and the fail-closed path through the real registry/bundle (Req 1.x, 5.5).
2. **Harness-free per-segment driver** (``_bound_stage`` + ``_drive``) — binds a duck-typed
   per-segment judge stub via ``_bind_runtime`` / ``_bind_model_config`` and drives
   :meth:`ReviewStage.on_step_end` directly over a seeded run ``State`` (mirroring
   ``tests/test_stage_review_journal.py``). This gives precise per-segment control of the judge
   verdict so the mixed-verdict, per-segment-failure-isolation, and empty-set gating cases can be
   asserted deterministically — the same real stage, exercised through the typed ``RunContext``.

The boundary under test is the ReviewStage gate; the deterministic core (criteria/parse/verdict/
aggregate) is pinned by its own unit suites, and we assert gating logic + report shape here, never
exact judge prose.
"""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from typing import Any

from harnessx.core.events import (
    ProcessorTriggerEvent,
    StepEndEvent,
    TaskStartEvent,
    make_run_id,
)
from harnessx.core.harness import BaseTask
from harnessx.core.model_config import ModelConfig
from harnessx.core.state import State

from docuharnessx.bundle import make_docgen
from docuharnessx.composition import segment_id
from docuharnessx.composition.model import WrittenSegments
from docuharnessx.context import RunContext
from docuharnessx.ontology import (
    InMemorySegmentStore,
    Segment,
    Subject,
    default_profile,
)
from docuharnessx.planning import COVERAGE_PLAN_SCHEMA_VERSION, CoveragePlan
from docuharnessx.planning.model import EvidenceRef, PlannedSegment
from docuharnessx.review import COBESY_CRITERIA, CRITERION_THRESHOLD
from docuharnessx.stages.base import STAGE_PARTICIPATION_ACTION
from docuharnessx.stages.review import STAGE_NAME, ReviewStage

from tests._fakes import FakeProvider


# --------------------------------------------------------------------------- #
# Verdict-JSON helpers (the deterministic parser/verdict contract)              #
# --------------------------------------------------------------------------- #


def _passing_verdict_json() -> str:
    """A clean, all-pass per-criterion JSON verdict the deterministic parser accepts.

    Every named COBESY criterion is scored at ``1.0`` (>= ``CRITERION_THRESHOLD``), so the
    verdict computer's threshold + all-of rule yields ``pass``.
    """
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


def _failing_verdict_json(failing: str = "clarity") -> str:
    """A verdict that scores one named criterion below the threshold (the rest pass).

    The verdict computer re-derives each ``passed`` flag from the score vs.
    ``CRITERION_THRESHOLD`` (the judge's own ``passed`` flag is *not* trusted), so a single
    sub-threshold criterion makes the all-of rule yield ``fail`` for that segment — even though
    we report an over-optimistic overall ``passed=True`` here to prove the gate ignores prose.
    """
    below = max(0.0, CRITERION_THRESHOLD - 0.5)
    return json.dumps(
        {
            "criteria": {
                name: {
                    "score": below if name == failing else 1.0,
                    "passed": True,  # deliberately lying: the gate must not trust this
                    "reason": "n/a",
                }
                for name in COBESY_CRITERIA
            },
            "passed": True,  # over-optimistic overall flag; the gate recomputes from scores
            "reason": "judge claims pass",
        }
    )


# --------------------------------------------------------------------------- #
# Bundle-driven harness-faithful driver (accept path + fail-closed path)        #
# --------------------------------------------------------------------------- #


class _PassingJudgeProvider(FakeProvider):
    """A no-network provider whose every ``complete`` returns a passing COBESY verdict."""

    def __init__(self) -> None:
        super().__init__(content=_passing_verdict_json())
        self.calls = 0

    async def complete(
        self, messages: Any, tools: Any, stream_callback: Any = None
    ) -> Any:
        self.calls += 1
        return await super().complete(messages, tools, stream_callback)


def _bundle_planned() -> tuple[PlannedSegment, ...]:
    """A small, default-profile-consistent plan for the bundle-driven run."""
    return (
        PlannedSegment(
            segment_key="developer__extend__component-scanner",
            roles=("developer",),
            intent="extend",
            subjects=(Subject(prefix="component", local="scanner"),),
            priority=20,
            evidence=(EvidenceRef(kind="entrypoint", detail="scanner/registry.py"),),
        ),
        PlannedSegment(
            segment_key="contributor__contribute__component-core",
            roles=("contributor",),
            intent="contribute",
            subjects=(Subject(prefix="component", local="core"),),
            priority=10,
            evidence=(),
        ),
    )


def _bundle_plan() -> CoveragePlan:
    return CoveragePlan(
        schema_version=COVERAGE_PLAN_SCHEMA_VERSION,
        repo_path="/repo/x",
        vocabulary_fingerprint="fp",
        segments=_bundle_planned(),
    )


@dataclass
class _BundleResult:
    exit_reason: str
    run_context: RunContext
    store: InMemorySegmentStore


def _drive_via_bundle(*, provider: Any, tmp_path) -> _BundleResult:
    """Run the composed ``make_docgen`` pipeline once with *provider* bound + slots seeded.

    Seeds only the writer's inputs (CoveragePlan / Vocabulary / an empty store) and lets the
    real Write stage publish ``SLOT_WRITTEN_SEGMENTS`` with the same ``Segment`` identities the
    Review stage then judges — the production seam (Req 7.4, 7.5). ``SLOT_REPO_ANALYSIS`` is left
    unset so the hand-seeded plan stays authoritative (mirrors the Write integration suite).
    """
    vocab = default_profile()
    store = InMemorySegmentStore(vocab)
    out_dir = str(tmp_path / "out")
    os.makedirs(out_dir, exist_ok=True)

    harness = ModelConfig(main=provider).agentic(make_docgen(journal_dir=out_dir))

    state = State(run_id=make_run_id())
    rc = RunContext(state)
    rc.set_coverage_plan(_bundle_plan())
    rc.set_vocabulary(vocab)
    rc.set_segment_store(store)

    task = BaseTask(description="review the docs", max_steps=4)
    try:
        harness_result = asyncio.run(harness.run(task, _resume_state=state))
    finally:
        asyncio.run(harness.cleanup())

    return _BundleResult(
        exit_reason=harness_result.task_end.exit_reason,
        run_context=rc,
        store=store,
    )


def test_bundle_passing_judge_accepts_every_segment_with_stored_identities(
    tmp_path,
) -> None:
    """Bundle + a passing fake judge: every written segment is accepted; identities match.

    Pins the accept path through the real registry/bundle (Req 5.5, 6.2, 6.4, 7.4): one entry
    per written segment, all ``pass``, none via the unavailable default, and the accepted set is
    exactly the pass entries carrying the SAME stored ``Segment`` identities, in written order.
    """
    provider = _PassingJudgeProvider()
    result = _drive_via_bundle(provider=provider, tmp_path=tmp_path)
    assert result.exit_reason == "done"

    report = result.run_context.review_report()
    written = result.run_context.written_segments()
    assert report is not None and written is not None

    written_ids = [s.id for s in written.segments]
    # Exactly one entry per written segment, in written order (Req 6.4, 6.6).
    assert [e.segment_id for e in report.entries] == written_ids
    assert report.aggregate.judged == len(written_ids)

    # Accept path: every segment passes; none used the fail-closed unavailable default.
    assert all(e.verdict == "pass" for e in report.entries)
    assert all(e.judge_source == "model" for e in report.entries)
    assert report.aggregate.accepted == len(written_ids)
    assert report.aggregate.unavailable == 0

    # accepted == exactly the pass entries in written order, carrying the stored identities
    # (Req 6.2, 7.4, 7.5).
    assert [s.id for s in report.accepted] == written_ids
    stored_by_id = {s.id: s for s in result.store.list_segments()}
    for seg in report.accepted:
        assert stored_by_id[seg.id] is seg


def test_bundle_plain_fake_provider_fails_closed_with_empty_accepted(tmp_path) -> None:
    """Bundle + a plain ``FakeProvider`` (no valid verdict JSON): fail-closed default-reject.

    The bare provider returns ``"done"`` (not a verdict), so the per-segment parse fails and the
    gate fails closed: every entry is a default-reject with ``judge_source="unavailable"`` and the
    accepted set is empty — a quality firewall does not pass unjudged content (Req 5.4, 6.3). The
    report is still well-formed and covers every written segment (Req 5.5).
    """
    result = _drive_via_bundle(provider=FakeProvider("done"), tmp_path=tmp_path)
    assert result.exit_reason == "done"

    report = result.run_context.review_report()
    written = result.run_context.written_segments()
    assert report is not None and written is not None
    n = len(written.segments)
    assert n > 0  # the writer produced a non-empty set, so the firewall has work to do

    # One entry per segment, all default-rejected via the unavailable judge source.
    assert [e.segment_id for e in report.entries] == [s.id for s in written.segments]
    assert all(e.verdict == "fail" for e in report.entries)
    assert all(e.judge_source == "unavailable" for e in report.entries)
    # Empty accepted set + consistent aggregate counts.
    assert report.accepted == ()
    assert report.aggregate.accepted == 0
    assert report.aggregate.rejected == n
    assert report.aggregate.unavailable == n


# --------------------------------------------------------------------------- #
# Harness-free per-segment driver (mixed verdicts + per-segment failure)        #
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


@dataclass
class _Resp:
    content: Any


class _PerSegmentJudge:
    """A duck-typed per-segment judge whose behaviour is keyed by the segment id in the brief.

    The deterministic prompt assembler renders ``Segment id: <id>`` into the user message, so a
    judge can branch per segment from the request messages alone. The constructor takes a map of
    ``segment_id -> behaviour`` where a behaviour is one of:

    * a ``str`` -> returned verbatim as ``.content`` (a verdict JSON, or garbage for unparseable);
    * the sentinel ``"RAISE"`` -> ``complete`` raises ``RuntimeError`` (an injected judge failure);
    * the sentinel ``"TIMEOUT"`` -> ``complete`` raises ``TimeoutError`` — the exact exception
      :func:`docuharnessx.review.judge.judge_segment` catches as the absorbed-timeout branch, so
      the timeout path is exercised deterministically and instantly without a real wall-clock wait
      (the stage's judge budget is a fixed default this tests-only boundary must not change).

    An id with no entry defaults to a clean passing verdict. ``calls`` records, per segment id,
    how many times the judge was consulted — so per-segment failure isolation (others still
    judged, exactly once each) is assertable.
    """

    def __init__(self, behaviours: dict[str, str]) -> None:
        self._behaviours = behaviours
        self.calls: dict[str, int] = {}

    @staticmethod
    def _segment_id_of(messages: Any) -> str:
        for msg in messages:
            content = getattr(msg, "content", None)
            if content is None and isinstance(msg, dict):
                content = msg.get("content")
            if isinstance(content, str) and "Segment id: " in content:
                for line in content.splitlines():
                    if line.startswith("Segment id: "):
                        return line[len("Segment id: ") :].strip()
        return "?"

    async def complete(
        self, messages: Any, tools: Any, stream_callback: Any = None
    ) -> Any:
        sid = self._segment_id_of(messages)
        self.calls[sid] = self.calls.get(sid, 0) + 1
        behaviour = self._behaviours.get(sid, _passing_verdict_json())
        if behaviour == "RAISE":
            raise RuntimeError(f"injected judge failure for {sid}")
        if behaviour == "TIMEOUT":
            # The judge step bounds complete() with asyncio.wait_for and catches TimeoutError
            # as the absorbed-timeout branch; raising it directly exercises that path without a
            # real wall-clock wait.
            raise TimeoutError(f"injected judge timeout for {sid}")
        return _Resp(content=behaviour)

    def count_tokens(self, messages: Any) -> int:
        return 1


def _planned(
    *, key: str, roles: tuple[str, ...], intent: str, subject_local: str, priority: int
) -> PlannedSegment:
    return PlannedSegment(
        segment_key=key,
        roles=roles,
        intent=intent,
        subjects=(Subject(prefix="component", local=subject_local),),
        priority=priority,
        evidence=(),
    )


def _three_planned() -> tuple[PlannedSegment, ...]:
    """Three default-profile-consistent planned segments (priority-desc order)."""
    return (
        _planned(
            key="developer__extend__component-scanner",
            roles=("developer",),
            intent="extend",
            subject_local="scanner",
            priority=30,
        ),
        _planned(
            key="contributor__contribute__component-core",
            roles=("contributor",),
            intent="contribute",
            subject_local="core",
            priority=20,
        ),
        _planned(
            key="devops-admin__operate__component-runner",
            roles=("devops-admin",),
            intent="operate",
            subject_local="runner",
            priority=10,
        ),
    )


def _segment_for(planned: PlannedSegment) -> Segment:
    """A wired ontology Segment matching a planned segment (same id the writer derives)."""
    return Segment(
        id=segment_id(planned),
        title=f"{planned.intent} {planned.subjects[0].local}",
        roles=list(planned.roles),
        subjects=list(planned.subjects),
        intent=planned.intent,
        summary=f"Summary for {planned.subjects[0].local}.",
        related=[],
        body=f"# Body for {planned.subjects[0].local}\n\nDetailed prose grounding.",
    )


def _seed_state(
    planned: tuple[PlannedSegment, ...],
) -> tuple[State, InMemorySegmentStore, list[Segment]]:
    """Seed a run State with the written set + plan + vocab + store the Review stage reads."""
    vocab = default_profile()
    store = InMemorySegmentStore(vocab)
    segments = [_segment_for(p) for p in planned]
    for seg in segments:
        store.put(seg)

    state = State(run_id="run-review-gating")
    rc = RunContext(state)
    rc.set_coverage_plan(
        CoveragePlan(
            schema_version=COVERAGE_PLAN_SCHEMA_VERSION,
            repo_path="/repo/x",
            vocabulary_fingerprint="fp",
            segments=planned,
        )
    )
    rc.set_vocabulary(vocab)
    rc.set_segment_store(store)
    rc.set_written_segments(
        WrittenSegments(
            segments=tuple(segments),
            flags=(),
            total_planned=len(planned),
        )
    )
    return state, store, segments


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


def _sample_event() -> StepEndEvent:
    return StepEndEvent(
        run_id="run-review-gating",
        step_id=7,
        step_summary="prior summary",
        tool_call_summary="readFile(a)",
        cumulative_tokens=10,
        cumulative_cost_usd=0.1,
    )


def _drive(stage: ReviewStage, event: StepEndEvent) -> list[Any]:
    async def _collect() -> list[Any]:
        return [out async for out in stage.on_step_end(event)]

    return asyncio.run(_collect())


def _review_trigger(tracer: _CapturingTracer) -> ProcessorTriggerEvent:
    triggers = [
        e
        for e in tracer.events
        if isinstance(e, ProcessorTriggerEvent)
        and e.action == STAGE_PARTICIPATION_ACTION
        and e.detail.get("stage") == STAGE_NAME
    ]
    assert len(triggers) == 1, f"expected exactly one Review trigger, got {triggers!r}"
    return triggers[0]


# --------------------------------------------------------------------------- #
# Mixed verdicts: accepted == exactly the pass entries in written order         #
# (Req 6.2, 6.4)                                                              #
# --------------------------------------------------------------------------- #


def test_mixed_verdicts_accept_exactly_the_pass_entries_in_order(tmp_path) -> None:
    state, store, segments = _seed_state(_three_planned())
    ids = [s.id for s in segments]
    # Middle segment fails one criterion (sub-threshold clarity); the other two pass.
    failing_id = ids[1]
    judge = _PerSegmentJudge(
        {
            ids[0]: _passing_verdict_json(),
            failing_id: _failing_verdict_json("clarity"),
            ids[2]: _passing_verdict_json(),
        }
    )
    stage = _bound_stage(state, model=judge)

    out = _drive(stage, _sample_event())
    assert len(out) == 1  # the event is forwarded unchanged

    report = RunContext(state).review_report()
    assert report is not None

    # Exactly one entry per written segment, in written order (Req 6.4, 6.6).
    assert [e.segment_id for e in report.entries] == ids
    verdict_by_id = {e.segment_id: e.verdict for e in report.entries}
    assert verdict_by_id[ids[0]] == "pass"
    assert verdict_by_id[failing_id] == "fail"
    assert verdict_by_id[ids[2]] == "pass"

    # accepted == exactly the pass entries, in written order, with the failing one excluded
    # and carrying the SAME stored identities (Req 6.2, 7.4).
    assert [s.id for s in report.accepted] == [ids[0], ids[2]]
    stored_by_id = {s.id: s for s in store.list_segments()}
    for seg in report.accepted:
        assert stored_by_id[seg.id] is seg

    # Aggregate counts consistent with the mixed outcome; the failing segment was judged
    # (not unavailable), so the rejection is a real fail, not the fail-closed default.
    assert report.aggregate.judged == 3
    assert report.aggregate.accepted == 2
    assert report.aggregate.rejected == 1
    assert report.aggregate.unavailable == 0
    failing_entry = next(e for e in report.entries if e.segment_id == failing_id)
    assert failing_entry.judge_source == "model"
    assert any("clarity" in f for f in failing_entry.findings)


# --------------------------------------------------------------------------- #
# Per-segment failure isolation: one bad judge default-rejects only its segment #
# (Req 5.4, 6.3) — the run completes; the others are still judged              #
# --------------------------------------------------------------------------- #


def _assert_one_segment_isolated(behaviour: str, tmp_path) -> None:
    """Drive a 3-segment review where the middle segment's judge misbehaves.

    The middle segment is default-rejected with ``judge_source="unavailable"`` while the first
    and third pass and are accepted — the run completes without aborting and every segment is
    judged exactly once (Req 5.4, 6.3).
    """
    state, store, segments = _seed_state(_three_planned())
    ids = [s.id for s in segments]
    bad_id = ids[1]
    judge = _PerSegmentJudge(
        {
            ids[0]: _passing_verdict_json(),
            bad_id: behaviour,
            ids[2]: _passing_verdict_json(),
        }
    )
    stage = _bound_stage(state, model=judge)

    out = _drive(stage, _sample_event())
    assert len(out) == 1  # the run does not abort: the event is still forwarded

    report = RunContext(state).review_report()
    assert report is not None

    # Every written segment still has exactly one entry (Req 6.4); the good ones pass.
    assert [e.segment_id for e in report.entries] == ids
    by_id = {e.segment_id: e for e in report.entries}
    assert by_id[ids[0]].verdict == "pass"
    assert by_id[ids[2]].verdict == "pass"
    # Only the misbehaving segment is the fail-closed default-reject.
    assert by_id[bad_id].verdict == "fail"
    assert by_id[bad_id].judge_source == "unavailable"
    assert by_id[ids[0]].judge_source == "model"
    assert by_id[ids[2]].judge_source == "model"

    # accepted == exactly the two passing segments (the isolated failure is excluded).
    assert [s.id for s in report.accepted] == [ids[0], ids[2]]
    assert report.aggregate.judged == 3
    assert report.aggregate.accepted == 2
    assert report.aggregate.rejected == 1
    assert report.aggregate.unavailable == 1

    # The other two segments were still judged exactly once each (the bad one's call count
    # depends on the failure mode but is bounded to one attempt — no uncapped retry loop).
    assert judge.calls.get(ids[0]) == 1
    assert judge.calls.get(ids[2]) == 1
    assert judge.calls.get(bad_id) == 1


def test_raising_judge_isolates_only_its_segment(tmp_path) -> None:
    _assert_one_segment_isolated("RAISE", tmp_path)


def test_unparseable_judge_isolates_only_its_segment(tmp_path) -> None:
    # Non-JSON garbage: parse_verdict returns None -> fail-closed default-reject for that one.
    _assert_one_segment_isolated("not json at all { : }", tmp_path)


def test_empty_content_judge_isolates_only_its_segment(tmp_path) -> None:
    # An empty body parses to None -> fail-closed default-reject for that one segment.
    _assert_one_segment_isolated("", tmp_path)


def test_timing_out_judge_isolates_only_its_segment(tmp_path) -> None:
    _assert_one_segment_isolated("TIMEOUT", tmp_path)


# --------------------------------------------------------------------------- #
# Empty written set -> well-formed empty report, no error (Req 6.5)             #
# --------------------------------------------------------------------------- #


def test_empty_written_set_yields_well_formed_empty_report(tmp_path) -> None:
    state, _store, _segments = _seed_state(())  # no planned -> no written segments
    judge = _PerSegmentJudge({})  # never consulted
    tracer = _CapturingTracer()
    stage = _bound_stage(state, tracer=tracer, model=judge)

    out = _drive(stage, _sample_event())
    assert len(out) == 1  # the event is forwarded; no error raised

    report = RunContext(state).review_report()
    assert report is not None
    # Well-formed empty report: no entries, empty accepted set, zero aggregate counts.
    assert report.entries == ()
    assert report.accepted == ()
    assert report.aggregate.judged == 0
    assert report.aggregate.accepted == 0
    assert report.aggregate.rejected == 0
    assert report.aggregate.unavailable == 0
    # The judge was never consulted (no segments to judge).
    assert judge.calls == {}

    # A single bounded participation trigger is still recorded for the empty review.
    trigger = _review_trigger(tracer)
    assert trigger.detail["judged"] == 0
    assert trigger.detail["top_accepted_ids"] == []
    assert trigger.detail["judge_source"] == {}
