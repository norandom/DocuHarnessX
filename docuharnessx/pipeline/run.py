"""Sequential explore-first pipeline runner.

``run_pipeline`` owns step order: analyze the repository, plan software
questions, write/gate each question, assemble a site only when at least one
page is accepted, and always write the operator run report.

No-model runs still plan and omit with ``no_model``. An empty plan writes the
report and no site shell. Writer stats become closed-set omission reasons;
page bodies never enter the report (Req 1.1, 1.3, 6.2, 8.1, 8.4, 9.1–9.4).
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

from docuharnessx.analysis import analyze, scan
from docuharnessx.assembler.identity import read_origin_remote, resolve_site_identity
from docuharnessx.assembler.pages import render_question_page
from docuharnessx.assembler.question_site import assemble_question_site
from docuharnessx.composition.explore_writer import write_questions
from docuharnessx.pages.model import Page
from docuharnessx.pipeline.report import RunReport, write_run_report
from docuharnessx.planning.questions import plan_questions

__all__ = ["RunOutcome", "run_pipeline"]

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class RunOutcome:
    """Product of :func:`run_pipeline`: the report, output directory, and pages."""

    report: RunReport
    out_dir: str
    pages: tuple[Page, ...]


def _persist_accepted_pages(pages: tuple[Page, ...], out_dir: str) -> None:
    """Write accepted page markdown under ``<out>/pages/``. Skip if none."""
    if not pages:
        return
    dest = Path(out_dir) / "pages"
    dest.mkdir(parents=True, exist_ok=True)
    for page in pages:
        rel_path, content = render_question_page(page, pages)
        path = dest / rel_path
        with open(path, "w", encoding="utf-8", newline="") as handle:
            handle.write(content)


def _assemble_if_accepted(
    pages: tuple[Page, ...],
    *,
    repo_path: str,
    out_dir: str,
    deploy_mode: str,
) -> None:
    """Write a question-organised site only when accepted ≥ 1.

    Zero accepted pages: report only — no ``pages/`` files, no role-based
    ``docs/<role>/index.md`` shell, no deploy (Req 8.4, 8.5). ``deploy_mode``
    is reserved for CLI publish wiring; this step does not deploy.
    """
    if not pages:
        return
    identity = resolve_site_identity(
        repo_path, read_origin_remote(repo_path), {}
    )
    assemble_question_site(pages, identity, out_dir)
    _log.info(
        "assembled question site under %s/site (accepted=%s, deploy_mode=%s)",
        out_dir,
        len(pages),
        deploy_mode,
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
    written under ``out_dir``; pages exist only for gate-accepted bodies; a
    site is emitted only if accepted ≥ 1 (Req 8.4). ``deploy_mode`` is unused
    when accepted is 0 (Req 8.5).
    """
    if not os.path.isdir(repo_path):
        raise NotADirectoryError(
            f"repository path is not a directory: {repo_path!r}"
        )

    inventory = scan(repo_path)
    analysis = analyze(inventory)
    plan = plan_questions(analysis)
    pages, omissions = write_questions(
        plan.questions, repo_path=repo_path, model=model
    )
    _log.info(
        "pipeline write: planned=%s accepted=%s omitted=%s",
        len(plan.questions),
        len(pages),
        len(omissions),
    )

    report = RunReport(
        planned=len(plan.questions),
        accepted=len(pages),
        omitted=len(omissions),
        questions=tuple(question.id for question in plan.questions),
        omissions=omissions,
    )
    _persist_accepted_pages(pages, out_dir)
    write_run_report(report, out_dir)
    _assemble_if_accepted(
        pages, repo_path=repo_path, out_dir=out_dir, deploy_mode=deploy_mode
    )
    return RunOutcome(report=report, out_dir=out_dir, pages=pages)
