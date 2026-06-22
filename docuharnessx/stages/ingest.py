"""Real Ingest stage: scan the target repository into a file inventory (task 5.1).

The Ingest stage performs the pipeline's first real work. It replaces the Wave 0
no-op stub **in place**, keeping the harness contract stable — same module path,
``STAGE_NAME``, :class:`IngestStage` class name, and :func:`make_ingest_stage`
factory — so the stage registry and ``make_docgen`` need no edits (Req 8.1). It
remains a subclass of :class:`~docuharnessx.stages.base.NoOpStage`, so it keeps the
same content-neutral lifecycle: it attaches to ``PIPELINE_HOOK`` (``step_end``,
which carries no message/content window), does its work as a *side effect* of that
content-free event, and then yields the :class:`StepEndEvent` unchanged (Req 5.3,
8.2, 8.3).

What it does (design "IngestStage"; Req 1.1, 1.2, 1.7, 8.4, 10.1, 10.3):

* reads the validated target-repository path from the run context
  (``SLOT_TARGET_REPO``) and walks it with the deterministic
  :func:`docuharnessx.analysis.scanner.scan`;
* publishes the resulting :class:`FileInventory` to the inter-stage handoff slot
  (``SLOT_FILE_INVENTORY``) for the Analyze stage to read instead of re-walking
  the filesystem (Req 1.7);
* raises an identifiable :class:`IngestError` that halts the run — producing **no**
  partial inventory — when the repo slot is unset or its path is missing / not a
  directory; the message names the offending slot/path (Req 1.2, 8.4);
* records its participation plus a **bounded** scan summary in the journal
  (counts + primary language + limit flag — never the full inventory) and yields
  the event unchanged (Req 8.2, 10.1, 10.3).

Reaching the live run ``State``
-------------------------------
The work needs the run ``State`` (to read the target repo and write the inventory
slot), but ``StepEndEvent`` is content-free and carries no live state. HarnessX
*does* carry the mutable run ``State`` on :class:`~harnessx.core.events.TaskStartEvent`,
which a :class:`~harnessx.core.processor.MultiHookProcessor` (this stage's base)
is driven with once per task. So the stage captures the live ``State`` in
:meth:`on_task_start` — a pure pass-through that changes nothing on the event —
and wraps it in a :class:`~docuharnessx.context.RunContext` from
:meth:`on_step_end`. No model is imported or required: the scan is fully
deterministic and model-free (Req 8.5, 9.1).
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any, AsyncIterator

from harnessx.core.events import (
    Event,
    ProcessorTriggerEvent,
    StepEndEvent,
    TaskStartEvent,
)
from harnessx.core.processor import Processor

from docuharnessx.analysis.errors import IngestError
from docuharnessx.analysis.languages import aggregate_languages
from docuharnessx.analysis.scanner import scan
from docuharnessx.context import RunContext
from docuharnessx.stages.base import (
    PIPELINE_HOOK,
    STAGE_PARTICIPATION_ACTION,
    NoOpStage,
    make_noop_stage,
)
from docuharnessx.types import SLOT_TARGET_REPO

if TYPE_CHECKING:  # typing only
    from harnessx.core.state import State

    from docuharnessx.analysis.scanner import FileInventory

#: Canonical stage name, used as the stage-registry key and processor identity.
STAGE_NAME = "ingest"

__all__ = ["STAGE_NAME", "IngestStage", "make_ingest_stage", "make_noop_stage"]


class IngestStage(NoOpStage):
    """Real Ingest stage: scan the target repo, publish a file inventory (Req 1.1).

    Subclasses :class:`NoOpStage` to inherit the participation/journaling lifecycle
    and the content-neutral ``step_end`` contract; overrides :meth:`on_task_start`
    to capture the live run ``State`` and :meth:`on_step_end` to do the real scan.
    """

    stage_name = STAGE_NAME

    #: The live run ``State`` captured from the ``TaskStartEvent``; ``None`` until
    #: the task starts (e.g. when ``on_step_end`` is unit-driven without a task).
    _run_state: "State | None" = None

    async def on_task_start(
        self, event: TaskStartEvent
    ) -> AsyncIterator[Event]:
        """Capture the live run ``State``, then forward the event unchanged.

        ``TaskStartEvent`` carries the mutable run ``State`` (``StepEndEvent`` does
        not). We stash it so :meth:`on_step_end` can read the target-repo slot and
        publish the inventory. This is a pure pass-through — no field on the event
        is modified (Req 5.3).
        """
        self._run_state = event.state
        yield event

    async def on_step_end(self, event: StepEndEvent) -> AsyncIterator[Event]:
        """Scan the target repo and publish the inventory, then yield unchanged.

        Reads ``target_repo()`` from the run context; raises :class:`IngestError`
        naming the offending slot/path when it is unset, missing, or not a
        directory — halting the run with no partial inventory (Req 1.2, 8.4).
        Otherwise scans the tree, publishes the :class:`FileInventory` to
        ``SLOT_FILE_INVENTORY`` (Req 1.1, 1.7), journals a bounded scan summary
        (Req 10.1, 10.3), and forwards the content-free event unchanged (Req 8.3).
        """
        run_context = self._resolve_run_context()

        repo_path = run_context.target_repo()
        if repo_path is None:
            raise IngestError(
                f"target-repository slot {SLOT_TARGET_REPO!r} is unset; "
                "cannot ingest without a target repository path"
            )
        if not os.path.isdir(repo_path):
            raise IngestError(
                f"target-repository path is not a directory: {repo_path!r}"
            )

        inventory = scan(repo_path)
        run_context.set_file_inventory(inventory)

        await self._journal_summary(event, inventory)

        # Pure pass-through: forward the content-free event unchanged (Req 8.3).
        yield event

    # ----------------------------------------------------------------- #
    # Internals                                                          #
    # ----------------------------------------------------------------- #

    def _resolve_run_context(self) -> RunContext:
        """Wrap the live run ``State`` in a :class:`RunContext`.

        Raises :class:`IngestError` if no run ``State`` was captured — that means
        ``on_step_end`` was driven without a preceding ``task_start`` (no live run),
        which is a misuse rather than a scan-input error, but still a fatal,
        identifiable stage condition (Req 8.4).
        """
        state = self._run_state
        if state is None:
            raise IngestError(
                "no run State available to the Ingest stage; "
                "on_step_end was driven without a task_start to bind it"
            )
        return RunContext(state)

    async def _journal_summary(
        self, event: StepEndEvent, inventory: "FileInventory"
    ) -> None:
        """Emit the participation trigger plus a bounded scan summary (Req 10.1).

        The detail carries only summary-level scalars — file count, primary
        language, and the limit-reached flag — never the full inventory, keeping
        the trace bounded for large repos (Req 10.3). When no tracer is bound (the
        stage is driven outside a harness) the record is silently skipped, exactly
        as the no-op base does.
        """
        tracer = self._resolve_tracer()
        if tracer is None:
            return
        on_event = getattr(tracer, "on_event", None)
        if on_event is None:
            return

        _stats, primary_languages = aggregate_languages(inventory.entries)
        # A single, deterministic primary-language label for the bounded summary;
        # the canonical multi-language breakdown is the Analyze stage's job.
        primary_language = primary_languages[0] if primary_languages else ""

        await on_event(
            ProcessorTriggerEvent(
                run_id=event.run_id,
                step_id=event.step_id,
                processor=type(self).__name__,
                hook=PIPELINE_HOOK,
                action=STAGE_PARTICIPATION_ACTION,
                detail={
                    "stage": self.stage_name,
                    "files": inventory.stats.files_scanned,
                    "primary_language": primary_language,
                    "limit_reached": inventory.stats.limit_reached,
                },
            )
        )


def make_ingest_stage() -> Processor:
    """Return a fresh real Ingest processor (Req 8.1).

    The factory name, return contract, and the :class:`IngestStage` identity are
    unchanged from the Wave 0 stub so the stage registry and ``make_docgen`` need
    no edits — only the body is real now.
    """
    return IngestStage()
