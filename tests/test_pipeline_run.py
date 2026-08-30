"""Tests for the explore-first pipeline skeleton (task 1.3).

Pins PipelineRunner: analyze → plan → skip write when no model is bound →
write a run report, and never emit outline pages or a role-based site shell.

Observable completion (tasks.md 1.3 / Req 1.1, 1.3, 6.1, 6.2, 8.4, 10.2): a
no-model run against ``tests/fixtures/agentic_repo`` writes a report with zero
accepted pages, no files under the pages output, and no “locate / smallest
action” text anywhere in the output directory.
"""

from __future__ import annotations

import ast
import inspect
import json
from pathlib import Path

import pytest

from docuharnessx.pages.model import OmissionReason
from docuharnessx.pipeline import RunOutcome, RunReport, run_pipeline
from docuharnessx.planning.question_model import (
    Question,
    QuestionKind,
    QuestionPlan,
    make_question_id,
)
from docuharnessx.planning.questions import plan_questions

_FIXTURE_REPO = Path(__file__).parent / "fixtures" / "agentic_repo"

_RETIRED_SLOGANS = (
    "smallest action",
    "locate the",
    "fastest path for",
    "verify you reached first success",
    "run the smallest action",
)


def _sample_question() -> Question:
    return Question(
        id=make_question_id(QuestionKind.STARTUP, "app.py"),
        kind=QuestionKind.STARTUP,
        title="How does this program start?",
        subject_name="app.py",
        evidence_paths=("app.py", "config.py"),
    )


def _run(
    tmp_path: Path,
    *,
    model: object | None = None,
    repo_path: Path | str | None = None,
    deploy_mode: str = "build-only",
) -> RunOutcome:
    return run_pipeline(
        repo_path=str(repo_path or _FIXTURE_REPO),
        out_dir=str(tmp_path),
        model=model,
        deploy_mode=deploy_mode,
    )


def _text_blobs(root: Path) -> list[str]:
    blobs: list[str] = []
    for path in root.rglob("*"):
        if path.is_file():
            blobs.append(path.read_text(encoding="utf-8", errors="replace"))
    return blobs


def _joined_output(root: Path) -> str:
    return "\n".join(_text_blobs(root))


def _page_files(root: Path) -> list[Path]:
    pages = root / "pages"
    if not pages.exists():
        return []
    return [path for path in pages.rglob("*") if path.is_file()]


def _role_landing_files(root: Path) -> list[Path]:
    return list(root.rglob("docs/*/index.md"))


def _assert_honest_empty(out_dir: Path, report: RunReport) -> None:
    assert report.accepted == 0
    assert report.planned == report.accepted + report.omitted
    assert (out_dir / "report.json").is_file()
    assert (out_dir / "report.md").is_file()
    payload = json.loads((out_dir / "report.json").read_text(encoding="utf-8"))
    assert payload["accepted"] == 0
    assert _page_files(out_dir) == []
    assert not (out_dir / "site").exists()
    assert _role_landing_files(out_dir) == []
    text = _joined_output(out_dir).lower()
    for slogan in _RETIRED_SLOGANS:
        assert slogan not in text, slogan
    assert "locate " not in text


# --------------------------------------------------------------------------- #
# Signature and package surface                                                #
# --------------------------------------------------------------------------- #


def test_run_pipeline_is_keyword_only() -> None:
    parameters = inspect.signature(run_pipeline).parameters
    assert list(parameters) == ["repo_path", "out_dir", "model", "deploy_mode"]
    for parameter in parameters.values():
        assert parameter.kind is inspect.Parameter.KEYWORD_ONLY


def test_run_pipeline_rejects_positional_arguments(tmp_path: Path) -> None:
    with pytest.raises(TypeError):
        run_pipeline(str(_FIXTURE_REPO), str(tmp_path), None, "build-only")  # type: ignore[misc]


def test_pipeline_package_exports_runner() -> None:
    import docuharnessx.pipeline as pkg
    from docuharnessx.pipeline.run import RunOutcome as RunOutcomeType
    from docuharnessx.pipeline.run import run_pipeline as run_pipeline_fn

    assert pkg.run_pipeline is run_pipeline_fn
    assert pkg.RunOutcome is RunOutcomeType
    assert pkg.RunReport is RunReport


# --------------------------------------------------------------------------- #
# Question-planner stub (empty until task 2.1)                                 #
# --------------------------------------------------------------------------- #


def test_plan_questions_stub_returns_empty_plan() -> None:
    from docuharnessx.analysis import analyze, scan

    analysis = analyze(scan(str(_FIXTURE_REPO)))
    plan = plan_questions(analysis)
    assert plan.questions == ()
    assert plan.repo_path == analysis.repo_path


# --------------------------------------------------------------------------- #
# Observable: no-model run on the shipped sample (Req 1.1, 1.3, 6.2, 8.4, 10.2)#
# --------------------------------------------------------------------------- #


def test_no_model_run_on_sample_writes_report_with_zero_pages(
    tmp_path: Path,
) -> None:
    """Observable completion for task 1.3."""
    outcome = _run(tmp_path, model=None)

    assert isinstance(outcome, RunOutcome)
    assert outcome.out_dir == str(tmp_path)
    assert outcome.pages == ()
    assert outcome.report.accepted == 0
    if outcome.report.planned:
        assert all(
            omission.reason is OmissionReason.NO_MODEL
            for omission in outcome.report.omissions
        )
    _assert_honest_empty(tmp_path, outcome.report)


def test_no_model_run_report_payload_has_counts_and_no_bodies(
    tmp_path: Path,
) -> None:
    _run(tmp_path, model=None)
    payload = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    markdown = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert payload["accepted"] == 0
    assert payload["planned"] == payload["accepted"] + payload["omitted"]
    assert payload["planned"] == len(payload["questions"])
    assert payload["omitted"] == len(payload["omissions"])
    assert "body" not in json.dumps(payload)
    assert "Locate " not in markdown
    assert "smallest action" not in markdown


# --------------------------------------------------------------------------- #
# No-model still analyzes + plans; skip write; omit with no_model (Req 1.3)    #
# --------------------------------------------------------------------------- #


def test_runner_calls_existing_analyzer_then_planner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from docuharnessx.analysis.analyzer import analyze as real_analyze
    from docuharnessx.analysis.scanner import scan as real_scan

    order: list[str] = []
    analyses: list[object] = []

    def tracking_scan(*args: object, **kwargs: object) -> object:
        order.append("scan")
        return real_scan(*args, **kwargs)

    def tracking_analyze(*args: object, **kwargs: object) -> object:
        order.append("analyze")
        analysis = real_analyze(*args, **kwargs)
        analyses.append(analysis)
        return analysis

    def tracking_plan(analysis: object) -> QuestionPlan:
        order.append("plan")
        assert analyses and analysis is analyses[-1]
        repo_path = getattr(analysis, "repo_path")
        return QuestionPlan(questions=(), repo_path=repo_path)

    monkeypatch.setattr("docuharnessx.pipeline.run.scan", tracking_scan)
    monkeypatch.setattr("docuharnessx.pipeline.run.analyze", tracking_analyze)
    monkeypatch.setattr("docuharnessx.pipeline.run.plan_questions", tracking_plan)

    _run(tmp_path, model=None)

    assert order == ["scan", "analyze", "plan"]
    analysis = analyses[0]
    assert analysis.total_files >= 1
    representative = analysis.components[0].representative_files
    assert "app.py" in representative
    assert any(build.path == "pyproject.toml" for build in analysis.build_files)


def test_no_model_omits_each_planned_question_with_no_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    question = _sample_question()

    def fake_plan(analysis: object) -> QuestionPlan:
        return QuestionPlan(
            questions=(question,),
            repo_path=getattr(analysis, "repo_path"),
        )

    monkeypatch.setattr("docuharnessx.pipeline.run.plan_questions", fake_plan)

    outcome = _run(tmp_path, model=None)
    report = outcome.report
    assert report.planned == 1
    assert report.accepted == 0
    assert report.omitted == 1
    assert report.questions == (question.id,)
    assert len(report.omissions) == 1
    assert report.omissions[0].question_id == question.id
    assert report.omissions[0].reason is OmissionReason.NO_MODEL
    assert outcome.pages == ()
    _assert_honest_empty(tmp_path, report)

    markdown = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert "no_model" in markdown
    payload = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert payload["omissions"][0]["reason"] == "no_model"


def test_bound_model_still_does_not_publish_outline_pages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Skeleton has no writer: a bound model must not invoke outline fallback."""
    question = _sample_question()

    def fake_plan(analysis: object) -> QuestionPlan:
        return QuestionPlan(
            questions=(question,),
            repo_path=getattr(analysis, "repo_path"),
        )

    monkeypatch.setattr("docuharnessx.pipeline.run.plan_questions", fake_plan)

    outcome = _run(tmp_path, model=object())
    assert outcome.report.accepted == 0
    assert outcome.pages == ()
    _assert_honest_empty(tmp_path, outcome.report)


# --------------------------------------------------------------------------- #
# Retired fallback renderer is not on the pipeline path (Req 6.1, 10.2)        #
# --------------------------------------------------------------------------- #


def test_pipeline_runner_source_does_not_import_fallback() -> None:
    source_path = (
        Path(__file__).resolve().parents[1] / "docuharnessx" / "pipeline" / "run.py"
    )
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.append(node.module or "")
            imported.extend(alias.name for alias in node.names)
    joined = " ".join(imported)
    assert "fallback" not in joined
    assert "render_fallback_body" not in source
    assert "docuharnessx.composition.fallback" not in source


def test_no_model_run_does_not_call_fallback_renderer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []

    def boom(*_args: object, **_kwargs: object) -> str:
        calls.append("render_fallback_body")
        raise AssertionError("pipeline must not call render_fallback_body")

    monkeypatch.setattr(
        "docuharnessx.composition.fallback.render_fallback_body",
        boom,
        raising=True,
    )
    question = _sample_question()

    def fake_plan(analysis: object) -> QuestionPlan:
        return QuestionPlan(
            questions=(question,),
            repo_path=getattr(analysis, "repo_path"),
        )

    monkeypatch.setattr("docuharnessx.pipeline.run.plan_questions", fake_plan)
    _run(tmp_path, model=None)
    _run(tmp_path / "with-model", model=object())
    assert calls == []
