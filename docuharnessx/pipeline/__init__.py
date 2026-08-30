"""Explore-first documentation pipeline.

Public surface: :func:`run_pipeline`, :class:`RunOutcome`, and the frozen
:class:`RunReport` helpers that serialize counts and omissions. Page bodies
are never included.
"""

from __future__ import annotations

from docuharnessx.pipeline.report import (
    RunReport,
    to_dict,
    to_json,
    to_markdown,
    write_run_report,
)
from docuharnessx.pipeline.run import RunOutcome, run_pipeline

__all__ = [
    "RunOutcome",
    "RunReport",
    "run_pipeline",
    "to_dict",
    "to_json",
    "to_markdown",
    "write_run_report",
]
