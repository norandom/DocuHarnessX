"""Unit tests for deterministic ``CoveragePlan`` serde (task 1.2).

These tests pin the *serde boundary* of the classification-coverage-planner: the
``to_dict`` / ``from_dict`` / ``to_json`` functions in
:mod:`docuharnessx.planning.serde`.

Observable completion (tasks.md 1.2):

* ``from_dict(to_dict(plan)) == plan`` for a populated plan (round-trip equality);
* ``to_json`` returns byte-identical strings for equal inputs across repeated calls
  (byte stability via ``sort_keys=True``);
* an unknown ``schema_version`` raises :class:`CoveragePlanVersionError`.

Each ``Subject`` serializes to its canonical ``"prefix:local"`` string and is rebuilt
on load via ``Subject.parse`` (the prefix is inferred from the subject's own
already-canonical form), so the round-trip needs no external vocabulary.
"""

from __future__ import annotations

import json

import pytest

from docuharnessx.ontology import Subject
from docuharnessx.planning.model import (
    COVERAGE_PLAN_SCHEMA_VERSION,
    CoveragePlan,
    CoveragePlanVersionError,
    EvidenceRef,
    PlannedSegment,
)
from docuharnessx.planning.serde import from_dict, to_dict, to_json

_PREFIXES = frozenset({"component", "tech", "artifact", "topic"})


def _subject(raw: str) -> Subject:
    return Subject.parse(raw, _PREFIXES)


def _segment(
    *,
    segment_key: str = "tech-savvy-user__install__abc123",
    roles: tuple[str, ...] = ("tech-savvy-user",),
    intent: str = "install",
    priority: int = 5,
    relevance_note: str = "",
) -> PlannedSegment:
    return PlannedSegment(
        segment_key=segment_key,
        roles=roles,
        intent=intent,
        subjects=(_subject("component:cli"), _subject("tech:go")),
        priority=priority,
        evidence=(
            EvidenceRef(kind="entrypoint", detail="cmd/main.go"),
            EvidenceRef(kind="test", detail="main_test.go"),
        ),
        relevance_note=relevance_note,
    )


def _populated_plan() -> CoveragePlan:
    """A fully-populated plan exercising every field, including non-defaults."""
    return CoveragePlan(
        schema_version=COVERAGE_PLAN_SCHEMA_VERSION,
        repo_path="/home/mc/Source/malware_hashes",
        vocabulary_fingerprint="vocab-fp-deadbeef",
        segments=(
            _segment(priority=9, relevance_note="top of mind"),
            _segment(
                segment_key="contributor__contribute__def456",
                roles=("contributor", "developer"),
                intent="contribute",
                priority=3,
            ),
        ),
        relevance_applied=True,
    )


def _empty_plan() -> CoveragePlan:
    return CoveragePlan(
        schema_version=COVERAGE_PLAN_SCHEMA_VERSION,
        repo_path="/repo",
        vocabulary_fingerprint="vocab-fp",
        segments=(),
    )


# --------------------------------------------------------------------------- #
# to_dict: JSON-compatible, Subject -> canonical string                        #
# --------------------------------------------------------------------------- #


def test_to_dict_is_json_compatible() -> None:
    data = to_dict(_populated_plan())
    # round-trips through json with no custom encoder
    assert json.loads(json.dumps(data)) == data


def test_to_dict_carries_top_level_fields() -> None:
    plan = _populated_plan()
    data = to_dict(plan)
    assert data["schema_version"] == COVERAGE_PLAN_SCHEMA_VERSION
    assert data["repo_path"] == plan.repo_path
    assert data["vocabulary_fingerprint"] == plan.vocabulary_fingerprint
    assert data["relevance_applied"] is True
    assert isinstance(data["segments"], list)
    assert len(data["segments"]) == 2


def test_to_dict_serializes_subject_to_canonical_string() -> None:
    data = to_dict(_populated_plan())
    seg0 = data["segments"][0]
    # subjects become a list of canonical strings, not nested dicts
    assert seg0["subjects"] == ["component:cli", "tech:go"]


def test_to_dict_serializes_evidence_as_dicts() -> None:
    data = to_dict(_populated_plan())
    seg0 = data["segments"][0]
    assert seg0["evidence"] == [
        {"kind": "entrypoint", "detail": "cmd/main.go"},
        {"kind": "test", "detail": "main_test.go"},
    ]


def test_to_dict_segment_collections_are_lists() -> None:
    seg0 = to_dict(_populated_plan())["segments"][0]
    assert isinstance(seg0["roles"], list)
    assert isinstance(seg0["subjects"], list)
    assert isinstance(seg0["evidence"], list)


def test_to_dict_empty_plan() -> None:
    data = to_dict(_empty_plan())
    assert data["segments"] == []
    assert data["relevance_applied"] is False


# --------------------------------------------------------------------------- #
# Round-trip equality                                                          #
# --------------------------------------------------------------------------- #


def test_round_trip_populated_plan_equal() -> None:
    plan = _populated_plan()
    assert from_dict(to_dict(plan)) == plan


def test_round_trip_empty_plan_equal() -> None:
    plan = _empty_plan()
    assert from_dict(to_dict(plan)) == plan


def test_round_trip_preserves_subject_types() -> None:
    plan = _populated_plan()
    rebuilt = from_dict(to_dict(plan))
    for seg in rebuilt.segments:
        assert all(isinstance(s, Subject) for s in seg.subjects)
        assert seg.subjects == plan.segments[plan.segments.index(seg)].subjects


def test_round_trip_preserves_segment_order() -> None:
    plan = _populated_plan()
    rebuilt = from_dict(to_dict(plan))
    assert tuple(s.segment_key for s in rebuilt.segments) == tuple(
        s.segment_key for s in plan.segments
    )


def test_round_trip_preserves_relevance_note_and_flag() -> None:
    plan = _populated_plan()
    rebuilt = from_dict(to_dict(plan))
    assert rebuilt.relevance_applied is True
    assert rebuilt.segments[0].relevance_note == "top of mind"
    assert rebuilt.segments[1].relevance_note == ""


def test_from_dict_via_json_round_trip() -> None:
    plan = _populated_plan()
    assert from_dict(json.loads(to_json(plan))) == plan


# --------------------------------------------------------------------------- #
# to_json byte stability                                                       #
# --------------------------------------------------------------------------- #


def test_to_json_is_byte_stable_across_repeated_calls() -> None:
    plan = _populated_plan()
    assert to_json(plan) == to_json(plan)


def test_to_json_byte_identical_for_equal_inputs() -> None:
    assert to_json(_populated_plan()) == to_json(_populated_plan())


def test_to_json_uses_sorted_keys() -> None:
    payload = to_json(_populated_plan())
    parsed = json.loads(payload)
    # top-level keys are emitted in sorted order
    reserialized = json.dumps(parsed, sort_keys=True, ensure_ascii=False)
    assert payload == reserialized


def test_to_json_differs_for_different_plans() -> None:
    assert to_json(_populated_plan()) != to_json(_empty_plan())


def test_to_json_round_trips_through_from_dict() -> None:
    plan = _populated_plan()
    assert from_dict(json.loads(to_json(plan))) == plan


# --------------------------------------------------------------------------- #
# Version error                                                                #
# --------------------------------------------------------------------------- #


def test_from_dict_unknown_version_raises() -> None:
    data = to_dict(_populated_plan())
    data["schema_version"] = 2
    with pytest.raises(CoveragePlanVersionError):
        from_dict(data)


def test_from_dict_missing_version_raises() -> None:
    data = to_dict(_populated_plan())
    del data["schema_version"]
    with pytest.raises(CoveragePlanVersionError):
        from_dict(data)


def test_from_dict_version_error_names_offending_version() -> None:
    data = to_dict(_populated_plan())
    data["schema_version"] = 99
    with pytest.raises(CoveragePlanVersionError, match="99"):
        from_dict(data)
