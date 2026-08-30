"""Credential-free e2e for the shipped sample (task 6.1, PipelineRunner).

Make-or-break suite for explore-first-simplification Req 8.5 / 11.1 / 11.2 / 11.3:

* inspecting writer → ≥1 accepted page citing real sample files and naming a
  symbol defined in those files; home lists that question; report counts add up;
* non-inspecting writer → zero accepted pages, omissions ``not_inspected`` or
  ``gate_rejected``, no template-slogan bodies under the output directory,
  report written;
* two ``plan_questions(analyze(scan(path)))`` passes on the unchanged sample
  yield the same question ids in the same order;
* optional publish after accepts still invokes existing deploy (``build-only``
  → ``<out>/site/site`` HTML);
* the suite **fails if a fallback slogan reappears** in ``out_dir``.
"""

from __future__ import annotations

import json
from pathlib import Path

from harnessx.core.model_config import ModelConfig

from docuharnessx import cli
from docuharnessx.analysis import analyze, scan
from docuharnessx.assembler.home import HOME_PAGE_PATH
from docuharnessx.pages.model import OmissionReason
from docuharnessx.pipeline import run_pipeline
from docuharnessx.planning.questions import plan_questions
from tests._fakes import FakeProvider, ScriptedAgentProvider

_FIXTURE_REPO = Path(__file__).parent / "fixtures" / "agentic_repo"

# Sample files and symbols the inspecting body must ground in (Req 11.1).
_SAMPLE_FILES = ("app.py", "config.py", "engine.py")
_SAMPLE_SYMBOLS = ("Engine", "load_config", "Application")

# Substance-gate-passing body from the explore-writer suite: two real fixture
# files plus Engine / load_config. Passes for component:root on the sample.
_GROUNDED_BODY = (
    "The `Engine` class loads run settings through `load_config` (`config.py:10`)\n"
    "and then drives a bounded work cycle (`engine.py:16`).\n"
)

_OUTLINE_BODY = "Locate the CLI. Run the smallest action. Fastest path for a role."

# Substrings that must never appear in an output directory. The suite is the
# regression tripwire if a fallback slogan is published again.
_FALLBACK_SLOGANS = (
    "locate ",
    "smallest action",
    "fastest path for",
)


def _home_path(out_dir: Path) -> Path:
    return out_dir / "site" / "docs" / HOME_PAGE_PATH


def _page_files(out_dir: Path) -> list[Path]:
    pages = out_dir / "pages"
    if not pages.exists():
        return []
    return [path for path in pages.rglob("*") if path.is_file()]


def _output_text(out_dir: Path) -> str:
    if not out_dir.exists():
        return ""
    blobs: list[str] = []
    for path in out_dir.rglob("*"):
        if path.is_file():
            blobs.append(path.read_text(encoding="utf-8", errors="replace"))
    return "\n".join(blobs)


def _assert_no_fallback_slogans(out_dir: Path) -> None:
    """Fail if a retired outline slogan reappears anywhere under ``out_dir``."""
    if not out_dir.exists():
        return
    for path in out_dir.rglob("*"):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace").lower()
        for slogan in _FALLBACK_SLOGANS:
            assert slogan not in text, f"{slogan!r} in {path.relative_to(out_dir)}"


def _assert_counts_add_up(report) -> None:
    assert report.planned == report.accepted + report.omitted
    assert report.planned == len(report.questions)
    assert report.omitted == len(report.omissions)


# --------------------------------------------------------------------------- #
# Inspecting writer (Req 11.1)                                                 #
# --------------------------------------------------------------------------- #


def test_inspecting_writer_accepts_grounded_sample_page(tmp_path: Path) -> None:
    for name in _SAMPLE_FILES:
        assert (_FIXTURE_REPO / name).is_file()

    expected = plan_questions(analyze(scan(str(_FIXTURE_REPO))))
    assert expected.questions

    provider = ScriptedAgentProvider(body=_GROUNDED_BODY)
    outcome = run_pipeline(
        repo_path=str(_FIXTURE_REPO),
        out_dir=str(tmp_path),
        model=provider,
        deploy_mode="build-only",
    )

    report = outcome.report
    assert report.accepted >= 1
    _assert_counts_add_up(report)
    assert report.planned == len(expected.questions)
    assert report.questions == tuple(question.id for question in expected.questions)
    assert len(outcome.pages) == report.accepted

    bodies = "\n".join(page.body for page in outcome.pages)
    cited = {path for page in outcome.pages for path in page.cited_files}
    named_symbols = [symbol for symbol in _SAMPLE_SYMBOLS if symbol in bodies]
    real_files = [name for name in _SAMPLE_FILES if name in cited or f"{name}:" in bodies]
    assert real_files, "accepted page must cite a real sample file"
    assert named_symbols, "accepted page must name a symbol defined in the sample"
    for name in real_files:
        assert (_FIXTURE_REPO / name).is_file()

    home = _home_path(tmp_path)
    assert home.is_file()
    home_text = home.read_text(encoding="utf-8")
    for page in outcome.pages:
        assert page.title in home_text
    assert _page_files(tmp_path)

    json_text = (tmp_path / "report.json").read_text(encoding="utf-8")
    markdown = (tmp_path / "report.md").read_text(encoding="utf-8")
    payload = json.loads(json_text)
    assert payload["planned"] == payload["accepted"] + payload["omitted"]
    assert "body" not in json.dumps(payload)
    for page in outcome.pages:
        assert page.body not in json_text
        assert page.body not in markdown

    _assert_no_fallback_slogans(tmp_path)


# --------------------------------------------------------------------------- #
# Non-inspecting writer (Req 11.2)                                             #
# --------------------------------------------------------------------------- #


def test_non_inspecting_writer_omits_all_and_writes_no_slogans(
    tmp_path: Path,
) -> None:
    outcome = run_pipeline(
        repo_path=str(_FIXTURE_REPO),
        out_dir=str(tmp_path),
        model=FakeProvider(content=_OUTLINE_BODY),
        deploy_mode="build-only",
    )

    report = outcome.report
    assert report.accepted == 0
    assert outcome.pages == ()
    _assert_counts_add_up(report)
    assert report.planned >= 1
    assert report.planned == report.omitted
    assert all(
        omission.reason
        in {OmissionReason.NOT_INSPECTED, OmissionReason.GATE_REJECTED}
        for omission in report.omissions
    )

    assert (tmp_path / "report.json").is_file()
    assert (tmp_path / "report.md").is_file()
    assert _page_files(tmp_path) == []
    assert not (tmp_path / "site").exists()
    assert _OUTLINE_BODY not in _output_text(tmp_path)
    _assert_no_fallback_slogans(tmp_path)


# --------------------------------------------------------------------------- #
# Planning determinism on the unchanged sample (Req 11.3)                      #
# --------------------------------------------------------------------------- #


def test_two_planning_passes_yield_same_question_ids_in_order() -> None:
    path = str(_FIXTURE_REPO)
    first = plan_questions(analyze(scan(path)))
    second = plan_questions(analyze(scan(path)))
    first_ids = tuple(question.id for question in first.questions)
    second_ids = tuple(question.id for question in second.questions)
    assert first_ids
    assert first_ids == second_ids
    assert first.questions == second.questions


# --------------------------------------------------------------------------- #
# Optional publish after accepts (Req 8.5)                                     #
# --------------------------------------------------------------------------- #


def test_cli_publish_after_accepts_invokes_build_only(tmp_path: Path) -> None:
    out = tmp_path / "out"
    model_config = ModelConfig(main=ScriptedAgentProvider(body=_GROUNDED_BODY))

    code = cli.main(
        [
            "run",
            str(_FIXTURE_REPO),
            "--out",
            str(out),
            "--deploy-mode",
            "build-only",
        ],
        model_config=model_config,
    )

    assert code == 0
    payload = json.loads((out / "report.json").read_text(encoding="utf-8"))
    assert payload["accepted"] >= 1
    assert payload["planned"] == payload["accepted"] + payload["omitted"]

    home = _home_path(out)
    assert home.is_file()
    page_files = _page_files(out)
    assert page_files
    bodies = "\n".join(path.read_text(encoding="utf-8") for path in page_files)
    assert any(symbol in bodies for symbol in _SAMPLE_SYMBOLS)
    assert any(f"{name}:" in bodies for name in _SAMPLE_FILES)

    built = out / "site" / "site"
    assert built.is_dir()
    html = list(built.rglob("*.html"))
    assert html, "build-only must emit mkdocs HTML under site/site"
    _assert_no_fallback_slogans(out)


def test_cli_non_inspecting_writer_is_honest_empty(tmp_path: Path) -> None:
    out = tmp_path / "out"
    model_config = ModelConfig(main=FakeProvider(content=_OUTLINE_BODY))

    code = cli.main(
        [
            "run",
            str(_FIXTURE_REPO),
            "--out",
            str(out),
            "--deploy-mode",
            "build-only",
        ],
        model_config=model_config,
    )

    assert code == 0
    payload = json.loads((out / "report.json").read_text(encoding="utf-8"))
    assert payload["accepted"] == 0
    assert payload["planned"] == payload["omitted"]
    reasons = {item["reason"] for item in payload["omissions"]}
    assert reasons <= {"not_inspected", "gate_rejected"}
    assert _page_files(out) == []
    assert not (out / "site").exists()
    assert _OUTLINE_BODY not in _output_text(out)
    _assert_no_fallback_slogans(out)
