"""The real Assemble stage adapter (mkdocs-site-assembler task 5.1 boundary: AssembleStage).

The Assemble stage turns the quality-gated content into a publishable **Material for MkDocs**
site source tree — the bridge from "accepted segments in a store" to "a website" for an
arbitrary target project. It is a **thin HarnessX adapter** over the pure, model-free assembly
core (:mod:`docuharnessx.assembler`): all deterministic work (per-target site-identity
resolution, per-segment page rendering, per-role landing-page rendering, ``mkdocs.yml``
building, and the byte-stable tree write) lives in that package and is unit-testable without a
harness, a model, or the network. This module merely wires that core into the run lifecycle
(design "pure core + thin gated-free stage adapter"), exactly mirroring
:class:`~docuharnessx.stages.review.ReviewStage` and :class:`~docuharnessx.stages.write.WriteStage`.

It replaces the former no-op stub **in place**: the ``STAGE_NAME`` constant (``"assemble"``),
the :class:`AssembleStage` class name, the :func:`make_assemble_stage` factory, the
``make_noop_stage`` re-export, the ``__all__`` set, and this module path are kept unchanged so
the stage registry and ``make_docgen`` need no edits — the real stage drops into exactly the
slot the stub occupied (Req 1.1, 1.2, single-stage replaceability).

Lifecycle (same shape as :class:`~docuharnessx.stages.review.ReviewStage`)
--------------------------------------------------------------------------
Like every pipeline stage it does its work as a side effect of the **content-free**
``step_end`` event and yields that event **unchanged** (Req 1.4): ``StepEndEvent`` carries no
``messages``/content window, so a processor on :data:`PIPELINE_HOOK` is structurally incapable
of mutating generated content — the :class:`~docuharnessx.assembler.model.AssembledSite` is
published into a run-context *slot*, never into the conversation. The live run ``State`` is
captured from the ``TaskStartEvent`` in :meth:`on_task_start` (a pure pass-through) and wrapped
in a :class:`~docuharnessx.context.RunContext` from :meth:`on_step_end`.

Input boundary (Req 2.1-2.6)
----------------------------
With a bound run ``State`` the stage reads the input slots through the typed ``RunContext``
accessors — the :class:`~docuharnessx.review.model.ReviewReport` (``SLOT_REVIEW_REPORT``), the
loaded ``Vocabulary`` (``SLOT_VOCABULARY``), the optional
:class:`~docuharnessx.analysis.model.RepoAnalysis` (``SLOT_REPO_ANALYSIS``), the resolved output
directory (``SLOT_OUTPUT_DIR``), and the target-repository path (``SLOT_TARGET_REPO``) — pins
:data:`~docuharnessx.review.REVIEW_REPORT_SCHEMA_VERSION`, and raises
:class:`~docuharnessx.assembler.AssemblerInputError` naming the cause when the review-report,
vocabulary, or output-directory slot is unset, or when the consumed report declares an
unsupported version. It produces **no site** on that fatal path (Req 2.3, 2.4, 2.6), mirroring
:class:`~docuharnessx.review.ReviewInputError`. An absent ``RepoAnalysis`` is tolerated — the
identity resolver and the writer both ground without it (Req 2.5). The accepted segments are
consumed read-only (Req 2.6).

Driven outside a harness (no ``task_start`` to bind the run ``State`` — e.g. the generic stage
smoke suite) the stage has no ``State`` to read, so it forwards the event unchanged and produces
nothing, exactly like the no-op base (Req 1.3). It raises
:class:`~docuharnessx.assembler.AssemblerInputError` only when it *has* a run ``State`` but a
required input slot is missing or unsupported.

Per-target site identity (Req 3.x)
----------------------------------
The stage reads the per-field identity overrides (:meth:`_identity_overrides` — an overrides
mapping placed by the CLI config layer / flags; absent → an empty mapping) and the target's
``origin`` remote via the mockable, read-only :func:`~docuharnessx.assembler.read_origin_remote`
helper (the only subprocess in this spec; it degrades to ``None`` for a git-less / remote-less
target), then resolves the per-target :class:`~docuharnessx.assembler.model.SiteIdentity` via the
pure :func:`~docuharnessx.assembler.resolve_site_identity` — never DocuHarnessX's own identity
(Req 3.8). The resolved identity, the report, the vocabulary, and the optional analysis are
handed to :func:`~docuharnessx.assembler.assemble_site`, which writes the tree under
``<out_dir>/site`` and returns the frozen :class:`AssembledSite` published to
``SLOT_ASSEMBLED_SITE`` (Req 7.1).
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, AsyncIterator

from harnessx.core.events import (
    Event,
    ProcessorTriggerEvent,
    StepEndEvent,
    TaskStartEvent,
)
from harnessx.core.processor import Processor

from docuharnessx.assembler import (
    AssembledSite,
    AssemblerInputError,
    assemble_site,
    read_origin_remote,
    resolve_site_identity,
)
from docuharnessx.context import RunContext
from docuharnessx.review import REVIEW_REPORT_SCHEMA_VERSION
from docuharnessx.stages.base import (
    PIPELINE_HOOK,
    STAGE_PARTICIPATION_ACTION,
    NoOpStage,
    make_noop_stage,
)
from docuharnessx.types import (
    SLOT_OUTPUT_DIR,
    SLOT_REVIEW_REPORT,
    SLOT_VOCABULARY,
)

if TYPE_CHECKING:  # typing only
    from harnessx.core.state import State

    from docuharnessx._ontology import Vocabulary
    from docuharnessx.review.model import ReviewReport

#: Canonical stage name, used as the stage-registry key and processor identity.
STAGE_NAME = "assemble"

__all__ = ["STAGE_NAME", "AssembleStage", "make_assemble_stage", "make_noop_stage"]

_log = logging.getLogger(__name__)

#: The override keys the per-target identity resolver honors (Req 3.7). The stage forwards
#: whatever overrides mapping the CLI config layer placed; the resolver itself ignores any key
#: outside its own overridable set, so this is purely the source of the (possibly empty) mapping.
_NO_OVERRIDES: dict[str, str] = {}


class AssembleStage(NoOpStage):
    """Real Assemble stage: accepted ``Segment`` set -> Material for MkDocs source tree.

    Subclasses :class:`NoOpStage` so it inherits the runtime binding (:meth:`_bind_runtime`),
    the tracer resolution, and the attach-to-:data:`PIPELINE_HOOK` contract — the registry and
    ``make_docgen`` treat it exactly like the stub it replaces (Req 1.1, 1.2). It overrides only
    ``on_task_start`` (to capture the run ``State``) and ``on_step_end`` (to read + validate the
    assemble inputs, resolve the per-target identity, run the deterministic site writer, and
    publish the frozen :class:`~docuharnessx.assembler.model.AssembledSite`), then yields the
    event unchanged (Req 1.4).
    """

    stage_name = STAGE_NAME

    #: The live run ``State`` captured from the ``TaskStartEvent``; ``None`` until the task
    #: starts (e.g. when ``on_step_end`` is unit-driven without a task), so a harness-free
    #: smoke run forwards the event unchanged (Req 1.3).
    _run_state: "State | None" = None

    async def on_task_start(self, event: TaskStartEvent) -> AsyncIterator[Event]:
        """Capture the live run ``State``, then forward the event unchanged.

        ``TaskStartEvent`` carries the mutable run ``State`` (``StepEndEvent`` does not). We
        stash it so :meth:`on_step_end` can read the input slots and publish the assembled
        site. Pure pass-through — the same mechanism the Classify/Analyze/Plan/Write/Review
        stages use.
        """
        self._run_state = event.state
        yield event

    async def on_step_end(self, event: StepEndEvent) -> AsyncIterator[Event]:
        """Read + validate the assemble inputs, write the site, then forward the event.

        Reads the :class:`~docuharnessx.review.model.ReviewReport`, the loaded ``Vocabulary``,
        the optional :class:`~docuharnessx.analysis.model.RepoAnalysis`, the output directory,
        and the target-repository path; pins
        :data:`~docuharnessx.review.REVIEW_REPORT_SCHEMA_VERSION` and raises
        :class:`~docuharnessx.assembler.AssemblerInputError` naming the cause on a missing
        review-report/vocabulary/output-dir slot or an unsupported report version, producing no
        site (Req 2.1-2.4, 2.6). Resolves the per-target identity, runs the deterministic site
        writer, and publishes the frozen
        :class:`~docuharnessx.assembler.model.AssembledSite` to ``SLOT_ASSEMBLED_SITE`` (Req
        7.1). Yields the *same* ``StepEndEvent`` back, modifying no generated content (Req 1.4).

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

        # Read + validate the assemble inputs; raises AssemblerInputError (no site) on a missing
        # required slot or an unsupported report version (Req 2.1-2.4, 2.6).
        report, vocab, analysis, out_dir, target_repo = self._read_inputs(run_context)

        # Resolve the per-target site identity from the target git remote + overrides; never
        # DocuHarnessX's own identity (Req 3.x, 3.8). The read-only origin-remote read is the
        # only subprocess and degrades to None for a git-less / remote-less target (Req 2.5).
        overrides = self._identity_overrides()
        remote_url = read_origin_remote(target_repo)
        identity = resolve_site_identity(target_repo, remote_url, overrides)

        # Run the deterministic, model-free, network-free site writer and publish the frozen
        # AssembledSite seam (Req 7.1). The accepted segments are consumed read-only (Req 2.6).
        site = assemble_site(report, vocab, analysis, out_dir, identity)
        run_context.set_assembled_site(site)

        # Record this stage's participation in the run journal (Req 1.4) with a *bounded* site
        # summary — the page/role-page counts, the resolved ``site_name``, and the ``base_path``
        # — so the assemble stage is observable in the trace exactly like every other real
        # stage, while never writing a page body to the journal. No-op when no tracer is bound
        # (driven outside a journaling harness).
        await self._journal_participation(event, site)

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
    ) -> "tuple[ReviewReport, Vocabulary, Any, str, str]":
        """Read + validate the input slots; raise on a fatal input error.

        Reads the :class:`~docuharnessx.review.model.ReviewReport` (``SLOT_REVIEW_REPORT``), the
        loaded ``Vocabulary`` (``SLOT_VOCABULARY``), the optional
        :class:`~docuharnessx.analysis.model.RepoAnalysis` (``SLOT_REPO_ANALYSIS``), the resolved
        output directory (``SLOT_OUTPUT_DIR``), and the target-repository path
        (``SLOT_TARGET_REPO``) through the typed ``RunContext`` accessors (Req 2.1). Pins
        :data:`REVIEW_REPORT_SCHEMA_VERSION` and raises
        :class:`~docuharnessx.assembler.AssemblerInputError` naming the cause when the
        review-report, vocabulary, or output-directory slot is unset, or when the report declares
        an unsupported version, producing no site (Req 2.2-2.4, 2.6). The ``RepoAnalysis`` is
        optional — an unset slot is returned as ``None`` and tolerated (Req 2.5).
        """
        report = run_context.review_report()
        if report is None:
            raise AssemblerInputError(
                "Assemble stage cannot run: the review-report slot "
                f"'{SLOT_REVIEW_REPORT}' is unset (the Review stage did not publish a "
                "ReviewReport). No site was assembled."
            )

        # Pin the consumed report's schema version (Req 2.4): halt loudly on a version this
        # build does not support rather than assembling against an unknown shape.
        if report.schema_version != REVIEW_REPORT_SCHEMA_VERSION:
            raise AssemblerInputError(
                "Assemble stage cannot run: the ReviewReport declares unsupported "
                f"schema_version {report.schema_version!r} (this build supports "
                f"{REVIEW_REPORT_SCHEMA_VERSION!r}). No site was assembled."
            )

        vocab = run_context.vocabulary()
        if vocab is None:
            raise AssemblerInputError(
                "Assemble stage cannot run: the vocabulary slot "
                f"'{SLOT_VOCABULARY}' is unset (no project vocabulary was loaded). "
                "No site was assembled."
            )

        out_dir = run_context.output_dir()
        if out_dir is None:
            raise AssemblerInputError(
                "Assemble stage cannot run: the output-directory slot "
                f"'{SLOT_OUTPUT_DIR}' is unset (no resolved output directory). "
                "No site was assembled."
            )

        # The RepoAnalysis is optional (Req 2.5): an absent slot is tolerated and the identity
        # resolver / writer ground without it.
        analysis = run_context.repo_analysis()

        # The target-repository path drives the per-target identity (Req 3.x). An unset slot
        # degrades to the empty string, which the resolver turns into the no-remote fallback
        # (a buildable root-base-path identity) rather than aborting the run.
        target_repo = run_context.target_repo() or ""

        return report, vocab, analysis, out_dir, target_repo

    def _identity_overrides(self) -> Mapping[str, str]:
        """Return the per-field site-identity overrides mapping, or an empty mapping.

        The overrides are an ``{field: value}`` mapping the CLI config layer / flags place on
        the stage (e.g. an explicit ``site_name``/``site_url``/``repo_url``/``edit_uri``); the
        resolver applies only its own overridable keys and ignores the rest (Req 3.7). The
        mapping is reached through a concrete, named per-instance accessor — mirroring how
        :meth:`~docuharnessx.stages.review.ReviewStage._judge_model` reaches the bound model
        config via ``getattr(self, "_model_config", None)``. Absent (the credential-free /
        no-config path, and the current CLI) → an empty mapping, so the derived per-target
        identity is used verbatim. Any non-mapping value degrades to the empty mapping rather
        than perturbing the identity.
        """
        overrides = getattr(self, "_identity_overrides_config", None)
        if isinstance(overrides, Mapping):
            return overrides
        return _NO_OVERRIDES

    async def _journal_participation(
        self, event: StepEndEvent, site: AssembledSite
    ) -> None:
        """Emit one participation trigger carrying a bounded assemble summary (Req 1.4).

        Records this stage's participation in the run journal so the trace contains an
        ``assemble`` ``stage_participated`` marker — the same observability the no-op base and
        every other real stage provide — with a *summary-level* ``detail`` only: the stage
        name, the per-segment page count, the per-role landing-page count, the resolved
        ``site_name``, and the project Pages ``base_path``. Page bodies and the full page set
        are **never** written to the trace, keeping it bounded for a large accepted set —
        mirroring :meth:`~docuharnessx.stages.review.ReviewStage._summary_detail`. Reuses the
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
                detail=self._summary_detail(site),
            )
        )

    def _summary_detail(self, site: AssembledSite) -> dict[str, Any]:
        """Build the bounded, scalar-only summary recorded on the journal trigger (Req 1.4).

        Summary-level fields only — the stage name, the per-segment ``page_count``, the
        per-role ``role_page_count``, and the resolved per-target ``site_name`` and Pages
        ``base_path`` — read verbatim from the published
        :class:`~docuharnessx.assembler.model.AssembledSite` / its
        :class:`~docuharnessx.assembler.model.SiteIdentity` so the journal and the seam never
        disagree. No page bodies, no render tuples, no ``Segment`` objects, and no site_dir
        path, so the trace stays bounded for large sites.
        """
        return {
            "stage": self.stage_name,
            "page_count": site.page_count,
            "role_page_count": site.role_page_count,
            "site_name": site.identity.site_name,
            "base_path": site.identity.base_path,
        }


def make_assemble_stage() -> Processor:
    """Return a fresh real Assemble-stage processor (Req 1.1 stable factory)."""
    return AssembleStage()
