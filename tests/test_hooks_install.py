"""Install hooks / CI workflow and fail-open hook runner."""

from __future__ import annotations

from pathlib import Path

from docuharnessx import cli
from docuharnessx.ci_install import CONSUMER_WORKFLOW_RELPATH, install_ci_workflow
from docuharnessx.hooks import (
    HOOK_ID,
    install_git_hook,
    install_pre_commit_config,
    render_pre_commit_hooks_yaml,
    run_precommit_hook,
    stage_doc_paths,
)


def test_published_pre_commit_hooks_yaml_matches_renderer() -> None:
    published = Path(__file__).resolve().parents[1] / ".pre-commit-hooks.yaml"
    assert published.read_text(encoding="utf-8") == render_pre_commit_hooks_yaml()


def test_install_pre_commit_config(tmp_path: Path) -> None:
    path = Path(install_pre_commit_config(str(tmp_path)))
    text = path.read_text(encoding="utf-8")
    assert HOOK_ID in text
    assert "github.com/norandom/DocuHarnessX" in text
    assert "rev: v2.0.0" in text
    # Second install without force is a no-op when already present.
    assert install_pre_commit_config(str(tmp_path)) == str(path)


def test_install_git_hook_requires_git_dir(tmp_path: Path) -> None:
    try:
        install_git_hook(str(tmp_path))
    except FileNotFoundError as exc:
        assert ".git missing" in str(exc)
    else:
        raise AssertionError("expected FileNotFoundError")
    git_hooks = tmp_path / ".git" / "hooks"
    git_hooks.mkdir(parents=True)
    path = Path(install_git_hook(str(tmp_path)))
    script = path.read_text(encoding="utf-8")
    assert "dhx hook" in script
    assert "uvx" in script
    assert path.stat().st_mode & 0o111


def test_install_ci_workflow(tmp_path: Path) -> None:
    path = Path(install_ci_workflow(str(tmp_path), evolve="pr"))
    assert path.as_posix().endswith(CONSUMER_WORKFLOW_RELPATH)
    text = path.read_text(encoding="utf-8")
    assert "norandom/DocuHarnessX/.github/workflows/adopt.yml@v2.0.0" in text
    assert "evolve: pr" in text
    assert "secrets.OPENAI_API_KEY" in text
    assert "vars.OPENAI_API_BASE" in text
    assert "vars.OPENAI_DEFAULT_MAIN_MODEL" in text
    assert "secrets.OPENAI_API_BASE" not in text
    assert "secrets.OPENAI_DEFAULT_MAIN_MODEL" not in text
    try:
        install_ci_workflow(str(tmp_path))
    except FileExistsError:
        pass
    else:
        raise AssertionError("expected FileExistsError")


def test_this_repo_dogfoods_adopt_from_checkout() -> None:
    text = (
        Path(__file__).resolve().parents[1] / ".github" / "workflows" / "dhx.yml"
    ).read_text(encoding="utf-8")
    assert "uses: ./.github/workflows/adopt.yml" in text
    assert "source: checkout" in text
    assert "secrets.OPENAI_API_KEY" in text
    assert "vars.OPENAI_API_BASE" in text
    assert "vars.OPENAI_DEFAULT_MAIN_MODEL" in text
    assert "secrets.OPENAI_API_BASE" not in text


def test_hook_runner_skips_without_key_and_does_not_generate(tmp_path: Path) -> None:
    called: list[str] = []
    result = run_precommit_hook(
        str(tmp_path),
        staged_paths=["app.py"],
        environ={},
        generate=lambda p: called.append(p),
    )
    assert result.skipped is True
    assert called == []


def test_hook_runner_generates_and_stages_docs(tmp_path: Path) -> None:
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "index.md").write_text("# hi\n", encoding="utf-8")
    added: list[str] = []

    def _add(paths: list[str]) -> None:
        added.extend(paths)

    result = run_precommit_hook(
        str(tmp_path),
        staged_paths=["pkg/main.go"],
        environ={"OPENAI_API_KEY": "sk-test"},
        generate=lambda p: (tmp_path / "mkdocs.yml").write_text("site_name: x\n"),
        git_add=_add,
    )
    assert result.skipped is False
    assert "docs" in added
    assert "mkdocs.yml" in added
    assert ".env" not in added


def test_cli_install_hooks_pre_commit(tmp_path: Path) -> None:
    code = cli.main(["install-hooks", str(tmp_path), "--pre-commit"])
    assert code == 0
    assert (tmp_path / ".pre-commit-config.yaml").is_file()


def test_cli_install_ci(tmp_path: Path) -> None:
    code = cli.main(["install-ci", str(tmp_path), "--evolve", "off"])
    assert code == 0
    text = (tmp_path / ".github" / "workflows" / "dhx.yml").read_text(encoding="utf-8")
    assert "evolve: off" in text


def test_cli_hook_skips_without_key(tmp_path, capsys, monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("LITELLM_API_KEY", raising=False)
    (tmp_path / "app.py").write_text("print(1)\n", encoding="utf-8")
    code = cli.main(["hook", str(tmp_path)])
    assert code == 0
    assert "skip" in capsys.readouterr().out.lower()


def test_stage_doc_paths_never_includes_env(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("OPENAI_API_KEY=sk-secret\n", encoding="utf-8")
    (tmp_path / "docs").mkdir()
    added: list[str] = []
    stage_doc_paths(str(tmp_path), git_add=lambda paths: added.extend(paths))
    assert ".env" not in added
    assert "docs" in added
