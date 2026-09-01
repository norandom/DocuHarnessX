"""CLI explore-first switch: drop the dummy DONE run (task 4.2).

Observable completion (tasks.md 4.2 / Req 1.1, 1.2, 1.3, 1.4, 8.5, 10.1–10.3):

* missing path fails as today (non-zero, no documentation pages);
* shipped sample without a model writes a report and zero documentation pages;
* inspecting fake (test injection) produces grounded pages and no role landings.

Binding a writer model is optional; reader-role selection is not required.
Honest-empty completes with exit 0. Invalid target exits non-zero.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

from harnessx.core.model_config import ModelConfig

from docuharnessx import cli
from docuharnessx.assembler.home import HOME_PAGE_PATH
from tests._fakes import ScriptedAgentProvider

_FIXTURE_REPO = Path(__file__).parent / "fixtures" / "agentic_repo"

# Same grounded body the pipeline integration suite uses: two real fixture
# files plus Engine / load_config so the substance gate accepts component:root.
_GROUNDED_BODY = (
    "The `Engine` class loads run settings through `load_config` (`config.py:10`)\n"
    "and then drives a bounded work cycle (`engine.py:16`).\n"
)

_PROVIDER_ENV_VARS = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_DEFAULT_MAIN_MODEL",
    "ANTHROPIC_API_BASE",
    "ANTHROPIC_BASE_URL",
    "OPENAI_API_KEY",
    "OPENAI_DEFAULT_MAIN_MODEL",
    "OPENAI_API_BASE",
    "LITELLM_API_KEY",
    "LITELLM_DEFAULT_MAIN_MODEL",
    "LITELLM_API_BASE",
)

_ROLE_INDEX_PHRASES = (
    "pick your role",
    "pick the path that matches your role",
    "choose your path",
    "role-based documentation",
)

_RETIRED_SLOGANS = (
    "smallest action",
    "locate the",
    "fastest path for",
    "run the smallest action",
)


def _clear_provider_env(monkeypatch) -> None:
    for var in _PROVIDER_ENV_VARS:
        monkeypatch.delenv(var, raising=False)


def _page_files(out: Path) -> list[Path]:
    pages = out / "pages"
    if not pages.exists():
        return []
    return [path for path in pages.rglob("*") if path.is_file()]


def _role_landing_indexes(out: Path) -> list[Path]:
    docs = out / "site" / "docs"
    if not docs.is_dir():
        return []
    return list(docs.glob("*/index.md"))


def _output_text(out: Path) -> str:
    if not out.exists():
        return ""
    blobs: list[str] = []
    for path in out.rglob("*"):
        if path.is_file():
            blobs.append(path.read_text(encoding="utf-8", errors="replace"))
    return "\n".join(blobs)


# --------------------------------------------------------------------------- #
# 1. Missing path fails as today (Req 1.2)                                     #
# --------------------------------------------------------------------------- #


def test_cli_missing_path_fails_as_today(tmp_path, capsys) -> None:
    missing = str(tmp_path / "does-not-exist")
    out = tmp_path / "out"

    code = cli.main(["run", missing, "--out", str(out)])

    assert code != 0
    err = capsys.readouterr().err
    assert "TargetRepoError" in err
    assert missing in err
    assert not out.exists()
    assert _page_files(out) == []


def test_cli_target_that_is_a_file_exits_nonzero_with_no_pages(
    tmp_path, capsys
) -> None:
    target = tmp_path / "a-file.txt"
    target.write_text("not a repo\n", encoding="utf-8")
    out = tmp_path / "out"

    code = cli.main(["run", str(target), "--out", str(out)])

    assert code != 0
    assert "TargetRepoError" in capsys.readouterr().err
    assert not out.exists()
    assert _page_files(out) == []


# --------------------------------------------------------------------------- #
# 2. Shipped sample without a model: report + zero pages (Req 1.3, 1.4, 10.2) #
# --------------------------------------------------------------------------- #


def test_cli_sample_without_model_writes_report_and_zero_pages(
    tmp_path, monkeypatch, capsys
) -> None:
    _clear_provider_env(monkeypatch)
    out = tmp_path / "out"

    # No model_config injection and no provider env: writing is skipped, not
    # substituted with outline pages. Roles are not supplied (Req 1.4, 10.3).
    repo = tmp_path / "repo"
    shutil.copytree(_FIXTURE_REPO, repo)
    code = cli.main(
        ["run", str(repo), "--out", str(out), "--deploy-mode", "build-only"]
    )

    assert code == 0, capsys.readouterr()
    report_json = out / "report.json"
    report_md = out / "report.md"
    assert report_json.is_file()
    assert report_md.is_file()
    payload = json.loads(report_json.read_text(encoding="utf-8"))
    assert payload["accepted"] == 0
    assert payload["planned"] == payload["accepted"] + payload["omitted"]
    assert "body" not in json.dumps(payload)
    reasons = {item["reason"] for item in payload["omissions"]}
    assert reasons <= {"no_model"} or payload["planned"] == 0
    if payload["planned"] >= 1:
        assert reasons == {"no_model"}
    assert _page_files(out) == []
    assert not (out / "site").exists() or _role_landing_indexes(out) == []
    lowered = _output_text(out).lower()
    for slogan in _RETIRED_SLOGANS:
        assert slogan not in lowered, slogan


def test_cli_honest_empty_exits_zero_without_roles(tmp_path, monkeypatch) -> None:
    _clear_provider_env(monkeypatch)
    target = tmp_path / "empty-repo"
    target.mkdir()
    out = tmp_path / "out"

    code = cli.main(["run", str(target), "--out", str(out)])

    assert code == 0
    assert (out / "report.json").is_file()
    payload = json.loads((out / "report.json").read_text(encoding="utf-8"))
    assert payload["accepted"] == 0
    assert _page_files(out) == []


# --------------------------------------------------------------------------- #
# 3. Inspecting fake (test injection): grounded pages, no role landings        #
# --------------------------------------------------------------------------- #


def test_cli_inspecting_fake_produces_grounded_pages_without_role_landings(
    tmp_path,
) -> None:
    out = tmp_path / "out"
    model_config = ModelConfig(main=ScriptedAgentProvider(body=_GROUNDED_BODY))

    repo = tmp_path / "repo"
    shutil.copytree(_FIXTURE_REPO, repo)
    code = cli.main(
        [
            "run",
            str(repo),
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

    page_files = _page_files(out)
    assert page_files
    bodies = "\n".join(path.read_text(encoding="utf-8") for path in page_files)
    assert "Engine" in bodies or "load_config" in bodies
    assert "config.py:10" in bodies or "engine.py:16" in bodies

    home = out / "site" / "docs" / HOME_PAGE_PATH
    assert home.is_file()
    home_text = home.read_text(encoding="utf-8")
    lowered_home = home_text.lower()
    for phrase in _ROLE_INDEX_PHRASES:
        assert phrase not in lowered_home, phrase
    assert _role_landing_indexes(out) == []
    assert "cobesy" not in bodies.lower()
    assert "cobesy" not in lowered_home
    lowered_all = _output_text(out).lower()
    for slogan in _RETIRED_SLOGANS:
        assert slogan not in lowered_all, slogan
