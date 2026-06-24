"""The real Write stage adapter (agentic-codebase-writer task 3.1 boundary: WriteStage).

The Write stage turns each :class:`~docuharnessx.planning.model.PlannedSegment` of the
frozen :class:`~docuharnessx.planning.model.CoveragePlan` into a written, COBESY-structured
ontology :class:`~docuharnessx.ontology.Segment`, filling the ``title``/``summary``/``body``
the planner deliberately left blank. It is a **thin HarnessX adapter** over the pure,
model-free composition core (:mod:`docuharnessx.composition`): all *structural* work
(blueprint, wiring, fallback) stays deterministic; only the per-segment **prose surface** is
model-touching.

Wave 2.5 ``agentic-codebase-writer`` (this task) replaces that prose surface in place: the
former single-shot :func:`docuharnessx.composition.generate_prose` call is swapped for the
bounded :class:`~docuharnessx.composition.AgenticProseRunner`, which runs one bounded HarnessX
agent per segment over a read-only ``Workspace`` rooted at the target repository, explores the
real source through the built-in read/grep/glob/bash tools, and emits a ``file:line``-cited,
Mermaid-diagrammed body the runner gates before returning. This module merely wires that core
into the run lifecycle (design "deterministic composition core + thin gated stage adapter"),
exactly mirroring :class:`~docuharnessx.stages.plan.PlanStage`. The stable
``STAGE_NAME``/``WriteStage``/``make_write_stage``/module path, the input boundary, the
plan-order iteration, the validate/store/flag logic, and the frozen
:class:`~docuharnessx.composition.WrittenSegments` output seam are all preserved, so the
registry, ``make_docgen``, and every downstream stage need no edits (Req 1.1, 7.1-7.5).

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

Model access (Req 5.2, 5.4)
---------------------------
The bound model, if any, is obtained from the runtime-injected ``ModelConfig`` exactly as
:meth:`~docuharnessx.stages.plan.PlanStage._relevance_model` does — via a concrete, named
per-instance accessor (:meth:`_writer_model`) over ``getattr(self, "_model_config",
None).main``. The composition core never constructs a provider itself; any failure to
reach one degrades to ``None`` so a misconfigured model can never abort the write (it
falls back to the deterministic body).

Target repository + agentic fallback (Req 2.6, 5.4, 6.1, 6.3)
-------------------------------------------------------------
The agent's read-only ``Workspace`` roots at the target-repository path read from
``RunContext.target_repo()``. When a model is bound **and** that path resolves to an existing
directory, the per-segment prose comes from the bounded :class:`AgenticProseRunner` (offloaded
off the pipeline run loop via :func:`asyncio.to_thread`), and an accepted body is used
verbatim. When no model is bound, or the repo path is unset / not a directory, the stage skips
the agentic attempt entirely and renders the existing deterministic fallback for every segment
— the run never crashes (Req 2.6, 5.4, 6.3). A bound-model run whose agent raises / times out /
returns empty / over-budget / fails the structure gate likewise yields the deterministic
fallback for that segment (Req 6.1).
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import TYPE_CHECKING, Any, AsyncIterator

from harnessx.core.events import (
    Event,
    ProcessorTriggerEvent,
    StepEndEvent,
    TaskStartEvent,
)
from harnessx.core.processor import Processor

from docuharnessx.composition import (
    AgenticProseRunner,
    AgentRunStats,
    ProseResult,
    WriteFlag,
    WriterInputError,
    WrittenSegments,
    build_blueprint,
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

#: The shared, stateless bounded agentic prose runner — the single model surface of the
#: agentic writer. It builds a fresh bounded :class:`~harnessx.core.harness.Harness` +
#: :class:`~harnessx.core.harness.BaseTask` per :meth:`AgenticProseRunner.run` call, so one
#: instance can safely drive every segment of every run (Req 5.3). It never raises: every
#: agentic failure is absorbed into ``(None, stats)`` so the stage falls back deterministically
#: (Req 6.1).
_AGENT_RUNNER: AgenticProseRunner = AgenticProseRunner()


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

    #: The per-segment :class:`~docuharnessx.composition.AgentRunStats` collected during the
    #: most recent :meth:`_write_segments`, in plan order. Set just before the journal trigger
    #: is emitted so :meth:`_summary_detail` can fold a bounded, scalar-only aggregate of the
    #: agentic runs into the participation summary (Req 8.2). Empty until the first write.
    _last_agent_stats: "tuple[AgentRunStats, ...]" = ()

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
        # on a missing required slot or an unsupported plan version (Req 2.1-2.4). The
        # target-repository path is read here too: it is the (validated) root of the agent's
        # read-only workspace, or None when unset/invalid (Req 2.1, 2.6).
        plan, analysis, vocab, store, repo_path = self._read_inputs(run_context)

        # The deterministic model, if any, is reached via the named per-instance accessor
        # mirroring PlanStage._relevance_model (Req 5.2). It is absent on the
        # credential-free path; the per-segment step then falls back deterministically.
        model = self._writer_model()

        # Run the per-segment write in the plan's existing order (Req 6.6) and publish the
        # ordered WrittenSegments seam to SLOT_WRITTEN_SEGMENTS (Req 7.1, 7.4, 7.5). An
        # empty plan yields an empty written set and completes without error (Req 6.5).
        written, prose_source = await self._write_segments(
            plan, analysis, vocab, store, model, repo_path
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
    ) -> "tuple[CoveragePlan, Any, Vocabulary, SegmentStore, str | None]":
        """Read + validate the input slots; raise on a fatal input error.

        Reads the :class:`CoveragePlan` (``SLOT_COVERAGE_PLAN``), the optional
        :class:`~docuharnessx.analysis.model.RepoAnalysis` (``SLOT_REPO_ANALYSIS``), the
        loaded ``Vocabulary`` (``SLOT_VOCABULARY``), the ``SegmentStore`` handle
        (``SLOT_SEGMENT_STORE``), and the target-repository path (``SLOT_TARGET_REPO``)
        through the typed ``RunContext`` accessors (Req 2.1). Pins
        :data:`COVERAGE_PLAN_SCHEMA_VERSION` and raises :class:`WriterInputError` naming the
        cause when the plan/vocabulary/store slot is unset or the plan declares an
        unsupported version, producing no partial output (Req 2.2-2.4). The
        ``RepoAnalysis`` is optional — an unset slot is returned as ``None`` and tolerated
        by the blueprint (Req 2.5).

        The target-repository path is returned as a *validated* string when it is set and
        resolves to an existing directory, else ``None`` (Req 2.6): an unset or invalid path
        is **not** fatal — it simply disables the agentic attempt so every segment uses the
        deterministic fallback (the agent's read-only workspace can only root at a real
        directory; rooting elsewhere would raise inside the run, which the runner already
        absorbs, but resolving it here keeps the run loud-free and the journal honest).
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

        # The target-repository path is optional for the writer (Req 2.6): when set and a real
        # directory it roots the agent's read-only workspace; otherwise it degrades to None so
        # every segment uses the deterministic fallback (no run is attempted).
        repo_path = self._resolve_repo_path(run_context.target_repo())

        return plan, analysis, vocab, store, repo_path

    @staticmethod
    def _resolve_repo_path(raw: str | None) -> str | None:
        """Return *raw* iff it names an existing directory, else ``None`` (Req 2.6).

        The agent's read-only workspace can only root at a real directory. An unset slot, an
        empty string, or a path that does not resolve to an existing directory is reduced to
        ``None`` so the stage skips the agentic attempt and falls back deterministically for
        every segment rather than crashing the run.
        """
        if not raw or not os.path.isdir(raw):
            return None
        return raw

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
        repo_path: str | None,
    ) -> "tuple[WrittenSegments, str]":
        """Write every planned segment in plan order and build the output seam.

        Iterates ``plan.segments`` in their existing (deterministic) order (Req 6.6):
        for each segment it builds the deterministic COBESY blueprint, runs the bounded
        agentic prose step (off the run loop), falls back to the deterministic renderer
        when prose is unavailable, wires the ontology ``Segment``, validates it against the
        loaded ``Vocabulary``, and either stores it (adding it to the ordered written set,
        Req 6.1) or records a deterministic :class:`WriteFlag` and continues (Req 6.2, 6.4).
        An absent ``RepoAnalysis`` is tolerated — the blueprint grounds on the planner
        evidence alone (Req 2.5).

        ``repo_path`` is the validated target-repository path (or ``None``): an agentic run
        is viable only when a model is bound **and** the path is a real directory; otherwise
        every segment uses the deterministic fallback without attempting a run (Req 2.6, 5.4,
        6.3). This is decided once for the whole plan so the per-segment branch stays cheap.

        Returns the ordered :class:`WrittenSegments` whose ``segments`` are the *same
        identities* handed to ``store.put`` (Req 7.4, 7.5) paired with the aggregate
        prose-source marker for the run (``"model"``/``"fallback"``/``"fake"``,
        Req 8.3). An empty plan yields an empty written set and the model-less
        ``"fallback"`` marker (Req 6.5). Every planned segment is represented in
        ``segments`` or ``flags``, so the seam is auditable.
        """
        # An agentic attempt is viable only when BOTH a model is bound and the repo path is a
        # real directory; otherwise no run is attempted and every segment falls back (Req 2.6,
        # 5.4, 6.3).
        agentic = model is not None and repo_path is not None

        written: list[Segment] = []
        flags: list[WriteFlag] = []
        sources: list[str] = []
        stats: list[AgentRunStats] = []

        for planned in plan.segments:
            segment, source, run_stats = await self._compose_segment(
                planned, analysis, vocab, model, repo_path, agentic
            )
            sources.append(source)
            stats.append(run_stats)
            self._store_or_flag(segment, planned, store, vocab, written, flags)

        self._last_agent_stats = tuple(stats)

        return (
            WrittenSegments(
                segments=tuple(written),
                flags=tuple(flags),
                total_planned=len(plan.segments),
            ),
            _aggregate_prose_source(sources, model_bound=agentic),
        )

    async def _compose_segment(
        self,
        planned: "PlannedSegment",
        analysis: Any,
        vocab: "Vocabulary",
        model: Any | None,
        repo_path: str | None,
        agentic: bool,
    ) -> "tuple[Segment, str, AgentRunStats]":
        """Build the deterministic ``Segment`` for one planned segment (blueprint then wire).

        Builds the COBESY blueprint (deterministic, model-free), runs the bounded agentic
        prose step, and wires the ontology ``Segment``. The prose source provenance is
        recorded on the :class:`ProseResult`: ``"model"`` when the agent produced a body that
        cleared the structure gate, ``"fake"`` when an agentic run *was* attempted but its
        body was unusable (so the deterministic fallback rendered the body), and ``"fallback"``
        when no agentic run was viable at all (no model and/or no repo path; Req 5.4, 6.3,
        8.3). The agent only ever contributes ``body``/``summary``; every non-body field is
        fixed by :func:`wire_segment` (Req 4.5, 7.3). Returns the wired ``Segment`` paired with
        that prose-source marker **and** the per-run
        :class:`~docuharnessx.composition.AgentRunStats` telemetry so the bounded journal
        summary can report both (Req 8.2, 8.3).
        """
        blueprint = build_blueprint(planned, analysis, vocab)
        prose, run_stats = await self._prose_for(blueprint, model, repo_path, agentic)
        return wire_segment(planned, blueprint, prose), prose.source, run_stats

    async def _prose_for(
        self,
        blueprint: "CompositionBlueprint",
        model: Any | None,
        repo_path: str | None,
        agentic: bool,
    ) -> "tuple[ProseResult, AgentRunStats]":
        """Run the bounded agent, falling back deterministically when it returns ``None``.

        When an agentic run is viable (``agentic`` -- a model is bound and ``repo_path`` is a
        real directory) the synchronous :meth:`AgenticProseRunner.run` (which drives the
        bounded ``Harness.run`` coroutine on its own private loop) is offloaded to a worker
        thread via :func:`asyncio.to_thread` so the agent's event loop never nests inside the
        pipeline run loop (Req 5.5), exactly as :meth:`PlanStage._maybe_apply_relevance`. The
        runner gates the agent body internally (>=1 Mermaid fence + >=N ``file:line``
        citations) and returns a ``source="model"`` :class:`ProseResult` only on an accepted
        body; on raise / timeout / empty / over-budget / rejected it returns ``None`` (Req
        6.1), so the deterministic fallback renders the body with ``source="fake"`` (an agentic
        run *was* attempted). When no agentic run is viable (no model and/or no repo path) the
        deterministic fallback renders with ``source="fallback"`` and no run is attempted (Req
        2.6, 5.4, 6.3).

        Returns the :class:`ProseResult` paired with the per-run
        :class:`~docuharnessx.composition.AgentRunStats` telemetry (steps, cost, exit reason,
        accepted) so the caller can fold a bounded aggregate into the journal summary (Req
        8.2). When no run is attempted at all the stats are a zeroed, non-attempted sentinel
        whose ``exit_reason`` names *why* (``"no_model"`` when no model is bound, else
        ``"invalid_repo"`` when the model is present but the repo path is unusable) — scalar
        only, never the body.
        """
        if not agentic:
            return (
                self._fallback_prose(blueprint, source="fallback"),
                AgentRunStats(
                    steps=0,
                    cost_usd=0.0,
                    exit_reason="no_model" if model is None else "invalid_repo",
                    accepted=False,
                ),
            )

        # A model + a real repo path are present: run the bounded agent off the run loop's
        # thread so its private event loop never nests. The runner absorbs every failure and
        # gates the body, returning (None, stats) on any unusable response (Req 6.1).
        result, stats = await asyncio.to_thread(
            _AGENT_RUNNER.run, blueprint, repo_path=repo_path, model=model
        )
        if result is not None:
            return result, stats
        return self._fallback_prose(blueprint, source="fake"), stats

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
        priority-desc order, so the head is the most important), the aggregate
        ``prose_source`` marker (Req 8.3), and the bounded **agentic aggregate** folded from
        the per-segment :class:`~docuharnessx.composition.AgentRunStats` of the most recent
        write (Req 8.2). No raw ``Segment``/``ProseResult``/``AgentRunStats`` objects, no
        segment bodies, no tool outputs and no transcripts, so the trace stays bounded for
        large plans (Req 8.2).
        """
        top_written_ids = [
            seg.id for seg in written.segments[:_TOP_WRITTEN_IDS_CAP]
        ]
        detail: dict[str, Any] = {
            "stage": self.stage_name,
            "total_planned": written.total_planned,
            "written_count": len(written.segments),
            "flagged_count": len(written.flags),
            "top_written_ids": top_written_ids,
            "prose_source": prose_source,
        }
        # Fold the per-segment agentic telemetry into a bounded, scalar-only aggregate
        # alongside the existing summary fields (extend, never replace; Req 8.1, 8.2).
        detail.update(_aggregate_agent_stats(self._last_agent_stats))
        return detail


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


def _aggregate_agent_stats(
    stats: "tuple[AgentRunStats, ...]",
) -> dict[str, Any]:
    """Fold the per-segment agentic runs into one bounded, scalar-only journal aggregate.

    The bounded journal summary folds each per-segment
    :class:`~docuharnessx.composition.AgentRunStats` into a *summary-level* aggregate carrying
    only scalars (Req 8.2) — never the body, the tool outputs, or the conversation transcript:

    * ``agent_run_count`` — the number of per-segment runs recorded (one per planned segment;
      ``0`` for an empty plan);
    * ``agent_written_count`` — how many runs produced a body the structure gate accepted
      (``accepted=True``);
    * ``agent_fallback_count`` — how many runs fell back (``accepted=False``: no model /
      invalid repo / raise / timeout / empty / over-budget / rejected);
    * ``agent_total_steps`` — the summed agentic step count across the runs;
    * ``agent_total_cost_usd`` — the summed accumulated US-dollar cost across the runs;
    * ``agent_exit_reasons`` — a bounded ``{exit_reason: count}`` tally (mirroring the Review
      stage's ``judge_source`` breakdown): only reasons actually present are keyed, so a
      clean accepted run reports ``{"done": N}``, a model-less run ``{"no_model": N}``, and an
      empty plan ``{}``.

    Pure, deterministic, scalar-valued; ``accepted`` and the fallback set always partition the
    runs so ``agent_written_count + agent_fallback_count == agent_run_count`` and the
    exit-reason tally sums to ``agent_run_count``.
    """
    exit_reasons: dict[str, int] = {}
    total_steps = 0
    total_cost_usd = 0.0
    written_count = 0
    for run in stats:
        exit_reasons[run.exit_reason] = exit_reasons.get(run.exit_reason, 0) + 1
        total_steps += run.steps
        total_cost_usd += run.cost_usd
        if run.accepted:
            written_count += 1
    return {
        "agent_run_count": len(stats),
        "agent_written_count": written_count,
        "agent_fallback_count": len(stats) - written_count,
        "agent_total_steps": total_steps,
        "agent_total_cost_usd": total_cost_usd,
        "agent_exit_reasons": exit_reasons,
    }


def make_write_stage() -> Processor:
    """Return a fresh real Write-stage processor (Req 1.1 stable factory)."""
    return WriteStage()
