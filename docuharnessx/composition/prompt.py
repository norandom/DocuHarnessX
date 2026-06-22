"""The deterministic prompt assembler (cobesy-writer task 2.2).

This module owns the *Prompt Assembler* boundary of the Wave 2 ``cobesy-writer``:
:func:`build_request` turns one frozen
:class:`~docuharnessx.composition.model.CompositionBlueprint` into the ``(messages,
tools)`` model request the gated prose step (task 2.5) issues (design "Prompt Assembler";
Req 4.1, 4.2).

It is a **pure function**: no model, no I/O, no global state, never mutates its input
(Req 4.1). Every byte of the request is derived from the blueprint, so equal blueprints
produce an equal request (Req 4.5) and the writer's structure/grounding is fully
unit-testable without any credentials.

The request has two parts, mirroring :func:`docuharnessx.planning.relevance._build_request`:

* A **system prompt** — a fixed, model-agnostic instruction telling the model to honor
  the COBESY structure (the SCQA opener -> the Minto lead-with-conclusion -> the
  working-memory chunks -> the REDUCE-barrier fast path), to ground every claim in the
  supplied evidence anchors and invent no repository facts, and to return a Markdown
  ``body`` plus a short ``summary`` (Req 4.1).
* A **user message** — a compact, deterministic brief built **only** from
  blueprint-derived facts: the role/intent axis *labels*, the Minto key message, the SCQA
  moves, the chunk headings and points, the fast-path steps, the andragogy flag, and the
  evidence anchors (``kind``/``detail``/``note``). It never carries raw repository file
  *contents* — only the planner/analysis-supplied facts the blueprint already distilled
  (Req 4.2).

No tools are offered (``tools == []``): prose generation is a single-shot call, not an
agentic loop, exactly as the planner's relevance hook. The
:class:`harnessx.core.events.Message` type is imported **lazily behind a plain-dict
fallback** so the pure composition core never hard-depends on the harness at import time
(design "Prompt Assembler"; mirrors :mod:`docuharnessx.planning.relevance`).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # frozen seam consumed verbatim — typing-only import.
    from docuharnessx.composition.model import CompositionBlueprint

__all__ = ["build_request"]


#: A compact, model-agnostic system instruction. It names the COBESY moves the model must
#: honor (SCQA -> Minto lead -> working-memory chunks -> REDUCE fast path), the grounding
#: rule (use only the supplied evidence anchors; invent no repository facts), and the
#: required output (a Markdown ``body`` plus a short ``summary``). It is a constant so the
#: request is deterministic; the per-segment specifics live in the user brief (Req 4.1).
_SYSTEM_PROMPT = (
    "You are writing one documentation segment for a software repository. "
    "A deterministic planner has already chosen the segment's audience, intent, and "
    "structure; honor it exactly and add nothing it does not authorize.\n"
    "Write the body so it:\n"
    "1. Opens with the SCQA opener (Situation, Complication, Question, Answer).\n"
    "2. Leads with the conclusion (Minto): state the key message first, then support "
    "it.\n"
    "3. Groups the support into the given working-memory chunks (a short subhead plus a "
    "few points each) so the reader holds the structure at once.\n"
    "4. Ends with the REDUCE-barrier fast path: the shortest ordered sequence of steps "
    "to first success.\n"
    "Ground every claim only in the supplied evidence anchors; do not invent repository "
    "facts, file contents, commands, or names that are not given. "
    "When the brief marks the audience as expert, respect their prior knowledge and "
    "frame the segment around the problem they are solving rather than basics. "
    "Return the Markdown body and a short one-paragraph summary of it."
)


def build_request(
    blueprint: "CompositionBlueprint",
) -> tuple[list[Any], list[Any]]:
    """Build the deterministic ``(messages, tools)`` model request from a blueprint.

    Pure and model-free (Req 4.1): assembles a fixed system instruction plus a compact
    user brief rendered **only** from ``blueprint``-derived facts (axis labels, the Minto
    key message, the SCQA moves, the chunk headings/points, the fast-path steps, the
    andragogy flag, and the evidence anchors). No raw repository file contents are
    included (Req 4.2). The :class:`harnessx.core.events.Message` type is imported lazily
    with a plain-dict fallback so the core never hard-depends on the harness at import
    time.

    Args:
        blueprint: The deterministic COBESY blueprint for one planned segment.

    Returns:
        A ``(messages, tools)`` pair. ``messages`` is a system message followed by a user
        message (HarnessX ``Message`` objects when available, else plain dicts);
        ``tools`` is always ``[]`` (single-shot generation, not an agentic loop). Equal
        blueprints yield an equal request (Req 4.5).

    Invariants: never consults a model; never mutates ``blueprint``.
    """
    brief = _render_brief(blueprint)
    messages = _make_messages(_SYSTEM_PROMPT, brief)
    return messages, []


def _make_messages(system: str, user: str) -> list[Any]:
    """Build the message list as HarnessX ``Message`` objects, dict fallback.

    Imports :class:`harnessx.core.events.Message` lazily and behind a fallback so the
    pure composition core never hard-depends on the harness at import time (mirrors
    :func:`docuharnessx.planning.relevance._build_request`). The provider protocol only
    requires an iterable of message-like records, so plain dicts are an adequate fallback.
    """
    try:
        from harnessx.core.events import Message

        return [
            Message(role="system", content=system),
            Message(role="user", content=user),
        ]
    except Exception:
        return [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]


def _render_brief(blueprint: "CompositionBlueprint") -> str:
    """Render the compact, deterministic user brief from blueprint-derived facts only.

    Read-only over ``blueprint`` — emits the title, the role/intent axis *labels*, the
    andragogy flag, the SCQA moves, the Minto key message, the working-memory chunks
    (heading + points), the REDUCE fast-path steps, and the evidence anchors
    (``kind``/``detail``/``note``). It deliberately carries no raw repository file
    contents: only the facts the planner and analyzer already distilled into the blueprint
    (Req 4.2). Pure: returns a string and never mutates ``blueprint``.
    """
    lines: list[str] = [
        f"Title: {blueprint.title}",
        f"Audience (roles): {_join(blueprint.role_labels) or 'the reader'}",
        f"Intent: {blueprint.intent_label}",
        f"Expert audience (apply andragogy): {'yes' if blueprint.andragogy else 'no'}",
        "",
        "SCQA opener:",
        f"- Situation: {blueprint.scqa.situation}",
        f"- Complication: {blueprint.scqa.complication}",
        f"- Question: {blueprint.scqa.question}",
        f"- Answer: {blueprint.scqa.answer}",
        "",
        f"Key message (lead with this conclusion): {blueprint.key_message}",
        "",
        "Working-memory chunks (use as the body's sections, in order):",
    ]

    for chunk in blueprint.chunks:
        lines.append(f"- {chunk.heading}")
        for point in chunk.points:
            lines.append(f"  - {point}")

    lines.append("")
    lines.append("REDUCE-barrier fast path (the shortest sequence to first success):")
    for index, step in enumerate(blueprint.fast_path, start=1):
        lines.append(f"  {index}. {step}")

    lines.append("")
    lines.append("Evidence anchors (ground every claim only in these):")
    if blueprint.evidence_anchors:
        for anchor in blueprint.evidence_anchors:
            note = f" — {anchor.note}" if anchor.note else ""
            lines.append(f"- {anchor.kind}: {anchor.detail}{note}")
    else:
        lines.append("- (none supplied; do not invent repository facts)")

    return "\n".join(lines)


def _join(labels: tuple[str, ...]) -> str:
    """Join axis labels into a deterministic comma-separated phrase."""
    return ", ".join(labels)
