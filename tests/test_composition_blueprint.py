"""Unit tests for the deterministic COBESY blueprint builder (cobesy-writer task 2.1).

These tests pin the *Blueprint Builder* boundary: ``build_blueprint(planned, analysis,
vocab) -> CompositionBlueprint``. The builder turns one frozen ``PlannedSegment`` (plus
the optional ``RepoAnalysis`` and the loaded ``Vocabulary``) into a deterministic COBESY
composition blueprint *before* any prose — the SCQA opener, the Minto key message, the
working-memory chunks, the REDUCE-barrier fast path, the andragogy (expert-framing) flag,
and the evidence anchors — all derived from the loaded ``Vocabulary`` ``AxisTerm`` labels,
never from a hardcoded role/intent/subject literal.

Observable completion (tasks.md 2.1): the blueprint's SCQA/Minto/chunk/fast-path fields
are populated from a *custom* ``Vocabulary``, the andragogy flag is set for an expert
role, evidence anchors are built with and without a matching ``RepoAnalysis`` finding, and
equal inputs produce an equal blueprint (Req 2.5, 2.6, 3.1-3.6, 9.1, 9.2).
"""

from __future__ import annotations

import pytest

from docuharnessx.analysis.model import (
    REPO_ANALYSIS_SCHEMA_VERSION,
    Component,
    DocPresence,
    Entrypoint,
    RepoAnalysis,
    ScanStats,
)
from docuharnessx.analysis.model import TestLayout as _TestLayout  # noqa: N813
from docuharnessx.composition.blueprint import build_blueprint
from docuharnessx.composition.model import (
    Chunk,
    CompositionBlueprint,
    EvidenceAnchor,
    SCQAOpener,
)
from docuharnessx.ontology import AxisTerm, Subject, Vocabulary, validate_segment
from docuharnessx.planning.model import EvidenceRef, PlannedSegment

_PREFIXES = frozenset({"component", "tech", "artifact", "topic"})


def _subject(raw: str) -> Subject:
    return Subject.parse(raw, _PREFIXES)


# --------------------------------------------------------------------------- #
# Fixtures: a custom vocabulary + planned segments                            #
# --------------------------------------------------------------------------- #


def _vocab() -> Vocabulary:
    """A custom, NON-default vocabulary so tests prove labels are read from it."""
    return Vocabulary(
        roles=(
            AxisTerm(
                "newcomer", "Curious Newcomer", "Evaluating whether to adopt the tool."
            ),
            AxisTerm(
                "platform-dev",
                "Platform Developer",
                "Builds on and extends the platform's code internals.",
            ),
            AxisTerm(
                "auditor",
                "Compliance Auditor",
                "Assesses the security and compliance posture in depth.",
            ),
        ),
        intents=(
            AxisTerm("setup", "Get Started", "Get the tool installed and running."),
            AxisTerm("extend", "Extend", "Add capabilities or customize behavior."),
            AxisTerm("review", "Review", "Judge quality and compliance."),
        ),
        subject_prefixes=("component:", "tech:", "artifact:", "topic:"),
    )


def _planned(
    *,
    roles: tuple[str, ...] = ("newcomer",),
    intent: str = "setup",
    subjects: tuple[Subject, ...] | None = None,
    evidence: tuple[EvidenceRef, ...] | None = None,
    segment_key: str = "newcomer__setup__abc123",
) -> PlannedSegment:
    return PlannedSegment(
        segment_key=segment_key,
        roles=roles,
        intent=intent,
        subjects=subjects if subjects is not None else (_subject("component:cli"),),
        priority=7,
        evidence=evidence
        if evidence is not None
        else (EvidenceRef(kind="entrypoint", detail="cmd/main.go"),),
    )


def _analysis() -> RepoAnalysis:
    return RepoAnalysis(
        schema_version=REPO_ANALYSIS_SCHEMA_VERSION,
        repo_path="/repo",
        languages=(),
        primary_languages=(),
        total_loc=0,
        total_files=0,
        structure=(),
        entrypoints=(Entrypoint(path="cmd/main.go", kind="main", name="app"),),
        build_files=(),
        ci_workflows=(),
        tests=_TestLayout(present=False, frameworks=(), paths=()),
        dependencies=(),
        components=(
            Component(name="cli", path="cmd", representative_files=("cmd/main.go",)),
        ),
        public_surface=(),
        docs=DocPresence(
            has_readme=False, readme_paths=(), doc_dirs=(), other_docs=()
        ),
        artifacts=(),
        scan_stats=ScanStats(
            files_scanned=1,
            files_skipped=0,
            bytes_scanned=10,
            limit_reached=False,
            notes=(),
        ),
    )


# --------------------------------------------------------------------------- #
# Shape + type                                                                 #
# --------------------------------------------------------------------------- #


def test_returns_composition_blueprint() -> None:
    bp = build_blueprint(_planned(), None, _vocab())
    assert isinstance(bp, CompositionBlueprint)


def test_copies_axis_values_verbatim_from_planned() -> None:
    planned = _planned(
        roles=("newcomer",),
        intent="setup",
        subjects=(_subject("component:cli"), _subject("tech:go")),
    )
    bp = build_blueprint(planned, None, _vocab())
    assert bp.segment_key == planned.segment_key
    assert bp.roles == planned.roles
    assert bp.intent == planned.intent
    assert bp.subjects == planned.subjects


def test_blueprint_collections_are_tuples() -> None:
    bp = build_blueprint(_planned(), None, _vocab())
    assert isinstance(bp.roles, tuple)
    assert isinstance(bp.subjects, tuple)
    assert isinstance(bp.chunks, tuple)
    assert isinstance(bp.fast_path, tuple)
    assert isinstance(bp.evidence_anchors, tuple)
    assert isinstance(bp.role_labels, tuple)
    assert all(isinstance(c, Chunk) for c in bp.chunks)
    assert all(isinstance(a, EvidenceAnchor) for a in bp.evidence_anchors)
    assert isinstance(bp.scqa, SCQAOpener)


# --------------------------------------------------------------------------- #
# Labels are read from the LOADED vocabulary (Req 9.1, 9.2)                     #
# --------------------------------------------------------------------------- #


def test_labels_come_from_loaded_vocabulary() -> None:
    bp = build_blueprint(_planned(roles=("platform-dev",), intent="extend"), None, _vocab())
    assert bp.role_labels == ("Platform Developer",)
    assert bp.intent_label == "Extend"


def test_multi_role_labels_in_planned_order() -> None:
    bp = build_blueprint(
        _planned(roles=("newcomer", "auditor"), intent="review"), None, _vocab()
    )
    assert bp.role_labels == ("Curious Newcomer", "Compliance Auditor")
    assert bp.intent_label == "Review"


def test_no_default_profile_labels_leak() -> None:
    # The custom vocab has none of the default profile labels; assert nothing
    # from the default profile (e.g. "Tech-savvy User", "Install") shows up.
    bp = build_blueprint(_planned(), None, _vocab())
    blob = " ".join(
        (
            bp.title,
            bp.key_message,
            bp.scqa.situation,
            bp.scqa.complication,
            bp.scqa.question,
            bp.scqa.answer,
            bp.intent_label,
            *bp.role_labels,
            *(c.heading for c in bp.chunks),
            *(p for c in bp.chunks for p in c.points),
            *bp.fast_path,
        )
    )
    assert "Tech-savvy User" not in blob
    assert "Possible Adopter" not in blob
    # The custom labels DO appear.
    assert "Curious Newcomer" in blob
    assert "Get Started" in bp.intent_label or "Get Started" in blob


# --------------------------------------------------------------------------- #
# SCQA opener (Req 3.2, 3.3) — tuned to role+intent, answer == key message     #
# --------------------------------------------------------------------------- #


def test_scqa_populated_and_tuned_to_role_and_intent() -> None:
    bp = build_blueprint(_planned(roles=("newcomer",), intent="setup"), None, _vocab())
    assert bp.scqa.situation.strip()
    assert bp.scqa.complication.strip()
    assert bp.scqa.question.strip()
    assert bp.scqa.answer.strip()
    # The situation is subject-focused and role-free — never second-person "You are a <role>"
    # (the role is metadata, not reader-facing prose). The role tunes the orientation chunk.
    assert "You are" not in bp.scqa.situation
    assert any(
        "Curious Newcomer" in point for chunk in bp.chunks for point in chunk.points
    )
    assert "Get Started" in bp.scqa.question or "Get Started" in bp.scqa.complication


def test_scqa_answer_is_the_minto_key_message() -> None:
    bp = build_blueprint(_planned(), None, _vocab())
    # The Minto lead conclusion is echoed into the SCQA answer (model.py contract).
    assert bp.scqa.answer == bp.key_message


def test_key_message_is_a_nonempty_lead_conclusion() -> None:
    bp = build_blueprint(_planned(intent="extend"), None, _vocab())
    assert bp.key_message.strip()
    # Minto lead-with-conclusion mentions the intent label.
    assert "Extend" in bp.key_message


# --------------------------------------------------------------------------- #
# Working-memory chunks + REDUCE fast path (Req 3.3)                            #
# --------------------------------------------------------------------------- #


def test_chunks_present_and_bounded_to_working_memory() -> None:
    bp = build_blueprint(_planned(), None, _vocab())
    assert len(bp.chunks) >= 1
    # Working memory: keep the chunk count small (<= 4 supports the 7+/-2 rule).
    assert len(bp.chunks) <= 4
    for chunk in bp.chunks:
        assert chunk.heading.strip()
        assert len(chunk.points) >= 1
        assert all(p.strip() for p in chunk.points)


def test_fast_path_present_for_reduce_barrier() -> None:
    bp = build_blueprint(_planned(), None, _vocab())
    assert len(bp.fast_path) >= 1
    assert all(step.strip() for step in bp.fast_path)


# --------------------------------------------------------------------------- #
# Title (Req 3 / design: intent label + leading subject)                       #
# --------------------------------------------------------------------------- #


def test_title_derived_from_intent_label_and_leading_subject() -> None:
    bp = build_blueprint(
        _planned(intent="setup", subjects=(_subject("component:cli"),)),
        None,
        _vocab(),
    )
    assert "Get Started" in bp.title
    assert "cli" in bp.title


# --------------------------------------------------------------------------- #
# Andragogy: expert framing derived from the loaded vocabulary term (Req 3.4)  #
# --------------------------------------------------------------------------- #


def test_andragogy_set_for_expert_role() -> None:
    # "platform-dev" — its loaded AxisTerm description marks deep code work => expert.
    bp = build_blueprint(_planned(roles=("platform-dev",), intent="extend"), None, _vocab())
    assert bp.andragogy is True


def test_andragogy_set_for_auditor_expert_role() -> None:
    bp = build_blueprint(_planned(roles=("auditor",), intent="review"), None, _vocab())
    assert bp.andragogy is True


def test_andragogy_unset_for_non_expert_role() -> None:
    # "newcomer" — evaluating/adopting; not an expert framing.
    bp = build_blueprint(_planned(roles=("newcomer",), intent="setup"), None, _vocab())
    assert bp.andragogy is False


def test_andragogy_follows_vocabulary_not_role_id() -> None:
    # Same role id "newcomer", but re-described as a deep expert => andragogy flips.
    expert_vocab = Vocabulary(
        roles=(
            AxisTerm(
                "newcomer",
                "Newcomer",
                "An expert developer who extends and builds the internals.",
            ),
        ),
        intents=(AxisTerm("setup", "Get Started", "Get the tool installed."),),
        subject_prefixes=("component:", "tech:", "artifact:", "topic:"),
    )
    bp = build_blueprint(_planned(roles=("newcomer",), intent="setup"), None, expert_vocab)
    assert bp.andragogy is True


# --------------------------------------------------------------------------- #
# Evidence anchors (Req 2.5, 3.5) — with and without analysis                  #
# --------------------------------------------------------------------------- #


def test_evidence_anchors_built_from_evidence_without_analysis() -> None:
    planned = _planned(
        evidence=(
            EvidenceRef(kind="entrypoint", detail="cmd/main.go"),
            EvidenceRef(kind="ci", detail=".github/workflows/ci.yml"),
        )
    )
    bp = build_blueprint(planned, None, _vocab())
    assert len(bp.evidence_anchors) == 2
    kinds = {a.kind for a in bp.evidence_anchors}
    details = {a.detail for a in bp.evidence_anchors}
    assert kinds == {"entrypoint", "ci"}
    assert details == {"cmd/main.go", ".github/workflows/ci.yml"}
    # No analysis => notes are empty (no invented facts, Req 2.5).
    assert all(a.note == "" for a in bp.evidence_anchors)


def test_evidence_anchors_preserve_evidence_kind_and_detail_verbatim() -> None:
    planned = _planned(evidence=(EvidenceRef(kind="test", detail="main_test.go"),))
    bp = build_blueprint(planned, None, _vocab())
    assert bp.evidence_anchors[0].kind == "test"
    assert bp.evidence_anchors[0].detail == "main_test.go"


def test_evidence_anchor_enriched_by_matching_analysis_finding() -> None:
    planned = _planned(evidence=(EvidenceRef(kind="entrypoint", detail="cmd/main.go"),))
    bp = build_blueprint(planned, _analysis(), _vocab())
    anchor = bp.evidence_anchors[0]
    assert anchor.kind == "entrypoint"
    assert anchor.detail == "cmd/main.go"
    # The matching analysis entrypoint enriches the note (a real repo fact).
    assert anchor.note != ""


def test_evidence_anchor_no_enrichment_when_no_match() -> None:
    planned = _planned(
        evidence=(EvidenceRef(kind="entrypoint", detail="other/none.go"),)
    )
    bp = build_blueprint(planned, _analysis(), _vocab())
    # The analysis has no entrypoint at other/none.go => no invented note.
    assert bp.evidence_anchors[0].note == ""


def test_tolerates_empty_evidence() -> None:
    planned = _planned(evidence=())
    bp = build_blueprint(planned, _analysis(), _vocab())
    assert bp.evidence_anchors == ()


# --------------------------------------------------------------------------- #
# Determinism + read-only inputs (Req 2.6, 3.6, 9.x)                            #
# --------------------------------------------------------------------------- #


def test_equal_inputs_produce_equal_blueprint() -> None:
    a = build_blueprint(_planned(), _analysis(), _vocab())
    b = build_blueprint(_planned(), _analysis(), _vocab())
    assert a == b


def test_equal_inputs_produce_equal_blueprint_without_analysis() -> None:
    a = build_blueprint(_planned(), None, _vocab())
    b = build_blueprint(_planned(), None, _vocab())
    assert a == b


def test_does_not_mutate_planned_segment() -> None:
    planned = _planned()
    before = (
        planned.segment_key,
        planned.roles,
        planned.intent,
        planned.subjects,
        planned.evidence,
    )
    build_blueprint(planned, _analysis(), _vocab())
    after = (
        planned.segment_key,
        planned.roles,
        planned.intent,
        planned.subjects,
        planned.evidence,
    )
    assert before == after


def test_blueprint_is_hashable() -> None:
    bp = build_blueprint(_planned(), _analysis(), _vocab())
    assert hash(bp) == hash(build_blueprint(_planned(), _analysis(), _vocab()))


# --------------------------------------------------------------------------- #
# The blueprint shapes a validate_segment-valid Segment (integration sanity)   #
# --------------------------------------------------------------------------- #


def test_blueprint_axis_values_validate_against_vocabulary() -> None:
    # The blueprint copies the planner's axis values verbatim; a Segment built
    # from them must validate against the loaded vocabulary.
    from docuharnessx.ontology import SCHEMA_VERSION, Segment

    planned = _planned(roles=("platform-dev",), intent="extend")
    bp = build_blueprint(planned, None, _vocab())
    seg = Segment(
        id="platform-dev-extend-abc123",
        title=bp.title,
        roles=list(bp.roles),
        subjects=list(bp.subjects),
        intent=bp.intent,
        summary="x",
        body="# x\n\nbody",
        schema_version=SCHEMA_VERSION,
    )
    result = validate_segment(seg, _vocab())
    assert result.is_valid, result.errors


# --------------------------------------------------------------------------- #
# Unknown axis ids degrade deterministically (defensive, never raise)          #
# --------------------------------------------------------------------------- #


def test_unknown_role_or_intent_falls_back_to_id_label_deterministically() -> None:
    # Defensive: the planner guarantees membership, but an id not in the vocab
    # must still produce a deterministic label (the id) rather than raising.
    planned = _planned(roles=("ghost",), intent="phantom")
    bp = build_blueprint(planned, None, _vocab())
    assert bp.role_labels == ("ghost",)
    assert bp.intent_label == "phantom"
    assert bp == build_blueprint(planned, None, _vocab())
