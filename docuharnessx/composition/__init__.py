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

The parallel core tasks (2.1-2.4) each added only their own self-contained module file
and never contended on this ``__init__``; this task wires them into the single namespace.

Each re-export is identity-equal to its submodule definition (no shadow copies), and
:data:`__all__` is the authoritative, self-consistent contract for the package (mirroring
:mod:`docuharnessx.planning`).
"""

from __future__ import annotations

from docuharnessx.composition.blueprint import build_blueprint
from docuharnessx.composition.fallback import (
    render_fallback_body,
    render_fallback_summary,
)
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
]
