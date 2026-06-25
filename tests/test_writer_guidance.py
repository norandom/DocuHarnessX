"""Unit tests for the additive, never-echoed ``guidance`` keyword on the bounded writer.

Task 2.3 (docuharnessx-mcp-refine, boundary: *writer guidance keyword* —
``composition/agent.py`` + ``composition/task_prompt.py``) threads one optional,
backward-compatible ``guidance: str = ""`` keyword through
:meth:`docuharnessx.composition.agent.AgenticProseRunner.run` ->
:func:`docuharnessx.composition.task_prompt.build_agent_task` ->
``_render_description``. The human refinement guidance shapes WHAT the agent writes and
emphasises (an **applied** author-guidance instruction near the mission) but is **never
echoed**: it is not quoted verbatim, named, or rendered as a heading/section — mirroring the
existing role/COBESY anti-echo discipline (Req 5.2, 5.9, 7.2, 9.1, 9.7).

Observable completion (tasks.md 2.3):
  (a) with ``guidance=""`` the rendered ``BaseTask.description`` is byte-identical to today's
      task (the existing agentic-writer suite stays green);
  (b) with a non-empty ``guidance`` the applied author-guidance instruction reaches the
      rendered ``BaseTask.description`` near the mission;
  (c) the verbatim ``guidance`` text does NOT appear as a heading/section line in the
      description (applied, not echoed).

No model is consulted: ``build_agent_task`` / ``_render_description`` are pure, model-free.
"""

from __future__ import annotations

from harnessx.core.harness import BaseTask

from docuharnessx.composition.model import (
    Chunk,
    CompositionBlueprint,
    EvidenceAnchor,
    SCQAOpener,
)
from docuharnessx.composition.task_prompt import build_agent_task
from docuharnessx.ontology import Subject

_PREFIXES = frozenset({"component", "tech", "artifact", "topic"})


def _subject(raw: str) -> Subject:
    return Subject.parse(raw, _PREFIXES)


def _blueprint() -> CompositionBlueprint:
    """A blueprint with distinct, recognizable text (mirrors task_prompt tests)."""
    key_message = "Extend: the fastest path is the short sequence below."
    return CompositionBlueprint(
        segment_key="platform-dev__extend__abc123",
        roles=("platform-dev",),
        intent="extend",
        subjects=(_subject("component:cli"),),
        title="Extend: the CLI",
        scqa=SCQAOpener(
            situation="You are Platform Developer working with the CLI.",
            complication="Reaching the Extend goal for the CLI is unclear.",
            question="How do you Extend the CLI on the shortest path?",
            answer=key_message,
        ),
        key_message=key_message,
        chunks=(
            Chunk(
                heading="Orientation",
                points=("Who this is for: Platform Developer.", "Goal: Extend the CLI."),
            ),
            Chunk(
                heading="Extend: the core path",
                points=("Start with the CLI.", "Follow the fast path to Extend."),
            ),
        ),
        fast_path=(
            "Locate the CLI.",
            "Run the smallest action that makes progress toward Extend.",
            "Verify you reached first success, then stop.",
        ),
        andragogy=True,
        evidence_anchors=(
            EvidenceAnchor(
                kind="entrypoint", detail="cmd/main.go", note="entrypoint: main (app)"
            ),
            EvidenceAnchor(kind="component", detail="internal/auth", note="component: auth"),
        ),
        role_labels=("Platform Developer",),
        intent_label="Extend",
    )


def _text(task: BaseTask) -> str:
    """The task's natural-language description as a single string."""
    description = task.description
    if isinstance(description, str):
        return description
    parts: list[str] = []
    for block in description:
        if isinstance(block, dict):
            parts.append(str(block.get("text", "")))
        else:
            parts.append(str(getattr(block, "text", "")))
    return "\n".join(parts)


# A distinctive, multi-word guidance phrase a naive echo would surface verbatim.
_GUIDANCE = "Emphasise the retry-and-backoff behaviour of the auth client."


# --------------------------------------------------------------------------- #
# (a) guidance="" is byte-identical to today's task (backward compatible)      #
# --------------------------------------------------------------------------- #


def test_guidance_keyword_defaults_to_empty() -> None:
    # build_agent_task accepts the keyword and defaults it to "" so existing callers
    # (which pass no guidance) reproduce today's behaviour.
    bp = _blueprint()
    default = build_agent_task(bp, repo_path="/repo")
    explicit_empty = build_agent_task(bp, repo_path="/repo", guidance="")
    assert _text(default) == _text(explicit_empty)


def test_empty_guidance_is_byte_identical_to_no_guidance() -> None:
    # The whole point of the default "": the rendered description must be byte-identical
    # to today's task so every existing composition/writer test stays green.
    bp = _blueprint()
    baseline = _text(build_agent_task(bp, repo_path="/repo"))
    with_empty = _text(build_agent_task(bp, repo_path="/repo", guidance=""))
    assert with_empty == baseline
    # And a non-empty guidance must actually CHANGE the description (it is applied).
    with_guidance = _text(build_agent_task(bp, repo_path="/repo", guidance=_GUIDANCE))
    assert with_guidance != baseline


# --------------------------------------------------------------------------- #
# (b) non-empty guidance reaches the rendered description, near the mission     #
# --------------------------------------------------------------------------- #


def test_non_empty_guidance_reaches_the_description() -> None:
    bp = _blueprint()
    text = _text(build_agent_task(bp, repo_path="/repo", guidance=_GUIDANCE))
    # The guidance text is carried into the task so the agent can apply it.
    assert _GUIDANCE in text


def test_guidance_is_an_applied_author_instruction() -> None:
    bp = _blueprint()
    text = _text(build_agent_task(bp, repo_path="/repo", guidance=_GUIDANCE))
    lowered = text.lower()
    # Rendered as an APPLIED author-guidance instruction (mirroring the role/COBESY
    # anti-echo wording): it directs WHAT to write/emphasise and forbids echoing.
    assert "apply" in lowered
    assert "do not quote" in lowered or "do not name" in lowered


def test_guidance_sits_near_the_mission() -> None:
    bp = _blueprint()
    text = _text(build_agent_task(bp, repo_path="/repo", guidance=_GUIDANCE))
    guidance_at = text.index(_GUIDANCE)
    # "near the mission": the applied-guidance line appears before the grounding/scope
    # block (the read-only repo root line), not buried in the output requirements.
    repo_root_at = text.index("The repository source tree is rooted read-only at")
    assert guidance_at < repo_root_at


# --------------------------------------------------------------------------- #
# (c) the guidance is APPLIED, never ECHOED (no heading/section for it)         #
# --------------------------------------------------------------------------- #


def test_guidance_is_not_rendered_as_a_heading_or_section() -> None:
    bp = _blueprint()
    text = _text(build_agent_task(bp, repo_path="/repo", guidance=_GUIDANCE))
    for line in text.splitlines():
        stripped = line.strip()
        # The verbatim guidance must never be a standalone heading/section line:
        # not a Markdown heading, not a numbered/bulleted section title that is just
        # the guidance text, and not the guidance verbatim on its own line.
        assert stripped != _GUIDANCE
        assert stripped != f"# {_GUIDANCE}"
        assert stripped != f"## {_GUIDANCE}"
        assert stripped != f"- {_GUIDANCE}"
        # When the guidance appears, it is embedded inside the applied-instruction
        # sentence, never as a bare heading: the line carrying it must also carry
        # the applying/forbidding instruction words.
        if _GUIDANCE in line:
            assert "apply" in line.lower()
