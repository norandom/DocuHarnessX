"""The deterministic agentic task-prompt assembler (agentic-codebase-writer task 2.1).

``docuharnessx.composition.task_prompt`` owns the *task_prompt* boundary of the Wave 2.5
``agentic-codebase-writer``: :func:`build_agent_task` turns one frozen
:class:`~docuharnessx.composition.model.CompositionBlueprint` plus the target-repo path
into a bounded agentic :class:`harnessx.core.harness.BaseTask` — the task the per-segment
HarnessX agent runs over a read-only ``Workspace`` rooted at the repository (design
"build_agent_task"; Req 3.3, 4.1, 4.2, 4.3, 4.6).

It is a **pure function**: no model, no I/O, no global state, never mutates its input
(Req 4.1). Every byte of the task ``description`` is derived from the blueprint, so equal
``(blueprint, repo_path, caps)`` inputs produce a byte-identical task — determinism lives
in the orchestration, the agent's freedom is bounded by the structure gate downstream.

Scope is derived **internally from the blueprint**, never from a separate scope argument:

* the **evidence files** the agent starts from are ``blueprint.evidence_anchors`` (each
  anchor's ``kind``/``detail``/``note``, where ``detail`` is the repo-relative path the
  planner cited);
* the **subject phrases** are ``blueprint.subjects`` (each :class:`~docuharnessx.ontology.Subject`'s
  ``local`` name).

The task instructs the agent to: start from those evidence files, read the *real* source
with the built-in tools, honor the blueprint's COBESY structure (the SCQA opener -> the
Minto lead-with-conclusion -> the working-memory chunks -> the REDUCE-barrier fast path;
andragogy/expert framing when ``blueprint.andragogy`` is set), include at least one valid
Mermaid diagram (a supported diagram type, vertical orientation, short node labels, valid
arrow grammar), and cite real ``file:line`` sources for at least ``min_citations`` distinct
files (Req 4.1, 4.2, 4.3). All audience/intent framing derives from the blueprint's
loaded-``Vocabulary`` labels (``role_labels``/``intent_label``); the assembler hardcodes no
project role/intent/subject literal (Req 4.6).

The bounded caps (``max_steps``, ``max_cost_usd``, ``token_budget``) default to the shared
writer budgets from :mod:`docuharnessx.composition.budgets` so every per-segment run is
bounded by the same auditable values (Req 5.1); the caller (the
:class:`~docuharnessx.composition.agent.AgenticProseRunner`) may override them per call.
The :class:`harnessx.core.harness.BaseTask` type is imported lazily behind a plain-data
fallback so the pure composition core never hard-depends on the harness at import time
(mirroring :mod:`docuharnessx.composition.prompt`).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from docuharnessx.composition.budgets import (
    MIN_CITED_FILES,
    WRITER_MAX_COST_USD,
    WRITER_MAX_STEPS,
    WRITER_TOKEN_BUDGET,
)

if TYPE_CHECKING:  # frozen seam consumed verbatim — typing-only import.
    from docuharnessx.composition.model import CompositionBlueprint

__all__ = ["build_agent_task"]


def build_agent_task(
    blueprint: "CompositionBlueprint",
    *,
    repo_path: str,
    min_citations: int = MIN_CITED_FILES,
    max_steps: int = WRITER_MAX_STEPS,
    max_cost_usd: float = WRITER_MAX_COST_USD,
    token_budget: int = WRITER_TOKEN_BUDGET,
) -> Any:
    """Build the deterministic, bounded agentic :class:`BaseTask` for one segment.

    Pure and model-free (Req 4.1): assembles a single natural-language ``description`` from
    ``blueprint``-derived facts only — the loaded-``Vocabulary`` role/intent labels, the
    title, the SCQA moves, the Minto key message, the working-memory chunks, the
    REDUCE-barrier fast path, the andragogy flag, the evidence anchors (the files to start
    from), and the subject phrases — and binds the bounded caps onto the task. The scope is
    derived internally from ``blueprint.evidence_anchors`` + ``blueprint.subjects`` (Req
    3.3); there is no separate scope argument. No hardcoded role/intent/subject literal is
    emitted (Req 4.6).

    Args:
        blueprint: The deterministic COBESY blueprint for one planned segment. Read-only;
            never mutated.
        repo_path: The target-repository path the agent's read-only ``Workspace`` roots at,
            named in the task so the agent knows the source tree it explores.
        min_citations: The minimum number of distinct ``file:line`` source files the agent
            must cite; defaults to :data:`MIN_CITED_FILES`, the same threshold the
            structure gate enforces (Req 4.3, 4.4).
        max_steps: ``BaseTask.max_steps`` cap for this run; defaults to
            :data:`WRITER_MAX_STEPS` (Req 5.1).
        max_cost_usd: ``BaseTask.max_cost_usd`` cap; defaults to
            :data:`WRITER_MAX_COST_USD` (Req 5.1).
        token_budget: ``BaseTask.token_budget`` cap; defaults to
            :data:`WRITER_TOKEN_BUDGET` (Req 5.1).

    Returns:
        A :class:`harnessx.core.harness.BaseTask` (a plain-data fallback when the harness is
        unavailable at import time) carrying the bounded caps and the scoped, COBESY-seeded
        description that demands a Mermaid diagram and ``file:line`` citations. Equal inputs
        yield a byte-identical description and equal caps (Req 4.1, task 2.1 determinism).

    Invariants: never consults a model; never mutates ``blueprint``; deterministic.
    """
    description = _render_description(
        blueprint, repo_path=repo_path, min_citations=min_citations
    )
    return _make_task(
        description,
        max_steps=max_steps,
        max_cost_usd=max_cost_usd,
        token_budget=token_budget,
    )


def _make_task(
    description: str,
    *,
    max_steps: int,
    max_cost_usd: float,
    token_budget: int,
) -> Any:
    """Build the :class:`BaseTask`, importing it lazily behind a plain-data fallback.

    Imports :class:`harnessx.core.harness.BaseTask` lazily and behind a fallback so the
    pure composition core never hard-depends on the harness at import time (mirroring
    :func:`docuharnessx.composition.prompt._make_messages`). The fallback is a tiny frozen
    record carrying the same ``description``/``max_steps``/``max_cost_usd``/``token_budget``
    fields the runner reads, so the assembler stays unit-testable without the harness.
    """
    try:
        from harnessx.core.harness import BaseTask

        return BaseTask(
            description=description,
            max_steps=max_steps,
            token_budget=token_budget,
            max_cost_usd=max_cost_usd,
        )
    except Exception:  # pragma: no cover - exercised only without the harness installed
        return _FallbackTask(
            description=description,
            max_steps=max_steps,
            token_budget=token_budget,
            max_cost_usd=max_cost_usd,
        )


# --------------------------------------------------------------------------- #
# Plain-data fallback (harness-free import)                                    #
# --------------------------------------------------------------------------- #


class _FallbackTask:
    """A minimal stand-in for :class:`BaseTask` when the harness is unavailable.

    Carries only the fields the agentic runner reads (``description``/``max_steps``/
    ``max_cost_usd``/``token_budget``), so the pure assembler is importable and testable
    without HarnessX. Production always builds a real ``BaseTask``.
    """

    __slots__ = ("description", "max_steps", "token_budget", "max_cost_usd")

    def __init__(
        self,
        *,
        description: str,
        max_steps: int,
        token_budget: int,
        max_cost_usd: float,
    ) -> None:
        self.description = description
        self.max_steps = max_steps
        self.token_budget = token_budget
        self.max_cost_usd = max_cost_usd


# --------------------------------------------------------------------------- #
# Deterministic description rendering (blueprint-derived facts only)            #
# --------------------------------------------------------------------------- #


def _render_description(
    blueprint: "CompositionBlueprint",
    *,
    repo_path: str,
    min_citations: int,
) -> str:
    """Render the bounded agentic task description from blueprint-derived facts only.

    Read-only over ``blueprint``: emits the mission, the read-only repo root, the evidence
    files to start from (the scope's anchors), the subject phrases, the COBESY structure
    the agent must honor (SCQA -> Minto lead -> working-memory chunks -> REDUCE fast path,
    plus the andragogy framing when flagged), and the hard output requirements (at least
    one valid Mermaid diagram and at least ``min_citations`` distinct ``file:line``
    citations). All audience/intent framing is the loaded-``Vocabulary`` labels carried by
    the blueprint (Req 4.6). Pure: returns a string and never mutates ``blueprint``.
    """
    role_phrase = _join(blueprint.role_labels) or "the reader"
    intent_label = blueprint.intent_label

    lines: list[str] = [
        # Mission — what the agent produces and for whom (vocabulary labels only). The role is
        # a TARGETING signal, never reader-facing content: the page is written so the audience
        # finds what they need, but the role itself must not appear in the prose.
        "You are writing one documentation segment for a software repository by "
        "exploring its real source code.",
        f"Write it FOR this audience — their role shapes which concerns, depth, and tasks you "
        f"cover — but NEVER state or address the role in the page itself: do not write 'You "
        f"are a {role_phrase}', 'As a {role_phrase}', 'this is for {role_phrase}s', or a "
        f"'who this is for' line. Audience: {role_phrase}.",
        f"Intent: {intent_label}.",
        f"Title: {blueprint.title}",
        f"Expert audience (assume prior knowledge, skip basics): "
        f"{'yes' if blueprint.andragogy else 'no'}",
        "",
        # Grounding — the read-only repo and the tools.
        f"The repository source tree is rooted read-only at: {repo_path}",
        "Read the real source with the read, grep, glob, and bash tools. Ground every "
        "claim in code you have actually read; do not invent repository facts.",
        "Work within a limited budget: read the evidence files below and at most a few "
        "files they directly reference — do NOT browse the whole repository. As soon as you "
        "have read enough to ground the segment (a handful of files is enough), STOP "
        "exploring and write the complete final answer. Your final message must BE the "
        "finished Markdown body — do not end on a tool call and do not promise to write it "
        "later, or the segment is discarded.",
        "",
        # Scope — the evidence files to start from (from blueprint.evidence_anchors).
        "Start from these evidence files (read them first, then follow references as "
        "needed to ground the segment):",
    ]

    if blueprint.evidence_anchors:
        for anchor in blueprint.evidence_anchors:
            note = f" — {anchor.note}" if anchor.note else ""
            lines.append(f"- {anchor.kind}: {anchor.detail}{note}")
    else:
        lines.append(
            "- (no evidence files supplied; explore from the repository root and ground "
            "the segment in what you read)"
        )

    # Subjects — the subject phrases this segment is about (from blueprint.subjects).
    lines.append("")
    lines.append("This segment is about these subjects:")
    if blueprint.subjects:
        for subject in blueprint.subjects:
            lines.append(f"- {subject.local}")
    else:
        lines.append("- the project")

    # Structure guidance — an INTERNAL authoring guide. The agent fills it with natural,
    # reader-facing prose and must NOT name the authoring method in the output (user
    # directive: internal concepts like SCQA/Minto/REDUCE must not surface unless they add
    # reader value, which for a how-the-page-was-written concept they do not).
    lines.append("")
    lines.append(
        "Structure the body as follows. THIS IS AN INTERNAL AUTHORING GUIDE — follow its "
        "shape, but write natural, reader-facing prose and plain headings. Do NOT name the "
        "authoring method or its concepts anywhere in the output: never write 'COBESY', "
        "'SCQA', 'Minto', 'REDUCE', 'REDUCE barrier', 'working memory', or 'andragogy', and "
        "do not use 'Situation/Complication/Question/Answer' as headings. The reader cares "
        "about the software, not how the page was written."
    )
    lines.append(
        "1. Open by setting the context and the question this page answers, then give the "
        "answer up front — as flowing prose, not labelled parts:"
    )
    lines.append(f"   - context: {blueprint.scqa.situation}")
    lines.append(f"   - problem: {blueprint.scqa.complication}")
    lines.append(f"   - question it raises: {blueprint.scqa.question}")
    lines.append(f"   - answer to lead with: {blueprint.scqa.answer}")
    lines.append("2. State that key message first, then support it:")
    lines.append(f"   key message: {blueprint.key_message}")
    lines.append(
        "3. Cover these topics, in order — use them as the body's section headings "
        "(rephrase into plain, descriptive titles as needed):"
    )
    for chunk in blueprint.chunks:
        lines.append(f"   - {chunk.heading}")
        for point in chunk.points:
            lines.append(f"     - {point}")
    lines.append(
        "4. End with a short get-started section (a plain heading such as 'Quick start' or "
        "'Getting started') giving the shortest ordered sequence of steps to first success:"
    )
    for index, step in enumerate(blueprint.fast_path, start=1):
        lines.append(f"   {index}. {step}")
    if blueprint.andragogy:
        lines.append(
            "The audience is expert: respect their prior knowledge and frame the segment "
            "around the problem they are solving rather than basics (do not name this)."
        )

    # Hard output requirements — Mermaid + file:line citations (gated downstream).
    lines.append("")
    lines.append("Hard output requirements (the body is rejected if these are not met):")
    lines.append(
        "- Include at least one Mermaid diagram that visualises the code you read "
        "(architecture, call flow, or data model). It MUST be a fenced block whose opening "
        "line is exactly ```mermaid and whose very FIRST line inside the fence is the diagram "
        "type — no title, comment, or prose before that type line. It must PARSE with no "
        "Mermaid syntax error and render in the browser. Example of the exact required shape:"
    )
    lines.append("```mermaid")
    lines.append("graph TD")
    lines.append('    A["Application"] --> B["Engine.start()"]')
    lines.append('    B --> C["load_config()"]')
    lines.append("```")
    lines.append(
        "Mermaid syntax rules (follow them exactly so the diagram renders): use `graph TD` "
        "(top-down) or another supported type (`sequenceDiagram`, `classDiagram`, "
        "`erDiagram`, `stateDiagram`). Node IDs are short and alphanumeric (A, B, Engine) "
        "with no spaces and are never a reserved word (end, graph, class, state, subgraph). "
        "Put ALL human text in double-quoted labels — `A[\"Engine.start()\"]` — so dots, "
        "parentheses, colons, slashes and spaces are safe; never put those characters in a "
        "label without the surrounding quotes. Use only valid edges (`A --> B`, or a labelled "
        "`A -->|\"loads\"| B`). Keep it under ~10 nodes, one diagram, no HTML, no markdown, "
        "and no backticks inside the fence. The diagram is required — a body without a valid, "
        "parseable ```mermaid block is rejected."
    )
    lines.append(
        f"- Cite real `file:line` sources for at least {min_citations} distinct source "
        f"files. Write each citation in exactly the `path:line` form — a repo-relative "
        f"path, a colon, and a line number, e.g. `src/app.py:42` or `engine.py:16` — inline "
        f"in the prose. Do NOT write 'line 42 of app.py' or `app.py#L42`; only the "
        f"`path:line` form counts, and fewer than {min_citations} distinct files is "
        f"rejected."
    )
    lines.append(
        "Return only the Markdown body of the segment as your final message — the Mermaid "
        "diagram and the `path:line` citations must appear in it verbatim."
    )

    return "\n".join(lines)


def _join(labels: tuple[str, ...]) -> str:
    """Join axis labels into a deterministic comma-separated phrase."""
    return ", ".join(labels)
