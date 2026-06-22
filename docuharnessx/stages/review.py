"""The real Review stage adapter (quality-review-gate task 4.1 boundary: ReviewStage).

The Review stage is the **COBESY quality firewall**: it evaluates each written ontology
:class:`~docuharnessx.ontology.Segment` the upstream ``cobesy-writer`` published against the
fixed COBESY validation gate (MECE, working-memory fit, role-fit, clarity,
falsifiability/evidence, no-AI-slop) and gates which segments proceed to assembly. It is a
**thin HarnessX adapter** over the pure, model-free review core (:mod:`docuharnessx.review`):
all structural work (criteria definition, judge-prompt assembly, response parsing, verdict
computation, accept/reject, aggregation, report assembly) is deterministic and the only
model-touching step is the gated :func:`docuharnessx.review.judge_segment`. This module
merely wires that core into the run lifecycle (design "deterministic review core + thin
gated stage adapter"), exactly mirroring :class:`~docuharnessx.stages.write.WriteStage` and
:class:`~docuharnessx.stages.plan.PlanStage`.

It replaces the former no-op stub **in place**: the ``STAGE_NAME`` constant (``"review"``),
the :class:`ReviewStage` class name, the :func:`make_review_stage` factory, the
``make_noop_stage`` re-export, the ``__all__`` set, and this module path are kept unchanged
so the stage registry and ``make_docgen`` need no edits — the real stage drops into exactly
the slot the stub occupied (Req 1.1, single-stage replaceability).

Lifecycle (same shape as :class:`~docuharnessx.stages.write.WriteStage`)
------------------------------------------------------------------------
Like every pipeline stage it does its work as a side effect of the **content-free**
``step_end`` event and yields that event **unchanged** (Req 1.4): ``StepEndEvent`` carries
no ``messages``/content window, so a processor on :data:`PIPELINE_HOOK` is structurally
incapable of mutating generated content — the :class:`~docuharnessx.review.ReviewReport` is
published into a run-context *slot*, never into the conversation. The live run ``State`` is
captured from the ``TaskStartEvent`` in :meth:`on_task_start` (a pure pass-through) and
wrapped in a :class:`~docuharnessx.context.RunContext` from :meth:`on_step_end`.

Input boundary (Req 2.1-2.6)
----------------------------
With a bound run ``State`` the stage reads the five input slots through the typed
``RunContext`` accessors — the :class:`~docuharnessx.composition.WrittenSegments`
(``SLOT_WRITTEN_SEGMENTS``), the :class:`~docuharnessx.planning.CoveragePlan`
(``SLOT_COVERAGE_PLAN``), the optional :class:`~docuharnessx.analysis.model.RepoAnalysis`
(``SLOT_REPO_ANALYSIS``), the loaded ``Vocabulary`` (``SLOT_VOCABULARY``), and the
``SegmentStore`` handle (``SLOT_SEGMENT_STORE``) — pins
:data:`~docuharnessx.planning.COVERAGE_PLAN_SCHEMA_VERSION`, and raises
:class:`~docuharnessx.review.ReviewInputError` naming the cause when the written-segments
slot or the vocabulary slot is unset, or when the consumed plan declares an unsupported
version. It produces **no report** on that fatal path (Req 2.2-2.4), mirroring
:class:`~docuharnessx.composition.WriterInputError`. An absent ``RepoAnalysis`` is tolerated
— the criteria builder then grounds on the planner evidence alone (Req 2.5). All consumed
inputs are treated read-only (Req 2.6).

Driven outside a harness (no ``task_start`` to bind the run ``State`` — e.g. the generic
stage smoke suite) the stage has no ``State`` to read, so it forwards the event unchanged
and produces nothing, exactly like the no-op base (Req 1.3). It raises
:class:`ReviewInputError` only when it *has* a run ``State`` but a required input slot is
missing or unsupported.

Per-segment review (Req 5, 6, 7)
--------------------------------
A ``segment_id -> PlannedSegment`` lookup is built once from the ``CoveragePlan`` (matching
on the deterministic :func:`docuharnessx.composition.segment_id` the writer derived) for
evidence-anchor grounding. Then, for each written ``Segment`` in the written set's order
(Req 6.6): :func:`~docuharnessx.review.build_criteria` ->
:func:`~docuharnessx.review.build_request` -> the gated
:func:`~docuharnessx.review.judge_segment` (run off the run loop via
:func:`asyncio.to_thread` when a model is bound, mirroring
:meth:`WriteStage._prose_for`) -> :func:`~docuharnessx.review.compute_verdict`. A
model-less / failed / timed-out / unparseable judge yields the absent verdict, which the
verdict computer turns into the fail-closed default-reject with
``judge_source="unavailable"`` (Req 5.4, 6.3) — a quality firewall does not pass unjudged
content. Every written segment gets exactly one entry (Req 6.4). After the loop the ordered
entries + the written-segment identities are folded by
:func:`~docuharnessx.review.aggregate` / :func:`~docuharnessx.review.assemble_report` into
the frozen :class:`~docuharnessx.review.ReviewReport` published to ``SLOT_REVIEW_REPORT``
(Req 7.1, 7.4, 7.5). An empty written set yields a well-formed empty report (Req 6.5).

Model access (Req 5.2)
----------------------
The bound model, if any, is obtained from the runtime-injected ``ModelConfig`` exactly as
:meth:`~docuharnessx.stages.plan.PlanStage._relevance_model` and
:meth:`~docuharnessx.stages.write.WriteStage._writer_model` do — via a concrete, named
per-instance accessor (:meth:`_judge_model`) over ``getattr(self, "_model_config",
None).main``. The review core never constructs a provider itself; any failure to reach one
degrades to ``None`` so a misconfigured model can never abort the review (it falls back to
the deterministic default-reject path).

On completion with a bound run ``State`` the stage records its participation plus a
**bounded** review summary in the journal (Req 9.1-9.3) — the judged/accepted/rejected/
unavailable counts, a *capped* list of the top-priority accepted segment ids, and a
``judge_source`` breakdown marker (``model``/``fake``/``unavailable`` -> count) — reusing
the :class:`~docuharnessx.stages.base.NoOpStage` tracer resolution and never writing full
segment bodies or full judge prose to the trace. It is a no-op when no tracer is bound.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any, AsyncIterator

from harnessx.core.events import (
    Event,
    ProcessorTriggerEvent,
    StepEndEvent,
    TaskStartEvent,
)
from harnessx.core.processor import Processor

from docuharnessx.composition import segment_id
from docuharnessx.context import RunContext
from docuharnessx.planning import COVERAGE_PLAN_SCHEMA_VERSION
from docuharnessx.review import (
    ReviewInputError,
    ReviewReport,
    aggregate,
    assemble_report,
    build_criteria,
    compute_verdict,
    judge_segment,
)
from docuharnessx.stages.base import (
    PIPELINE_HOOK,
    STAGE_PARTICIPATION_ACTION,
    NoOpStage,
    make_noop_stage,
)
from docuharnessx.types import (
    SLOT_COVERAGE_PLAN,
    SLOT_VOCABULARY,
    SLOT_WRITTEN_SEGMENTS,
)

if TYPE_CHECKING:  # typing only
    from harnessx.core.state import State

    from docuharnessx._ontology import SegmentStore, Vocabulary
    from docuharnessx.composition import WrittenSegments
    from docuharnessx.ontology import Segment
    from docuharnessx.planning import CoveragePlan
    from docuharnessx.planning.model import PlannedSegment
    from docuharnessx.review.model import SegmentReview

#: Canonical stage name, used as the stage-registry key and processor identity.
STAGE_NAME = "review"

__all__ = ["STAGE_NAME", "ReviewStage", "make_review_stage", "make_noop_stage"]

_log = logging.getLogger(__name__)

#: Upper bound on the number of accepted segment ids listed in the bounded journal
#: summary (Req 9.2). Keeps the trace bounded for a large accepted set while still naming
#: the top-priority accepted segments: ``ReviewReport.accepted`` is in the written set's
#: priority-desc order, so the head is the most important — only the first few ids are
#: recorded, never the full accepted list and never any segment body/judge prose.
_TOP_ACCEPTED_IDS_CAP: int = 5


class ReviewStage(NoOpStage):
    """Real Review stage: written ``Segment`` set -> COBESY gate -> frozen ``ReviewReport``.

    Subclasses :class:`NoOpStage` so it inherits the runtime binding
    (:meth:`_bind_runtime`), the tracer resolution, and the
    attach-to-:data:`PIPELINE_HOOK` contract — the registry and ``make_docgen`` treat it
    exactly like the stub it replaces (Req 1.1, 1.2). It overrides only ``on_task_start``
    (to capture the run ``State``) and ``on_step_end`` (to read + validate the review
    inputs, run the per-segment COBESY gate, and publish the frozen
    :class:`~docuharnessx.review.ReviewReport`), then yields the event unchanged (Req 1.4).
    """

    stage_name = STAGE_NAME

    #: The live run ``State`` captured from the ``TaskStartEvent``; ``None`` until the task
    #: starts (e.g. when ``on_step_end`` is unit-driven without a task), so a harness-free
    #: smoke run forwards the event unchanged (Req 1.3).
    _run_state: "State | None" = None

    async def on_task_start(self, event: TaskStartEvent) -> AsyncIterator[Event]:
        """Capture the live run ``State``, then forward the event unchanged.

        ``TaskStartEvent`` carries the mutable run ``State`` (``StepEndEvent`` does not).
        We stash it so :meth:`on_step_end` can read the input slots and publish the report.
        Pure pass-through — no field on the event is modified; the same mechanism the
        Classify/Analyze/Plan/Write stages use.
        """
        self._run_state = event.state
        yield event

    async def on_step_end(self, event: StepEndEvent) -> AsyncIterator[Event]:
        """Read + validate the review inputs, run the COBESY gate, then forward the event.

        Reads the :class:`~docuharnessx.composition.WrittenSegments`, the
        :class:`~docuharnessx.planning.CoveragePlan`, the optional
        :class:`~docuharnessx.analysis.model.RepoAnalysis`, the loaded ``Vocabulary``, and
        the ``SegmentStore``; pins
        :data:`~docuharnessx.planning.COVERAGE_PLAN_SCHEMA_VERSION` and raises
        :class:`ReviewInputError` naming the cause on a missing written-segments/vocabulary
        slot or an unsupported plan version, producing no report (Req 2.1-2.4). Judges every
        written segment in written order, assembles the frozen
        :class:`~docuharnessx.review.ReviewReport`, and publishes it to
        ``SLOT_REVIEW_REPORT`` (Req 7.1). Yields the *same* ``StepEndEvent`` back, modifying
        no generated content (Req 1.4).

        Driven outside a harness (no run ``State`` bound) it forwards the event unchanged and
        produces nothing, exactly like the no-op base (Req 1.3) — never raising there, so the
        generic stage smoke tests stay valid.
        """
        _log.debug("stage participated: %s", self.stage_name)

        run_context = self._resolve_run_context()
        if run_context is None:
            # No run State bound (driven outside a harness): nothing to read or write.
            yield event
            return

        # Read + validate the review inputs; raises ReviewInputError (no report) on a
        # missing required slot or an unsupported plan version (Req 2.1-2.4).
        written, plan, analysis, vocab, store = self._read_inputs(run_context)

        # The bound model, if any, reached via the named per-instance accessor mirroring
        # PlanStage._relevance_model / WriteStage._writer_model (Req 5.2). It is absent on
        # the credential-free path; the per-segment gate then default-rejects (fail-closed).
        model = self._judge_model()

        report = await self._review_segments(written, plan, analysis, vocab, model)
        run_context.set_review_report(report)

        # Record participation + a bounded review summary in the journal (Req 9.1-9.3):
        # the judged/accepted/rejected/unavailable counts, a capped list of top-priority
        # accepted ids, and a judge-source breakdown marker — never full bodies/judge prose.
        await self._journal_participation(event, report)

        # Pure pass-through: forward the content-free event unchanged (Req 1.4).
        yield event

    # ------------------------------------------------------------------ #
    # Helpers                                                            #
    # ------------------------------------------------------------------ #

    def _resolve_run_context(self) -> RunContext | None:
        """Wrap the live run ``State`` (captured at ``task_start``) in a RunContext.

        Returns ``None`` when no ``State`` was captured (the stage is being driven outside a
        harness, with no preceding ``task_start``), so the caller forwards the event
        unchanged instead of failing (Req 1.3).
        """
        state = self._run_state
        if state is None:
            return None
        return RunContext(state)

    def _read_inputs(
        self, run_context: RunContext
    ) -> "tuple[WrittenSegments, CoveragePlan, Any, Vocabulary, SegmentStore | None]":
        """Read + validate the five input slots; raise on a fatal input error.

        Reads the :class:`~docuharnessx.composition.WrittenSegments`
        (``SLOT_WRITTEN_SEGMENTS``), the :class:`~docuharnessx.planning.CoveragePlan`
        (``SLOT_COVERAGE_PLAN``), the optional
        :class:`~docuharnessx.analysis.model.RepoAnalysis` (``SLOT_REPO_ANALYSIS``), the
        loaded ``Vocabulary`` (``SLOT_VOCABULARY``), and the ``SegmentStore`` handle
        (``SLOT_SEGMENT_STORE``) through the typed ``RunContext`` accessors (Req 2.1).
        Pins :data:`COVERAGE_PLAN_SCHEMA_VERSION` and raises :class:`ReviewInputError`
        naming the cause when the written-segments slot or the vocabulary slot is unset, or
        when the plan declares an unsupported version, producing no report (Req 2.2-2.4).
        The ``RepoAnalysis`` is optional — an unset slot is returned as ``None`` and
        tolerated by the criteria builder (Req 2.5).
        """
        written = run_context.written_segments()
        if written is None:
            raise ReviewInputError(
                "Review stage cannot run: the written-segments slot "
                f"'{SLOT_WRITTEN_SEGMENTS}' is unset (the Write stage did not publish a "
                "WrittenSegments). No review report was produced."
            )

        vocab = run_context.vocabulary()
        if vocab is None:
            raise ReviewInputError(
                "Review stage cannot run: the vocabulary slot "
                f"'{SLOT_VOCABULARY}' is unset (no project vocabulary was loaded). "
                "No review report was produced."
            )

        # The CoveragePlan supplies the per-segment evidence anchors. Pin its schema version
        # (Req 2.2): halt loudly on a version this build does not support. An absent plan is
        # tolerated (the criteria builder grounds on segment content alone) — but a present
        # plan with the wrong version is a contract mismatch, not a silent guess.
        plan = run_context.coverage_plan()
        if plan is not None and plan.schema_version != COVERAGE_PLAN_SCHEMA_VERSION:
            raise ReviewInputError(
                "Review stage cannot run: the CoveragePlan declares unsupported "
                f"schema_version {plan.schema_version!r} (this build supports "
                f"{COVERAGE_PLAN_SCHEMA_VERSION!r}). No review report was produced."
            )

        # The RepoAnalysis is optional (Req 2.5): an absent slot is tolerated and the
        # criteria builder grounds on the planner evidence alone.
        analysis = run_context.repo_analysis()

        # The SegmentStore handle is read for completeness/consistency (Req 2.1); the
        # accepted-set identities come from the written set itself, so an absent store does
        # not abort the review.
        store = run_context.segment_store()

        return written, plan, analysis, vocab, store

    # ------------------------------------------------------------------ #
    # Per-segment review orchestration (Req 5, 6, 7)                      #
    # ------------------------------------------------------------------ #

    async def _review_segments(
        self,
        written: "WrittenSegments",
        plan: "CoveragePlan | None",
        analysis: Any,
        vocab: "Vocabulary",
        model: Any | None,
    ) -> ReviewReport:
        """Judge every written segment in order and assemble the frozen report.

        Builds a ``segment_id -> PlannedSegment`` lookup once (matching on the deterministic
        :func:`docuharnessx.composition.segment_id`), then for each written ``Segment`` in
        the written set's order (Req 6.6) builds the deterministic COBESY criteria, runs the
        gated judge off the run loop when a model is bound, and computes the per-segment
        verdict — one entry per segment (Req 6.4). Folds the entries + the written-segment
        identities into the frozen :class:`~docuharnessx.review.ReviewReport` (Req 7.1, 7.4,
        7.5). An empty written set yields a well-formed empty report (Req 6.5).
        """
        plan_by_id = self._plan_lookup(plan)

        entries: list[SegmentReview] = []
        by_id: dict[str, Segment] = {}
        for segment in written.segments:
            planned = plan_by_id.get(segment.id)
            criteria = build_criteria(segment, planned, analysis, vocab)
            verdict = await self._judge(criteria, model)
            judge_source = "unavailable" if verdict is None else "model"
            entries.append(
                compute_verdict(verdict, criteria, judge_source=judge_source)
            )
            by_id[segment.id] = segment

        return assemble_report(tuple(entries), by_id)

    @staticmethod
    def _plan_lookup(plan: "CoveragePlan | None") -> "dict[str, PlannedSegment]":
        """Build the ``segment_id -> PlannedSegment`` lookup for evidence anchoring.

        The writer derives each written ``Segment.id`` from
        :func:`docuharnessx.composition.segment_id` of its planned segment, so matching on
        that id reunites a written segment with its planner evidence (Req 3.3). An absent
        plan yields an empty lookup — every written segment then gets criteria with empty
        evidence anchors and is still judged (never dropped).
        """
        if plan is None:
            return {}
        return {segment_id(planned): planned for planned in plan.segments}

    async def _judge(
        self, criteria: Any, model: Any | None
    ) -> Any:
        """Run the gated judge step, off the run loop when a model is consulted.

        :func:`docuharnessx.review.judge_segment` is *synchronous*: when it consults a model
        it drives the provider's awaitable ``complete`` on a private loop via ``asyncio.run``.
        Because ``on_step_end`` runs inside the harness run loop, calling that bridge
        directly would nest ``asyncio.run`` inside a running loop and raise. We therefore
        offload to a worker thread via :func:`asyncio.to_thread` when a model is bound
        (mirroring :meth:`WriteStage._prose_for` and
        :meth:`PlanStage._maybe_apply_relevance`). With no model bound there is no async
        work — ``judge_segment`` returns ``None`` immediately — so we take it inline. All
        judge failures/timeouts are absorbed inside ``judge_segment`` (it never raises); a
        ``None`` verdict is the fail-closed default-reject signal for the caller (Req 5.4).
        """
        if model is None:
            return judge_segment(criteria, model=None)
        return await asyncio.to_thread(judge_segment, criteria, model=model)

    def _judge_model(self) -> Any | None:
        """Return the bound main model provider for the gated judge step, or ``None``.

        The bound model, if any, comes from the parent ``ModelConfig`` injected at
        ``Harness.__init__`` via ``_bind_model_config`` — obtained here through a concrete,
        named per-instance accessor exactly as
        :meth:`~docuharnessx.stages.plan.PlanStage._relevance_model` and
        :meth:`~docuharnessx.stages.write.WriteStage._writer_model` (Req 5.2). The review
        core never constructs a provider itself. Any failure to reach a provider degrades to
        ``None`` so a misconfigured model can never abort the review — the per-segment gate
        then applies the fail-closed default-reject.
        """
        model_config = getattr(self, "_model_config", None)
        if model_config is None:
            return None
        try:
            return model_config.main
        except Exception:  # pragma: no cover - defensive: never gate the review
            return None

    # ------------------------------------------------------------------ #
    # Bounded journal summary + judge-source markers (Req 9.1-9.3)        #
    # ------------------------------------------------------------------ #

    async def _journal_participation(
        self, event: StepEndEvent, report: ReviewReport
    ) -> None:
        """Emit one participation trigger carrying a bounded review summary.

        Records this stage's participation in the run journal (Req 9.1) with a
        summary-level ``detail`` only — the stage name, the judged/accepted/rejected/
        unavailable counts, a *capped* list of the top-priority accepted segment ids, and
        a ``judge_source`` breakdown marker (``model``/``fake``/``unavailable`` -> count,
        Req 9.3). Full segment bodies and full judge prose are **never** written to the
        trace, keeping it bounded for large repos (Req 9.2). Reuses the
        :class:`~docuharnessx.stages.base.NoOpStage` tracer resolution and is a no-op when
        no tracer is bound (driven outside a journaling harness).
        """
        tracer = self._resolve_tracer()
        if tracer is None:
            return
        on_event = getattr(tracer, "on_event", None)
        if on_event is None:
            return
        await on_event(
            ProcessorTriggerEvent(
                run_id=event.run_id,
                step_id=event.step_id,
                processor=type(self).__name__,
                hook=PIPELINE_HOOK,
                action=STAGE_PARTICIPATION_ACTION,
                detail=self._summary_detail(report),
            )
        )

    def _summary_detail(self, report: ReviewReport) -> dict[str, Any]:
        """Build the bounded, scalar-only summary recorded on the journal trigger.

        Summary-level fields only (Req 9.2): the stage name, the aggregate
        judged/accepted/rejected/unavailable counts (read verbatim from the published
        :class:`~docuharnessx.review.ReviewAggregate` so the journal and the seam never
        disagree), a *capped* list of the top-priority accepted segment ids (the accepted
        set is already in the written set's priority-desc order, so the head is the most
        important), and a ``judge_source`` breakdown marker — a ``{source: count}`` map of
        scalar values across the per-segment entries (Req 9.3), so a credential-free /
        fake / model-less run is auditable. No raw ``Segment`` objects, no segment bodies,
        and no judge prose, so the trace stays bounded for large reviews (Req 9.2).
        """
        agg = report.aggregate
        top_accepted_ids = [
            seg.id for seg in report.accepted[:_TOP_ACCEPTED_IDS_CAP]
        ]
        return {
            "stage": self.stage_name,
            "judged": agg.judged,
            "accepted": agg.accepted,
            "rejected": agg.rejected,
            "unavailable": agg.unavailable,
            "top_accepted_ids": top_accepted_ids,
            "judge_source": _judge_source_breakdown(report),
        }


def _judge_source_breakdown(report: ReviewReport) -> dict[str, int]:
    """Collapse the per-segment ``judge_source`` markers into one bounded breakdown.

    The bounded journal summary carries a ``judge_source`` marker so a credential-free
    run is auditable (Req 9.3): a ``{source: count}`` map naming each provenance present
    (``"model"`` / ``"fake"`` / ``"unavailable"``) and how many segments carried it. Only
    sources actually present are keyed, so an all-model run reports ``{"model": N}``, a
    fail-closed model-less run reports ``{"unavailable": N}``, and an empty review reports
    ``{}``. Pure, deterministic, scalar-valued; no segment body/prose is read.
    """
    breakdown: dict[str, int] = {}
    for entry in report.entries:
        breakdown[entry.judge_source] = breakdown.get(entry.judge_source, 0) + 1
    return breakdown


def make_review_stage() -> Processor:
    """Return a fresh real Review-stage processor (Req 1.1 stable factory)."""
    return ReviewStage()
