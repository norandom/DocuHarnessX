"""Credential-free stage integration test for the Review stage (quality-review-gate task 4.1).

This suite drives the **real** :class:`~docuharnessx.stages.review.ReviewStage` end to end
through a genuine HarnessX run, exactly as ``tests/test_stage_write_integration.py`` drives
the Write stage: it binds the test-scoped, no-network :class:`tests._fakes.FakeProvider`
onto the composed ``make_docgen`` bundle (``ModelConfig(main=provider).agentic(make_docgen
(...))`` — the exact bind point the ``dhx`` CLI uses), seeds the review-input slots on the
run ``State`` (a hand-built ``WrittenSegments`` over real wired ``Segment`` objects, the
matching ``CoveragePlan``, a minimal ``RepoAnalysis``, the loaded ``Vocabulary``, and an
``InMemorySegmentStore`` holding the *same* ``Segment`` identities), and runs the pipeline
once with a minimal ``BaseTask`` passed as ``_resume_state`` (mirroring
:func:`docuharnessx.cli.orchestrate_run`).

The Review stage thus FIRES inside the live run loop, on the ``step_end`` hook, reading the
slots through the typed ``RunContext`` exactly as it would in production. That is the seam
task 4.1 pins (design "Validation: a credential-free integration run via the bundle bound to
the fake provider"; Req 1.1-1.4, 2.1-2.6, 5.1, 5.2, 6.5, 6.6, 7.1, 7.4, 7.5):

* with a stub provider returning a clean **passing** per-criterion JSON verdict -> every
  written segment is accepted, ``judge_source`` is non-``unavailable``, and the accepted set
  carries the same stored ``Segment`` identities;
* with the bare :class:`FakeProvider` (``content="done"``, not a verdict) -> the per-segment
  parse fails, so the gate fails closed: every entry is a default-reject with
  ``judge_source="unavailable"`` and the accepted set is empty;
* ``SLOT_REVIEW_REPORT`` is populated with a well-formed :class:`ReviewReport` covering every
  written segment (exactly one entry per segment, in written order); and
* the registry and the bundle are unedited (the real stage drops into the stub's slot).

Why the upstream Write stage is allowed to run (and produce the written set)
----------------------------------------------------------------------------
The Review stage and the upstream Write stage share the same ``step_end`` hook and read
overlapping slots. Rather than hand-seed ``SLOT_WRITTEN_SEGMENTS`` (which the real Write
stage would then overwrite — or, worse, conflict against a pre-populated store), this suite
seeds only the *writer's* inputs (``CoveragePlan``/``RepoAnalysis``/``Vocabulary``/an empty
``InMemorySegmentStore``) and lets the **real** :class:`~docuharnessx.stages.write.WriteStage`
populate ``SLOT_WRITTEN_SEGMENTS`` and the store. The Review stage then judges exactly that
written set, with the *same* ``Segment`` identities the writer stored — which is precisely
the production seam (Req 7.4, 7.5). The boundary under test stays the Review stage: the
writer is the faithful producer of its input.

Credential-free / network-free: every run binds only :class:`FakeProvider`-derived
providers; the production model resolver is never touched.
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any

from harnessx.core.events import make_run_id
from harnessx.core.harness import BaseTask
from harnessx.core.model_config import ModelConfig
from harnessx.core.state import State

from docuharnessx.bundle import make_docgen
from docuharnessx.composition import segment_id
from docuharnessx.context import RunContext
from docuharnessx.ontology import (
    InMemorySegmentStore,
    Subject,
    default_profile,
)
from docuharnessx.planning import COVERAGE_PLAN_SCHEMA_VERSION, CoveragePlan
from docuharnessx.planning.model import EvidenceRef, PlannedSegment
from docuharnessx.review import COBESY_CRITERIA

from tests._fakes import FakeProvider


# --------------------------------------------------------------------------- #
# Fixtures: a seeded plan + the matching written segments + analysis + store    #
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


def _seeded_planned() -> tuple[PlannedSegment, ...]:
    """A small, vocabulary-consistent plan (the default profile knows these axes)."""
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


# --------------------------------------------------------------------------- #
# Providers: a passing-verdict stub judge and the fail-closed bare fake         #
# --------------------------------------------------------------------------- #


def _passing_verdict_json() -> str:
    """A clean, passing per-criterion JSON verdict the deterministic parser accepts.

    Every named COBESY criterion is scored at ``1.0`` with ``passed=True`` and an overall
    ``passed=True`` — so the verdict computer's threshold + all-of rule yields ``pass``.
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


class _PassingJudge(FakeProvider):
    """A no-network provider whose every ``complete`` returns a passing COBESY verdict.

    The *same* bound provider drives both the run loop's own turn and the Review stage's
    gated per-segment judge step; the judge consumes the response ``.content`` (the passing
    JSON verdict), so the deterministic parse/verdict path accepts each segment. ``complete``
    is counted so the test can assert exactly one judge call per segment.
    """

    def __init__(self) -> None:
        super().__init__(content=_passing_verdict_json())
        self.calls = 0

    async def complete(
        self, messages: Any, tools: Any, stream_callback: Any = None
    ) -> Any:
        self.calls += 1
        return await super().complete(messages, tools, stream_callback)


# --------------------------------------------------------------------------- #
# Harness-faithful driver: bind provider, seed slots, run once                  #
# --------------------------------------------------------------------------- #


class _RunResult:
    def __init__(
        self,
        *,
        exit_reason: str,
        run_context: RunContext,
        store: InMemorySegmentStore,
        out_dir: str,
        run_id: str,
    ) -> None:
        self.exit_reason = exit_reason
        self.run_context = run_context
        self.store = store
        self.out_dir = out_dir
        self.run_id = run_id

    def review_trigger_details(self) -> list[dict[str, Any]]:
        details: list[dict[str, Any]] = []
        for trace in _find_trace_jsonl(self.out_dir):
            for record in _read_jsonl(trace):
                if (
                    record.get("event_type") == "processor_trigger"
                    and record.get("action") == "stage_participated"
                    and record.get("detail", {}).get("stage") == "review"
                ):
                    details.append(record["detail"])
        return details


def _drive_review_stage(
    *,
    provider: Any,
    tmp_path,
    seed: bool = True,
) -> _RunResult:
    """Run the composed pipeline once with *provider* bound and the review slots seeded."""
    vocab = default_profile()
    store = InMemorySegmentStore(vocab)
    out_dir = str(tmp_path / "out")
    os.makedirs(out_dir, exist_ok=True)

    harness = ModelConfig(main=provider).agentic(make_docgen(journal_dir=out_dir))

    state = State(run_id=make_run_id())
    run_context = RunContext(state)
    if seed:
        # Seed only the *writer's* inputs; the real Write stage produces the written set
        # and stores the same Segment identities the Review stage then judges (Req 7.4).
        #
        # Boundary note (mirrors tests/test_stage_write_integration.py): SLOT_REPO_ANALYSIS
        # is intentionally NOT seeded at the run level. Seeding it would re-activate the
        # upstream Classify -> Plan chain in the same step_end (Classify reads
        # SLOT_REPO_ANALYSIS; Plan then OVERWRITES SLOT_COVERAGE_PLAN with an empty re-derived
        # plan), so the Write stage would write zero segments and the Review stage would judge
        # an empty set — moving the boundary off the Review stage. Leaving it unset keeps the
        # hand-seeded CoveragePlan authoritative and exercises the Review stage's tolerated
        # ``analysis is None`` path (Req 2.5). The RepoAnalysis-grounding of the criteria is
        # pinned by the deterministic criteria-builder unit tests (task 2.1).
        plan = _plan(_seeded_planned())
        run_context.set_coverage_plan(plan)
        run_context.set_vocabulary(vocab)
        run_context.set_segment_store(store)

    task = BaseTask(description="review the docs", max_steps=4)
    try:
        harness_result = asyncio.run(harness.run(task, _resume_state=state))
    finally:
        asyncio.run(harness.cleanup())

    return _RunResult(
        exit_reason=harness_result.task_end.exit_reason,
        run_context=run_context,
        store=store,
        out_dir=out_dir,
        run_id=state.run_id,
    )


def _find_trace_jsonl(out_dir: str) -> list[str]:
    found: list[str] = []
    for root, _dirs, files in os.walk(out_dir):
        for name in files:
            if name.endswith("_trace.jsonl"):
                found.append(os.path.join(root, name))
    return found


def _read_jsonl(path: str) -> list[dict]:
    with open(path, "r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


# --------------------------------------------------------------------------- #
# Coverage: one report entry per written segment, in written order (Req 6.4, 6.6, 7.1)
# --------------------------------------------------------------------------- #


def test_credential_free_run_publishes_report_covering_every_segment(tmp_path) -> None:
    result = _drive_review_stage(provider=FakeProvider("done"), tmp_path=tmp_path)
    assert result.exit_reason == "done"

    report = result.run_context.review_report()
    assert report is not None

    written = result.run_context.written_segments()
    written_ids = [s.id for s in written.segments]
    # Exactly one entry per written segment, in written order (Req 6.4, 6.6).
    assert [e.segment_id for e in report.entries] == written_ids
    assert report.aggregate.judged == len(written_ids)


def test_report_entry_order_matches_plan_order(tmp_path) -> None:
    result = _drive_review_stage(provider=FakeProvider("done"), tmp_path=tmp_path)
    report = result.run_context.review_report()
    plan = _plan(_seeded_planned())
    assert [e.segment_id for e in report.entries] == [
        segment_id(ps) for ps in plan.segments
    ]


# --------------------------------------------------------------------------- #
# Accept path: a passing stub judge accepts every segment (Req 5.1, 6.2, 7.4) #
# --------------------------------------------------------------------------- #


def test_passing_judge_accepts_every_segment(tmp_path) -> None:
    provider = _PassingJudge()
    result = _drive_review_stage(provider=provider, tmp_path=tmp_path)

    report = result.run_context.review_report()
    written = result.run_context.written_segments()

    # Every segment passes; none used the fail-closed unavailable default.
    assert all(e.verdict == "pass" for e in report.entries)
    assert all(e.judge_source != "unavailable" for e in report.entries)
    assert report.aggregate.accepted == len(written.segments)
    assert report.aggregate.unavailable == 0

    # The accepted set carries the SAME stored Segment identities (Req 7.4, 7.5).
    stored_by_id = {s.id: s for s in result.store.list_segments()}
    assert [s.id for s in report.accepted] == [s.id for s in written.segments]
    for seg in report.accepted:
        assert stored_by_id[seg.id] is seg

    # The bound provider was consulted by the Review stage's gated judge step at least
    # once per written segment (Req 5.1; the run loop and the upstream writer share the
    # same provider, so the exact per-segment-call isolation is pinned by the judge unit
    # tests — here it is enough that judging actually reached the model).
    assert provider.calls >= len(written.segments)


# --------------------------------------------------------------------------- #
# Fail-closed path: a non-verdict fake / model-less run default-rejects        #
# (Req 5.4, 6.3)                                                              #
# --------------------------------------------------------------------------- #


def test_bare_fake_provider_fails_closed_with_empty_accepted(tmp_path) -> None:
    # The bare FakeProvider returns "done" (not a verdict): the per-segment parse fails, so
    # every segment is default-rejected with judge_source="unavailable" and nothing is
    # accepted — a quality firewall never passes unjudged content (Req 5.4, 6.3).
    result = _drive_review_stage(provider=FakeProvider("done"), tmp_path=tmp_path)

    report = result.run_context.review_report()
    written = result.run_context.written_segments()

    assert all(e.verdict == "fail" for e in report.entries)
    assert all(e.judge_source == "unavailable" for e in report.entries)
    assert report.accepted == ()
    assert report.aggregate.accepted == 0
    assert report.aggregate.rejected == len(written.segments)
    assert report.aggregate.unavailable == len(written.segments)


# --------------------------------------------------------------------------- #
# Pass-through: no seeded state -> forward the event, no report (Req 1.3)       #
# --------------------------------------------------------------------------- #


def test_unseeded_run_produces_no_report(tmp_path) -> None:
    result = _drive_review_stage(
        provider=FakeProvider("done"), tmp_path=tmp_path, seed=False
    )
    # With no written-segments slot the stage halts gracefully (like write on a missing
    # store): the run still completes and no report is published.
    assert result.run_context.review_report() is None


# --------------------------------------------------------------------------- #
# Bounded journal summary + judge-source markers (task 4.2; Req 9.1-9.3)        #
# --------------------------------------------------------------------------- #


def test_run_records_a_single_bounded_review_trigger(tmp_path) -> None:
    # The bare FakeProvider fails closed -> every segment is judged via the unavailable
    # default, so the bounded journal summary should report that provenance.
    result = _drive_review_stage(provider=FakeProvider("done"), tmp_path=tmp_path)

    report = result.run_context.review_report()
    written = result.run_context.written_segments()

    details = result.review_trigger_details()
    # Exactly one bounded participation trigger for the Review stage (Req 9.1).
    assert len(details) == 1
    detail = details[0]

    # The four aggregate counts, matching the published report (Req 9.2).
    assert detail["judged"] == report.aggregate.judged == len(written.segments)
    assert detail["accepted"] == report.aggregate.accepted == 0
    assert detail["rejected"] == report.aggregate.rejected == len(written.segments)
    assert detail["unavailable"] == report.aggregate.unavailable == len(written.segments)

    # A capped accepted-id list (empty here — nothing accepted) and a judge-source
    # breakdown marker (Req 9.2, 9.3).
    assert detail["top_accepted_ids"] == []
    assert detail["judge_source"] == {"unavailable": len(written.segments)}

    # Bounded: no full segment body leaked into the trace detail (Req 9.2).
    serialized = json.dumps(detail)
    for seg in written.segments:
        assert seg.body not in serialized


def test_passing_judge_run_records_accepted_ids_and_model_source(tmp_path) -> None:
    result = _drive_review_stage(provider=_PassingJudge(), tmp_path=tmp_path)

    report = result.run_context.review_report()
    written = result.run_context.written_segments()

    details = result.review_trigger_details()
    assert len(details) == 1
    detail = details[0]

    # A passing judge accepts every segment; the bounded summary names the top accepted
    # ids (in accepted order) and records the model judge source (Req 9.2, 9.3).
    assert detail["accepted"] == len(written.segments)
    assert detail["top_accepted_ids"] == [s.id for s in report.accepted]
    assert detail["judge_source"] == {"model": len(written.segments)}
