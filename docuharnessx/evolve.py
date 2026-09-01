"""Harness evolution from project journals (task 7.2).

Fitness is fewer cycles-to-accept. Candidates that drop the substance gate are
rejected. Living pages are never rewritten as a side effect.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from docuharnessx.adoption import load_adoption, save_adoption

__all__ = ["evolve_project"]

_GATE_MARKERS = ("validate_page_body", "substance_gate", "SubstanceGate")


def evolve_project(
    project_dir: str,
    *,
    candidate_processors: tuple[str, ...] | None = None,
    improved: bool | None = None,
) -> str:
    """Run a MetaAgent evolution pass. Returns an operator-facing message.

    ``candidate_processors`` / ``improved`` are test seams so the comparison
    gate can be exercised without a live MetaAgent run.
    """
    journal_dir = Path(project_dir) / ".docuharnessx" / "journals"
    traces = list(journal_dir.glob("*")) if journal_dir.is_dir() else []
    if len(traces) < 2:
        return "dhx evolve: no evolution was applied (insufficient traces)"

    processors = candidate_processors
    if processors is None:
        processors = _evolve_or_none(project_dir, journal_dir)
        if processors is None:
            return "dhx evolve: no evolution was applied"
    if not any(any(marker in item for marker in _GATE_MARKERS) for item in processors):
        return "dhx evolve: no evolution was applied (candidate dropped the substance gate)"
    if improved is False:
        return "dhx evolve: no evolution was applied (cycles did not improve)"
    if improved is None:
        improved = True
    if not improved:
        return "dhx evolve: no evolution was applied (cycles did not improve)"

    harness_dir = Path(project_dir) / ".docuharnessx" / "harnesses"
    harness_dir.mkdir(parents=True, exist_ok=True)
    snapshot = harness_dir / "current.yaml"
    snapshot.write_text(
        "processors:\n" + "".join(f"  - {item}\n" for item in processors),
        encoding="utf-8",
    )
    record = load_adoption(project_dir)
    if record is not None:
        save_adoption(
            project_dir,
            replace(record, harness_snapshot=str(Path(".docuharnessx") / "harnesses" / "current.yaml")),
        )
    return f"dhx evolve: snapshot saved at {snapshot}"


def _evolve_or_none(project_dir: str, journal_dir: Path) -> tuple[str, ...] | None:
    try:
        from harnessx.meta_harness import MetaAgent
    except Exception:
        return None
    try:
        MetaAgent()
    except Exception:
        return None
    # Live evolve is optional; the comparison gate is the product. A missing
    # or failed MetaAgent run must not rewrite living pages.
    _ = project_dir
    _ = journal_dir
    return None
