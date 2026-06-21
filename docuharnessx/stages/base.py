"""Stage base: the pipeline hook constant and the shared no-op stage class.

This module (task 2.5 boundary: ``Stage stubs, stages/base``) defines the single
pattern every pipeline stage stub shares:

* :data:`PIPELINE_HOOK` — the one HarnessX lifecycle hook all eight stages attach
  to (Req 5.1). The stage registry (task 3.1) appends each stage processor on this
  hook in canonical order; ``make_docgen`` (task 3.2) wires the registry into the
  bundle. Keeping the hook name in one place means a change to the pipeline hook
  point is a one-line edit here (design "Changes that ripple": stage hook point).
* :class:`NoOpStage` — the shared base every per-stage class subclasses. It is a
  genuine no-op: its ``on_step_end`` yields the lifecycle event unchanged and
  modifies no generated content (Req 5.2, 5.3), while recording the stage's
  participation in the run journal (Req 8.2). Each per-stage module
  (``ingest`` … ``deploy``) defines its own ``<Title>Stage`` subclass **at module
  level** so a later spec can replace exactly one stub without touching the others
  (Req 5.2, 5.6).
* :func:`make_noop_stage` — a backward-compatible factory that returns a fresh
  per-stage instance by stage name (used by tests and the per-stage factories).

Why real module-level classes (the runtime-instantiation contract)
------------------------------------------------------------------
``make_docgen``/``builder.build()`` serializes each stage processor to a dict whose
``_target_`` is the class's ``module.qualname``. At run time HarnessX's
``_instantiate_proc`` resolves it via ``getattr(import_module(module), qualname)``;
if the class is *not* a real module-level attribute at that path the lookup raises
``AttributeError``, which HarnessX **swallows**, dropping the processor silently.
The eight stages must therefore each be a real, importable module-level class
(``docuharnessx.stages.ingest.IngestStage`` … ``deploy.DeployStage``) so every
stage actually instantiates — and fires — at run time.

Hook choice — ``step_end``: stages must "participate in the run lifecycle without
modifying generated content" (Req 5.3). ``StepEndEvent`` is a read-only lifecycle
event that carries no ``messages`` field, so a processor on this hook is, by the
HarnessX hook-contract, structurally incapable of mutating the conversation/content
window. That makes a pass-through here a provably content-neutral participation
point — exactly what a no-op stub needs — while still being driven once per step by
the runloop so each stage's participation is observable in the journal.

Observability without content mutation (Req 8.2)
------------------------------------------------
The HarnessX :class:`~harnessx.core.processor.ProcessorChain` only auto-emits a
``processor_trigger`` journal record when a processor *changes* the primary event,
and a true pass-through changes nothing. So instead of mutating the (content-free)
``StepEndEvent``, each no-op stage records its own participation explicitly: it is a
:class:`~harnessx.core.processor.MultiHookProcessor`, so ``Harness.__init__`` binds
the live runtime to it (``_bind_runtime``); from ``on_step_end`` it emits a
:class:`~harnessx.core.events.ProcessorTriggerEvent` straight to the run tracer
(``action='stage_participated'``, ``detail={'stage': <name>}``) and then yields the
``StepEndEvent`` unchanged. The journal records the trigger (Req 8.2) while the
generated content is never touched (Req 5.3).

This module contains no documentation-generation logic; the stubs must remain
no-ops until a Wave 1+ spec replaces them (design out-of-scope: stage business
logic).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, AsyncIterator

from harnessx.core.events import Event, ProcessorTriggerEvent, StepEndEvent
from harnessx.core.processor import MultiHookProcessor, Processor

if TYPE_CHECKING:  # pragma: no cover - typing only
    pass

__all__ = ["PIPELINE_HOOK", "NoOpStage", "make_noop_stage"]


#: The single HarnessX lifecycle hook every pipeline stage attaches to (Req 5.1).
#: ``step_end`` is read-only (no ``messages`` field) so a no-op stage participates
#: in the run lifecycle without modifying generated content (Req 5.3).
PIPELINE_HOOK: str = "step_end"

#: A short label recorded on each stage's ``ProcessorTriggerEvent`` so the journal
#: marks the record as a stage's lifecycle participation (Req 8.2).
STAGE_PARTICIPATION_ACTION: str = "stage_participated"

#: Module logger every no-op stage writes a participation marker to on execution.
#: Capturable in tests (``caplog``) as a second, journal-independent proof that the
#: stage's ``process``/``on_step_end`` actually fired at run time.
_log = logging.getLogger(__name__)


class NoOpStage(MultiHookProcessor):
    """Shared base for the eight no-op pipeline stage stubs (Req 5.2, 5.3, 8.2).

    A genuine pass-through on :data:`PIPELINE_HOOK`: ``on_step_end`` yields the
    incoming :class:`~harnessx.core.events.StepEndEvent` unchanged (same object —
    no copy, no mutation), so the stage participates in the run lifecycle while
    modifying no generated content (``StepEndEvent`` carries no message/content
    window at all).

    Participation is made observable in the journal without mutating any event:
    because this is a :class:`MultiHookProcessor`, ``Harness.__init__`` injects the
    live runtime via :meth:`_bind_runtime`; ``on_step_end`` reads the run tracer
    from it and emits a :class:`ProcessorTriggerEvent`
    (``action=`` :data:`STAGE_PARTICIPATION_ACTION`, ``detail={'stage': name}``)
    which HarnessJournal records as a ``processor_trigger`` trace entry (Req 8.2).

    Each concrete stage is a module-level subclass named ``<Title>Stage`` (e.g.
    ``IngestStage`` in ``docuharnessx.stages.ingest``) so it serializes to a real,
    importable ``_target_`` and is instantiated — and fired — at run time, and so
    the journal/registry distinguish per-stage participation by class name.
    """

    #: Bound hook the registry/bundle attach this processor to. Mirrors the
    #: module-level constant so introspection (and ``HarnessBuilder.add``'s
    #: class-attribute defaulting) sees the same hook the registry passes.
    _hook = PIPELINE_HOOK

    #: The canonical stage name. Concrete subclasses override this; the base value
    #: is a defensive placeholder only.
    stage_name: str = "noop"

    def _bind_runtime(self, rt: Any) -> None:
        """Capture the live :class:`_HarnessRuntime` so ``on_step_end`` can journal.

        Called by ``Harness.__init__`` for every ``MultiHookProcessor``. We keep
        the runtime so we can reach its ``tracer`` and emit a participation marker
        to the journal at run time (Req 8.2). Falls back gracefully (no marker) when
        the stage is driven outside a harness (e.g. a unit test) where nothing is
        bound.
        """
        self._harness_runtime = rt

    async def on_step_end(self, event: StepEndEvent) -> AsyncIterator[Event]:
        """Record participation, then forward the lifecycle event unchanged.

        Emits a :class:`ProcessorTriggerEvent` to the run tracer so the journal
        records this stage's participation (Req 8.2), logs a lightweight marker,
        and yields the *same* ``StepEndEvent`` object back — modifying no generated
        content (Req 5.3).
        """
        _log.debug("stage participated: %s", self.stage_name)

        tracer = self._resolve_tracer()
        if tracer is not None:
            on_event = getattr(tracer, "on_event", None)
            if on_event is not None:
                await on_event(
                    ProcessorTriggerEvent(
                        run_id=event.run_id,
                        step_id=event.step_id,
                        processor=type(self).__name__,
                        hook=PIPELINE_HOOK,
                        action=STAGE_PARTICIPATION_ACTION,
                        detail={"stage": self.stage_name},
                    )
                )

        # Pure pass-through: forward the event unchanged, modify nothing.
        yield event

    def _resolve_tracer(self) -> Any:
        """Return the live run tracer bound at ``Harness.__init__``, or ``None``.

        ``_bind_runtime`` stores the :class:`_HarnessRuntime`, whose ``tracer`` is
        the HarnessJournal (or wrapper) the run writes to. Returns ``None`` when no
        runtime/tracer is bound (the stage is being driven outside a harness).
        """
        rt = getattr(self, "_harness_runtime", None)
        return getattr(rt, "tracer", None) if rt is not None else None


def make_noop_stage(name: str) -> Processor:
    """Build a no-op stage processor for *name* (backward-compatible factory).

    Returns a fresh instance of the per-stage module's real, module-level
    ``<Title>Stage`` class (e.g. ``make_noop_stage('ingest')`` →
    :class:`docuharnessx.stages.ingest.IngestStage`). Routing through the concrete
    class — rather than building an anonymous local class — is what makes the
    returned processor serialize to an importable ``_target_`` and therefore
    actually instantiate (and fire) at run time.

    Args:
        name: The stage identifier (one of the eight canonical stage names).

    Returns:
        A new pass-through no-op ``Processor`` for the named stage.

    Raises:
        ValueError: If *name* is not one of the eight canonical stage names.
    """
    from docuharnessx.stages import stage_class_for

    return stage_class_for(name)()
