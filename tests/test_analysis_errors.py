"""Unit tests for task 1.5 (the analysis error hierarchy).

Task 1.5 owns exactly one new module — ``docuharnessx.analysis.errors`` — and
pins the observable contract of the small, stage-scoped error hierarchy the
scanner, the two stage adapters, and ``serde`` raise (design "Error Handling →
Error Strategy"; Req 6.3, 8.4):

* :class:`AnalysisError` — the single base for the analysis package so callers
  can catch the whole family at the stage boundary while still distinguishing
  causes.
* :class:`IngestError` — fatal Ingest-stage input error: the target-repository
  slot is unset, or its path is missing / not a directory. Halts the run with an
  identifiable cause naming the offending slot/path (Req 8.4).
* :class:`AnalyzeError` — fatal Analyze-stage input error: the file-inventory
  slot is unset. Halts the run with an identifiable cause naming the offending
  slot (Req 8.4).
* :class:`RepoAnalysisVersionError` — ``serde.from_dict`` was handed a
  ``schema_version`` it does not understand; the message identifies the
  offending version (Req 6.3, 6.6).

This task's boundary is the analysis errors only — the scanner, the stages, and
``serde`` that *raise* these errors are out of scope here (later tasks). The
hierarchy is deliberately separate from the skeleton-wide
``docuharnessx.errors`` family so the pure analysis core stays self-contained and
unit-testable without a harness (design "pure-core + stage-adapter").
"""

from __future__ import annotations

import importlib

import pytest


ERRORS_MODULE = "docuharnessx.analysis.errors"
PACKAGE = "docuharnessx.analysis"

# Every concrete (non-base) error the design pins for task 1.5.
LEAF_ERROR_NAMES = (
    "IngestError",
    "AnalyzeError",
    "RepoAnalysisVersionError",
)
ALL_ERROR_NAMES = ("AnalysisError",) + LEAF_ERROR_NAMES


# --------------------------------------------------------------------------- #
# Module + package import / export
# --------------------------------------------------------------------------- #


def test_errors_module_imports() -> None:
    mod = importlib.import_module(ERRORS_MODULE)
    assert mod is not None


@pytest.mark.parametrize("name", ALL_ERROR_NAMES)
def test_error_class_exists_and_is_exception_subclass(name: str) -> None:
    mod = importlib.import_module(ERRORS_MODULE)
    assert hasattr(mod, name), f"missing analysis error class {name}"
    cls = getattr(mod, name)
    assert isinstance(cls, type)
    assert issubclass(cls, Exception)


@pytest.mark.parametrize("name", ALL_ERROR_NAMES)
def test_error_is_in_module_all_exports(name: str) -> None:
    mod = importlib.import_module(ERRORS_MODULE)
    assert name in mod.__all__, f"{name} not in {ERRORS_MODULE}.__all__"


@pytest.mark.parametrize("name", ALL_ERROR_NAMES)
def test_error_is_reexported_from_package(name: str) -> None:
    """The analysis package re-exports the error family for a single import site."""
    pkg = importlib.import_module(PACKAGE)
    assert hasattr(pkg, name), f"{name} not re-exported from {PACKAGE}"
    assert name in pkg.__all__, f"{name} not in {PACKAGE}.__all__"


# --------------------------------------------------------------------------- #
# Hierarchy (design "Error Strategy": a small stage-scoped hierarchy)
# --------------------------------------------------------------------------- #


def test_analysis_error_is_the_base() -> None:
    """``AnalysisError`` is the single catch-all base for the analysis family."""
    mod = importlib.import_module(ERRORS_MODULE)
    assert issubclass(mod.AnalysisError, Exception)


@pytest.mark.parametrize("name", LEAF_ERROR_NAMES)
def test_leaf_errors_derive_from_analysis_error(name: str) -> None:
    mod = importlib.import_module(ERRORS_MODULE)
    cls = getattr(mod, name)
    assert issubclass(cls, mod.AnalysisError), (
        f"{name} should derive from AnalysisError"
    )


def test_leaf_errors_are_distinct_types() -> None:
    """Ingest, Analyze, and version errors are distinguishable subclasses."""
    mod = importlib.import_module(ERRORS_MODULE)
    leaves = {getattr(mod, n) for n in LEAF_ERROR_NAMES}
    assert len(leaves) == len(LEAF_ERROR_NAMES)
    # No leaf is a subclass of another leaf — they are siblings under the base.
    assert not issubclass(mod.IngestError, mod.AnalyzeError)
    assert not issubclass(mod.AnalyzeError, mod.IngestError)
    assert not issubclass(mod.RepoAnalysisVersionError, mod.IngestError)
    assert not issubclass(mod.RepoAnalysisVersionError, mod.AnalyzeError)


def test_analysis_errors_are_separate_from_skeleton_errors() -> None:
    """The analysis core hierarchy is self-contained, not under DocuHarnessXError.

    The pure analysis core must not depend on the skeleton-wide error family so
    it stays unit-testable without the harness (design "pure-core + stage-
    adapter"; allowed-dependencies pin stdlib + model/context only).
    """
    errors_mod = importlib.import_module(ERRORS_MODULE)
    skeleton = importlib.import_module("docuharnessx.errors")
    assert not issubclass(errors_mod.AnalysisError, skeleton.DocuHarnessXError)


# --------------------------------------------------------------------------- #
# Observable: each error carries a clear, cause-naming message (task 1.5 Obs)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("name", ALL_ERROR_NAMES)
def test_error_carries_its_message(name: str) -> None:
    mod = importlib.import_module(ERRORS_MODULE)
    cls = getattr(mod, name)
    err = cls("boom")
    assert str(err) == "boom"


@pytest.mark.parametrize("name", ALL_ERROR_NAMES)
def test_error_is_catchable_via_base(name: str) -> None:
    """Any leaf is catchable through ``AnalysisError`` at the stage boundary."""
    mod = importlib.import_module(ERRORS_MODULE)
    cls = getattr(mod, name)
    with pytest.raises(mod.AnalysisError):
        raise cls("boom")


def test_ingest_error_message_can_name_the_offending_path() -> None:
    """IngestError surfaces the missing/invalid repo path (Req 8.4)."""
    mod = importlib.import_module(ERRORS_MODULE)
    err = mod.IngestError("target repository path does not exist: /nope/here")
    assert "/nope/here" in str(err)


def test_analyze_error_message_can_name_the_offending_slot() -> None:
    """AnalyzeError surfaces the missing inventory slot (Req 8.4)."""
    mod = importlib.import_module(ERRORS_MODULE)
    err = mod.AnalyzeError(
        "file-inventory slot is unset: docuharnessx.file_inventory"
    )
    assert "docuharnessx.file_inventory" in str(err)


def test_version_error_message_can_name_the_offending_version() -> None:
    """RepoAnalysisVersionError surfaces the unknown schema version (Req 6.3)."""
    mod = importlib.import_module(ERRORS_MODULE)
    err = mod.RepoAnalysisVersionError(
        "unsupported RepoAnalysis schema_version: 999 (expected 1)"
    )
    assert "999" in str(err)
