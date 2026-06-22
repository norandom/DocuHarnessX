"""The frozen ``CoveragePlan`` seam, the Classify->Plan handoff, and planning errors.

This module is the **model boundary** of the classification-coverage-planner (task
1.1). It defines:

* The **frozen, versioned output seam** the Wave 2 ``cobesy-writer`` consumes verbatim
  — :class:`CoveragePlan` and its nested :class:`PlannedSegment` / :class:`EvidenceRef`
  records, plus the single version authority :data:`COVERAGE_PLAN_SCHEMA_VERSION`.
* The **intermediate Classify->Plan handoff** records owned by this spec —
  :class:`CandidateCell` (one activated role x intent cell) and :class:`Classification`
  (the value object the internal handoff slot carries).
* The **planning error hierarchy** — :class:`PlanningError` base, the fatal-input
  :class:`PlanningInputError`, and the deserialization :class:`CoveragePlanVersionError`.

Design constraints pinned here (design "model — CoveragePlan (the frozen seam)")
--------------------------------------------------------------------------------
* Every type is a ``@dataclass(frozen=True)`` so instances are immutable value objects
  consumers cannot mutate (Req 6.1).
* Every collection field is a ``tuple[...]`` (never a ``list``) so an instance is
  *deeply* immutable and hashable (Req 6.1). The planner is responsible for building
  each tuple pre-ordered in the order documented on the field, so two runs over equal
  inputs yield equal objects (Req 5.3, 6.4). The model itself performs no ordering.
* :data:`COVERAGE_PLAN_SCHEMA_VERSION` is the single version authority, carried on
  :attr:`CoveragePlan.schema_version` (Req 6.3). Evolution is additive (new optional
  fields with defaults); the version bumps only when the frozen field set changes
  (Req 6.6).
* Each :class:`PlannedSegment` keys to the ontology segment schema: it carries the axis
  values a writer needs to fill a ``Segment`` — ``roles`` (role ids), ``subjects``
  (typed ontology :class:`~docuharnessx.ontology.Subject` values), ``intent`` (intent
  id) — plus a deterministic plan-local ``segment_key``, a ``priority`` score, and
  ``evidence`` references. It deliberately does NOT carry title/summary/body (the
  writer authors those) (Req 6.2).

This module defines pure data and errors only — serialization lives in ``serde`` (task
1.2), the deterministic transforms live in ``subjects`` / ``matrix`` / ``classifier`` /
``scorer`` / ``planner``, and the stage adapters live in ``stages/`` (task 1.1
boundary: model). It reuses the ontology :class:`~docuharnessx.ontology.Subject` type
verbatim and reimplements no ontology logic.
"""

from __future__ import annotations

from dataclasses import dataclass

from docuharnessx.ontology import Subject

__all__ = [
    "COVERAGE_PLAN_SCHEMA_VERSION",
    "EvidenceRef",
    "PlannedSegment",
    "CoveragePlan",
    "CandidateCell",
    "Classification",
    "PlanningError",
    "PlanningInputError",
    "CoveragePlanVersionError",
]

#: The single schema-version authority for the :class:`CoveragePlan` seam. Carried on
#: :attr:`CoveragePlan.schema_version`; bumped only when the frozen field set changes
#: (Req 6.3, 6.6).
COVERAGE_PLAN_SCHEMA_VERSION: int = 1


# --------------------------------------------------------------------------- #
# Evidence reference                                                           #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class EvidenceRef:
    """A single auditable reference to the analysis finding behind a decision.

    Records *why* a subject was derived or a cell activated/ranked: a finding
    ``kind`` (e.g. ``"entrypoint"`` | ``"ci"`` | ``"test"`` | ``"dependency"`` |
    ``"component"`` | ``"doc"`` | ``"artifact"`` | ``"language"``) plus a deterministic
    ``detail`` (a repo-relative path or a canonical finding token). It carries no
    free-form score — weighting lives entirely in the scorer (design
    "model — CoveragePlan").
    """

    kind: str
    detail: str


# --------------------------------------------------------------------------- #
# The frozen output seam (the writer consumes EXACTLY this)                    #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class PlannedSegment:
    """One planned content segment: the axis values a writer fills into a ``Segment``.

    Keys to the ontology segment required-field set — ``roles`` (role ids),
    ``subjects`` (typed :class:`~docuharnessx.ontology.Subject` values), ``intent``
    (intent id) — so the Wave 2 writer can fill title/summary/body from these (Req 6.2).
    It additionally carries a deterministic plan-local ``segment_key``, the integer
    ``priority`` score (higher = more important), and the ``evidence`` references it was
    derived/ranked from (Req 5.4).

    ``relevance_note`` is an OPTIONAL annotation set by the gated LLM relevance hook;
    it defaults to ``""`` so the deterministic core never sets it (Req 8.2).

    The planner builds every collection pre-ordered (``subjects`` sorted by
    ``Subject.canonical()``, ``evidence`` sorted by ``(kind, detail)``, ``roles`` in
    declared vocabulary order); this frozen record performs no ordering itself.
    """

    segment_key: str  # deterministic plan-local key, e.g. "<role>__<intent>__<digest>"
    roles: tuple[str, ...]  # role ids (loaded-Vocabulary members), declared order
    intent: str  # intent id (a loaded-Vocabulary member)
    subjects: tuple[Subject, ...]  # typed ontology Subjects, sorted by canonical()
    priority: int  # deterministic priority score (higher = more important)
    evidence: tuple[EvidenceRef, ...]  # sorted by (kind, detail); why this is planned
    relevance_note: str = ""  # OPTIONAL gated-LLM annotation; "" by default (Req 8.2)


@dataclass(frozen=True)
class CoveragePlan:
    """The frozen, versioned, serializable seam the Wave 2 writer consumes (Req 6.1).

    Aggregates the ordered planned segments plus provenance: the ``repo_path`` planned
    over and a deterministic ``vocabulary_fingerprint`` of the loaded vocabulary
    (roles + intents + prefixes). ``schema_version`` equals
    :data:`COVERAGE_PLAN_SCHEMA_VERSION` (Req 6.3).

    ``segments`` is ordered by priority desc, then role order, then intent order, then
    the stable ``segment_key`` (the planner establishes this order; the model performs
    no ordering, Req 5.2). An empty ``segments`` tuple is a valid, well-formed plan when
    no cell is activated (Req 5.5).

    ``relevance_applied`` is ``True`` only when the optional, gated LLM relevance hook
    ran and was applied; it defaults to ``False`` for the deterministic core (Req 8.2).
    """

    schema_version: int  # == COVERAGE_PLAN_SCHEMA_VERSION
    repo_path: str  # provenance: the analysis.repo_path planned over
    vocabulary_fingerprint: str  # deterministic digest of the vocabulary used
    segments: tuple[PlannedSegment, ...]  # ordered priority desc, then role/intent/key
    relevance_applied: bool = False  # True iff the gated LLM hook ran + applied (Req 8.2)


# --------------------------------------------------------------------------- #
# Intermediate Classify -> Plan handoff (owned here, internal slot)            #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class CandidateCell:
    """One activated role x intent coverage cell (the Classify -> Plan handoff unit).

    Produced by the coverage matrix when an evidence predicate fires: the ``roles`` it
    serves and the ``intent`` it addresses (all loaded-Vocabulary members), the typed
    ``subjects`` attached to the cell, and the ``evidence`` findings that activated it.
    The planner scores each cell and materializes it into a :class:`PlannedSegment`.
    """

    roles: tuple[str, ...]  # role ids the cell serves (vocabulary members)
    intent: str  # intent id (a vocabulary member)
    subjects: tuple[Subject, ...]  # typed subjects attached to the cell
    evidence: tuple[EvidenceRef, ...]  # findings that activated the cell


@dataclass(frozen=True)
class Classification:
    """The intermediate value object the internal Classify -> Plan handoff slot carries.

    Aggregates every derived subject (sorted by ``Subject.canonical()``), every
    activated :class:`CandidateCell` (deterministically ordered), and the provenance the
    plan inherits: the ``repo_path`` classified and the ``vocabulary_fingerprint`` of
    the loaded vocabulary. Deterministic by construction — the classifier builds
    pre-ordered tuples so two runs over equal inputs yield equal objects (Req 4.5).
    """

    repo_path: str
    vocabulary_fingerprint: str
    subjects: tuple[Subject, ...]  # all derived subjects, sorted by canonical()
    cells: tuple[CandidateCell, ...]  # activated role x intent cells, ordered


# --------------------------------------------------------------------------- #
# Planning error hierarchy                                                     #
# --------------------------------------------------------------------------- #


class PlanningError(Exception):
    """Base class for every explicit error raised by the planning core.

    Provides a single catch-all type at the stage boundary while letting each failure
    path raise a specific subclass with an explicit, cause-naming message. Kept
    independent of the skeleton-wide ``DocuHarnessXError`` family so the pure planning
    core stays self-contained and harness-free (design "Error Handling").
    """


class PlanningInputError(PlanningError):
    """A required planning input is missing or carries an unsupported contract version.

    Raised at the stage boundary when ``RunContext.repo_analysis()`` or
    ``RunContext.vocabulary()`` is unset at Classify, when ``RunContext.classification()``
    is unset at Plan, or when the consumed ``RepoAnalysis`` declares a ``schema_version``
    this build does not support. The message names the offending slot/cause so the run
    halts with an identifiable cause rather than emitting a partial or guessed plan
    (Req 2.3, 2.4, 2.5).
    """


class CoveragePlanVersionError(PlanningError):
    """A serialized ``CoveragePlan`` carries an unsupported ``schema_version``.

    Raised by ``serde.from_dict`` when the ``schema_version`` it is handed is not the
    one this build understands, so a consumer reading a future/foreign contract fails
    loudly with a message naming the offending version rather than silently
    mis-reconstructing the seam (Req 6.5).
    """
