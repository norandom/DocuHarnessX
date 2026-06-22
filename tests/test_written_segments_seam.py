"""Tests for the written-segments output seam (cobesy-writer task 1.2).

Task 1.2 is an **append-only** extension of two ``harness-bundle-skeleton``-owned
modules so the Wave 2 ``quality-review-gate`` can consume exactly the segments the
writer produced:

* ``docuharnessx/types.py`` gains the ``SLOT_WRITTEN_SEGMENTS`` slot-key constant
  (added to ``__all__``), changing no existing slot key, ``StageName``, or
  ``STAGE_NAMES`` entry (Req 7.2).
* ``docuharnessx/context.py`` gains the ``set_written_segments()`` /
  ``written_segments()`` accessor pair, which returns an explicit ``None`` before
  the Write Stage has run (Req 7.1, 7.3) and round-trips a ``WrittenSegments``
  value object (Req 7.4, 7.5).

These tests pin only the seam contract for this task's boundary (types/context
additions); the publishing behaviour lives in the WriteStage (later tasks).
"""

from __future__ import annotations

import importlib
import typing

from harnessx.core.state import State

from docuharnessx.composition import WrittenSegments
from docuharnessx.context import RunContext
from docuharnessx.types import SLOT_WRITTEN_SEGMENTS

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


def _written(total: int = 0) -> WrittenSegments:
    """A minimal, model-free WrittenSegments value object for round-trip tests."""
    return WrittenSegments(segments=(), flags=(), total_planned=total)


# --------------------------------------------------------------------------- #
# types.py — the append-only SLOT_WRITTEN_SEGMENTS slot key (Req 7.2)          #
# --------------------------------------------------------------------------- #


def test_written_segments_slot_key_exists_with_pinned_value() -> None:
    mod = importlib.import_module("docuharnessx.types")
    assert hasattr(mod, "SLOT_WRITTEN_SEGMENTS")
    value = mod.SLOT_WRITTEN_SEGMENTS
    assert isinstance(value, str)
    assert value == "docuharnessx.written_segments"


def test_written_segments_slot_key_in_all_exports() -> None:
    mod = importlib.import_module("docuharnessx.types")
    assert "SLOT_WRITTEN_SEGMENTS" in set(mod.__all__)


def test_written_segments_slot_key_distinct_from_existing() -> None:
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
    ]
    assert len(set(values)) == len(values), "slot keys must be unique"


def test_existing_slot_keys_and_stage_names_unchanged_by_extension() -> None:
    """Appending the new key leaves existing keys + StageName/STAGE_NAMES intact."""
    mod = importlib.import_module("docuharnessx.types")
    assert mod.SLOT_TARGET_REPO == "docuharnessx.target_repo"
    assert mod.SLOT_OUTPUT_DIR == "docuharnessx.output_dir"
    assert mod.SLOT_SEGMENT_STORE == "docuharnessx.segment_store"
    assert mod.SLOT_VOCABULARY == "docuharnessx.vocabulary"
    assert mod.SLOT_COVERAGE_PLAN == "docuharnessx.coverage_plan"
    assert tuple(typing.get_args(mod.StageName)) == CANONICAL_STAGES
    assert tuple(mod.STAGE_NAMES) == CANONICAL_STAGES


# --------------------------------------------------------------------------- #
# context.py — the append-only written_segments accessor pair (Req 7.1, 7.3)  #
# --------------------------------------------------------------------------- #


def test_absent_written_segments_returns_none() -> None:
    """Reading the slot before the Write Stage runs returns None (Req 7.3)."""
    assert RunContext(_state()).written_segments() is None


def test_written_segments_round_trip() -> None:
    """A stored WrittenSegments is read back as the same instance (Req 7.4)."""
    ctx = RunContext(_state())
    assert ctx.written_segments() is None  # explicit unset before set (Req 7.3)
    value = _written(total=3)
    ctx.set_written_segments(value)
    assert ctx.written_segments() is value


def test_written_segments_written_through_named_slot() -> None:
    """The accessor writes through the shared SLOT_WRITTEN_SEGMENTS key (Req 7.2)."""
    state = _state()
    value = _written()
    RunContext(state).set_written_segments(value)
    slot = state.get_slot(SLOT_WRITTEN_SEGMENTS)
    assert slot is not None
    assert slot.content is value


def test_written_segments_preserves_plan_order_view() -> None:
    """The seam round-trips the ordered segments/flags view verbatim (Req 7.5)."""
    from docuharnessx.composition import WriteFlag

    flag = WriteFlag(segment_key="k", reason="validation", cause="bad")
    value = WrittenSegments(segments=(), flags=(flag,), total_planned=2)
    ctx = RunContext(_state())
    ctx.set_written_segments(value)
    retrieved = ctx.written_segments()
    assert retrieved is value
    assert retrieved.flags == (flag,)
    assert retrieved.total_planned == 2
