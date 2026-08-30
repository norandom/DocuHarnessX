"""Unit tests for the explore-first writer task assembler (task 2.3).

Task 2.3 (explore-first-simplification, boundary: *ExploreWriter*) adds
:func:`docuharnessx.composition.question_task.build_question_task`. The task
description is assembled from a :class:`~docuharnessx.planning.question_model.Question`
and the read-only repo root only — not a filled composition outline.

Observable completion (tasks.md 2.3 / Req 5.1, 5.4): a sample question's title
and evidence paths appear in the task; forbidden outline/slogan strings do not.
"""

from __future__ import annotations

import dataclasses

from harnessx.core.harness import BaseTask

from docuharnessx.composition.budgets import (
    WRITER_MAX_COST_USD,
    WRITER_MAX_STEPS,
    WRITER_TOKEN_BUDGET,
)
from docuharnessx.composition.question_task import build_question_task
from docuharnessx.planning.question_model import Question, QuestionKind, make_question_id

# Parent-listed outline/slogan strings that must not appear in the task (Req 5.4).
_FORBIDDEN_STRINGS: tuple[str, ...] = (
    "COBESY",
    "SCQA",
    "Minto",
    "REDUCE",
    "fastest path for",
    "Situation:",
    "Complication:",
    "key message",
    "Run the smallest action",
    "working-memory",
)


def _sample_question() -> Question:
    return Question(
        id=make_question_id(QuestionKind.COMPONENT, "engine"),
        kind=QuestionKind.COMPONENT,
        title="What does Engine do?",
        subject_name="Engine",
        evidence_paths=("engine.py", "config.py"),
    )


def _startup_question() -> Question:
    return Question(
        id=make_question_id(QuestionKind.STARTUP, "app.py"),
        kind=QuestionKind.STARTUP,
        title="How does this program start?",
        subject_name="app.py",
        evidence_paths=("app.py",),
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


# --------------------------------------------------------------------------- #
# Shape and bounded caps                                                       #
# --------------------------------------------------------------------------- #


def test_returns_base_task() -> None:
    task = build_question_task(_sample_question(), repo_path="/repo")
    assert isinstance(task, BaseTask)


def test_carries_writer_budget_caps_by_default() -> None:
    task = build_question_task(_sample_question(), repo_path="/repo")
    assert task.max_steps == WRITER_MAX_STEPS
    assert task.max_cost_usd == WRITER_MAX_COST_USD
    assert task.token_budget == WRITER_TOKEN_BUDGET


def test_caps_are_overridable() -> None:
    task = build_question_task(
        _sample_question(),
        repo_path="/repo",
        max_steps=7,
        max_cost_usd=0.11,
        token_budget=42_000,
    )
    assert task.max_steps == 7
    assert task.max_cost_usd == 0.11
    assert task.token_budget == 42_000


def test_description_is_a_nonempty_string() -> None:
    task = build_question_task(_sample_question(), repo_path="/repo")
    assert isinstance(task.description, str)
    assert task.description.strip()


# --------------------------------------------------------------------------- #
# Question + evidence + repo (Req 5.1)                                         #
# --------------------------------------------------------------------------- #


def test_sample_question_title_and_evidence_paths_appear() -> None:
    question = _sample_question()
    text = _text(build_question_task(question, repo_path="/tmp/sample-repo"))
    assert question.title in text
    assert "engine.py" in text
    assert "config.py" in text


def test_names_the_read_only_repo_root() -> None:
    text = _text(build_question_task(_sample_question(), repo_path="/tmp/sample-repo"))
    assert "/tmp/sample-repo" in text
    lowered = text.lower()
    assert "read-only" in lowered or "read only" in lowered


def test_instructs_reading_evidence_first() -> None:
    text = _text(build_question_task(_sample_question(), repo_path="/repo")).lower()
    assert "read" in text
    assert "first" in text
    assert "engine.py" in text
    assert "config.py" in text


def test_instructs_path_line_citations_and_real_symbols() -> None:
    text = _text(build_question_task(_sample_question(), repo_path="/repo"))
    lowered = text.lower()
    assert "path:line" in lowered
    assert "symbol" in lowered


def test_final_message_is_the_markdown_body() -> None:
    text = _text(build_question_task(_sample_question(), repo_path="/repo")).lower()
    assert "markdown" in text
    assert "final" in text and "body" in text


def test_empty_evidence_paths_still_assembles() -> None:
    question = Question(
        id=make_question_id(QuestionKind.BUILD, "pyproject.toml"),
        kind=QuestionKind.BUILD,
        title="How is this project built and verified?",
        subject_name="pyproject.toml",
        evidence_paths=(),
    )
    task = build_question_task(question, repo_path="/repo")
    assert isinstance(task, BaseTask)
    text = _text(task)
    assert question.title in text
    assert text.strip()


# --------------------------------------------------------------------------- #
# No filled outline / slogans / method names (Req 5.4)                         #
# --------------------------------------------------------------------------- #


def test_forbidden_outline_and_slogan_strings_are_absent() -> None:
    text = _text(build_question_task(_sample_question(), repo_path="/repo"))
    lowered = text.lower()
    for phrase in _FORBIDDEN_STRINGS:
        assert phrase.lower() not in lowered, phrase


def test_does_not_instruct_copying_an_outline() -> None:
    lowered = _text(build_question_task(_sample_question(), repo_path="/repo")).lower()
    assert "copy the outline" not in lowered
    assert "copy this outline" not in lowered
    assert "honor the outline" not in lowered
    assert "honor this outline" not in lowered
    assert "copy an outline" not in lowered


def test_prohibits_template_slogans_and_reciting_a_prewritten_outline() -> None:
    lowered = _text(build_question_task(_sample_question(), repo_path="/repo")).lower()
    assert "template slogan" in lowered
    assert "outline" in lowered


# --------------------------------------------------------------------------- #
# Determinism and purity                                                       #
# --------------------------------------------------------------------------- #


def test_byte_identical_for_equal_inputs() -> None:
    question = _sample_question()
    a = build_question_task(question, repo_path="/repo")
    b = build_question_task(question, repo_path="/repo")
    assert _text(a) == _text(b)
    assert a.max_steps == b.max_steps
    assert a.max_cost_usd == b.max_cost_usd
    assert a.token_budget == b.token_budget


def test_different_questions_produce_different_tasks() -> None:
    a = build_question_task(_sample_question(), repo_path="/repo")
    b = build_question_task(_startup_question(), repo_path="/repo")
    assert _text(a) != _text(b)
    assert _sample_question().title in _text(a)
    assert _startup_question().title in _text(b)


def test_does_not_mutate_question() -> None:
    question = _sample_question()
    before = dataclasses.asdict(question)
    build_question_task(question, repo_path="/repo")
    assert dataclasses.asdict(question) == before
