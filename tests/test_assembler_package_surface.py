"""Scaffold tests for task 1.1 (mkdocs-site-assembler).

Task 1.1 owns two observable contracts:

* **Runtime dependencies (Req 8.3)** — ``mkdocs`` and ``mkdocs-material`` are
  declared as project runtime dependencies (so a fresh-environment install pulls
  them in and the deploy stage can run ``mkdocs build``) and are importable in the
  current environment (they are already installed in ``.venv``).
* **Package scaffold** — the ``docuharnessx.assembler`` package exists with a
  single public namespace, mirroring the existing pure-core package layout
  (``review`` / ``composition`` / ``planning``): importing it succeeds and it
  exposes its (initially empty) public surface via a self-consistent ``__all__``.

Task 1.1 does NOT own the model, identity resolver, renderers, writer, or the
stage adapter — those live in later tasks. This file asserts only the scaffold +
dependency contract.
"""

from __future__ import annotations

import importlib
import importlib.metadata as md
import tomllib
from pathlib import Path

import pytest

_PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"


def _runtime_dependencies() -> list[str]:
    data = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))
    return list(data["project"]["dependencies"])


def _dep_names(deps: list[str]) -> set[str]:
    """Lower-cased distribution names from PEP 508 requirement strings."""
    names: set[str] = set()
    for dep in deps:
        # Drop URL specifiers, version specifiers, extras, and markers.
        token = dep.split("@", 1)[0]
        token = token.split(";", 1)[0]
        for sep in ("==", ">=", "<=", "~=", "!=", ">", "<", "["):
            token = token.split(sep, 1)[0]
        token = token.strip()
        if token:
            names.add(token.lower())
    return names


# --- Requirement 8.3: runtime dependency declaration -----------------------


@pytest.mark.parametrize("dep", ["mkdocs", "mkdocs-material"])
def test_runtime_dependency_declared(dep: str) -> None:
    # Req 8.3: the project declares mkdocs + mkdocs-material as runtime deps.
    assert dep in _dep_names(_runtime_dependencies()), (
        f"{dep!r} not declared in [project].dependencies"
    )


def test_dependency_declaration_is_idempotent_no_duplicates() -> None:
    # Declaring the deps must not duplicate an existing requirement.
    deps = _runtime_dependencies()
    names = [n for n in (_single_name(d) for d in deps) if n]
    assert len(names) == len(set(names)), f"duplicate dependency declarations: {names}"


def _single_name(dep: str) -> str:
    return next(iter(_dep_names([dep])), "")


@pytest.mark.parametrize(
    ("module", "distribution"),
    [("mkdocs", "mkdocs"), ("material", "mkdocs-material")],
)
def test_runtime_dependency_importable_and_installed(
    module: str, distribution: str
) -> None:
    # The declared deps are present in the environment (already installed in .venv).
    importlib.import_module(module)
    assert md.version(distribution)  # raises PackageNotFoundError if absent


# --- Package scaffold: single public namespace -----------------------------


def test_assembler_package_imports() -> None:
    pkg = importlib.import_module("docuharnessx.assembler")
    assert pkg is not None


def test_assembler_package_exposes_all() -> None:
    pkg = importlib.import_module("docuharnessx.assembler")
    assert hasattr(pkg, "__all__")
    assert isinstance(pkg.__all__, list)


def test_assembler_all_is_self_consistent_and_unique() -> None:
    # Every advertised name resolves on the package; no duplicates. (Initially empty.)
    pkg = importlib.import_module("docuharnessx.assembler")
    assert len(pkg.__all__) == len(set(pkg.__all__)), "duplicate names in __all__"
    for name in pkg.__all__:
        assert hasattr(pkg, name), f"__all__ advertises {name!r} but it is not present"


def test_assembler_star_import_exposes_exactly_all() -> None:
    pkg = importlib.import_module("docuharnessx.assembler")
    namespace: dict[str, object] = {}
    exec("from docuharnessx.assembler import *", namespace)  # noqa: S102
    exported = {k for k in namespace if not k.startswith("__")}
    assert exported == set(pkg.__all__)
