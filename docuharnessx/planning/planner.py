"""Materialize a :class:`Classification` into the frozen, ordered ``CoveragePlan``.

This is the *planner* component of the deterministic planning core (task 3.2,
boundary: planner). It is the final transform of the pure core: it consumes the
intermediate Classify->Plan handoff value object
(:class:`~docuharnessx.planning.model.Classification`) and produces the frozen,
versioned :class:`~docuharnessx.planning.model.CoveragePlan` the Wave 2
``cobesy-writer`` consumes verbatim (design "planner — Classification to CoveragePlan";
Req 5.1-5.5, 6.1, 8.1).

What it does
------------
For each activated :class:`~docuharnessx.planning.model.CandidateCell` in the
classification, :func:`plan_coverage` builds exactly one
:class:`~docuharnessx.planning.model.PlannedSegment` carrying:

* the cell's ``roles`` (role ids, kept in the order the classifier emitted them — the
  loaded vocabulary's declared role order) and ``intent`` (Req 6.2);
* the cell's ``subjects`` sorted by :meth:`~docuharnessx.ontology.Subject.canonical`
  and ``evidence`` sorted by ``(kind, detail)`` (Req 5.4) — the model documents these
  orders, so the planner is the single place that establishes them;
* a deterministic, plan-local ``segment_key`` of the form
  ``"<roles>__<intent>__<subjects-digest>"`` (the digest is a stable hash over the
  sorted canonical subject strings, so distinct cells get distinct keys, the same cell
  always gets the same key, and the key never depends on iteration order);
* the integer ``priority`` from :func:`~docuharnessx.planning.scorer.score_cell` (the
  documented evidence-strength + vocabulary-position scoring, Req 5.1).

The segments are then ordered by :func:`~docuharnessx.planning.scorer.order_key`
(``priority`` desc, then the loaded vocabulary's role order, then ``intent_order()``,
then the stable ``segment_key``) — a total, reproducible order (Req 5.2, 5.3). The
plan's provenance — ``schema_version`` (:data:`COVERAGE_PLAN_SCHEMA_VERSION`),
``repo_path``, and ``vocabulary_fingerprint`` — is propagated verbatim from the
classification (the classifier owns fingerprinting; the planner never recomputes it).

Guarantees
----------
* **Never raises for "no evidence"**: a classification with no activated cell yields a
  well-formed :class:`CoveragePlan` with an empty ``segments`` tuple (Req 5.5).
* **Never fabricates**: exactly one segment per activated cell, nothing invented
  (Req 8.1).
* **Deterministic**: equal inputs always yield equal plans — every collection is built
  pre-ordered (Req 5.3, 8.1). ``relevance_applied`` is ``False``; the optional gated
  relevance hook (``relevance.py``) is the only thing that may flip it.

This module is pure, model-free, and side-effect-free. It imports only this spec's model
records, the scorer, and the ontology :class:`~docuharnessx.ontology.Vocabulary`
(read-only) — never ``stages/`` or HarnessX.
"""

from __future__ import annotations

import hashlib

from docuharnessx.ontology import Subject, Vocabulary
from docuharnessx.planning.model import (
    COVERAGE_PLAN_SCHEMA_VERSION,
    CandidateCell,
    Classification,
    CoveragePlan,
    EvidenceRef,
    PlannedSegment,
)
from docuharnessx.planning.scorer import order_key, score_cell

__all__ = ["plan_coverage"]

#: Length (hex chars) of the subjects digest embedded in a ``segment_key``. 12 hex
#: chars (48 bits) makes an accidental collision between two distinct subject sets
#: vanishingly unlikely while keeping the key compact and human-scannable.
_SUBJECT_DIGEST_LEN: int = 12


def _sorted_subjects(subjects: tuple[Subject, ...]) -> tuple[Subject, ...]:
    """Subjects sorted by their ``canonical()`` ``"prefix:local"`` string (Req 5.4)."""
    return tuple(sorted(subjects, key=lambda s: s.canonical()))


def _sorted_evidence(evidence: tuple[EvidenceRef, ...]) -> tuple[EvidenceRef, ...]:
    """Evidence refs sorted by ``(kind, detail)`` — a total, stable order (Req 5.4)."""
    return tuple(sorted(evidence, key=lambda e: (e.kind, e.detail)))


def _subjects_digest(sorted_subjects: tuple[Subject, ...]) -> str:
    """A short, stable hash over the sorted canonical subject strings.

    Embedding a digest (rather than the raw subjects) keeps the ``segment_key`` compact
    and bounded regardless of subject count, while still distinguishing cells that share
    a role+intent but cover different subjects. Computed over a newline-joined,
    already-sorted list of ``canonical()`` strings, so it is independent of the input
    order and identical across runs. An empty subject set yields the digest of the empty
    string — a stable, well-defined value.
    """
    payload = "\n".join(s.canonical() for s in sorted_subjects)
    return hashlib.blake2b(
        payload.encode("utf-8"), digest_size=_SUBJECT_DIGEST_LEN // 2
    ).hexdigest()


def _segment_key(
    roles: tuple[str, ...], intent: str, sorted_subjects: tuple[Subject, ...]
) -> str:
    """Build the deterministic plan-local key ``"<roles>__<intent>__<subjects-digest>"``.

    ``roles`` are joined with ``","`` in their emitted (vocabulary-declared) order; the
    digest distinguishes cells covering different subjects. Distinct cells therefore get
    distinct keys, and the same cell always gets the same key across runs — making the
    key usable as the final stable tie-breaker in :func:`~scorer.order_key`.
    """
    roles_part = ",".join(roles)
    return f"{roles_part}__{intent}__{_subjects_digest(sorted_subjects)}"


def _build_segment(cell: CandidateCell, vocab: Vocabulary) -> PlannedSegment:
    """Materialize one :class:`CandidateCell` into a :class:`PlannedSegment`.

    Sorts the cell's subjects (by canonical) and evidence (by kind/detail), derives the
    deterministic ``segment_key``, and scores the cell via
    :func:`~docuharnessx.planning.scorer.score_cell`. ``roles``/``intent`` are carried
    verbatim (the classifier already emits roles in the vocabulary's declared order).
    """
    subjects = _sorted_subjects(cell.subjects)
    evidence = _sorted_evidence(cell.evidence)
    return PlannedSegment(
        segment_key=_segment_key(cell.roles, cell.intent, subjects),
        roles=cell.roles,
        intent=cell.intent,
        subjects=subjects,
        priority=score_cell(cell, vocab),
        evidence=evidence,
    )


def plan_coverage(
    classification: Classification, vocab: Vocabulary
) -> CoveragePlan:
    """Score, order, and materialize a ``Classification`` into a ``CoveragePlan``.

    Builds one :class:`~docuharnessx.planning.model.PlannedSegment` per activated
    :class:`~docuharnessx.planning.model.CandidateCell` (deterministic ``segment_key``,
    scored ``priority``, sorted ``subjects`` and ``evidence``), orders the segments by
    :func:`~docuharnessx.planning.scorer.order_key` (priority desc, then the loaded
    vocabulary's role order, then ``intent_order()``, then the stable ``segment_key``),
    and sets ``schema_version`` (:data:`COVERAGE_PLAN_SCHEMA_VERSION`), ``repo_path``,
    and ``vocabulary_fingerprint`` from the classification (Req 5.1-5.4, 6.1-6.3).

    When ``classification.cells`` is empty, returns a well-formed
    :class:`~docuharnessx.planning.model.CoveragePlan` with an empty ``segments`` tuple
    — never raising and never fabricating a segment (Req 5.5, 8.1). The deterministic
    core leaves ``relevance_applied`` ``False``; the optional gated relevance hook is the
    only path that may set it.
    """
    segments = tuple(
        _build_segment(cell, vocab) for cell in classification.cells
    )
    ordered = tuple(sorted(segments, key=lambda seg: order_key(seg, vocab)))
    return CoveragePlan(
        schema_version=COVERAGE_PLAN_SCHEMA_VERSION,
        repo_path=classification.repo_path,
        vocabulary_fingerprint=classification.vocabulary_fingerprint,
        segments=ordered,
        relevance_applied=False,
    )
