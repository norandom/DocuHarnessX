"""Unit tests for the deterministic fallback body renderer (cobesy-writer task 2.4).

These tests pin the *Fallback Renderer* boundary: ``render_fallback_body(blueprint) ->
str`` and ``render_fallback_summary(blueprint) -> str``. The fallback renderer is the
deterministic, model-free backbone the Write stage falls back to whenever no model is
bound, or the gated prose step fails/times out/returns empty content. It turns a COBESY
``CompositionBlueprint`` into a valid Markdown ``body`` (honoring the SCQA opener, the
Minto lead-with-conclusion key message, the working-memory chunk subheads + bullet
points, the REDUCE-barrier fast-path list, and the evidence-anchor references) and a
short ``summary`` — built only from blueprint-derived facts.

Observable completion (tasks.md 2.4): a fallback body that, once wired, yields a
``validate_segment``-valid ``Segment`` against a loaded ``Vocabulary``, and equal
blueprints produce equal fallback text (Req 6.3, 8.3).

These tests construct the ``CompositionBlueprint`` directly (the blueprint builder is a
sibling module) so the fallback boundary is pinned in isolation; one integration sanity
test also exercises ``build_blueprint`` to prove the real blueprint renders a valid
segment.
"""

from __future__ import annotations

from docuharnessx.composition.blueprint import build_blueprint
from docuharnessx.composition.fallback import (
    render_fallback_body,
    render_fallback_summary,
)
from docuharnessx.composition.model import (
    Chunk,
    CompositionBlueprint,
    EvidenceAnchor,
    ProseResult,
    SCQAOpener,
)
from docuharnessx.composition.wiring import wire_segment
from docuharnessx.ontology import (
    SCHEMA_VERSION,
    AxisTerm,
    Segment,
    Subject,
    Vocabulary,
    validate_segment,
)
from docuharnessx.planning.model import EvidenceRef, PlannedSegment

_PREFIXES = frozenset({"component", "tech", "artifact", "topic"})


def _subject(raw: str) -> Subject:
    return Subject.parse(raw, _PREFIXES)


# --------------------------------------------------------------------------- #
# Fixtures: a custom vocabulary, planned segments, and blueprints             #
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
    roles: tuple[str, ...] = ("platform-dev",),
    intent: str = "extend",
    subjects: tuple[Subject, ...] | None = None,
    evidence: tuple[EvidenceRef, ...] | None = None,
    segment_key: str = "platform-dev__extend__abc123",
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


def _blueprint_direct(
    *,
    title: str = "Extend: cli",
    andragogy: bool = True,
    evidence_anchors: tuple[EvidenceAnchor, ...] | None = None,
    chunks: tuple[Chunk, ...] | None = None,
    fast_path: tuple[str, ...] | None = None,
) -> CompositionBlueprint:
    """Construct a blueprint directly, isolating the fallback boundary."""
    return CompositionBlueprint(
        segment_key="platform-dev__extend__abc123",
        roles=("platform-dev",),
        intent="extend",
        subjects=(_subject("component:cli"),),
        title=title,
        scqa=SCQAOpener(
            situation="You are a Platform Developer working with cli.",
            complication="Reaching the Extend goal for cli is unclear.",
            question="How do you Extend cli on the shortest path?",
            answer="Extend: the fastest path is the short sequence below.",
        ),
        key_message="Extend: the fastest path is the short sequence below.",
        chunks=chunks
        if chunks is not None
        else (
            Chunk(
                heading="Orientation",
                points=("Who this is for: Platform Developer.", "Goal: Extend cli."),
            ),
            Chunk(
                heading="Extend: the core path",
                points=("Start with cli.", "Follow the fast path to Extend."),
            ),
        ),
        fast_path=fast_path
        if fast_path is not None
        else (
            "Locate cli.",
            "Run the smallest action that makes progress toward Extend.",
            "Verify you reached first success, then stop.",
        ),
        andragogy=andragogy,
        evidence_anchors=evidence_anchors
        if evidence_anchors is not None
        else (EvidenceAnchor(kind="entrypoint", detail="cmd/main.go", note="entrypoint: main (app)"),),
        role_labels=("Platform Developer",),
        intent_label="Extend",
    )


# --------------------------------------------------------------------------- #
# Body: type + non-empty valid Markdown                                       #
# --------------------------------------------------------------------------- #


def test_body_is_a_nonempty_str() -> None:
    body = render_fallback_body(_blueprint_direct())
    assert isinstance(body, str)
    assert body.strip()


def test_body_leads_with_a_markdown_h1_title() -> None:
    body = render_fallback_body(_blueprint_direct(title="Extend: cli"))
    first_line = body.lstrip().splitlines()[0]
    assert first_line == "# Extend: cli"


def test_summary_is_a_nonempty_str() -> None:
    summary = render_fallback_summary(_blueprint_direct())
    assert isinstance(summary, str)
    assert summary.strip()


# --------------------------------------------------------------------------- #
# Body honors the COBESY blueprint structure (Req 6.3, 8.3)                    #
# --------------------------------------------------------------------------- #


def test_body_contains_the_minto_key_message_lead() -> None:
    bp = _blueprint_direct()
    body = render_fallback_body(bp)
    # Minto lead-with-conclusion: the key message appears in the body.
    assert bp.key_message in body


def test_body_contains_the_scqa_opener_moves() -> None:
    bp = _blueprint_direct()
    body = render_fallback_body(bp)
    assert bp.scqa.situation in body
    assert bp.scqa.complication in body
    assert bp.scqa.question in body


def test_body_renders_each_chunk_as_a_subhead_with_bullets() -> None:
    bp = _blueprint_direct()
    body = render_fallback_body(bp)
    for chunk in bp.chunks:
        # Each chunk heading is a Markdown subhead.
        assert f"## {chunk.heading}" in body
        for point in chunk.points:
            # Each point is a Markdown bullet.
            assert f"- {point}" in body


def test_body_renders_the_reduce_fast_path_as_a_list() -> None:
    bp = _blueprint_direct()
    body = render_fallback_body(bp)
    for step in bp.fast_path:
        assert step in body


def test_body_references_each_evidence_anchor() -> None:
    anchors = (
        EvidenceAnchor(kind="entrypoint", detail="cmd/main.go", note="entrypoint: main"),
        EvidenceAnchor(kind="ci", detail=".github/workflows/ci.yml", note=""),
    )
    bp = _blueprint_direct(evidence_anchors=anchors)
    body = render_fallback_body(bp)
    for anchor in anchors:
        assert anchor.detail in body


def test_body_tolerates_no_evidence_anchors() -> None:
    bp = _blueprint_direct(evidence_anchors=())
    body = render_fallback_body(bp)
    assert body.strip()
    # The body still leads with the title and the key message.
    assert "# Extend: cli" in body
    assert bp.key_message in body


def test_body_tolerates_no_chunks() -> None:
    bp = _blueprint_direct(chunks=())
    body = render_fallback_body(bp)
    assert body.strip()
    assert bp.key_message in body


# --------------------------------------------------------------------------- #
# Determinism (Req 9.3)                                                        #
# --------------------------------------------------------------------------- #


def test_equal_blueprints_produce_equal_body() -> None:
    assert render_fallback_body(_blueprint_direct()) == render_fallback_body(
        _blueprint_direct()
    )


def test_equal_blueprints_produce_equal_summary() -> None:
    assert render_fallback_summary(_blueprint_direct()) == render_fallback_summary(
        _blueprint_direct()
    )


def test_body_deterministic_from_real_builder_blueprint() -> None:
    a = build_blueprint(_planned(), None, _vocab())
    b = build_blueprint(_planned(), None, _vocab())
    assert render_fallback_body(a) == render_fallback_body(b)


def test_render_does_not_mutate_blueprint() -> None:
    bp = _blueprint_direct()
    before = (bp.title, bp.key_message, bp.chunks, bp.fast_path, bp.evidence_anchors)
    render_fallback_body(bp)
    render_fallback_summary(bp)
    after = (bp.title, bp.key_message, bp.chunks, bp.fast_path, bp.evidence_anchors)
    assert before == after


# --------------------------------------------------------------------------- #
# Wired fallback segment validates against the loaded vocabulary (Req 6.3)     #
# --------------------------------------------------------------------------- #


def test_wired_fallback_segment_is_valid_against_vocabulary() -> None:
    planned = _planned(roles=("platform-dev",), intent="extend")
    bp = build_blueprint(planned, None, _vocab())
    prose = ProseResult(
        body=render_fallback_body(bp),
        summary=render_fallback_summary(bp),
        source="fallback",
    )
    seg = wire_segment(planned, bp, prose)
    result = validate_segment(seg, _vocab())
    assert result.is_valid, result.errors


def test_wired_fallback_segment_valid_for_each_role_intent() -> None:
    # The fallback must produce a valid segment for any vocabulary role/intent pair.
    cases = (
        (("newcomer",), "setup"),
        (("platform-dev",), "extend"),
        (("auditor",), "review"),
        (("newcomer", "auditor"), "review"),
    )
    vocab = _vocab()
    for roles, intent in cases:
        planned = _planned(
            roles=roles,
            intent=intent,
            segment_key=f"{'-'.join(roles)}__{intent}__k",
        )
        bp = build_blueprint(planned, None, vocab)
        prose = ProseResult(
            body=render_fallback_body(bp),
            summary=render_fallback_summary(bp),
            source="fallback",
        )
        seg = wire_segment(planned, bp, prose)
        result = validate_segment(seg, vocab)
        assert result.is_valid, (roles, intent, result.errors)


def test_wired_fallback_segment_has_nonempty_body_and_title() -> None:
    planned = _planned()
    bp = build_blueprint(planned, None, _vocab())
    prose = ProseResult(
        body=render_fallback_body(bp),
        summary=render_fallback_summary(bp),
        source="fallback",
    )
    seg = wire_segment(planned, bp, prose)
    assert isinstance(seg, Segment)
    assert seg.body.strip()
    assert seg.title.strip()
    assert seg.schema_version == SCHEMA_VERSION


# --------------------------------------------------------------------------- #
# Andragogy framing surfaces in the body when set (Req 3.4 carried through)    #
# --------------------------------------------------------------------------- #


def test_body_differs_when_andragogy_flag_differs() -> None:
    # The expert-framing flag is a blueprint fact the fallback honors, so an
    # expert blueprint and a non-expert one render distinguishable bodies.
    expert = render_fallback_body(_blueprint_direct(andragogy=True))
    novice = render_fallback_body(_blueprint_direct(andragogy=False))
    assert expert != novice
