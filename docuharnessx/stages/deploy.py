"""The real Deploy stage adapter (github-pages-deploy task 4.1 boundary: DeployStage).

The Deploy stage is the **finale** of the DocuHarnessX pipeline (Ingest → Analyze → Classify →
Plan → Write → Review → Assemble → Deploy): it takes the assembled Material for MkDocs site
source tree and **publishes it to the target project's GitHub Pages**. It is a **thin HarnessX
adapter** over the pure, model-free deploy core (:mod:`docuharnessx.deployer`): all deterministic
work — the deploy-mode resolution, the GitHub Actions Pages workflow rendering, the target-tree
write, the build validation, and the (isolated) ``gh-deploy`` push — lives in that package and is
unit-testable without a harness, a model, or the network. This module merely wires that core into
the run lifecycle (design "thin harness adapter"), exactly mirroring
:class:`~docuharnessx.stages.assemble.AssembleStage` and
:class:`~docuharnessx.stages.review.ReviewStage`.

It replaces the former no-op stub **in place**: the ``STAGE_NAME`` constant (``"deploy"``), the
:class:`DeployStage` class name, the :func:`make_deploy_stage` factory, the ``make_noop_stage``
re-export, the ``__all__`` set, and this module path are kept unchanged so the stage registry and
``make_docgen`` need no edits — the real stage drops into exactly the slot the stub occupied
(Req 1.1, 1.2, single-stage replaceability).

Lifecycle (same shape as :class:`~docuharnessx.stages.assemble.AssembleStage`)
------------------------------------------------------------------------------
Like every pipeline stage it does its work as a side effect of the **content-free**
``step_end`` event and yields that event **unchanged** (Req 1.4): ``StepEndEvent`` carries no
``messages``/content window, so a processor on :data:`PIPELINE_HOOK` is structurally incapable
of mutating generated content — the :class:`~docuharnessx.deployer.model.DeployResult` is
published into a run-context *slot*, never into the conversation. The live run ``State`` is
captured from the ``TaskStartEvent`` in :meth:`on_task_start` (a pure pass-through) and wrapped
in a :class:`~docuharnessx.context.RunContext` from :meth:`on_step_end`.

Input boundary (Req 2.1-2.5)
----------------------------
With a bound run ``State`` the stage reads the input slots through the typed ``RunContext``
accessors — the :class:`~docuharnessx.assembler.model.AssembledSite` (``SLOT_ASSEMBLED_SITE``),
the resolved output directory (``SLOT_OUTPUT_DIR``), and the target-repository path
(``SLOT_TARGET_REPO``) — pins
:data:`~docuharnessx.assembler.model.ASSEMBLED_SITE_SCHEMA_VERSION`, and raises
:class:`~docuharnessx.deployer.model.DeployInputError` naming the cause when the assembled-site,
output-directory, or target-repository slot is unset, or when the consumed site declares an
unsupported version. It performs **no deploy action** on that fatal path (Req 2.3, 2.4, 2.5),
mirroring :class:`~docuharnessx.stages.assemble.AssembleStage`'s
:class:`~docuharnessx.assembler.AssemblerInputError` handling. The
:class:`~docuharnessx.assembler.model.AssembledSite` is consumed verbatim, read-only — the stage
never re-derives the site layout or re-parses the target git remote (Req 2.2).

Driven outside a harness (no ``task_start`` to bind the run ``State`` — e.g. the generic stage
smoke suite) the stage has no ``State`` to read, so it forwards the event unchanged and performs
no deploy, exactly like the no-op base (Req 1.3). It raises
:class:`~docuharnessx.deployer.model.DeployInputError` only when it *has* a run ``State`` but a
required input slot is missing/unsupported or the configured mode is invalid.

Mode selection + execution (Req 3.x, 4.x, 5.x, 6.x, 7.x)
--------------------------------------------------------
The stage resolves the configured deploy mode (:meth:`_deploy_mode_value` — a per-instance value
placed by the CLI config layer / flags; absent → the ``emit-ci-workflow`` default) via the pure
:func:`~docuharnessx.deployer.resolve_deploy_mode`, then runs the selected mode end to end through
:func:`~docuharnessx.deployer.deploy_site` with the injected
:class:`~docuharnessx.deployer.commands.CommandRunner` (:meth:`_resolve_command_runner`; default
:class:`~docuharnessx.deployer.commands.DefaultCommandRunner`). The runner isolates the only
process-touching surface (the git default-branch read, ``mkdocs build``, ``mkdocs gh-deploy``) so
tests substitute a fake — no real subprocess is spawned and the ``gh-deploy`` push is never
exercised (Req 5.4, 7.4). The frozen :class:`~docuharnessx.deployer.model.DeployResult` is
published to ``SLOT_DEPLOY_RESULT`` (Req 8.1) and recorded in the run journal as a bounded
participation summary (Req 8.2). Per-project isolation (Req 9.1, 9.2): every per-target parameter
comes from the consumed ``AssembledSite.identity`` and the target path — never DocuHarnessX's own
identity. The stage performs no model call (Req 9.4).
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

from docuharnessx.assembler.model import ASSEMBLED_SITE_SCHEMA_VERSION
from docuharnessx.context import RunContext
from docuharnessx.deployer import (
    DeployInputError,
    DeployResult,
    DefaultCommandRunner,
    deploy_site,
    resolve_deploy_mode,
)
from docuharnessx.stages.base import (
    PIPELINE_HOOK,
    STAGE_PARTICIPATION_ACTION,
    NoOpStage,
    make_noop_stage,
)
from docuharnessx.types import (
    SLOT_ASSEMBLED_SITE,
    SLOT_OUTPUT_DIR,
    SLOT_TARGET_REPO,
)

if TYPE_CHECKING:  # typing only
    from harnessx.core.state import State

    from docuharnessx.assembler.model import AssembledSite
    from docuharnessx.deployer.commands import CommandRunner

#: Canonical stage name, used as the stage-registry key and processor identity.
STAGE_NAME = "deploy"

__all__ = ["STAGE_NAME", "DeployStage", "make_deploy_stage", "make_noop_stage"]

_log = logging.getLogger(__name__)


class DeployStage(NoOpStage):
    """Real Deploy stage: the assembled site -> the target project's GitHub Pages.

    Subclasses :class:`NoOpStage` so it inherits the runtime binding (:meth:`_bind_runtime`),
    the tracer resolution, and the attach-to-:data:`PIPELINE_HOOK` contract — the registry and
    ``make_docgen`` treat it exactly like the stub it replaces (Req 1.1, 1.2). It overrides only
    ``on_task_start`` (to capture the run ``State``) and ``on_step_end`` (to read + validate the
    deploy inputs, resolve the mode, run the deterministic deploy core, and publish the frozen
    :class:`~docuharnessx.deployer.model.DeployResult`), then yields the event unchanged
    (Req 1.4).
    """

    stage_name = STAGE_NAME

    #: The live run ``State`` captured from the ``TaskStartEvent``; ``None`` until the task
    #: starts (e.g. when ``on_step_end`` is unit-driven without a task), so a harness-free
    #: smoke run forwards the event unchanged (Req 1.3).
    _run_state: "State | None" = None

    async def on_task_start(self, event: TaskStartEvent) -> AsyncIterator[Event]:
        """Capture the live run ``State``, then forward the event unchanged.

        ``TaskStartEvent`` carries the mutable run ``State`` (``StepEndEvent`` does not). We
        stash it so :meth:`on_step_end` can read the input slots and publish the deploy result.
        Pure pass-through — the same mechanism the Assemble/Review/Write stages use.
        """
        self._run_state = event.state
        yield event

    async def on_step_end(self, event: StepEndEvent) -> AsyncIterator[Event]:
        """Read + validate the deploy inputs, run the deploy, then forward the event.

        Reads the :class:`~docuharnessx.assembler.model.AssembledSite`, the output directory,
        and the target-repository path; pins
        :data:`~docuharnessx.assembler.model.ASSEMBLED_SITE_SCHEMA_VERSION` and raises
        :class:`~docuharnessx.deployer.model.DeployInputError` naming the cause on a missing
        assembled-site/output-dir/target-repo slot or an unsupported site version, performing no
        deploy (Req 2.1-2.5). Resolves the configured deploy mode (default ``emit-ci-workflow``),
        runs :func:`~docuharnessx.deployer.deploy_site` end to end through the injected command
        runner, and publishes the frozen :class:`~docuharnessx.deployer.model.DeployResult` to
        ``SLOT_DEPLOY_RESULT`` (Req 8.1). Yields the *same* ``StepEndEvent`` back, modifying no
        generated content (Req 1.4).

        Driven outside a harness (no run ``State`` bound) it forwards the event unchanged and
        performs no deploy, exactly like the no-op base (Req 1.3) — never raising there, so the
        generic stage smoke tests stay valid.
        """
        _log.debug("stage participated: %s", self.stage_name)

        run_context = self._resolve_run_context()
        if run_context is None:
            # No run State bound (driven outside a harness): nothing to read or deploy.
            yield event
            return

        # Read + validate the deploy inputs; raises DeployInputError (no deploy) on a missing
        # required slot or an unsupported site version (Req 2.1-2.5).
        site, out_dir, target_repo = self._read_inputs(run_context)

        # Resolve the configured deploy mode -> the default emit-ci-workflow when unset; a bad
        # configured value raises DeployInputError (no deploy) naming the bad value + valid modes
        # (Req 3.2, 3.3, 3.4).
        mode = resolve_deploy_mode(self._deploy_mode_value())

        # Run the selected mode end to end through the pure deploy core with the injected runner.
        # Every per-target parameter comes from the consumed AssembledSite + the target path,
        # never a hardcoded DocuHarnessX value (Req 9.1, 9.2). A failed build / push raises a
        # DeployError that propagates so the run records the failure honestly (Req 5.3, 7.3).
        result = deploy_site(
            site, target_repo, out_dir, mode, runner=self._resolve_command_runner()
        )

        # Publish the frozen DeployResult seam to the run-context slot (Req 8.1).
        run_context.set_deploy_result(result)

        # Record this stage's participation in the run journal (Req 8.2) with a *bounded* deploy
        # summary — the mode, status, per-target Pages URL, written-path count, and built flag —
        # so the deploy stage is observable in the trace exactly like every other real stage,
        # while never writing a page body to the journal. No-op when no tracer is bound.
        await self._journal_participation(event, result)

        # Pure pass-through: forward the content-free event unchanged (Req 1.4).
        yield event

    # ------------------------------------------------------------------ #
    # Helpers                                                            #
    # ------------------------------------------------------------------ #

    def _resolve_run_context(self) -> RunContext | None:
        """Wrap the live run ``State`` (captured at ``task_start``) in a RunContext.

        Returns ``None`` when no ``State`` was captured (the stage is being driven outside a
        harness, with no preceding ``task_start``), so the caller forwards the event unchanged
        instead of failing (Req 1.3).
        """
        state = self._run_state
        if state is None:
            return None
        return RunContext(state)

    def _read_inputs(
        self, run_context: RunContext
    ) -> "tuple[AssembledSite, str, str]":
        """Read + validate the input slots; raise on a fatal input error.

        Reads the :class:`~docuharnessx.assembler.model.AssembledSite` (``SLOT_ASSEMBLED_SITE``),
        the resolved output directory (``SLOT_OUTPUT_DIR``), and the target-repository path
        (``SLOT_TARGET_REPO``) through the typed ``RunContext`` accessors (Req 2.1). Pins
        :data:`ASSEMBLED_SITE_SCHEMA_VERSION` and raises
        :class:`~docuharnessx.deployer.model.DeployInputError` naming the cause when the
        assembled-site, output-directory, or target-repository slot is unset, or when the site
        declares an unsupported version, performing no deploy (Req 2.2-2.5). The consumed
        ``AssembledSite`` is read verbatim, read-only (Req 2.2).
        """
        site = run_context.assembled_site()
        if site is None:
            raise DeployInputError(
                "Deploy stage cannot run: the assembled-site slot "
                f"'{SLOT_ASSEMBLED_SITE}' is unset (the Assemble stage did not publish an "
                "AssembledSite). No deploy action was performed."
            )

        # Pin the consumed site's schema version (Req 2.4): halt loudly on a version this build
        # does not support rather than deploying against an unknown shape.
        if site.schema_version != ASSEMBLED_SITE_SCHEMA_VERSION:
            raise DeployInputError(
                "Deploy stage cannot run: the AssembledSite declares unsupported "
                f"schema_version {site.schema_version!r} (this build supports "
                f"{ASSEMBLED_SITE_SCHEMA_VERSION!r}). No deploy action was performed."
            )

        out_dir = run_context.output_dir()
        if out_dir is None:
            raise DeployInputError(
                "Deploy stage cannot run: the output-directory slot "
                f"'{SLOT_OUTPUT_DIR}' is unset (no resolved output directory). "
                "No deploy action was performed."
            )

        target_repo = run_context.target_repo()
        if target_repo is None:
            raise DeployInputError(
                "Deploy stage cannot run: the target-repository slot "
                f"'{SLOT_TARGET_REPO}' is unset (no resolved target repository). "
                "No deploy action was performed."
            )

        return site, out_dir, target_repo

    def _deploy_mode_value(self) -> str | None:
        """Return the configured deploy-mode value, or ``None`` when unset.

        The mode is a per-instance value the CLI config layer / flags place on the stage (from
        ``DocgenConfig.deploy_mode`` / ``--deploy-mode``); it is reached through a concrete,
        named per-instance accessor — mirroring how
        :meth:`~docuharnessx.stages.review.ReviewStage._judge_model` reaches the bound model
        config via ``getattr(self, "_model_config", None)``. Absent (the no-config path) →
        ``None``, which :func:`~docuharnessx.deployer.resolve_deploy_mode` resolves to the
        ``emit-ci-workflow`` default (Req 3.2). The validation of a configured value is left to
        the resolver, so a bad mode surfaces as a :class:`DeployInputError` at the stage boundary
        consistent with the other fatal-input paths (Req 3.4).
        """
        return getattr(self, "_deploy_mode", None)

    def _resolve_command_runner(self) -> "CommandRunner":
        """Return the injected :class:`CommandRunner`, or a fresh production default.

        The runner isolates the only process-touching surface (the git default-branch read,
        ``mkdocs build``, ``mkdocs gh-deploy``). It is reached through a concrete, named
        per-instance accessor — mirroring how
        :meth:`~docuharnessx.stages.review.ReviewStage._judge_model` reaches its bound config —
        so tests inject a fake (no real subprocess; the ``gh-deploy`` push is never exercised —
        Req 5.4, 7.4). Absent → a fresh :class:`~docuharnessx.deployer.commands.DefaultCommandRunner`
        (the production path).
        """
        runner = getattr(self, "_command_runner", None)
        if runner is not None:
            return runner
        return DefaultCommandRunner()

    async def _journal_participation(
        self, event: StepEndEvent, result: DeployResult
    ) -> None:
        """Emit one participation trigger carrying a bounded deploy summary (Req 8.2).

        Records this stage's participation in the run journal so the trace contains a ``deploy``
        ``stage_participated`` marker — the same observability the no-op base and every other
        real stage provide — with a *summary-level* ``detail`` only: the stage name, the resolved
        mode, the status, the per-target Pages URL, the count of files written into the target
        tree, and a boolean built flag. Full written-path lists, page bodies, and the site tree
        are **never** written to the trace, keeping it bounded — mirroring
        :meth:`~docuharnessx.stages.assemble.AssembleStage._summary_detail`. Reuses the
        :class:`~docuharnessx.stages.base.NoOpStage` tracer resolution and is a no-op when no
        tracer is bound (driven outside a journaling harness).
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
                detail=self._summary_detail(result),
            )
        )

    def _summary_detail(self, result: DeployResult) -> dict[str, Any]:
        """Build the bounded, scalar-only summary recorded on the journal trigger (Req 8.2).

        Summary-level fields only — the stage name, the resolved ``mode``, the ``status``, the
        per-target ``target_pages_url``, the count of files written into the target tree, and a
        boolean ``built`` flag — read verbatim from the published
        :class:`~docuharnessx.deployer.model.DeployResult` so the journal and the seam never
        disagree. No written-path list, no page bodies, no built-site path, so the trace stays
        bounded.
        """
        return {
            "stage": self.stage_name,
            "mode": result.mode,
            "status": result.status,
            "target_pages_url": result.target_pages_url,
            "written_path_count": len(result.written_paths),
            "built": bool(result.built_path),
        }


def make_deploy_stage() -> Processor:
    """Return a fresh real Deploy-stage processor (Req 1.1 stable factory)."""
    return DeployStage()
