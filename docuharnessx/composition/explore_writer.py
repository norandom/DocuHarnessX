"""Explore-first writer adapter: one bounded agent per question, omit on failure.

This module owns the *ExploreWriter* run boundary of
``explore-first-simplification``: :func:`write_questions` drives the existing
read-only writer harness once per planned question using
:func:`build_question_task` and :func:`validate_page_body`. Ungrounded results
become closed-set omissions. The adapter never substitutes an outline body.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from docuharnessx.composition.harness_factory import build_writer_harness
from docuharnessx.composition.question_task import build_question_task
from docuharnessx.composition.substance_gate import (
    _existing_cited_files,
    validate_page_body,
)
from docuharnessx.pages.model import Omission, OmissionReason, Page
from docuharnessx.planning.question_model import Question

__all__ = ["write_questions"]

_log = logging.getLogger(__name__)


def write_questions(
    questions: tuple[Question, ...],
    *,
    repo_path: str,
    model: object | None,
    guidance: str = "",
) -> tuple[tuple[Page, ...], tuple[Omission, ...]]:
    """Write one page per question or omit; never invent a substitute body.

    Each question gets a fresh bounded harness rooted read-only at
    ``repo_path``. A missing or non-directory repo omits every question with
    ``inspection_impossible``. ``model is None`` omits every question with
    ``no_model``. Per-question failures (no tool loop, empty body, substance
    gate reject, or a raised writer) omit that question and continue.
    """
    if not repo_path or not os.path.isdir(repo_path):
        return (), tuple(
            Omission(
                question_id=question.id,
                reason=OmissionReason.INSPECTION_IMPOSSIBLE,
            )
            for question in questions
        )
    if model is None:
        return (), tuple(
            Omission(question_id=question.id, reason=OmissionReason.NO_MODEL)
            for question in questions
        )

    pages: list[Page] = []
    omissions: list[Omission] = []
    for question in questions:
        page = _write_one(
            question, repo_path=repo_path, model=model, guidance=guidance
        )
        if isinstance(page, Page):
            pages.append(page)
        else:
            omissions.append(page)
    return tuple(pages), tuple(omissions)


def _write_one(
    question: Question,
    *,
    repo_path: str,
    model: object,
    guidance: str = "",
) -> Page | Omission:
    """Run one bounded writer; return an accepted page or a closed-set omission."""
    try:
        config = build_writer_harness(repo_path)
    except Exception as exc:
        _log.warning(
            "Explore writer could not root a read-only workspace at "
            "repo_path=%r for question %r (%s: %s); omitting.",
            repo_path,
            question.id,
            type(exc).__name__,
            exc,
        )
        return Omission(
            question_id=question.id,
            reason=OmissionReason.INSPECTION_IMPOSSIBLE,
        )

    task = build_question_task(question, repo_path=repo_path, guidance=guidance)
    try:
        body, _exit_reason, steps, _cost_usd, _tokens = _run_bounded(
            model, config, task
        )
    except Exception as exc:
        _log.warning(
            "Explore writer run failed for question %r (%s: %s); omitting.",
            question.id,
            type(exc).__name__,
            exc,
        )
        return Omission(question_id=question.id, reason=OmissionReason.EMPTY)

    if not isinstance(body, str) or not body.strip():
        return Omission(question_id=question.id, reason=OmissionReason.EMPTY)
    if steps <= 1:
        return Omission(
            question_id=question.id, reason=OmissionReason.NOT_INSPECTED
        )

    gate = validate_page_body(body, repo_path=repo_path, question=question)
    if not gate.accepted:
        return Omission(
            question_id=question.id, reason=OmissionReason.GATE_REJECTED
        )

    return Page(
        id=question.id,
        title=question.title,
        summary=_summary(body),
        body=body,
        subjects=(question.subject_name,),
        related=(),
        cited_files=_existing_cited_files(body, repo_path),
    )


def _summary(body: str) -> str:
    """First non-heading prose line, else the first non-empty line."""
    lines = [line.strip() for line in body.splitlines()]
    for line in lines:
        if line and not line.startswith("#"):
            return line
    for line in lines:
        if line:
            return line.lstrip("#").strip()
    return body.strip()


def _run_bounded(
    model: Any, config: Any, task: Any
) -> tuple[str, str, int, float, int]:
    """Bind the model and drive one bounded ``Harness.run`` on a private loop."""
    from harnessx.core.model_config import ModelConfig

    async def _drive() -> tuple[str, str, int, float, int]:
        harness = ModelConfig(main=model).agentic(config)
        try:
            result = await harness.run(task)
            end = result.task_end
            return (
                getattr(end, "final_output", "") or "",
                getattr(end, "exit_reason", "done") or "done",
                int(getattr(end, "total_steps", 0) or 0),
                float(getattr(end, "total_cost_usd", 0.0) or 0.0),
                int(getattr(end, "total_tokens", 0) or 0),
            )
        finally:
            try:
                await harness.cleanup()
            except Exception:  # pragma: no cover - cleanup is best-effort
                pass

    return asyncio.run(_drive())
