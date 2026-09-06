"""The explore-first writer task assembled from a question, evidence, and blueprint.

This module owns the *ExploreWriter* task-prompt boundary:
:func:`build_question_task` turns one frozen question plus the read-only
repository root into a bounded :class:`harnessx.core.harness.BaseTask`. A
question-scoped composition blueprint (governing idea, opening cues, skeleton,
density, abstraction) is included as writer instructions. Those labels are not
the page to copy. Methodology names are forbidden in the published Markdown.

Caps default to the shared writer budgets. :class:`harnessx.core.harness.BaseTask`
is imported lazily behind a plain-data fallback so the assembler stays
importable without the harness.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from docuharnessx.composition.blueprint_question import (
    QuestionBlueprint,
    build_question_blueprint,
)
from docuharnessx.composition.budgets import (
    WRITER_MAX_COST_USD,
    WRITER_MAX_STEPS,
    WRITER_TOKEN_BUDGET,
)
from docuharnessx.planning.question_model import Question

if TYPE_CHECKING:
    from docuharnessx.comprehension.signals import ArchitectureModel

__all__ = ["build_question_task"]


def build_question_task(
    question: Question,
    *,
    repo_path: str,
    max_steps: int = WRITER_MAX_STEPS,
    max_cost_usd: float = WRITER_MAX_COST_USD,
    token_budget: int = WRITER_TOKEN_BUDGET,
    guidance: str = "",
    architecture: "ArchitectureModel | None" = None,
) -> Any:
    """Build the bounded explore-first :class:`BaseTask` for one question.

    Pure: the description is derived from ``question``, ``repo_path``, and an
    optional architecture model. Never mutates ``question``. Equal inputs yield
    a byte-identical description and equal caps.

    Args:
        question: The planned software question (title, subject, evidence
            paths). Read-only.
        repo_path: Target-repository path the agent's read-only workspace
            roots at.
        max_steps: ``BaseTask.max_steps`` cap; defaults to
            :data:`WRITER_MAX_STEPS`.
        max_cost_usd: ``BaseTask.max_cost_usd`` cap; defaults to
            :data:`WRITER_MAX_COST_USD`.
        token_budget: ``BaseTask.token_budget`` cap; defaults to
            :data:`WRITER_TOKEN_BUDGET`.
        architecture: Optional frozen architecture model used only to fill
            actor and package-level abstraction on the blueprint.
    """
    blueprint = build_question_blueprint(question, architecture)
    description = _render_description(
        question,
        repo_path=repo_path,
        guidance=guidance,
        blueprint=blueprint,
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
    """Build :class:`BaseTask`, importing it lazily behind a plain-data fallback."""
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


class _FallbackTask:
    """Stand-in for :class:`BaseTask` when the harness is unavailable."""

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


def _render_blueprint_block(blueprint: QuestionBlueprint) -> list[str]:
    """Writer-facing composition cues. Not copied as page labels."""
    lines = [
        "",
        "Composition (follow this; do not print these labels on the page):",
        f"Governing idea: {blueprint.governing_idea}",
        f"Audience: {blueprint.audience}",
        f"Purpose: {blueprint.purpose}",
        f"Abstraction: {blueprint.abstraction}",
        "Opening cues (write them as ordinary sentences, unlabeled):",
        f"- {blueprint.opening[0]}",
        f"- {blueprint.opening[1]}",
        f"- {blueprint.opening[2]}",
        "Section heads (at most five; use them as headings if they fit what you read):",
    ]
    for head in blueprint.skeleton:
        lines.append(f"- {head}")
    lines.extend(
        [
            (
                f"Summary: at most {blueprint.density.summary_sentences} sentences "
                f"and {blueprint.density.summary_chars} characters, with no `path:line`."
            ),
            "Put `path:line` citations under a Grounding heading, not in the opening.",
            "Do not write the words SCQA, Minto, COBESY, or andragogy anywhere "
            "in the Markdown.",
        ]
    )
    return lines


def _render_description(
    question: Question,
    *,
    repo_path: str,
    guidance: str = "",
    blueprint: QuestionBlueprint,
) -> str:
    """Render the explore-first task from the question, evidence, and blueprint."""
    lines: list[str] = [
        "You are answering one software question about a repository by reading "
        "its real source code.",
        f"Software question: {question.title}",
        f"This question is about {question.subject_name}.",
        "",
        f"The repository source tree is rooted read-only at: {repo_path}",
        "Read the real source with the read, grep, glob, and bash tools. Ground "
        "every claim in code you have actually read; do not invent repository facts.",
        "Read the evidence files below first, then follow a few files they "
        "directly reference. Do not browse the whole repository. When you have "
        "enough to answer, write the complete Markdown body.",
        "",
        "Start from these evidence files (read them first):",
    ]
    if question.evidence_paths:
        for path in question.evidence_paths:
            lines.append(f"- {path}")
    else:
        lines.append(
            "- (no evidence files supplied; explore from the repository root "
            "and ground the answer in what you read)"
        )
    lines.extend(
        [
            "",
            "Cite real source locations in `path:line` form for at least two "
            "distinct files — a repo-relative path, a colon, and a line number, "
            "e.g. `src/app.py:42`. Put those citations under a Grounding heading, "
            "not in the opening or the summary. Name concrete symbols, "
            "commands, or module identifiers that appear in the source you read; "
            "do not rely on generic words such as 'component' or 'the project'.",
            "Do not recite a pre-written outline as the page. Do not fill the body "
            "with generic template slogans. Write only what you grounded in source.",
            "",
            "Your final message must BE the finished Markdown body — do not end on "
            "a tool call and do not promise to write it later.",
        ]
    )
    lines.extend(_render_blueprint_block(blueprint))
    if guidance.strip():
        lines.extend(
            [
                "",
                "Operator guidance (apply it; do not quote it as a heading):",
                guidance.strip(),
            ]
        )
    return "\n".join(lines)
