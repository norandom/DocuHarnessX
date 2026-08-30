"""Unit tests for the frozen question-plan types (task 1.1).

Pins the QuestionPlanner model boundary: ``QuestionKind``, ``Question``,
``QuestionPlan``, the documented ``{kind}:{slug}`` id helper, and the named
caps. Planner logic (``plan_questions``) is out of scope.

Observable completion (tasks.md 1.1 / Req 2.2, 2.4): equal constructed inputs
compare equal; a sample startup question round-trips; the id helper rejects a
role-intent shaped id.
"""

from __future__ import annotations

import dataclasses

import pytest

from docuharnessx.planning.question_model import (
    MAX_COMPONENT_QUESTIONS,
    MAX_QUESTIONS,
    Question,
    QuestionKind,
    QuestionPlan,
    make_question_id,
)


def _startup_question() -> Question:
    return Question(
        id=make_question_id(QuestionKind.STARTUP, "app.py"),
        kind=QuestionKind.STARTUP,
        title="How does this program start?",
        subject_name="app.py",
        evidence_paths=("app.py", "config.py"),
    )


def _component_question() -> Question:
    return Question(
        id=make_question_id(QuestionKind.COMPONENT, "engine"),
        kind=QuestionKind.COMPONENT,
        title="What does engine do?",
        subject_name="engine",
        evidence_paths=("engine.py",),
    )


def _plan(*, questions: tuple[Question, ...] | None = None) -> QuestionPlan:
    return QuestionPlan(
        questions=(_startup_question(),) if questions is None else questions,
        repo_path="/repo",
    )


# --------------------------------------------------------------------------- #
# Question kinds and caps                                                      #
# --------------------------------------------------------------------------- #


def test_question_kinds_are_the_documented_set() -> None:
    assert {kind.value for kind in QuestionKind} == {
        "startup",
        "component",
        "public_surface",
        "build",
        "tests",
    }


def test_caps_are_the_documented_constants() -> None:
    assert MAX_QUESTIONS == 12
    assert MAX_COMPONENT_QUESTIONS == 6


# --------------------------------------------------------------------------- #
# Sample startup question round-trip (Req 2.2 page-unit identity)              #
# --------------------------------------------------------------------------- #


def test_startup_question_round_trips() -> None:
    original = _startup_question()
    assert original.id == "startup:app.py"
    assert original.kind is QuestionKind.STARTUP
    assert original.title == "How does this program start?"
    assert original.subject_name == "app.py"
    assert original.evidence_paths == ("app.py", "config.py")

    rebuilt = Question(**dataclasses.asdict(original))
    assert rebuilt == original
    assert rebuilt.id == make_question_id(original.kind, original.subject_name)


def test_question_field_set_has_no_role_or_intent() -> None:
    fields = {field.name for field in dataclasses.fields(Question)}
    assert fields == {"id", "kind", "title", "subject_name", "evidence_paths"}


def test_question_plan_field_set() -> None:
    fields = {field.name for field in dataclasses.fields(QuestionPlan)}
    assert fields == {"questions", "repo_path"}


# --------------------------------------------------------------------------- #
# Construction, tuples, immutability, equality                                 #
# --------------------------------------------------------------------------- #


def test_question_plan_preserves_order_and_repo_path() -> None:
    plan = QuestionPlan(
        questions=(_startup_question(), _component_question()),
        repo_path="/repo",
    )
    assert plan.repo_path == "/repo"
    assert [q.kind for q in plan.questions] == [
        QuestionKind.STARTUP,
        QuestionKind.COMPONENT,
    ]
    assert isinstance(plan.questions, tuple)
    assert isinstance(plan.questions[0].evidence_paths, tuple)


def test_empty_question_plan_is_valid() -> None:
    plan = _plan(questions=())
    assert plan.questions == ()


def test_questions_from_equal_inputs_are_equal() -> None:
    assert _startup_question() == _startup_question()


def test_question_plans_from_equal_inputs_are_equal() -> None:
    assert _plan() == _plan()


def test_question_plans_differ_when_inputs_differ() -> None:
    assert _plan(questions=()) != _plan()


def test_value_objects_are_hashable() -> None:
    assert hash(_startup_question()) == hash(_startup_question())
    assert hash(_plan()) == hash(_plan())


@pytest.mark.parametrize(
    "obj, field, value",
    [
        (_startup_question(), "title", "other"),
        (_startup_question(), "id", "startup:other"),
        (_plan(), "repo_path", "/other"),
        (_plan(), "questions", ()),
    ],
)
def test_fields_are_immutable(obj: object, field: str, value: object) -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(obj, field, value)


# --------------------------------------------------------------------------- #
# Id helper: ``{kind}:{slug}``, filesystem-safe, no role-intent identity       #
# --------------------------------------------------------------------------- #


def test_make_question_id_is_kind_colon_slug() -> None:
    assert make_question_id(QuestionKind.STARTUP, "app.py") == "startup:app.py"
    assert make_question_id(QuestionKind.COMPONENT, "engine") == "component:engine"
    assert (
        make_question_id(QuestionKind.PUBLIC_SURFACE, "api")
        == "public_surface:api"
    )
    assert make_question_id(QuestionKind.BUILD, "Makefile") == "build:makefile"
    assert make_question_id(QuestionKind.TESTS, "tests") == "tests:tests"


def test_make_question_id_uses_basename_and_is_filesystem_safe() -> None:
    assert (
        make_question_id(QuestionKind.STARTUP, "src/cli/Main.py")
        == "startup:main.py"
    )
    assert (
        make_question_id(QuestionKind.COMPONENT, "My Component!")
        == "component:my-component"
    )
    assert (
        make_question_id(QuestionKind.BUILD, r"dir\\CI Workflow.yml")
        == "build:ci-workflow.yml"
    )


def test_make_question_id_rejects_role_intent_shaped_id() -> None:
    """Retired page identity was ``{role}__{intent}__{digest}``.

    The documented rejected shape is the delimiter form ``{role}__{intent}`` or
    ``{role}__{intent}__{digest}`` (e.g. ``developer__extend__abc``), not a
    leading/trailing dunder in a basename. Question ids are ``{kind}:{slug}``
    and must not include a reader role or intent.
    """
    rejected = "developer__extend__abc"
    with pytest.raises(ValueError, match=r"developer__extend__abc") as err:
        make_question_id(QuestionKind.COMPONENT, rejected)
    message = str(err.value)
    assert "kind" in message and "slug" in message
    assert "__" in message


def test_make_question_id_rejects_role_intent_pair_without_digest() -> None:
    with pytest.raises(ValueError, match=r"platform-dev__extend"):
        make_question_id(QuestionKind.PUBLIC_SURFACE, "platform-dev__extend")


def test_make_question_id_keeps_dunder_module_basenames() -> None:
    """Entrypoint/package dunder files stay in the slug (underscores + dots)."""
    assert (
        make_question_id(QuestionKind.STARTUP, "__main__.py")
        == "startup:__main__.py"
    )
    assert (
        make_question_id(QuestionKind.STARTUP, "pkg/__main__.py")
        == "startup:__main__.py"
    )
    assert (
        make_question_id(QuestionKind.COMPONENT, "__init__.py")
        == "component:__init__.py"
    )
