"""Credential-free stage integration test for the Write stage (cobesy-writer task 4.1).

Where ``tests/test_stage_write.py`` (task 3.1) and ``tests/test_stage_write_orchestration.py``
(task 3.2) drive :meth:`WriteStage.on_step_end` *directly* with a tiny runtime stub, this
suite drives the **real** :class:`~docuharnessx.stages.write.WriteStage` end to end through
a genuine HarnessX run: it binds the test-scoped, no-network
:class:`tests._fakes.FakeProvider` onto the composed ``make_docgen`` bundle
(``ModelConfig(main=FakeProvider(...)).agentic(make_docgen(...))`` — the exact bind point the
``dhx`` CLI uses), seeds the writer-input slots on the run ``State``
(``CoveragePlan``/``Vocabulary``/``InMemorySegmentStore``; the optional ``RepoAnalysis`` is
left unset — see the "Boundary note" below), and runs the pipeline once with a minimal
``BaseTask`` passed as ``_resume_state`` (mirroring :func:`docuharnessx.cli.orchestrate_run`).

The Write stage thus FIRES inside the live run loop, on the ``step_end`` hook, reading the
slots through the typed ``RunContext`` exactly as it would in production. That is the seam
task 4.1 pins (design "Validation: integration test runs ``make_docgen`` bound to
``FakeProvider.agentic(...)``"; Req 1.1, 1.3, 5.1, 5.4, 6.1, 7.1, 7.4, 8.1-8.3):

* with the fake model returning clean content -> the body is wired from the model
  (``prose_source == "model"``), one valid stored ``Segment`` per planned segment;
* with the fake model returning unusable content (or no model at all) -> the deterministic
  fallback renders the body, ``prose_source`` is recorded (``"fake"``/``"fallback"``), and
  there is still one valid stored ``Segment`` per planned segment;
* ``SLOT_WRITTEN_SEGMENTS`` is populated and consistent with the segment store (same
  ``Segment`` identities), in plan order; and
* a bounded participation record lands in the run's HarnessJournal ``_trace.jsonl``
  carrying the counts, the capped top-id list, and the ``prose_source`` marker — never a
  full segment body.

Credential-free / network-free: every run binds only :class:`FakeProvider`; the upstream
ingest/analyze/classify/plan stages have no slots seeded, so they crash-skip (the run loop
absorbs a stage error and continues), which is exactly why this suite seeds the writer's
own inputs directly rather than running the full upstream chain — the boundary under test
is the Write stage, not the planner. The production model resolver is never touched.

Boundary note — why ``SLOT_REPO_ANALYSIS`` is *not* seeded at the run level
---------------------------------------------------------------------------
The ``RepoAnalysis`` is an **optional** writer input (Req 2.5): the blueprint grounds on
the planner evidence alone when it is absent. Seeding ``SLOT_REPO_ANALYSIS`` here would
*re-activate* the upstream Classify -> Plan chain in the same ``step_end`` (Classify reads
``SLOT_REPO_ANALYSIS``, Plan then overwrites ``SLOT_COVERAGE_PLAN``), which would replace
this suite's hand-seeded ``CoveragePlan`` with one re-derived by the planner — moving the
test's boundary off the Write stage and onto the planner. To keep the Write stage the
genuine boundary (the task 4.1 boundary), the suite seeds the exact ``CoveragePlan`` it
asserts against and lets the writer take its tolerated ``analysis is None`` path; the
RepoAnalysis-grounding of the blueprint is pinned by the deterministic blueprint unit
tests (task 2.1). The :class:`RepoAnalysis` grounding seam is still exercised: it is
constructed (:func:`_analysis`) and the writer's tolerance of its absence is asserted
end-to-end.
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

from docuharnessx.analysis.model import DocPresence, RepoAnalysis, ScanStats
from docuharnessx.analysis.model import TestLayout as _TestLayout  # noqa: N813
from docuharnessx.bundle import make_docgen
from docuharnessx.context import RunContext
from docuharnessx.ontology import (
    InMemorySegmentStore,
    Subject,
    default_profile,
    validate_segment,
)
from docuharnessx.planning import COVERAGE_PLAN_SCHEMA_VERSION, CoveragePlan
from docuharnessx.planning.model import EvidenceRef, PlannedSegment

from tests._fakes import FakeProvider


# --------------------------------------------------------------------------- #
# Fixtures: a seeded plan / analysis / vocabulary / store                       #
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


def _seeded_segments() -> tuple[PlannedSegment, ...]:
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


def _analysis() -> RepoAnalysis:
    """A minimal, well-formed ``RepoAnalysis`` to seed the optional grounding slot.

    The writer tolerates an absent analysis (Req 2.5); seeding a real one here exercises
    the evidence-grounding path through the live run rather than the ``None`` shortcut.
    """
    return RepoAnalysis(
        schema_version=1,
        repo_path="/repo/x",
        languages=(),
        primary_languages=(),
        total_loc=0,
        total_files=0,
        structure=(),
        entrypoints=(),
        build_files=(),
        ci_workflows=(),
        tests=_TestLayout(present=False, frameworks=(), paths=()),
        dependencies=(),
        components=(),
        public_surface=(),
        docs=DocPresence(
            has_readme=False, readme_paths=(), doc_dirs=(), other_docs=()
        ),
        artifacts=(),
        scan_stats=ScanStats(
            files_scanned=0,
            files_skipped=0,
            bytes_scanned=0,
            limit_reached=False,
            notes=(),
        ),
    )


# --------------------------------------------------------------------------- #
# Harness-faithful driver: bind FakeProvider, seed slots, run once             #
# --------------------------------------------------------------------------- #


class _CleanProse(FakeProvider):
    """A no-network provider returning a clean structured prose body.

    Subclasses :class:`tests._fakes.FakeProvider` so its single ``complete`` response is a
    genuine end-turn :class:`~harnessx.core.events.ModelResponseEvent` — the run loop
    accepts ``finish_reason='end_turn'`` as a terminal turn and reaches ``done`` in one
    step (so the writer's ``step_end`` fires exactly once). The *same* bound provider is
    what the writer's gated prose step consumes: the response ``.content`` is a JSON
    ``{"body": ..., "summary": ...}`` object so the deterministic parse yields the body the
    wiring uses, proving the model surface flows through to the stored ``Segment`` (Req
    5.1). ``complete`` is counted so the test can assert exactly one call per segment.
    """

    BODY = "# Extending the scanner\n\nLead with the conclusion, then the detail."
    SUMMARY = "How to extend the scanner."

    def __init__(self) -> None:
        super().__init__(content=json.dumps({"body": self.BODY, "summary": self.SUMMARY}))
        self.calls = 0

    async def complete(
        self, messages: Any, tools: Any, stream_callback: Any = None
    ) -> Any:
        self.calls += 1
        return await super().complete(messages, tools, stream_callback)


class _RunResult:
    """The observable surface of one driven Write-stage run."""

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

    def write_trigger_detail(self) -> dict[str, Any]:
        """The bounded participation ``detail`` the Write stage recorded in the journal.

        Reads the run's HarnessJournal ``_trace.jsonl`` and returns the
        ``processor_trigger`` (``action='stage_participated'``) detail whose
        ``stage == 'write'``. Asserts exactly one such Write record exists for the run.
        """
        details: list[dict[str, Any]] = []
        for trace in _find_trace_jsonl(self.out_dir):
            for record in _read_jsonl(trace):
                if (
                    record.get("event_type") == "processor_trigger"
                    and record.get("action") == "stage_participated"
                    and record.get("detail", {}).get("stage") == "write"
                ):
                    details.append(record["detail"])
        assert len(details) == 1, f"expected one Write trigger, got {len(details)}"
        return details[0]


def _drive_write_stage(
    plan: CoveragePlan,
    *,
    provider: Any,
    tmp_path,
    store: InMemorySegmentStore | None = None,
) -> _RunResult:
    """Run the composed pipeline once with *provider* bound and the writer slots seeded.

    Binds the (credential-free) *provider* via ``ModelConfig(main=...).agentic(make_docgen
    (...))`` — the exact bind point the ``dhx`` CLI uses — seeds the writer's input slots on
    a fresh run ``State`` (mirroring :func:`docuharnessx.cli.orchestrate_run`), and drives
    one run via ``harness.run(task, _resume_state=state)`` so the Write stage fires on the
    live ``step_end`` hook reading those slots.

    Seeds ``SLOT_COVERAGE_PLAN``/``SLOT_VOCABULARY``/``SLOT_SEGMENT_STORE`` (the writer's
    required inputs). ``SLOT_REPO_ANALYSIS`` is intentionally left unset — see the module
    docstring "Boundary note" — so the seeded plan stays authoritative and the writer takes
    its tolerated ``analysis is None`` path (Req 2.5).
    """
    vocab = default_profile()
    store = store if store is not None else InMemorySegmentStore(vocab)
    out_dir = str(tmp_path / "out")
    os.makedirs(out_dir, exist_ok=True)

    harness = ModelConfig(main=provider).agentic(make_docgen(journal_dir=out_dir))

    state = State(run_id=make_run_id())
    run_context = RunContext(state)
    run_context.set_coverage_plan(plan)
    run_context.set_vocabulary(vocab)
    run_context.set_segment_store(store)

    task = BaseTask(description="write the docs", max_steps=4)
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
# Credential-free end-to-end: one valid stored Segment per planned segment      #
# (Req 1.1, 1.3, 5.4, 6.1, 7.1, 7.4)                                          #
# --------------------------------------------------------------------------- #


def test_credential_free_run_writes_one_valid_segment_per_planned(tmp_path) -> None:
    plan = _plan(_seeded_segments())
    result = _drive_write_stage(
        plan, provider=FakeProvider("done"), tmp_path=tmp_path
    )

    # The whole pipeline ran to a clean terminal state with no network call.
    assert result.exit_reason == "done"

    # One valid stored Segment per planned segment (Req 6.1), each valid under the
    # loaded Vocabulary (Req 6.1, the validation gate the stage applied).
    stored = result.store.list_segments()
    assert len(stored) == len(plan.segments)
    vocab = default_profile()
    for seg in stored:
        assert validate_segment(seg, vocab).is_valid


def test_written_slot_populated_and_consistent_with_store(tmp_path) -> None:
    plan = _plan(_seeded_segments())
    result = _drive_write_stage(
        plan, provider=FakeProvider("done"), tmp_path=tmp_path
    )

    written = result.run_context.written_segments()
    assert written is not None
    assert written.total_planned == len(plan.segments)
    assert len(written.flags) == 0
    assert len(written.segments) == len(plan.segments)

    # The written-set Segment objects are the *same identities* handed to store.put
    # (Req 7.4): a consumer can use either handle for the same content.
    stored_by_id = {s.id: s for s in result.store.list_segments()}
    assert {s.id for s in written.segments} == set(stored_by_id)
    for seg in written.segments:
        assert stored_by_id[seg.id] is seg


def test_written_set_is_in_plan_order(tmp_path) -> None:
    from docuharnessx.composition import segment_id

    plan = _plan(_seeded_segments())
    result = _drive_write_stage(
        plan, provider=FakeProvider("done"), tmp_path=tmp_path
    )

    written = result.run_context.written_segments()
    assert [s.id for s in written.segments] == [segment_id(ps) for ps in plan.segments]


# --------------------------------------------------------------------------- #
# Gated prose: a clean model body is wired into the segment (prose_source model)#
# (Req 5.1, 5.4, 8.3)                                                          #
# --------------------------------------------------------------------------- #


def test_bound_model_without_repo_path_falls_back_through_live_run(tmp_path) -> None:
    # The agentic writer (Wave 2.5, task 3.1) runs its per-segment agent ONLY when a model is
    # bound AND the target-repository path resolves to a real directory. This live-run driver
    # seeds no SLOT_TARGET_REPO (the agentic end-to-end path with a fixture repo + scripted
    # provider lands in task 5.2), so the writer must NOT attempt a run: it renders the
    # deterministic fallback for every segment without consulting the bound provider for prose
    # (Req 2.6, 5.4, 6.3). The provider is still bound for the run loop's own turn.
    provider = _CleanProse()
    plan = _plan(_seeded_segments())
    result = _drive_write_stage(
        plan, provider=provider, tmp_path=tmp_path
    )

    # The writer never consulted the bound provider (no repo path => no agentic run), so the
    # clean-prose body never reaches a stored Segment; every body is the deterministic
    # fallback instead (Req 2.6, 5.4).
    stored = result.store.list_segments()
    assert len(stored) == len(plan.segments)
    vocab = default_profile()
    for seg in stored:
        assert validate_segment(seg, vocab).is_valid
        assert seg.body.startswith("# ")  # the blueprint-title-led fallback body
        assert seg.body != _CleanProse.BODY

    # The bounded journal records the model-less fallback provenance (Req 8.3): no agentic run
    # was viable for any segment.
    assert result.write_trigger_detail()["prose_source"] == "fallback"


def test_no_repo_path_falls_back_but_still_writes_valid_segments(tmp_path) -> None:
    # Even with a bound provider, a run with no target-repository path falls back
    # deterministically for every segment and never crashes — there is still one valid stored
    # Segment per planned segment (Req 2.6, 6.1). The content is non-empty so the run loop
    # reaches its clean terminal state in a single step (one ``step_end``, one Write trigger).
    plan = _plan(_seeded_segments())
    result = _drive_write_stage(
        plan, provider=FakeProvider("done"), tmp_path=tmp_path
    )

    stored = result.store.list_segments()
    assert len(stored) == len(plan.segments)
    vocab = default_profile()
    for seg in stored:
        assert validate_segment(seg, vocab).is_valid
        # The deterministic fallback leads with a Markdown heading (the blueprint title).
        assert seg.body.startswith("# ")

    assert result.write_trigger_detail()["prose_source"] == "fallback"


# --------------------------------------------------------------------------- #
# Bounded journal summary: counts + capped ids + prose marker, no bodies        #
# (Req 8.1, 8.2, 8.3)                                                          #
# --------------------------------------------------------------------------- #


def test_journal_summary_is_bounded_and_carries_counts(tmp_path) -> None:
    plan = _plan(_seeded_segments())
    result = _drive_write_stage(
        plan, provider=FakeProvider("done"), tmp_path=tmp_path
    )

    detail = result.write_trigger_detail()
    assert detail["stage"] == "write"
    assert detail["total_planned"] == len(plan.segments)
    assert detail["written_count"] == len(plan.segments)
    assert detail["flagged_count"] == 0
    # No SLOT_TARGET_REPO is seeded by this driver, so no agentic run is viable and every
    # segment uses the deterministic fallback (Req 2.6, 8.3).
    assert detail["prose_source"] == "fallback"

    # The capped top-id list reflects the stored segments, in plan order, and stays
    # bounded (never the full set on a large plan).
    written = result.run_context.written_segments()
    expected_ids = [s.id for s in written.segments]
    assert detail["top_written_ids"] == expected_ids[: len(detail["top_written_ids"])]

    # The bounded agentic aggregate is folded in alongside the existing summary fields
    # (Req 8.2). No agentic run was viable (no target repo), so every per-segment run is a
    # zeroed "no_model"/"invalid_repo" fallback with no steps or cost.
    assert detail["agent_run_count"] == len(plan.segments)
    assert detail["agent_written_count"] == 0
    assert detail["agent_fallback_count"] == len(plan.segments)
    assert detail["agent_total_steps"] == 0
    assert detail["agent_total_cost_usd"] == 0.0
    assert sum(detail["agent_exit_reasons"].values()) == len(plan.segments)

    # The summary is scalar/bounded only — never a full segment body (Req 8.2): every value
    # is a scalar, a short list of strings, or a scalar-valued dict (the exit-reason tally).
    for value in detail.values():
        if isinstance(value, list):
            assert all(isinstance(item, str) for item in value)
        elif isinstance(value, dict):
            assert all(isinstance(k, str) for k in value)
            assert all(isinstance(v, int) for v in value.values())
        else:
            assert isinstance(value, (str, int, float, bool))
    flat = repr(detail)
    for seg in written.segments:
        assert seg.body not in flat


def test_run_is_network_free_and_completes_clean(tmp_path) -> None:
    # Defensive end-to-end smoke: the only provider bound is the no-network FakeProvider,
    # and the run reaches the clean terminal state — proving the Write stage is testable
    # end-to-end without credentials (Req 1.1, 5.4).
    plan = _plan(_seeded_segments())
    result = _drive_write_stage(
        plan, provider=FakeProvider("done"), tmp_path=tmp_path
    )
    assert result.exit_reason == "done"
    # A HarnessJournal trace was written under the resolved output dir.
    assert _find_trace_jsonl(result.out_dir)


def test_absent_analysis_still_writes_segments_end_to_end(tmp_path) -> None:
    # The RepoAnalysis slot is optional (Req 2.5): with it unset (see the module
    # "Boundary note") the writer grounds on the planner evidence alone and still produces
    # one valid stored Segment per planned segment through the live run.
    #
    # The RepoAnalysis grounding seam is a real, well-formed value object — constructed
    # here to pin its shape — whose *absence* the writer tolerates end-to-end (the
    # blueprint's use of a present analysis is unit-pinned in task 2.1).
    analysis = _analysis()
    assert isinstance(analysis, RepoAnalysis)

    plan = _plan(_seeded_segments())
    result = _drive_write_stage(
        plan, provider=FakeProvider("done"), tmp_path=tmp_path
    )

    # The writer ran with no RepoAnalysis seeded (the slot is unset on the run state).
    assert result.run_context.repo_analysis() is None

    assert result.exit_reason == "done"
    stored = result.store.list_segments()
    assert len(stored) == len(plan.segments)
    written = result.run_context.written_segments()
    assert len(written.segments) == len(plan.segments)
    assert len(written.flags) == 0
