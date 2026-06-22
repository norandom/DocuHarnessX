"""The pure, model-free classification + coverage-planning core (Wave 1, spec #2).

``docuharnessx.planning`` is the deterministic, side-effect-free decision-intelligence
core that turns *what a repository is* (the upstream frozen
:class:`~docuharnessx.analysis.model.RepoAnalysis`) and *who reads it and why* (the
loaded, project-configurable :class:`~docuharnessx.ontology.Vocabulary` of roles x
intents x subject prefixes) into a deterministic, prioritized
:class:`~docuharnessx.planning.model.CoveragePlan`. It is stdlib-only and
unit-testable without any harness; only the two stage adapters
(``docuharnessx/stages/classify.py`` and ``plan.py``) know about HarnessX (design
"deterministic pipeline-stage adapters over a pure planning core").

This module is the **single public namespace** for the planning core (task 3.4).
Downstream consumers — the Wave 2 ``cobesy-writer``, the ``ClassifyStage`` /
``PlanStage`` adapters, and tests — import from ``docuharnessx.planning`` rather than
reaching into submodules. The re-exported surface is:

* the **frozen output seam + handoff records** (:class:`CoveragePlan`,
  :class:`PlannedSegment`, :class:`EvidenceRef`, :class:`CandidateCell`,
  :class:`Classification`) and the single version authority
  :data:`COVERAGE_PLAN_SCHEMA_VERSION` — from :mod:`docuharnessx.planning.model`;
* the **deterministic serialization** functions :func:`to_dict` / :func:`from_dict` /
  :func:`to_json` — from :mod:`docuharnessx.planning.serde`;
* the **entry points** :func:`classify_repo` (RepoAnalysis -> Classification),
  :func:`plan_coverage` (Classification -> CoveragePlan), and the optional gated
  :func:`apply_relevance` re-rank/annotate hook;
* the **deterministic-core helpers** that compose those entry points —
  :func:`derive_subjects`, :func:`activate_cells`, :func:`score_cell`,
  :func:`order_key`, :func:`vocabulary_fingerprint`, and
  :data:`DEFAULT_RELEVANCE_TIMEOUT_S`;
* the **planning error hierarchy** (:class:`PlanningError`,
  :class:`PlanningInputError`, :class:`CoveragePlanVersionError`).

Each re-export is identity-equal to its submodule definition (no shadow copies), and
:data:`__all__` is the authoritative, self-consistent contract for the package.
"""

from __future__ import annotations

from docuharnessx.planning.classifier import classify_repo, vocabulary_fingerprint
from docuharnessx.planning.matrix import activate_cells
from docuharnessx.planning.model import (
    COVERAGE_PLAN_SCHEMA_VERSION,
    CandidateCell,
    Classification,
    CoveragePlan,
    CoveragePlanVersionError,
    EvidenceRef,
    PlannedSegment,
    PlanningError,
    PlanningInputError,
)
from docuharnessx.planning.planner import plan_coverage
from docuharnessx.planning.relevance import DEFAULT_RELEVANCE_TIMEOUT_S, apply_relevance
from docuharnessx.planning.scorer import order_key, score_cell
from docuharnessx.planning.serde import from_dict, to_dict, to_json
from docuharnessx.planning.subjects import derive_subjects

__all__ = [
    "COVERAGE_PLAN_SCHEMA_VERSION",
    "DEFAULT_RELEVANCE_TIMEOUT_S",
    "CandidateCell",
    "Classification",
    "CoveragePlan",
    "CoveragePlanVersionError",
    "EvidenceRef",
    "PlannedSegment",
    "PlanningError",
    "PlanningInputError",
    "activate_cells",
    "apply_relevance",
    "classify_repo",
    "derive_subjects",
    "from_dict",
    "order_key",
    "plan_coverage",
    "score_cell",
    "to_dict",
    "to_json",
    "vocabulary_fingerprint",
]
