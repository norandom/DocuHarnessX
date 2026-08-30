"""Frozen run-report values and serialize / write helpers (task 1.2).

This module is the **RunReport boundary**: operator counts, planned question
ids, and closed-set omissions. Serialize emits JSON (machine) and Markdown
(human) with those fields only — **never page bodies** (Req 9.1, 9.2, 9.3).

Design constraints (design "RunReport" / "Data Models")
-------------------------------------------------------
* :class:`RunReport` is a ``@dataclass(frozen=True)`` value object.
* Collection fields are ``tuple[...]``.
* Invariants (enforced in the constructor): ``planned == accepted + omitted``,
  ``planned == len(questions)``, and ``omitted == len(omissions)``.
* Payloads contain counts, question ids, and omission reasons only.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from docuharnessx.pages.model import Omission, QuestionId

__all__ = [
    "RunReport",
    "to_dict",
    "to_json",
    "to_markdown",
    "write_run_report",
]


@dataclass(frozen=True)
class RunReport:
    """Operator-facing result of one documentation run.

    Carries counts, planned question ids, and omissions. It does not carry
    page bodies, roles, or intent.
    """

    planned: int
    accepted: int
    omitted: int
    questions: tuple[QuestionId, ...]
    omissions: tuple[Omission, ...]

    def __post_init__(self) -> None:
        if self.planned < 0 or self.accepted < 0 or self.omitted < 0:
            raise ValueError(
                "planned, accepted, and omitted must be non-negative"
            )
        if self.planned != self.accepted + self.omitted:
            raise ValueError(
                f"planned ({self.planned}) must equal accepted "
                f"({self.accepted}) + omitted ({self.omitted})"
            )
        if self.planned != len(self.questions):
            raise ValueError(
                f"planned ({self.planned}) must equal len(questions) "
                f"({len(self.questions)})"
            )
        if self.omitted != len(self.omissions):
            raise ValueError(
                f"omitted ({self.omitted}) must equal len(omissions) "
                f"({len(self.omissions)})"
            )


def to_dict(report: RunReport) -> dict[str, Any]:
    """Plain JSON-compatible dict of counts, question ids, and omissions."""
    return {
        "planned": report.planned,
        "accepted": report.accepted,
        "omitted": report.omitted,
        "questions": list(report.questions),
        "omissions": [
            {"question_id": omission.question_id, "reason": omission.reason.value}
            for omission in report.omissions
        ],
    }


def to_json(report: RunReport) -> str:
    """Byte-stable JSON for ``report`` (``sort_keys=True``; no page bodies)."""
    return json.dumps(to_dict(report), sort_keys=True, ensure_ascii=False)


def to_markdown(report: RunReport) -> str:
    """Human-readable report: counts, question ids, omission reasons."""
    lines = [
        "# Run report",
        "",
        f"- planned: {report.planned}",
        f"- accepted: {report.accepted}",
        f"- omitted: {report.omitted}",
        "",
        "## Questions",
        "",
    ]
    if report.questions:
        lines.extend(f"- `{question_id}`" for question_id in report.questions)
    else:
        lines.append("(none)")
    lines.extend(["", "## Omissions", ""])
    if report.omissions:
        lines.extend(
            f"- `{omission.question_id}`: {omission.reason.value}"
            for omission in report.omissions
        )
    else:
        lines.append("(none)")
    lines.append("")
    return "\n".join(lines)


def write_run_report(report: RunReport, out_dir: str | Path) -> None:
    """Write ``report.json`` and ``report.md`` under ``out_dir``. No bodies."""
    dest = Path(out_dir)
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "report.json").write_text(to_json(report) + "\n", encoding="utf-8")
    (dest / "report.md").write_text(to_markdown(report), encoding="utf-8")
