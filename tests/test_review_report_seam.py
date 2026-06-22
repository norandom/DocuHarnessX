"""Tests for the review-report output seam (quality-review-gate task 1.3).

Task 1.3 is an **append-only** extension of two ``harness-bundle-skeleton``-owned
modules so the Wave 3 ``mkdocs-site-assembler`` can consume exactly the segments
that passed the COBESY gate:

* ``docuharnessx/types.py`` gains the ``SLOT_REVIEW_REPORT`` slot-key constant
  (added to ``__all__``), changing no existing slot key, ``StageName``, or
  ``STAGE_NAMES`` entry (Req 7.2).
* ``docuharnessx/context.py`` gains the ``set_review_report()`` /
  ``review_report()`` accessor pair, which returns an explicit ``None`` before the
  Review Stage has run (Req 7.1, 7.3) and round-trips a ``ReviewReport`` value
  object.

These tests pin only the seam contract for this task's boundary (types/context
additions); the publishing behaviour lives in the ReviewStage (later tasks).
"""

from __future__ import annotations

import importlib
import typing

from harnessx.core.state import State

from docuharnessx.context import RunContext
from docuharnessx.review import (
    REVIEW_REPORT_SCHEMA_VERSION,
    ReviewAggregate,
    ReviewReport,
)
from docuharnessx.types import SLOT_REVIEW_REPORT

CANONICAL_STAGES = (
    "ingest",
    "analyze",
    "classify",
    "plan",
    "write",
    "review",
    "assemble",
    "deploy",
)


def _state() -> State:
    return State(run_id="test-run")


def _empty_aggregate() -> ReviewAggregate:
    return ReviewAggregate(
        judged=0,
        accepted=0,
        rejected=0,
        unavailable=0,
        criterion_tally=(),
    )


def _report() -> ReviewReport:
    """A minimal, model-free ReviewReport value object for round-trip tests."""
    return ReviewReport(
        schema_version=REVIEW_REPORT_SCHEMA_VERSION,
        entries=(),
        accepted=(),
        aggregate=_empty_aggregate(),
    )


# --------------------------------------------------------------------------- #
# types.py — the append-only SLOT_REVIEW_REPORT slot key (Req 7.2)             #
# --------------------------------------------------------------------------- #


def test_review_report_slot_key_exists_with_pinned_value() -> None:
    mod = importlib.import_module("docuharnessx.types")
    assert hasattr(mod, "SLOT_REVIEW_REPORT")
    value = mod.SLOT_REVIEW_REPORT
    assert isinstance(value, str)
    assert value == "docuharnessx.review_report"


def test_review_report_slot_key_in_all_exports() -> None:
    mod = importlib.import_module("docuharnessx.types")
    assert "SLOT_REVIEW_REPORT" in set(mod.__all__)


def test_review_report_slot_key_distinct_from_existing() -> None:
    """The new key must not collide with any pre-existing slot key."""
    mod = importlib.import_module("docuharnessx.types")
    values = [
        mod.SLOT_TARGET_REPO,
        mod.SLOT_OUTPUT_DIR,
        mod.SLOT_SEGMENT_STORE,
        mod.SLOT_VOCABULARY,
        mod.SLOT_FILE_INVENTORY,
        mod.SLOT_REPO_ANALYSIS,
        mod.SLOT_CLASSIFICATION,
        mod.SLOT_COVERAGE_PLAN,
        mod.SLOT_WRITTEN_SEGMENTS,
        mod.SLOT_REVIEW_REPORT,
    ]
    assert len(set(values)) == len(values), "slot keys must be unique"


def test_existing_slot_keys_and_stage_names_unchanged_by_extension() -> None:
    """Appending the new key leaves existing keys + StageName/STAGE_NAMES intact."""
    mod = importlib.import_module("docuharnessx.types")
    assert mod.SLOT_TARGET_REPO == "docuharnessx.target_repo"
    assert mod.SLOT_OUTPUT_DIR == "docuharnessx.output_dir"
    assert mod.SLOT_SEGMENT_STORE == "docuharnessx.segment_store"
    assert mod.SLOT_VOCABULARY == "docuharnessx.vocabulary"
    assert mod.SLOT_FILE_INVENTORY == "docuharnessx.file_inventory"
    assert mod.SLOT_REPO_ANALYSIS == "docuharnessx.repo_analysis"
    assert mod.SLOT_CLASSIFICATION == "docuharnessx.classification"
    assert mod.SLOT_COVERAGE_PLAN == "docuharnessx.coverage_plan"
    assert mod.SLOT_WRITTEN_SEGMENTS == "docuharnessx.written_segments"
    assert tuple(typing.get_args(mod.StageName)) == CANONICAL_STAGES
    assert tuple(mod.STAGE_NAMES) == CANONICAL_STAGES


# --------------------------------------------------------------------------- #
# context.py — the append-only review_report accessor pair (Req 7.1, 7.3)     #
# --------------------------------------------------------------------------- #


def test_absent_review_report_returns_none() -> None:
    """Reading the slot before the Review Stage runs returns None (Req 7.3)."""
    assert RunContext(_state()).review_report() is None


def test_review_report_round_trip() -> None:
    """A stored ReviewReport is read back as the same instance (Req 7.1)."""
    ctx = RunContext(_state())
    assert ctx.review_report() is None  # explicit unset before set (Req 7.3)
    value = _report()
    ctx.set_review_report(value)
    assert ctx.review_report() is value


def test_review_report_written_through_named_slot() -> None:
    """The accessor writes through the shared SLOT_REVIEW_REPORT key (Req 7.2)."""
    state = _state()
    value = _report()
    RunContext(state).set_review_report(value)
    slot = state.get_slot(SLOT_REVIEW_REPORT)
    assert slot is not None
    assert slot.content is value


def test_review_report_preserves_schema_and_aggregate_view() -> None:
    """The seam round-trips the versioned report + aggregate verbatim (Req 7.5, 7.6)."""
    aggregate = ReviewAggregate(
        judged=2,
        accepted=1,
        rejected=1,
        unavailable=0,
        criterion_tally=(),
    )
    value = ReviewReport(
        schema_version=REVIEW_REPORT_SCHEMA_VERSION,
        entries=(),
        accepted=(),
        aggregate=aggregate,
    )
    ctx = RunContext(_state())
    ctx.set_review_report(value)
    retrieved = ctx.review_report()
    assert retrieved is value
    assert retrieved.schema_version == REVIEW_REPORT_SCHEMA_VERSION
    assert retrieved.aggregate is aggregate
    assert retrieved.aggregate.judged == 2


# --------------------------------------------------------------------------- #
# Independence from the other slot accessors (append-only, no regression)      #
# --------------------------------------------------------------------------- #


def test_review_report_slot_independent_from_written_segments() -> None:
    """Setting the review-report slot does not disturb sibling accessors."""
    ctx = RunContext(_state())
    ctx.set_review_report(_report())
    assert ctx.written_segments() is None
    assert ctx.coverage_plan() is None
    assert ctx.vocabulary() is None
