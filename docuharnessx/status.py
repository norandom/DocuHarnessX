"""Coverage and sufficiency status for a project (task 4.1)."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from docuharnessx.adoption import load_adoption
from docuharnessx.analysis import analyze, scan
from docuharnessx.pages.model import Omission, OmissionReason
from docuharnessx.pages.store import FilesystemLivingPageStore
from docuharnessx.planning.questions import plan_questions

__all__ = ["CoverageStatus", "coverage_status", "format_coverage"]


@dataclass(frozen=True)
class CoverageStatus:
    blueprint_name: str | None
    blueprint_version: str | None
    planned_ids: tuple[str, ...]
    living_ids: tuple[str, ...]
    omitted: tuple[Omission, ...]
    missing_ids: tuple[str, ...]
    sufficient: bool
    sufficient_stale: bool


def coverage_status(
    project_dir: str, *, out_dir: str | None = None
) -> CoverageStatus:
    """Compute coverage for ``project_dir``. No model required."""
    record = load_adoption(project_dir)
    inventory = scan(project_dir)
    analysis = analyze(inventory)
    plan = plan_questions(analysis)
    planned_ids = tuple(question.id for question in plan.questions)
    store = FilesystemLivingPageStore(project_dir)
    living_ids = tuple(page.id for page in store.list() if page.id in set(planned_ids))
    report_dir = out_dir or os.path.join(project_dir, ".docuharnessx", "out")
    omitted = _omissions_from_report(report_dir)
    omitted_ids = {item.question_id for item in omitted}
    living_set = set(living_ids)
    missing_ids = tuple(
        item
        for item in planned_ids
        if item not in living_set and item not in omitted_ids
    )
    return CoverageStatus(
        blueprint_name=None if record is None else record.blueprint_name,
        blueprint_version=None if record is None else record.blueprint_version,
        planned_ids=planned_ids,
        living_ids=living_ids,
        omitted=omitted,
        missing_ids=missing_ids,
        sufficient=bool(record and record.sufficient and not record.sufficient_stale),
        sufficient_stale=bool(record and record.sufficient_stale),
    )


def format_coverage(status: CoverageStatus) -> str:
    if status.blueprint_version:
        blueprint = f"{status.blueprint_name} {status.blueprint_version}"
    else:
        blueprint = "none (project has not adopted a blueprint)"
    if status.sufficient_stale:
        sufficient = "stale"
    elif status.sufficient:
        sufficient = "yes"
    else:
        sufficient = "no"
    lines = [
        f"blueprint: {blueprint}",
        f"sufficient: {sufficient}",
        "planned:",
    ]
    lines.extend(f"  - {item}" for item in status.planned_ids or ("(none)",))
    lines.append("living:")
    lines.extend(f"  - {item}" for item in status.living_ids or ("(none)",))
    lines.append("omitted:")
    if status.omitted:
        lines.extend(
            f"  - {item.question_id}: {item.reason.value}" for item in status.omitted
        )
    else:
        lines.append("  - (none)")
    lines.append("missing:")
    lines.extend(f"  - {item}" for item in status.missing_ids or ("(none)",))
    lines.append("")
    return "\n".join(lines)


def _omissions_from_report(report_dir: str) -> tuple[Omission, ...]:
    path = Path(report_dir) / "report.json"
    if not path.is_file():
        return ()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ()
    rows = payload.get("omissions") or ()
    omissions: list[Omission] = []
    for row in rows:
        try:
            omissions.append(
                Omission(
                    question_id=str(row["question_id"]),
                    reason=OmissionReason(row["reason"]),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    return tuple(omissions)
