"""Unit tests for the frozen review data model (quality-review-gate task 1.1).

These tests pin the *model boundary* (design "ReviewModel") of the
``quality-review-gate`` review core: the frozen, tuple-only value objects
(:class:`CriterionScore`, :class:`JudgeVerdict`, :class:`SegmentReview`,
:class:`CriterionTally`, :class:`ReviewAggregate`, :class:`ReviewReport`), the
``Verdict`` / ``JudgeSource`` value types, the single
:data:`REVIEW_REPORT_SCHEMA_VERSION` version authority, and the
:class:`ReviewError` / :class:`ReviewInputError` error hierarchy.

Observable completion (tasks.md 1.1): importing ``docuharnessx.review`` exposes the
report model, the version constant, and the error types via ``__all__``; constructing
a report from sample entries yields a frozen, structurally-equal value object (two
equal constructions compare equal). The ``ReviewReport`` carries the *same*
``Segment`` identities as the written set / store (mirroring ``WrittenSegments``).
"""

from __future__ import annotations

import dataclasses

import pytest

import docuharnessx.review as review
from docuharnessx.review import (
    REVIEW_REPORT_SCHEMA_VERSION,
    CriterionScore,
    CriterionTally,
    JudgeVerdict,
    ReviewAggregate,
    ReviewError,
    ReviewInputError,
    ReviewReport,
    SegmentReview,
)
from docuharnessx.review import model as review_model
from docuharnessx.ontology import SCHEMA_VERSION, Segment, Subject

_PREFIXES = frozenset({"component", "tech", "artifact", "topic"})


def _subject(raw: str) -> Subject:
    return Subject.parse(raw, _PREFIXES)


def _segment(seg_id: str = "tech-savvy-user-install-abc123") -> Segment:
    return Segment(
        id=seg_id,
        title="Install the CLI",
        roles=["tech-savvy-user"],
        subjects=[_subject("component:cli")],
        intent="install",
        summary="How to install.",
        body="# Install\n\nRun the bootstrap.",
    )


def _score(
    name: str = "mece",
    *,
    score: float = 0.9,
    passed: bool = True,
    reason: str = "Sections are mutually exclusive.",
) -> CriterionScore:
    return CriterionScore(name=name, score=score, passed=passed, reason=reason)


def _scores() -> tuple[CriterionScore, ...]:
    return (
        _score("mece", score=0.9, passed=True, reason="MECE."),
        _score("clarity", score=0.8, passed=True, reason="Clear."),
    )


def _judge_verdict() -> JudgeVerdict:
    return JudgeVerdict(
        scores=_scores(),
        overall_passed=True,
        reason="All criteria met.",
    )


def _segment_review(
    *,
    segment_id: str = "tech-savvy-user-install-abc123",
    verdict: str = "pass",
    scores: tuple[CriterionScore, ...] | None = None,
    findings: tuple[str, ...] = (),
    judge_source: str = "model",
) -> SegmentReview:
    return SegmentReview(
        segment_id=segment_id,
        verdict=verdict,
        scores=_scores() if scores is None else scores,
        findings=findings,
        judge_source=judge_source,
    )


def _tally() -> tuple[CriterionTally, ...]:
    return (
        CriterionTally(name="mece", passed=1, failed=0),
        CriterionTally(name="clarity", passed=1, failed=0),
    )


def _aggregate() -> ReviewAggregate:
    return ReviewAggregate(
        judged=1,
        accepted=1,
        rejected=0,
        unavailable=0,
        criterion_tally=_tally(),
    )


def _report(
    *,
    entries: tuple[SegmentReview, ...] | None = None,
    accepted: tuple[Segment, ...] | None = None,
    aggregate: ReviewAggregate | None = None,
) -> ReviewReport:
    seg = _segment()
    return ReviewReport(
        schema_version=REVIEW_REPORT_SCHEMA_VERSION,
        entries=(_segment_review(),) if entries is None else entries,
        accepted=(seg,) if accepted is None else accepted,
        aggregate=_aggregate() if aggregate is None else aggregate,
    )


# --------------------------------------------------------------------------- #
# Package namespace surface                                                    #
# --------------------------------------------------------------------------- #


def test_package_exports_all_model_types_via_all() -> None:
    expected = {
        "REVIEW_REPORT_SCHEMA_VERSION",
        "Verdict",
        "JudgeSource",
        "CriterionScore",
        "JudgeVerdict",
        "SegmentReview",
        "CriterionTally",
        "ReviewAggregate",
        "ReviewReport",
        "ReviewError",
        "ReviewInputError",
    }
    assert expected.issubset(set(review.__all__))
    for name in expected:
        assert hasattr(review, name), name


def test_reexports_are_identity_equal_to_submodule_definitions() -> None:
    assert review.CriterionScore is review_model.CriterionScore
    assert review.JudgeVerdict is review_model.JudgeVerdict
    assert review.SegmentReview is review_model.SegmentReview
    assert review.CriterionTally is review_model.CriterionTally
    assert review.ReviewAggregate is review_model.ReviewAggregate
    assert review.ReviewReport is review_model.ReviewReport
    assert review.ReviewError is review_model.ReviewError
    assert review.ReviewInputError is review_model.ReviewInputError
    assert (
        review.REVIEW_REPORT_SCHEMA_VERSION
        is review_model.REVIEW_REPORT_SCHEMA_VERSION
    )


# --------------------------------------------------------------------------- #
# Version authority                                                            #
# --------------------------------------------------------------------------- #


def test_schema_version_is_a_positive_int() -> None:
    assert isinstance(REVIEW_REPORT_SCHEMA_VERSION, int)
    assert REVIEW_REPORT_SCHEMA_VERSION >= 1


def test_report_carries_the_schema_version() -> None:
    assert _report().schema_version == REVIEW_REPORT_SCHEMA_VERSION


# --------------------------------------------------------------------------- #
# Verdict / JudgeSource value types                                            #
# --------------------------------------------------------------------------- #


def test_verdict_and_judge_source_are_string_compatible() -> None:
    # Verdict / JudgeSource are str value objects (Literal aliases) -> plain
    # strings construct the model fields, mirroring the design's str shape.
    entry = _segment_review(verdict="fail", judge_source="unavailable")
    assert entry.verdict == "fail"
    assert entry.judge_source == "unavailable"


# --------------------------------------------------------------------------- #
# Construction succeeds                                                        #
# --------------------------------------------------------------------------- #


def test_construct_criterion_score() -> None:
    cs = _score("role_fit", score=0.75, passed=True, reason="Matches the role.")
    assert cs.name == "role_fit"
    assert cs.score == 0.75
    assert cs.passed is True
    assert cs.reason == "Matches the role."


def test_construct_judge_verdict() -> None:
    jv = _judge_verdict()
    assert jv.overall_passed is True
    assert jv.reason == "All criteria met."
    assert len(jv.scores) == 2


def test_construct_segment_review() -> None:
    sr = _segment_review(verdict="fail", findings=("clarity: too dense",))
    assert sr.segment_id == "tech-savvy-user-install-abc123"
    assert sr.verdict == "fail"
    assert sr.findings == ("clarity: too dense",)
    assert sr.judge_source == "model"


def test_construct_criterion_tally() -> None:
    ct = CriterionTally(name="mece", passed=3, failed=1)
    assert ct.name == "mece"
    assert ct.passed == 3
    assert ct.failed == 1


def test_construct_review_aggregate() -> None:
    agg = _aggregate()
    assert agg.judged == 1
    assert agg.accepted == 1
    assert agg.rejected == 0
    assert agg.unavailable == 0
    assert len(agg.criterion_tally) == 2


def test_construct_review_report() -> None:
    report = _report()
    assert report.schema_version == REVIEW_REPORT_SCHEMA_VERSION
    assert len(report.entries) == 1
    assert len(report.accepted) == 1
    assert report.aggregate == _aggregate()


def test_construct_empty_review_report() -> None:
    empty_agg = ReviewAggregate(
        judged=0, accepted=0, rejected=0, unavailable=0, criterion_tally=()
    )
    report = ReviewReport(
        schema_version=REVIEW_REPORT_SCHEMA_VERSION,
        entries=(),
        accepted=(),
        aggregate=empty_agg,
    )
    assert report.entries == ()
    assert report.accepted == ()
    assert report.aggregate.judged == 0


# --------------------------------------------------------------------------- #
# Collections are tuples                                                       #
# --------------------------------------------------------------------------- #


def test_judge_verdict_scores_is_tuple() -> None:
    assert isinstance(_judge_verdict().scores, tuple)


def test_segment_review_collections_are_tuples() -> None:
    sr = _segment_review(findings=("a", "b"))
    assert isinstance(sr.scores, tuple)
    assert isinstance(sr.findings, tuple)


def test_review_aggregate_tally_is_tuple() -> None:
    assert isinstance(_aggregate().criterion_tally, tuple)


def test_review_report_collections_are_tuples() -> None:
    report = _report()
    assert isinstance(report.entries, tuple)
    assert isinstance(report.accepted, tuple)


# --------------------------------------------------------------------------- #
# Immutability (mutating a field raises)                                       #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "obj, field_name, value",
    [
        (_score(), "score", 0.1),
        (_score(), "passed", False),
        (_judge_verdict(), "overall_passed", False),
        (_segment_review(), "verdict", "fail"),
        (_segment_review(), "judge_source", "fake"),
        (CriterionTally(name="mece", passed=1, failed=0), "passed", 9),
        (_aggregate(), "judged", 99),
        (_report(), "schema_version", 999),
    ],
)
def test_value_objects_are_immutable(
    obj: object, field_name: str, value: object
) -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(obj, field_name, value)


# --------------------------------------------------------------------------- #
# Structural equality from equal inputs                                        #
# --------------------------------------------------------------------------- #


def test_criterion_scores_from_equal_inputs_are_equal() -> None:
    assert _score() == _score()


def test_judge_verdicts_from_equal_inputs_are_equal() -> None:
    assert _judge_verdict() == _judge_verdict()


def test_segment_reviews_from_equal_inputs_are_equal() -> None:
    assert _segment_review() == _segment_review()


def test_review_aggregates_from_equal_inputs_are_equal() -> None:
    assert _aggregate() == _aggregate()


def test_reports_from_equal_inputs_are_equal() -> None:
    assert _report() == _report()


def test_reports_differ_when_inputs_differ() -> None:
    assert _report(entries=()) != _report()


# --------------------------------------------------------------------------- #
# Hashability of the deeply-frozen value objects (no Segment field)            #
# --------------------------------------------------------------------------- #


def test_score_verdict_aggregate_are_hashable() -> None:
    # frozen + tuple-only collections (no mutable-Segment field) => hashable.
    assert hash(_score()) == hash(_score())
    assert hash(_judge_verdict()) == hash(_judge_verdict())
    assert hash(_segment_review()) == hash(_segment_review())
    assert hash(_aggregate()) == hash(_aggregate())


# --------------------------------------------------------------------------- #
# ReviewReport carries the SAME stored Segment identities                      #
# --------------------------------------------------------------------------- #


def test_report_preserves_segment_identity() -> None:
    seg = _segment()
    report = _report(accepted=(seg,))
    assert report.accepted[0] is seg
    assert report.accepted[0].schema_version == SCHEMA_VERSION


# --------------------------------------------------------------------------- #
# Error hierarchy                                                              #
# --------------------------------------------------------------------------- #


def test_error_hierarchy() -> None:
    assert issubclass(ReviewError, Exception)
    assert issubclass(ReviewInputError, ReviewError)


def test_review_input_error_is_raisable() -> None:
    with pytest.raises(ReviewInputError):
        raise ReviewInputError("missing slot: docuharnessx.written_segments")


def test_review_input_error_catchable_as_base() -> None:
    with pytest.raises(ReviewError):
        raise ReviewInputError("x")


def test_review_error_independent_of_writer_and_planning_errors() -> None:
    # The review error family is kept independent of the writer / planning
    # families (matching how each keeps its own), so a ReviewError is neither.
    from docuharnessx.composition import WriterError
    from docuharnessx.planning import PlanningError

    assert not issubclass(ReviewError, WriterError)
    assert not issubclass(ReviewError, PlanningError)
    assert not issubclass(WriterError, ReviewError)
    assert not issubclass(PlanningError, ReviewError)
