"""The pure, model-free COBESY review-gate core (Wave 2, spec #2: ``quality-review-gate``).

``docuharnessx.review`` is the deterministic review core behind the thin
:class:`~docuharnessx.stages.review.ReviewStage` adapter. It evaluates each written
ontology :class:`~docuharnessx.ontology.Segment` against the **COBESY validation gate**
(MECE, working-memory fit, role-fit, clarity, falsifiability/evidence, no-AI-slop) and
gates which segments proceed to assembly. All structural work (criteria definition,
judge-prompt assembly, response parsing, verdict computation, accept/reject, aggregation,
report assembly) is deterministic and unit-testable without a model; the single
model-touching step lives in :mod:`docuharnessx.review.judge`.

This module is the **single public namespace** for the review core (mirroring
:mod:`docuharnessx.planning` and :mod:`docuharnessx.composition`). Downstream consumers —
the ``ReviewStage`` adapter and tests — import from ``docuharnessx.review`` rather than
reaching into submodules.

At task 1.1 the namespace exposes the **frozen review data model** from
:mod:`docuharnessx.review.model`:

* the single version authority (:data:`REVIEW_REPORT_SCHEMA_VERSION`);
* the verdict / judge-source value types (:data:`Verdict`, :data:`JudgeSource`);
* the parsed judge output (:class:`CriterionScore`, :class:`JudgeVerdict`);
* the per-segment review entry (:class:`SegmentReview`);
* the aggregate quality summary (:class:`CriterionTally`, :class:`ReviewAggregate`);
* the output seam the assembler consumes (:class:`ReviewReport`);
* the review error hierarchy (:class:`ReviewError`, :class:`ReviewInputError`).

At task 1.2 the namespace additionally exposes the **fixed COBESY gate definition
and the deterministic gate rules** from :mod:`docuharnessx.review.criteria`:

* the fixed, named criteria set (:data:`COBESY_CRITERIA`);
* the single per-criterion pass threshold (:data:`CRITERION_THRESHOLD`) and its
  rule (:func:`meets_threshold`);
* the all-of combination rule (:func:`combine_verdict`);
* the fail-closed default verdict for an unavailable judge
  (:data:`DEFAULT_UNAVAILABLE_VERDICT`).

At task 2.1 the namespace additionally exposes the **deterministic per-segment
criteria builder** and its records:

* the builder (:func:`build_criteria`) — turns one written
  :class:`~docuharnessx.ontology.Segment` (+ its planned segment, analysis, and
  the loaded vocabulary) into a deterministic
  :class:`~docuharnessx.review.model.SegmentCriteria`;
* the criteria context value object (:class:`SegmentCriteria`) and its nested
  records (:class:`RoleContext` for the vocab-derived role/intent context,
  :class:`EvidenceAnchor` for the grounding anchors).

At task 2.2 the namespace additionally exposes the **deterministic judge-prompt
assembler** from :mod:`docuharnessx.review.prompt`:

* the assembler (:func:`build_request`) — turns one
  :class:`~docuharnessx.review.model.SegmentCriteria` into the deterministic
  ``(messages, tools)`` judge request (strict per-criterion JSON-verdict instruction;
  ``tools == []``), with no model consulted.

At task 2.3 the namespace additionally exposes the **deterministic verdict parser**
from :mod:`docuharnessx.review.parse`:

* the parser (:func:`parse_verdict`) — decodes the judge's JSON reply (fenced-code
  stripping, score clamp to ``[0,1]``, per-criterion ``passed`` fallback to the threshold
  rule, known-criteria-only) into a bounded
  :class:`~docuharnessx.review.model.JudgeVerdict`, or ``None`` on malformed / empty /
  wrong-shape content, without raising or consulting a model.

At task 2.4 the namespace additionally exposes the **deterministic verdict computer** from
:mod:`docuharnessx.review.verdict`:

* the computer (:func:`compute_verdict`) — turns a parsed
  :class:`~docuharnessx.review.model.JudgeVerdict` (or the absent value ``None``) plus the
  per-segment :class:`~docuharnessx.review.model.SegmentCriteria` and a ``judge_source``
  marker into the single per-segment
  :class:`~docuharnessx.review.model.SegmentReview` entry, applying the per-criterion
  threshold + the all-of combination rule (independent of free-form judge prose) and the
  fail-closed default-reject (``judge_source="unavailable"``) on the absent verdict.

At task 2.5 the namespace additionally exposes the **deterministic aggregator and report
assembler** from :mod:`docuharnessx.review.aggregate`:

* the aggregator (:func:`aggregate`) — folds the ordered per-segment
  :class:`~docuharnessx.review.model.SegmentReview` entries into the
  :class:`~docuharnessx.review.model.ReviewAggregate` quality summary (the
  judged/accepted/rejected/unavailable counts + the per-criterion pass/fail tally);
* the report assembler (:func:`assemble_report`) — builds the accepted
  :class:`~docuharnessx.ontology.Segment` set (exactly the ``pass`` entries in written
  order, carrying the same stored identities) and assembles the frozen
  :class:`~docuharnessx.review.model.ReviewReport` output seam with the single
  :data:`~docuharnessx.review.model.REVIEW_REPORT_SCHEMA_VERSION`.

At task 3.1 the namespace additionally exposes the **gated judge step** — the only
model-touching surface of the review core — from :mod:`docuharnessx.review.judge`:

* the step (:func:`judge_segment`) — over a duck-typed bound provider, builds the request
  (reusing :func:`build_request`), drives ``complete`` once under a wall-clock timeout on a
  private loop, and delegates parsing to :func:`parse_verdict`; absorbs every failure /
  timeout / empty / unparseable response into the absent value ``None`` (fail-closed), never
  raises, never constructs a provider, and sets no segment field;
* its default wall-clock budget (:data:`DEFAULT_JUDGE_TIMEOUT_S`).

Each re-export is identity-equal to its submodule definition (no shadow copies), and
:data:`__all__` is the authoritative, self-consistent contract for the package (mirroring
:mod:`docuharnessx.planning` / :mod:`docuharnessx.composition`).
"""

from __future__ import annotations

from docuharnessx.review.criteria import (
    COBESY_CRITERIA,
    CRITERION_THRESHOLD,
    DEFAULT_UNAVAILABLE_VERDICT,
    build_criteria,
    combine_verdict,
    meets_threshold,
)
from docuharnessx.review.aggregate import aggregate, assemble_report
from docuharnessx.review.judge import DEFAULT_JUDGE_TIMEOUT_S, judge_segment
from docuharnessx.review.parse import parse_verdict
from docuharnessx.review.prompt import build_request
from docuharnessx.review.verdict import compute_verdict
from docuharnessx.review.model import (
    REVIEW_REPORT_SCHEMA_VERSION,
    CriterionScore,
    CriterionTally,
    EvidenceAnchor,
    JudgeSource,
    JudgeVerdict,
    ReviewAggregate,
    ReviewError,
    ReviewInputError,
    ReviewReport,
    RoleContext,
    SegmentCriteria,
    SegmentReview,
    Verdict,
)

__all__ = [
    # frozen review data model (task 1.1)
    "REVIEW_REPORT_SCHEMA_VERSION",
    "Verdict",
    "JudgeSource",
    "CriterionScore",
    "JudgeVerdict",
    "SegmentReview",
    "CriterionTally",
    "ReviewAggregate",
    "ReviewReport",
    "ReviewError",
    "ReviewInputError",
    # COBESY gate definition + deterministic gate rules (task 1.2)
    "COBESY_CRITERIA",
    "CRITERION_THRESHOLD",
    "DEFAULT_UNAVAILABLE_VERDICT",
    "meets_threshold",
    "combine_verdict",
    # deterministic per-segment criteria builder + its records (task 2.1)
    "RoleContext",
    "EvidenceAnchor",
    "SegmentCriteria",
    "build_criteria",
    # deterministic judge-prompt assembler (task 2.2)
    "build_request",
    # deterministic verdict parser (task 2.3)
    "parse_verdict",
    # deterministic verdict computer (task 2.4)
    "compute_verdict",
    # deterministic aggregator + report assembler (task 2.5)
    "aggregate",
    "assemble_report",
    # gated judge step — the only model surface (task 3.1)
    "judge_segment",
    "DEFAULT_JUDGE_TIMEOUT_S",
]
