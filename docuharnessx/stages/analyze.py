"""The real Analyze stage adapter (task 5.2 boundary: AnalyzeStage).

The Analyze stage turns the file inventory the Ingest stage published into the
frozen :class:`~docuharnessx.analysis.model.RepoAnalysis` the downstream
``classification-coverage-planner`` consumes. It is a **thin HarnessX adapter**
over the pure, model-free analysis core (:mod:`docuharnessx.analysis`): all the
real work lives in :func:`docuharnessx.analysis.analyze` (deterministic) and the
optional, gated :func:`docuharnessx.analysis.enrich` (the only place a model may
be consulted). This module only wires those into the run lifecycle.

Same lifecycle shape as :class:`~docuharnessx.stages.base.NoOpStage`, richer
journal (design "AnalyzeStage", "Why work happens as a step_end side effect").
The stage does its work as a **side effect of the content-free** ``step_end``
event and then yields that event **unchanged**:

* ``StepEndEvent`` carries no ``messages``/content window, so a processor on
  :data:`PIPELINE_HOOK` is structurally incapable of mutating generated content
  (Req 8.2, 8.3) — the analysis is published into run-context *slots*, never into
  the conversation;
* it reaches the live run :class:`~harnessx.core.state.State` the same way the
  Ingest stage does: ``StepEndEvent`` is content-free and carries no live state,
  but HarnessX *does* carry the mutable run ``State`` on
  :class:`~harnessx.core.events.TaskStartEvent`, with which a
  :class:`~harnessx.core.processor.MultiHookProcessor` (this stage's base) is driven
  once per task. The stage captures that ``State`` in :meth:`on_task_start` (a pure
  pass-through), wraps it in a :class:`~docuharnessx.context.RunContext` from
  :meth:`on_step_end`, reads the inventory from ``SLOT_FILE_INVENTORY`` and writes
  the analysis to ``SLOT_REPO_ANALYSIS`` (Req 7.2);
* a missing inventory slot raises :class:`AnalyzeError`, halting the run with a
  clear cause and **no** partial analysis (Req 8.4);
* the core path requires **no** model binding (Req 8.5, 9.1); enrichment is OFF
  by default and gated by an explicit per-instance flag (Req 9.4), failure-tolerant
  (Req 9.5);
* it records its participation plus a **bounded** analysis summary in the journal
  — summary-level counts/flags only, never the full inventory (Req 8.2, 10.1, 10.3).

Stable contract (Req 8.1): the ``STAGE_NAME`` constant, the :class:`AnalyzeStage`
class name, the :func:`make_analyze_stage` factory, and this module path are kept
unchanged so the stage registry and ``make_docgen`` need no edits — the real stage
drops into exactly the slot the no-op stub occupied (single-stage replaceability).

Driven outside a harness (no ``task_start`` to bind the run ``State`` — e.g. a
generic stage smoke test that calls ``process`` directly) the stage has no
``State`` to read, so it does nothing and forwards the event unchanged, exactly
like the no-op base. It only raises :class:`AnalyzeError` when it *has* a run
``State`` but the inventory slot is missing.
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

from docuharnessx.analysis import analyze, enrich
from docuharnessx.analysis.errors import AnalyzeError
from docuharnessx.analysis.scanner import FileInventory
from docuharnessx.context import RunContext
from docuharnessx.stages.base import (
    PIPELINE_HOOK,
    STAGE_PARTICIPATION_ACTION,
    NoOpStage,
    make_noop_stage,
)
from docuharnessx.types import SLOT_FILE_INVENTORY

if TYPE_CHECKING:  # typing only
    from harnessx.core.state import State

#: Canonical stage name, used as the stage-registry key and processor identity.
STAGE_NAME = "analyze"

__all__ = ["STAGE_NAME", "AnalyzeStage", "make_analyze_stage", "make_noop_stage"]

_log = logging.getLogger(__name__)


class AnalyzeStage(NoOpStage):
    """Real Analyze stage: inventory -> deterministic ``RepoAnalysis`` (Req 4-10).

    Subclasses :class:`NoOpStage` so it inherits the runtime binding
    (:meth:`_bind_runtime`), the tracer resolution, and the
    attach-to-:data:`PIPELINE_HOOK` contract — the registry and ``make_docgen``
    treat it exactly like the stub it replaces (Req 8.1). It overrides only
    ``on_step_end`` to do the real analysis as a side effect of the content-free
    ``step_end`` event, publishing into run-context slots and journaling a bounded
    summary, then yielding the event unchanged.
    """

    stage_name = STAGE_NAME

    #: The explicit enrichment gate (Req 9.4). OFF by default: the deterministic
    #: core never depends on a model and a model is consulted only when a caller
    #: flips this on *and* a model is reachable. No env-driven hidden behavior —
    #: the gate is a plain attribute a caller (e.g. a future CLI flag) sets.
    enrich_enabled: bool = False

    #: The live run ``State`` captured from the ``TaskStartEvent``; ``None`` until
    #: the task starts (e.g. when ``on_step_end`` is unit-driven without a task).
    _run_state: "State | None" = None

    async def on_task_start(
        self, event: TaskStartEvent
    ) -> AsyncIterator[Event]:
        """Capture the live run ``State``, then forward the event unchanged.

        ``TaskStartEvent`` carries the mutable run ``State`` (``StepEndEvent`` does
        not). We stash it so :meth:`on_step_end` can read the inventory slot and
        publish the analysis. Pure pass-through — no field on the event is modified
        (Req 8.3); the same mechanism the Ingest stage uses.
        """
        self._run_state = event.state
        yield event

    async def on_step_end(self, event: StepEndEvent) -> AsyncIterator[Event]:
        """Analyze the inventory, publish ``RepoAnalysis``, journal, forward event.

        Reads ``SLOT_FILE_INVENTORY`` from the run ``State``; runs the
        deterministic core analyzer and the optional gated enrichment; writes the
        produced :class:`RepoAnalysis` to ``SLOT_REPO_ANALYSIS`` (Req 7.2); emits a
        participation trigger plus a bounded analysis summary to the journal (Req
        8.2, 10.1, 10.3); and yields the *same* ``StepEndEvent`` back, modifying no
        generated content (Req 8.3). A missing inventory raises
        :class:`AnalyzeError` (Req 8.4).
        """
        _log.debug("stage participated: %s", self.stage_name)

        run_context = self._resolve_run_context()
        if run_context is None:
            # No run State bound (driven outside a harness): nothing to read or
            # write. Forward the event unchanged, exactly like the no-op base —
            # never raise here, so the generic stage smoke tests stay valid.
            yield event
            return

        inventory = run_context.file_inventory()
        if inventory is None:
            # Fatal input error: the Ingest stage did not run or did not publish an
            # inventory. Halt the run with a clear cause naming the offending slot,
            # producing no partial analysis (Req 8.4).
            raise AnalyzeError(
                "Analyze stage cannot run: the file-inventory slot "
                f"'{SLOT_FILE_INVENTORY}' is unset (the Ingest stage did not "
                "publish an inventory). No RepoAnalysis was produced."
            )
        if not isinstance(inventory, FileInventory):  # pragma: no cover - defensive
            raise AnalyzeError(
                "Analyze stage cannot run: the file-inventory slot "
                f"'{SLOT_FILE_INVENTORY}' holds {type(inventory).__name__}, "
                "not a FileInventory. No RepoAnalysis was produced."
            )

        # Deterministic, model-free core (Req 9.1). No model is required to reach
        # here, and none is consulted unless enrichment is explicitly enabled below.
        analysis = analyze(inventory)

        # Optional, gated, failure-tolerant enrichment (Req 9.3, 9.4, 9.5). Off by
        # default; the model, if any, comes from the runtime-bound ModelConfig. A
        # disabled/model-less/failed enrichment returns the core unchanged.
        enabled = bool(self.enrich_enabled)
        model = self._enrichment_model() if enabled else None
        analysis = await self._maybe_enrich(analysis, model=model, enabled=enabled)

        # Publish the produced RepoAnalysis to its slot — the planner-facing output
        # seam (Req 7.2). Written through the typed RunContext accessor.
        run_context.set_repo_analysis(analysis)

        # Journal participation + a bounded analysis summary (Req 8.2, 10.1, 10.3).
        await self._journal_participation(event, analysis)

        # Pure pass-through: forward the content-free event unchanged (Req 8.3).
        yield event

    # ------------------------------------------------------------------ #
    # Helpers                                                            #
    # ------------------------------------------------------------------ #

    def _resolve_run_context(self) -> RunContext | None:
        """Wrap the live run ``State`` (captured at ``task_start``) in a RunContext.

        The run ``State`` is captured from the ``TaskStartEvent`` in
        :meth:`on_task_start`. Returns ``None`` when no ``State`` was captured (the
        stage is being driven outside a harness, with no preceding ``task_start``),
        so the caller forwards the event unchanged instead of failing.
        """
        state = self._run_state
        if state is None:
            return None
        return RunContext(state)

    async def _maybe_enrich(
        self, analysis: Any, *, model: Any | None, enabled: bool
    ) -> Any:
        """Apply the gated :func:`enrich` without nesting event loops.

        The pure-core :func:`docuharnessx.analysis.enrich` is *synchronous*: when it
        actually consults a model it drives the provider's awaitable ``complete`` on
        a private loop via ``asyncio.run``. Because ``on_step_end`` itself runs
        inside the harness run loop, calling that synchronous bridge directly would
        nest ``asyncio.run`` inside a running loop and raise. We therefore offload
        the call to a worker thread (``asyncio.to_thread``) so ``enrich`` gets its
        own loop. When enrichment is disabled or model-less, ``enrich`` returns the
        core unchanged without ever touching a model, so there is nothing to offload
        and we call it inline (still failure-tolerant — Req 9.4, 9.5).
        """
        if not enabled or model is None:
            # Fast path: no model is consulted, so enrich() does no async work — it
            # returns the same object. Keep it inline (no thread, no loop).
            return enrich(analysis, model=model, enabled=enabled)
        # A model will be consulted: run the synchronous enrich() (with its own
        # asyncio.run) off the run loop's thread so loops never nest. enrich()
        # absorbs its own failures/timeouts, so this never gates the core (Req 9.5).
        return await asyncio.to_thread(
            enrich, analysis, model=model, enabled=enabled
        )

    def _enrichment_model(self) -> Any | None:
        """Return the bound main model provider for enrichment, or ``None``.

        The bound model, if any, comes from the parent ``ModelConfig`` injected at
        ``Harness.__init__`` via ``_bind_model_config``. Enrichment never constructs
        a provider itself (design "the bound model, if any, is obtained from the
        runtime"). Any failure to reach a provider degrades to ``None`` so a
        misconfigured model can never gate the deterministic core (Req 9.4, 9.5).
        """
        model_config = getattr(self, "_model_config", None)
        if model_config is None:
            return None
        try:
            return model_config.main
        except Exception:  # pragma: no cover - defensive: never gate the core
            return None

    async def _journal_participation(
        self, event: StepEndEvent, analysis: Any
    ) -> None:
        """Emit a participation trigger carrying a bounded analysis summary.

        Records this stage's participation in the HarnessJournal (Req 8.2) with a
        summary-level ``detail`` only — counts, primary language(s), whether a scan
        limit was reached, and whether enrichment ran (Req 10.1). The full inventory
        is **never** written to the trace, keeping it bounded for large repos (Req
        10.3). No-op when no tracer is bound (driven outside a journaling harness).
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
                detail=self._summary_detail(analysis),
            )
        )

    def _summary_detail(self, analysis: Any) -> dict[str, Any]:
        """Build the bounded, scalar-only summary recorded on the journal trigger.

        Summary-level fields only (Req 10.1, 10.3): the stage name, project size
        counts, the primary language(s), the component count, whether any scan limit
        was reached, and whether enrichment ran. No per-file inventory data and no
        nested model objects, so the trace stays bounded for large repos.
        """
        return {
            "stage": self.stage_name,
            "total_loc": analysis.total_loc,
            "total_files": analysis.total_files,
            "primary_languages": list(analysis.primary_languages),
            "components": len(analysis.components),
            "limit_reached": analysis.scan_stats.limit_reached,
            "enriched": analysis.enrichment is not None,
        }


def make_analyze_stage() -> Processor:
    """Return a fresh real Analyze-stage processor (Req 8.1 stable factory)."""
    return AnalyzeStage()
