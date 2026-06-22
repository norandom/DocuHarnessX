"""The real Write stage adapter (cobesy-writer task 3.1 boundary: WriteStage).

The Write stage turns each :class:`~docuharnessx.planning.model.PlannedSegment` of the
frozen :class:`~docuharnessx.planning.model.CoveragePlan` into a written, COBESY-structured
ontology :class:`~docuharnessx.ontology.Segment`, filling the ``title``/``summary``/``body``
the planner deliberately left blank. It is a **thin HarnessX adapter** over the pure,
model-free composition core (:mod:`docuharnessx.composition`): all structural work
(blueprint, prompt, wiring, fallback) is deterministic and the only model-touching step is
the gated :func:`docuharnessx.composition.generate_prose`. This module merely wires that
core into the run lifecycle (design "deterministic composition core + thin gated stage
adapter"), exactly mirroring :class:`~docuharnessx.stages.plan.PlanStage`.

It replaces the former no-op stub **in place**: the ``STAGE_NAME`` constant
(``"write"``), the :class:`WriteStage` class name, the :func:`make_write_stage` factory,
the ``make_noop_stage`` re-export, the ``__all__`` set, and this module path are kept
unchanged so the stage registry and ``make_docgen`` need no edits — the real stage drops
into exactly the slot the stub occupied (Req 1.1, single-stage replaceability).

Lifecycle (same shape as :class:`~docuharnessx.stages.plan.PlanStage`)
----------------------------------------------------------------------
Like every pipeline stage it does its work as a side effect of the **content-free**
``step_end`` event and yields that event **unchanged** (Req 1.4): ``StepEndEvent`` carries
no ``messages``/content window, so a processor on :data:`PIPELINE_HOOK` is structurally
incapable of mutating generated content — the written set is published into a run-context
*slot* and the ``SegmentStore``, never into the conversation. The live run ``State`` is
reached the same way the Classify/Analyze/Plan stages do: it is captured from the
``TaskStartEvent`` in :meth:`on_task_start` (a pure pass-through) and wrapped in a
:class:`~docuharnessx.context.RunContext` from :meth:`on_step_end`.

Input boundary (this task, Req 2.1-2.4)
---------------------------------------
With a bound run ``State`` the stage reads the four input slots through the typed
``RunContext`` accessors — the :class:`CoveragePlan` (``SLOT_COVERAGE_PLAN``), the optional
:class:`~docuharnessx.analysis.model.RepoAnalysis` (``SLOT_REPO_ANALYSIS``), the loaded
``Vocabulary`` (``SLOT_VOCABULARY``), and the ``SegmentStore`` handle
(``SLOT_SEGMENT_STORE``) — pins :data:`~docuharnessx.planning.COVERAGE_PLAN_SCHEMA_VERSION`,
and raises :class:`~docuharnessx.composition.WriterInputError` naming the cause when the
plan slot, vocabulary slot, or store slot is unset, or when the consumed plan declares an
unsupported version. It produces **no partial output** on that fatal path (Req 2.2-2.4),
mirroring :class:`~docuharnessx.planning.model.PlanningInputError`. An absent
``RepoAnalysis`` is tolerated — the blueprint then grounds on the planner evidence alone
(Req 2.5).

Driven outside a harness (no ``task_start`` to bind the run ``State`` — e.g. the generic
stage smoke suite) the stage has no ``State`` to read, so it forwards the event unchanged
and writes nothing, exactly like the no-op base (Req 1.3). It raises
:class:`WriterInputError` only when it *has* a run ``State`` but a required input slot is
missing or unsupported.

Model access (Req 5.2)
----------------------
The bound model, if any, is obtained from the runtime-injected ``ModelConfig`` exactly as
:meth:`~docuharnessx.stages.plan.PlanStage._relevance_model` does — via a concrete, named
per-instance accessor (:meth:`_writer_model`) over ``getattr(self, "_model_config",
None).main``. The composition core never constructs a provider itself; any failure to
reach one degrades to ``None`` so a misconfigured model can never abort the write (it
falls back to the deterministic body).

The per-segment write orchestration (blueprint -> prompt -> gated prose -> fallback ->
wiring -> validate -> store -> publish ``WrittenSegments``) lands in task 3.2; this task
establishes the stable adapter shell and the input boundary it builds on.
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

from docuharnessx.composition import (
    ProseResult,
    WriteFlag,
    WriterInputError,
    WrittenSegments,
    build_blueprint,
    generate_prose,
    render_fallback_body,
    render_fallback_summary,
    wire_segment,
)
from docuharnessx.context import RunContext
from docuharnessx.ontology import IdConflictError, validate_segment
from docuharnessx.planning import COVERAGE_PLAN_SCHEMA_VERSION
from docuharnessx.stages.base import (
    PIPELINE_HOOK,
    STAGE_PARTICIPATION_ACTION,
    NoOpStage,
    make_noop_stage,
)
from docuharnessx.types import (
    SLOT_COVERAGE_PLAN,
    SLOT_SEGMENT_STORE,
    SLOT_VOCABULARY,
)

if TYPE_CHECKING:  # typing only
    from harnessx.core.state import State

    from docuharnessx._ontology import SegmentStore, Vocabulary
    from docuharnessx.composition import CompositionBlueprint
    from docuharnessx.ontology import Segment
    from docuharnessx.planning import CoveragePlan
    from docuharnessx.planning.model import PlannedSegment

#: Canonical stage name, used as the stage-registry key and processor identity.
STAGE_NAME = "write"

__all__ = ["STAGE_NAME", "WriteStage", "make_write_stage", "make_noop_stage"]

_log = logging.getLogger(__name__)

#: Upper bound on the number of written segment ids listed in the bounded journal
#: summary. The written set is already in the plan's priority-desc order, so the head is
#: the most important; only the first few ids are recorded, never the full set, keeping
#: the trace bounded for large repos (Req 8.2).
_TOP_WRITTEN_IDS_CAP: int = 5


class WriteStage(NoOpStage):
    """Real Write stage: ``CoveragePlan`` + ``Vocabulary`` + ``SegmentStore`` -> segments.

    Subclasses :class:`NoOpStage` so it inherits the runtime binding
    (:meth:`_bind_runtime`), the tracer resolution, and the
    attach-to-:data:`PIPELINE_HOOK` contract — the registry and ``make_docgen`` treat it
    exactly like the stub it replaces (Req 1.1, 1.2). It overrides only ``on_task_start``
    (to capture the run ``State``) and ``on_step_end`` (to read and validate the writer's
    inputs and, from task 3.2, run the per-segment write), then yields the event unchanged
    (Req 1.4).
    """

    stage_name = STAGE_NAME

    #: The live run ``State`` captured from the ``TaskStartEvent``; ``None`` until the
    #: task starts (e.g. when ``on_step_end`` is unit-driven without a task), so a
    #: harness-free smoke run forwards the event unchanged (Req 1.3).
    _run_state: "State | None" = None

    async def on_task_start(
        self, event: TaskStartEvent
    ) -> AsyncIterator[Event]:
        """Capture the live run ``State``, then forward the event unchanged.

        ``TaskStartEvent`` carries the mutable run ``State`` (``StepEndEvent`` does not).
        We stash it so :meth:`on_step_end` can read the input slots and publish the written
        set. Pure pass-through — no field on the event is modified; the same mechanism the
        Classify/Analyze/Plan stages use.
        """
        self._run_state = event.state
        yield event

    async def on_step_end(self, event: StepEndEvent) -> AsyncIterator[Event]:
        """Read + validate the writer inputs, run the write, then forward the event.

        Reads the :class:`CoveragePlan`, the optional
        :class:`~docuharnessx.analysis.model.RepoAnalysis`, the loaded ``Vocabulary``, and
        the ``SegmentStore`` from the run ``State``; pins
        :data:`~docuharnessx.planning.COVERAGE_PLAN_SCHEMA_VERSION` and raises
        :class:`WriterInputError` naming the cause on a missing plan/vocabulary/store slot
        or an unsupported plan version, producing no partial output (Req 2.1-2.4). Yields
        the *same* ``StepEndEvent`` back, modifying no generated content (Req 1.4).

        Driven outside a harness (no run ``State`` bound) it forwards the event unchanged
        and writes nothing, exactly like the no-op base (Req 1.3) — never raising there, so
        the generic stage smoke tests stay valid.
        """
        _log.debug("stage participated: %s", self.stage_name)

        run_context = self._resolve_run_context()
        if run_context is None:
            # No run State bound (driven outside a harness): nothing to read or write.
            # Forward the event unchanged, exactly like the no-op base.
            yield event
            return

        # Read + validate the writer inputs; raises WriterInputError (no partial output)
        # on a missing required slot or an unsupported plan version (Req 2.1-2.4).
        plan, analysis, vocab, store = self._read_inputs(run_context)

        # The deterministic model, if any, is reached via the named per-instance accessor
        # mirroring PlanStage._relevance_model (Req 5.2). It is absent on the
        # credential-free path; the per-segment step then falls back deterministically.
        model = self._writer_model()

        # Run the per-segment write in the plan's existing order (Req 6.6) and publish the
        # ordered WrittenSegments seam to SLOT_WRITTEN_SEGMENTS (Req 7.1, 7.4, 7.5). An
        # empty plan yields an empty written set and completes without error (Req 6.5).
        written, prose_source = await self._write_segments(
            plan, analysis, vocab, store, model
        )
        run_context.set_written_segments(written)

        # Record a bounded, summary-level participation trigger in the run journal
        # (counts + capped top ids + prose-source marker; never full bodies) — a no-op
        # when no tracer is bound (Req 8.1-8.3).
        await self._journal_participation(event, written, prose_source)

        # Pure pass-through: forward the content-free event unchanged (Req 1.4).
        yield event

    # ------------------------------------------------------------------ #
    # Helpers                                                            #
    # ------------------------------------------------------------------ #

    def _resolve_run_context(self) -> RunContext | None:
        """Wrap the live run ``State`` (captured at ``task_start``) in a RunContext.

        Returns ``None`` when no ``State`` was captured (the stage is being driven outside
        a harness, with no preceding ``task_start``), so the caller forwards the event
        unchanged instead of failing (Req 1.3).
        """
        state = self._run_state
        if state is None:
            return None
        return RunContext(state)

    def _read_inputs(
        self, run_context: RunContext
    ) -> "tuple[CoveragePlan, Any, Vocabulary, SegmentStore]":
        """Read + validate the four input slots; raise on a fatal input error.

        Reads the :class:`CoveragePlan` (``SLOT_COVERAGE_PLAN``), the optional
        :class:`~docuharnessx.analysis.model.RepoAnalysis` (``SLOT_REPO_ANALYSIS``), the
        loaded ``Vocabulary`` (``SLOT_VOCABULARY``), and the ``SegmentStore`` handle
        (``SLOT_SEGMENT_STORE``) through the typed ``RunContext`` accessors (Req 2.1).
        Pins :data:`COVERAGE_PLAN_SCHEMA_VERSION` and raises :class:`WriterInputError`
        naming the cause when the plan/vocabulary/store slot is unset or the plan declares
        an unsupported version, producing no partial output (Req 2.2-2.4). The
        ``RepoAnalysis`` is optional — an unset slot is returned as ``None`` and tolerated
        by the blueprint (Req 2.5).
        """
        plan = run_context.coverage_plan()
        if plan is None:
            raise WriterInputError(
                "Write stage cannot run: the coverage-plan slot "
                f"'{SLOT_COVERAGE_PLAN}' is unset (the Plan stage did not publish a "
                "CoveragePlan). No segments were written."
            )

        # Pin the consumed CoveragePlan schema version (Req 2.2): halt loudly on a
        # version this build does not support rather than guessing at a changed shape.
        if plan.schema_version != COVERAGE_PLAN_SCHEMA_VERSION:
            raise WriterInputError(
                "Write stage cannot run: the CoveragePlan declares unsupported "
                f"schema_version {plan.schema_version!r} (this build supports "
                f"{COVERAGE_PLAN_SCHEMA_VERSION!r}). No segments were written."
            )

        vocab = run_context.vocabulary()
        if vocab is None:
            raise WriterInputError(
                "Write stage cannot run: the vocabulary slot "
                f"'{SLOT_VOCABULARY}' is unset (no project vocabulary was loaded). "
                "No segments were written."
            )

        store = run_context.segment_store()
        if store is None:
            raise WriterInputError(
                "Write stage cannot run: the segment-store slot "
                f"'{SLOT_SEGMENT_STORE}' is unset (no SegmentStore handle was placed in "
                "the run context). No segments were written."
            )

        # The RepoAnalysis is optional (Req 2.5): an absent slot is tolerated and the
        # blueprint grounds on the planner evidence alone.
        analysis = run_context.repo_analysis()

        return plan, analysis, vocab, store

    # ------------------------------------------------------------------ #
    # Per-segment write orchestration (Req 5, 6, 7)                       #
    # ------------------------------------------------------------------ #

    async def _write_segments(
        self,
        plan: "CoveragePlan",
        analysis: Any,
        vocab: "Vocabulary",
        store: "SegmentStore",
        model: Any | None,
    ) -> "tuple[WrittenSegments, str]":
        """Write every planned segment in plan order and build the output seam.

        Iterates ``plan.segments`` in their existing (deterministic) order (Req 6.6):
        for each segment it builds the deterministic COBESY blueprint, runs the gated
        prose step (off the run loop when a model is consulted), falls back to the
        deterministic renderer when prose is unavailable, wires the ontology ``Segment``,
        validates it against the loaded ``Vocabulary``, and either stores it (adding it to
        the ordered written set, Req 6.1) or records a deterministic :class:`WriteFlag`
        and continues (Req 6.2, 6.4). An absent ``RepoAnalysis`` is tolerated — the
        blueprint grounds on the planner evidence alone (Req 2.5).

        Returns the ordered :class:`WrittenSegments` whose ``segments`` are the *same
        identities* handed to ``store.put`` (Req 7.4, 7.5) paired with the aggregate
        prose-source marker for the run (``"model"``/``"fallback"``/``"fake"``,
        Req 8.3). An empty plan yields an empty written set and the model-less
        ``"fallback"`` marker (Req 6.5). Every planned segment is represented in
        ``segments`` or ``flags``, so the seam is auditable.
        """
        written: list[Segment] = []
        flags: list[WriteFlag] = []
        sources: list[str] = []

        for planned in plan.segments:
            segment, source = await self._compose_segment(
                planned, analysis, vocab, model
            )
            sources.append(source)
            self._store_or_flag(segment, planned, store, vocab, written, flags)

        return (
            WrittenSegments(
                segments=tuple(written),
                flags=tuple(flags),
                total_planned=len(plan.segments),
            ),
            _aggregate_prose_source(sources, model_bound=model is not None),
        )

    async def _compose_segment(
        self,
        planned: "PlannedSegment",
        analysis: Any,
        vocab: "Vocabulary",
        model: Any | None,
    ) -> "tuple[Segment, str]":
        """Build the deterministic ``Segment`` for one planned segment (blueprint→wire).

        Builds the COBESY blueprint (deterministic, model-free), runs the gated prose
        step, and wires the ontology ``Segment``. The prose source provenance is recorded
        on the :class:`ProseResult`: ``"model"`` when the bound model returned a clean
        response, ``"fake"`` when a model *was* consulted but its response was unusable
        (so the deterministic fallback rendered the body), and ``"fallback"`` when no
        model was bound at all (Req 5.1, 5.4, 8.3). The model only ever contributes
        ``body``/``summary`` — every non-body field is fixed by :func:`wire_segment`
        (Req 5.5). Returns the wired ``Segment`` paired with that prose-source marker so
        the bounded journal summary can report it (Req 8.3).
        """
        blueprint = build_blueprint(planned, analysis, vocab)
        prose = await self._prose_for(blueprint, model)
        return wire_segment(planned, blueprint, prose), prose.source

    async def _prose_for(
        self, blueprint: "CompositionBlueprint", model: Any | None
    ) -> ProseResult:
        """Run the gated prose step, falling back deterministically when it returns ``None``.

        When a model is bound the synchronous :func:`generate_prose` (which drives the
        provider's awaitable ``complete`` on its own private loop) is offloaded to a worker
        thread via :func:`asyncio.to_thread` so loops never nest inside the run loop —
        exactly as :meth:`PlanStage._maybe_apply_relevance` (Req 5.1, 5.3). When no model
        is bound there is no async work, so the model-less gate is taken inline. A ``None``
        result (model-less, failed, timed-out, empty, or unparseable) renders the
        deterministic fallback (Req 5.4, 6.3); its ``source`` is ``"fake"`` when a model
        was consulted (the fake/recorded-provider case) and ``"fallback"`` when no model
        was bound at all (Req 8.3).
        """
        if model is None:
            return self._fallback_prose(blueprint, source="fallback")

        # A model will be consulted: run the synchronous generate_prose (with its own
        # asyncio.run) off the run loop's thread so loops never nest. generate_prose
        # absorbs its own failures/timeouts and returns None on any unusable response.
        result = await asyncio.to_thread(generate_prose, blueprint, model=model)
        if result is not None:
            return result
        return self._fallback_prose(blueprint, source="fake")

    @staticmethod
    def _fallback_prose(
        blueprint: "CompositionBlueprint", *, source: str
    ) -> ProseResult:
        """Render the deterministic fallback body/summary with the given provenance."""
        return ProseResult(
            body=render_fallback_body(blueprint),
            summary=render_fallback_summary(blueprint),
            source=source,
        )

    def _store_or_flag(
        self,
        segment: "Segment",
        planned: "PlannedSegment",
        store: "SegmentStore",
        vocab: "Vocabulary",
        written: "list[Segment]",
        flags: "list[WriteFlag]",
    ) -> None:
        """Validate + store one segment, or record a deterministic flag and continue.

        Validates ``segment`` against the loaded ``Vocabulary`` (Req 6.1): on any error a
        :class:`WriteFlag` (``reason="validation"``) is recorded and the segment is
        skipped (Req 6.2). On a valid segment, ``store.put`` is called; an
        :class:`IdConflictError` is recorded as a :class:`WriteFlag`
        (``reason="id_conflict"``) and the run continues rather than aborting (Req 6.4).
        A stored segment is appended to ``written`` (the same identity as stored, Req 7.4).
        """
        result = validate_segment(segment, vocab)
        if not result.is_valid:
            flags.append(
                WriteFlag(
                    segment_key=planned.segment_key,
                    reason="validation",
                    cause=str(result.errors[0]),
                )
            )
            return

        try:
            store.put(segment)
        except IdConflictError as exc:
            flags.append(
                WriteFlag(
                    segment_key=planned.segment_key,
                    reason="id_conflict",
                    cause=str(exc),
                )
            )
            return

        written.append(segment)

    def _writer_model(self) -> Any | None:
        """Return the bound main model provider for the gated prose step, or ``None``.

        The bound model, if any, comes from the parent ``ModelConfig`` injected at
        ``Harness.__init__`` via ``_bind_model_config`` — obtained here through a concrete,
        named per-instance accessor exactly as
        :meth:`~docuharnessx.stages.plan.PlanStage._relevance_model` (design "the bound
        model, if any, is obtained from the runtime"; Req 5.2). The composition core never
        constructs a provider itself. Any failure to reach a provider degrades to ``None``
        so a misconfigured model can never abort the write — the per-segment step then
        falls back to the deterministic body.
        """
        model_config = getattr(self, "_model_config", None)
        if model_config is None:
            return None
        try:
            return model_config.main
        except Exception:  # pragma: no cover - defensive: never gate the write
            return None

    # ------------------------------------------------------------------ #
    # Bounded journal summary (Req 8.1-8.3)                               #
    # ------------------------------------------------------------------ #

    async def _journal_participation(
        self, event: StepEndEvent, written: WrittenSegments, prose_source: str
    ) -> None:
        """Emit one participation trigger carrying a bounded write summary.

        Records this stage's participation in the run journal (Req 8.1) with a
        summary-level ``detail`` only — the stage name, the total planned-segment count,
        the written/flagged counts, a *capped* list of the top-priority written segment
        ids, and the aggregate ``prose_source`` marker (``model``/``fallback``/``fake``,
        Req 8.3). Full segment bodies/objects are **never** written to the trace, keeping
        it bounded for large repos (Req 8.2). Reuses the :class:`NoOpStage` tracer
        resolution and is a no-op when no tracer is bound (driven outside a journaling
        harness).
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
                detail=self._summary_detail(written, prose_source),
            )
        )

    def _summary_detail(
        self, written: WrittenSegments, prose_source: str
    ) -> dict[str, Any]:
        """Build the bounded, scalar-only summary recorded on the journal trigger.

        Summary-level fields only (Req 8.2): the stage name, the total planned count, the
        successfully-written count, the flagged/skipped count, a *capped* list of the
        top-priority written segment ids (the written set is already in the plan's
        priority-desc order, so the head is the most important), and the aggregate
        ``prose_source`` marker (Req 8.3). No raw ``Segment``/``ProseResult`` objects and
        no segment bodies, so the trace stays bounded for large plans (Req 8.2).
        """
        top_written_ids = [
            seg.id for seg in written.segments[:_TOP_WRITTEN_IDS_CAP]
        ]
        return {
            "stage": self.stage_name,
            "total_planned": written.total_planned,
            "written_count": len(written.segments),
            "flagged_count": len(written.flags),
            "top_written_ids": top_written_ids,
            "prose_source": prose_source,
        }


def _aggregate_prose_source(sources: list[str], *, model_bound: bool) -> str:
    """Collapse the per-segment prose sources into one deterministic run-level marker.

    The bounded journal summary carries a single ``prose_source`` marker
    (``model``/``fallback``/``fake``, Req 8.3). The collapse is deterministic and
    auditable: a run whose every segment used genuine model prose reports ``"model"``;
    a run where a model was consulted but at least one segment fell back to the
    deterministic renderer reports ``"fake"`` (the credential-free / recorded-provider
    case); a run with no model bound at all (so no segments, or every segment used the
    deterministic fallback) reports ``"fallback"``. This biases the marker toward the
    weakest provenance present so a credential-free run is never mislabeled as fully
    model-generated.
    """
    if not model_bound:
        return "fallback"
    if sources and all(source == "model" for source in sources):
        return "model"
    # A model was consulted but at least one segment did not yield clean model prose.
    return "fake"


def make_write_stage() -> Processor:
    """Return a fresh real Write-stage processor (Req 1.1 stable factory)."""
    return WriteStage()
