"""The deterministic judge-prompt assembler (quality-review-gate task 2.2).

This module owns the *Judge Prompt Assembler* boundary of the Wave 2
``quality-review-gate`` review core: :func:`build_request` turns one frozen
:class:`~docuharnessx.review.model.SegmentCriteria` into the ``(messages, tools)`` model
request the gated per-segment judge step (task 3.1) issues (design "Judge Prompt
Assembler"; Req 4.1, 4.2, 4.3, 4.4).

It is a **pure function**: no model, no I/O, no global state, never mutates its input
(Req 4.1). Every byte of the request is derived from the supplied ``SegmentCriteria``, so
equal criteria produce an equal request (Req 4.4) and the gate's structure/grounding is
fully unit-testable without any credentials.

The request has two parts, mirroring
:func:`docuharnessx.composition.prompt.build_request` and
:func:`docuharnessx.planning.relevance._build_request`:

* A **system prompt** — a fixed, model-agnostic instruction telling the judge to act as an
  objective COBESY evaluator, score *each* named criterion in ``[0,1]`` with a one-line
  reason, and return an overall pass/fail — all inside a **strict JSON object** with no
  prose or markdown outside it. The instructed JSON shape reuses the
  :class:`harnessx.processors.evaluation`'s ``LLMJudgeEvaluator`` discipline
  (``{"score", "passed", "reason"}``) lifted to the per-criterion level
  (``{"criteria": {<name>: {...}}, "passed": ..., "reason": ...}``), so the deterministic
  :mod:`docuharnessx.review.parse` can decode it (Req 4.3).
* A **user message** — a compact, deterministic brief built **only** from the supplied
  criteria-derived facts: the segment ``title``/``summary``/``body``, the role/intent
  context derived from the loaded vocabulary's labels/descriptions (the
  :class:`~docuharnessx.review.model.RoleContext` records), the named COBESY criteria, and
  the evidence anchors (``kind``/``detail``/``note``). It never carries unrelated
  repository file *contents* — only the facts the criteria builder already distilled
  (Req 4.2).

No tools are offered (``tools == []``): the judgement is a single-shot call, not an
agentic loop, exactly as the planner's relevance hook and the writer's prose step. The
:class:`harnessx.core.events.Message` type is imported **lazily behind a plain-dict
fallback** so the pure review core never hard-depends on the harness at import time
(design "Judge Prompt Assembler"; mirrors :mod:`docuharnessx.composition.prompt`).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # frozen seam consumed verbatim — typing-only import.
    from docuharnessx.review.model import RoleContext, SegmentCriteria

__all__ = ["build_request"]


#: A compact, model-agnostic system instruction. It frames the judge as an objective
#: COBESY evaluator, pins the per-criterion scoring rule (a ``[0,1]`` score plus a
#: one-line reason and an explicit pass/fail flag for each named criterion), the overall
#: pass/fail flag, and the **strict JSON-only** output discipline reused from
#: :class:`harnessx.processors.evaluation`'s ``LLMJudgeEvaluator`` (no markdown, no prose
#: outside the JSON object) lifted to the per-criterion level. It is a constant so the
#: request is deterministic; the per-segment specifics live in the user brief (Req 4.1,
#: 4.3). The instructed shape is exactly what :mod:`docuharnessx.review.parse` decodes.
_SYSTEM_PROMPT = (
    "You are an objective COBESY documentation quality evaluator (a judge). "
    "You are given one documentation segment and the named quality criteria it must "
    "meet. Judge the segment against each criterion strictly and independently.\n"
    "For EACH named criterion, assign:\n"
    "- a score, a float from 0 to 1 (0 worst, 1 best);\n"
    "- a passed flag (true or false);\n"
    "- a reason, one short line justifying the score.\n"
    "Then give an overall pass/fail flag (passed true or false) and a one-line overall "
    "reason. "
    "Judge only against the criteria and the supplied evidence anchors; do not invent "
    "repository facts, file contents, commands, or names that are not given.\n"
    "Respond with a single JSON object only — no markdown, no prose outside the JSON:\n"
    '{"criteria": {"<criterion name>": {"score": <float 0..1>, '
    '"passed": <true|false>, "reason": "<one line>"}}, '
    '"passed": <true|false>, "reason": "<one line>"}'
)


def build_request(
    criteria: "SegmentCriteria",
) -> tuple[list[Any], list[Any]]:
    """Build the deterministic ``(messages, tools)`` judge request from a criteria context.

    Pure and model-free (Req 4.1): assembles the fixed COBESY-evaluator system instruction
    (the per-criterion strict-JSON scoring contract) plus a compact user brief rendered
    **only** from ``criteria``-derived facts (the segment title/summary/body, the
    role/intent vocabulary context, the named criteria, and the evidence anchors). No
    unrelated repository file contents are included (Req 4.2). The
    :class:`harnessx.core.events.Message` type is imported lazily with a plain-dict
    fallback so the core never hard-depends on the harness at import time.

    Args:
        criteria: The deterministic per-segment
            :class:`~docuharnessx.review.model.SegmentCriteria` for one written segment.

    Returns:
        A ``(messages, tools)`` pair. ``messages`` is a system message followed by a user
        message (HarnessX ``Message`` objects when available, else plain dicts); ``tools``
        is always ``[]`` (single-shot judgement, not an agentic loop). Equal criteria
        yield an equal request (Req 4.4).

    Invariants: never consults a model; never mutates ``criteria``.
    """
    brief = _render_brief(criteria)
    messages = _make_messages(_SYSTEM_PROMPT, brief)
    return messages, []


def _make_messages(system: str, user: str) -> list[Any]:
    """Build the message list as HarnessX ``Message`` objects, dict fallback.

    Imports :class:`harnessx.core.events.Message` lazily and behind a fallback so the pure
    review core never hard-depends on the harness at import time (mirrors
    :func:`docuharnessx.composition.prompt._make_messages` /
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


def _render_brief(criteria: "SegmentCriteria") -> str:
    """Render the compact, deterministic user brief from criteria-derived facts only.

    Read-only over ``criteria`` — emits the segment title/summary/body, the role/intent
    context from the loaded vocabulary (each :class:`RoleContext`'s label + description,
    never a hardcoded axis), the named COBESY criteria to score, and the evidence anchors
    (``kind``/``detail``/``note``). It deliberately carries no unrelated repository file
    contents: only the facts the criteria builder already distilled (Req 4.2). Pure:
    returns a string and never mutates ``criteria``.
    """
    lines: list[str] = [
        f"Segment id: {criteria.segment_id}",
        f"Title: {criteria.title}",
        f"Summary: {criteria.summary}",
        "",
        "Audience roles (judge role-fit against these):",
    ]
    for role in criteria.roles:
        lines.append(f"- {_render_role(role)}")
    lines.append(f"Intent: {_render_role(criteria.intent)}")

    lines.append("")
    lines.append("Criteria to score (each on a 0..1 scale with a one-line reason):")
    for name in criteria.criteria:
        lines.append(f"- {name}")

    lines.append("")
    lines.append("Evidence anchors (judge falsifiability/evidence only against these):")
    if criteria.evidence_anchors:
        for anchor in criteria.evidence_anchors:
            note = f" — {anchor.note}" if anchor.note else ""
            lines.append(f"- {anchor.kind}: {anchor.detail}{note}")
    else:
        lines.append("- (none supplied; do not invent repository facts)")

    lines.append("")
    lines.append("Segment body to judge:")
    lines.append(criteria.body)

    return "\n".join(lines)


def _render_role(role: "RoleContext") -> str:
    """Render one role/intent vocabulary term: label plus its description when present.

    Uses the loaded-vocabulary ``label``/``description`` verbatim (Req 3.2, 10.2), never a
    hardcoded axis; the machine ``id`` is included so the judge can tie the term back to
    the segment. An empty description degrades to just the label (Req: total over absent
    descriptions). Pure.
    """
    suffix = f" — {role.description}" if role.description else ""
    return f"{role.label} (id={role.id}){suffix}"
