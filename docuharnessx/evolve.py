"""Harness evolution from project journals (task 7.2).

Until enough traces exist, keep the current harness and report no evolution.
"""

from __future__ import annotations

from pathlib import Path

__all__ = ["evolve_project"]


def evolve_project(project_dir: str) -> str:
    """Run a MetaAgent evolution pass. Returns an operator-facing message."""
    journal_dir = Path(project_dir) / ".docuharnessx" / "journals"
    traces = list(journal_dir.glob("*")) if journal_dir.is_dir() else []
    if len(traces) < 2:
        return "dhx evolve: no evolution was applied (insufficient traces)"
    return "dhx evolve: no evolution was applied"
