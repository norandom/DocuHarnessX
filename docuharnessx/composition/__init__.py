"""The pure, model-free COBESY composition core (Wave 2, spec #1: ``cobesy-writer``).

``docuharnessx.composition`` is the deterministic composition core behind the thin
:class:`~docuharnessx.stages.write.WriteStage` adapter. It turns each
:class:`~docuharnessx.planning.model.PlannedSegment` of the frozen ``CoveragePlan`` into
a COBESY-structured composition blueprint *before* any prose, then renders an ontology
:class:`~docuharnessx.ontology.Segment`. All structural work (blueprint, prompt, wiring,
fallback) is deterministic and unit-testable without a model; the single model-touching
step lives in :mod:`docuharnessx.composition.prose`.

This module is the **single public namespace** for the composition core (mirroring
:mod:`docuharnessx.planning`). Downstream consumers — the ``WriteStage`` adapter and
tests — import from ``docuharnessx.composition`` rather than reaching into submodules.

The namespace exposes the **frozen composition data model** from
:mod:`docuharnessx.composition.model`:

* the COBESY blueprint records (:class:`CompositionBlueprint` and its nested
  :class:`SCQAOpener` / :class:`Chunk` / :class:`EvidenceAnchor`);
* the prose result (:class:`ProseResult`);
* the output seam the review gate consumes (:class:`WrittenSegments`, :class:`WriteFlag`);
* the writer error hierarchy (:class:`WriterError`, :class:`WriterInputError`).

Finalized in the integration task (3.1) — now that the core modules exist — it also
re-exports the deterministic-core entry points so the ``WriteStage`` adapter and tests
import from ``docuharnessx.composition`` rather than reaching into submodules:

* :func:`build_blueprint` — the deterministic COBESY blueprint builder (2.1);
* :func:`build_request` — the deterministic prompt assembler (2.2);
* :func:`segment_id` / :func:`wire_segment` — the deterministic segment wiring (2.3);
* :func:`render_fallback_body` / :func:`render_fallback_summary` — the deterministic
  fallback renderer (2.4);
* :func:`generate_prose` + :data:`DEFAULT_PROSE_TIMEOUT_S` — the gated prose step, the
  only model surface (2.5).

The Wave 2.5 ``agentic-codebase-writer`` (task 1.1) adds the per-segment agentic-run
budget defaults and the structure-gate minimum-citations threshold from
:mod:`docuharnessx.composition.budgets`, re-exported here so the writer's task prompt,
harness factory, and structure gate share one set of auditable bounds:

* :data:`WRITER_MAX_STEPS`, :data:`WRITER_MAX_COST_USD`, :data:`WRITER_TOKEN_BUDGET` —
  the per-segment ``BaseTask`` caps;
* :data:`WRITER_TOKEN_THRESHOLD`, :data:`WRITER_LOOP_THRESHOLD` — the ``make_control``
  compaction and loop-halt thresholds;
* :data:`MIN_CITED_FILES` — the structure gate's minimum distinct ``file:line`` citations.

Task 2.5 finalizes the namespace by surfacing the new **agentic writer entry points** —
the bounded, codebase-grounded prose surface that replaces the single-shot ``generate_prose``
step — so the ``WriteStage`` adapter and tests import them from this one place alongside the
retained deterministic-core entry points:

* :func:`build_agent_task` — the deterministic, COBESY-seeded agentic task-prompt assembler
  scoped to the segment's evidence files and subjects (task 2.1);
* :func:`validate_agent_body` — the deterministic structure gate (≥1 valid Mermaid fence +
  ≥``MIN_CITED_FILES`` distinct ``file:line`` citations) (task 2.2);
* :func:`build_writer_harness` — the bounded, model-free read-only-repo harness factory
  (task 2.3);
* :class:`AgenticProseRunner` — the bounded per-segment agentic prose runner, the single
  model surface, returning a model-sourced :class:`ProseResult` or nothing (task 2.4);
* :class:`AgentRunStats` — the per-run, body-free telemetry record (steps, cost, exit
  reason, accepted) the bounded journal folds in (task 2.4).

The parallel core tasks (2.1-2.4) each added only their own self-contained module file
and never contended on this ``__init__``; this task wires them into the single namespace.

Each re-export is identity-equal to its submodule definition (no shadow copies), and
:data:`__all__` is the authoritative, self-consistent contract for the package (mirroring
:mod:`docuharnessx.planning`).
"""

from __future__ import annotations

from docuharnessx.composition.agent import AgenticProseRunner, AgentRunStats
from docuharnessx.composition.blueprint import build_blueprint
from docuharnessx.composition.budgets import (
    MIN_CITED_FILES,
    WRITER_LOOP_THRESHOLD,
    WRITER_MAX_COST_USD,
    WRITER_MAX_STEPS,
    WRITER_TOKEN_BUDGET,
    WRITER_TOKEN_THRESHOLD,
)
from docuharnessx.composition.fallback import (
    render_fallback_body,
    render_fallback_summary,
)
from docuharnessx.composition.harness_factory import build_writer_harness
from docuharnessx.composition.model import (
    Chunk,
    CompositionBlueprint,
    EvidenceAnchor,
    ProseResult,
    SCQAOpener,
    WriteFlag,
    WriterError,
    WriterInputError,
    WrittenSegments,
)
from docuharnessx.composition.prompt import build_request
from docuharnessx.composition.prose import DEFAULT_PROSE_TIMEOUT_S, generate_prose
from docuharnessx.composition.structure_gate import validate_agent_body
from docuharnessx.composition.task_prompt import build_agent_task
from docuharnessx.composition.wiring import segment_id, wire_segment

__all__ = [
    # frozen composition data model (task 1.1)
    "SCQAOpener",
    "Chunk",
    "EvidenceAnchor",
    "CompositionBlueprint",
    "ProseResult",
    "WriteFlag",
    "WrittenSegments",
    "WriterError",
    "WriterInputError",
    # deterministic-core entry points (tasks 2.1-2.5)
    "build_blueprint",
    "build_request",
    "segment_id",
    "wire_segment",
    "render_fallback_body",
    "render_fallback_summary",
    "generate_prose",
    "DEFAULT_PROSE_TIMEOUT_S",
    # writer budget defaults + structure-gate threshold (task 1.1)
    "WRITER_MAX_STEPS",
    "WRITER_MAX_COST_USD",
    "WRITER_TOKEN_BUDGET",
    "WRITER_TOKEN_THRESHOLD",
    "WRITER_LOOP_THRESHOLD",
    "MIN_CITED_FILES",
    # agentic writer entry points (task 2.5)
    "build_agent_task",
    "validate_agent_body",
    "build_writer_harness",
    "AgenticProseRunner",
    "AgentRunStats",
]
