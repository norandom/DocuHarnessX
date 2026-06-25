"""Scaffold tests for task 1.1 (docuharnessx-mcp-refine).

Task 1.1 owns one observable contract: the ``docuharnessx.mcp`` package exists as
the **single public namespace** for the MCP refine server, mirroring the existing
pure-core package layout (``assembler`` / ``composition`` / ``review`` / ``planning``).
Importing it succeeds and it exposes its public surface via a self-consistent
``__all__`` (initially empty — later tasks populate it as each module lands:
``resolve_session`` / ``RefineSession`` (1.2), ``build_refine_server`` / ``run_stdio``
(4.1/4.2), and the eight tool handlers (3.x)).

Task 1.1 introduces **no behaviour beyond importability**: it does NOT own the
session, the resolver, the server factory, the launcher, or the handlers — those
arrive in later tasks. This file asserts only the package scaffold + single-namespace
contract (Req 1.1, 1.4, 1.5).
"""

from __future__ import annotations

import importlib


def test_mcp_package_imports() -> None:
    # Req 1.1 / 1.5: the single MCP package namespace exists and imports cleanly,
    # introducing no behaviour (and no eager model/network/SDK dependency) on import.
    pkg = importlib.import_module("docuharnessx.mcp")
    assert pkg is not None


def test_mcp_package_exposes_all() -> None:
    # Req 1.5: the package advertises its public surface via __all__ (a list).
    pkg = importlib.import_module("docuharnessx.mcp")
    assert hasattr(pkg, "__all__")
    assert isinstance(pkg.__all__, list)


def test_mcp_all_is_self_consistent_and_unique() -> None:
    # Every advertised name resolves on the package; no duplicates. (Initially empty;
    # later tasks fill it.) This is the authoritative, self-consistent package contract.
    pkg = importlib.import_module("docuharnessx.mcp")
    assert len(pkg.__all__) == len(set(pkg.__all__)), "duplicate names in __all__"
    for name in pkg.__all__:
        assert hasattr(pkg, name), f"__all__ advertises {name!r} but it is not present"


def test_mcp_star_import_exposes_exactly_all() -> None:
    # A star-import surfaces exactly the names in __all__ — no leakage, no shortfall.
    pkg = importlib.import_module("docuharnessx.mcp")
    namespace: dict[str, object] = {}
    exec("from docuharnessx.mcp import *", namespace)  # noqa: S102
    exported = {k for k in namespace if not k.startswith("__")}
    assert exported == set(pkg.__all__)
