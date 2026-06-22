"""The deterministic verdict parser (quality-review-gate task 2.3).

This module owns the *Verdict Parser* boundary of the Wave 2 ``quality-review-gate``
review core: :func:`parse_verdict` decodes the judge's JSON reply into a bounded
:class:`~docuharnessx.review.model.JudgeVerdict`, or returns ``None`` when the reply is
malformed, empty, wrong-shaped, or carries no known criterion (design "Verdict Parser";
Req 4.3, 6.1). The gated judge step (task 3.1) delegates parsing here; the verdict
computer (task 2.4) turns a ``JudgeVerdict | None`` into the deterministic per-segment
:class:`~docuharnessx.review.model.SegmentReview`, applying the fail-closed default-reject
on ``None``.

It is a **pure function**: no model, no I/O, no global state, never mutates its input, and
**never raises** — any decode/shape failure is absorbed into ``None`` so the caller's
fail-closed firewall (a deterministic default-reject) governs the unjudged case (Req 6.1,
6.3). Equal content + equal criteria yield an equal verdict on every run.

Parse discipline (reused verbatim from :class:`harnessx.processors.evaluation`'s
``LLMJudgeEvaluator``, lifted to the per-criterion level; design "Verdict Parser"):

* **Fenced-code stripping** — a leading ```` ```json ```` / ```` ``` ```` opener and a
  trailing ```` ``` ```` closer are removed before decoding (the same regex the harness
  judge uses), so a model that wraps its JSON in a markdown fence still parses.
* **JSON decode** — :func:`json.loads`; a non-object top level (list, scalar, ``null``) is
  rejected (``None``).
* **Per-criterion bounds** — each criterion ``score`` is coerced to ``float`` and clamped
  to ``[0,1]``; a non-numeric score drops that one criterion (it is not fabricated).
* **``passed`` fallback** — a missing per-criterion ``passed`` flag defaults to the
  per-criterion threshold rule (:func:`~docuharnessx.review.criteria.meets_threshold`); an
  explicit flag is respected. The overall ``passed`` flag likewise defaults to the
  threshold rule applied to the **minimum** per-criterion score when the judge omits it
  (the gate recomputes the binding verdict from the per-criterion ``passed`` flags in
  :mod:`docuharnessx.review.verdict`, so this overall flag is advisory).
* **Known-criteria only** — only names present in the segment's configured
  :attr:`~docuharnessx.review.model.SegmentCriteria.criteria` (the COBESY gate) are kept;
  unknown names are dropped. A reply that scores **no** known criterion yields ``None``
  (the segment is then treated as unjudged) rather than an empty, misleading verdict.
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any

from docuharnessx.review.criteria import meets_threshold
from docuharnessx.review.model import CriterionScore, JudgeVerdict

if TYPE_CHECKING:  # frozen seam consumed verbatim — typing-only import.
    from docuharnessx.review.model import SegmentCriteria

__all__ = ["parse_verdict"]


#: The fenced-code stripper, identical in shape to the one
#: :class:`harnessx.processors.evaluation`'s ``LLMJudgeEvaluator`` applies: remove a
#: leading ```` ```json ```` / ```` ``` ```` opener and a trailing ```` ``` ```` closer
#: (line-anchored) so a fence-wrapped JSON object still decodes (Req 4.3).
_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", flags=re.MULTILINE)


def parse_verdict(
    content: str, criteria: "SegmentCriteria"
) -> JudgeVerdict | None:
    """Parse the judge's JSON ``content`` into a bounded :class:`JudgeVerdict`, or ``None``.

    Pure, model-free, and deterministic (Req 4.3, 6.1). Strips a markdown code fence,
    decodes the JSON, clamps each known criterion's score to ``[0,1]``, coerces each
    per-criterion ``passed`` flag (defaulting a missing flag to the threshold rule), keeps
    only criterion names configured on ``criteria`` (the COBESY gate), and bounds the
    overall flag/reason. Any malformed, empty, non-object, or no-known-criterion reply
    yields ``None`` so the caller applies the fail-closed default-reject — this function
    **never raises**.

    Args:
        content: The judge model's raw reply text (may be fence-wrapped).
        criteria: The segment's :class:`~docuharnessx.review.model.SegmentCriteria`; its
            :attr:`~docuharnessx.review.model.SegmentCriteria.criteria` tuple is the set of
            known criterion names and fixes the order of the parsed scores.

    Returns:
        A :class:`~docuharnessx.review.model.JudgeVerdict` carrying one
        :class:`~docuharnessx.review.model.CriterionScore` per scored known criterion (in
        the configured criteria order), the bounded overall ``passed`` flag, and the
        bounded overall ``reason`` — or ``None`` on malformed / empty / wrong-shape /
        no-known-criterion content.

    Invariants: never consults a model; never mutates ``criteria``; never raises; equal
    inputs yield an equal verdict.
    """
    data = _decode_object(content)
    if data is None:
        return None

    raw_criteria = data.get("criteria")
    if not isinstance(raw_criteria, dict):
        return None

    known = criteria.criteria  # the configured COBESY gate names, in order
    scores: list[CriterionScore] = []
    for name in known:  # iterate the configured order so output order is deterministic
        entry = raw_criteria.get(name)
        if not isinstance(entry, dict):
            continue  # missing or wrong-shaped: not scored (drop, do not fabricate)
        score = _coerce_score(entry.get("score"))
        if score is None:
            continue  # non-numeric score: drop this criterion rather than invent one
        passed = _coerce_passed(entry.get("passed"), score)
        reason = _coerce_str(entry.get("reason"))
        scores.append(
            CriterionScore(name=name, score=score, passed=passed, reason=reason)
        )

    if not scores:
        # No known criterion was scored: a misleading empty verdict is worse than an
        # explicit "unjudged" — return None so the caller applies the default-reject.
        return None

    overall_passed = _coerce_overall_passed(data.get("passed"), scores)
    overall_reason = _coerce_str(data.get("reason"))

    return JudgeVerdict(
        scores=tuple(scores),
        overall_passed=overall_passed,
        reason=overall_reason,
    )


def _decode_object(content: Any) -> dict | None:
    """Strip a code fence and decode ``content`` into a JSON object, or ``None``.

    Tolerates a non-string ``content`` (returns ``None``), an empty/whitespace reply, a
    decode error, and a decoded non-object (list/scalar/``null``) — never raises (Req 6.1).
    """
    if not isinstance(content, str):
        return None
    stripped = _FENCE_RE.sub("", content).strip()
    if not stripped:
        return None
    try:
        data = json.loads(stripped)
    except (json.JSONDecodeError, ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def _coerce_score(raw: Any) -> float | None:
    """Coerce a raw score to a ``float`` clamped to ``[0,1]``, or ``None`` if not numeric.

    Accepts ``int``/``float`` and a numeric string (mirroring the harness judge's
    ``float(...)`` coercion); a non-numeric value yields ``None`` so the caller drops that
    one criterion rather than fabricating a score. Never raises.
    """
    if isinstance(raw, bool):  # bool is an int subclass; reject it as a score
        return None
    try:
        value = float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if value != value:  # NaN guard (NaN != NaN)
        return None
    return max(0.0, min(1.0, value))


def _coerce_passed(raw: Any, score: float) -> bool:
    """Coerce a per-criterion ``passed`` flag, defaulting a missing flag to the threshold.

    An explicit ``passed`` value is respected (``bool(raw)``); a missing flag (``None``)
    falls back to the per-criterion threshold rule
    (:func:`~docuharnessx.review.criteria.meets_threshold`), reusing the harness judge's
    ``bool(data.get("passed", score >= threshold))`` discipline at the per-criterion level
    (Req 4.3). Never raises.
    """
    if raw is None:
        return meets_threshold(score)
    return bool(raw)


def _coerce_overall_passed(raw: Any, scores: list[CriterionScore]) -> bool:
    """Coerce the overall ``passed`` flag, defaulting a missing flag to the threshold rule.

    An explicit overall flag is respected; a missing flag defaults to the threshold rule
    applied to the **minimum** per-criterion score (so the advisory overall flag is
    consistent with the all-of combination rule the gate enforces). The binding segment
    verdict is recomputed deterministically from the per-criterion ``passed`` flags in
    :mod:`docuharnessx.review.verdict`, so this value is advisory only. Never raises.
    """
    if raw is None:
        worst = min((s.score for s in scores), default=0.0)
        return meets_threshold(worst)
    return bool(raw)


def _coerce_str(raw: Any) -> str:
    """Coerce a raw reason to a bounded ``str`` (``""`` when absent). Never raises."""
    if raw is None:
        return ""
    return str(raw)
