"""Tests for the classification-coverage-planner harness seams (task 4.1).

Task 4.1 extends two ``harness-bundle-skeleton``-owned modules append-only:

* ``docuharnessx.types`` gains the internal Classify -> Plan handoff slot
  ``SLOT_CLASSIFICATION`` and the frozen output slot ``SLOT_COVERAGE_PLAN``,
  both added to ``__all__`` with no existing constant / ``StageName`` /
  ``STAGE_NAMES`` entry modified (Req 7.1, 7.5).
* ``docuharnessx.context.RunContext`` gains two accessor pairs mirroring the
  existing slot-type-tag + ``_get_content`` style:
  ``set_classification`` / ``classification`` and
  ``set_coverage_plan`` / ``coverage_plan``. Each getter returns ``None`` when
  its slot is unset (Req 7.2, 7.4) and no existing accessor changes.

These are the boundary for task 4.1: types + context only. The slots are
content-agnostic at this seam, so opaque sentinels exercise round-trip fidelity
without coupling these tests to the planning model's shape (built elsewhere).
"""

from __future__ import annotations

import importlib
import typing

import pytest
from harnessx.core.state import State

from docuharnessx.context import RunContext
from docuharnessx.types import (
    SLOT_CLASSIFICATION,
    SLOT_COVERAGE_PLAN,
)

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

# Pre-existing slot keys whose values must be left intact by the extension.
PREEXISTING_SLOTS = {
    "SLOT_TARGET_REPO": "docuharnessx.target_repo",
    "SLOT_OUTPUT_DIR": "docuharnessx.output_dir",
    "SLOT_SEGMENT_STORE": "docuharnessx.segment_store",
    "SLOT_VOCABULARY": "docuharnessx.vocabulary",
    "SLOT_FILE_INVENTORY": "docuharnessx.file_inventory",
    "SLOT_REPO_ANALYSIS": "docuharnessx.repo_analysis",
}


def _state() -> State:
    return State(run_id="test-run")


# --------------------------------------------------------------------------- #
# types.py — the two new append-only slot keys (Req 7.1)                       #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "const_name, expected_value",
    [
        ("SLOT_CLASSIFICATION", "docuharnessx.classification"),
        ("SLOT_COVERAGE_PLAN", "docuharnessx.coverage_plan"),
    ],
)
def test_new_planner_slot_keys_exist_with_pinned_values(
    const_name: str, expected_value: str
) -> None:
    """The handoff + output slot keys carry their frozen design values."""
    mod = importlib.import_module("docuharnessx.types")
    assert hasattr(mod, const_name), f"missing slot-key constant {const_name}"
    value = getattr(mod, const_name)
    assert isinstance(value, str)
    assert value == expected_value


def test_new_planner_slot_keys_in_all_exports() -> None:
    mod = importlib.import_module("docuharnessx.types")
    exported = set(mod.__all__)
    assert "SLOT_CLASSIFICATION" in exported
    assert "SLOT_COVERAGE_PLAN" in exported


def test_all_slot_keys_distinct_including_planner_ones() -> None:
    """Adding the planner keys must not collide with any pre-existing key."""
    mod = importlib.import_module("docuharnessx.types")
    values = [getattr(mod, name) for name in PREEXISTING_SLOTS]
    values.append(mod.SLOT_CLASSIFICATION)
    values.append(mod.SLOT_COVERAGE_PLAN)
    assert len(set(values)) == len(values), "slot keys must be unique"


def test_preexisting_slot_keys_unchanged_by_planner_extension() -> None:
    """Appending the planner keys leaves every pre-existing key value intact."""
    mod = importlib.import_module("docuharnessx.types")
    for name, expected in PREEXISTING_SLOTS.items():
        assert getattr(mod, name) == expected


def test_stagename_and_stage_names_unchanged_by_planner_extension() -> None:
    """StageName and STAGE_NAMES are untouched by the append-only additions."""
    mod = importlib.import_module("docuharnessx.types")
    assert tuple(typing.get_args(mod.StageName)) == CANONICAL_STAGES
    assert tuple(mod.STAGE_NAMES) == CANONICAL_STAGES


# --------------------------------------------------------------------------- #
# context.py — classification handoff accessor pair (Req 7.2, 7.4)            #
# --------------------------------------------------------------------------- #


def test_absent_classification_returns_none() -> None:
    """Reading the classification slot before Classify runs returns None."""
    assert RunContext(_state()).classification() is None


def test_classification_round_trip() -> None:
    ctx = RunContext(_state())
    assert ctx.classification() is None  # explicit unset before set (Req 7.4)
    classification = object()  # opaque handoff value; slot is content-agnostic
    ctx.set_classification(classification)
    assert ctx.classification() is classification


def test_classification_written_through_named_slot() -> None:
    state = _state()
    classification = object()
    RunContext(state).set_classification(classification)
    assert state.get_slot(SLOT_CLASSIFICATION) is not None
    assert state.get_slot(SLOT_CLASSIFICATION).content is classification


# --------------------------------------------------------------------------- #
# context.py — coverage-plan output accessor pair (Req 7.2, 7.3, 7.4)         #
# --------------------------------------------------------------------------- #


def test_absent_coverage_plan_returns_none() -> None:
    """Reading the coverage-plan slot before Plan runs returns None (Req 7.4)."""
    assert RunContext(_state()).coverage_plan() is None


def test_coverage_plan_round_trip() -> None:
    ctx = RunContext(_state())
    assert ctx.coverage_plan() is None  # explicit unset before set (Req 7.4)
    plan = object()  # opaque CoveragePlan stand-in; slot is content-agnostic
    ctx.set_coverage_plan(plan)
    assert ctx.coverage_plan() is plan


def test_coverage_plan_written_through_named_slot() -> None:
    state = _state()
    plan = object()
    RunContext(state).set_coverage_plan(plan)
    assert state.get_slot(SLOT_COVERAGE_PLAN) is not None
    assert state.get_slot(SLOT_COVERAGE_PLAN).content is plan


# --------------------------------------------------------------------------- #
# Existing accessors remain intact (append-only guarantee, Req 7.5)           #
# --------------------------------------------------------------------------- #


def test_existing_accessors_present_and_unchanged() -> None:
    """The new pairs do not displace any pre-existing RunContext accessor."""
    ctx = RunContext(_state())
    for name in (
        "set_target_repo",
        "target_repo",
        "set_output_dir",
        "output_dir",
        "set_segment_store",
        "segment_store",
        "set_vocabulary",
        "vocabulary",
        "set_file_inventory",
        "file_inventory",
        "set_repo_analysis",
        "repo_analysis",
    ):
        assert callable(getattr(ctx, name)), f"missing accessor {name}"


def test_new_and_existing_slots_are_independent() -> None:
    """Setting the planner slots leaves the upstream slots reading None."""
    ctx = RunContext(_state())
    ctx.set_classification(object())
    ctx.set_coverage_plan(object())
    assert ctx.repo_analysis() is None
    assert ctx.file_inventory() is None
    assert ctx.target_repo() is None
