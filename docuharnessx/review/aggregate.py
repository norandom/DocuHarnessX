"""The deterministic aggregator and report assembler (quality-review-gate task 2.5).

This module owns the *Aggregator* boundary of the Wave 2 ``quality-review-gate`` review
core (design "Aggregator"; Req 6.2, 6.5, 7.1, 7.4, 7.5, 8.1, 8.2, 8.3). It is the final
deterministic step before the harness adapter publishes the seam: it folds the ordered
per-segment :class:`~docuharnessx.review.model.SegmentReview` entries produced by the
verdict computer (task 2.4) — one per written segment, in the written set's order — into
the frozen :class:`~docuharnessx.review.model.ReviewReport` the Wave 3
``mkdocs-site-assembler`` consumes verbatim.

It exposes two pure functions:

* :func:`aggregate` — folds the entries into the
  :class:`~docuharnessx.review.model.ReviewAggregate` quality summary: the
  ``judged``/``accepted``/``rejected``/``unavailable`` counts (Req 8.1) and the
  per-criterion pass/fail :class:`~docuharnessx.review.model.CriterionTally` across all
  entries, in the fixed :data:`~docuharnessx.review.criteria.COBESY_CRITERIA` gate order
  (Req 8.2).
* :func:`assemble_report` — builds the accepted :class:`~docuharnessx.ontology.Segment`
  set (exactly the ``pass`` entries, in written order, carrying the *same* stored
  ``Segment`` identities — Req 6.2, 7.4, 7.5) and assembles the frozen
  :class:`~docuharnessx.review.model.ReviewReport` with the single
  :data:`~docuharnessx.review.model.REVIEW_REPORT_SCHEMA_VERSION` (Req 7.1, 7.6).

Both functions are **pure**: no model, no I/O, no global state, and they never mutate
their inputs (the consumed entries and the ``Segment`` objects are read-only). Equal
inputs yield an equal report on every run (Req 8.3, 10.3). An empty entries input yields a
well-formed empty report — zero counts, a full zero-count tally, and an empty accepted set
(Req 6.5).

Authority and invariants
-------------------------
* **Counts** (Req 8.1): ``judged`` is the number of entries; ``accepted`` /
  ``rejected`` partition them by the per-segment ``verdict`` (``"pass"`` vs ``"fail"``) so
  ``accepted + rejected == judged``; ``unavailable`` counts the entries whose
  ``judge_source == "unavailable"`` (the fail-closed default-reject from the verdict
  computer), a strict subset of ``rejected``.
* **Tally** (Req 8.2): for each named criterion (in gate order), ``passed`` / ``failed``
  count the per-entry :class:`~docuharnessx.review.model.CriterionScore` ``passed`` flag,
  which the verdict computer re-derives from the threshold rule (not free-form prose). An
  entry's missing score for a known criterion (or an unavailable entry's not-passed
  scores) counts as a fail, so ``passed + failed == judged`` for every criterion.
* **Accepted set** (Req 6.2, 7.4, 7.5): exactly the ``verdict == "pass"`` entries, in the
  entries' (written) order, each resolved through the ``segment_id -> Segment`` lookup so
  the report carries the *same identities* present in the ``WrittenSegments`` /
  ``SegmentStore``. A pass entry whose id is absent from the lookup is a contract
  violation surfaced as a ``KeyError`` at the stage boundary rather than a silently
  dropped accepted segment.

The module is pure and model-free: it imports only the frozen value objects from
:mod:`docuharnessx.review.model` and the fixed gate definition from
:mod:`docuharnessx.review.criteria`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from docuharnessx.review.criteria import COBESY_CRITERIA
from docuharnessx.review.model import (
    REVIEW_REPORT_SCHEMA_VERSION,
    CriterionTally,
    ReviewAggregate,
    ReviewReport,
)

if TYPE_CHECKING:  # frozen seams consumed verbatim — typing-only imports.
    from docuharnessx.ontology import Segment
    from docuharnessx.review.model import SegmentReview

__all__ = ["aggregate", "assemble_report"]


def aggregate(entries: tuple["SegmentReview", ...]) -> ReviewAggregate:
    """Fold the per-segment entries into the aggregate quality summary (Req 8.1, 8.2).

    Pure and model-free. Computes the ``judged``/``accepted``/``rejected``/``unavailable``
    counts and the per-criterion pass/fail tally across every entry, in the fixed
    :data:`~docuharnessx.review.criteria.COBESY_CRITERIA` gate order so the summary is
    deterministic regardless of any per-entry score key order.

    * ``judged`` is ``len(entries)``; ``accepted`` / ``rejected`` partition them by the
      per-segment ``verdict`` (so ``accepted + rejected == judged``); ``unavailable``
      counts the ``judge_source == "unavailable"`` entries (a subset of ``rejected``).
    * The tally counts each entry's per-criterion :attr:`CriterionScore.passed` flag (the
      threshold-derived flag from the verdict computer). A known criterion an entry did not
      score counts as a fail, so ``passed + failed == judged`` for every criterion.

    An empty ``entries`` tuple yields zero counts and a full zero-count tally (Req 6.5).
    Deterministic (equal inputs yield an equal aggregate, Req 8.3); never mutates
    ``entries``; never raises.
    """

    judged = len(entries)
    accepted = sum(1 for e in entries if e.verdict == "pass")
    rejected = judged - accepted
    unavailable = sum(1 for e in entries if e.judge_source == "unavailable")

    tally = tuple(
        _criterion_tally(name, entries) for name in COBESY_CRITERIA
    )

    return ReviewAggregate(
        judged=judged,
        accepted=accepted,
        rejected=rejected,
        unavailable=unavailable,
        criterion_tally=tally,
    )


def _criterion_tally(
    name: str, entries: tuple["SegmentReview", ...]
) -> CriterionTally:
    """Build one criterion's pass/fail tally across every entry (Req 8.2).

    Pure. ``passed`` counts the entries whose :class:`CriterionScore` for ``name`` is
    ``passed``; ``failed`` is every other entry (a missing-for-``name`` score or a
    not-passed one), so ``passed + failed == len(entries)`` for the criterion.
    """

    passed = 0
    for entry in entries:
        score = next((s for s in entry.scores if s.name == name), None)
        if score is not None and score.passed:
            passed += 1
    return CriterionTally(name=name, passed=passed, failed=len(entries) - passed)


def assemble_report(
    entries: tuple["SegmentReview", ...],
    by_id: dict[str, "Segment"],
) -> ReviewReport:
    """Assemble the frozen :class:`ReviewReport` seam from the entries (Req 6.2, 7.1-7.6).

    Pure and model-free. Keeps the ``entries`` in their incoming (written) order, builds
    the accepted set as exactly the ``verdict == "pass"`` entries — in that same order,
    resolved through ``by_id`` so each accepted segment is the *same*
    :class:`~docuharnessx.ontology.Segment` identity stored in the
    ``WrittenSegments`` / ``SegmentStore`` (Req 7.4, 7.5) — and carries the aggregate from
    :func:`aggregate` and the single
    :data:`~docuharnessx.review.model.REVIEW_REPORT_SCHEMA_VERSION` (Req 7.1, 7.6).

    An empty ``entries`` tuple yields a well-formed empty report (empty entries, empty
    accepted, zero-count aggregate; Req 6.5). Deterministic (equal inputs yield an equal
    report, Req 8.3, 10.3); never mutates ``entries`` or ``by_id``.

    Args:
        entries: The per-segment entries, one per written segment, in written order.
        by_id: A ``segment_id -> Segment`` lookup over the written segment identities
            (the same objects in the ``SegmentStore`` / written set).

    Returns:
        The frozen :class:`~docuharnessx.review.model.ReviewReport`.

    Raises:
        KeyError: if a ``pass`` entry's ``segment_id`` is absent from ``by_id`` — a
            contract violation at the stage boundary (an accepted segment must carry its
            stored identity) surfaced rather than silently dropped.
    """

    accepted = tuple(
        by_id[entry.segment_id] for entry in entries if entry.verdict == "pass"
    )
    return ReviewReport(
        schema_version=REVIEW_REPORT_SCHEMA_VERSION,
        entries=tuple(entries),
        accepted=accepted,
        aggregate=aggregate(entries),
    )
