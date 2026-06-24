"""Cross-stage regression tests for the agentic-codebase-writer (task 5.3).

Task 5.3 is a **boundary: cross-stage regression** check. The ``agentic-codebase-writer``
swaps *only* the Write stage's per-segment prose surface (single-shot
``generate_prose`` -> the bounded :class:`~docuharnessx.composition.AgenticProseRunner`)
plus one idempotent ``mkdocs.yml`` Mermaid-fence enablement. Everything downstream of the
writer — the review gate, the assembler page/role rendering, and the deployer — consumes
the **unchanged** frozen ``WrittenSegments`` / ``Segment`` output seam and must require no
edit. The stage registry and the ``make_docgen`` bundle composition are likewise untouched
(single-stage swap). This file pins those invariants so a future regression that mutates
the seam shape, edits a downstream stage's public surface, or perturbs the registry/bundle
is caught here (Req 7.5, 9.5).

What this file asserts (boundary: cross-stage regression)
---------------------------------------------------------
1. **The frozen output seam is byte-identical in shape** — ``WrittenSegments`` carries
   exactly ``(segments, flags, total_planned)`` as a frozen value object, ``WriteFlag``
   exactly ``(segment_key, reason, cause)``, ``ProseResult`` exactly ``(body, summary,
   source)``, and the ontology ``Segment`` the writer wires carries exactly the
   nine documented fields. The same value type sits at the same run-context slot
   (``SLOT_WRITTEN_SEGMENTS``) the review gate reads (Req 7.1, 7.5).
2. **The single-stage swap left the registry + bundle untouched** — ``STAGES`` is the
   canonical eight-stage list, ``make_docgen`` composes the canonical pipeline order with
   ``WriteStage`` in the write slot, and the review/assemble/deploy stages keep their
   stable ``STAGE_NAME`` / class / factory / module path (Req 7.5, single-stage swap).
3. **The deterministic core stays model-free and unit-testable** — ``build_blueprint`` ->
   ``wire_segment`` -> ``render_fallback_body`` / ``render_fallback_summary`` produce a
   validate-clean ``Segment`` with **no model bound and no agent**, and a model-free
   ``WriteStage`` run over a seeded plan publishes a non-empty ``WrittenSegments`` the
   review gate consumes — proving the seam still flows end-to-end without credentials
   (Req 9.5).
4. **The writer feeds the review gate verbatim** — a model-free ``WriteStage`` run
   publishes a ``WrittenSegments`` whose stored ``Segment`` identities are the same ones
   the downstream ``ReviewStage`` then reads (the writer -> review seam handshake), with
   no edit to the review stage (Req 7.2, 7.5).

These tests are credential-free and (mostly) harness-free: the deterministic core is
driven directly, and the writer/review stages are driven through ``on_task_start`` ->
``on_step_end`` over a seeded run ``State`` exactly as the existing stage suites do
(``tests/test_stage_write_orchestration.py`` / ``tests/test_stage_review_replaceability.py``).
No network, no model resolver, no agent run.
"""

from __future__ import annotations

import asyncio
import dataclasses
import importlib
from typing import Any

from harnessx.core.events import StepEndEvent, TaskStartEvent
from harnessx.core.state import State

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
    Segment,
    Subject,
    default_profile,
    validate_segment,
)
from docuharnessx.planning import COVERAGE_PLAN_SCHEMA_VERSION, CoveragePlan
from docuharnessx.planning.model import PlannedSegment
from docuharnessx.types import SLOT_WRITTEN_SEGMENTS


# --------------------------------------------------------------------------- #
# Shared fixtures: a default-profile plan + seeded run State (no model)         #
# --------------------------------------------------------------------------- #


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


def _seed_write_state(
    planned: tuple[PlannedSegment, ...], *, run_id: str
) -> tuple[State, InMemorySegmentStore]:
    """Seed the inputs the Write stage reads: plan + vocab + store (NO model, NO repo).

    Deliberately leaves the target-repo slot unset so the writer takes the deterministic
    fallback for every segment without attempting an agentic run — the credential-free
    deterministic-core path (Req 9.5, 2.6).
    """
    vocab = default_profile()
    store = InMemorySegmentStore(vocab)
    state = State(run_id=run_id)
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
    return state, store


def _sample_event(run_id: str) -> StepEndEvent:
    return StepEndEvent(
        run_id=run_id,
        step_id=7,
        step_summary="prior summary",
        tool_call_summary="readFile(a)",
        cumulative_tokens=10,
        cumulative_cost_usd=0.1,
    )


def _start_task(stage: Any, state: State) -> None:
    async def _collect() -> None:
        async for _ in stage.on_task_start(
            TaskStartEvent(run_id=state.run_id, step_id=0, state=state)
        ):
            pass

    asyncio.run(_collect())


def _drive_step_end(stage: Any, event: StepEndEvent) -> list[Any]:
    async def _collect() -> list[Any]:
        return [out async for out in stage.on_step_end(event)]

    return asyncio.run(_collect())


def _run_writer_no_model(
    planned: tuple[PlannedSegment, ...], *, run_id: str
) -> tuple[WrittenSegments, State, InMemorySegmentStore]:
    """Drive the real WriteStage with NO model bound; return its published seam + state."""
    from docuharnessx.stages.write import make_write_stage

    state, store = _seed_write_state(planned, run_id=run_id)
    stage = make_write_stage()
    _start_task(stage, state)
    out = _drive_step_end(stage, _sample_event(run_id))
    assert len(out) == 1  # the content-free event is forwarded unchanged (Req 1.4)
    written = RunContext(state).written_segments()
    assert written is not None
    return written, state, store


# =========================================================================== #
# 1. The frozen output seam is byte-identical in shape (Req 7.1, 7.5)           #
# =========================================================================== #


def test_written_segments_is_frozen_with_exact_field_shape() -> None:
    # The review gate / assembler consume WrittenSegments verbatim: its frozen field
    # shape must not drift. Exactly (segments, flags, total_planned), frozen (Req 7.1).
    assert dataclasses.is_dataclass(WrittenSegments)
    params = getattr(WrittenSegments, "__dataclass_params__")
    assert params.frozen is True
    field_names = tuple(f.name for f in dataclasses.fields(WrittenSegments))
    assert field_names == ("segments", "flags", "total_planned")


def test_write_flag_is_frozen_with_exact_field_shape() -> None:
    # Every planned segment is represented as a written segment or a WriteFlag (Req 7.4);
    # the flag's shape is part of the seam the review gate audits.
    assert dataclasses.is_dataclass(WriteFlag)
    assert getattr(WriteFlag, "__dataclass_params__").frozen is True
    field_names = tuple(f.name for f in dataclasses.fields(WriteFlag))
    assert field_names == ("segment_key", "reason", "cause")


def test_prose_result_is_frozen_and_body_only() -> None:
    # ProseResult carries only body/summary/source: the agent contributes body+summary,
    # never any non-body Segment field (Req 7.3). Pinned so the prose-surface swap cannot
    # widen this contract.
    assert dataclasses.is_dataclass(ProseResult)
    assert getattr(ProseResult, "__dataclass_params__").frozen is True
    field_names = tuple(f.name for f in dataclasses.fields(ProseResult))
    assert field_names == ("body", "summary", "source")


def test_segment_field_shape_is_unchanged() -> None:
    # The ontology Segment the writer wires is the unit the review gate / assembler render.
    # Its nine documented fields must not drift under the prose-surface swap (Req 7.3, 7.5).
    field_names = tuple(f.name for f in dataclasses.fields(Segment))
    assert field_names == (
        "id",
        "title",
        "roles",
        "subjects",
        "intent",
        "summary",
        "related",
        "body",
        "schema_version",
    )


def test_seam_value_type_and_slot_are_unchanged() -> None:
    # The same value type sits at the same run-context slot the review gate reads
    # (SLOT_WRITTEN_SEGMENTS) — the publish/consume seam handshake (Req 7.1).
    assert SLOT_WRITTEN_SEGMENTS == "docuharnessx.written_segments"
    state = State(run_id="seam-slot")
    value = WrittenSegments(segments=(), flags=(), total_planned=0)
    RunContext(state).set_written_segments(value)
    slot = state.get_slot(SLOT_WRITTEN_SEGMENTS)
    assert slot is not None
    assert slot.content is value
    assert isinstance(slot.content, WrittenSegments)


# =========================================================================== #
# 2. Single-stage swap: registry + bundle + downstream stages untouched (7.5)   #
# =========================================================================== #


def test_stage_registry_is_canonical_eight_stage_order() -> None:
    # The single-stage swap edits only the write module; the registry list is unchanged.
    from docuharnessx.stages import STAGES

    assert [name for name, _ in STAGES] == [
        "ingest",
        "analyze",
        "classify",
        "plan",
        "write",
        "review",
        "assemble",
        "deploy",
    ]


def test_make_docgen_composes_canonical_pipeline_with_write_in_slot() -> None:
    # The bundle composition is untouched: make_docgen still composes the canonical
    # eight-stage pipeline, with WriteStage in the write slot, downstream stages intact.
    from docuharnessx.bundle import make_docgen

    config = make_docgen(journal_dir="/tmp/dhx-cross-stage-5-3-out")

    def _is_stage_target(target: str) -> bool:
        if not target.startswith("docuharnessx.stages."):
            return False
        module_path, _, class_name = target.rpartition(".")
        return module_path != "docuharnessx.stages.base" and class_name.endswith(
            "Stage"
        )

    stage_classes = [
        p["_target_"].rsplit(".", 1)[1]
        for p in config.processors
        if isinstance(p, dict) and _is_stage_target(p.get("_target_", ""))
    ]
    assert stage_classes == [
        "IngestStage",
        "AnalyzeStage",
        "ClassifyStage",
        "PlanStage",
        "WriteStage",
        "ReviewStage",
        "AssembleStage",
        "DeployStage",
    ]


def test_downstream_stage_public_surfaces_are_stable() -> None:
    # The agentic-codebase-writer requires no change to review/assemble/deploy: their
    # stable STAGE_NAME / class / factory / module path are pinned here (Req 7.5).
    expected = {
        "docuharnessx.stages.review": ("review", "ReviewStage", "make_review_stage"),
        "docuharnessx.stages.assemble": (
            "assemble",
            "AssembleStage",
            "make_assemble_stage",
        ),
        "docuharnessx.stages.deploy": ("deploy", "DeployStage", "make_deploy_stage"),
    }
    for module_path, (name, cls_name, factory_name) in expected.items():
        module = importlib.import_module(module_path)
        assert module.__name__ == module_path
        assert module.STAGE_NAME == name
        cls = getattr(module, cls_name)
        assert cls.__name__ == cls_name
        assert cls.stage_name == name
        factory = getattr(module, factory_name)
        assert factory.__name__ == factory_name
        assert isinstance(factory(), cls)
        # The no-op re-export is retained so the registry's import surface is unchanged.
        assert "make_noop_stage" in module.__all__


def test_write_stage_public_surface_is_stable() -> None:
    # The write module keeps its stable contract through the prose-surface swap (Req 1.1):
    # STAGE_NAME / WriteStage / make_write_stage / module path unchanged.
    import docuharnessx.stages.write as write_module
    from docuharnessx.stages.write import STAGE_NAME, WriteStage, make_write_stage

    assert STAGE_NAME == "write"
    assert WriteStage.__name__ == "WriteStage"
    assert WriteStage.stage_name == "write"
    assert make_write_stage.__name__ == "make_write_stage"
    assert write_module.__name__ == "docuharnessx.stages.write"
    assert isinstance(make_write_stage(), WriteStage)
    assert "make_noop_stage" in write_module.__all__


# =========================================================================== #
# 3. The deterministic core stays model-free and unit-testable (Req 9.5)        #
# =========================================================================== #


def test_deterministic_core_wires_a_valid_segment_without_a_model() -> None:
    # build_blueprint -> render_fallback_* -> wire_segment produces a validate-clean
    # Segment with no model bound and no agent run — the deterministic core is fully
    # unit-testable offline (Req 9.5). This is the path the writer falls back to.
    vocab = default_profile()
    planned = _three_planned()[0]
    blueprint = build_blueprint(planned, None, vocab)

    prose = ProseResult(
        body=render_fallback_body(blueprint),
        summary=render_fallback_summary(blueprint),
        source="fallback",
    )
    segment = wire_segment(planned, blueprint, prose)

    # Every non-body field is fixed deterministically from the planned segment/blueprint
    # (Req 7.3); only body/summary come from the prose source.
    assert segment.id == segment_id(planned)
    assert segment.title == blueprint.title
    assert segment.roles == list(planned.roles)
    assert segment.subjects == list(planned.subjects)
    assert segment.intent == planned.intent
    assert segment.related == []
    assert segment.body == prose.body
    assert segment.summary == prose.summary

    # The wired segment validates clean against the loaded vocabulary (no model needed).
    result = validate_segment(segment, vocab)
    assert result.is_valid, [str(e) for e in result.errors]


def test_deterministic_core_is_reproducible_without_a_model() -> None:
    # Equal inputs yield equal blueprint + equal fallback body/summary on repeated calls —
    # two model-free runs produce byte-equal text (Req 9.5).
    vocab = default_profile()
    planned = _three_planned()[1]
    bp1 = build_blueprint(planned, None, vocab)
    bp2 = build_blueprint(planned, None, vocab)
    assert bp1 == bp2
    assert render_fallback_body(bp1) == render_fallback_body(bp2)
    assert render_fallback_summary(bp1) == render_fallback_summary(bp2)


def test_model_free_writer_run_publishes_non_empty_seam() -> None:
    # A model-free WriteStage run over a seeded plan (no repo, no model) falls back
    # deterministically for every segment and publishes a NON-EMPTY WrittenSegments seam —
    # the deterministic seam still flows end-to-end without credentials (Req 9.5, 6.3).
    planned = _three_planned()
    written, _state, store = _run_writer_no_model(planned, run_id="write-no-model")

    assert isinstance(written, WrittenSegments)
    assert written.total_planned == len(planned)
    # Every planned segment is represented as a written segment or a flag (auditable seam).
    assert len(written.segments) + len(written.flags) == len(planned)
    # The deterministic fallback yields valid segments, so all three are written.
    assert len(written.segments) == len(planned)
    assert written.flags == ()
    # The published identities are the same ones stored (Req 7.2, 7.4).
    written_ids = [s.id for s in written.segments]
    assert written_ids == [segment_id(p) for p in planned]
    stored_ids = {s.id for s in store.list_segments()}
    for seg in written.segments:
        assert seg.id in stored_ids


# =========================================================================== #
# 4. The writer feeds the review gate verbatim (Req 7.2, 7.5)                   #
# =========================================================================== #


def test_writer_to_review_seam_handshake_without_a_model() -> None:
    # The writer -> review seam: a model-free WriteStage run publishes WrittenSegments;
    # the downstream ReviewStage then reads exactly those identities with NO edit to the
    # review stage. Proves the unchanged seam is consumed end-to-end (Req 7.2, 7.5, 9.5).
    from docuharnessx.stages.review import make_review_stage

    planned = _three_planned()
    written, state, store = _run_writer_no_model(planned, run_id="write-then-review")

    # The review stage reads SLOT_WRITTEN_SEGMENTS + the same store, with no model bound
    # (fail-closed default-reject), driven over the SAME run State the writer published to.
    review = make_review_stage()
    # Bind a runtime so the journal path is a no-op-safe pass-through (mirrors review suite).
    class _RuntimeStub:
        tracer = None

    review._bind_runtime(_RuntimeStub())
    _start_task(review, state)
    out = _drive_step_end(review, _sample_event("write-then-review"))
    assert len(out) == 1  # the review stage forwards the content-free event unchanged

    report = RunContext(state).review_report()
    assert report is not None
    # The review report carries exactly the written segment identities the writer produced,
    # in written order — the unchanged seam consumed verbatim (Req 7.5).
    assert [e.segment_id for e in report.entries] == [s.id for s in written.segments]
    # The same store identities are reachable downstream (writer stored, review read).
    stored_ids = {s.id for s in store.list_segments()}
    for entry in report.entries:
        assert entry.segment_id in stored_ids
