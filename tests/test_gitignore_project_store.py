"""Tests for gitignore of the project documentation store (task 1.4, boundary: ProjectStore).

Pins that the project-local documentation store is eligible for version control:

* ``.env`` stays ignored (Req 12.6).
* Journals are not hidden from version control (Req 13.2).
* Journals, ontology, living pages, the adoption record, and harness snapshots
  remain eligible while throwaway ``.docuharnessx/out/`` is ignored (Req 13.3).

These tests run ``git check-ignore`` against ignore *patterns* from the
repository root (the directory that contains ``.gitignore`` and ``.git``). The
named files need not exist. They touch no model and no network.
"""

from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

# Paths that must stay eligible for version control (Req 13.2, 13.3).
_TRACKED_STORE_PATHS = (
    ".docuharnessx/journals/example.jsonl",
    ".docuharnessx/pages/example.md",
    ".docuharnessx/ontology.yaml",
    ".docuharnessx/adoption.yaml",
    ".docuharnessx/harnesses/snapshot.yaml",
)

# Existing ignore rules this change must not drop.
_STILL_IGNORED_PATHS = (
    "__pycache__/mod.pyc",
    ".venv/bin/python",
    "site/index.html",
    "_docs_out/report.json",
)


def _repo_root() -> Path:
    for candidate in Path(__file__).resolve().parents:
        if (candidate / ".gitignore").is_file() and (candidate / ".git").exists():
            return candidate
    raise AssertionError("could not locate repository root (.gitignore + .git)")


def _check_ignore(path: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "check-ignore", "-q", path],
        cwd=_repo_root(),
        capture_output=True,
        text=True,
        check=False,
    )


def _assert_ignored(path: str) -> None:
    completed = _check_ignore(path)
    assert completed.returncode == 0, (
        f"{path!r} should be ignored (git check-ignore -q exits 0); "
        f"got {completed.returncode}\nSTDERR:\n{completed.stderr}"
    )


def _assert_not_ignored(path: str) -> None:
    completed = _check_ignore(path)
    assert completed.returncode == 1, (
        f"{path!r} should not be ignored (git check-ignore -q exits 1); "
        f"got {completed.returncode}\nSTDERR:\n{completed.stderr}"
    )


def test_env_is_ignored() -> None:
    # Req 12.6: accepted credentials live only in the project's .env, which
    # remains ignored by version control.
    _assert_ignored(".env")


def test_journal_is_not_ignored() -> None:
    # Req 13.2: the journal path is not hidden from version control.
    # The file need not exist; check-ignore matches patterns.
    _assert_not_ignored(".docuharnessx/journals/example.jsonl")


def test_throwaway_out_is_ignored() -> None:
    # Req 13.3: throwaway assemble/report output stays ignored.
    _assert_ignored(".docuharnessx/out/report.json")


@pytest.mark.parametrize("path", _TRACKED_STORE_PATHS)
def test_project_store_artifacts_are_not_ignored(path: str) -> None:
    # Req 13.3: journals, ontology, living pages, the adoption record, and
    # harness snapshots remain eligible for version control.
    _assert_not_ignored(path)


@pytest.mark.parametrize("path", _STILL_IGNORED_PATHS)
def test_other_ignore_rules_remain(path: str) -> None:
    _assert_ignored(path)
