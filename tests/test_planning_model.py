"""Unit tests for the frozen ``CoveragePlan`` data model (task 1.1).

These tests pin the *model boundary* of the classification-coverage-planner: the
frozen, tuple-only value objects (``EvidenceRef``, ``PlannedSegment``,
``CoveragePlan``), the intermediate Classify->Plan handoff records
(``CandidateCell``, ``Classification``), the single ``COVERAGE_PLAN_SCHEMA_VERSION``
authority, and the planning error hierarchy
(``PlanningError`` / ``PlanningInputError`` / ``CoveragePlanVersionError``).

Observable completion (tasks.md 1.1): constructing a ``CoveragePlan`` /
``PlannedSegment`` succeeds, every collection field is a tuple, mutating a field
raises, and two instances built from equal inputs compare equal.
"""

from __future__ import annotations

import dataclasses

import pytest

from docuharnessx.ontology import Subject
from docuharnessx.planning.model import (
    COVERAGE_PLAN_SCHEMA_VERSION,
    CandidateCell,
    Classification,
    CoveragePlan,
    CoveragePlanVersionError,
    EvidenceRef,
    PlannedSegment,
    PlanningError,
    PlanningInputError,
)

_PREFIXES = frozenset({"component", "tech", "artifact", "topic"})


def _subject(raw: str) -> Subject:
    return Subject.parse(raw, _PREFIXES)


def _evidence() -> tuple[EvidenceRef, ...]:
    return (
        EvidenceRef(kind="entrypoint", detail="cmd/main.go"),
        EvidenceRef(kind="test", detail="main_test.go"),
    )


def _segment(*, priority: int = 5) -> PlannedSegment:
    return PlannedSegment(
        segment_key="tech-savvy-user__install__abc123",
        roles=("tech-savvy-user",),
        intent="install",
        subjects=(_subject("tech:go"), _subject("component:cli")),
        priority=priority,
        evidence=_evidence(),
    )


def _plan(*, segments: tuple[PlannedSegment, ...] | None = None) -> CoveragePlan:
    return CoveragePlan(
        schema_version=COVERAGE_PLAN_SCHEMA_VERSION,
        repo_path="/repo",
        vocabulary_fingerprint="vocab-fp",
        segments=(_segment(),) if segments is None else segments,
    )


# --------------------------------------------------------------------------- #
# Schema version authority                                                     #
# --------------------------------------------------------------------------- #


def test_schema_version_is_one() -> None:
    assert COVERAGE_PLAN_SCHEMA_VERSION == 1


def test_coverage_plan_carries_schema_version() -> None:
    plan = _plan()
    assert plan.schema_version == COVERAGE_PLAN_SCHEMA_VERSION


# --------------------------------------------------------------------------- #
# Construction succeeds                                                        #
# --------------------------------------------------------------------------- #


def test_construct_evidence_ref() -> None:
    ref = EvidenceRef(kind="ci", detail=".github/workflows/ci.yml")
    assert ref.kind == "ci"
    assert ref.detail == ".github/workflows/ci.yml"


def test_construct_planned_segment() -> None:
    seg = _segment()
    assert seg.segment_key == "tech-savvy-user__install__abc123"
    assert seg.roles == ("tech-savvy-user",)
    assert seg.intent == "install"
    assert seg.priority == 5
    assert seg.relevance_note == ""  # default


def test_construct_coverage_plan() -> None:
    plan = _plan()
    assert plan.repo_path == "/repo"
    assert plan.vocabulary_fingerprint == "vocab-fp"
    assert len(plan.segments) == 1
    assert plan.relevance_applied is False  # default


def test_construct_empty_coverage_plan() -> None:
    plan = _plan(segments=())
    assert plan.segments == ()


def test_planned_segment_reuses_ontology_subject() -> None:
    seg = _segment()
    assert all(isinstance(s, Subject) for s in seg.subjects)


# --------------------------------------------------------------------------- #
# Collections are tuples                                                       #
# --------------------------------------------------------------------------- #


def test_planned_segment_collections_are_tuples() -> None:
    seg = _segment()
    assert isinstance(seg.roles, tuple)
    assert isinstance(seg.subjects, tuple)
    assert isinstance(seg.evidence, tuple)


def test_coverage_plan_segments_is_tuple() -> None:
    plan = _plan()
    assert isinstance(plan.segments, tuple)


def test_classification_collections_are_tuples() -> None:
    cls = Classification(
        repo_path="/repo",
        vocabulary_fingerprint="vocab-fp",
        subjects=(_subject("component:cli"),),
        cells=(
            CandidateCell(
                roles=("tech-savvy-user",),
                intent="install",
                subjects=(_subject("component:cli"),),
                evidence=_evidence(),
            ),
        ),
    )
    assert isinstance(cls.subjects, tuple)
    assert isinstance(cls.cells, tuple)
    assert isinstance(cls.cells[0].roles, tuple)
    assert isinstance(cls.cells[0].subjects, tuple)
    assert isinstance(cls.cells[0].evidence, tuple)


# --------------------------------------------------------------------------- #
# Immutability (mutating a field raises)                                       #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "obj, field, value",
    [
        (EvidenceRef(kind="ci", detail="x"), "kind", "other"),
        (_segment(), "priority", 9),
        (_segment(), "relevance_note", "note"),
        (_plan(), "relevance_applied", True),
        (_plan(), "repo_path", "/other"),
    ],
)
def test_fields_are_immutable(obj: object, field: str, value: object) -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(obj, field, value)


def test_candidate_cell_is_immutable() -> None:
    cell = CandidateCell(
        roles=("r",), intent="i", subjects=(), evidence=()
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        cell.intent = "other"  # type: ignore[misc]


def test_classification_is_immutable() -> None:
    cls = Classification(
        repo_path="/repo",
        vocabulary_fingerprint="fp",
        subjects=(),
        cells=(),
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        cls.repo_path = "/other"  # type: ignore[misc]


# --------------------------------------------------------------------------- #
# Structural equality from equal inputs                                        #
# --------------------------------------------------------------------------- #


def test_planned_segments_from_equal_inputs_are_equal() -> None:
    assert _segment() == _segment()


def test_coverage_plans_from_equal_inputs_are_equal() -> None:
    assert _plan() == _plan()


def test_coverage_plans_differ_when_inputs_differ() -> None:
    assert _plan(segments=()) != _plan()


def test_classifications_from_equal_inputs_are_equal() -> None:
    def build() -> Classification:
        return Classification(
            repo_path="/repo",
            vocabulary_fingerprint="fp",
            subjects=(_subject("component:cli"),),
            cells=(
                CandidateCell(
                    roles=("r",),
                    intent="i",
                    subjects=(_subject("component:cli"),),
                    evidence=_evidence(),
                ),
            ),
        )

    assert build() == build()


# --------------------------------------------------------------------------- #
# Hashability (deeply immutable -> hashable)                                   #
# --------------------------------------------------------------------------- #


def test_value_objects_are_hashable() -> None:
    # frozen + tuple-only collections => safely hashable
    assert hash(_segment()) == hash(_segment())
    assert hash(_plan()) == hash(_plan())
    assert hash(EvidenceRef(kind="ci", detail="x")) == hash(
        EvidenceRef(kind="ci", detail="x")
    )


# --------------------------------------------------------------------------- #
# Error hierarchy                                                              #
# --------------------------------------------------------------------------- #


def test_error_hierarchy() -> None:
    assert issubclass(PlanningError, Exception)
    assert issubclass(PlanningInputError, PlanningError)
    assert issubclass(CoveragePlanVersionError, PlanningError)


def test_planning_input_error_is_raisable() -> None:
    with pytest.raises(PlanningInputError):
        raise PlanningInputError("missing slot: docuharnessx.repo_analysis")


def test_coverage_plan_version_error_is_raisable() -> None:
    with pytest.raises(CoveragePlanVersionError):
        raise CoveragePlanVersionError("unsupported schema_version 2")


def test_subclasses_catchable_as_base() -> None:
    with pytest.raises(PlanningError):
        raise PlanningInputError("x")
    with pytest.raises(PlanningError):
        raise CoveragePlanVersionError("x")
