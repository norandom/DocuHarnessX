"""Unit tests for the deterministic per-segment criteria builder.

quality-review-gate task 2.1 (design "Criteria Builder"; Req 2.5, 2.6, 3.1,
3.2, 3.3, 3.4, 10.1, 10.2). These tests pin the *Criteria Builder* boundary of
the deterministic, model-free review core: :func:`build_criteria` turns one
written :class:`~docuharnessx.ontology.Segment` (plus its matching
:class:`~docuharnessx.planning.model.PlannedSegment`, the optional
:class:`~docuharnessx.analysis.model.RepoAnalysis`, and the loaded
:class:`~docuharnessx.ontology.Vocabulary`) into a deterministic
:class:`~docuharnessx.review.model.SegmentCriteria` context.

Observable completion (tasks.md 2.1): a unit test builds criteria for a segment
under a *custom* vocabulary and asserts the criteria names, the role-fit context
taken from the custom vocab labels/descriptions (never hardcoded), evidence
anchors with and without a matching analysis finding, the no-plan fallback
(empty anchors, still produced), and that equal inputs yield equal criteria and
anchors. Inputs are treated read-only (Req 2.6).
"""

from __future__ import annotations

import dataclasses

import pytest

import docuharnessx.review as review
from docuharnessx.review import (
    COBESY_CRITERIA,
    EvidenceAnchor,
    RoleContext,
    SegmentCriteria,
    build_criteria,
)
from docuharnessx.review import criteria as review_criteria
from docuharnessx.review import model as review_model

from docuharnessx.analysis.model import (
    REPO_ANALYSIS_SCHEMA_VERSION,
    DocPresence,
    Entrypoint,
    RepoAnalysis,
    ScanStats,
)
from docuharnessx.analysis.model import TestLayout as _TestLayout  # noqa: N813
from docuharnessx.composition.wiring import wire_segment
from docuharnessx.composition.model import (
    CompositionBlueprint,
    ProseResult,
    SCQAOpener,
)
from docuharnessx.ontology import AxisTerm, Subject, Vocabulary
from docuharnessx.planning.model import EvidenceRef, PlannedSegment


# --------------------------------------------------------------------------- #
# Fixtures — a custom vocabulary so role-fit context can never be hardcoded   #
# --------------------------------------------------------------------------- #

# Deliberately NOT the default-profile ids/labels: a custom profile proves the
# role-fit context is read from the loaded Vocabulary, not a hardcoded table.
_CUSTOM_ROLE = AxisTerm(
    id="astronaut",
    label="Orbital Astronaut",
    description="Operates the station in microgravity.",
)
_OTHER_ROLE = AxisTerm(
    id="ground-crew",
    label="Ground Crew",
    description="Coordinates the mission from the ground.",
)
_CUSTOM_INTENT = AxisTerm(
    id="dock",
    label="Dock the Capsule",
    description="Bring the capsule to a safe berth.",
)
_PREFIXES = ("module:", "system:")


def _custom_vocab() -> Vocabulary:
    return Vocabulary(
        roles=(_CUSTOM_ROLE, _OTHER_ROLE),
        intents=(_CUSTOM_INTENT,),
        subject_prefixes=_PREFIXES,
    )


def _subject(raw: str) -> Subject:
    return Subject.parse(raw, frozenset({"module", "system"}))


def _planned(
    *,
    segment_key: str = "astronaut__dock__deadbeef",
    roles: tuple[str, ...] = ("astronaut",),
    intent: str = "dock",
    evidence: tuple[EvidenceRef, ...] = (),
) -> PlannedSegment:
    return PlannedSegment(
        segment_key=segment_key,
        roles=roles,
        intent=intent,
        subjects=(_subject("module:capsule"),),
        priority=10,
        evidence=evidence,
    )


def _segment_for(planned: PlannedSegment) -> Segment:
    """Wire a real ontology Segment whose id matches the planned segment_id.

    Uses the production wiring so the test mirrors how a written Segment is
    aligned to its plan by the deterministic ``segment_id`` matching key.
    """
    blueprint = CompositionBlueprint(
        segment_key=planned.segment_key,
        roles=planned.roles,
        intent=planned.intent,
        subjects=planned.subjects,
        title="Dock the capsule",
        scqa=SCQAOpener(situation="s", complication="c", question="q", answer="a"),
        key_message="k",
        chunks=(),
        fast_path=(),
        andragogy=True,
        evidence_anchors=(),
        role_labels=("Orbital Astronaut",),
        intent_label="Dock the Capsule",
    )
    prose = ProseResult(body="The body.", summary="The summary.", source="fake")
    return wire_segment(planned, blueprint, prose)


def _analysis_with_entrypoint(path: str) -> RepoAnalysis:
    return RepoAnalysis(
        schema_version=REPO_ANALYSIS_SCHEMA_VERSION,
        repo_path="/repo",
        languages=(),
        primary_languages=(),
        total_loc=0,
        total_files=0,
        structure=(),
        entrypoints=(Entrypoint(path=path, kind="cli", name="dock"),),
        build_files=(),
        ci_workflows=(),
        tests=_TestLayout(present=False, frameworks=(), paths=()),
        dependencies=(),
        components=(),
        public_surface=(),
        docs=DocPresence(
            has_readme=False, readme_paths=(), doc_dirs=(), other_docs=()
        ),
        artifacts=(),
        scan_stats=ScanStats(
            files_scanned=0,
            files_skipped=0,
            bytes_scanned=0,
            limit_reached=False,
            notes=(),
        ),
    )


# --------------------------------------------------------------------------- #
# Package namespace surface                                                    #
# --------------------------------------------------------------------------- #


def test_builder_and_records_exported_via_all() -> None:
    expected = {"build_criteria", "SegmentCriteria", "RoleContext", "EvidenceAnchor"}
    assert expected.issubset(set(review.__all__))
    for name in expected:
        assert hasattr(review, name), name


def test_reexports_are_identity_equal_to_submodule_definitions() -> None:
    assert review.build_criteria is review_criteria.build_criteria
    assert review.SegmentCriteria is review_model.SegmentCriteria
    assert review.RoleContext is review_model.RoleContext
    assert review.EvidenceAnchor is review_model.EvidenceAnchor


# --------------------------------------------------------------------------- #
# Criteria names — the fixed COBESY gate carried verbatim (Req 3.1)            #
# --------------------------------------------------------------------------- #


def test_criteria_names_are_the_cobesy_gate() -> None:
    planned = _planned()
    criteria = build_criteria(_segment_for(planned), planned, None, _custom_vocab())
    assert criteria.criteria == COBESY_CRITERIA


def test_segment_criteria_carries_segment_content() -> None:
    planned = _planned()
    segment = _segment_for(planned)
    criteria = build_criteria(segment, planned, None, _custom_vocab())
    assert criteria.segment_id == segment.id
    assert criteria.title == segment.title
    assert criteria.summary == segment.summary
    assert criteria.body == segment.body


# --------------------------------------------------------------------------- #
# Role-fit context from the LOADED vocabulary labels/descriptions (Req 3.2)   #
# --------------------------------------------------------------------------- #


def test_role_context_taken_from_custom_vocab_labels_not_hardcoded() -> None:
    planned = _planned()
    criteria = build_criteria(_segment_for(planned), planned, None, _custom_vocab())

    # The role-fit context is the loaded vocabulary's labels/descriptions for the
    # segment's roles — NOT a hardcoded default-profile label.
    assert criteria.roles == (
        RoleContext(
            id="astronaut",
            label="Orbital Astronaut",
            description="Operates the station in microgravity.",
        ),
    )
    assert criteria.intent == RoleContext(
        id="dock",
        label="Dock the Capsule",
        description="Bring the capsule to a safe berth.",
    )


def test_role_context_follows_a_renamed_term_with_no_code_change() -> None:
    # Re-describe the same role id with a different label/description; the
    # role-fit context must follow the loaded vocabulary, proving it is not
    # keyed off a hardcoded literal (Req 10.2).
    renamed = AxisTerm(
        id="astronaut",
        label="Spacefarer",
        description="A renamed role.",
    )
    vocab = Vocabulary(
        roles=(renamed, _OTHER_ROLE),
        intents=(_CUSTOM_INTENT,),
        subject_prefixes=_PREFIXES,
    )
    planned = _planned()
    criteria = build_criteria(_segment_for(planned), planned, None, vocab)
    assert criteria.roles[0].label == "Spacefarer"
    assert criteria.roles[0].description == "A renamed role."


def test_multiple_roles_preserve_segment_role_order() -> None:
    planned = _planned(roles=("ground-crew", "astronaut"))
    criteria = build_criteria(_segment_for(planned), planned, None, _custom_vocab())
    assert tuple(r.id for r in criteria.roles) == ("ground-crew", "astronaut")
    assert criteria.roles[0].label == "Ground Crew"
    assert criteria.roles[1].label == "Orbital Astronaut"


def test_role_id_absent_from_vocab_degrades_to_id_without_raising() -> None:
    # The writer guarantees membership, but the builder stays total + pure:
    # an id the vocab does not carry falls back to the id as its own label.
    planned = _planned(roles=("unknown-role",))
    criteria = build_criteria(_segment_for(planned), planned, None, _custom_vocab())
    assert criteria.roles == (
        RoleContext(id="unknown-role", label="unknown-role", description=""),
    )


def test_intent_id_absent_from_vocab_degrades_to_id() -> None:
    planned = _planned(intent="unknown-intent")
    criteria = build_criteria(_segment_for(planned), planned, None, _custom_vocab())
    assert criteria.intent == RoleContext(
        id="unknown-intent", label="unknown-intent", description=""
    )


# --------------------------------------------------------------------------- #
# Evidence anchors from the matching PlannedSegment (+ analysis) (Req 3.3)    #
# --------------------------------------------------------------------------- #


def test_evidence_anchors_without_analysis_fall_back_to_refs_alone() -> None:
    evidence = (
        EvidenceRef(kind="entrypoint", detail="cmd/dock/main.go"),
        EvidenceRef(kind="component", detail="pkg/nav"),
    )
    planned = _planned(evidence=evidence)
    criteria = build_criteria(_segment_for(planned), planned, None, _custom_vocab())
    assert criteria.evidence_anchors == (
        EvidenceAnchor(kind="entrypoint", detail="cmd/dock/main.go", note=""),
        EvidenceAnchor(kind="component", detail="pkg/nav", note=""),
    )


def test_evidence_anchor_enriched_by_matching_analysis_finding() -> None:
    evidence = (EvidenceRef(kind="entrypoint", detail="cmd/dock/main.go"),)
    planned = _planned(evidence=evidence)
    analysis = _analysis_with_entrypoint("cmd/dock/main.go")
    criteria = build_criteria(
        _segment_for(planned), planned, analysis, _custom_vocab()
    )
    (anchor,) = criteria.evidence_anchors
    assert anchor.kind == "entrypoint"
    assert anchor.detail == "cmd/dock/main.go"
    assert anchor.note != ""  # grounded in the matching real finding


def test_non_matching_analysis_does_not_invent_a_note() -> None:
    evidence = (EvidenceRef(kind="entrypoint", detail="cmd/dock/main.go"),)
    planned = _planned(evidence=evidence)
    analysis = _analysis_with_entrypoint("cmd/other/main.go")  # different path
    criteria = build_criteria(
        _segment_for(planned), planned, analysis, _custom_vocab()
    )
    (anchor,) = criteria.evidence_anchors
    assert anchor.note == ""


def test_no_matching_plan_still_produces_criteria_with_empty_anchors() -> None:
    # A written segment with no matching planned segment still gets criteria;
    # evidence anchors are empty (never dropped) — Req from tasks.md 2.1.
    planned = _planned()
    segment = _segment_for(planned)
    criteria = build_criteria(segment, None, None, _custom_vocab())
    assert isinstance(criteria, SegmentCriteria)
    assert criteria.criteria == COBESY_CRITERIA
    assert criteria.evidence_anchors == ()
    # role/intent context still comes from the segment's own roles/intent.
    assert criteria.roles[0].id == "astronaut"
    assert criteria.intent.id == "dock"


# --------------------------------------------------------------------------- #
# Determinism + immutability (Req 3.4, 2.6, 10.x)                              #
# --------------------------------------------------------------------------- #


def test_equal_inputs_yield_equal_criteria_and_anchors() -> None:
    evidence = (EvidenceRef(kind="entrypoint", detail="cmd/dock/main.go"),)
    analysis = _analysis_with_entrypoint("cmd/dock/main.go")

    planned_a = _planned(evidence=evidence)
    planned_b = _planned(evidence=evidence)
    a = build_criteria(_segment_for(planned_a), planned_a, analysis, _custom_vocab())
    b = build_criteria(_segment_for(planned_b), planned_b, analysis, _custom_vocab())
    assert a == b
    assert a.evidence_anchors == b.evidence_anchors


def test_segment_criteria_is_frozen() -> None:
    planned = _planned()
    criteria = build_criteria(_segment_for(planned), planned, None, _custom_vocab())
    with pytest.raises(dataclasses.FrozenInstanceError):
        criteria.title = "mutated"  # type: ignore[misc]


def test_records_are_frozen_and_hashable() -> None:
    anchor = EvidenceAnchor(kind="k", detail="d", note="n")
    role = RoleContext(id="i", label="l", description="d")
    assert hash(anchor) == hash(EvidenceAnchor(kind="k", detail="d", note="n"))
    assert hash(role) == hash(RoleContext(id="i", label="l", description="d"))
    with pytest.raises(dataclasses.FrozenInstanceError):
        anchor.note = "x"  # type: ignore[misc]


def test_builder_does_not_mutate_inputs() -> None:
    evidence = (EvidenceRef(kind="entrypoint", detail="cmd/dock/main.go"),)
    planned = _planned(evidence=evidence)
    segment = _segment_for(planned)
    vocab = _custom_vocab()
    analysis = _analysis_with_entrypoint("cmd/dock/main.go")

    seg_roles_before = list(segment.roles)
    seg_body_before = segment.body
    build_criteria(segment, planned, analysis, vocab)

    # The written Segment is treated read-only (Req 2.6).
    assert segment.roles == seg_roles_before
    assert segment.body == seg_body_before
    # Frozen inputs are unchanged by identity.
    assert planned.evidence == evidence
    assert vocab == _custom_vocab()


def test_evidence_anchor_order_follows_planned_evidence_order() -> None:
    evidence = (
        EvidenceRef(kind="component", detail="pkg/a"),
        EvidenceRef(kind="entrypoint", detail="cmd/b/main.go"),
    )
    planned = _planned(evidence=evidence)
    criteria = build_criteria(_segment_for(planned), planned, None, _custom_vocab())
    assert tuple((a.kind, a.detail) for a in criteria.evidence_anchors) == (
        ("component", "pkg/a"),
        ("entrypoint", "cmd/b/main.go"),
    )
