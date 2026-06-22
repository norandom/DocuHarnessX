"""Unit tests for task 1.2 (deterministic serialize/deserialize for RepoAnalysis).

Task 1.2 owns exactly one new module — ``docuharnessx.analysis.serde`` — which
gives the frozen :class:`RepoAnalysis` seam a JSON-compatible, byte-stable
serialization and a round-trip deserialization (design "serde — deterministic
serialization"; Req 6.3, 6.4, 6.5, 6.6):

* ``to_dict(analysis) -> dict`` — an ordered, plain, JSON-compatible structure;
  tuples become lists preserving the analyzer's sort order; ``None`` enrichment
  becomes ``None``/``null`` (Req 6.4).
* ``from_dict(data) -> RepoAnalysis`` — reconstructs an **equal** aggregate
  (round-trip equality, Req 6.5); an unknown ``schema_version`` raises
  :class:`RepoAnalysisVersionError` naming the offending version (Req 6.3, 6.6).
* ``to_json(analysis) -> str`` — ``json.dumps(to_dict, sort_keys=True,
  ensure_ascii=False)``; byte-identical across repeated calls for equal inputs
  (Req 6.4).

This task's boundary is serde only — the model (task 1.1), the error hierarchy
(task 1.5), the scanner/analyzer, and the stages are out of scope here. The
helper builds a fully-populated ``RepoAnalysis`` directly (no scanner needed) so
the round-trip can be proven against every field of the seam.
"""

from __future__ import annotations

import dataclasses
import importlib
import json

import pytest

from docuharnessx.analysis import model as model_mod
from docuharnessx.analysis.errors import RepoAnalysisVersionError


SERDE_MODULE = "docuharnessx.analysis.serde"
PACKAGE = "docuharnessx.analysis"


# --------------------------------------------------------------------------- #
# Fixtures: fully-populated RepoAnalysis instances (no scanner involved)
# --------------------------------------------------------------------------- #


def _build_core_analysis():
    """A fully-populated core ``RepoAnalysis`` (enrichment absent, Req 9.4)."""
    return model_mod.RepoAnalysis(
        schema_version=model_mod.REPO_ANALYSIS_SCHEMA_VERSION,
        repo_path="/abs/repo",
        languages=(
            model_mod.LanguageStat(language="Go", files=3, loc=120),
            model_mod.LanguageStat(language="Markdown", files=1, loc=10),
        ),
        primary_languages=("Go",),
        total_loc=130,
        total_files=4,
        structure=(
            model_mod.DirectorySummary(
                path="",
                file_count=4,
                dominant_language="Go",
                role="source",
            ),
            model_mod.DirectorySummary(
                path="internal",
                file_count=2,
                dominant_language="Go",
                role="source",
            ),
        ),
        entrypoints=(model_mod.Entrypoint(path="main.go", kind="main", name=""),),
        build_files=(model_mod.BuildFile(path="go.mod", kind="go_mod"),),
        ci_workflows=(
            model_mod.CIWorkflow(
                path=".github/workflows/ci.yml", provider="github_actions"
            ),
        ),
        tests=model_mod.TestLayout(
            present=True,
            frameworks=("go_testing",),
            paths=("main_test.go",),
        ),
        dependencies=(
            model_mod.Dependency(
                name="cobra",
                version_spec="v1.0.0",
                source="go.mod",
                scope="runtime",
            ),
        ),
        components=(
            model_mod.Component(
                name="internal",
                path="internal",
                representative_files=("internal/a.go", "internal/b.go"),
            ),
        ),
        public_surface=(
            model_mod.PublicSymbol(
                name="Run", kind="exported_symbol", source="main.go"
            ),
        ),
        docs=model_mod.DocPresence(
            has_readme=True,
            readme_paths=("README.md",),
            doc_dirs=("docs",),
            other_docs=(),
        ),
        artifacts=(model_mod.Artifact(path="LICENSE", kind="license"),),
        scan_stats=model_mod.ScanStats(
            files_scanned=4,
            files_skipped=1,
            bytes_scanned=4096,
            limit_reached=False,
            notes=("skipped 1 unreadable entry",),
        ),
    )


def _build_enriched_analysis():
    """The same aggregate with the optional enrichment region attached (Req 9.3)."""
    return dataclasses.replace(
        _build_core_analysis(),
        enrichment=model_mod.Enrichment(
            architecture_summary="A small Go CLI.",
            model_id="test-model",
        ),
    )


def _build_empty_analysis():
    """A minimal aggregate where every collection category is empty (Req 4.6)."""
    return model_mod.RepoAnalysis(
        schema_version=model_mod.REPO_ANALYSIS_SCHEMA_VERSION,
        repo_path="/abs/empty",
        languages=(),
        primary_languages=(),
        total_loc=0,
        total_files=0,
        structure=(),
        entrypoints=(),
        build_files=(),
        ci_workflows=(),
        tests=model_mod.TestLayout(present=False, frameworks=(), paths=()),
        dependencies=(),
        components=(),
        public_surface=(),
        docs=model_mod.DocPresence(
            has_readme=False,
            readme_paths=(),
            doc_dirs=(),
            other_docs=(),
        ),
        artifacts=(),
        scan_stats=model_mod.ScanStats(
            files_scanned=0,
            files_skipped=0,
            bytes_scanned=0,
            limit_reached=False,
            notes=(),
        ),
    )


# --------------------------------------------------------------------------- #
# Module + public surface
# --------------------------------------------------------------------------- #


def test_serde_module_imports() -> None:
    mod = importlib.import_module(SERDE_MODULE)
    assert mod is not None


@pytest.mark.parametrize("name", ("to_dict", "from_dict", "to_json"))
def test_serde_exports_callables(name: str) -> None:
    mod = importlib.import_module(SERDE_MODULE)
    assert hasattr(mod, name), f"serde must export {name}"
    assert callable(getattr(mod, name))
    assert name in mod.__all__, f"{name} not in {SERDE_MODULE}.__all__"


def test_serde_functions_reexported_from_package() -> None:
    pkg = importlib.import_module(PACKAGE)
    for name in ("to_dict", "from_dict", "to_json"):
        assert hasattr(pkg, name), f"{name} not re-exported from {PACKAGE}"


# --------------------------------------------------------------------------- #
# to_dict produces a plain, JSON-compatible structure (Req 6.4)
# --------------------------------------------------------------------------- #


def test_to_dict_is_json_compatible() -> None:
    from docuharnessx.analysis import serde

    data = serde.to_dict(_build_core_analysis())
    assert isinstance(data, dict)
    # Must serialize through stdlib json without a custom encoder.
    rendered = json.dumps(data)
    assert isinstance(rendered, str)


def test_to_dict_carries_schema_version() -> None:
    from docuharnessx.analysis import serde

    data = serde.to_dict(_build_core_analysis())
    assert data["schema_version"] == model_mod.REPO_ANALYSIS_SCHEMA_VERSION


def test_to_dict_tuples_become_lists() -> None:
    """Tuple collections become JSON arrays (lists) preserving order."""
    from docuharnessx.analysis import serde

    data = serde.to_dict(_build_core_analysis())
    assert isinstance(data["languages"], list)
    assert data["languages"][0] == {"language": "Go", "files": 3, "loc": 120}
    assert data["languages"][1]["language"] == "Markdown"
    assert isinstance(data["primary_languages"], list)
    assert data["primary_languages"] == ["Go"]
    assert isinstance(data["tests"]["frameworks"], list)
    assert isinstance(data["scan_stats"]["notes"], list)


def test_to_dict_nested_records_become_dicts() -> None:
    from docuharnessx.analysis import serde

    data = serde.to_dict(_build_core_analysis())
    assert isinstance(data["tests"], dict)
    assert data["tests"]["present"] is True
    assert isinstance(data["docs"], dict)
    assert data["docs"]["has_readme"] is True
    assert isinstance(data["scan_stats"], dict)


def test_to_dict_absent_enrichment_is_none() -> None:
    """``None`` enrichment serializes to ``None`` (null in JSON) — Req 9.4."""
    from docuharnessx.analysis import serde

    data = serde.to_dict(_build_core_analysis())
    assert data["enrichment"] is None
    assert "null" in json.dumps(data)


def test_to_dict_present_enrichment_is_nested_dict() -> None:
    from docuharnessx.analysis import serde

    data = serde.to_dict(_build_enriched_analysis())
    assert isinstance(data["enrichment"], dict)
    assert data["enrichment"]["architecture_summary"] == "A small Go CLI."
    assert data["enrichment"]["model_id"] == "test-model"


# --------------------------------------------------------------------------- #
# Round-trip equality: from_dict(to_dict(a)) == a (Req 6.5)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "builder",
    (_build_core_analysis, _build_enriched_analysis, _build_empty_analysis),
)
def test_round_trip_equality(builder) -> None:
    from docuharnessx.analysis import serde

    original = builder()
    restored = serde.from_dict(serde.to_dict(original))
    assert restored == original


def test_round_trip_reconstructs_frozen_types() -> None:
    """The reconstructed aggregate uses the frozen model types, not raw dicts."""
    from docuharnessx.analysis import serde

    restored = serde.from_dict(serde.to_dict(_build_core_analysis()))
    assert isinstance(restored, model_mod.RepoAnalysis)
    assert isinstance(restored.languages[0], model_mod.LanguageStat)
    assert isinstance(restored.tests, model_mod.TestLayout)
    assert isinstance(restored.docs, model_mod.DocPresence)
    assert isinstance(restored.scan_stats, model_mod.ScanStats)


def test_round_trip_collections_are_tuples() -> None:
    """Reconstruction restores tuple-typed collections (deeply immutable, Req 6.2)."""
    from docuharnessx.analysis import serde

    restored = serde.from_dict(serde.to_dict(_build_core_analysis()))
    assert isinstance(restored.languages, tuple)
    assert isinstance(restored.primary_languages, tuple)
    assert isinstance(restored.tests.frameworks, tuple)
    assert isinstance(restored.scan_stats.notes, tuple)
    assert isinstance(restored.components[0].representative_files, tuple)


def test_round_trip_through_json_string() -> None:
    """A full to_json -> json.loads -> from_dict cycle reconstructs the aggregate."""
    from docuharnessx.analysis import serde

    original = _build_enriched_analysis()
    restored = serde.from_dict(json.loads(serde.to_json(original)))
    assert restored == original


def test_round_trip_preserves_absent_enrichment() -> None:
    from docuharnessx.analysis import serde

    restored = serde.from_dict(serde.to_dict(_build_core_analysis()))
    assert restored.enrichment is None


# --------------------------------------------------------------------------- #
# to_json byte-stability (Req 6.4)
# --------------------------------------------------------------------------- #


def test_to_json_returns_str() -> None:
    from docuharnessx.analysis import serde

    out = serde.to_json(_build_core_analysis())
    assert isinstance(out, str)


def test_to_json_byte_identical_across_repeated_calls() -> None:
    """Repeated serialization of the same instance is byte-identical (Req 6.4)."""
    from docuharnessx.analysis import serde

    analysis = _build_core_analysis()
    first = serde.to_json(analysis)
    second = serde.to_json(analysis)
    assert first == second


def test_to_json_byte_identical_for_equal_independent_inputs() -> None:
    """Two independently-built equal aggregates serialize byte-identically."""
    from docuharnessx.analysis import serde

    a = _build_core_analysis()
    b = _build_core_analysis()
    assert a == b
    assert serde.to_json(a) == serde.to_json(b)


def test_to_json_keys_are_sorted() -> None:
    """Keys are emitted sorted so output is order-independent of dict insertion."""
    from docuharnessx.analysis import serde

    out = serde.to_json(_build_core_analysis())
    # sort_keys=True puts 'artifacts' before 'build_files' before 'ci_workflows'.
    assert out.index('"artifacts"') < out.index('"build_files"')
    assert out.index('"build_files"') < out.index('"ci_workflows"')
    assert out.index('"repo_path"') < out.index('"schema_version"')


def test_to_json_preserves_non_ascii() -> None:
    """ensure_ascii=False keeps non-ASCII characters literal (byte-stable)."""
    from docuharnessx.analysis import serde

    analysis = dataclasses.replace(
        _build_core_analysis(),
        enrichment=model_mod.Enrichment(
            architecture_summary="café — déjà vu",
            model_id="m",
        ),
    )
    out = serde.to_json(analysis)
    assert "café — déjà vu" in out
    assert "\\u" not in out  # not escaped


# --------------------------------------------------------------------------- #
# Schema-version rejection (Req 6.3, 6.6)
# --------------------------------------------------------------------------- #


def test_from_dict_rejects_unknown_schema_version() -> None:
    from docuharnessx.analysis import serde

    data = serde.to_dict(_build_core_analysis())
    data["schema_version"] = 999
    with pytest.raises(RepoAnalysisVersionError):
        serde.from_dict(data)


def test_from_dict_version_error_message_names_version() -> None:
    """The error message identifies the offending version (Req 6.3)."""
    from docuharnessx.analysis import serde

    data = serde.to_dict(_build_core_analysis())
    data["schema_version"] = 7
    with pytest.raises(RepoAnalysisVersionError) as exc:
        serde.from_dict(data)
    assert "7" in str(exc.value)


def test_from_dict_rejects_missing_schema_version() -> None:
    """A payload with no recognizable schema version is rejected (Req 6.3)."""
    from docuharnessx.analysis import serde

    data = serde.to_dict(_build_core_analysis())
    del data["schema_version"]
    with pytest.raises(RepoAnalysisVersionError):
        serde.from_dict(data)


def test_from_dict_accepts_current_schema_version() -> None:
    from docuharnessx.analysis import serde

    data = serde.to_dict(_build_core_analysis())
    assert data["schema_version"] == model_mod.REPO_ANALYSIS_SCHEMA_VERSION
    restored = serde.from_dict(data)
    assert restored.schema_version == model_mod.REPO_ANALYSIS_SCHEMA_VERSION


def test_version_error_is_an_analysis_error() -> None:
    """RepoAnalysisVersionError is catchable as the family base (design errors)."""
    from docuharnessx.analysis.errors import AnalysisError

    assert issubclass(RepoAnalysisVersionError, AnalysisError)
