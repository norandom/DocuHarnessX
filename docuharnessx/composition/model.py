"""The frozen composition value objects and the writer error hierarchy.

This module is the **data boundary** of the Wave 2 ``cobesy-writer`` (task 1.1). It
defines the deterministic, model-free value objects the composition core produces and
the stage adapter publishes, plus the error family raised at the stage boundary. It
contains pure data and errors only — the deterministic transforms live in ``blueprint``
/ ``prompt`` / ``wiring`` / ``fallback``, the single model surface lives in ``prose``,
and the harness adapter lives in ``stages/write.py``.

It defines three layers of value objects:

* The **COBESY composition blueprint** — :class:`CompositionBlueprint` and its nested
  :class:`SCQAOpener` / :class:`Chunk` / :class:`EvidenceAnchor`. Built deterministically
  per :class:`~docuharnessx.planning.model.PlannedSegment` *before* any prose, it encodes
  the SCQA opener (tuned to the segment's role(s)+intent via the loaded ``Vocabulary``
  labels), the Minto lead-with-conclusion key message, working-memory chunks, the
  REDUCE-barrier fast path, the andragogy (expert-framing) flag, and the evidence anchors.
* The **prose result** — :class:`ProseResult`, the ``body``/``summary``/``source`` carrier
  the gated model step (or the deterministic fallback) returns.
* The **output seam** the Wave 2 ``quality-review-gate`` consumes verbatim —
  :class:`WrittenSegments` (an ordered view over the stored :class:`~docuharnessx.ontology.Segment`
  identities plus the :class:`WriteFlag` records and the planned total).

Design constraints pinned here (design "CompositionModel")
----------------------------------------------------------
* Every blueprint/result/flag/written-set type is a ``@dataclass(frozen=True)`` so
  instances are immutable value objects that compare by value — deterministic and
  unit-testable, mirroring :mod:`docuharnessx.planning.model`.
* Every collection field is a ``tuple[...]`` (never a ``list``) so an instance is
  *deeply* immutable. The blueprint value objects carry only immutable members
  (strings, tuples, frozen :class:`~docuharnessx.ontology.Subject` values) and are
  therefore hashable.
* :class:`WrittenSegments` is the **stabilized seam** the review gate consumes: a thin,
  ordered view whose :class:`~docuharnessx.ontology.Segment` objects are the *same
  identities* stored in the ``SegmentStore``. Because the ontology ``Segment`` is a
  non-frozen dataclass (it carries mutable ``list`` fields), :class:`WrittenSegments` is
  frozen and compares by value but is intentionally not relied upon as hashable.
* The :class:`WriterError` family is kept **independent** of the skeleton-wide error
  family (and of :class:`~docuharnessx.planning.model.PlanningError`), matching how the
  planner keeps ``PlanningError`` self-contained (design "Error Handling").
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # frozen seams consumed verbatim — typing-only imports.
    from docuharnessx.ontology import Segment, Subject

__all__ = [
    "SCQAOpener",
    "Chunk",
    "EvidenceAnchor",
    "CompositionBlueprint",
    "ProseResult",
    "WriteFlag",
    "WrittenSegments",
    "WriterError",
    "WriterInputError",
]


# --------------------------------------------------------------------------- #
# Blueprint nested records                                                     #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class SCQAOpener:
    """The Situation-Complication-Question-Answer opener for one segment.

    Tuned to the segment's role(s) and intent as read from the loaded ``Vocabulary``
    (never a hardcoded role/intent list, Req 3.2). The ``answer`` is the Minto lead
    conclusion echoed into the opener so the body leads with the conclusion (Req 3.3).
    Immutable and hashable.
    """

    situation: str
    complication: str
    question: str
    answer: str  # the Minto lead conclusion echoed into the opener


@dataclass(frozen=True)
class Chunk:
    """One working-memory chunk: a descriptive subhead plus its MECE support points.

    The ordered :attr:`chunks` of a :class:`CompositionBlueprint` encode the
    working-memory chunking plan (Req 3.3): each chunk is a digestible unit a reader can
    hold at once. ``points`` is a ``tuple`` so the chunk is deeply immutable and hashable.
    """

    heading: str
    points: tuple[str, ...]


@dataclass(frozen=True)
class EvidenceAnchor:
    """A grounding anchor derived from a planner ``EvidenceRef`` (+ matching analysis).

    Built verbatim from the segment's :class:`~docuharnessx.planning.model.EvidenceRef`
    (``kind``/``detail``) and enriched by the matching ``RepoAnalysis`` finding when one
    is present; absent analysis is tolerated and ``note`` falls back to ``""`` (Req 2.5,
    3.5). Read-only: the blueprint never mutates the consumed evidence.
    """

    kind: str
    detail: str
    note: str = ""  # enrichment from a matching RepoAnalysis finding; "" when absent


# --------------------------------------------------------------------------- #
# The deterministic COBESY blueprint                                           #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class CompositionBlueprint:
    """The deterministic per-segment COBESY plan, built before any prose (Req 3.1).

    Carries the segment's axis values (``roles``/``intent``/``subjects``, copied verbatim
    from the :class:`~docuharnessx.planning.model.PlannedSegment` — read-only inputs,
    Req 2.6) plus the COBESY structure derived from the loaded ``Vocabulary``:

    * :attr:`scqa` — the SCQA opener tuned to the role(s)+intent labels (Req 3.2).
    * :attr:`key_message` — the Minto lead-with-conclusion key message (Req 3.3).
    * :attr:`chunks` — the ordered working-memory chunking plan (Req 3.3).
    * :attr:`fast_path` — the REDUCE-barrier fast-path cues to first success (Req 3.3).
    * :attr:`andragogy` — ``True`` when the segment serves an expert role per the loaded
      ``Vocabulary`` term (Req 3.4); not a closed role set.
    * :attr:`evidence_anchors` — the grounding anchors (Req 3.5).
    * :attr:`role_labels` / :attr:`intent_label` — the loaded ``Vocabulary``
      ``AxisTerm`` labels used to shape the blueprint (Req 9.2), retained for the prompt
      assembler and fallback renderer so they need not re-resolve the vocabulary.

    Every collection field is a ``tuple`` and every member is immutable, so equal inputs
    yield an equal — and hashable — blueprint (Req 3.6).
    """

    segment_key: str
    roles: tuple[str, ...]
    intent: str
    subjects: "tuple[Subject, ...]"
    title: str
    scqa: SCQAOpener
    key_message: str  # the Minto lead conclusion
    chunks: tuple[Chunk, ...]  # working-memory ordered support
    fast_path: tuple[str, ...]  # REDUCE-barrier steps to first success
    andragogy: bool
    evidence_anchors: tuple[EvidenceAnchor, ...]
    role_labels: tuple[str, ...]
    intent_label: str


# --------------------------------------------------------------------------- #
# The prose result (model or deterministic fallback)                           #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ProseResult:
    """The ``body``/``summary`` text produced for one segment, plus its provenance.

    The gated model step returns ``source="model"`` on a clean response; the stage marks
    ``source="fallback"`` (no/failed model) or ``source="fake"`` (a recorded/fake
    provider) when the deterministic fallback renderer produced the text (Req 8.3). The
    prose source only ever sets ``body``/``summary`` — never any non-body ``Segment``
    field (Req 5.5).
    """

    body: str
    summary: str
    source: str  # "model" | "fallback" | "fake"


# --------------------------------------------------------------------------- #
# The output seam (the review gate consumes this)                              #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class WriteFlag:
    """A deterministic record that one planned segment was not stored.

    Recorded when a produced :class:`~docuharnessx.ontology.Segment` fails validation
    against the loaded ``Vocabulary`` or storing it raises an ``IdConflictError`` (Req
    6.2, 6.4): the planner-supplied ``segment_key``, a short ``reason`` category, and the
    scalar ``cause`` string. Every planned segment is represented either in
    :attr:`WrittenSegments.segments` or in :attr:`WrittenSegments.flags`.
    """

    segment_key: str
    reason: str  # category, e.g. "validation" | "id_conflict"
    cause: str  # the scalar, deterministic cause message


@dataclass(frozen=True)
class WrittenSegments:
    """The frozen output seam published to ``SLOT_WRITTEN_SEGMENTS`` (Req 7.1, 7.4).

    A thin, ordered view the Wave 2 ``quality-review-gate`` consumes verbatim:

    * :attr:`segments` — the successfully written, valid :class:`~docuharnessx.ontology.Segment`
      objects in the plan's deterministic order; these are the *same identities* stored
      in the ``SegmentStore`` (Req 7.4, 7.5).
    * :attr:`flags` — the :class:`WriteFlag` records for planned segments that were not
      stored (Req 6.2, 6.4).
    * :attr:`total_planned` — the count of planned segments the writer processed.

    Invariant: every planned segment appears in :attr:`segments` or :attr:`flags` (so the
    seam is auditable and ``len(segments) + len(flags) <= total_planned``). The type is
    frozen and compares by value; because the ontology ``Segment`` it carries is a
    non-frozen dataclass with mutable list fields, ``WrittenSegments`` is intentionally
    not used as a hashable key (the ``Segment`` objects are treated read-only).
    """

    segments: "tuple[Segment, ...]"  # plan order; same identities as stored
    flags: tuple[WriteFlag, ...]
    total_planned: int


# --------------------------------------------------------------------------- #
# Writer error hierarchy                                                       #
# --------------------------------------------------------------------------- #


class WriterError(Exception):
    """Base class for every explicit error raised by the writer.

    Provides a single catch-all type at the stage boundary while letting each failure
    path raise a specific subclass with an explicit, cause-naming message. Kept
    independent of the skeleton-wide error family (and of
    :class:`~docuharnessx.planning.model.PlanningError`) so the composition core stays
    self-contained and harness-free (design "Error Handling"; matches ``PlanningError``).
    """


class WriterInputError(WriterError):
    """A required writer input is missing or carries an unsupported contract version.

    Raised at the stage boundary when the ``CoveragePlan``, ``Vocabulary``, or
    segment-store slot is unset with a bound run state, or when the consumed
    ``CoveragePlan`` declares a ``schema_version`` this build does not support. The
    message names the offending slot/version so the run halts with an identifiable cause
    and produces no partial output (Req 2.2, 2.3, 2.4). Mirrors
    :class:`~docuharnessx.planning.model.PlanningInputError`.
    """
