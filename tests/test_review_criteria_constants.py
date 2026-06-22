"""Unit tests for the COBESY criteria constants and deterministic gate rules.

quality-review-gate task 1.2 (design "COBESY criteria definition" +
"Verdict Computer"; Req 3.1, 3.5, 6.3). These tests pin the *fixed gate
definition* the deterministic review core applies identically to every
segment, with no model:

* the named COBESY criteria set (:data:`COBESY_CRITERIA`) — MECE, working-memory
  fit, role-fit, clarity, falsifiability/evidence, no-AI-slop (Req 3.1);
* the single per-criterion pass threshold (:data:`CRITERION_THRESHOLD`, Req 3.5);
* the documented all-of combination rule — a segment passes iff *every*
  criterion passes (Req 3.5);
* the fail-closed default verdict for an unavailable judge
  (:data:`DEFAULT_UNAVAILABLE_VERDICT` == ``"fail"``, Req 6.3).

Observable completion (tasks.md 1.2): the criteria names, threshold, and
default-verdict are importable constants from ``docuharnessx.review``; the named
criteria set is exactly the COBESY gate and the default-unavailable verdict is a
reject (``"fail"``). The combination-rule and threshold helpers are deterministic
and applied identically to every segment.
"""

from __future__ import annotations

import pytest

import docuharnessx.review as review
from docuharnessx.review import (
    COBESY_CRITERIA,
    CRITERION_THRESHOLD,
    DEFAULT_UNAVAILABLE_VERDICT,
    CriterionScore,
    combine_verdict,
    meets_threshold,
)
from docuharnessx.review import criteria as review_criteria


def _score(name: str, *, score: float, passed: bool) -> CriterionScore:
    return CriterionScore(name=name, score=score, passed=passed, reason="r")


# --------------------------------------------------------------------------- #
# Package namespace surface                                                    #
# --------------------------------------------------------------------------- #


def test_constants_and_rules_exported_via_all() -> None:
    expected = {
        "COBESY_CRITERIA",
        "CRITERION_THRESHOLD",
        "DEFAULT_UNAVAILABLE_VERDICT",
        "combine_verdict",
        "meets_threshold",
    }
    assert expected.issubset(set(review.__all__))
    for name in expected:
        assert hasattr(review, name), name


def test_reexports_are_identity_equal_to_submodule_definitions() -> None:
    assert review.COBESY_CRITERIA is review_criteria.COBESY_CRITERIA
    assert review.CRITERION_THRESHOLD is review_criteria.CRITERION_THRESHOLD
    assert (
        review.DEFAULT_UNAVAILABLE_VERDICT
        is review_criteria.DEFAULT_UNAVAILABLE_VERDICT
    )
    assert review.combine_verdict is review_criteria.combine_verdict
    assert review.meets_threshold is review_criteria.meets_threshold


# --------------------------------------------------------------------------- #
# COBESY_CRITERIA — the fixed named gate (Req 3.1)                             #
# --------------------------------------------------------------------------- #


def test_cobesy_criteria_is_the_exact_named_gate() -> None:
    assert COBESY_CRITERIA == (
        "mece",
        "working_memory",
        "role_fit",
        "clarity",
        "falsifiability",
        "no_ai_slop",
    )


def test_cobesy_criteria_is_an_immutable_tuple_of_str() -> None:
    assert isinstance(COBESY_CRITERIA, tuple)
    assert all(isinstance(name, str) for name in COBESY_CRITERIA)


def test_cobesy_criteria_has_no_duplicates() -> None:
    assert len(COBESY_CRITERIA) == len(set(COBESY_CRITERIA))


# --------------------------------------------------------------------------- #
# CRITERION_THRESHOLD — the single per-criterion pass threshold (Req 3.5)      #
# --------------------------------------------------------------------------- #


def test_criterion_threshold_is_a_float_in_unit_range() -> None:
    assert isinstance(CRITERION_THRESHOLD, float)
    assert 0.0 < CRITERION_THRESHOLD <= 1.0


def test_meets_threshold_at_and_above_passes_below_fails() -> None:
    # The threshold rule is inclusive at the threshold (>=), and applied
    # identically to every criterion score.
    assert meets_threshold(CRITERION_THRESHOLD) is True
    assert meets_threshold(1.0) is True
    assert meets_threshold(CRITERION_THRESHOLD - 0.01) is False
    assert meets_threshold(0.0) is False


def test_meets_threshold_is_deterministic() -> None:
    for value in (0.0, 0.3, CRITERION_THRESHOLD, 0.95, 1.0):
        assert meets_threshold(value) == meets_threshold(value)


# --------------------------------------------------------------------------- #
# DEFAULT_UNAVAILABLE_VERDICT — fail-closed default (Req 6.3)                   #
# --------------------------------------------------------------------------- #


def test_default_unavailable_verdict_is_reject() -> None:
    # A quality firewall does not pass unjudged content: the documented default
    # for an unavailable judge is a reject ("fail").
    assert DEFAULT_UNAVAILABLE_VERDICT == "fail"


# --------------------------------------------------------------------------- #
# combine_verdict — the documented all-of combination rule (Req 3.5)           #
# --------------------------------------------------------------------------- #


def test_combine_verdict_all_pass_is_pass() -> None:
    scores = tuple(
        _score(name, score=0.9, passed=True) for name in COBESY_CRITERIA
    )
    assert combine_verdict(scores) == "pass"


def test_combine_verdict_one_fail_is_fail() -> None:
    scores = (
        _score("mece", score=0.9, passed=True),
        _score("clarity", score=0.2, passed=False),
    )
    assert combine_verdict(scores) == "fail"


def test_combine_verdict_empty_is_fail() -> None:
    # No per-criterion evidence cannot satisfy "every criterion passes" -> fail
    # (fail-closed, consistent with the unavailable-judge default).
    assert combine_verdict(()) == "fail"


def test_combine_verdict_is_deterministic() -> None:
    scores = (
        _score("mece", score=0.9, passed=True),
        _score("clarity", score=0.8, passed=True),
    )
    assert combine_verdict(scores) == combine_verdict(scores)


def test_combine_verdict_uses_passed_flags_not_prose_or_scores() -> None:
    # The rule reads the per-criterion `passed` flag (already threshold-coerced
    # upstream), independent of the raw score value or any free-form prose.
    high_score_but_not_passed = (_score("mece", score=1.0, passed=False),)
    assert combine_verdict(high_score_but_not_passed) == "fail"
    low_score_but_passed = (_score("mece", score=0.0, passed=True),)
    assert combine_verdict(low_score_but_passed) == "pass"


# --------------------------------------------------------------------------- #
# No hardcoded role/intent/subject literals in the gate definition (Req 10.1)  #
# --------------------------------------------------------------------------- #


def test_no_hardcoded_role_intent_subject_literals_in_criteria_names() -> None:
    # The named gate is about *quality dimensions*, never about a specific
    # project's roles / intents / subject prefixes (those come from the loaded
    # Vocabulary at build_criteria time, task 2.1).
    forbidden = {"tech-savvy-user", "install", "component", "topic", "artifact"}
    assert not (set(COBESY_CRITERIA) & forbidden)
