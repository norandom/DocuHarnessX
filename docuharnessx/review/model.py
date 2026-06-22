"""The frozen review value objects and the review error hierarchy.

This module is the **data boundary** (design "ReviewModel") of the Wave 2
``quality-review-gate`` (task 1.1). It defines the deterministic, model-free value
objects the review core computes and the :class:`~docuharnessx.stages.review.ReviewStage`
adapter publishes, plus the error family raised at the stage boundary. It contains pure
data and errors only — the deterministic transforms live in ``criteria`` / ``prompt`` /
``parse`` / ``verdict`` / ``aggregate``, the single model surface lives in ``judge``, and
the harness adapter lives in ``stages/review.py``.

It defines the value objects of the COBESY review gate:

* The parsed, bounded judge output — :class:`JudgeVerdict` and its nested
  :class:`CriterionScore`. Produced by ``parse``/``judge`` from one bounded model call;
  carries the per-criterion scores, the per-criterion ``passed`` flags, and the judge's
  overall pass/fail with a one-line reason.
* The per-segment review entry — :class:`SegmentReview`: the segment id, the deterministic
  ``verdict`` (derived from the per-criterion thresholds + the all-of combination rule, not
  free-form prose), the per-criterion scores, the actionable findings (one per failing
  criterion), and the ``judge_source`` provenance marker.
* The aggregate quality summary — :class:`ReviewAggregate` and its nested
  :class:`CriterionTally`: the judged/accepted/rejected/unavailable counts plus the
  per-criterion pass/fail tally.
* The **output seam** the Wave 3 ``mkdocs-site-assembler`` consumes verbatim —
  :class:`ReviewReport`: the ordered per-segment entries, the accepted
  :class:`~docuharnessx.ontology.Segment` set (the *same identities* stored in the
  ``SegmentStore`` / the written set), the aggregate, and the single
  :data:`REVIEW_REPORT_SCHEMA_VERSION` version authority.

Design constraints pinned here (design "ReviewModel" + "Data Models")
---------------------------------------------------------------------
* Every report/entry/score/aggregate/verdict type is a ``@dataclass(frozen=True)`` so
  instances are immutable value objects that compare by value — deterministic and
  unit-testable, mirroring :mod:`docuharnessx.planning.model` and
  :mod:`docuharnessx.composition.model`.
* Every collection field is a ``tuple[...]`` (never a ``list``) so an instance is
  *deeply* immutable. :class:`CriterionScore`, :class:`JudgeVerdict`,
  :class:`SegmentReview`, :class:`CriterionTally`, and :class:`ReviewAggregate` carry only
  immutable members (strings, floats, bools, tuples thereof) and are therefore hashable.
* :class:`ReviewReport` is the **stabilized seam** the assembler consumes: the
  :class:`~docuharnessx.ontology.Segment` objects in :attr:`ReviewReport.accepted` are the
  *same identities* present in the ``WrittenSegments`` / ``SegmentStore``. Because the
  ontology ``Segment`` is a non-frozen dataclass (it carries mutable ``list`` fields),
  :class:`ReviewReport` is frozen and compares by value but is intentionally not relied
  upon as hashable — exactly like
  :class:`~docuharnessx.composition.model.WrittenSegments`.
* :data:`REVIEW_REPORT_SCHEMA_VERSION` is the single version authority (Req 7.6); evolution
  is additive (new optional fields with defaults), and any field-set change bumps the
  version and is a revalidation trigger for the assembler.
* The :class:`ReviewError` family is kept **independent** of the skeleton-wide error
  family (and of :class:`~docuharnessx.planning.model.PlanningError` /
  :class:`~docuharnessx.composition.model.WriterError`), matching how the planner and
  writer each keep their error family self-contained (design "Error Handling").
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:  # frozen seam consumed verbatim — typing-only import.
    from docuharnessx.ontology import Segment

__all__ = [
    "REVIEW_REPORT_SCHEMA_VERSION",
    "Verdict",
    "JudgeSource",
    "RoleContext",
    "EvidenceAnchor",
    "SegmentCriteria",
    "CriterionScore",
    "JudgeVerdict",
    "SegmentReview",
    "CriterionTally",
    "ReviewAggregate",
    "ReviewReport",
    "ReviewError",
    "ReviewInputError",
]

#: The single schema-version authority for the :class:`ReviewReport` seam. Carried on
#: :attr:`ReviewReport.schema_version`; bumped only when the frozen field set changes
#: (Req 7.6). Any change is a revalidation trigger for the ``mkdocs-site-assembler``.
REVIEW_REPORT_SCHEMA_VERSION: int = 1

#: The per-segment review outcome. A ``str`` value object: ``"pass"`` includes the
#: segment in the accepted set; ``"fail"`` excludes it (Req 6.1, 6.2).
Verdict = Literal["pass", "fail"]

#: The provenance of a segment's verdict (Req 6.4, 9.3): ``"model"`` for a production
#: judged segment, ``"fake"`` for a recorded/fake judge run, ``"unavailable"`` for the
#: fail-closed default-reject when no parseable verdict was obtained.
JudgeSource = Literal["model", "fake", "unavailable"]


# --------------------------------------------------------------------------- #
# The per-segment criteria context (the deterministic Criteria Builder output) #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class RoleContext:
    """One role or intent term's loaded-vocabulary context for the role-fit criterion.

    Carries a vocabulary term's stable machine ``id`` together with its loaded display
    ``label`` and ``description`` — read verbatim from the loaded
    :class:`~docuharnessx.ontology.Vocabulary` ``AxisTerm`` at ``build_criteria`` time
    (Req 3.2, 10.1, 10.2), never from a hardcoded role/intent table. The role-fit
    criterion (``"role_fit"``) is judged against these labels/descriptions, so a project
    that renames or re-describes a term changes the criteria context with no code change.
    An id the loaded vocabulary does not carry degrades deterministically to the id as its
    own ``label`` with an empty ``description`` (the writer guarantees membership, but the
    builder stays total). Immutable and hashable.
    """

    id: str  # the vocabulary term id (a loaded-Vocabulary member, normally)
    label: str  # the loaded display label (falls back to the id when absent)
    description: str = ""  # the loaded description ("" when absent)


@dataclass(frozen=True)
class EvidenceAnchor:
    """A grounding anchor for the falsifiability/evidence criterion (Req 2.5, 3.3).

    Built verbatim from the matching :class:`~docuharnessx.planning.model.PlannedSegment`
    :class:`~docuharnessx.planning.model.EvidenceRef` (``kind``/``detail``) and enriched
    by the matching ``RepoAnalysis`` finding when one is present; absent analysis (or no
    match) is tolerated and ``note`` falls back to ``""`` so no repository fact is invented
    (Req 2.5). Mirrors :class:`~docuharnessx.composition.model.EvidenceAnchor` so the
    review gate judges the *same* grounding the writer composed against. Read-only:
    ``build_criteria`` never mutates the consumed evidence. Immutable and hashable.
    """

    kind: str
    detail: str
    note: str = ""  # enrichment from a matching RepoAnalysis finding; "" when absent


@dataclass(frozen=True)
class SegmentCriteria:
    """The deterministic per-segment criteria context the judge prompt is built from.

    Produced by :func:`docuharnessx.review.criteria.build_criteria` for one written
    :class:`~docuharnessx.ontology.Segment` (design "Criteria Builder"; Req 3.1-3.4). It
    is pure, model-free data: the segment's identity + content, the named COBESY gate, the
    role/intent context derived from the loaded vocabulary's labels/descriptions, and the
    evidence anchors — exactly what the prompt assembler (task 2.2) and the verdict
    computer (task 2.4) need, with no harness coupling.

    * :attr:`segment_id` / :attr:`title` / :attr:`summary` / :attr:`body` — the written
      segment's identity and content (read-only copies), so the judge scores the real
      content (Req 4.2).
    * :attr:`criteria` — the fixed, named COBESY gate
      (:data:`~docuharnessx.review.criteria.COBESY_CRITERIA`) carried verbatim so the
      prompt instructs the judge to score each named criterion (Req 3.1).
    * :attr:`roles` — the per-role loaded-vocabulary :class:`RoleContext` (in the
      segment's role order), and :attr:`intent` — the intent :class:`RoleContext`; both
      derived from the loaded :class:`~docuharnessx.ontology.Vocabulary` for the role-fit
      criterion, never hardcoded (Req 3.2, 10.1, 10.2).
    * :attr:`evidence_anchors` — the grounding anchors for the falsifiability/evidence
      criterion (Req 2.5, 3.3), in the planner's evidence order.

    Every collection field is a ``tuple`` and every member is immutable, so equal inputs
    yield an equal — and hashable — criteria context (Req 3.4). Built only from frozen /
    read-only inputs; never consults a model.
    """

    segment_id: str
    title: str
    summary: str
    body: str
    criteria: tuple[str, ...]  # the fixed COBESY_CRITERIA names, verbatim
    roles: tuple[RoleContext, ...]  # loaded-vocab context per role, in segment order
    intent: RoleContext  # loaded-vocab context for the segment's intent
    evidence_anchors: tuple[EvidenceAnchor, ...]  # in planner evidence order


# --------------------------------------------------------------------------- #
# The parsed, bounded judge output                                            #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class CriterionScore:
    """One COBESY criterion's bounded score, pass flag, and one-line reason.

    Produced deterministically by ``parse`` from the judge's JSON (clamped to ``[0,1]``,
    ``passed`` coerced — defaulting to the threshold rule when absent) and carried both on
    the parsed :class:`JudgeVerdict` and on the per-segment :class:`SegmentReview`. The
    segment verdict derives from the per-criterion :attr:`passed` flags via the all-of
    combination rule, never from free-form prose (Req 6.1).

    ``name`` is a ``COBESY_CRITERIA`` member (e.g. ``"mece"`` | ``"working_memory"`` |
    ``"role_fit"`` | ``"clarity"`` | ``"falsifiability"`` | ``"no_ai_slop"``); ``score``
    is in ``[0,1]``. Immutable and hashable.
    """

    name: str  # a COBESY_CRITERIA member
    score: float  # clamped to [0, 1]
    passed: bool
    reason: str  # one-line judge reason


@dataclass(frozen=True)
class JudgeVerdict:
    """The parsed, bounded judge output for one segment (``parse``/``judge`` produce it).

    The per-criterion :attr:`scores`, the judge's :attr:`overall_passed` flag, and the
    judge's one-line :attr:`reason`. This is the *raw* parsed verdict; the deterministic
    segment :class:`SegmentReview` verdict is computed from the per-criterion ``passed``
    flags + the all-of combination rule (in ``verdict``), independent of
    :attr:`overall_passed` (Req 6.1). ``scores`` is a ``tuple`` so the verdict is deeply
    immutable and hashable.
    """

    scores: tuple[CriterionScore, ...]
    overall_passed: bool  # the judge's own overall flag (advisory; gate recomputes)
    reason: str  # the judge's one-line overall reason


# --------------------------------------------------------------------------- #
# The per-segment review entry                                                 #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class SegmentReview:
    """The per-segment review entry — one per written segment, never dropped (Req 6.4).

    Records the segment ``segment_id``, the deterministic :attr:`verdict` (``"pass"`` |
    ``"fail"``) computed from the per-criterion thresholds + the all-of combination rule
    applied to :attr:`scores` (not free-form prose, Req 6.1), the actionable
    :attr:`findings` (one per failing criterion, so the report is a usable feedback
    channel, Req 6.4), and the :attr:`judge_source` provenance marker (``"model"`` |
    ``"fake"`` | ``"unavailable"``; ``"unavailable"`` marks the fail-closed default-reject,
    Req 6.3). Both collections are ``tuple`` fields; immutable and hashable.
    """

    segment_id: str
    verdict: Verdict  # "pass" | "fail"
    scores: tuple[CriterionScore, ...]
    findings: tuple[str, ...]  # one actionable finding per failing criterion
    judge_source: JudgeSource  # "model" | "fake" | "unavailable"


# --------------------------------------------------------------------------- #
# The aggregate quality summary                                                #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class CriterionTally:
    """One COBESY criterion's pass/fail tally across all judged segments (Req 8.2).

    ``name`` is a ``COBESY_CRITERIA`` member; :attr:`passed` / :attr:`failed` are the
    counts across every per-segment entry, so a maintainer can see which criterion most
    often fails. Immutable and hashable.
    """

    name: str  # a COBESY_CRITERIA member
    passed: int
    failed: int


@dataclass(frozen=True)
class ReviewAggregate:
    """The aggregate quality summary carried on the :class:`ReviewReport` (Req 8.1, 8.2).

    Carries the total :attr:`judged` count, the :attr:`accepted` / :attr:`rejected`
    counts, the count of segments judged via the unavailable-judge default
    (:attr:`unavailable`), and the per-criterion :attr:`criterion_tally`. Given equal
    inputs and an equal (deterministic/recorded) judge source it is equal on repeated runs
    (Req 8.3). ``criterion_tally`` is a ``tuple`` so the aggregate is deeply immutable and
    hashable.
    """

    judged: int
    accepted: int
    rejected: int
    unavailable: int
    criterion_tally: tuple[CriterionTally, ...]


# --------------------------------------------------------------------------- #
# The output seam (the assembler consumes this)                                #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ReviewReport:
    """The frozen output seam published to ``SLOT_REVIEW_REPORT`` (Req 7.1, 7.4-7.6).

    The stabilized contract the Wave 3 ``mkdocs-site-assembler`` consumes verbatim:

    * :attr:`schema_version` — equals :data:`REVIEW_REPORT_SCHEMA_VERSION` (Req 7.6).
    * :attr:`entries` — the per-segment :class:`SegmentReview` entries, one per written
      segment, in the written set's deterministic order (Req 6.4, 6.6, 7.5).
    * :attr:`accepted` — exactly the segments whose entry verdict is ``"pass"``, in
      written order, carrying the *same* :class:`~docuharnessx.ontology.Segment` identities
      stored in the ``SegmentStore`` / the written set (Req 6.2, 7.4, 7.5).
    * :attr:`aggregate` — the :class:`ReviewAggregate` quality summary (Req 8).

    Invariant (design "Data Models"): every written segment has exactly one
    :attr:`entries` element; :attr:`accepted` is exactly the entries with
    ``verdict == "pass"`` carrying the same ``Segment`` identities. An empty written set
    yields a well-formed empty report (Req 6.5). The type is frozen and compares by value;
    because the ontology ``Segment`` it carries is a non-frozen dataclass with mutable list
    fields, ``ReviewReport`` is intentionally not used as a hashable key (the ``Segment``
    objects are treated read-only) — exactly like
    :class:`~docuharnessx.composition.model.WrittenSegments`.
    """

    schema_version: int  # == REVIEW_REPORT_SCHEMA_VERSION
    entries: tuple[SegmentReview, ...]  # written order; one per written segment
    accepted: "tuple[Segment, ...]"  # the pass entries in written order; same identities
    aggregate: ReviewAggregate


# --------------------------------------------------------------------------- #
# Review error hierarchy                                                       #
# --------------------------------------------------------------------------- #


class ReviewError(Exception):
    """Base class for every explicit error raised by the review core.

    Provides a single catch-all type at the stage boundary while letting each failure path
    raise a specific subclass with an explicit, cause-naming message. Kept independent of
    the skeleton-wide error family (and of
    :class:`~docuharnessx.planning.model.PlanningError` /
    :class:`~docuharnessx.composition.model.WriterError`) so the review core stays
    self-contained and harness-free (design "Error Handling").
    """


class ReviewInputError(ReviewError):
    """A required review input is missing or carries an unsupported contract version.

    Raised at the stage boundary when the ``SLOT_WRITTEN_SEGMENTS`` or ``SLOT_VOCABULARY``
    slot is unset with a bound run state, or when the consumed ``CoveragePlan`` declares a
    ``schema_version`` this build does not support. The message names the offending
    slot/version so the run halts with an identifiable cause and produces no partial output
    (Req 2.2, 2.3, 2.4). Mirrors
    :class:`~docuharnessx.planning.model.PlanningInputError` and
    :class:`~docuharnessx.composition.model.WriterInputError`.
    """
