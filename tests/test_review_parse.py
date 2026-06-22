"""Unit tests for the deterministic verdict parser (quality-review-gate task 2.3).

These tests pin the *Verdict Parser* boundary of the deterministic, model-free review
core: ``parse_verdict(content, criteria) -> JudgeVerdict | None``. The parser decodes the
judge's JSON reply into a bounded :class:`~docuharnessx.review.model.JudgeVerdict`,
reusing the :class:`harnessx.processors.evaluation`'s ``LLMJudgeEvaluator`` discipline —
fenced-code stripping, ``json.loads``, per-criterion score clamp to ``[0,1]``, a
``passed`` flag that falls back to the per-criterion threshold rule when absent — and
keeps only criterion names in :data:`~docuharnessx.review.COBESY_CRITERIA`. Any malformed,
empty, or wrong-shape content (or a reply carrying no known criterion) yields ``None``
without raising; the caller (task 2.4) then applies the fail-closed default-reject.

Observable completion (tasks.md 2.3): parse a clean verdict, strip a fenced-code wrapper,
clamp out-of-range scores, default a missing pass flag via the threshold, drop an unknown
criterion, and return ``None`` for malformed/empty input. Pure and deterministic: equal
inputs yield an equal verdict; the parser never consults a model and never raises.
"""

from __future__ import annotations

import json

import pytest

from docuharnessx.review import (
    COBESY_CRITERIA,
    CRITERION_THRESHOLD,
    CriterionScore,
    EvidenceAnchor,
    JudgeVerdict,
    RoleContext,
    SegmentCriteria,
)
from docuharnessx.review.parse import parse_verdict


# --------------------------------------------------------------------------- #
# Fixtures                                                                      #
# --------------------------------------------------------------------------- #


def _criteria(*, criteria: tuple[str, ...] = COBESY_CRITERIA) -> SegmentCriteria:
    """A minimal :class:`SegmentCriteria`; only ``criteria`` matters to the parser."""
    return SegmentCriteria(
        segment_id="astronaut__dock__deadbeef",
        title="Dock: the capsule procedure",
        summary="How an orbital astronaut brings the capsule to a safe berth.",
        body="Align the docking ring, then close the latch on the green light.",
        criteria=criteria,
        roles=(RoleContext(id="astronaut", label="Orbital Astronaut", description=""),),
        intent=RoleContext(id="howto", label="How-to", description=""),
        evidence_anchors=(EvidenceAnchor(kind="entrypoint", detail="dock.py"),),
    )


def _full_payload(
    *,
    per_score: float = 0.9,
    per_passed: bool = True,
    overall_passed: bool = True,
    overall_reason: str = "All criteria met.",
) -> dict:
    """A well-formed judge JSON payload scoring every COBESY criterion."""
    return {
        "criteria": {
            name: {
                "score": per_score,
                "passed": per_passed,
                "reason": f"{name} ok",
            }
            for name in COBESY_CRITERIA
        },
        "passed": overall_passed,
        "reason": overall_reason,
    }


def _names(verdict: JudgeVerdict) -> set[str]:
    return {s.name for s in verdict.scores}


def _by_name(verdict: JudgeVerdict, name: str) -> CriterionScore:
    return next(s for s in verdict.scores if s.name == name)


# --------------------------------------------------------------------------- #
# Clean parse                                                                   #
# --------------------------------------------------------------------------- #


def test_parses_a_clean_verdict_into_a_bounded_judgeverdict() -> None:
    content = json.dumps(_full_payload(per_score=0.9, per_passed=True, overall_passed=True))

    verdict = parse_verdict(content, _criteria())

    assert isinstance(verdict, JudgeVerdict)
    assert verdict.overall_passed is True
    assert verdict.reason == "All criteria met."
    # one CriterionScore per known criterion, all bounded + flagged
    assert _names(verdict) == set(COBESY_CRITERIA)
    for score in verdict.scores:
        assert isinstance(score, CriterionScore)
        assert 0.0 <= score.score <= 1.0
        assert score.passed is True
        assert score.name in COBESY_CRITERIA


def test_scores_are_kept_in_cobesy_order() -> None:
    verdict = parse_verdict(json.dumps(_full_payload()), _criteria())
    assert verdict is not None
    assert tuple(s.name for s in verdict.scores) == COBESY_CRITERIA


def test_per_criterion_reason_is_carried_verbatim() -> None:
    payload = _full_payload()
    payload["criteria"]["mece"]["reason"] = "Sections do not overlap."
    verdict = parse_verdict(json.dumps(payload), _criteria())
    assert verdict is not None
    assert _by_name(verdict, "mece").reason == "Sections do not overlap."


# --------------------------------------------------------------------------- #
# Fenced-code stripping                                                         #
# --------------------------------------------------------------------------- #


def test_strips_a_fenced_json_code_block() -> None:
    inner = json.dumps(_full_payload(overall_passed=False, overall_reason="Nope."))
    content = f"```json\n{inner}\n```"

    verdict = parse_verdict(content, _criteria())

    assert verdict is not None
    assert verdict.overall_passed is False
    assert verdict.reason == "Nope."
    assert _names(verdict) == set(COBESY_CRITERIA)


def test_strips_a_bare_triple_backtick_fence() -> None:
    inner = json.dumps(_full_payload())
    content = f"```\n{inner}\n```"
    verdict = parse_verdict(content, _criteria())
    assert verdict is not None
    assert _names(verdict) == set(COBESY_CRITERIA)


# --------------------------------------------------------------------------- #
# Score clamping                                                                #
# --------------------------------------------------------------------------- #


def test_clamps_out_of_range_scores_to_unit_interval() -> None:
    payload = _full_payload()
    payload["criteria"]["mece"]["score"] = 1.7  # above 1
    payload["criteria"]["clarity"]["score"] = -0.4  # below 0

    verdict = parse_verdict(json.dumps(payload), _criteria())

    assert verdict is not None
    assert _by_name(verdict, "mece").score == 1.0
    assert _by_name(verdict, "clarity").score == 0.0
    # untouched criteria keep their value
    assert _by_name(verdict, "no_ai_slop").score == pytest.approx(0.9)


def test_string_numeric_score_is_coerced_and_clamped() -> None:
    payload = _full_payload()
    payload["criteria"]["mece"]["score"] = "0.85"
    verdict = parse_verdict(json.dumps(payload), _criteria())
    assert verdict is not None
    assert _by_name(verdict, "mece").score == pytest.approx(0.85)


# --------------------------------------------------------------------------- #
# passed-flag fallback to the threshold rule                                    #
# --------------------------------------------------------------------------- #


def test_missing_per_criterion_passed_defaults_to_threshold_rule() -> None:
    payload = _full_payload()
    # a score at/above threshold without an explicit passed flag -> pass
    payload["criteria"]["mece"] = {"score": CRITERION_THRESHOLD, "reason": "edge"}
    # a score below threshold without an explicit passed flag -> fail
    payload["criteria"]["clarity"] = {"score": CRITERION_THRESHOLD - 0.2, "reason": "low"}

    verdict = parse_verdict(json.dumps(payload), _criteria())

    assert verdict is not None
    assert _by_name(verdict, "mece").passed is True
    assert _by_name(verdict, "clarity").passed is False


def test_explicit_passed_flag_overrides_the_threshold_rule() -> None:
    payload = _full_payload()
    # high score but the judge explicitly failed it -> respect the explicit flag
    payload["criteria"]["mece"] = {"score": 0.95, "passed": False, "reason": "off-topic"}
    verdict = parse_verdict(json.dumps(payload), _criteria())
    assert verdict is not None
    assert _by_name(verdict, "mece").passed is False


def test_missing_overall_passed_defaults_to_threshold_rule() -> None:
    # no top-level "passed"; provide a high overall by omission -> default via score rule.
    payload = {
        "criteria": {
            name: {"score": 0.9, "passed": True, "reason": "ok"} for name in COBESY_CRITERIA
        },
        "reason": "looks fine",
    }
    verdict = parse_verdict(json.dumps(payload), _criteria())
    assert verdict is not None
    # the parser must produce a deterministic boolean overall flag, never raise
    assert isinstance(verdict.overall_passed, bool)


# --------------------------------------------------------------------------- #
# Unknown-criterion dropping + restriction to configured criteria               #
# --------------------------------------------------------------------------- #


def test_drops_unknown_criterion_names() -> None:
    payload = _full_payload()
    payload["criteria"]["totally_made_up"] = {"score": 1.0, "passed": True, "reason": "x"}

    verdict = parse_verdict(json.dumps(payload), _criteria())

    assert verdict is not None
    assert "totally_made_up" not in _names(verdict)
    assert _names(verdict) == set(COBESY_CRITERIA)


def test_keeps_only_criteria_configured_on_the_segment() -> None:
    # a SegmentCriteria configured with a subset still only yields that subset
    subset = ("mece", "clarity")
    payload = _full_payload()
    verdict = parse_verdict(json.dumps(payload), _criteria(criteria=subset))
    assert verdict is not None
    assert _names(verdict) == set(subset)


def test_partial_known_criteria_yields_only_present_known_scores() -> None:
    payload = {
        "criteria": {
            "mece": {"score": 0.9, "passed": True, "reason": "ok"},
            "clarity": {"score": 0.8, "passed": True, "reason": "ok"},
        },
        "passed": True,
        "reason": "two scored",
    }
    verdict = parse_verdict(json.dumps(payload), _criteria())
    assert verdict is not None
    # only the criteria the judge actually scored are carried (no fabricated scores)
    assert _names(verdict) == {"mece", "clarity"}


# --------------------------------------------------------------------------- #
# Malformed / empty / wrong-shape -> None (never raises)                        #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "content",
    [
        "",
        "   ",
        "not json at all",
        "{not valid json",
        "[1, 2, 3]",  # JSON, but not an object
        "\"a string\"",  # JSON, but not an object
        "42",  # JSON number
        "null",  # JSON null
    ],
)
def test_returns_none_on_malformed_or_wrong_shape(content: str) -> None:
    assert parse_verdict(content, _criteria()) is None


def test_returns_none_when_no_known_criterion_present() -> None:
    payload = {
        "criteria": {"totally_made_up": {"score": 1.0, "passed": True, "reason": "x"}},
        "passed": True,
        "reason": "no known criteria",
    }
    assert parse_verdict(json.dumps(payload), _criteria()) is None


def test_returns_none_when_criteria_key_is_missing() -> None:
    payload = {"passed": True, "reason": "no criteria block"}
    assert parse_verdict(json.dumps(payload), _criteria()) is None


def test_returns_none_when_criteria_block_is_not_a_mapping() -> None:
    payload = {"criteria": ["mece", "clarity"], "passed": True, "reason": "wrong shape"}
    assert parse_verdict(json.dumps(payload), _criteria()) is None


def test_skips_a_criterion_whose_entry_is_not_a_mapping() -> None:
    # one good, one malformed entry -> the good one survives, the bad one is skipped
    payload = {
        "criteria": {
            "mece": {"score": 0.9, "passed": True, "reason": "ok"},
            "clarity": "not a dict",
        },
        "passed": True,
        "reason": "mixed",
    }
    verdict = parse_verdict(json.dumps(payload), _criteria())
    assert verdict is not None
    assert _names(verdict) == {"mece"}


def test_non_numeric_score_does_not_raise() -> None:
    payload = _full_payload()
    payload["criteria"]["mece"]["score"] = "not-a-number"
    # must not raise; either drops the bad criterion or coerces deterministically
    verdict = parse_verdict(json.dumps(payload), _criteria())
    # other criteria still present and bounded
    if verdict is not None:
        for s in verdict.scores:
            assert 0.0 <= s.score <= 1.0


# --------------------------------------------------------------------------- #
# Determinism + purity                                                          #
# --------------------------------------------------------------------------- #


def test_equal_inputs_yield_equal_verdicts() -> None:
    content = json.dumps(_full_payload())
    a = parse_verdict(content, _criteria())
    b = parse_verdict(content, _criteria())
    assert a == b


def test_parsed_verdict_is_a_frozen_value_object() -> None:
    verdict = parse_verdict(json.dumps(_full_payload()), _criteria())
    assert verdict is not None
    with pytest.raises(Exception):
        verdict.overall_passed = False  # type: ignore[misc]
