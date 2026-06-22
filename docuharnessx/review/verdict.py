"""The deterministic verdict computer (quality-review-gate task 2.4).

This module owns the *Verdict Computer* boundary of the Wave 2 ``quality-review-gate``
review core (design "Verdict Computer"; Req 3.5, 6.1, 6.3, 6.4). :func:`compute_verdict`
turns a parsed :class:`~docuharnessx.review.model.JudgeVerdict` (or the absent value
``None``) plus the per-segment :class:`~docuharnessx.review.model.SegmentCriteria` and a
``judge_source`` marker into the single per-segment
:class:`~docuharnessx.review.model.SegmentReview` entry the aggregator (task 2.5) collects.

It is a **pure function**: no model, no I/O, no global state, and it never mutates its
inputs (the consumed ``JudgeVerdict`` / ``SegmentCriteria`` are read-only). Equal inputs
yield an equal ``SegmentReview`` on every run, and it never raises — every branch (a
passing verdict, a failing verdict, and the absent verdict) returns a well-formed entry, so
no written segment is ever left without one (Req 6.4).

The gate is authoritative, not the judge's prose
-------------------------------------------------
The segment ``verdict`` is derived **only** from the per-criterion threshold rule
(:func:`~docuharnessx.review.criteria.meets_threshold`) and the documented all-of
combination rule (:func:`~docuharnessx.review.criteria.combine_verdict`), applied to the
judge's per-criterion *scores* — independent of any free-form judge prose and of the
judge's own ``overall_passed`` / per-criterion ``passed`` flags (Req 6.1, 3.5). The
per-criterion ``passed`` flag carried on each :class:`~docuharnessx.review.model.CriterionScore`
in the returned entry is **re-derived** from the threshold, so a judge that marks a
sub-threshold score as passed cannot smuggle content past the gate. The gate is computed
over *every* named :data:`~docuharnessx.review.criteria.COBESY_CRITERIA` criterion: a known
criterion the judge omitted is treated as not-passed (a default score of ``0.0``), so an
incomplete verdict fails closed.

The fail-closed default
-----------------------
When the judge verdict is the absent value (``None`` — a model-less run, a fake judge
without a valid verdict, or a failed / timed-out / unparseable judge call), the computer
applies the documented fail-closed default
(:data:`~docuharnessx.review.criteria.DEFAULT_UNAVAILABLE_VERDICT`, a reject), forces
``judge_source="unavailable"`` (overriding the caller's marker — the segment was *not*
judged), records a marker finding noting the segment was not judged, and still emits a
not-passed :class:`~docuharnessx.review.model.CriterionScore` per criterion (Req 6.3). A
quality firewall does not pass unjudged content.

The findings channel
---------------------
:attr:`~docuharnessx.review.model.SegmentReview.findings` carries one actionable line per
failing criterion (the criterion name + the judge's one-line reason where present), so the
report is a usable feedback channel for a later iteration (Req 6.4). A passing segment has
no findings; the absent verdict carries the single unavailable marker.

The module is pure and model-free: it imports only the frozen value objects from
:mod:`docuharnessx.review.model` and the fixed gate definition / rules from
:mod:`docuharnessx.review.criteria`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from docuharnessx.review.criteria import (
    COBESY_CRITERIA,
    DEFAULT_UNAVAILABLE_VERDICT,
    combine_verdict,
    meets_threshold,
)
from docuharnessx.review.model import CriterionScore, SegmentReview

if TYPE_CHECKING:  # frozen seams consumed verbatim — typing-only imports.
    from docuharnessx.review.model import (
        JudgeSource,
        JudgeVerdict,
        SegmentCriteria,
    )

__all__ = ["compute_verdict"]

#: The marker finding recorded on the fail-closed default-reject when the judge verdict is
#: absent (Req 6.3). A single, deterministic line so a maintainer reading the report sees
#: *why* the segment was rejected (it was not judged), distinct from a criterion finding.
_UNAVAILABLE_FINDING = (
    "judge unavailable: segment was not judged; default-rejected (fail-closed)"
)


def compute_verdict(
    judge: "JudgeVerdict | None",
    criteria: "SegmentCriteria",
    *,
    judge_source: "JudgeSource",
) -> SegmentReview:
    """Compute the deterministic per-segment :class:`SegmentReview` entry (Req 3.5, 6.1-6.4).

    Pure and model-free. Derives the segment ``verdict`` from the per-criterion threshold
    rule and the all-of combination rule applied to ``judge``'s per-criterion scores,
    independent of any free-form judge prose (Req 6.1, 3.5). Always returns a well-formed
    entry — no written segment is ever left without one (Req 6.4) — and never raises.

    * **Judged** (``judge`` is a :class:`~docuharnessx.review.model.JudgeVerdict`): builds a
      :class:`~docuharnessx.review.model.CriterionScore` for *every* named
      :data:`~docuharnessx.review.criteria.COBESY_CRITERIA` criterion, taking the judge's
      score where present (a known criterion the judge omitted defaults to ``0.0`` and so
      fails closed) and re-deriving the per-criterion ``passed`` flag from the threshold
      rule (the judge's own ``passed`` flag is not trusted). The verdict is the all-of
      combination of those re-derived flags; ``judge_source`` is the caller's marker
      (``"model"`` or ``"fake"``). The findings carry one line per failing criterion.
    * **Unavailable** (``judge is None``): applies the documented fail-closed default
      (:data:`~docuharnessx.review.criteria.DEFAULT_UNAVAILABLE_VERDICT`, a reject), forces
      ``judge_source="unavailable"`` (overriding the caller's marker — the segment was not
      judged), records the single :data:`_UNAVAILABLE_FINDING` marker, and still emits a
      not-passed score per criterion (Req 6.3).

    Args:
        judge: The parsed judge output for this segment, or ``None`` when no parseable
            verdict was obtained.
        criteria: The deterministic per-segment
            :class:`~docuharnessx.review.model.SegmentCriteria` (supplies the segment id and
            the named criteria to score over).
        judge_source: The provenance marker for a *judged* segment (``"model"`` |
            ``"fake"``); ignored and forced to ``"unavailable"`` when ``judge is None``.

    Returns:
        The per-segment :class:`~docuharnessx.review.model.SegmentReview` entry: the segment
        id, the deterministic ``verdict``, the per-criterion scores (with threshold-derived
        ``passed`` flags), the actionable findings (one per failing criterion, or the
        unavailable marker), and the resolved ``judge_source``.

    Invariants: deterministic (equal inputs yield an equal entry); never consults a model;
    never mutates ``judge`` or ``criteria``; never raises.
    """

    if judge is None:
        return _default_reject(criteria)

    scores = _resolve_scores(judge)
    verdict = combine_verdict(scores)
    findings = _findings(scores)
    return SegmentReview(
        segment_id=criteria.segment_id,
        verdict=verdict,
        scores=scores,
        findings=findings,
        judge_source=judge_source,
    )


def _resolve_scores(judge: "JudgeVerdict") -> tuple[CriterionScore, ...]:
    """Build the authoritative per-criterion scores over the full COBESY gate.

    Pure and read-only. For *every* named :data:`COBESY_CRITERIA` criterion (in the fixed
    gate order, so the entry is deterministic regardless of the judge's key order), takes
    the judge's :class:`~docuharnessx.review.model.CriterionScore` where present and
    defaults a known-but-omitted criterion to a not-passed ``0.0`` score so an incomplete
    verdict fails closed (Req 6.1). The per-criterion ``passed`` flag is **re-derived** from
    :func:`~docuharnessx.review.criteria.meets_threshold` rather than trusted from the
    judge, keeping the gate independent of free-form judge prose (Req 6.1, 3.5).
    """

    judged = {s.name: s for s in judge.scores}
    resolved: list[CriterionScore] = []
    for name in COBESY_CRITERIA:
        source = judged.get(name)
        score = source.score if source is not None else 0.0
        reason = source.reason if source is not None else ""
        resolved.append(
            CriterionScore(
                name=name,
                score=score,
                passed=meets_threshold(score),
                reason=reason,
            )
        )
    return tuple(resolved)


def _findings(scores: tuple[CriterionScore, ...]) -> tuple[str, ...]:
    """Derive one actionable finding per failing criterion (Req 6.4).

    Pure. For each not-passed :class:`~docuharnessx.review.model.CriterionScore` (in gate
    order), emits a single line naming the failing criterion and carrying the judge's
    one-line reason where present, so the report is a usable feedback channel. A segment
    whose every criterion passes yields an empty tuple (no findings).
    """

    findings: list[str] = []
    for score in scores:
        if not score.passed:
            suffix = f": {score.reason}" if score.reason else ""
            findings.append(f"{score.name} did not meet the quality threshold{suffix}")
    return tuple(findings)


def _default_reject(criteria: "SegmentCriteria") -> SegmentReview:
    """Build the fail-closed default-reject entry for an unavailable judge (Req 6.3).

    Pure. Applies :data:`DEFAULT_UNAVAILABLE_VERDICT` (a reject), marks
    ``judge_source="unavailable"``, records the single :data:`_UNAVAILABLE_FINDING` marker,
    and emits a not-passed ``0.0`` :class:`~docuharnessx.review.model.CriterionScore` per
    named criterion so the entry is still well-formed (a score per criterion) while making
    plain the segment was not judged.
    """

    scores = tuple(
        CriterionScore(name=name, score=0.0, passed=False, reason="")
        for name in COBESY_CRITERIA
    )
    return SegmentReview(
        segment_id=criteria.segment_id,
        verdict=DEFAULT_UNAVAILABLE_VERDICT,
        scores=scores,
        findings=(_UNAVAILABLE_FINDING,),
        judge_source="unavailable",
    )
