"""Failure-handling and reproducibility tests for the Write stage (cobesy-writer task 4.2).

Where ``tests/test_stage_write_integration.py`` (task 4.1) pins the *happy* credential-free
end-to-end path (one valid stored ``Segment`` per planned segment, the populated
``SLOT_WRITTEN_SEGMENTS`` seam, the bounded journal record), this suite pins the
**failure and reproducibility** half of the Write stage's contract — driven through the
*same* genuine HarnessX run so the boundary under test stays the real
:class:`~docuharnessx.stages.write.WriteStage` firing on the live ``step_end`` hook, not a
hand-driven ``on_step_end`` (that direct-drive variant is task 3.2's
``tests/test_stage_write_orchestration.py``). It binds the no-network
:class:`tests._fakes.FakeProvider` onto the composed ``make_docgen`` bundle
(``ModelConfig(main=FakeProvider(...)).agentic(make_docgen(...))`` — the exact bind point
the ``dhx`` CLI uses), seeds the writer-input slots on the run ``State``, and runs the
pipeline once with a minimal ``BaseTask`` passed as ``_resume_state`` (mirroring
:func:`docuharnessx.cli.orchestrate_run`).

Failure handling (Req 6.2, 6.4, 6.5)
------------------------------------
* A planned segment that is **invalid** under the loaded ``Vocabulary`` (an unknown role)
  is recorded as a :class:`~docuharnessx.composition.WriteFlag` and *skipped*, while the
  other valid planned segments are still written (Req 6.2). The run never aborts.
* An injected :class:`~docuharnessx.ontology.IdConflictError` (the store already holds a
  segment whose id collides with the planned segment's deterministic id) is recorded as a
  flag rather than aborting the run, and the pre-seeded segment is never overwritten
  (Req 6.4).
* An **empty** ``CoveragePlan`` yields an empty written set (no segments, no flags) and
  completes the run cleanly with no error (Req 6.5).

Every planned segment is represented in ``segments`` *or* ``flags`` so the seam is
auditable (the ``WrittenSegments`` invariant; Req 6.6).

Reproducibility (Req 9.3, 6.6)
------------------------------
Two writer runs over an *equal* plan with the deterministic fallback (no usable model
prose) produce an **equal** ``WrittenSegments`` — equal ids, titles, bodies, summaries,
and order — proving a model-free run is fully reproducible (Req 9.3) and that processing
the plan in its existing order is deterministic across equal runs (Req 6.6). The
underlying deterministic blueprint is byte-stable for equal inputs as well.

Credential-free / network-free: every run binds only :class:`FakeProvider`; the upstream
ingest/analyze/classify/plan stages have no slots seeded, so they crash-skip (the run loop
absorbs a stage error and continues), which is exactly why this suite seeds the writer's
own inputs directly rather than running the full upstream chain — the boundary under test
is the Write stage. ``SLOT_REPO_ANALYSIS`` is intentionally left unset (an optional input,
Req 2.5): seeding it would re-activate the Classify -> Plan chain in the same ``step_end``
and overwrite this suite's hand-seeded ``CoveragePlan`` (see the task 4.1 "Boundary note").
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
from docuharnessx.composition import (
    ProseResult,
    WriteFlag,
    WrittenSegments,
    build_blueprint,
    render_fallback_body,
    render_fallback_summary,
    segment_id,
    wire_segment,
)
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
# Fixtures: planned segments / plans (vocabulary-consistent + invalid-by-role)  #
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


def _invalid_segment() -> PlannedSegment:
    """A planned segment whose role is unknown to the default vocabulary.

    The wired ``Segment`` therefore fails ``validate_segment`` against the loaded
    ``Vocabulary``, exercising the writer's deterministic flag-and-skip path (Req 6.2).
    """
    return _planned(
        key="ghost__extend__component-scanner",
        roles=("not-a-real-role",),
        intent="extend",
        subject_local="scanner",
        priority=30,
    )


def _plan(segments: tuple[PlannedSegment, ...]) -> CoveragePlan:
    return CoveragePlan(
        schema_version=COVERAGE_PLAN_SCHEMA_VERSION,
        repo_path="/repo/x",
        vocabulary_fingerprint="fp",
        segments=segments,
    )


# --------------------------------------------------------------------------- #
# Harness-faithful driver: bind FakeProvider, seed slots, run once             #
# (mirrors tests/test_stage_write_integration.py)                              #
# --------------------------------------------------------------------------- #


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

    def written(self) -> WrittenSegments:
        value = self.run_context.written_segments()
        assert isinstance(value, WrittenSegments)
        return value

    def write_trigger_detail(self) -> dict[str, Any]:
        """The bounded participation ``detail`` the Write stage recorded in the journal."""
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
    (...))`` — the exact bind point the ``dhx`` CLI uses — seeds the writer's required input
    slots on a fresh run ``State`` (mirroring :func:`docuharnessx.cli.orchestrate_run`), and
    drives one run via ``harness.run(task, _resume_state=state)`` so the Write stage fires on
    the live ``step_end`` hook reading those slots. ``SLOT_REPO_ANALYSIS`` is left unset (the
    optional input, Req 2.5) so the seeded plan stays authoritative.
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


def _seed_colliding_segment(
    store: InMemorySegmentStore, planned: PlannedSegment
) -> str:
    """Pre-seed *store* with a segment occupying *planned*'s deterministic id.

    Uses the same deterministic blueprint -> fallback -> wiring path the writer takes, so
    the pre-seeded segment's id is byte-identical to the id the writer will derive for
    *planned*. ``store.put`` therefore raises :class:`IdConflictError` for the writer's
    own segment, exercising the flag-not-fatal path (Req 6.4). Returns the colliding id.
    """
    vocab = default_profile()
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
    store.put(pre)
    return pre.id


# --------------------------------------------------------------------------- #
# Failure handling: invalid segment flagged + skipped, others written (Req 6.2) #
# --------------------------------------------------------------------------- #


def test_invalid_segment_is_flagged_and_others_still_written(tmp_path) -> None:
    invalid = _invalid_segment()
    valid_a, valid_b = _valid_segments()
    plan = _plan((invalid, valid_a, valid_b))

    result = _drive_write_stage(
        plan, provider=FakeProvider("done"), tmp_path=tmp_path
    )
    assert result.exit_reason == "done"  # the invalid segment never aborts the run

    written = result.written()
    assert written.total_planned == 3

    # The two valid segments are written; the invalid one is flagged and skipped (Req 6.2).
    assert len(written.segments) == 2
    assert [s.id for s in written.segments] == [
        segment_id(valid_a),
        segment_id(valid_b),
    ]
    vocab = default_profile()
    for seg in written.segments:
        assert validate_segment(seg, vocab).is_valid

    assert len(written.flags) == 1
    flag = written.flags[0]
    assert isinstance(flag, WriteFlag)
    assert flag.segment_key == invalid.segment_key
    assert flag.reason == "validation"
    assert flag.cause  # a non-empty, deterministic cause message

    # Only the two valid segments reached the store (the invalid one was skipped).
    assert {s.id for s in result.store.list_segments()} == {
        segment_id(valid_a),
        segment_id(valid_b),
    }

    # Every planned segment is represented in segments OR flags — the auditable seam.
    assert len(written.segments) + len(written.flags) == written.total_planned == 3

    # The bounded journal summary reflects the flagged count (Req 6.2, 8.2).
    detail = result.write_trigger_detail()
    assert detail["total_planned"] == 3
    assert detail["written_count"] == 2
    assert detail["flagged_count"] == 1


# --------------------------------------------------------------------------- #
# Failure handling: an id conflict is flagged, not fatal (Req 6.4)              #
# --------------------------------------------------------------------------- #


def test_id_conflict_is_flagged_not_fatal(tmp_path) -> None:
    vocab = default_profile()
    store = InMemorySegmentStore(vocab)
    valid_a, valid_b = _valid_segments()
    plan = _plan((valid_a, valid_b))

    # Pre-seed the store with a segment whose id collides with the FIRST planned segment's
    # deterministic id, so store.put raises IdConflictError for the writer's segment.
    colliding_id = _seed_colliding_segment(store, valid_a)

    result = _drive_write_stage(
        plan, provider=FakeProvider("done"), tmp_path=tmp_path, store=store
    )
    assert result.exit_reason == "done"  # the conflict never aborts the run

    written = result.written()
    assert written.total_planned == 2

    # The conflicting first segment is flagged; the second segment is still written (Req 6.4).
    assert len(written.flags) == 1
    flag = written.flags[0]
    assert isinstance(flag, WriteFlag)
    assert flag.segment_key == valid_a.segment_key
    assert flag.reason == "id_conflict"
    assert flag.cause

    assert [s.id for s in written.segments] == [segment_id(valid_b)]

    # The store holds the pre-seeded colliding segment plus the second written segment; the
    # writer never overwrote the pre-seeded id.
    stored_ids = {s.id for s in result.store.list_segments()}
    assert colliding_id in stored_ids
    assert segment_id(valid_b) in stored_ids
    assert len(result.store.list_segments()) == 2

    assert len(written.segments) + len(written.flags) == written.total_planned == 2


# --------------------------------------------------------------------------- #
# Failure handling: an empty plan yields an empty written set, no error (Req 6.5)#
# --------------------------------------------------------------------------- #


def test_empty_plan_yields_empty_written_set_no_error(tmp_path) -> None:
    plan = _plan(())

    result = _drive_write_stage(
        plan, provider=FakeProvider("done"), tmp_path=tmp_path
    )
    assert result.exit_reason == "done"  # completes cleanly with no error

    written = result.written()
    assert written.total_planned == 0
    assert written.segments == ()
    assert written.flags == ()

    # Nothing was stored, and the bounded journal still records the (zeroed) summary.
    assert result.store.list_segments() == ()
    detail = result.write_trigger_detail()
    assert detail["total_planned"] == 0
    assert detail["written_count"] == 0
    assert detail["flagged_count"] == 0
    assert detail["top_written_ids"] == []


# --------------------------------------------------------------------------- #
# Reproducibility: two model-free runs over an equal plan are byte-equal         #
# (Req 9.3, 6.6)                                                               #
# --------------------------------------------------------------------------- #


def test_two_model_free_runs_produce_equal_written_segments(tmp_path) -> None:
    plan = _plan(_valid_segments())

    def _run(tag: str) -> WrittenSegments:
        # A FakeProvider whose non-empty content carries no usable JSON body drives the
        # gated prose step to None, so every segment uses the DETERMINISTIC fallback body
        # — the model-free reproducibility path (Req 9.3). A fresh store per run isolates
        # the two runs.
        no_body = json.dumps({"summary": "no body field here"})
        result = _drive_write_stage(
            plan,
            provider=FakeProvider(no_body),
            tmp_path=tmp_path / tag,
            store=InMemorySegmentStore(default_profile()),
        )
        return result.written()

    w1 = _run("run-a")
    w2 = _run("run-b")

    # Equal ids, titles, bodies, summaries, and order across the two model-free runs.
    assert w1.total_planned == w2.total_planned
    assert [s.id for s in w1.segments] == [s.id for s in w2.segments]
    assert [s.title for s in w1.segments] == [s.title for s in w2.segments]
    assert [s.body for s in w1.segments] == [s.body for s in w2.segments]
    assert [s.summary for s in w1.segments] == [s.summary for s in w2.segments]
    assert w1.flags == w2.flags

    # The fallback bodies are non-empty Markdown (the blueprint title leads), proving the
    # equality above is over real rendered content, not two empty bodies.
    assert w1.segments  # the seeded plan produced segments
    for seg in w1.segments:
        assert seg.body.startswith("# ")
        assert seg.summary


def test_deterministic_blueprint_is_byte_stable() -> None:
    # The reproducibility above rests on the deterministic, model-free blueprint: equal
    # inputs (same PlannedSegment + Vocabulary, no analysis) yield an equal blueprint and
    # therefore byte-identical fallback body/summary (Req 9.3, 6.6).
    vocab = default_profile()
    planned = _valid_segments()[0]

    bp1 = build_blueprint(planned, None, vocab)
    bp2 = build_blueprint(planned, None, vocab)
    assert bp1 == bp2

    assert render_fallback_body(bp1) == render_fallback_body(bp2)
    assert render_fallback_summary(bp1) == render_fallback_summary(bp2)
