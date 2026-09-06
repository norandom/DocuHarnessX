"""Deterministic composition blueprint for one explore-first question.

COBESY is authoring infrastructure: governing idea, opening cues, a short
MECE skeleton, density budget, abstraction. The blueprint is not a Role ×
Intent outline and is not copied onto the published page.
"""

from __future__ import annotations

from dataclasses import dataclass

from docuharnessx.comprehension.signals import (
    AbstractionLevel,
    ArchitectureModel,
)
from docuharnessx.planning.question_model import Question, QuestionKind

__all__ = [
    "DensityBudget",
    "QuestionBlueprint",
    "build_question_blueprint",
]


@dataclass(frozen=True)
class DensityBudget:
    """Caps for the first screen of a question page."""

    summary_sentences: int = 2
    summary_chars: int = 280
    max_h2: int = 5


@dataclass(frozen=True)
class QuestionBlueprint:
    """Question-scoped composition plan. Equal inputs yield an equal value."""

    governing_idea: str
    audience: str
    purpose: str
    opening: tuple[str, str, str]
    skeleton: tuple[str, ...]
    abstraction: AbstractionLevel
    density: DensityBudget


_PURPOSE = "Answer the question."

_AUDIENCE = {
    AbstractionLevel.CONTEXT: "adopter",
    AbstractionLevel.CONTAINER: "operator",
    AbstractionLevel.COMPONENT: "programmer",
    AbstractionLevel.CODE: "programmer",
}

_SKELETONS: dict[QuestionKind, tuple[str, ...]] = {
    QuestionKind.STARTUP: (
        "How the program starts",
        "What runs first",
        "What that means",
        "Grounding",
    ),
    QuestionKind.COMPONENT: (
        "What this part is",
        "What it does",
        "How it fits",
        "Grounding",
    ),
    QuestionKind.PUBLIC_SURFACE: (
        "What is public",
        "How to use it",
        "How to extend it",
        "Grounding",
    ),
    QuestionKind.BUILD: (
        "How the project is built",
        "How it is verified",
        "What that implies",
        "Grounding",
    ),
    QuestionKind.TESTS: (
        "Where tests live",
        "How they run",
        "What they cover",
        "Grounding",
    ),
}

_STAKES: dict[QuestionKind, str] = {
    QuestionKind.STARTUP: "If start is wrong, nothing else on this site is trustworthy.",
    QuestionKind.COMPONENT: "Misreading this part puts later modules in the wrong place.",
    QuestionKind.PUBLIC_SURFACE: "Callers cannot extend what they cannot name.",
    QuestionKind.BUILD: "A broken build path means the documented commands will fail.",
    QuestionKind.TESTS: "Unlocated tests cannot be run or trusted as evidence.",
}


def _alnum(value: str) -> str:
    return "".join(ch for ch in value.lower() if ch.isalnum())


def _abstraction(
    question: Question,
    model: ArchitectureModel | None,
) -> AbstractionLevel:
    kind = str(question.kind)
    if kind in {"startup", "public_surface"}:
        return AbstractionLevel.CONTEXT
    if kind in {"build", "tests"}:
        return AbstractionLevel.CONTAINER
    if kind == "component" and model is not None:
        if _alnum(question.subject_name) == _alnum(model.system_name):
            return AbstractionLevel.CONTAINER
    return AbstractionLevel.COMPONENT


def _actor(model: ArchitectureModel | None) -> str:
    if model is not None:
        for node in model.nodes:
            if node.kind == "actor" and node.label:
                return node.label
    return "Operator"


def _governing_idea(question: Question) -> str:
    subject = question.subject_name.strip() or "this system"
    if question.kind == QuestionKind.STARTUP:
        return f"This program starts through {subject}."
    if question.kind == QuestionKind.COMPONENT:
        return f"{subject} is the part of the system this page explains."
    if question.kind == QuestionKind.PUBLIC_SURFACE:
        return f"The public surface is reached through {subject}."
    if question.kind == QuestionKind.BUILD:
        return f"This project is built and verified through {subject}."
    if question.kind == QuestionKind.TESTS:
        return f"Tests for this project live under {subject}."
    return f"This page answers: {question.title}"


def _happening(question: Question) -> str:
    title = question.title.strip()
    if title.endswith("?"):
        title = title[:-1].rstrip()
    return title or question.subject_name


def _skeleton(question: Question) -> tuple[str, ...]:
    heads = _SKELETONS.get(question.kind, _SKELETONS[QuestionKind.COMPONENT])
    return heads[:5]


def build_question_blueprint(
    question: Question,
    model: ArchitectureModel | None = None,
) -> QuestionBlueprint:
    """Build a frozen question blueprint. No model call. No Role × Intent."""
    abstraction = _abstraction(question, model)
    skeleton = _skeleton(question)
    return QuestionBlueprint(
        governing_idea=_governing_idea(question),
        audience=_AUDIENCE[abstraction],
        purpose=_PURPOSE,
        opening=(
            _actor(model),
            _happening(question),
            _STAKES.get(
                question.kind,
                "The reader needs one idea, not a file dump.",
            ),
        ),
        skeleton=skeleton,
        abstraction=abstraction,
        density=DensityBudget(),
    )
