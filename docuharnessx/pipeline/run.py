"""Sequential explore-first pipeline runner (task 1.3).

``run_pipeline`` owns step order: analyze the repository, plan software
questions, write/gate each question, assemble a site only when at least one
page is accepted, and always write the operator run report.

This skeleton calls the existing analyzer and the question-planner seam,
skips writing when no model is bound, writes the report, and never publishes
outline fallback pages or a role-based site shell (Req 1.1, 1.3, 6.1, 6.2,
8.4, 10.2).
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from docuharnessx.analysis import analyze, scan
from docuharnessx.pages.model import Omission, OmissionReason, Page
from docuharnessx.pipeline.report import RunReport, write_run_report
from docuharnessx.planning.question_model import Question
from docuharnessx.planning.questions import plan_questions

__all__ = ["RunOutcome", "run_pipeline"]


@dataclass(frozen=True)
class RunOutcome:
    """Product of :func:`run_pipeline`: the report, output directory, and pages."""

    report: RunReport
    out_dir: str
    pages: tuple[Page, ...]


def _omit_unwritten(
    questions: tuple[Question, ...],
    *,
    model: object | None,
) -> tuple[tuple[Page, ...], tuple[Omission, ...]]:
    """Skip write and record a closed-set omission for each planned question.

    No-model runs omit with ``no_model`` (Req 1.3). A bound model still does
    not substitute outline prose: the writer adapter is not wired here, so
    each question is omitted rather than rendered from a planning blueprint
    (Req 6.1, 10.2).
    """
    reason = (
        OmissionReason.NO_MODEL if model is None else OmissionReason.EMPTY
    )
    omissions = tuple(
        Omission(question_id=question.id, reason=reason)
        for question in questions
    )
    return (), omissions


def _assemble_if_accepted(
    pages: tuple[Page, ...],
    *,
    out_dir: str,
    deploy_mode: str,
) -> None:
    """Write a site (and optionally deploy) only when accepted ≥ 1.

    Zero accepted pages: report only — no ``pages/`` files, no role-based
    ``docs/<role>/index.md`` shell, no deploy (Req 8.4, 8.5).
    """
    if not pages:
        return
    raise RuntimeError(
        "pipeline skeleton does not assemble a site or deploy "
        f"({len(pages)} accepted page(s) under {out_dir!r}, "
        f"deploy_mode={deploy_mode!r})"
    )


def run_pipeline(
    *,
    repo_path: str,
    out_dir: str,
    model: object | None,
    deploy_mode: str,
) -> RunOutcome:
    """Run analyze → questions → write/gate → assemble/report for one repo.

    Preconditions: ``repo_path`` is an existing directory (the CLI validates;
    this function still checks). Postconditions: a :class:`RunReport` is
    written under ``out_dir``; pages exist only for gate-accepted bodies
    (none in this skeleton); a site is emitted only if accepted ≥ 1
    (Req 8.4). ``deploy_mode`` is unused when accepted is 0 (Req 8.5).
    """
    if not os.path.isdir(repo_path):
        raise NotADirectoryError(
            f"repository path is not a directory: {repo_path!r}"
        )

    inventory = scan(repo_path)
    analysis = analyze(inventory)
    plan = plan_questions(analysis)
    pages, omissions = _omit_unwritten(plan.questions, model=model)

    report = RunReport(
        planned=len(plan.questions),
        accepted=len(pages),
        omitted=len(omissions),
        questions=tuple(question.id for question in plan.questions),
        omissions=omissions,
    )
    write_run_report(report, out_dir)
    _assemble_if_accepted(pages, out_dir=out_dir, deploy_mode=deploy_mode)
    return RunOutcome(report=report, out_dir=out_dir, pages=pages)
