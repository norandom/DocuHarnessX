"""Unit tests for the deterministic judge-prompt assembler (quality-review-gate task 2.2).

These tests pin the *Judge Prompt Assembler* boundary of the deterministic, model-free
review core: ``build_request(criteria) -> (messages, tools)``. The assembler turns one
frozen :class:`~docuharnessx.review.model.SegmentCriteria` into the model request the
gated per-segment judge step issues — a **system** instruction telling the judge to act
as an objective COBESY evaluator, score each named criterion in ``[0,1]`` with a one-line
reason, and return an overall pass/fail in a strict JSON object; plus a **user** message
carrying a compact brief built **only** from criteria-derived facts (the segment
body/summary/title, the vocab-derived role/intent context, the named criteria, and the
evidence anchors) — never unrelated repository file contents (Req 4.1, 4.2, 4.3, 4.4).

Observable completion (tasks.md 2.2): the request is deterministic for equal criteria,
carries the segment content + role/intent context + evidence anchors + the
structured-verdict instruction, contains no unrelated file contents, and offers an empty
tools list. The assembler is pure and never consults a model.
"""

from __future__ import annotations

from docuharnessx.review import COBESY_CRITERIA
from docuharnessx.review.model import (
    EvidenceAnchor,
    RoleContext,
    SegmentCriteria,
)
from docuharnessx.review.prompt import build_request


# --------------------------------------------------------------------------- #
# Fixtures: a SegmentCriteria with distinct, recognizable text                 #
# --------------------------------------------------------------------------- #


def _criteria(
    *,
    segment_id: str = "astronaut__dock__deadbeef",
    title: str = "Dock: the capsule procedure",
    summary: str = "How an orbital astronaut brings the capsule to a safe berth.",
    body: str = "Align the docking ring, then close the latch on the green light.",
    criteria: tuple[str, ...] = COBESY_CRITERIA,
    roles: tuple[RoleContext, ...] | None = None,
    intent: RoleContext | None = None,
    evidence_anchors: tuple[EvidenceAnchor, ...] | None = None,
) -> SegmentCriteria:
    return SegmentCriteria(
        segment_id=segment_id,
        title=title,
        summary=summary,
        body=body,
        criteria=criteria,
        roles=roles
        if roles is not None
        else (
            RoleContext(
                id="astronaut",
                label="Orbital Astronaut",
                description="Operates the station in microgravity.",
            ),
        ),
        intent=intent
        if intent is not None
        else RoleContext(
            id="dock",
            label="Dock the Capsule",
            description="Bring the capsule to a safe berth.",
        ),
        evidence_anchors=evidence_anchors
        if evidence_anchors is not None
        else (
            EvidenceAnchor(
                kind="entrypoint",
                detail="cmd/dock.go",
                note="entrypoint: dock (capsule)",
            ),
        ),
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


def _system_text(messages: list[object]) -> str:
    return _content_of(messages[0])


def _user_text(messages: list[object]) -> str:
    return "\n".join(
        _content_of(m) for m in messages if _role_of(m) == "user"
    )


# --------------------------------------------------------------------------- #
# Shape (Req 4.1, 4.4)                                                         #
# --------------------------------------------------------------------------- #


def test_returns_messages_and_tools_pair() -> None:
    messages, tools = build_request(_criteria())
    assert isinstance(messages, list)
    assert isinstance(tools, list)


def test_tools_is_empty() -> None:
    # Single-shot judgement, not an agentic loop (Req 4.4; mirrors planning.relevance).
    _messages, tools = build_request(_criteria())
    assert tools == []


def test_has_system_first_then_user() -> None:
    messages, _tools = build_request(_criteria())
    roles = [_role_of(m) for m in messages]
    assert roles[0] == "system"
    assert "user" in roles


# --------------------------------------------------------------------------- #
# System instruction: objective COBESY evaluator + strict JSON verdict shape  #
# (Req 4.1, 4.3)                                                              #
# --------------------------------------------------------------------------- #


def test_system_instructs_objective_cobesy_judge() -> None:
    system = _system_text(build_request(_criteria())[0]).lower()
    assert "cobesy" in system
    # An objective evaluator / judge framing.
    assert "evaluat" in system or "judge" in system


def test_system_instructs_per_criterion_score_in_range_with_reason() -> None:
    system = _system_text(build_request(_criteria())[0]).lower()
    # Score each named criterion in range [0,1] with a one-line reason (Req 4.3).
    assert "score" in system
    assert "0" in system and "1" in system
    assert "reason" in system


def test_system_instructs_overall_pass_fail() -> None:
    system = _system_text(build_request(_criteria())[0]).lower()
    assert "pass" in system
    assert "fail" in system


def test_system_instructs_strict_json_only() -> None:
    system = _system_text(build_request(_criteria())[0])
    low = system.lower()
    assert "json" in low
    # The strict-JSON discipline (mirrors harnessx LLMJudgeEvaluator): JSON only, no prose.
    assert "json only" in low or "no prose" in low or "only json" in low or (
        "json" in low and "no markdown" in low
    )


def test_system_carries_the_structured_verdict_keys() -> None:
    # The instructed JSON shape names the per-criterion + overall verdict keys (Req 4.3).
    system = _system_text(build_request(_criteria())[0])
    assert '"score"' in system
    assert '"passed"' in system
    assert '"reason"' in system
    assert '"criteria"' in system


# --------------------------------------------------------------------------- #
# User brief carries only criteria-derived facts (Req 4.2)                     #
# --------------------------------------------------------------------------- #


def test_user_brief_carries_segment_content() -> None:
    c = _criteria()
    user = _user_text(build_request(c)[0])
    assert c.title in user
    assert c.summary in user
    assert c.body in user


def test_user_brief_carries_role_and_intent_context_from_vocab() -> None:
    c = _criteria()
    user = _user_text(build_request(c)[0])
    # The vocab-derived role/intent *labels* and descriptions (never hardcoded axes).
    assert "Orbital Astronaut" in user
    assert "Operates the station in microgravity." in user
    assert "Dock the Capsule" in user
    assert "Bring the capsule to a safe berth." in user


def test_user_brief_names_each_cobesy_criterion() -> None:
    c = _criteria()
    user = _user_text(build_request(c)[0])
    for name in COBESY_CRITERIA:
        assert name in user


def test_user_brief_carries_evidence_anchors() -> None:
    c = _criteria()
    user = _user_text(build_request(c)[0])
    assert "cmd/dock.go" in user
    assert "entrypoint: dock (capsule)" in user


def test_evidence_note_absent_is_tolerated() -> None:
    c = _criteria(
        evidence_anchors=(EvidenceAnchor(kind="component", detail="cmd", note=""),)
    )
    user = _user_text(build_request(c)[0])
    assert "cmd" in user
    assert "component" in user


def test_no_evidence_anchors_still_assembles() -> None:
    c = _criteria(evidence_anchors=())
    messages, tools = build_request(c)
    assert tools == []
    assert len(messages) >= 2


def test_multiple_roles_all_surfaced() -> None:
    c = _criteria(
        roles=(
            RoleContext(id="astronaut", label="Orbital Astronaut", description="In orbit."),
            RoleContext(id="ground-crew", label="Ground Crew", description="On the ground."),
        )
    )
    user = _user_text(build_request(c)[0])
    assert "Orbital Astronaut" in user
    assert "Ground Crew" in user


def test_no_raw_file_contents_in_request() -> None:
    # The brief carries only the segment's own content + criteria-derived facts (paths,
    # labels), never the *contents* of an unrelated repository file (Req 4.2).
    leaked = "def secret():\n    return 'unrelated-source-line'"
    messages, _tools = build_request(_criteria())
    text = _all_text(messages)
    assert leaked not in text
    assert "unrelated-source-line" not in text


# --------------------------------------------------------------------------- #
# Determinism (Req 4.1, 4.4)                                                   #
# --------------------------------------------------------------------------- #


def test_equal_criteria_produce_equal_requests() -> None:
    a = build_request(_criteria())
    b = build_request(_criteria())
    assert a == b


def test_different_criteria_produce_different_requests() -> None:
    a = build_request(_criteria(body="Align the docking ring."))
    b = build_request(_criteria(body="Open the airlock first."))
    assert a != b


def test_does_not_mutate_criteria() -> None:
    c = _criteria()
    before = (c.criteria, c.roles, c.intent, c.evidence_anchors)
    build_request(c)
    assert (c.criteria, c.roles, c.intent, c.evidence_anchors) == before


# --------------------------------------------------------------------------- #
# Message shape: real harnessx Message when available                          #
# --------------------------------------------------------------------------- #


def test_uses_harnessx_message_when_available() -> None:
    from harnessx.core.events import Message

    messages, _tools = build_request(_criteria())
    assert all(isinstance(m, Message) for m in messages)


# --------------------------------------------------------------------------- #
# Package surface: build_request re-exported from the review namespace         #
# --------------------------------------------------------------------------- #


def test_build_request_re_exported_from_package() -> None:
    import docuharnessx.review as review
    from docuharnessx.review import prompt as review_prompt

    assert review.build_request is review_prompt.build_request
