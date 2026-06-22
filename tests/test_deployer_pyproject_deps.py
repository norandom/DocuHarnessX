"""Task 1.3 (github-pages-deploy): mkdocs runtime dependency declaration.

Requirement 9.3 — the project shall declare ``mkdocs`` and ``mkdocs-material``
as runtime dependencies, so a fresh-environment install resolves them and the
``mkdocs`` CLI is invocable (the deploy stage runs ``mkdocs build`` /
``mkdocs gh-deploy`` as subprocesses).

These deps were first declared by the ``mkdocs-site-assembler`` spec (which emits
the buildable MkDocs tree). Task 1.3 is **idempotent** with that prior
declaration: this file asserts the deploy spec's own observable contract — the
deps are present, declared exactly once (no duplicate/rewrite), and the ``mkdocs``
CLI is invocable in the current environment — without re-declaring or rewriting
the existing requirement.
"""

from __future__ import annotations

import importlib.metadata as md
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

_PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"

_REQUIRED_DEPS = ("mkdocs", "mkdocs-material")


def _runtime_dependencies() -> list[str]:
    data = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))
    return list(data["project"]["dependencies"])


def _dep_name(requirement: str) -> str:
    """Lower-cased distribution name from a PEP 508 requirement string."""
    token = requirement.split("@", 1)[0]
    token = token.split(";", 1)[0]
    for sep in ("==", ">=", "<=", "~=", "!=", ">", "<", "["):
        token = token.split(sep, 1)[0]
    return token.strip().lower()


def _dep_names(deps: list[str]) -> list[str]:
    return [name for name in (_dep_name(dep) for dep in deps) if name]


# --- Requirement 9.3: runtime dependency declaration -----------------------


@pytest.mark.parametrize("dep", _REQUIRED_DEPS)
def test_mkdocs_dependency_declared(dep: str) -> None:
    # Req 9.3: mkdocs + mkdocs-material are declared in [project].dependencies.
    assert dep in _dep_names(_runtime_dependencies()), (
        f"{dep!r} not declared in [project].dependencies"
    )


@pytest.mark.parametrize("dep", _REQUIRED_DEPS)
def test_mkdocs_dependency_declared_once_idempotent(dep: str) -> None:
    # Idempotent with the assembler's prior declaration: declared exactly once,
    # never duplicated or rewritten by this spec.
    names = _dep_names(_runtime_dependencies())
    assert names.count(dep) == 1, (
        f"{dep!r} must be declared exactly once, found {names.count(dep)}: {names}"
    )


def test_runtime_dependency_declarations_are_unique() -> None:
    # No dependency (mkdocs or otherwise) is declared more than once.
    names = _dep_names(_runtime_dependencies())
    assert len(names) == len(set(names)), f"duplicate dependency declarations: {names}"


# --- Observable completion: a fresh install resolves the deps + CLI works ---


@pytest.mark.parametrize(
    ("module", "distribution"),
    [("mkdocs", "mkdocs"), ("mkdocs.commands.build", "mkdocs-material")],
)
def test_declared_dependency_resolves_in_environment(
    module: str, distribution: str
) -> None:
    # A resolved install carries the declared distribution (already in .venv).
    assert md.version(distribution)  # raises PackageNotFoundError if absent


def test_mkdocs_cli_is_invocable() -> None:
    # Observable completion: the ``mkdocs`` CLI is invocable (no network).
    result = subprocess.run(
        [sys.executable, "-m", "mkdocs", "--version"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"`mkdocs --version` failed (rc={result.returncode}):\n"
        f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
    )
    assert "mkdocs" in (result.stdout + result.stderr).lower()
