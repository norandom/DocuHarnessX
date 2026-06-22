"""Unit tests for the deterministic aggregator and report assembler (task 2.5).

These tests pin the *Aggregator* boundary of the deterministic, model-free review core:
``aggregate(entries) -> ReviewAggregate`` and
``assemble_report(entries, by_id) -> ReviewReport``. The aggregator turns the ordered
per-segment :class:`~docuharnessx.review.model.SegmentReview` entries (one per written
segment, in written order) plus a ``segment_id -> Segment`` lookup into the frozen
:class:`~docuharnessx.review.model.ReviewReport` the Wave 3 assembler consumes verbatim.

Observable completion (tasks.md 2.5):

* the accepted set equals exactly the ``pass`` entries in written order and carries the
  *same* :class:`~docuharnessx.ontology.Segment` identities (Req 6.2, 7.4, 7.5);
* the :class:`~docuharnessx.review.model.ReviewAggregate` counts
  (``judged``/``accepted``/``rejected``/``unavailable``) and the per-criterion tally are
  correct (Req 8.1, 8.2);
* an empty entries input yields a well-formed empty report (Req 6.5);
* equal inputs yield an equal report (Req 8.3, 10.3);
* every written segment has exactly one entry (the invariant) and the report carries the
  single :data:`~docuharnessx.review.model.REVIEW_REPORT_SCHEMA_VERSION` (Req 7.1, 7.6).

The aggregator is pure: no model, no I/O, never mutates its inputs, never raises.
"""

from __future__ import annotations

import pytest

from docuharnessx.ontology import Segment
from docuharnessx.review import (
    COBESY_CRITERIA,
    REVIEW_REPORT_SCHEMA_VERSION,
    CriterionScore,
    CriterionTally,
    ReviewAggregate,
    ReviewReport,
    SegmentReview,
)
import importlib

from docuharnessx.review.aggregate import aggregate, assemble_report

# The package re-exports a function named ``aggregate`` that shadows the submodule
# attribute, so reach the module object explicitly (mirrors how the verdict tests
# avoid the collision by importing a non-shadowed name).
review_aggregate = importlib.import_module("docuharnessx.review.aggregate")


# --------------------------------------------------------------------------- #
# Fixtures                                                                     #
# --------------------------------------------------------------------------- #


def _segment(segment_id: str) -> Segment:
    """A minimal real ontology :class:`Segment` with the given id."""

    return Segment(
        id=segment_id,
        title=f"Title {segment_id}",
        roles=["astronaut"],
        subjects=[],
        intent="dock",
        summary=f"Summary {segment_id}",
        body=f"Body {segment_id}",
    )


def _scores(*, passing: set[str] | None = None) -> tuple[CriterionScore, ...]:
    """A full per-criterion score tuple; criteria in ``passing`` pass, the rest fail.

    ``passing=None`` means every criterion passes.
    """

    if passing is None:
        passing = set(COBESY_CRITERIA)
    out = []
    for name in COBESY_CRITERIA:
        ok = name in passing
        out.append(
            CriterionScore(
                name=name,
                score=0.9 if ok else 0.1,
                passed=ok,
                reason=f"{name} ok" if ok else f"{name} bad",
            )
        )
    return tuple(out)


def _pass_entry(segment_id: str) -> SegmentReview:
    return SegmentReview(
        segment_id=segment_id,
        verdict="pass",
        scores=_scores(),
        findings=(),
        judge_source="model",
    )


def _fail_entry(segment_id: str, *, failing: set[str]) -> SegmentReview:
    passing = set(COBESY_CRITERIA) - failing
    return SegmentReview(
        segment_id=segment_id,
        verdict="fail",
        scores=_scores(passing=passing),
        findings=tuple(f"{name} did not meet the quality threshold" for name in failing),
        judge_source="model",
    )


def _unavailable_entry(segment_id: str) -> SegmentReview:
    return SegmentReview(
        segment_id=segment_id,
        verdict="fail",
        scores=_scores(passing=set()),
        findings=("judge unavailable: segment was not judged; default-rejected",),
        judge_source="unavailable",
    )


# --------------------------------------------------------------------------- #
# aggregate(): counts (Req 8.1)                                                #
# --------------------------------------------------------------------------- #


def test_aggregate_returns_review_aggregate() -> None:
    agg = aggregate((_pass_entry("a"),))
    assert isinstance(agg, ReviewAggregate)


def test_aggregate_judged_counts_every_entry() -> None:
    entries = (_pass_entry("a"), _fail_entry("b", failing={"clarity"}), _unavailable_entry("c"))
    agg = aggregate(entries)
    assert agg.judged == 3


def test_aggregate_accepted_counts_pass_entries() -> None:
    entries = (_pass_entry("a"), _pass_entry("b"), _fail_entry("c", failing={"mece"}))
    agg = aggregate(entries)
    assert agg.accepted == 2


def test_aggregate_rejected_counts_fail_entries() -> None:
    entries = (_pass_entry("a"), _fail_entry("b", failing={"mece"}), _unavailable_entry("c"))
    agg = aggregate(entries)
    # Both the model-fail and the unavailable entry have verdict "fail".
    assert agg.rejected == 2


def test_aggregate_unavailable_counts_unavailable_source() -> None:
    entries = (_pass_entry("a"), _unavailable_entry("b"), _unavailable_entry("c"))
    agg = aggregate(entries)
    assert agg.unavailable == 2


def test_aggregate_accepted_plus_rejected_equals_judged() -> None:
    entries = (
        _pass_entry("a"),
        _fail_entry("b", failing={"clarity"}),
        _unavailable_entry("c"),
        _pass_entry("d"),
    )
    agg = aggregate(entries)
    assert agg.accepted + agg.rejected == agg.judged


# --------------------------------------------------------------------------- #
# aggregate(): per-criterion tally (Req 8.2)                                  #
# --------------------------------------------------------------------------- #


def test_aggregate_tally_has_one_entry_per_criterion_in_gate_order() -> None:
    agg = aggregate((_pass_entry("a"),))
    assert tuple(t.name for t in agg.criterion_tally) == COBESY_CRITERIA


def test_aggregate_tally_entries_are_criterion_tally() -> None:
    agg = aggregate((_pass_entry("a"),))
    assert all(isinstance(t, CriterionTally) for t in agg.criterion_tally)


def test_aggregate_tally_counts_passed_and_failed_per_criterion() -> None:
    # a: all pass; b: only clarity fails; c: only clarity fails.
    entries = (
        _pass_entry("a"),
        _fail_entry("b", failing={"clarity"}),
        _fail_entry("c", failing={"clarity"}),
    )
    agg = aggregate(entries)
    by_name = {t.name: t for t in agg.criterion_tally}
    # clarity: passed by "a" only -> passed 1, failed 2
    assert by_name["clarity"].passed == 1
    assert by_name["clarity"].failed == 2
    # mece: passed by all three -> passed 3, failed 0
    assert by_name["mece"].passed == 3
    assert by_name["mece"].failed == 0


def test_aggregate_tally_passed_plus_failed_equals_judged_per_criterion() -> None:
    entries = (
        _pass_entry("a"),
        _fail_entry("b", failing={"mece", "clarity"}),
        _unavailable_entry("c"),
    )
    agg = aggregate(entries)
    for tally in agg.criterion_tally:
        assert tally.passed + tally.failed == agg.judged


def test_aggregate_unavailable_entry_counts_as_failed_for_every_criterion() -> None:
    agg = aggregate((_unavailable_entry("a"),))
    for tally in agg.criterion_tally:
        assert tally.passed == 0
        assert tally.failed == 1


# --------------------------------------------------------------------------- #
# aggregate(): empty input (Req 6.5)                                          #
# --------------------------------------------------------------------------- #


def test_aggregate_empty_yields_zero_counts() -> None:
    agg = aggregate(())
    assert (agg.judged, agg.accepted, agg.rejected, agg.unavailable) == (0, 0, 0, 0)


def test_aggregate_empty_still_has_full_tally_with_zero_counts() -> None:
    agg = aggregate(())
    assert tuple(t.name for t in agg.criterion_tally) == COBESY_CRITERIA
    assert all(t.passed == 0 and t.failed == 0 for t in agg.criterion_tally)


# --------------------------------------------------------------------------- #
# assemble_report(): accepted set == pass entries, same identities (Req 6.2,  #
# 7.4, 7.5)                                                                    #
# --------------------------------------------------------------------------- #


def test_assemble_report_returns_review_report() -> None:
    seg = _segment("a")
    report = assemble_report((_pass_entry("a"),), {"a": seg})
    assert isinstance(report, ReviewReport)


def test_assemble_report_carries_the_schema_version() -> None:
    report = assemble_report((), {})
    assert report.schema_version == REVIEW_REPORT_SCHEMA_VERSION


def test_assemble_report_entries_preserved_in_written_order() -> None:
    entries = (_pass_entry("a"), _fail_entry("b", failing={"clarity"}), _pass_entry("c"))
    by_id = {sid: _segment(sid) for sid in ("a", "b", "c")}
    report = assemble_report(entries, by_id)
    assert report.entries == entries
    assert tuple(e.segment_id for e in report.entries) == ("a", "b", "c")


def test_assemble_report_accepted_is_exactly_pass_entries_in_written_order() -> None:
    entries = (
        _pass_entry("a"),
        _fail_entry("b", failing={"clarity"}),
        _pass_entry("c"),
        _unavailable_entry("d"),
    )
    by_id = {sid: _segment(sid) for sid in ("a", "b", "c", "d")}
    report = assemble_report(entries, by_id)
    assert tuple(s.id for s in report.accepted) == ("a", "c")


def test_assemble_report_accepted_uses_same_segment_identities() -> None:
    seg_a = _segment("a")
    seg_b = _segment("b")
    entries = (_pass_entry("a"), _pass_entry("b"))
    by_id = {"a": seg_a, "b": seg_b}
    report = assemble_report(entries, by_id)
    # Identity (is), not just equality: the assembler must carry the SAME Segment objects
    # as the written set / store, so a consumer can use either handle (Req 7.4).
    assert report.accepted[0] is seg_a
    assert report.accepted[1] is seg_b


def test_assemble_report_rejects_excluded_from_accepted() -> None:
    entries = (_fail_entry("a", failing={"mece"}), _unavailable_entry("b"))
    by_id = {"a": _segment("a"), "b": _segment("b")}
    report = assemble_report(entries, by_id)
    assert report.accepted == ()


def test_assemble_report_aggregate_matches_standalone_aggregate() -> None:
    entries = (_pass_entry("a"), _fail_entry("b", failing={"clarity"}))
    by_id = {"a": _segment("a"), "b": _segment("b")}
    report = assemble_report(entries, by_id)
    assert report.aggregate == aggregate(entries)


# --------------------------------------------------------------------------- #
# assemble_report(): empty input (Req 6.5)                                    #
# --------------------------------------------------------------------------- #


def test_assemble_report_empty_yields_well_formed_empty_report() -> None:
    report = assemble_report((), {})
    assert report.entries == ()
    assert report.accepted == ()
    assert report.aggregate == aggregate(())
    assert report.schema_version == REVIEW_REPORT_SCHEMA_VERSION


# --------------------------------------------------------------------------- #
# Invariant: one entry per written segment; accepted ids subset of entries     #
# --------------------------------------------------------------------------- #


def test_assemble_report_one_entry_per_segment_preserved() -> None:
    entries = (_pass_entry("a"), _pass_entry("b"), _pass_entry("c"))
    by_id = {sid: _segment(sid) for sid in ("a", "b", "c")}
    report = assemble_report(entries, by_id)
    assert len(report.entries) == len(entries)
    assert tuple(e.segment_id for e in report.entries) == ("a", "b", "c")


def test_assemble_report_missing_segment_for_pass_entry_raises() -> None:
    # A pass entry whose segment id is absent from the lookup is a contract violation
    # at the stage boundary (the accepted set must carry the stored identity). The
    # aggregator surfaces it deterministically rather than silently dropping content.
    entries = (_pass_entry("a"),)
    with pytest.raises(KeyError):
        assemble_report(entries, {})


# --------------------------------------------------------------------------- #
# Determinism (Req 8.3, 10.3)                                                 #
# --------------------------------------------------------------------------- #


def test_aggregate_equal_inputs_yield_equal_aggregate() -> None:
    entries = (_pass_entry("a"), _fail_entry("b", failing={"clarity"}), _unavailable_entry("c"))
    assert aggregate(entries) == aggregate(entries)


def test_assemble_report_equal_inputs_yield_equal_report() -> None:
    entries = (_pass_entry("a"), _fail_entry("b", failing={"clarity"}), _pass_entry("c"))
    by_id_1 = {sid: _segment(sid) for sid in ("a", "b", "c")}
    by_id_2 = {sid: _segment(sid) for sid in ("a", "b", "c")}
    report_1 = assemble_report(entries, by_id_1)
    report_2 = assemble_report(entries, by_id_2)
    # ReviewReport compares by value; equal entries + equal (by value) segments -> equal.
    assert report_1 == report_2


def test_aggregate_does_not_mutate_inputs() -> None:
    entries = (_pass_entry("a"), _fail_entry("b", failing={"clarity"}))
    before = entries
    aggregate(entries)
    assert entries == before


def test_assemble_report_does_not_mutate_lookup() -> None:
    entries = (_pass_entry("a"),)
    by_id = {"a": _segment("a")}
    before_keys = set(by_id)
    assemble_report(entries, by_id)
    assert set(by_id) == before_keys


# --------------------------------------------------------------------------- #
# Package surface (mirrors planning/composition)                              #
# --------------------------------------------------------------------------- #


def test_aggregate_re_exported_from_package() -> None:
    import docuharnessx.review as review

    assert review.aggregate is review_aggregate.aggregate
    assert "aggregate" in review.__all__


def test_assemble_report_re_exported_from_package() -> None:
    import docuharnessx.review as review

    assert review.assemble_report is review_aggregate.assemble_report
    assert "assemble_report" in review.__all__
