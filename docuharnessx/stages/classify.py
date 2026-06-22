"""The real Classify stage adapter (task 4.2 boundary: ClassifyStage).

The Classify stage turns *what a repository is* (the upstream frozen
:class:`~docuharnessx.analysis.model.RepoAnalysis` the Analyze stage published) and
*who reads it and why* (the loaded, project-configurable
:class:`~docuharnessx.ontology.Vocabulary`) into the intermediate
:class:`~docuharnessx.planning.model.Classification` — the derived typed subjects plus
the activated role x intent coverage cells — which it hands off to the downstream
``PlanStage`` through an internal run-context slot. It is a **thin HarnessX adapter**
over the pure, model-free planning core (:mod:`docuharnessx.planning`): all the real
decision-intelligence lives in the deterministic :func:`docuharnessx.planning.classify_repo`;
this module only wires that into the run lifecycle (design "deterministic
pipeline-stage adapters over a pure planning core").

Same lifecycle shape as :class:`~docuharnessx.stages.base.NoOpStage`, richer journal
(design "ClassifyStage", "Why work happens as a step_end side effect"). The stage does
its work as a **side effect of the content-free** ``step_end`` event and then yields
that event **unchanged**:

* ``StepEndEvent`` carries no ``messages``/content window, so a processor on
  :data:`PIPELINE_HOOK` is structurally incapable of mutating generated content — the
  classification is published into a run-context *slot*, never into the conversation;
* it reaches the live run :class:`~harnessx.core.state.State` the same way the Analyze
  stage does: ``StepEndEvent`` is content-free and carries no live state, but HarnessX
  *does* carry the mutable run ``State`` on
  :class:`~harnessx.core.events.TaskStartEvent`, with which a
  :class:`~harnessx.core.processor.MultiHookProcessor` (this stage's base) is driven
  once per task. The stage captures that ``State`` in :meth:`on_task_start` (a pure
  pass-through), wraps it in a :class:`~docuharnessx.context.RunContext` from
  :meth:`on_step_end`, reads ``repo_analysis()`` + ``vocabulary()`` and writes the
  produced :class:`Classification` to ``SLOT_CLASSIFICATION`` (Req 2.1, 2.2);
* a missing analysis, a missing vocabulary, or an analysis declaring an unsupported
  ``schema_version`` raises :class:`~docuharnessx.planning.model.PlanningInputError`,
  halting the run with a clear cause and **no** partial classification (Req 2.3, 2.4,
  2.5);
* the core path requires **no** model binding — it is deterministic by construction
  (Req 8.1);
* it records its participation plus a **bounded** classify summary in the journal —
  summary-level counts only (subject counts per prefix, activated-cell count), never
  the full classification (Req 9.1, 9.3).

Stable contract (Req 1.1): the ``STAGE_NAME`` constant, the :class:`ClassifyStage`
class name, the :func:`make_classify_stage` factory, and this module path are kept
unchanged so the stage registry and ``make_docgen`` need no edits — the real stage
drops into exactly the slot the no-op stub occupied (single-stage replaceability).

Driven outside a harness (no ``task_start`` to bind the run ``State`` — e.g. the
generic stage smoke suite that calls ``process`` directly) the stage has no ``State``
to read, so it does nothing and forwards the event unchanged, exactly like the no-op
base. It only raises :class:`PlanningInputError` when it *has* a run ``State`` but a
required input slot is missing/unsupported.
"""

from __future__ import annotations

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
from docuharnessx.planning import Classification, classify_repo
from docuharnessx.planning.model import PlanningInputError
from docuharnessx.stages.base import (
    PIPELINE_HOOK,
    STAGE_PARTICIPATION_ACTION,
    NoOpStage,
    make_noop_stage,
)
from docuharnessx.types import SLOT_REPO_ANALYSIS, SLOT_VOCABULARY

if TYPE_CHECKING:  # typing only
    from harnessx.core.state import State

#: Canonical stage name, used as the stage-registry key and processor identity.
STAGE_NAME = "classify"

__all__ = ["STAGE_NAME", "ClassifyStage", "make_classify_stage", "make_noop_stage"]

_log = logging.getLogger(__name__)


class ClassifyStage(NoOpStage):
    """Real Classify stage: ``RepoAnalysis`` + ``Vocabulary`` -> ``Classification``.

    Subclasses :class:`NoOpStage` so it inherits the runtime binding
    (:meth:`_bind_runtime`), the tracer resolution, and the
    attach-to-:data:`PIPELINE_HOOK` contract — the registry and ``make_docgen`` treat
    it exactly like the stub it replaces (Req 1.1). It overrides only ``on_task_start``
    (to capture the run ``State``) and ``on_step_end`` (to do the real classification
    as a side effect of the content-free ``step_end`` event, publishing into a
    run-context slot and journaling a bounded summary), then yields the event
    unchanged.
    """

    stage_name = STAGE_NAME

    #: The live run ``State`` captured from the ``TaskStartEvent``; ``None`` until the
    #: task starts (e.g. when ``on_step_end`` is unit-driven without a task).
    _run_state: "State | None" = None

    async def on_task_start(
        self, event: TaskStartEvent
    ) -> AsyncIterator[Event]:
        """Capture the live run ``State``, then forward the event unchanged.

        ``TaskStartEvent`` carries the mutable run ``State`` (``StepEndEvent`` does
        not). We stash it so :meth:`on_step_end` can read the input slots and publish
        the classification. Pure pass-through — no field on the event is modified; the
        same mechanism the Analyze stage uses.
        """
        self._run_state = event.state
        yield event

    async def on_step_end(self, event: StepEndEvent) -> AsyncIterator[Event]:
        """Classify the analysis, publish ``Classification``, journal, forward event.

        Reads ``repo_analysis()`` + ``vocabulary()`` from the run ``State``; runs the
        deterministic :func:`~docuharnessx.planning.classify_repo` core; writes the
        produced :class:`Classification` to ``SLOT_CLASSIFICATION``; emits a
        participation trigger plus a bounded classify summary to the journal (Req 9.1,
        9.3); and yields the *same* ``StepEndEvent`` back, modifying no generated
        content (Req 1.3). A missing analysis/vocabulary or an unsupported analysis
        ``schema_version`` raises :class:`PlanningInputError` (Req 2.3, 2.4, 2.5).
        """
        _log.debug("stage participated: %s", self.stage_name)

        run_context = self._resolve_run_context()
        if run_context is None:
            # No run State bound (driven outside a harness): nothing to read or write.
            # Forward the event unchanged, exactly like the no-op base — never raise
            # here, so the generic stage smoke tests stay valid.
            yield event
            return

        analysis = run_context.repo_analysis()
        if analysis is None:
            # Fatal input error: the Analyze stage did not run or did not publish an
            # analysis. Halt the run with a clear cause naming the offending slot,
            # producing no partial classification (Req 2.4).
            raise PlanningInputError(
                "Classify stage cannot run: the repo-analysis slot "
                f"'{SLOT_REPO_ANALYSIS}' is unset (the Analyze stage did not "
                "publish a RepoAnalysis). No Classification was produced."
            )

        vocab = run_context.vocabulary()
        if vocab is None:
            # Fatal input error: no loaded vocabulary to classify against (Req 2.4).
            raise PlanningInputError(
                "Classify stage cannot run: the vocabulary slot "
                f"'{SLOT_VOCABULARY}' is unset (no project vocabulary was loaded). "
                "No Classification was produced."
            )

        # Deterministic, model-free core (Req 8.1). classify_repo additionally pins the
        # consumed RepoAnalysis to the supported schema version and raises
        # PlanningInputError naming the offending version when it differs (Req 2.3, 2.5)
        # — the run halts with an identifiable cause rather than classifying against a
        # contract this build does not understand.
        classification = classify_repo(analysis, vocab)

        # Publish the Classification to the internal handoff slot — the input the
        # downstream PlanStage reads (Req 2.1). Written through the typed accessor.
        run_context.set_classification(classification)

        # Journal participation + a bounded classify summary (Req 9.1, 9.3).
        await self._journal_participation(event, classification)

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

    async def _journal_participation(
        self, event: StepEndEvent, classification: Classification
    ) -> None:
        """Emit a participation trigger carrying a bounded classify summary.

        Records this stage's participation in the HarnessJournal (Req 9.1) with a
        summary-level ``detail`` only — the subject counts per prefix and the
        activated-cell count (Req 9.3). The full classification (subjects/cells) is
        **never** written to the trace, keeping it bounded for large repos. No-op when
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
                detail=self._summary_detail(classification),
            )
        )

    def _summary_detail(self, classification: Classification) -> dict[str, Any]:
        """Build the bounded, scalar-only summary recorded on the journal trigger.

        Summary-level fields only (Req 9.3): the stage name, the count of derived
        subjects grouped by their bare prefix, and the count of activated coverage
        cells. No raw subject/cell objects, so the trace stays bounded for large repos.
        """
        subjects_by_prefix: dict[str, int] = {}
        for subject in classification.subjects:
            subjects_by_prefix[subject.prefix] = (
                subjects_by_prefix.get(subject.prefix, 0) + 1
            )
        return {
            "stage": self.stage_name,
            "subjects_by_prefix": subjects_by_prefix,
            "activated_cells": len(classification.cells),
        }


def make_classify_stage() -> Processor:
    """Return a fresh real Classify-stage processor (Req 1.1 stable factory)."""
    return ClassifyStage()
