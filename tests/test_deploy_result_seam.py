"""Tests for the deploy-result output seam (github-pages-deploy task 1.2).

Task 1.2 is an **append-only** extension of two ``harness-bundle-skeleton``-owned
modules so the Wave 3 ``github-pages-deploy`` DeployStage can publish exactly the
``DeployResult`` it produced and the journal/downstream can read it back:

* ``docuharnessx/types.py`` gains the ``SLOT_DEPLOY_RESULT`` slot-key constant
  (added to ``__all__``), changing no existing slot key, ``StageName``, or
  ``STAGE_NAMES`` entry (Req 8.4).
* ``docuharnessx/context.py`` gains the ``set_deploy_result()`` /
  ``deploy_result()`` accessor pair, which returns an explicit ``None`` before the
  Deploy Stage has run (Req 8.4) and round-trips a ``DeployResult`` value object.

These tests pin only the seam contract for this task's boundary (types/context
additions); the publishing behaviour lives in the DeployStage (later tasks).

Observable completion (tasks.md 1.2): setting then getting the deploy result
round-trips the same value, a fresh run context returns the absent value, and the
existing slots/accessors/exports are unchanged.
"""

from __future__ import annotations

import importlib
import typing

from harnessx.core.state import State

from docuharnessx.context import RunContext
from docuharnessx.deployer import (
    DEPLOY_RESULT_SCHEMA_VERSION,
    DeployResult,
)
from docuharnessx.types import SLOT_DEPLOY_RESULT

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


def _deploy_result() -> DeployResult:
    """A minimal, model-free DeployResult value object for round-trip tests."""
    return DeployResult(
        schema_version=DEPLOY_RESULT_SCHEMA_VERSION,
        mode="emit-ci-workflow",
        status="emitted",
        target_pages_url="https://norandom.github.io/malware_hashes/",
        written_paths=(
            "/tmp/target/mkdocs.yml",
            "/tmp/target/docs",
            "/tmp/target/.github/workflows/docs.yml",
        ),
        built_path="/tmp/out/site/site",
        detail="emitted CI workflow into target tree",
    )


# --------------------------------------------------------------------------- #
# types.py — the append-only SLOT_DEPLOY_RESULT slot key (Req 8.4)             #
# --------------------------------------------------------------------------- #


def test_deploy_result_slot_key_exists_with_pinned_value() -> None:
    mod = importlib.import_module("docuharnessx.types")
    assert hasattr(mod, "SLOT_DEPLOY_RESULT")
    value = mod.SLOT_DEPLOY_RESULT
    assert isinstance(value, str)
    assert value == "docuharnessx.deploy_result"


def test_deploy_result_slot_key_in_all_exports() -> None:
    mod = importlib.import_module("docuharnessx.types")
    assert "SLOT_DEPLOY_RESULT" in set(mod.__all__)


def test_deploy_result_slot_key_distinct_from_existing() -> None:
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
        mod.SLOT_ASSEMBLED_SITE,
        mod.SLOT_DEPLOY_RESULT,
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
    assert mod.SLOT_REVIEW_REPORT == "docuharnessx.review_report"
    assert mod.SLOT_ASSEMBLED_SITE == "docuharnessx.assembled_site"
    assert tuple(typing.get_args(mod.StageName)) == CANONICAL_STAGES
    assert tuple(mod.STAGE_NAMES) == CANONICAL_STAGES


# --------------------------------------------------------------------------- #
# context.py — the append-only deploy_result accessor pair (Req 8.4)           #
# --------------------------------------------------------------------------- #


def test_absent_deploy_result_returns_none() -> None:
    """Reading the slot before the Deploy Stage runs returns None (Req 8.4)."""
    assert RunContext(_state()).deploy_result() is None


def test_deploy_result_round_trip() -> None:
    """A stored DeployResult is read back as the same instance (Req 8.4)."""
    ctx = RunContext(_state())
    assert ctx.deploy_result() is None  # explicit unset before set (Req 8.4)
    value = _deploy_result()
    ctx.set_deploy_result(value)
    assert ctx.deploy_result() is value


def test_deploy_result_written_through_named_slot() -> None:
    """The accessor writes through the shared SLOT_DEPLOY_RESULT key (Req 8.4)."""
    state = _state()
    value = _deploy_result()
    RunContext(state).set_deploy_result(value)
    slot = state.get_slot(SLOT_DEPLOY_RESULT)
    assert slot is not None
    assert slot.content is value


def test_deploy_result_preserves_value_verbatim() -> None:
    """The seam round-trips the versioned result + its fields verbatim (Req 8.4)."""
    value = _deploy_result()
    ctx = RunContext(_state())
    ctx.set_deploy_result(value)
    retrieved = ctx.deploy_result()
    assert retrieved is value
    assert retrieved.schema_version == DEPLOY_RESULT_SCHEMA_VERSION
    assert retrieved.mode == "emit-ci-workflow"
    assert retrieved.status == "emitted"
    assert retrieved.target_pages_url == "https://norandom.github.io/malware_hashes/"
    assert len(retrieved.written_paths) == 3
    assert retrieved.built_path == "/tmp/out/site/site"


def test_deploy_result_equal_value_round_trips() -> None:
    """The slot compares-by-value seam round-trips an equal DeployResult (Req 8.4)."""
    ctx = RunContext(_state())
    ctx.set_deploy_result(_deploy_result())
    assert ctx.deploy_result() == _deploy_result()


# --------------------------------------------------------------------------- #
# Independence from the other slot accessors (append-only, no regression)      #
# --------------------------------------------------------------------------- #


def test_deploy_result_slot_independent_from_assembled_site() -> None:
    """Setting the deploy-result slot does not disturb sibling accessors."""
    ctx = RunContext(_state())
    ctx.set_deploy_result(_deploy_result())
    assert ctx.assembled_site() is None
    assert ctx.review_report() is None
    assert ctx.written_segments() is None
    assert ctx.coverage_plan() is None
    assert ctx.vocabulary() is None


def test_setting_assembled_site_leaves_deploy_result_absent() -> None:
    """A sibling slot write does not pre-populate the deploy-result slot."""
    ctx = RunContext(_state())
    # Use a sibling accessor without importing AssembledSite — set then assert
    # the deploy slot stays explicitly absent (Req 8.4).
    ctx.set_target_repo("/tmp/target")
    assert ctx.deploy_result() is None
