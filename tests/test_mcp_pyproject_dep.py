"""Task 5.1 (docuharnessx-mcp-refine): the ``mcp`` SDK direct dependency.

Requirement 1.4 — this feature makes the MCP SDK a **direct** runtime
dependency of ``docuharnessx`` (the stdio server is built on the low-level
``mcp.server`` API). The SDK is importable in the working venv (1.28.0) today
only because HarnessX pulls it in transitively for its MCP *client*; relying on
a transitive dep is fragile, so ``mcp>=1.28`` must be declared directly in
``[project].dependencies`` — a version floor matching the existing
``mkdocs>=1.6`` style, with no upper pin. This is the only build-config change
for the feature.

Observable completion: ``pyproject.toml`` lists ``mcp>=1.28`` as a direct
dependency and a fresh install resolves it (offline: importing ``mcp.server``
succeeds against the declared floor).
"""

from __future__ import annotations

import importlib.metadata as md
import tomllib
from pathlib import Path

from packaging.requirements import Requirement
from packaging.version import Version

_PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"

_DEP_NAME = "mcp"
_DEP_FLOOR = Version("1.28")


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


def _mcp_requirement() -> str:
    for dep in _runtime_dependencies():
        if _dep_name(dep) == _DEP_NAME:
            return dep
    raise AssertionError(
        f"{_DEP_NAME!r} not declared in [project].dependencies: "
        f"{_runtime_dependencies()}"
    )


# --- Requirement 1.4: direct runtime dependency declaration ---------------


def test_mcp_dependency_declared() -> None:
    # Req 1.4: ``mcp`` is declared directly in [project].dependencies.
    assert _DEP_NAME in _dep_names(_runtime_dependencies()), (
        f"{_DEP_NAME!r} not declared in [project].dependencies"
    )


def test_mcp_dependency_declared_once() -> None:
    # Declared exactly once: no duplicate / rewritten requirement.
    names = _dep_names(_runtime_dependencies())
    assert names.count(_DEP_NAME) == 1, (
        f"{_DEP_NAME!r} must be declared exactly once, found "
        f"{names.count(_DEP_NAME)}: {names}"
    )


def test_runtime_dependency_declarations_are_unique() -> None:
    # Adding the mcp dep does not duplicate any existing declaration.
    names = _dep_names(_runtime_dependencies())
    assert len(names) == len(set(names)), (
        f"duplicate dependency declarations: {names}"
    )


def test_mcp_dependency_has_version_floor_no_upper_pin() -> None:
    # Req 1.4: a ``>=1.28`` floor (mkdocs>=1.6 style) with no upper pin.
    req = Requirement(_mcp_requirement())
    specifiers = list(req.specifier)
    assert specifiers, f"{_DEP_NAME!r} must carry a version floor: {req!r}"
    assert all(spec.operator == ">=" for spec in specifiers), (
        f"{_DEP_NAME!r} must use a `>=` floor with no upper pin: {req!r}"
    )
    # The declared floor is exactly 1.28 (no laxer, no stricter than the task).
    floors = {Version(spec.version) for spec in specifiers if spec.operator == ">="}
    assert _DEP_FLOOR in floors, (
        f"{_DEP_NAME!r} floor must be >={_DEP_FLOOR}: {req!r}"
    )


# --- Observable completion: a resolved install satisfies the declared floor --


def test_declared_mcp_dependency_resolves_in_environment() -> None:
    # A resolved install carries the ``mcp`` distribution at/above the floor.
    installed = Version(md.version(_DEP_NAME))  # PackageNotFoundError if absent
    assert installed >= _DEP_FLOOR, (
        f"installed mcp {installed} is below the declared floor {_DEP_FLOOR}"
    )


def test_mcp_server_module_is_importable() -> None:
    # Observable completion: ``mcp.server`` imports against the declared floor
    # (the low-level server API the feature builds on), with no network.
    import mcp.server  # noqa: F401

    assert md.version(_DEP_NAME)  # the import resolved the declared distribution
