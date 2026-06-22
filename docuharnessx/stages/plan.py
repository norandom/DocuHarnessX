"""The real Plan stage adapter (task 4.3 boundary: PlanStage).

The Plan stage turns the intermediate
:class:`~docuharnessx.planning.model.Classification` the upstream ``ClassifyStage``
published (the derived typed subjects plus the activated role x intent coverage cells)
into the frozen, versioned :class:`~docuharnessx.planning.model.CoveragePlan` the Wave 2
``cobesy-writer`` consumes verbatim. It is a **thin HarnessX adapter** over the pure,
model-free planning core (:mod:`docuharnessx.planning`): all the real
decision-intelligence lives in the deterministic
:func:`docuharnessx.planning.plan_coverage`, and the only place a model may ever be
consulted is the optional, gated :func:`docuharnessx.planning.apply_relevance`
(annotate/re-rank only); this module merely wires those into the run lifecycle (design
"deterministic pipeline-stage adapters over a pure planning core").

Same lifecycle shape as :class:`~docuharnessx.stages.base.NoOpStage`, richer journal
(design "PlanStage", "Why work happens as a step_end side effect"). The stage does its
work as a **side effect of the content-free** ``step_end`` event and then yields that
event **unchanged**:

* ``StepEndEvent`` carries no ``messages``/content window, so a processor on
  :data:`PIPELINE_HOOK` is structurally incapable of mutating generated content — the
  plan is published into a run-context *slot*, never into the conversation;
* it reaches the live run :class:`~harnessx.core.state.State` the same way the
  Classify/Analyze stages do: ``StepEndEvent`` is content-free and carries no live
  state, but HarnessX *does* carry the mutable run ``State`` on
  :class:`~harnessx.core.events.TaskStartEvent`, with which a
  :class:`~harnessx.core.processor.MultiHookProcessor` (this stage's base) is driven
  once per task. The stage captures that ``State`` in :meth:`on_task_start` (a pure
  pass-through), wraps it in a :class:`~docuharnessx.context.RunContext` from
  :meth:`on_step_end`, reads ``classification()`` + ``vocabulary()`` and writes the
  produced :class:`CoveragePlan` to ``SLOT_COVERAGE_PLAN`` (Req 7.3);
* a missing classification or a missing vocabulary raises
  :class:`~docuharnessx.planning.model.PlanningInputError`, halting the run with a clear
  cause and **no** partial plan (Req 2.4);
* the core path requires **no** model binding — it is deterministic by construction
  (Req 8.1). The optional relevance hook is OFF by default and gated by an explicit
  per-instance flag (Req 8.5); any failure/timeout is absorbed and the deterministic
  plan is kept (Req 8.4);
* it records its participation plus a **bounded** plan summary in the journal —
  summary-level fields only (total segments, top-priority segment keys,
  ``relevance_applied``, an empty-plan ``empty_reason``), never the full plan (Req 9.2,
  9.3, 9.4).

Stable contract (Req 1.1): the ``STAGE_NAME`` constant, the :class:`PlanStage` class
name, the :func:`make_plan_stage` factory, and this module path are kept unchanged so
the stage registry and ``make_docgen`` need no edits — the real stage drops into exactly
the slot the no-op stub occupied (single-stage replaceability).

Driven outside a harness (no ``task_start`` to bind the run ``State`` — e.g. the generic
stage smoke suite that calls ``process`` directly) the stage has no ``State`` to read, so
it does nothing and forwards the event unchanged, exactly like the no-op base. It only
raises :class:`PlanningInputError` when it *has* a run ``State`` but a required input slot
is missing.
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

from docuharnessx.context import RunContext
from docuharnessx.planning import CoveragePlan, apply_relevance, plan_coverage
from docuharnessx.planning.model import PlanningInputError
from docuharnessx.stages.base import (
    PIPELINE_HOOK,
    STAGE_PARTICIPATION_ACTION,
    NoOpStage,
    make_noop_stage,
)
from docuharnessx.types import SLOT_CLASSIFICATION, SLOT_VOCABULARY

if TYPE_CHECKING:  # typing only
    from harnessx.core.state import State

#: Canonical stage name, used as the stage-registry key and processor identity.
STAGE_NAME = "plan"

__all__ = ["STAGE_NAME", "PlanStage", "make_plan_stage", "make_noop_stage"]

_log = logging.getLogger(__name__)

#: Upper bound on the number of segment keys listed in the bounded journal summary.
#: Keeps the trace bounded for large plans while still naming the top-priority cells
#: (Req 9.2, 9.3): only the first few highest-priority keys are recorded, never the
#: full segment list.
_TOP_SEGMENT_KEYS_CAP: int = 5


class PlanStage(NoOpStage):
    """Real Plan stage: ``Classification`` + ``Vocabulary`` -> ``CoveragePlan``.

    Subclasses :class:`NoOpStage` so it inherits the runtime binding
    (:meth:`_bind_runtime`), the tracer resolution, and the
    attach-to-:data:`PIPELINE_HOOK` contract — the registry and ``make_docgen`` treat
    it exactly like the stub it replaces (Req 1.1). It overrides only ``on_task_start``
    (to capture the run ``State``) and ``on_step_end`` (to do the real planning as a
    side effect of the content-free ``step_end`` event, publishing into a run-context
    slot and journaling a bounded summary), then yields the event unchanged.
    """

    stage_name = STAGE_NAME

    #: The explicit relevance-hook gate (Req 8.5). OFF by default: the deterministic
    #: core never depends on a model and the optional LLM re-rank/annotate hook is
    #: consulted only when a caller flips this on *and* a model is reachable. No
    #: env-driven hidden behavior — the gate is a plain attribute a caller (e.g. a
    #: future CLI flag) sets.
    relevance_enabled: bool = False

    #: The live run ``State`` captured from the ``TaskStartEvent``; ``None`` until the
    #: task starts (e.g. when ``on_step_end`` is unit-driven without a task).
    _run_state: "State | None" = None

    async def on_task_start(
        self, event: TaskStartEvent
    ) -> AsyncIterator[Event]:
        """Capture the live run ``State``, then forward the event unchanged.

        ``TaskStartEvent`` carries the mutable run ``State`` (``StepEndEvent`` does
        not). We stash it so :meth:`on_step_end` can read the handoff slot and publish
        the plan. Pure pass-through — no field on the event is modified; the same
        mechanism the Classify/Analyze stages use.
        """
        self._run_state = event.state
        yield event

    async def on_step_end(self, event: StepEndEvent) -> AsyncIterator[Event]:
        """Plan the classification, publish ``CoveragePlan``, journal, forward event.

        Reads ``classification()`` + ``vocabulary()`` from the run ``State``; runs the
        deterministic :func:`~docuharnessx.planning.plan_coverage` core; optionally
        applies the gated, failure-tolerant :func:`~docuharnessx.planning.apply_relevance`
        hook; writes the produced :class:`CoveragePlan` to ``SLOT_COVERAGE_PLAN``
        (Req 7.3); emits a participation trigger plus a bounded plan summary to the
        journal (Req 9.2, 9.3, 9.4); and yields the *same* ``StepEndEvent`` back,
        modifying no generated content (Req 1.3). A missing classification or vocabulary
        raises :class:`PlanningInputError` (Req 2.4).
        """
        _log.debug("stage participated: %s", self.stage_name)

        run_context = self._resolve_run_context()
        if run_context is None:
            # No run State bound (driven outside a harness): nothing to read or write.
            # Forward the event unchanged, exactly like the no-op base — never raise
            # here, so the generic stage smoke tests stay valid.
            yield event
            return

        classification = run_context.classification()
        if classification is None:
            # Fatal input error: the Classify stage did not run or did not publish a
            # classification. Halt the run with a clear cause naming the offending slot,
            # producing no partial plan (Req 2.4).
            raise PlanningInputError(
                "Plan stage cannot run: the classification slot "
                f"'{SLOT_CLASSIFICATION}' is unset (the Classify stage did not "
                "publish a Classification). No CoveragePlan was produced."
            )

        vocab = run_context.vocabulary()
        if vocab is None:
            # Fatal input error: no loaded vocabulary to score/order the plan against
            # (Req 2.4).
            raise PlanningInputError(
                "Plan stage cannot run: the vocabulary slot "
                f"'{SLOT_VOCABULARY}' is unset (no project vocabulary was loaded). "
                "No CoveragePlan was produced."
            )

        # Deterministic, model-free core (Req 8.1): one segment per activated cell,
        # scored and ordered; an empty classification yields a well-formed empty plan
        # (never raises, never fabricates — Req 5.5).
        plan = plan_coverage(classification, vocab)

        # Optional, gated, failure-tolerant relevance hook (Req 8.2, 8.3, 8.4). Off by
        # default; the model, if any, comes from the runtime-bound ModelConfig. A
        # disabled/model-less/failed/out-of-bounds hook returns the deterministic plan
        # unchanged (relevance_applied=False).
        enabled = bool(self.relevance_enabled)
        model = self._relevance_model() if enabled else None
        plan = await self._maybe_apply_relevance(plan, model=model, enabled=enabled)

        # Publish the produced CoveragePlan to its slot — the writer-facing output seam
        # (Req 7.3). Written through the typed RunContext accessor.
        run_context.set_coverage_plan(plan)

        # Journal participation + a bounded plan summary (Req 9.2, 9.3, 9.4).
        await self._journal_participation(event, plan)

        # Pure pass-through: forward the content-free event unchanged (Req 1.3).
        yield event

    # ------------------------------------------------------------------ #
    # Helpers                                                            #
    # ------------------------------------------------------------------ #

    def _resolve_run_context(self) -> RunContext | None:
        """Wrap the live run ``State`` (captured at ``task_start``) in a RunContext.

        Returns ``None`` when no ``State`` was captured (the stage is being driven
        outside a harness, with no preceding ``task_start``), so the caller forwards
        the event unchanged instead of failing.
        """
        state = self._run_state
        if state is None:
            return None
        return RunContext(state)

    async def _maybe_apply_relevance(
        self, plan: CoveragePlan, *, model: Any | None, enabled: bool
    ) -> CoveragePlan:
        """Apply the gated :func:`apply_relevance` without nesting event loops.

        The pure-core :func:`docuharnessx.planning.apply_relevance` is *synchronous*:
        when it actually consults a model it drives the provider's awaitable
        ``complete`` on a private loop via ``asyncio.run``. Because ``on_step_end``
        itself runs inside the harness run loop, calling that synchronous bridge
        directly would nest ``asyncio.run`` inside a running loop and raise. We
        therefore offload the call to a worker thread (``asyncio.to_thread``) so the
        hook gets its own loop. When relevance is disabled or model-less,
        ``apply_relevance`` returns the same plan without ever touching a model, so
        there is nothing to offload and we call it inline. The hook absorbs its own
        failures/timeouts, so this never gates the deterministic core (Req 8.4).
        """
        if not enabled or model is None:
            # Fast path: no model is consulted, so apply_relevance does no async work —
            # it returns the same plan. Keep it inline (no thread, no loop).
            return apply_relevance(plan, model=model, enabled=enabled)
        # A model will be consulted: run the synchronous apply_relevance (with its own
        # asyncio.run) off the run loop's thread so loops never nest. apply_relevance
        # absorbs its own failures/timeouts, so this never gates the core (Req 8.4).
        return await asyncio.to_thread(
            apply_relevance, plan, model=model, enabled=enabled
        )

    def _relevance_model(self) -> Any | None:
        """Return the bound main model provider for the relevance hook, or ``None``.

        The bound model, if any, comes from the parent ``ModelConfig`` injected at
        ``Harness.__init__`` via ``_bind_model_config``. The planning core never
        constructs a provider itself (design "the bound model, if any, is obtained from
        the runtime"). Any failure to reach a provider degrades to ``None`` so a
        misconfigured model can never gate the deterministic core (Req 8.4, 8.5).
        """
        model_config = getattr(self, "_model_config", None)
        if model_config is None:
            return None
        try:
            return model_config.main
        except Exception:  # pragma: no cover - defensive: never gate the core
            return None

    async def _journal_participation(
        self, event: StepEndEvent, plan: CoveragePlan
    ) -> None:
        """Emit a participation trigger carrying a bounded plan summary.

        Records this stage's participation in the HarnessJournal (Req 9.2) with a
        summary-level ``detail`` only — the total segment count, the first few
        top-priority segment keys, whether the relevance hook was applied, and an
        explainable ``empty_reason`` when the plan is empty (Req 9.3, 9.4). The full
        :class:`CoveragePlan` (segments/subjects/evidence) is **never** written to the
        trace, keeping it bounded for large repos. No-op when no tracer is bound (driven
        outside a journaling harness).
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
                detail=self._summary_detail(plan),
            )
        )

    def _summary_detail(self, plan: CoveragePlan) -> dict[str, Any]:
        """Build the bounded, scalar-only summary recorded on the journal trigger.

        Summary-level fields only (Req 9.2, 9.3): the stage name, the total planned
        segment count, a *capped* list of the top-priority segment keys (the plan is
        already ordered priority-desc, so the head is the most important), whether the
        gated relevance hook was applied, and an ``empty_reason`` string explaining an
        empty result (Req 9.4) — empty (``""``) for a non-empty plan. No raw
        segment/subject/evidence objects, so the trace stays bounded for large plans.
        """
        total_segments = len(plan.segments)
        top_segment_keys = [
            seg.segment_key for seg in plan.segments[:_TOP_SEGMENT_KEYS_CAP]
        ]
        empty_reason = (
            "no coverage cells were activated: the analysis surfaced no "
            "evidence supporting any role x intent segment"
            if total_segments == 0
            else ""
        )
        return {
            "stage": self.stage_name,
            "total_segments": total_segments,
            "top_segment_keys": top_segment_keys,
            "relevance_applied": plan.relevance_applied,
            "empty_reason": empty_reason,
        }


def make_plan_stage() -> Processor:
    """Return a fresh real Plan-stage processor (Req 1.1 stable factory)."""
    return PlanStage()
