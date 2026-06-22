"""Tests for the assembled-site output seam (mkdocs-site-assembler task 1.3).

Task 1.3 is an **append-only** extension of two ``harness-bundle-skeleton``-owned
modules so the Wave 3 ``github-pages-deploy`` spec can consume exactly the site the
assembler produced:

* ``docuharnessx/types.py`` gains the ``SLOT_ASSEMBLED_SITE`` slot-key constant
  (added to ``__all__``), changing no existing slot key, ``StageName``, or
  ``STAGE_NAMES`` entry (Req 7.5).
* ``docuharnessx/context.py`` gains the ``set_assembled_site()`` /
  ``assembled_site()`` accessor pair, which returns an explicit ``None`` before the
  Assemble Stage has run (Req 7.4) and round-trips an ``AssembledSite`` value object.

These tests pin only the seam contract for this task's boundary (types/context
additions); the publishing behaviour lives in the AssembleStage (later tasks).
"""

from __future__ import annotations

import importlib
import typing

from harnessx.core.state import State

from docuharnessx.assembler import (
    ASSEMBLED_SITE_SCHEMA_VERSION,
    AssembledSite,
    SiteIdentity,
)
from docuharnessx.context import RunContext
from docuharnessx.types import SLOT_ASSEMBLED_SITE

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


def _identity() -> SiteIdentity:
    return SiteIdentity(
        site_name="malware_hashes",
        repo_name="norandom/malware_hashes",
        repo_url="https://github.com/norandom/malware_hashes",
        site_url="https://norandom.github.io/malware_hashes/",
        base_path="/malware_hashes/",
        edit_uri="edit/main/docs/",
    )


def _assembled_site() -> AssembledSite:
    """A minimal, model-free AssembledSite value object for round-trip tests."""
    return AssembledSite(
        schema_version=ASSEMBLED_SITE_SCHEMA_VERSION,
        site_dir="/tmp/out/site",
        docs_dir="/tmp/out/site/docs",
        mkdocs_yml_path="/tmp/out/site/mkdocs.yml",
        identity=_identity(),
        page_count=3,
        role_page_count=2,
    )


# --------------------------------------------------------------------------- #
# types.py — the append-only SLOT_ASSEMBLED_SITE slot key (Req 7.5)            #
# --------------------------------------------------------------------------- #


def test_assembled_site_slot_key_exists_with_pinned_value() -> None:
    mod = importlib.import_module("docuharnessx.types")
    assert hasattr(mod, "SLOT_ASSEMBLED_SITE")
    value = mod.SLOT_ASSEMBLED_SITE
    assert isinstance(value, str)
    assert value == "docuharnessx.assembled_site"


def test_assembled_site_slot_key_in_all_exports() -> None:
    mod = importlib.import_module("docuharnessx.types")
    assert "SLOT_ASSEMBLED_SITE" in set(mod.__all__)


def test_assembled_site_slot_key_distinct_from_existing() -> None:
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
    assert tuple(typing.get_args(mod.StageName)) == CANONICAL_STAGES
    assert tuple(mod.STAGE_NAMES) == CANONICAL_STAGES


# --------------------------------------------------------------------------- #
# context.py — the append-only assembled_site accessor pair (Req 7.4)          #
# --------------------------------------------------------------------------- #


def test_absent_assembled_site_returns_none() -> None:
    """Reading the slot before the Assemble Stage runs returns None (Req 7.4)."""
    assert RunContext(_state()).assembled_site() is None


def test_assembled_site_round_trip() -> None:
    """A stored AssembledSite is read back as the same instance (Req 7.1)."""
    ctx = RunContext(_state())
    assert ctx.assembled_site() is None  # explicit unset before set (Req 7.4)
    value = _assembled_site()
    ctx.set_assembled_site(value)
    assert ctx.assembled_site() is value


def test_assembled_site_written_through_named_slot() -> None:
    """The accessor writes through the shared SLOT_ASSEMBLED_SITE key (Req 7.5)."""
    state = _state()
    value = _assembled_site()
    RunContext(state).set_assembled_site(value)
    slot = state.get_slot(SLOT_ASSEMBLED_SITE)
    assert slot is not None
    assert slot.content is value


def test_assembled_site_preserves_identity_and_counts() -> None:
    """The seam round-trips the versioned site + nested identity verbatim (Req 7.2)."""
    value = _assembled_site()
    ctx = RunContext(_state())
    ctx.set_assembled_site(value)
    retrieved = ctx.assembled_site()
    assert retrieved is value
    assert retrieved.schema_version == ASSEMBLED_SITE_SCHEMA_VERSION
    assert retrieved.identity is value.identity
    assert retrieved.identity.base_path == "/malware_hashes/"
    assert retrieved.page_count == 3
    assert retrieved.role_page_count == 2


# --------------------------------------------------------------------------- #
# Independence from the other slot accessors (append-only, no regression)      #
# --------------------------------------------------------------------------- #


def test_assembled_site_slot_independent_from_review_report() -> None:
    """Setting the assembled-site slot does not disturb sibling accessors."""
    ctx = RunContext(_state())
    ctx.set_assembled_site(_assembled_site())
    assert ctx.review_report() is None
    assert ctx.written_segments() is None
    assert ctx.coverage_plan() is None
    assert ctx.vocabulary() is None
