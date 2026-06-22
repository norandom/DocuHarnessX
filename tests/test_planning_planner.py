"""Unit tests for plan materialization: Classification -> CoveragePlan (task 3.2).

These tests pin the *planner* boundary of the classification-coverage-planner:
``docuharnessx.planning.planner.plan_coverage`` turns an intermediate
:class:`~docuharnessx.planning.model.Classification` (the Classify->Plan handoff) into
the frozen, ordered :class:`~docuharnessx.planning.model.CoveragePlan` the Wave 2 writer
consumes. It builds one :class:`~docuharnessx.planning.model.PlannedSegment` per
activated :class:`~docuharnessx.planning.model.CandidateCell` — each carrying a
deterministic ``segment_key``, the scored ``priority`` (from ``scorer.score_cell``),
sorted ``subjects`` and ``evidence``, and the cell's ``roles``/``intent`` — orders the
segments by ``scorer.order_key``, and sets ``schema_version``, ``repo_path``, and
``vocabulary_fingerprint`` from the classification.

Observable completion (tasks.md 3.2):

* over a crafted ``Classification`` the returned plan lists segments in descending
  priority, each carrying roles/subjects/intent and evidence;
* an empty ``Classification`` yields an empty-but-valid plan (never raising, never
  fabricating segments);
* two runs over equal inputs are equal.

Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 6.1, 8.1.
"""

from __future__ import annotations

import dataclasses

import pytest

from docuharnessx.ontology import Subject, Vocabulary, default_profile
from docuharnessx.planning.model import (
    COVERAGE_PLAN_SCHEMA_VERSION,
    CandidateCell,
    Classification,
    CoveragePlan,
    EvidenceRef,
    PlannedSegment,
)
from docuharnessx.planning.planner import plan_coverage
from docuharnessx.planning.scorer import order_key, score_cell


# --------------------------------------------------------------------------- #
# Fixtures                                                                      #
# --------------------------------------------------------------------------- #


def _vocab() -> Vocabulary:
    return default_profile()


def _subject(raw: str, vocab: Vocabulary) -> Subject:
    return Subject.parse(raw, frozenset(vocab.subject_prefixes))


def _cell(
    *,
    roles: tuple[str, ...],
    intent: str,
    subjects: tuple[Subject, ...] = (),
    evidence: tuple[EvidenceRef, ...] = (),
) -> CandidateCell:
    return CandidateCell(
        roles=roles, intent=intent, subjects=subjects, evidence=evidence
    )


def _classification(
    *,
    cells: tuple[CandidateCell, ...],
    subjects: tuple[Subject, ...] = (),
    repo_path: str = "/repo",
    fingerprint: str = "fp-abc",
) -> Classification:
    return Classification(
        repo_path=repo_path,
        vocabulary_fingerprint=fingerprint,
        subjects=subjects,
        cells=cells,
    )


# --------------------------------------------------------------------------- #
# Plan envelope: provenance + version                                          #
# --------------------------------------------------------------------------- #


def test_plan_carries_version_repo_path_and_fingerprint() -> None:
    vocab = _vocab()
    classification = _classification(
        cells=(
            _cell(
                roles=("tech-savvy-user",),
                intent="install",
                evidence=(EvidenceRef(kind="entrypoint", detail="main.go"),),
            ),
        ),
        repo_path="/home/x/proj",
        fingerprint="vocab-fp-123",
    )

    plan = plan_coverage(classification, vocab)

    assert isinstance(plan, CoveragePlan)
    assert plan.schema_version == COVERAGE_PLAN_SCHEMA_VERSION
    assert plan.repo_path == "/home/x/proj"
    assert plan.vocabulary_fingerprint == "vocab-fp-123"
    # The deterministic core never sets relevance.
    assert plan.relevance_applied is False


def test_plan_returns_tuples_and_is_frozen() -> None:
    vocab = _vocab()
    plan = plan_coverage(
        _classification(
            cells=(
                _cell(
                    roles=("tech-savvy-user",),
                    intent="install",
                    evidence=(EvidenceRef(kind="entrypoint", detail="m"),),
                ),
            )
        ),
        vocab,
    )
    assert isinstance(plan.segments, tuple)
    for seg in plan.segments:
        assert isinstance(seg, PlannedSegment)
        assert isinstance(seg.roles, tuple)
        assert isinstance(seg.subjects, tuple)
        assert isinstance(seg.evidence, tuple)
    with pytest.raises(dataclasses.FrozenInstanceError):
        plan.segments = ()  # type: ignore[misc]


# --------------------------------------------------------------------------- #
# One PlannedSegment per cell, carrying its axis + evidence                     #
# --------------------------------------------------------------------------- #


def test_one_segment_per_cell_carrying_roles_intent_subjects_evidence() -> None:
    vocab = _vocab()
    comp = _subject("component:scanner", vocab)
    tech = _subject("tech:go", vocab)
    cell = _cell(
        roles=("tech-savvy-user",),
        intent="install",
        subjects=(comp, tech),
        evidence=(EvidenceRef(kind="entrypoint", detail="cmd/main.go"),),
    )
    plan = plan_coverage(_classification(cells=(cell,)), vocab)

    assert len(plan.segments) == 1
    seg = plan.segments[0]
    assert seg.roles == ("tech-savvy-user",)
    assert seg.intent == "install"
    assert set(seg.subjects) == {comp, tech}
    assert seg.evidence == (EvidenceRef(kind="entrypoint", detail="cmd/main.go"),)
    assert seg.priority == score_cell(cell, vocab)
    assert seg.relevance_note == ""
    assert seg.segment_key  # non-empty deterministic key


def test_segment_subjects_sorted_by_canonical() -> None:
    vocab = _vocab()
    # Pass subjects in non-canonical order; planner must sort by canonical().
    a = _subject("tech:zzz", vocab)
    b = _subject("component:aaa", vocab)
    c = _subject("artifact:mmm", vocab)
    cell = _cell(
        roles=("developer",),
        intent="extend",
        subjects=(a, b, c),
        evidence=(EvidenceRef(kind="public_surface", detail="x"),),
    )
    plan = plan_coverage(_classification(cells=(cell,)), vocab)
    seg = plan.segments[0]
    assert [s.canonical() for s in seg.subjects] == sorted(
        s.canonical() for s in (a, b, c)
    )


def test_segment_evidence_sorted_by_kind_then_detail() -> None:
    vocab = _vocab()
    e1 = EvidenceRef(kind="entrypoint", detail="z.go")
    e2 = EvidenceRef(kind="entrypoint", detail="a.go")
    e3 = EvidenceRef(kind="ci", detail="ci.yml")
    cell = _cell(
        roles=("tech-savvy-user",),
        intent="use",
        evidence=(e1, e2, e3),
    )
    plan = plan_coverage(_classification(cells=(cell,)), vocab)
    seg = plan.segments[0]
    assert seg.evidence == (e3, e2, e1)  # (ci,*) then (entrypoint, a) then (entrypoint, z)


# --------------------------------------------------------------------------- #
# Ordering: priority desc, then scorer.order_key                               #
# --------------------------------------------------------------------------- #


def test_segments_ordered_by_priority_descending() -> None:
    vocab = _vocab()
    weak = _cell(
        roles=("tech-savvy-user",),
        intent="troubleshoot",
        evidence=(EvidenceRef(kind="language", detail="go"),),  # weakest kind
    )
    strong = _cell(
        roles=("tech-savvy-user",),
        intent="install",
        evidence=(
            EvidenceRef(kind="entrypoint", detail="a"),
            EvidenceRef(kind="entrypoint", detail="b"),
            EvidenceRef(kind="entrypoint", detail="c"),
        ),
    )
    plan = plan_coverage(_classification(cells=(weak, strong)), vocab)
    priorities = [s.priority for s in plan.segments]
    assert priorities == sorted(priorities, reverse=True)
    assert plan.segments[0].intent == "install"  # the strong cell ranks first


def test_segment_order_matches_scorer_order_key() -> None:
    vocab = _vocab()
    cells = (
        _cell(
            roles=("manager",),
            intent="evaluate",
            evidence=(EvidenceRef(kind="doc", detail="README.md"),),
        ),
        _cell(
            roles=("tech-savvy-user",),
            intent="install",
            evidence=(EvidenceRef(kind="entrypoint", detail="main"),),
        ),
        _cell(
            roles=("developer",),
            intent="extend",
            evidence=(EvidenceRef(kind="public_surface", detail="api"),),
        ),
    )
    plan = plan_coverage(_classification(cells=cells), vocab)
    keys = [order_key(s, vocab) for s in plan.segments]
    assert keys == sorted(keys)


# --------------------------------------------------------------------------- #
# segment_key determinism + uniqueness                                          #
# --------------------------------------------------------------------------- #


def test_segment_key_is_deterministic_and_unique_per_cell() -> None:
    vocab = _vocab()
    cells = (
        _cell(
            roles=("tech-savvy-user",),
            intent="install",
            subjects=(_subject("component:a", vocab),),
            evidence=(EvidenceRef(kind="entrypoint", detail="m"),),
        ),
        _cell(
            roles=("tech-savvy-user",),
            intent="use",
            subjects=(_subject("component:a", vocab),),
            evidence=(EvidenceRef(kind="entrypoint", detail="m"),),
        ),
    )
    classification = _classification(cells=cells)
    p1 = plan_coverage(classification, vocab)
    p2 = plan_coverage(classification, vocab)
    keys1 = {s.segment_key for s in p1.segments}
    # Two distinct cells -> two distinct keys.
    assert len(keys1) == 2
    # Deterministic across runs.
    assert [s.segment_key for s in p1.segments] == [
        s.segment_key for s in p2.segments
    ]


def test_segment_key_distinguishes_different_subjects() -> None:
    vocab = _vocab()
    base_kwargs = dict(
        roles=("tech-savvy-user",),
        intent="install",
        evidence=(EvidenceRef(kind="entrypoint", detail="m"),),
    )
    cell_a = _cell(subjects=(_subject("component:a", vocab),), **base_kwargs)
    cell_b = _cell(subjects=(_subject("component:b", vocab),), **base_kwargs)
    plan = plan_coverage(_classification(cells=(cell_a, cell_b)), vocab)
    keys = [s.segment_key for s in plan.segments]
    assert len(set(keys)) == 2


# --------------------------------------------------------------------------- #
# Empty plan (Req 5.5) + determinism (Req 5.3, 8.1)                             #
# --------------------------------------------------------------------------- #


def test_empty_classification_yields_empty_but_valid_plan() -> None:
    vocab = _vocab()
    plan = plan_coverage(_classification(cells=()), vocab)
    assert isinstance(plan, CoveragePlan)
    assert plan.segments == ()
    assert plan.schema_version == COVERAGE_PLAN_SCHEMA_VERSION
    assert plan.relevance_applied is False


def test_plan_coverage_never_raises_on_empty() -> None:
    vocab = _vocab()
    # Must not raise; an empty plan is a valid result, not an error.
    plan_coverage(_classification(cells=(), subjects=()), vocab)


def test_two_runs_over_equal_inputs_are_equal() -> None:
    vocab = _vocab()
    cells = (
        _cell(
            roles=("tech-savvy-user",),
            intent="install",
            subjects=(_subject("tech:go", vocab), _subject("component:c", vocab)),
            evidence=(
                EvidenceRef(kind="entrypoint", detail="b"),
                EvidenceRef(kind="entrypoint", detail="a"),
            ),
        ),
        _cell(
            roles=("manager",),
            intent="evaluate",
            evidence=(EvidenceRef(kind="doc", detail="README.md"),),
        ),
    )
    classification = _classification(cells=cells)
    assert plan_coverage(classification, vocab) == plan_coverage(classification, vocab)


def test_plan_does_not_fabricate_segments() -> None:
    vocab = _vocab()
    cells = (
        _cell(
            roles=("tech-savvy-user",),
            intent="install",
            evidence=(EvidenceRef(kind="entrypoint", detail="m"),),
        ),
    )
    plan = plan_coverage(_classification(cells=cells), vocab)
    # Exactly one segment per activated cell — nothing invented.
    assert len(plan.segments) == len(cells)


def test_multi_role_cell_preserved() -> None:
    vocab = _vocab()
    cell = _cell(
        roles=("possible-adopter", "manager"),
        intent="evaluate",
        evidence=(EvidenceRef(kind="doc", detail="README.md"),),
    )
    plan = plan_coverage(_classification(cells=(cell,)), vocab)
    assert plan.segments[0].roles == ("possible-adopter", "manager")
