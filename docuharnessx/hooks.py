"""Install and run DocuHarnessX git / pre-commit hooks."""

from __future__ import annotations

import os
import stat
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from docuharnessx import __version__
from docuharnessx.ci_policy import HookDecision, should_run_hook

__all__ = [
    "DHX_GITHUB_REPO",
    "HOOK_ID",
    "HookRunResult",
    "default_rev",
    "install_git_hook",
    "install_pre_commit_config",
    "render_git_pre_commit_script",
    "render_pre_commit_hooks_yaml",
    "render_consumer_pre_commit_config",
    "run_precommit_hook",
    "stage_doc_paths",
]

DHX_GITHUB_REPO = "https://github.com/norandom/DocuHarnessX"
HOOK_ID = "dhx"

STAGE_PATHS: tuple[str, ...] = (
    "docs",
    "mkdocs.yml",
    ".docuharnessx/pages",
    ".docuharnessx/adoption.yaml",
    ".docuharnessx/ontology.yaml",
    ".github/workflows/docs.yml",
)


def default_rev() -> str:
    """Git ref consumers should pin. Matches the package version tag when released."""
    return f"v{__version__}"


def render_pre_commit_hooks_yaml() -> str:
    """Hook definition published by this repo for ``pre-commit`` ``repo:`` installs."""
    return (
        f"- id: {HOOK_ID}\n"
        "  name: DocuHarnessX\n"
        "  description: Incremental living docs and MkDocs assemble when source changes\n"
        "  entry: dhx hook\n"
        "  language: python\n"
        "  language_version: python3.12\n"
        "  pass_filenames: false\n"
        "  always_run: false\n"
        "  types_or: [python, go, rust, javascript, c, c++, java]\n"
    )


def render_consumer_pre_commit_config(rev: str | None = None) -> str:
    """``.pre-commit-config.yaml`` snippet a consuming repo commits."""
    pin = rev or default_rev()
    return (
        "repos:\n"
        f"  - repo: {DHX_GITHUB_REPO}\n"
        f"    rev: {pin}\n"
        "    hooks:\n"
        f"      - id: {HOOK_ID}\n"
    )


def render_git_pre_commit_script(rev: str | None = None) -> str:
    """Native git ``pre-commit`` hook that prefers local ``dhx``, else ``uvx`` from GitHub."""
    pin = rev or default_rev()
    return (
        "#!/bin/sh\n"
        "# Installed by `dhx install-hooks`. Do not commit secrets.\n"
        "set -e\n"
        "if command -v dhx >/dev/null 2>&1; then\n"
        "  exec dhx hook\n"
        "fi\n"
        "if command -v uvx >/dev/null 2>&1; then\n"
        f'  exec uvx --python 3.12 --from "git+{DHX_GITHUB_REPO}.git@{pin}" dhx hook\n'
        "fi\n"
        'echo "dhx hook: install dhx (uv tool install from GitHub) or uvx" >&2\n'
        "exit 0\n"
    )


def install_pre_commit_config(
    project_dir: str, *, rev: str | None = None, force: bool = False
) -> str:
    """Write ``.pre-commit-config.yaml`` unless it already exists (unless ``force``)."""
    path = Path(project_dir) / ".pre-commit-config.yaml"
    if path.is_file() and not force:
        text = path.read_text(encoding="utf-8")
        if HOOK_ID in text and "DocuHarnessX" in text:
            return str(path)
        raise FileExistsError(
            f"{path} already exists; pass --force to overwrite, or merge the dhx hook by hand"
        )
    path.write_text(render_consumer_pre_commit_config(rev), encoding="utf-8")
    return str(path)


def install_git_hook(
    project_dir: str, *, rev: str | None = None, force: bool = False
) -> str:
    """Write ``.git/hooks/pre-commit`` (executable). Requires a git checkout."""
    git_dir = Path(project_dir) / ".git"
    if not git_dir.is_dir():
        raise FileNotFoundError(
            f"{project_dir} is not a git checkout (.git missing); "
            "use --pre-commit to write .pre-commit-config.yaml instead"
        )
    hooks_dir = git_dir / "hooks"
    hooks_dir.mkdir(exist_ok=True)
    path = hooks_dir / "pre-commit"
    if path.is_file() and not force:
        existing = path.read_text(encoding="utf-8")
        if "dhx hook" in existing:
            return str(path)
        raise FileExistsError(
            f"{path} already exists; pass --force to overwrite"
        )
    path.write_text(render_git_pre_commit_script(rev), encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return str(path)


@dataclass(frozen=True)
class HookRunResult:
    skipped: bool
    reason: str
    staged: tuple[str, ...]


def stage_doc_paths(
    project_dir: str,
    *,
    git_add: Callable[[Sequence[str]], None] | None = None,
) -> tuple[str, ...]:
    """``git add`` living docs / MkDocs paths that exist. Never adds ``.env``."""
    root = Path(project_dir)
    existing = [
        rel for rel in STAGE_PATHS if (root / rel).exists()
    ]
    if not existing:
        return ()
    if git_add is not None:
        git_add(existing)
        return tuple(existing)
    subprocess.run(
        ["git", "add", "--", *existing],
        cwd=project_dir,
        check=False,
    )
    return tuple(existing)


def run_precommit_hook(
    project_dir: str,
    *,
    staged_paths: Sequence[str],
    environ: Mapping[str, str] | None = None,
    generate: Callable[[str], None] | None = None,
    git_add: Callable[[Sequence[str]], None] | None = None,
    commit_message: str = "",
    actor: str = "",
) -> HookRunResult:
    """Run the hook policy, optionally generate, then stage doc paths.

    ``generate`` is injected in tests. Production wires ``dhx run``.
    Missing credentials skip with exit-equivalent ``skipped=True`` (fail-open).
    """
    env = os.environ if environ is None else environ
    decision: HookDecision = should_run_hook(
        staged_paths,
        environ=env,
        commit_message=commit_message,
        actor=actor,
    )
    if not decision.run:
        return HookRunResult(skipped=True, reason=decision.reason, staged=())
    if generate is not None:
        generate(project_dir)
    staged = stage_doc_paths(project_dir, git_add=git_add)
    return HookRunResult(skipped=False, reason=decision.reason, staged=staged)
