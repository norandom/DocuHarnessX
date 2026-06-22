"""Unit tests for the frozen composition data model (cobesy-writer task 1.1).

These tests pin the *model boundary* of the ``cobesy-writer`` composition core: the
frozen, tuple-only value objects (``SCQAOpener``, ``Chunk``, ``EvidenceAnchor``,
``CompositionBlueprint``, ``ProseResult``, ``WriteFlag``, ``WrittenSegments``) and the
``WriterError`` / ``WriterInputError`` error hierarchy.

Observable completion (tasks.md 1.1): importing ``docuharnessx.composition`` exposes
all model types via ``__all__``; constructing each type and comparing two equal
instances returns ``True``; every collection field is a ``tuple``; the
deterministically-immutable value objects raise on mutation.
"""

from __future__ import annotations

import dataclasses

import pytest

import docuharnessx.composition as composition
from docuharnessx.composition import (
    Chunk,
    CompositionBlueprint,
    EvidenceAnchor,
    ProseResult,
    SCQAOpener,
    WriteFlag,
    WriterError,
    WriterInputError,
    WrittenSegments,
)
from docuharnessx.composition import model as composition_model
from docuharnessx.ontology import SCHEMA_VERSION, Segment, Subject

_PREFIXES = frozenset({"component", "tech", "artifact", "topic"})


def _subject(raw: str) -> Subject:
    return Subject.parse(raw, _PREFIXES)


def _scqa() -> SCQAOpener:
    return SCQAOpener(
        situation="You run the CLI daily.",
        complication="Setup keeps failing on a fresh machine.",
        question="How do I install it cleanly?",
        answer="Install with the one-line bootstrap, then verify.",
    )


def _chunks() -> tuple[Chunk, ...]:
    return (
        Chunk(heading="Prerequisites", points=("Go 1.22+", "A clean PATH")),
        Chunk(heading="Install", points=("Run the bootstrap",)),
    )


def _anchors() -> tuple[EvidenceAnchor, ...]:
    return (
        EvidenceAnchor(kind="entrypoint", detail="cmd/main.go", note="primary CLI entry"),
        EvidenceAnchor(kind="ci", detail=".github/workflows/ci.yml", note=""),
    )


def _blueprint() -> CompositionBlueprint:
    return CompositionBlueprint(
        segment_key="tech-savvy-user__install__abc123",
        roles=("tech-savvy-user",),
        intent="install",
        subjects=(_subject("tech:go"), _subject("component:cli")),
        title="Install the CLI",
        scqa=_scqa(),
        key_message="Install with the one-line bootstrap, then verify.",
        chunks=_chunks(),
        fast_path=("Run the bootstrap", "Verify with --version"),
        andragogy=True,
        evidence_anchors=_anchors(),
        role_labels=("Tech-savvy user",),
        intent_label="Install",
    )


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


def _written(
    *,
    segments: tuple[Segment, ...] | None = None,
    flags: tuple[WriteFlag, ...] = (),
    total_planned: int = 1,
) -> WrittenSegments:
    return WrittenSegments(
        segments=(_segment(),) if segments is None else segments,
        flags=flags,
        total_planned=total_planned,
    )


# --------------------------------------------------------------------------- #
# Package namespace surface                                                    #
# --------------------------------------------------------------------------- #


def test_package_exports_all_model_types_via_all() -> None:
    expected = {
        "SCQAOpener",
        "Chunk",
        "EvidenceAnchor",
        "CompositionBlueprint",
        "ProseResult",
        "WriteFlag",
        "WrittenSegments",
        "WriterError",
        "WriterInputError",
    }
    assert expected.issubset(set(composition.__all__))
    for name in expected:
        assert hasattr(composition, name), name


def test_reexports_are_identity_equal_to_submodule_definitions() -> None:
    assert composition.SCQAOpener is composition_model.SCQAOpener
    assert composition.Chunk is composition_model.Chunk
    assert composition.EvidenceAnchor is composition_model.EvidenceAnchor
    assert composition.CompositionBlueprint is composition_model.CompositionBlueprint
    assert composition.ProseResult is composition_model.ProseResult
    assert composition.WriteFlag is composition_model.WriteFlag
    assert composition.WrittenSegments is composition_model.WrittenSegments
    assert composition.WriterError is composition_model.WriterError
    assert composition.WriterInputError is composition_model.WriterInputError


# --------------------------------------------------------------------------- #
# Construction succeeds                                                        #
# --------------------------------------------------------------------------- #


def test_construct_scqa_opener() -> None:
    scqa = _scqa()
    assert scqa.situation
    assert scqa.complication
    assert scqa.question
    assert scqa.answer


def test_construct_chunk() -> None:
    chunk = Chunk(heading="Install", points=("Run the bootstrap",))
    assert chunk.heading == "Install"
    assert chunk.points == ("Run the bootstrap",)


def test_construct_evidence_anchor() -> None:
    anchor = EvidenceAnchor(kind="entrypoint", detail="cmd/main.go", note="entry")
    assert anchor.kind == "entrypoint"
    assert anchor.detail == "cmd/main.go"
    assert anchor.note == "entry"


def test_construct_blueprint() -> None:
    bp = _blueprint()
    assert bp.segment_key == "tech-savvy-user__install__abc123"
    assert bp.roles == ("tech-savvy-user",)
    assert bp.intent == "install"
    assert bp.title == "Install the CLI"
    assert bp.andragogy is True
    assert bp.intent_label == "Install"


def test_construct_prose_result() -> None:
    result = ProseResult(body="# Body", summary="A summary.", source="model")
    assert result.body == "# Body"
    assert result.summary == "A summary."
    assert result.source == "model"


def test_construct_write_flag() -> None:
    flag = WriteFlag(
        segment_key="k", reason="validation", cause="unknown role 'x'"
    )
    assert flag.segment_key == "k"
    assert flag.reason == "validation"
    assert flag.cause == "unknown role 'x'"


def test_construct_written_segments() -> None:
    written = _written()
    assert len(written.segments) == 1
    assert written.flags == ()
    assert written.total_planned == 1


def test_construct_empty_written_segments() -> None:
    written = WrittenSegments(segments=(), flags=(), total_planned=0)
    assert written.segments == ()
    assert written.flags == ()
    assert written.total_planned == 0


# --------------------------------------------------------------------------- #
# Collections are tuples                                                       #
# --------------------------------------------------------------------------- #


def test_blueprint_collections_are_tuples() -> None:
    bp = _blueprint()
    assert isinstance(bp.roles, tuple)
    assert isinstance(bp.subjects, tuple)
    assert isinstance(bp.chunks, tuple)
    assert isinstance(bp.fast_path, tuple)
    assert isinstance(bp.evidence_anchors, tuple)
    assert isinstance(bp.role_labels, tuple)


def test_chunk_points_is_tuple() -> None:
    chunk = _chunks()[0]
    assert isinstance(chunk.points, tuple)


def test_written_segments_collections_are_tuples() -> None:
    written = _written(flags=(WriteFlag(segment_key="k", reason="r", cause="c"),))
    assert isinstance(written.segments, tuple)
    assert isinstance(written.flags, tuple)


# --------------------------------------------------------------------------- #
# Immutability (mutating a field raises)                                       #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "obj, field_name, value",
    [
        (_scqa(), "answer", "other"),
        (Chunk(heading="h", points=()), "heading", "other"),
        (EvidenceAnchor(kind="k", detail="d", note=""), "kind", "other"),
        (_blueprint(), "title", "Other"),
        (_blueprint(), "andragogy", False),
        (ProseResult(body="b", summary="s", source="model"), "source", "fake"),
        (WriteFlag(segment_key="k", reason="r", cause="c"), "cause", "x"),
        (_written(), "total_planned", 9),
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


def test_blueprints_from_equal_inputs_are_equal() -> None:
    assert _blueprint() == _blueprint()


def test_scqa_openers_from_equal_inputs_are_equal() -> None:
    assert _scqa() == _scqa()


def test_prose_results_from_equal_inputs_are_equal() -> None:
    assert ProseResult(body="b", summary="s", source="model") == ProseResult(
        body="b", summary="s", source="model"
    )


def test_write_flags_from_equal_inputs_are_equal() -> None:
    assert WriteFlag(segment_key="k", reason="r", cause="c") == WriteFlag(
        segment_key="k", reason="r", cause="c"
    )


def test_written_segments_from_equal_inputs_are_equal() -> None:
    assert _written() == _written()


def test_written_segments_differ_when_inputs_differ() -> None:
    assert _written(segments=()) != _written()


# --------------------------------------------------------------------------- #
# Hashability of the deeply-frozen value objects                               #
# --------------------------------------------------------------------------- #


def test_blueprint_is_hashable() -> None:
    # frozen + tuple-only collections (and hashable Subject) => hashable
    assert hash(_blueprint()) == hash(_blueprint())


def test_prose_result_and_flag_are_hashable() -> None:
    assert hash(ProseResult(body="b", summary="s", source="model")) == hash(
        ProseResult(body="b", summary="s", source="model")
    )
    assert hash(WriteFlag(segment_key="k", reason="r", cause="c")) == hash(
        WriteFlag(segment_key="k", reason="r", cause="c")
    )


# --------------------------------------------------------------------------- #
# WrittenSegments carries the SAME stored Segment identities                   #
# --------------------------------------------------------------------------- #


def test_written_segments_preserves_segment_identity() -> None:
    seg = _segment()
    written = WrittenSegments(segments=(seg,), flags=(), total_planned=1)
    assert written.segments[0] is seg
    assert written.segments[0].schema_version == SCHEMA_VERSION


# --------------------------------------------------------------------------- #
# Error hierarchy                                                              #
# --------------------------------------------------------------------------- #


def test_error_hierarchy() -> None:
    assert issubclass(WriterError, Exception)
    assert issubclass(WriterInputError, WriterError)


def test_writer_input_error_is_raisable() -> None:
    with pytest.raises(WriterInputError):
        raise WriterInputError("missing slot: docuharnessx.coverage_plan")


def test_writer_input_error_catchable_as_base() -> None:
    with pytest.raises(WriterError):
        raise WriterInputError("x")


def test_writer_error_independent_of_planning_error() -> None:
    # The writer error family is kept independent of the planning family
    # (matching PlanningError), so a WriterError is NOT a PlanningError.
    from docuharnessx.planning import PlanningError

    assert not issubclass(WriterError, PlanningError)
    assert not issubclass(PlanningError, WriterError)
