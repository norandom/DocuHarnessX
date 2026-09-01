"""CLI loads a project ``.env`` without overriding a live process environment."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from docuharnessx import cli


def test_load_env_files_reads_dotenv_without_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text(
        "OPENAI_API_KEY=sk-from-file\n"
        "OPENAI_API_BASE=https://api.deepseek.com\n"
        "OPENAI_DEFAULT_MAIN_MODEL=deepseek-v4-flash\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-already-set")
    monkeypatch.delenv("OPENAI_API_BASE", raising=False)
    monkeypatch.delenv("OPENAI_DEFAULT_MAIN_MODEL", raising=False)

    cli._load_env_files(force=True)

    assert os.environ["OPENAI_API_KEY"] == "sk-already-set"
    assert os.environ["OPENAI_API_BASE"] == "https://api.deepseek.com"
    assert os.environ["OPENAI_DEFAULT_MAIN_MODEL"] == "deepseek-v4-flash"


def test_prepare_run_loads_target_project_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from harnessx.core.model_config import ModelConfig

    from _fakes import FakeProvider

    project = tmp_path / "repo"
    project.mkdir()
    (project / ".env").write_text(
        "OPENAI_API_BASE=https://api.deepseek.com\n"
        "OPENAI_DEFAULT_MAIN_MODEL=deepseek-v4-flash\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OPENAI_API_BASE", raising=False)
    monkeypatch.delenv("OPENAI_DEFAULT_MAIN_MODEL", raising=False)

    args = cli.build_parser().parse_args(
        ["run", str(project), "--out", str(tmp_path / "out")]
    )
    cli.prepare_run(args, model_config=ModelConfig(main=FakeProvider()))

    assert os.environ["OPENAI_API_BASE"] == "https://api.deepseek.com"
    assert os.environ["OPENAI_DEFAULT_MAIN_MODEL"] == "deepseek-v4-flash"


def test_env_example_documents_deepseek_placeholders() -> None:
    example = Path(__file__).resolve().parents[1] / ".env.example"
    text = example.read_text(encoding="utf-8")
    assert "OPENAI_API_KEY=" in text
    assert "OPENAI_API_BASE=https://api.deepseek.com" in text
    assert "OPENAI_DEFAULT_MAIN_MODEL=deepseek-v4-flash" in text
    assert "sk-c0dfc918" not in text
