"""Question planner: ``RepoAnalysis`` → :class:`QuestionPlan`.

This module is the **QuestionPlanner** seam (design "Planning — QuestionPlanner").
The pipeline runner always calls :func:`plan_questions` after analysis.

Planning is deterministic and model-free: repository scan signals become a
bounded list of software questions. Equal analyses yield equal plans. Empty
or signal-free analysis yields an empty plan. The function never reads a
role vocabulary.
"""

from __future__ import annotations

from collections.abc import Iterable

from docuharnessx.analysis.model import (
    BuildFile,
    CIWorkflow,
    Component,
    Entrypoint,
    PublicSymbol,
    RepoAnalysis,
    TestLayout,
)
from docuharnessx.planning.question_model import (
    MAX_COMPONENT_QUESTIONS,
    MAX_QUESTIONS,
    Question,
    QuestionKind,
    QuestionPlan,
    make_question_id,
)

__all__ = ["plan_questions"]

_STARTUP_TITLE = "How does this program start?"
_COMPONENT_TITLE = "What does {name} do?"
_PUBLIC_SURFACE_TITLE = "How is the public surface used or extended?"
_BUILD_TITLE = "How is this project built and verified?"
_TESTS_TITLE = "How are tests organized?"
_TESTS_FALLBACK_SLUG = "tests"


def _basename(path: str) -> str:
    return path.replace("\\", "/").rsplit("/", 1)[-1].strip()


def _unique_paths(paths: Iterable[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    ordered: list[str] = []
    for path in paths:
        if path and path not in seen:
            seen.add(path)
            ordered.append(path)
    return tuple(ordered)


def _question(
    kind: QuestionKind,
    slug_source: str,
    *,
    title: str,
    subject_name: str,
    evidence_paths: tuple[str, ...],
) -> Question:
    return Question(
        id=make_question_id(kind, slug_source),
        kind=kind,
        title=title,
        subject_name=subject_name,
        evidence_paths=evidence_paths,
    )


def _startup_question(entrypoints: tuple[Entrypoint, ...]) -> Question | None:
    if not entrypoints:
        return None
    first = entrypoints[0]
    slug_source = first.path.strip() or first.name.strip()
    subject_name = _basename(first.path) or first.name.strip()
    if not slug_source or not subject_name:
        return None
    return _question(
        QuestionKind.STARTUP,
        slug_source,
        title=_STARTUP_TITLE,
        subject_name=subject_name,
        evidence_paths=_unique_paths(entrypoint.path for entrypoint in entrypoints),
    )


def _component_question(component: Component) -> Question | None:
    name = component.name.strip()
    slug_source = name or component.path.strip()
    if not slug_source:
        return None
    subject_name = name or _basename(component.path) or slug_source
    return _question(
        QuestionKind.COMPONENT,
        slug_source,
        title=_COMPONENT_TITLE.format(name=subject_name),
        subject_name=subject_name,
        evidence_paths=component.representative_files,
    )


def _public_surface_question(symbols: tuple[PublicSymbol, ...]) -> Question | None:
    if not symbols:
        return None
    evidence = _unique_paths(symbol.source for symbol in symbols)
    first_source = evidence[0] if evidence else symbols[0].source
    slug_source = (
        first_source.strip() or symbols[0].name.strip() or "public_surface"
    )
    subject_name = _basename(first_source) or symbols[0].name.strip() or slug_source
    return _question(
        QuestionKind.PUBLIC_SURFACE,
        slug_source,
        title=_PUBLIC_SURFACE_TITLE,
        subject_name=subject_name,
        evidence_paths=evidence,
    )


def _build_question(
    build_files: tuple[BuildFile, ...],
    ci_workflows: tuple[CIWorkflow, ...],
) -> Question | None:
    evidence = _unique_paths(
        (
            *(build.path for build in build_files),
            *(workflow.path for workflow in ci_workflows),
        )
    )
    if not evidence:
        return None
    slug_source = evidence[0]
    return _question(
        QuestionKind.BUILD,
        slug_source,
        title=_BUILD_TITLE,
        subject_name=_basename(slug_source),
        evidence_paths=evidence,
    )


def _tests_question(layout: TestLayout) -> Question | None:
    if not layout.present:
        return None
    evidence = _unique_paths(layout.paths)
    if evidence:
        slug_source = evidence[0]
        subject_name = _basename(slug_source)
    else:
        slug_source = _TESTS_FALLBACK_SLUG
        subject_name = _TESTS_FALLBACK_SLUG
    return _question(
        QuestionKind.TESTS,
        slug_source,
        title=_TESTS_TITLE,
        subject_name=subject_name,
        evidence_paths=evidence,
    )


def plan_questions(analysis: RepoAnalysis) -> QuestionPlan:
    """Return the bounded software-question plan for ``analysis``.

    Empty or signal-free analysis yields an empty plan (Req 3.5). Named
    components are capped at :data:`MAX_COMPONENT_QUESTIONS`; extra
    component questions are dropped rather than authored as persona pages.
    The whole plan is capped at :data:`MAX_QUESTIONS`. The function never
    reads a role vocabulary (Req 3.6).
    """
    questions: list[Question] = []

    startup = _startup_question(analysis.entrypoints)
    if startup is not None:
        questions.append(startup)

    upcoming = int(bool(analysis.public_surface))
    upcoming += int(bool(analysis.build_files or analysis.ci_workflows))
    upcoming += int(analysis.tests.present)
    component_budget = min(
        MAX_COMPONENT_QUESTIONS,
        max(0, MAX_QUESTIONS - len(questions) - upcoming),
    )
    taken = 0
    for component in analysis.components:
        if taken >= component_budget:
            break
        question = _component_question(component)
        if question is None:
            continue
        questions.append(question)
        taken += 1

    if analysis.public_surface:
        question = _public_surface_question(analysis.public_surface)
        if question is not None:
            questions.append(question)

    if analysis.build_files or analysis.ci_workflows:
        question = _build_question(analysis.build_files, analysis.ci_workflows)
        if question is not None:
            questions.append(question)

    if analysis.tests.present:
        question = _tests_question(analysis.tests)
        if question is not None:
            questions.append(question)

    return QuestionPlan(
        questions=tuple(questions[:MAX_QUESTIONS]),
        repo_path=analysis.repo_path,
    )
