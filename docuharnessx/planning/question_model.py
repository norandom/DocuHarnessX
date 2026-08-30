"""Frozen question-plan values the QuestionPlanner emits.

This module is the **model boundary** of the explore-first question planner
(task 1.1). It defines ``QuestionKind``, ``Question``, ``QuestionPlan``, the
documented ``{kind}:{slug}`` id helper, and the named caps. Planner logic
(``plan_questions``) lives in a later task.

Design constraints (design "Planning — QuestionPlanner" / "Data Models")
------------------------------------------------------------------------
* Every value object is a ``@dataclass(frozen=True)`` so instances compare by
  value and cannot be mutated.
* Collection fields are ``tuple[...]`` (never ``list``) so instances are
  deeply immutable and hashable.
* ``Question.id`` is ``{kind}:{slug}`` — a filesystem-safe slug with no reader
  role or intent (Req 2.4). The retired Role × Intent delimiter
  ``{role}__{intent}`` / ``{role}__{intent}__{digest}`` (e.g.
  ``developer__extend__abc``) is rejected by :func:`make_question_id`. Dunder
  module basenames such as ``__main__.py`` are not that shape.
* Caps are named constants only; applying them is planner work (task 2.1).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

__all__ = [
    "MAX_COMPONENT_QUESTIONS",
    "MAX_QUESTIONS",
    "Question",
    "QuestionKind",
    "QuestionPlan",
    "make_question_id",
]

#: Documented maximum number of questions per run (design "QuestionPlanner").
MAX_QUESTIONS: int = 12

#: Documented maximum number of component questions per run.
MAX_COMPONENT_QUESTIONS: int = 6

_UNSAFE_SLUG_CHARS = re.compile(r"[^a-z0-9._-]+")
_REPEATED_HYPHENS = re.compile(r"-{2,}")


class QuestionKind(StrEnum):
    """Software-question kinds derived from repository scan signals."""

    STARTUP = "startup"
    COMPONENT = "component"
    PUBLIC_SURFACE = "public_surface"
    BUILD = "build"
    TESTS = "tests"


def _basename(value: str) -> str:
    return value.replace("\\", "/").rsplit("/", 1)[-1].strip()


def _reject_role_intent_shape(value: str) -> None:
    """Reject the retired ``{role}__{intent}`` / ``{role}__{intent}__{digest}`` shape.

    ``__`` is the retired page-identity *delimiter* between non-empty tokens
    (Req 2.4). A leading or trailing dunder on a basename (``__main__.py``,
    ``__init__.py``) is not that shape.
    """
    parts = _basename(value).split("__")
    if not (2 <= len(parts) <= 3 and all(parts)):
        return
    raise ValueError(
        "question ids are '{kind}:{slug}' and must not use a reader-role "
        "combined with an intent (retired shape '{role}__{intent}' / "
        "'{role}__{intent}__{digest}', e.g. 'developer__extend__abc'); "
        f"got {value!r}"
    )


def _filesystem_safe_slug(source: str) -> str:
    """Basename of ``source``, lowercased, with unsafe characters replaced.

    Underscores and dots are already filesystem-safe, so dunder module names
    stay intact. Only sanitization hyphens are stripped from the ends.
    """
    name = _basename(source).lower()
    name = _UNSAFE_SLUG_CHARS.sub("-", name)
    name = _REPEATED_HYPHENS.sub("-", name)
    return name.strip("-")


def make_question_id(kind: QuestionKind | str, slug_source: str) -> str:
    """Build a ``{kind}:{slug}`` id from a kind and a subject/path source.

    The slug is the filesystem-safe basename of ``slug_source``. The retired
    Role × Intent delimiter ``{role}__{intent}`` / ``{role}__{intent}__{digest}``
    (e.g. ``developer__extend__abc``) is rejected (Req 2.4). Dunder module
    basenames such as ``__main__.py`` are kept.
    """
    _reject_role_intent_shape(slug_source)
    kind_value = QuestionKind(kind)
    slug = _filesystem_safe_slug(slug_source)
    if not slug:
        raise ValueError(
            f"question slug is empty after sanitizing {slug_source!r}"
        )
    _reject_role_intent_shape(slug)
    return f"{kind_value}:{slug}"


@dataclass(frozen=True)
class Question:
    """One planned software question: the page unit (Req 2.2).

    ``id`` is ``{kind}:{slug}`` and must not be a reader-role combined with
    an intent. ``evidence_paths`` are repo-relative files the writer should
    inspect first. The record carries no ``roles`` or ``intent`` field.
    """

    id: str
    kind: QuestionKind
    title: str
    subject_name: str
    evidence_paths: tuple[str, ...]


@dataclass(frozen=True)
class QuestionPlan:
    """Ordered questions for one repository (the QuestionPlanner output)."""

    questions: tuple[Question, ...]
    repo_path: str
