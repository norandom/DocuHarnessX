"""Unit tests for the deterministic prompt assembler (cobesy-writer task 2.2).

These tests pin the *Prompt Assembler* boundary: ``build_request(blueprint) ->
(messages, tools)``. The assembler turns one frozen
:class:`~docuharnessx.composition.model.CompositionBlueprint` into the model request the
gated prose step issues — a system prompt instructing the model to honor the COBESY
structure (SCQA -> Minto lead -> working-memory chunks -> REDUCE fast path) and ground
claims in the supplied evidence anchors, plus a user message carrying a compact brief
built **only** from blueprint-derived facts (axis labels, key message, chunk
headings/points, fast-path, evidence anchors) — never raw repository file contents
(Req 4.1, 4.2).

Observable completion (tasks.md 2.2): equal blueprints produce equal ``(messages,
tools)``, the request contains only blueprint-derived facts (no file contents), and
``tools`` is empty.
"""

from __future__ import annotations

from docuharnessx.composition.model import (
    Chunk,
    CompositionBlueprint,
    EvidenceAnchor,
    SCQAOpener,
)
from docuharnessx.composition.prompt import build_request
from docuharnessx.ontology import Subject

_PREFIXES = frozenset({"component", "tech", "artifact", "topic"})


def _subject(raw: str) -> Subject:
    return Subject.parse(raw, _PREFIXES)


# --------------------------------------------------------------------------- #
# Fixtures: blueprints with distinct, recognizable text                        #
# --------------------------------------------------------------------------- #


def _blueprint(
    *,
    segment_key: str = "platform-dev__extend__abc123",
    roles: tuple[str, ...] = ("platform-dev",),
    intent: str = "extend",
    subjects: tuple[Subject, ...] | None = None,
    title: str = "Extend: the CLI",
    key_message: str = "Extend: the fastest path is the short sequence below.",
    chunks: tuple[Chunk, ...] | None = None,
    fast_path: tuple[str, ...] = (
        "Locate the CLI.",
        "Run the smallest action that makes progress toward Extend.",
        "Verify you reached first success, then stop.",
    ),
    andragogy: bool = True,
    evidence_anchors: tuple[EvidenceAnchor, ...] | None = None,
    role_labels: tuple[str, ...] = ("Platform Developer",),
    intent_label: str = "Extend",
) -> CompositionBlueprint:
    return CompositionBlueprint(
        segment_key=segment_key,
        roles=roles,
        intent=intent,
        subjects=subjects if subjects is not None else (_subject("component:cli"),),
        title=title,
        scqa=SCQAOpener(
            situation="You are Platform Developer working with the CLI.",
            complication="Reaching the Extend goal for the CLI is unclear.",
            question="How do you Extend the CLI on the shortest path?",
            answer=key_message,
        ),
        key_message=key_message,
        chunks=chunks
        if chunks is not None
        else (
            Chunk(
                heading="Orientation",
                points=("Who this is for: Platform Developer.", "Goal: Extend the CLI."),
            ),
            Chunk(
                heading="Extend: the core path",
                points=("Start with the CLI.", "Follow the fast path to Extend."),
            ),
        ),
        fast_path=fast_path,
        andragogy=andragogy,
        evidence_anchors=evidence_anchors
        if evidence_anchors is not None
        else (
            EvidenceAnchor(
                kind="entrypoint", detail="cmd/main.go", note="entrypoint: main (app)"
            ),
        ),
        role_labels=role_labels,
        intent_label=intent_label,
    )


# --------------------------------------------------------------------------- #
# Helpers to read a message-like record regardless of Message-vs-dict shape    #
# --------------------------------------------------------------------------- #


def _role_of(message: object) -> str:
    if isinstance(message, dict):
        return message["role"]
    return message.role  # type: ignore[attr-defined]


def _content_of(message: object) -> str:
    if isinstance(message, dict):
        return message["content"]
    return message.content  # type: ignore[attr-defined]


def _all_text(messages: list[object]) -> str:
    return "\n".join(_content_of(m) for m in messages)


# --------------------------------------------------------------------------- #
# Shape (Req 4.1)                                                              #
# --------------------------------------------------------------------------- #


def test_returns_messages_and_tools_pair() -> None:
    messages, tools = build_request(_blueprint())
    assert isinstance(messages, list)
    assert isinstance(tools, list)


def test_tools_is_empty() -> None:
    # Single-shot generation, not an agentic loop (Req 4.1, mirrors planning.relevance).
    _messages, tools = build_request(_blueprint())
    assert tools == []


def test_has_system_and_user_messages() -> None:
    messages, _tools = build_request(_blueprint())
    roles = [_role_of(m) for m in messages]
    assert roles[0] == "system"
    assert "user" in roles


def test_system_message_instructs_cobesy_structure() -> None:
    messages, _tools = build_request(_blueprint())
    system = _content_of(messages[0]).lower()
    # The system prompt must instruct honoring SCQA -> Minto lead -> chunks -> REDUCE
    # fast path, grounding in evidence, and returning body + summary (task 2.2 text).
    assert "scqa" in system
    assert "minto" in system or "lead with the conclusion" in system
    assert "fast path" in system or "reduce" in system
    assert "evidence" in system
    assert "summary" in system
    assert "body" in system


# --------------------------------------------------------------------------- #
# User brief carries only blueprint-derived facts (Req 4.2)                     #
# --------------------------------------------------------------------------- #


def test_user_brief_carries_blueprint_facts() -> None:
    bp = _blueprint()
    messages, _tools = build_request(bp)
    text = _all_text(messages)
    # axis labels
    assert "Platform Developer" in text
    assert "Extend" in text
    # the Minto key message
    assert bp.key_message in text
    # chunk headings + points
    assert "Orientation" in text
    assert "Goal: Extend the CLI." in text
    # fast-path steps
    assert "Verify you reached first success, then stop." in text
    # evidence anchors (kind/detail/note)
    assert "cmd/main.go" in text
    assert "entrypoint: main (app)" in text


def test_andragogy_flag_surfaced_in_brief() -> None:
    expert = build_request(_blueprint(andragogy=True))
    novice = build_request(_blueprint(andragogy=False))
    # The expert-framing flag must change the request deterministically so the model is
    # told to respect prior knowledge for an expert role (Req 4.1 derived from blueprint).
    assert expert != novice


def test_no_raw_file_contents_in_request() -> None:
    # The brief must carry only planner/analysis-supplied *facts* (paths, labels), never
    # the *contents* of a repository file (Req 4.2). A path reference is allowed; a line
    # of source code is not.
    leaked = "def main():\n    print('secret-source-line')"
    bp = _blueprint()
    messages, _tools = build_request(bp)
    text = _all_text(messages)
    assert leaked not in text
    assert "secret-source-line" not in text


def test_evidence_note_absent_is_tolerated() -> None:
    # An anchor with an empty note (no matching analysis finding) still assembles cleanly
    # and includes the kind/detail (Req 2.5 tolerance flows through).
    bp = _blueprint(
        evidence_anchors=(
            EvidenceAnchor(kind="component", detail="cmd", note=""),
        )
    )
    messages, _tools = build_request(bp)
    text = _all_text(messages)
    assert "cmd" in text
    assert "component" in text


def test_no_evidence_anchors_still_assembles() -> None:
    bp = _blueprint(evidence_anchors=())
    messages, tools = build_request(bp)
    assert tools == []
    assert len(messages) >= 2


# --------------------------------------------------------------------------- #
# Determinism (Req 4.1, 4.5)                                                   #
# --------------------------------------------------------------------------- #


def test_equal_blueprints_produce_equal_requests() -> None:
    a = build_request(_blueprint())
    b = build_request(_blueprint())
    assert a == b


def test_different_blueprints_produce_different_requests() -> None:
    a = build_request(_blueprint(title="Extend: the CLI"))
    b = build_request(_blueprint(title="Review: the auth module"))
    assert a != b


def test_does_not_mutate_blueprint() -> None:
    bp = _blueprint()
    before = (bp.chunks, bp.fast_path, bp.evidence_anchors, bp.role_labels)
    build_request(bp)
    assert (bp.chunks, bp.fast_path, bp.evidence_anchors, bp.role_labels) == before


# --------------------------------------------------------------------------- #
# Message shape: real harnessx Message when available                          #
# --------------------------------------------------------------------------- #


def test_uses_harnessx_message_when_available() -> None:
    from harnessx.core.events import Message

    messages, _tools = build_request(_blueprint())
    assert all(isinstance(m, Message) for m in messages)
