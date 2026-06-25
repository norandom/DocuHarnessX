"""The bounded agentic prose runner (agentic-codebase-writer task 2.4).

``docuharnessx.composition.agent`` owns the *AgenticProseRunner* boundary of the Wave 2.5
``agentic-codebase-writer``: :class:`AgenticProseRunner` runs **one bounded HarnessX agent
per planned segment** and turns its final answer into the segment body — the single model
surface of the agentic writer (design "AgenticProseRunner", lines 389-431; Req 3.4, 3.5,
5.2, 5.3, 6.1, 8.2).

For one segment the runner:

#. builds the bounded, **model-free** read-only repo harness via
   :func:`docuharnessx.composition.harness_factory.build_writer_harness` (task 2.3), so the
   agent reads real source through the built-in read/grep/glob/bash tools but cannot modify
   the target repository;
#. binds the run's model onto that config via ``ModelConfig(main=model).agentic(config)``
   (the model is bound here, never embedded in the :class:`HarnessConfig` — steering rule);
#. builds the scoped, COBESY-seeded :class:`~harnessx.core.harness.BaseTask` via
   :func:`docuharnessx.composition.task_prompt.build_agent_task` (task 2.1), carrying the
   bounded per-segment caps (``max_steps``/``max_cost_usd``/``token_budget``);
#. drives the **real** agentic loop with ``await harness.run(task)`` so the tool outputs
   become model context (Req 3.4) — exercised offline by the scripted fake provider over the
   crafted fixture repo;
#. takes the body from ``result.task_end.final_output`` (Req 3.5) and runs it through the
   deterministic structure gate :func:`docuharnessx.composition.structure_gate.validate_agent_body`
   (task 2.2).

Two outcomes:

* **Accepted body** — the gate passes (≥1 valid Mermaid fence + ≥``MIN_CITED_FILES``
  distinct ``file:line`` citations). The runner returns
  ``(ProseResult(body=<verbatim>, summary=<derived>, source="model"), AgentRunStats(...))``
  with ``accepted=True``; the body is the agent's final answer **verbatim** (Req 4.5).
* **Failure / timeout / empty / over-budget / rejected / missing-repo / no-model** — the
  runner returns ``(None, AgentRunStats(...))`` with ``accepted=False`` so the caller (the
  :class:`~docuharnessx.stages.write.WriteStage`) renders the deterministic fallback (Req
  6.1). Every failure is **absorbed**: logged at WARNING and reduced to ``None`` — the runner
  **never raises** (Req 6.1).

Bounded by construction (Req 5.1, 5.3): a fresh harness + a fresh ``BaseTask`` per call, each
capped by the shared writer budgets (steps/cost/token) plus the harness's loop-detection and
context-compaction guards. One segment's run cannot starve the rest.

The entry point is **synchronous** so the stage can offload it with ``asyncio.to_thread``
off the pipeline run loop's thread (Req 5.5); internally it drives the harness coroutine on a
private event loop via :func:`asyncio.run`, mirroring
:func:`docuharnessx.composition.prose._complete_with_timeout` and
:meth:`docuharnessx.stages.plan.PlanStage._maybe_apply_relevance`.

Telemetry (:class:`AgentRunStats`) carries **only scalars** — ``steps``, ``cost_usd``,
``exit_reason``, ``accepted`` — and never the body, tool outputs, or conversation transcript
(Req 8.2), so the bounded journal stays auditable without leaking content.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from docuharnessx.composition.budgets import (
    MIN_CITED_FILES,
    WRITER_MAX_COST_USD,
    WRITER_MAX_STEPS,
    WRITER_TOKEN_BUDGET,
)
from docuharnessx.composition.harness_factory import build_writer_harness
from docuharnessx.composition.model import ProseResult
from docuharnessx.composition.prose import _derive_summary
from docuharnessx.composition.structure_gate import validate_agent_body
from docuharnessx.composition.task_prompt import build_agent_task

if TYPE_CHECKING:  # frozen seam consumed verbatim — typing-only import.
    from docuharnessx.composition.model import CompositionBlueprint

__all__ = ["AgentRunStats", "AgenticProseRunner"]

_log = logging.getLogger(__name__)


def _debug_agent_enabled() -> bool:
    """True when ``DHX_DEBUG_AGENT`` is set — log the full rejected agent body.

    Diagnostic only: when a real run's bodies keep failing the structure gate it is
    invaluable to see *what* the model actually wrote (did it read files? how did it
    cite?). Off by default so bodies never leak into normal logs.
    """
    return os.environ.get("DHX_DEBUG_AGENT", "").strip().lower() in {"1", "true", "yes", "on"}


# --------------------------------------------------------------------------- #
# Per-run telemetry value object (Req 8.2)                                     #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class AgentRunStats:
    """The bounded, scalar-only telemetry of one per-segment agentic run (Req 8.2).

    A frozen value object the bounded journal folds into its summary aggregate. It carries
    **only scalars** so it can never leak the segment body, tool outputs, or the conversation
    transcript into the journal:

    :param steps: the number of agentic steps the run took (``task_end.total_steps``); ``0``
        when no run was attempted (no model / invalid repo path) or the run never started.
    :param cost_usd: the run's accumulated US-dollar cost (``task_end.total_cost_usd``); ``0.0``
        when no run was attempted.
    :param exit_reason: why the run ended — ``"done"`` on a clean end-turn,
        ``"over_budget"``/``"loop"``/``"max_steps"`` etc. from the harness when a bound tripped,
        ``"error"`` when the run raised, or a runner sentinel
        (``"no_model"``/``"invalid_repo"``) when no run was attempted. Never the body.
    :param accepted: ``True`` iff the run produced a body the structure gate accepted (so the
        runner returned a ``source="model"`` :class:`ProseResult`); ``False`` on every
        fallback path.
    """

    steps: int
    cost_usd: float
    exit_reason: str
    accepted: bool


# --------------------------------------------------------------------------- #
# The bounded agentic prose runner (the only model surface; never raises)      #
# --------------------------------------------------------------------------- #


class AgenticProseRunner:
    """Run one bounded HarnessX agent per segment; return a grounded body or ``None``.

    Stateless: a single instance can drive every segment of a run (one fresh bounded
    :class:`~harnessx.core.harness.Harness` + :class:`~harnessx.core.harness.BaseTask` per
    :meth:`run` call, Req 5.3). The runner is the agentic writer's **only** model surface;
    all failures are absorbed so it never raises (Req 6.1).
    """

    def run(
        self,
        blueprint: "CompositionBlueprint",
        *,
        repo_path: str,
        model: Any | None,
        guidance: str = "",
        min_citations: int = MIN_CITED_FILES,
        max_steps: int = WRITER_MAX_STEPS,
        max_cost_usd: float = WRITER_MAX_COST_USD,
        token_budget: int = WRITER_TOKEN_BUDGET,
    ) -> tuple[ProseResult | None, AgentRunStats]:
        """Run the bounded agent for one segment; return ``(ProseResult|None, AgentRunStats)``.

        Builds the read-only repo harness (2.3), binds ``model`` via
        ``ModelConfig(main=model).agentic(config)``, builds the scoped COBESY task (2.1),
        drives the real agentic loop so tool outputs become model context (Req 3.4), takes
        ``task_end.final_output`` as the body (Req 3.5), and gates it (2.2).

        Args:
            blueprint: the deterministic COBESY blueprint for one planned segment; read-only,
                never mutated. Its ``evidence_anchors`` + ``subjects`` scope the task (2.1).
            repo_path: the target-repository path the agent's read-only ``Workspace`` roots
                at. A missing/invalid path is absorbed → ``(None, stats)`` (Req 2.6 driver).
            model: a bound HarnessX ``BaseModelProvider``-shaped object, or ``None``. ``None``
                means no run is attempted (Req 5.4) → ``(None, stats)``.
            guidance: optional human refinement guidance shaping WHAT the agent writes and
                emphasises (docuharnessx-mcp-refine task 2.3). Forwarded verbatim to
                :func:`~docuharnessx.composition.task_prompt.build_agent_task` and rendered as
                an applied, never-echoed author-guidance instruction; defaults to ``""`` so the
                rendered task stays byte-identical to today's for every existing caller.
            min_citations: the structure gate's minimum distinct ``file:line`` citations and
                the same minimum the task prompt demands; defaults to :data:`MIN_CITED_FILES`.
            max_steps: ``BaseTask.max_steps`` cap for this run; defaults to
                :data:`WRITER_MAX_STEPS` (Req 5.1).
            max_cost_usd: ``BaseTask.max_cost_usd`` cap; defaults to
                :data:`WRITER_MAX_COST_USD` (Req 5.1).
            token_budget: ``BaseTask.token_budget`` cap; defaults to
                :data:`WRITER_TOKEN_BUDGET` (Req 5.1).

        Returns:
            ``(ProseResult, AgentRunStats)`` with ``source="model"`` and ``accepted=True`` on
            an accepted body; ``(None, AgentRunStats)`` with ``accepted=False`` on
            no-model / invalid-repo / raise / timeout / empty / over-budget / rejected, so the
            caller renders the deterministic fallback. **Never raises** (Req 6.1).
        """
        seg = getattr(blueprint, "segment_key", "?")

        # Gate 1 — no model bound: the run is not attempted (Req 5.4); the caller falls back.
        if model is None:
            return None, AgentRunStats(
                steps=0, cost_usd=0.0, exit_reason="no_model", accepted=False
            )

        # Gate 2 — the harness factory requires a real directory to root the read-only
        # workspace; an unset/invalid repo path is absorbed here (Req 2.6 driver) rather than
        # crashing the segment loop.
        try:
            config = build_writer_harness(repo_path)
        except Exception as exc:
            # Absorbed, not a crash: log a one-line WARNING with the error (no traceback —
            # exc_info would render as a full colorized stack via better_exceptions and read
            # like an unhandled failure) and fall back to the deterministic body.
            _log.warning(
                "Agentic writer could not root a read-only workspace at repo_path=%r for "
                "segment %r (%s: %s); falling back to the deterministic body.",
                repo_path,
                seg,
                type(exc).__name__,
                exc,
            )
            return None, AgentRunStats(
                steps=0, cost_usd=0.0, exit_reason="invalid_repo", accepted=False
            )

        # Build the bounded, scoped task (2.1) — deterministic, blueprint-derived, model-free.
        task = build_agent_task(
            blueprint,
            repo_path=repo_path,
            min_citations=min_citations,
            max_steps=max_steps,
            max_cost_usd=max_cost_usd,
            token_budget=token_budget,
            guidance=guidance,
        )

        # Drive the real bounded agentic loop on a private event loop; absorb every failure.
        try:
            body, exit_reason, steps, cost_usd, tokens = self._run_bounded(
                model, config, task
            )
        except Exception as exc:
            # Absorbed, not a crash: a one-line WARNING with the error (no traceback —
            # see the invalid-repo path above) and fall back to the deterministic body.
            _log.warning(
                "Agentic writer run failed for segment %r (%s: %s); falling back to the "
                "deterministic body.",
                seg,
                type(exc).__name__,
                exc,
            )
            return None, AgentRunStats(
                steps=0, cost_usd=0.0, exit_reason="error", accepted=False
            )

        # Empty final answer — over-budget/early-stop with no usable text, or an empty
        # end-turn (Req 5.2, 6.1). No body to gate; fall back.
        if not isinstance(body, str) or not body.strip():
            _log.warning(
                "Agentic writer returned an empty answer for segment %r "
                "(exit=%s, steps=%s, tokens=%s, cost=$%.4g); falling back to the "
                "deterministic body.",
                seg,
                exit_reason,
                steps,
                tokens,
                cost_usd,
            )
            return None, AgentRunStats(
                steps=steps, cost_usd=cost_usd, exit_reason=exit_reason, accepted=False
            )

        # Deterministic structure gate (2.2): accept verbatim only with Mermaid + citations.
        gate = validate_agent_body(body, min_citations=min_citations)
        if not gate.accepted:
            # steps/exit_reason are the key diagnostic: steps<=1 means the model never
            # looped through the read tools (answered blind → nothing to cite); steps>1
            # means it explored but did not cite in the expected ``file:line`` form or
            # omitted the Mermaid fence. Set DHX_DEBUG_AGENT=1 to dump the full body.
            _log.warning(
                "Agentic writer body rejected by the structure gate for segment %r "
                "(%s; steps=%s, exit=%s, tokens=%s, cost=$%.4g, body_chars=%d); falling "
                "back to the deterministic body.",
                seg,
                gate.reason,
                steps,
                exit_reason,
                tokens,
                cost_usd,
                len(body),
            )
            if _debug_agent_enabled():
                _log.warning("[DHX_DEBUG_AGENT] rejected body for %r:\n%s", seg, body)
            return None, AgentRunStats(
                steps=steps, cost_usd=cost_usd, exit_reason=exit_reason, accepted=False
            )

        # Accepted: the body is the agent's final answer verbatim (Req 3.5, 4.5); the summary
        # is a deterministic one-liner derived from it (the agentic body carries no separate
        # summary field). The prose source sets only body/summary (Req 5.5).
        result = ProseResult(
            body=body,
            summary=_derive_summary(body),
            source="model",
        )
        return result, AgentRunStats(
            steps=steps, cost_usd=cost_usd, exit_reason=exit_reason, accepted=True
        )

    # ----------------------------------------------------------------------- #
    # Private: drive the harness coroutine on a private event loop             #
    # ----------------------------------------------------------------------- #

    @staticmethod
    def _run_bounded(
        model: Any, config: Any, task: Any
    ) -> tuple[str, str, int, float, int]:
        """Bind the model, drive one bounded ``Harness.run`` on a private loop, read the result.

        Binds ``model`` onto the model-free ``config`` via
        ``ModelConfig(main=model).agentic(config)`` (the model is bound here, not embedded in
        the config — steering rule) and drives the resulting :class:`Harness` coroutine to
        completion with :func:`asyncio.run`, exactly as
        :func:`docuharnessx.composition.prose._complete_with_timeout` drives the prose call —
        so the synchronous :meth:`run` entry point can itself be offloaded off the pipeline
        run loop with :func:`asyncio.to_thread` (Req 5.5). The per-run step/cost/token caps
        on the ``BaseTask`` plus the harness's loop-detection and compaction guards bound the
        run (Req 5.1); a tripped bound surfaces as a non-``"done"`` ``exit_reason`` with
        whatever partial answer exists (Req 5.2).

        Returns ``(final_output, exit_reason, total_steps, total_cost_usd, total_tokens)``
        read from ``result.task_end`` (``total_tokens``/``total_cost_usd`` are ``0`` when the
        endpoint does not report usage). The harness is always cleaned up via ``cleanup()`` on the
        same private loop so per-segment runs leave no live harness behind (Req 5.3). Any
        exception propagates to the caller, which absorbs it into the fallback path.
        """
        from harnessx.core.model_config import ModelConfig

        async def _drive() -> tuple[str, str, int, float, int]:
            harness = ModelConfig(main=model).agentic(config)
            try:
                result = await harness.run(task)
                end = result.task_end
                return (
                    getattr(end, "final_output", "") or "",
                    getattr(end, "exit_reason", "done") or "done",
                    int(getattr(end, "total_steps", 0) or 0),
                    float(getattr(end, "total_cost_usd", 0.0) or 0.0),
                    int(getattr(end, "total_tokens", 0) or 0),
                )
            finally:
                try:
                    await harness.cleanup()
                except Exception:  # pragma: no cover - cleanup is best-effort
                    pass

        return asyncio.run(_drive())
