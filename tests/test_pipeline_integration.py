"""Pipeline integration: analyze → questions → write/gate → assemble → report.

Task 4.1 (explore-first-simplification, boundary: *PipelineRunner*) wires the
real planner, ``write_questions`` (substance gate inside the writer), and
``assemble_question_site``. Observable completion (tasks.md 4.1 / Req 1.1, 1.3,
2.2, 6.2, 8.1, 8.4, 9.1–9.4):

* shipped sample + inspecting scripted writer → ≥1 accepted page, home lists
  question titles, planned = accepted + omitted;
* no-model run still yields zero pages and reason ``no_model``;
* report files stay bounded (counts, ids, reasons) and never include bodies,
  including when logging is verbose.
"""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path

import pytest

from docuharnessx.analysis import analyze, scan
from docuharnessx.assembler.home import HOME_PAGE_PATH
from docuharnessx.pages.model import OmissionReason
from docuharnessx.pipeline import run_pipeline
from docuharnessx.planning.questions import plan_questions
from tests._fakes import FakeProvider, ScriptedAgentProvider

_FIXTURE_REPO = Path(__file__).parent / "fixtures" / "agentic_repo"

# Substance-gate-passing body used by the explore-writer suite (two real
# fixture files + Engine / load_config). Passes for component:root on the
# shipped sample; the build question is omitted (identifier mismatch).
_GROUNDED_BODY = (
    "The `Engine` class loads run settings through `load_config` (`config.py:10`)\n"
    "and then drives a bounded work cycle (`engine.py:16`).\n"
)

_RETIRED_SLOGANS = (
    "smallest action",
    "locate the",
    "fastest path for",
    "verify you reached first success",
    "run the smallest action",
)

_ROLE_INDEX_PHRASES = (
    "pick your role",
    "pick the path that matches your role",
    "choose your path",
    "role-based documentation",
)


def _copied_repo(tmp_path: Path) -> Path:
    dest = tmp_path / "repo"
    shutil.copytree(_FIXTURE_REPO, dest)
    return dest


def _home_path(out_dir: Path) -> Path:
    return out_dir / "site" / "docs" / HOME_PAGE_PATH


def _report_texts(out_dir: Path) -> tuple[str, str]:
    return (
        (out_dir / "report.json").read_text(encoding="utf-8"),
        (out_dir / "report.md").read_text(encoding="utf-8"),
    )


# --------------------------------------------------------------------------- #
# Inspecting scripted writer on the shipped sample (Req 1.1, 2.2, 8.1, 9.x)   #
# --------------------------------------------------------------------------- #


def test_inspecting_scripted_writer_accepts_pages_and_assembles_home(
    tmp_path: Path,
) -> None:
    repo = _copied_repo(tmp_path)
    expected = plan_questions(analyze(scan(str(repo))))
    assert expected.questions

    provider = ScriptedAgentProvider(body=_GROUNDED_BODY)
    outcome = run_pipeline(
        repo_path=str(repo),
        out_dir=str(tmp_path / "out"),
        model=provider,
        deploy_mode="build-only",
    )

    report = outcome.report
    assert report.accepted >= 1
    assert report.planned == len(expected.questions)
    assert report.questions == tuple(question.id for question in expected.questions)
    assert report.planned == report.accepted + report.omitted
    assert len(outcome.pages) == report.accepted
    assert {page.id for page in outcome.pages} <= set(report.questions)
    accepted_ids = {page.id for page in outcome.pages}
    omitted_ids = {omission.question_id for omission in report.omissions}
    assert accepted_ids.isdisjoint(omitted_ids)
    assert accepted_ids | omitted_ids == set(report.questions)

    page_files = list((tmp_path / "out" / "pages").glob("*.md"))
    assert page_files
    home = _home_path(tmp_path / "out")
    assert home.is_file()
    home_text = home.read_text(encoding="utf-8")
    for page in outcome.pages:
        assert page.title in home_text
        assert any(page.title in path.read_text(encoding="utf-8") for path in page_files)
    lowered_home = home_text.lower()
    for phrase in _ROLE_INDEX_PHRASES:
        assert phrase not in lowered_home, phrase
    assert list((tmp_path / "out" / "site" / "docs").glob("*/index.md")) == []

    json_text, markdown = _report_texts(tmp_path / "out")
    payload = json.loads(json_text)
    assert payload["planned"] == payload["accepted"] + payload["omitted"]
    assert "body" not in json.dumps(payload)
    for page in outcome.pages:
        assert page.body not in json_text
        assert page.body not in markdown
        assert page.summary not in json_text


def test_inspecting_writer_report_stays_bounded_under_verbose_logging(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    repo = _copied_repo(tmp_path)
    provider = ScriptedAgentProvider(body=_GROUNDED_BODY)
    outcome = run_pipeline(
        repo_path=str(repo),
        out_dir=str(tmp_path / "out"),
        model=provider,
        deploy_mode="build-only",
    )
    assert outcome.report.accepted >= 1
    json_text, markdown = _report_texts(tmp_path / "out")
    payload = json.loads(json_text)
    assert set(payload) == {"planned", "accepted", "omitted", "questions", "omissions"}
    for page in outcome.pages:
        assert page.body not in json_text
        assert page.body not in markdown
        assert "bounded work cycle" not in json_text
        assert "bounded work cycle" not in markdown


def test_non_inspecting_writer_omits_all_and_writes_no_site(tmp_path: Path) -> None:
    repo = _copied_repo(tmp_path)
    outcome = run_pipeline(
        repo_path=str(repo),
        out_dir=str(tmp_path / "out"),
        model=FakeProvider(content="Locate the CLI. Run the smallest action."),
        deploy_mode="build-only",
    )
    report = outcome.report
    assert report.accepted == 0
    assert outcome.pages == ()
    assert report.planned == report.omitted
    assert report.planned >= 1
    assert all(
        omission.reason
        in {OmissionReason.NOT_INSPECTED, OmissionReason.GATE_REJECTED}
        for omission in report.omissions
    )
    out = tmp_path / "out"
    assert not (out / "site").exists()
    assert not list((out / "pages").rglob("*") if (out / "pages").exists() else [])
    text = "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in out.rglob("*")
        if path.is_file()
    ).lower()
    for slogan in _RETIRED_SLOGANS:
        assert slogan not in text, slogan


# --------------------------------------------------------------------------- #
# No-model still plans, writes zero pages, reason no_model (Req 1.3, 6.2, 8.4)#
# --------------------------------------------------------------------------- #


def test_no_model_run_still_zero_pages_and_reason_no_model(tmp_path: Path) -> None:
    repo = _copied_repo(tmp_path)
    expected = plan_questions(analyze(scan(str(repo))))
    out = tmp_path / "out"
    outcome = run_pipeline(
        repo_path=str(repo),
        out_dir=str(out),
        model=None,
        deploy_mode="build-only",
    )
    report = outcome.report
    assert report.planned == len(expected.questions)
    assert report.accepted == 0
    assert report.omitted == report.planned
    assert outcome.pages == ()
    assert all(
        omission.reason is OmissionReason.NO_MODEL for omission in report.omissions
    )
    assert (out / "report.json").is_file()
    assert (out / "report.md").is_file()
    assert not (out / "site").exists()
    pages_dir = out / "pages"
    assert not pages_dir.exists() or list(pages_dir.rglob("*")) == []
