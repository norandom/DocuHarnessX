"""Question-scoped composition blueprint (architect-narrative task 3)."""

from __future__ import annotations

import dataclasses

from docuharnessx.composition.blueprint_question import (
    DensityBudget,
    QuestionBlueprint,
    build_question_blueprint,
)
from docuharnessx.composition.question_task import build_question_task
from docuharnessx.comprehension.signals import (
    AbstractionLevel,
    ArchitectureModel,
    ArchitectureNode,
)
from docuharnessx.planning.question_model import Question, QuestionKind, make_question_id


def _question(
    kind: QuestionKind = QuestionKind.COMPONENT,
    slug: str = "engine",
    title: str = "What does Engine do?",
    subject: str = "Engine",
    evidence: tuple[str, ...] = ("engine.py", "config.py"),
) -> Question:
    return Question(
        id=make_question_id(kind, slug),
        kind=kind,
        title=title,
        subject_name=subject,
        evidence_paths=evidence,
    )


def _startup() -> Question:
    return _question(
        QuestionKind.STARTUP,
        "app.py",
        "How does this program start?",
        "app.py",
        ("app.py",),
    )


def _architecture(*, actor: str = "Operator", system: str = "agentic_repo") -> ArchitectureModel:
    return ArchitectureModel(
        system_name=system,
        nodes=(
            ArchitectureNode(
                id="actor:operator",
                label=actor,
                level=AbstractionLevel.CONTEXT,
                kind="actor",
            ),
            ArchitectureNode(
                id="system",
                label=system,
                level=AbstractionLevel.CONTEXT,
                kind="system",
            ),
        ),
    )


def _text(task: object) -> str:
    description = getattr(task, "description")
    if isinstance(description, str):
        return description
    return "\n".join(str(block) for block in description)


def test_blueprint_is_frozen_and_byte_stable() -> None:
    question = _question()
    first = build_question_blueprint(question)
    second = build_question_blueprint(question)
    assert first == second
    assert hash(first) == hash(second)
    assert isinstance(first, QuestionBlueprint)
    assert dataclasses.replace(first, governing_idea=first.governing_idea) == first


def test_blueprint_with_model_is_byte_stable() -> None:
    question = _question()
    model = _architecture()
    assert build_question_blueprint(question, model) == build_question_blueprint(
        question, model
    )


def test_missing_model_still_builds() -> None:
    blueprint = build_question_blueprint(_question(), None)
    assert blueprint.governing_idea
    assert blueprint.opening[0] == "Operator"
    assert blueprint.abstraction == AbstractionLevel.COMPONENT


def test_governing_idea_is_one_sentence_from_subject() -> None:
    blueprint = build_question_blueprint(_question())
    assert blueprint.governing_idea == (
        "Engine is the part of the system this page explains."
    )
    assert "path:" not in blueprint.governing_idea
    startup = build_question_blueprint(_startup())
    assert startup.governing_idea == "This program starts through app.py."


def test_opening_cues_are_actor_happening_stake() -> None:
    blueprint = build_question_blueprint(_question(), _architecture(actor="User"))
    assert blueprint.opening[0] == "User"
    assert blueprint.opening[1] == "What does Engine do"
    assert blueprint.opening[2]
    assert len(blueprint.opening) == 3


def test_skeleton_is_kind_specific_and_capped() -> None:
    for kind in QuestionKind:
        blueprint = build_question_blueprint(
            _question(kind=kind, slug=str(kind), title=f"About {kind}?")
        )
        assert 1 <= len(blueprint.skeleton) <= 5
        assert blueprint.skeleton[-1] == "Grounding"
        joined = " ".join(blueprint.skeleton).lower()
        assert "scqa" not in joined
        assert "situation" not in joined
        assert "complication" not in joined


def test_audience_and_abstraction_from_kind() -> None:
    startup = build_question_blueprint(_startup())
    assert startup.abstraction == AbstractionLevel.CONTEXT
    assert startup.audience == "adopter"
    module = build_question_blueprint(_question())
    assert module.abstraction == AbstractionLevel.COMPONENT
    assert module.audience == "programmer"
    package = build_question_blueprint(
        _question(slug="agentic_repo", subject="agentic_repo"),
        _architecture(system="agentic_repo"),
    )
    assert package.abstraction == AbstractionLevel.CONTAINER
    assert package.audience == "operator"
    build = build_question_blueprint(
        _question(
            QuestionKind.BUILD,
            "pyproject.toml",
            "How is this project built and verified?",
            "pyproject.toml",
            (),
        )
    )
    assert build.abstraction == AbstractionLevel.CONTAINER
    assert build.audience == "operator"


def test_density_budget_defaults() -> None:
    density = build_question_blueprint(_question()).density
    assert isinstance(density, DensityBudget)
    assert density.summary_sentences == 2
    assert density.summary_chars == 280
    assert density.max_h2 == 5


def test_not_role_intent_blueprint() -> None:
    blueprint = build_question_blueprint(_question())
    assert not hasattr(blueprint, "scqa")
    assert not hasattr(blueprint, "roles")
    assert not hasattr(blueprint, "intent")
    assert not hasattr(blueprint, "andragogy")
    assert not hasattr(blueprint, "key_message")


def test_task_description_contains_governing_idea_and_is_stable() -> None:
    question = _question()
    blueprint = build_question_blueprint(question)
    a = _text(build_question_task(question, repo_path="/repo"))
    b = _text(build_question_task(question, repo_path="/repo"))
    assert a == b
    assert blueprint.governing_idea in a
    assert "Grounding" in a
    assert "Do not write the words SCQA, Minto, COBESY, or andragogy" in a
    for jargon in ("Situation:", "Complication:", "key message", "working-memory"):
        assert jargon not in a
