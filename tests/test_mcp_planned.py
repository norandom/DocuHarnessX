"""Unit tests for the stable-id ``PlannedSegment`` reconstruction (mcp-refine task 2.1).

Task 2.1 owns one pure, model-free boundary: ``planned_from_segment(segment) ->
PlannedSegment``. Its load-bearing contract is the **stable-id round-trip** —

    segment_id(planned_from_segment(seg)) == seg.id

— so a later ``rewrite_segment`` re-wires the *same* id in place (the
``FilesystemSegmentStore`` has no update method and ``put`` raises on an existing id, so
the rewrite must reproduce the stored id exactly to replace ``<id>.md``). The
reconstruction copies the stored segment's ``roles`` / ``intent`` / ``subjects`` and
derives a stable ``segment_key`` from them (the same deterministic key the planner builds),
so the derived id matches the stored one. Evidence is reconstructed best-effort (an empty
tuple is tolerated by ``build_blueprint``), it consults no model, and it never mutates the
input.

These tests pin: (a) the stable-id round-trip for representative stored segments — including
multi-role, multi-subject, and zero-subject shapes, and segments whose ids were produced by
the real wiring from the real planner key; (b) that ``build_blueprint(planned_from_segment(
seg), None, vocab)`` yields a well-formed blueprint with no model; and (c) purity (no input
mutation; deterministic).

The fixtures rebuild a stored ``Segment`` the way the real pipeline does — through the
planner's ``segment_key`` construction, ``segment_id``, and ``wire_segment`` — so the
round-trip is pinned against the *actual* persisted-id derivation, not a hand-picked id.
"""

from __future__ import annotations

import copy

from docuharnessx.composition.blueprint import build_blueprint
from docuharnessx.composition.model import CompositionBlueprint, ProseResult
from docuharnessx.composition.wiring import segment_id, wire_segment
from docuharnessx.mcp.planned import planned_from_segment
from docuharnessx.ontology import AxisTerm, Segment, Subject, Vocabulary
from docuharnessx.planning.model import EvidenceRef, PlannedSegment

_PREFIXES = frozenset({"component", "tech", "artifact", "topic"})


def _subject(raw: str) -> Subject:
    return Subject.parse(raw, _PREFIXES)


def _vocab() -> Vocabulary:
    return Vocabulary(
        roles=(
            AxisTerm("platform-dev", "Platform Developer", "Builds on the platform."),
            AxisTerm("auditor", "Compliance Auditor", "Assesses compliance."),
            AxisTerm("adopter", "Adopter", "Adopts the project."),
        ),
        intents=(
            AxisTerm("extend", "Extend", "Add capabilities."),
            AxisTerm("review", "Review", "Judge quality."),
            AxisTerm("understand", "Understand", "Build a mental model."),
        ),
        subject_prefixes=("component:", "tech:", "artifact:", "topic:"),
    )


# --------------------------------------------------------------------------- #
# Build a stored Segment the way the real pipeline does                        #
# --------------------------------------------------------------------------- #
#
# The planner builds segment_key = "<roles-joined>__<intent>__<subjects-digest>" and the
# wiring derives the persisted id from that key. We reproduce that derivation here (without
# importing planner-private helpers) so the round-trip is pinned against the *actual*
# persisted-id shape, then prove planned_from_segment reconstructs an equal id from the
# Segment alone.

import hashlib  # noqa: E402  (local helper region below)


def _planner_segment_key(
    roles: tuple[str, ...], intent: str, subjects: tuple[Subject, ...]
) -> str:
    """Mirror the planner's deterministic segment_key (for fixture construction only)."""
    sorted_subjects = tuple(sorted(subjects, key=lambda s: s.canonical()))
    payload = "\n".join(s.canonical() for s in sorted_subjects)
    digest = hashlib.blake2b(payload.encode("utf-8"), digest_size=6).hexdigest()
    return f"{','.join(roles)}__{intent}__{digest}"


def _stored_segment(
    *,
    roles: tuple[str, ...],
    intent: str,
    subjects: tuple[Subject, ...],
    evidence: tuple[EvidenceRef, ...] = (),
) -> Segment:
    """A Segment as the real pipeline persists it: planner key -> wire_segment."""
    sorted_subjects = tuple(sorted(subjects, key=lambda s: s.canonical()))
    sorted_evidence = tuple(sorted(evidence, key=lambda e: (e.kind, e.detail)))
    planned = PlannedSegment(
        segment_key=_planner_segment_key(roles, intent, sorted_subjects),
        roles=roles,
        intent=intent,
        subjects=sorted_subjects,
        priority=7,
        evidence=sorted_evidence,
    )
    blueprint = build_blueprint(planned, None, _vocab())
    return wire_segment(planned, blueprint, ProseResult(body="b", summary="s", source="fake"))


# Representative stored segments: multi-role, single-role/zero-subject, single-subject.
_SEGMENTS: tuple[Segment, ...] = (
    _stored_segment(
        roles=("platform-dev", "auditor"),
        intent="extend",
        subjects=(_subject("component:cli"), _subject("tech:python")),
        evidence=(EvidenceRef(kind="entrypoint", detail="cmd/main.py"),),
    ),
    _stored_segment(
        roles=("adopter",),
        intent="understand",
        subjects=(),
    ),
    _stored_segment(
        roles=("auditor",),
        intent="review",
        subjects=(_subject("topic:security"),),
    ),
)


# --------------------------------------------------------------------------- #
# (a) Stable-id round-trip                                                     #
# --------------------------------------------------------------------------- #


def test_segment_id_round_trips_for_representative_segments() -> None:
    # The load-bearing contract: the reconstructed planned segment derives the SAME id as
    # the stored segment, for every representative shape — so a rewrite re-wires <id>.md.
    for seg in _SEGMENTS:
        planned = planned_from_segment(seg)
        assert segment_id(planned) == seg.id


def test_round_trip_is_independent_of_summary_and_body() -> None:
    # body/summary are not part of the id derivation: two segments that differ only in
    # body/summary still reconstruct the same id (only roles/intent/subjects key the id).
    seg = _SEGMENTS[0]
    other = copy.deepcopy(seg)
    other.body = "a completely different body"
    other.summary = "different summary"
    assert segment_id(planned_from_segment(seg)) == segment_id(
        planned_from_segment(other)
    )
    assert segment_id(planned_from_segment(other)) == seg.id


def test_reconstruction_copies_axis_values() -> None:
    # roles/intent/subjects are copied verbatim from the stored segment (the axis values a
    # rewrite must keep fixed); the result is a frozen PlannedSegment.
    seg = _SEGMENTS[0]
    planned = planned_from_segment(seg)
    assert isinstance(planned, PlannedSegment)
    assert tuple(planned.roles) == tuple(seg.roles)
    assert planned.intent == seg.intent
    assert set(planned.subjects) == set(seg.subjects)


# --------------------------------------------------------------------------- #
# (b) The reconstructed planned segment builds a well-formed blueprint          #
# --------------------------------------------------------------------------- #


def test_build_blueprint_over_reconstruction_is_well_formed() -> None:
    # build_blueprint(planned_from_segment(seg), None, vocab) yields a well-formed blueprint
    # with no model, for every representative segment (empty-evidence is tolerated).
    vocab = _vocab()
    for seg in _SEGMENTS:
        blueprint = build_blueprint(planned_from_segment(seg), None, vocab)
        assert isinstance(blueprint, CompositionBlueprint)
        assert blueprint.title
        assert blueprint.chunks  # at least orientation + core path
        assert blueprint.roles == tuple(seg.roles)
        assert blueprint.intent == seg.intent


def test_blueprint_segment_key_round_trips_through_segment_id() -> None:
    # The blueprint carries the same segment_key, so segment_id over it also matches the id
    # (the rewrite path runs build_blueprint then wire_segment, which re-derives the id).
    for seg in _SEGMENTS:
        planned = planned_from_segment(seg)
        blueprint = build_blueprint(planned, None, _vocab())
        assert blueprint.segment_key == planned.segment_key


# --------------------------------------------------------------------------- #
# (c) Purity: deterministic, no input mutation, no model                       #
# --------------------------------------------------------------------------- #


def test_reconstruction_is_deterministic() -> None:
    seg = _SEGMENTS[0]
    assert planned_from_segment(seg) == planned_from_segment(seg)


def test_reconstruction_does_not_mutate_input() -> None:
    seg = _SEGMENTS[0]
    before = copy.deepcopy(seg)
    planned_from_segment(seg)
    assert seg.id == before.id
    assert seg.roles == before.roles
    assert seg.intent == before.intent
    assert seg.subjects == before.subjects
    assert seg.title == before.title
    assert seg.body == before.body


def test_evidence_is_best_effort_empty_tuple_tolerated() -> None:
    # Evidence is reconstructed best-effort; an empty tuple is the documented tolerated
    # default and build_blueprint accepts it (no Grounding chunk required).
    seg = _SEGMENTS[1]  # zero-subject segment
    planned = planned_from_segment(seg)
    assert isinstance(planned.evidence, tuple)
    # An empty-evidence blueprint is still well-formed.
    build_blueprint(planned, None, _vocab())
