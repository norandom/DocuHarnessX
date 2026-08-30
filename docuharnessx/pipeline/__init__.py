"""Explore-first documentation pipeline.

Public surface at this task: the frozen :class:`RunReport` and helpers that
serialize it to JSON and write ``report.json`` / ``report.md`` under an
output directory. Page bodies are never included.
"""

from __future__ import annotations

from docuharnessx.pipeline.report import (
    RunReport,
    to_dict,
    to_json,
    to_markdown,
    write_run_report,
)

__all__ = [
    "RunReport",
    "to_dict",
    "to_json",
    "to_markdown",
    "write_run_report",
]
