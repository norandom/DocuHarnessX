"""Unit tests for the deterministic verdict computer (quality-review-gate task 2.4).

These tests pin the *Verdict Computer* boundary of the deterministic, model-free review
core: ``compute_verdict(judge, criteria, *, judge_source) -> SegmentReview``. The computer
turns a parsed :class:`~docuharnessx.review.model.JudgeVerdict` (or the absent value
``None``) plus the per-segment :class:`~docuharnessx.review.model.SegmentCriteria` and a
judge-source marker into the per-segment :class:`~docuharnessx.review.model.SegmentReview`
entry — applying the per-criterion :data:`~docuharnessx.review.criteria.CRITERION_THRESHOLD`
and the documented all-of combination rule to derive the ``pass``/``fail`` verdict,
**independent of any free-form judge prose** (Req 3.5, 6.1). On the absent verdict it
applies the fail-closed :data:`~docuharnessx.review.criteria.DEFAULT_UNAVAILABLE_VERDICT`
(reject) with ``judge_source="unavailable"`` and a marker finding; it derives one
actionable finding per failing criterion; it always produces an entry — no written segment
is left without one (Req 6.3, 6.4).

Observable completion (tasks.md 2.4): all-pass criteria yield ``pass``; one failing
criterion yields ``fail`` with a finding; an absent verdict yields the default-reject with
the unavailable source and a marker; and equal inputs yield equal entries (deterministic).
The computer is pure and never consults a model.
"""

from __future__ import annotations

from docuharnessx.review import (
    COBESY_CRITERIA,
    CRITERION_THRESHOLD,
    DEFAULT_UNAVAILABLE_VERDICT,
    CriterionScore,
    JudgeVerdict,
    SegmentCriteria,
    SegmentReview,
)
from docuharnessx.review import verdict as review_verdict
from docuharnessx.review.model import EvidenceAnchor, RoleContext
from docuharnessx.review.verdict import compute_verdict


# --------------------------------------------------------------------------- #
# Fixtures                                                                     #
# --------------------------------------------------------------------------- #


def _criteria(
    *,
    segment_id: str = "astronaut__dock__deadbeef",
    criteria: tuple[str, ...] = COBESY_CRITERIA,
) -> SegmentCriteria:
    return SegmentCriteria(
        segment_id=segment_id,
        title="Dock: the capsule procedure",
        summary="How an orbital astronaut brings the capsule to a safe berth.",
        body="Align the docking ring, then close the latch on the green light.",
        criteria=criteria,
        roles=(
            RoleContext(
                id="astronaut",
                label="Orbital Astronaut",
                description="Operates the station in microgravity.",
            ),
        ),
        intent=RoleContext(
            id="dock",
            label="Dock the Capsule",
            description="Bring the capsule to a safe berth.",
        ),
        evidence_anchors=(
            EvidenceAnchor(kind="entrypoint", detail="cmd/dock.go", note=""),
        ),
    )


def _score(
    name: str, *, score: float, passed: bool, reason: str = "r"
) -> CriterionScore:
    return CriterionScore(name=name, score=score, passed=passed, reason=reason)


def _all_pass_verdict(*, overall_passed: bool = True) -> JudgeVerdict:
    return JudgeVerdict(
        scores=tuple(
            _score(name, score=0.9, passed=True, reason=f"{name} ok")
            for name in COBESY_CRITERIA
        ),
        overall_passed=overall_passed,
        reason="all good",
    )


# --------------------------------------------------------------------------- #
# Always produces a SegmentReview for the criteria's segment (Req 6.4)         #
# --------------------------------------------------------------------------- #


def test_returns_segment_review_for_the_segment() -> None:
    entry = compute_verdict(_all_pass_verdict(), _criteria(), judge_source="model")
    assert isinstance(entry, SegmentReview)
    assert entry.segment_id == "astronaut__dock__deadbeef"


def test_segment_id_taken_from_criteria() -> None:
    entry = compute_verdict(
        _all_pass_verdict(), _criteria(segment_id="other__id__cafe"), judge_source="model"
    )
    assert entry.segment_id == "other__id__cafe"


# --------------------------------------------------------------------------- #
# All-of pass (Req 3.5, 6.1)                                                   #
# --------------------------------------------------------------------------- #


def test_all_criteria_pass_yields_pass() -> None:
    entry = compute_verdict(_all_pass_verdict(), _criteria(), judge_source="model")
    assert entry.verdict == "pass"


def test_pass_has_no_findings() -> None:
    entry = compute_verdict(_all_pass_verdict(), _criteria(), judge_source="model")
    assert entry.findings == ()


def test_pass_carries_a_score_per_criterion() -> None:
    entry = compute_verdict(_all_pass_verdict(), _criteria(), judge_source="model")
    names = tuple(s.name for s in entry.scores)
    assert names == COBESY_CRITERIA


def test_pass_preserves_judge_source_model() -> None:
    entry = compute_verdict(_all_pass_verdict(), _criteria(), judge_source="model")
    assert entry.judge_source == "model"


def test_pass_preserves_judge_source_fake() -> None:
    entry = compute_verdict(_all_pass_verdict(), _criteria(), judge_source="fake")
    assert entry.judge_source == "fake"


# --------------------------------------------------------------------------- #
# One failing criterion -> fail with a finding (Req 6.1, 6.4)                  #
# --------------------------------------------------------------------------- #


def _verdict_with_one_failing(failing: str = "clarity") -> JudgeVerdict:
    return JudgeVerdict(
        scores=tuple(
            _score(
                name,
                score=0.2 if name == failing else 0.9,
                passed=name != failing,
                reason=f"{name} reason",
            )
            for name in COBESY_CRITERIA
        ),
        overall_passed=False,
        reason="one criterion failed",
    )


def test_one_failing_criterion_yields_fail() -> None:
    entry = compute_verdict(
        _verdict_with_one_failing("clarity"), _criteria(), judge_source="model"
    )
    assert entry.verdict == "fail"


def test_one_failing_criterion_yields_exactly_one_finding() -> None:
    entry = compute_verdict(
        _verdict_with_one_failing("clarity"), _criteria(), judge_source="model"
    )
    assert len(entry.findings) == 1


def test_finding_names_the_failing_criterion() -> None:
    entry = compute_verdict(
        _verdict_with_one_failing("clarity"), _criteria(), judge_source="model"
    )
    assert "clarity" in entry.findings[0]


def test_finding_carries_the_judge_reason_for_the_failing_criterion() -> None:
    entry = compute_verdict(
        _verdict_with_one_failing("clarity"), _criteria(), judge_source="model"
    )
    assert "clarity reason" in entry.findings[0]


def test_finding_count_matches_failing_criteria_count() -> None:
    # A complete verdict over every COBESY criterion with exactly two below threshold:
    # there must be exactly two findings (one per failing criterion).
    failing = {"mece", "clarity"}
    judge = JudgeVerdict(
        scores=tuple(
            _score(
                name,
                score=0.2 if name in failing else 0.9,
                passed=name not in failing,
                reason=f"{name} bad" if name in failing else "ok",
            )
            for name in COBESY_CRITERIA
        ),
        overall_passed=False,
        reason="two failed",
    )
    entry = compute_verdict(judge, _criteria(), judge_source="model")
    assert entry.verdict == "fail"
    assert len(entry.findings) == 2
    failing_in_findings = " ".join(entry.findings)
    assert "mece" in failing_in_findings
    assert "clarity" in failing_in_findings


# --------------------------------------------------------------------------- #
# Threshold authority: verdict from threshold, independent of judge prose      #
# (Req 3.5, 6.1)                                                               #
# --------------------------------------------------------------------------- #


def test_passed_flag_recomputed_from_threshold_not_trusted_verbatim() -> None:
    # A judge that marks a sub-threshold score as passed must NOT pass: the gate
    # re-derives the per-criterion pass from the threshold rule, independent of the
    # judge's free-form pass flag (Req 6.1).
    judge = JudgeVerdict(
        scores=tuple(
            _score(name, score=0.1, passed=True, reason="judge says ok")
            for name in COBESY_CRITERIA
        ),
        overall_passed=True,
        reason="judge claims pass",
    )
    entry = compute_verdict(judge, _criteria(), judge_source="model")
    assert entry.verdict == "fail"


def test_at_threshold_score_passes_that_criterion() -> None:
    judge = JudgeVerdict(
        scores=tuple(
            _score(name, score=CRITERION_THRESHOLD, passed=False, reason="at threshold")
            for name in COBESY_CRITERIA
        ),
        overall_passed=False,
        reason="exactly at threshold",
    )
    entry = compute_verdict(judge, _criteria(), judge_source="model")
    # Threshold rule is inclusive at the threshold -> all criteria pass -> pass.
    assert entry.verdict == "pass"


def test_overall_passed_flag_is_ignored_for_the_verdict() -> None:
    # The judge claims overall fail, but every criterion is above threshold: the
    # deterministic verdict is pass (the verdict derives from per-criterion scores).
    judge = _all_pass_verdict(overall_passed=False)
    entry = compute_verdict(judge, _criteria(), judge_source="model")
    assert entry.verdict == "pass"


def test_scores_in_entry_reflect_threshold_derived_passed() -> None:
    judge = JudgeVerdict(
        scores=tuple(
            _score(name, score=0.1, passed=True, reason="judge says ok")
            for name in COBESY_CRITERIA
        ),
        overall_passed=True,
        reason="judge claims pass",
    )
    entry = compute_verdict(judge, _criteria(), judge_source="model")
    assert all(s.passed is False for s in entry.scores)


# --------------------------------------------------------------------------- #
# Missing-criterion handling: a known criterion the judge omitted fails closed #
# (Req 6.1)                                                                    #
# --------------------------------------------------------------------------- #


def test_missing_known_criterion_is_treated_as_not_passed() -> None:
    # The judge only scored some criteria; the gate is over all COBESY criteria, so
    # an omitted known criterion cannot satisfy "every criterion passes" -> fail.
    judge = JudgeVerdict(
        scores=(_score("mece", score=0.9, passed=True, reason="ok"),),
        overall_passed=True,
        reason="partial",
    )
    entry = compute_verdict(judge, _criteria(), judge_source="model")
    assert entry.verdict == "fail"


def test_entry_has_a_score_for_every_cobesy_criterion() -> None:
    judge = JudgeVerdict(
        scores=(_score("mece", score=0.9, passed=True, reason="ok"),),
        overall_passed=True,
        reason="partial",
    )
    entry = compute_verdict(judge, _criteria(), judge_source="model")
    assert tuple(s.name for s in entry.scores) == COBESY_CRITERIA


# --------------------------------------------------------------------------- #
# Absent verdict -> fail-closed default-reject (Req 6.3)                        #
# --------------------------------------------------------------------------- #


def test_none_verdict_yields_default_reject() -> None:
    entry = compute_verdict(None, _criteria(), judge_source="model")
    assert entry.verdict == DEFAULT_UNAVAILABLE_VERDICT
    assert entry.verdict == "fail"


def test_none_verdict_sets_unavailable_judge_source_overriding_arg() -> None:
    # Even when the caller passes "model"/"fake", an absent verdict means the segment
    # was not judged -> the source is recorded as "unavailable" (Req 6.3).
    entry = compute_verdict(None, _criteria(), judge_source="model")
    assert entry.judge_source == "unavailable"


def test_none_verdict_with_fake_source_still_unavailable() -> None:
    entry = compute_verdict(None, _criteria(), judge_source="fake")
    assert entry.judge_source == "unavailable"


def test_none_verdict_has_a_marker_finding() -> None:
    entry = compute_verdict(None, _criteria(), judge_source="model")
    assert len(entry.findings) >= 1
    marker = " ".join(entry.findings).lower()
    assert "judge" in marker or "unavailable" in marker or "not judged" in marker


def test_none_verdict_still_produces_an_entry_for_the_segment() -> None:
    entry = compute_verdict(
        None, _criteria(segment_id="seg__none__1234"), judge_source="model"
    )
    assert isinstance(entry, SegmentReview)
    assert entry.segment_id == "seg__none__1234"


def test_none_verdict_scores_default_to_not_passed_for_each_criterion() -> None:
    entry = compute_verdict(None, _criteria(), judge_source="model")
    # A well-formed entry still carries a score per criterion, all not-passed.
    assert tuple(s.name for s in entry.scores) == COBESY_CRITERIA
    assert all(s.passed is False for s in entry.scores)


# --------------------------------------------------------------------------- #
# Determinism (Req 6.1)                                                        #
# --------------------------------------------------------------------------- #


def test_equal_inputs_yield_equal_entries_pass() -> None:
    a = compute_verdict(_all_pass_verdict(), _criteria(), judge_source="model")
    b = compute_verdict(_all_pass_verdict(), _criteria(), judge_source="model")
    assert a == b


def test_equal_inputs_yield_equal_entries_fail() -> None:
    a = compute_verdict(
        _verdict_with_one_failing("clarity"), _criteria(), judge_source="model"
    )
    b = compute_verdict(
        _verdict_with_one_failing("clarity"), _criteria(), judge_source="model"
    )
    assert a == b


def test_equal_inputs_yield_equal_entries_none() -> None:
    a = compute_verdict(None, _criteria(), judge_source="model")
    b = compute_verdict(None, _criteria(), judge_source="model")
    assert a == b


def test_does_not_raise_on_any_branch() -> None:
    # The computer must never raise: pass, fail, and absent paths all return cleanly.
    compute_verdict(_all_pass_verdict(), _criteria(), judge_source="model")
    compute_verdict(_verdict_with_one_failing(), _criteria(), judge_source="fake")
    compute_verdict(None, _criteria(), judge_source="model")


def test_does_not_mutate_inputs() -> None:
    judge = _all_pass_verdict()
    criteria = _criteria()
    before_scores = judge.scores
    before_criteria = (criteria.segment_id, criteria.criteria)
    compute_verdict(judge, criteria, judge_source="model")
    assert judge.scores == before_scores
    assert (criteria.segment_id, criteria.criteria) == before_criteria


# --------------------------------------------------------------------------- #
# Package surface (mirrors planning/composition)                              #
# --------------------------------------------------------------------------- #


def test_compute_verdict_re_exported_from_package() -> None:
    import docuharnessx.review as review

    assert review.compute_verdict is review_verdict.compute_verdict
    assert "compute_verdict" in review.__all__
