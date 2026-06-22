"""Unit tests for task 1.1 (the frozen ``RepoAnalysis`` model + nested records).

Task 1.1 owns exactly one new module — ``docuharnessx.analysis.model`` — plus the
``docuharnessx.analysis`` package ``__init__``. It pins the observable contract of
the **frozen seam** the downstream ``classification-coverage-planner`` consumes
(design "model — RepoAnalysis (the frozen seam)"; Req 6.1, 6.2, 6.3, 6.6):

* A single aggregate root :class:`RepoAnalysis` aggregating language/LOC,
  structure, entrypoints, build/config files, CI workflows, test layout, declared
  dependencies, component map, public surface, documentation presence, notable
  artifacts, scan stats, and the optional enrichment region (Req 6.1).
* Every model type is an immutable (frozen) value object; every collection field
  is a ``tuple`` (never ``list``) so instances are deeply immutable (Req 6.2).
* An explicit ``REPO_ANALYSIS_SCHEMA_VERSION`` carried on the aggregate root
  (Req 6.3).

This task's boundary is the model only — serialization (task 1.2), the slot keys
(task 1.3), the RunContext accessors (task 1.4), and the error hierarchy
(task 1.5) are out of scope here.
"""

from __future__ import annotations

import dataclasses
import importlib
import typing

import pytest


MODEL_MODULE = "docuharnessx.analysis.model"
PACKAGE = "docuharnessx.analysis"

# The exact nested record type names the design pins for the frozen seam.
NESTED_TYPES = (
    "LanguageStat",
    "DirectorySummary",
    "Entrypoint",
    "BuildFile",
    "CIWorkflow",
    "TestLayout",
    "Dependency",
    "Component",
    "PublicSymbol",
    "DocPresence",
    "Artifact",
    "ScanStats",
    "Enrichment",
)


# --------------------------------------------------------------------------- #
# Package + module import
# --------------------------------------------------------------------------- #


def test_analysis_package_imports() -> None:
    pkg = importlib.import_module(PACKAGE)
    assert pkg is not None


def test_model_module_imports() -> None:
    mod = importlib.import_module(MODEL_MODULE)
    assert mod is not None


def test_schema_version_constant_is_one() -> None:
    mod = importlib.import_module(MODEL_MODULE)
    assert hasattr(mod, "REPO_ANALYSIS_SCHEMA_VERSION")
    assert mod.REPO_ANALYSIS_SCHEMA_VERSION == 1
    assert isinstance(mod.REPO_ANALYSIS_SCHEMA_VERSION, int)


@pytest.mark.parametrize("name", NESTED_TYPES + ("RepoAnalysis",))
def test_model_type_exists_and_is_a_dataclass(name: str) -> None:
    mod = importlib.import_module(MODEL_MODULE)
    assert hasattr(mod, name), f"missing model type {name}"
    cls = getattr(mod, name)
    assert isinstance(cls, type)
    assert dataclasses.is_dataclass(cls), f"{name} must be a dataclass"


@pytest.mark.parametrize("name", NESTED_TYPES + ("RepoAnalysis",))
def test_model_type_is_frozen(name: str) -> None:
    """Every model type is a frozen dataclass (immutable value object, Req 6.2)."""
    mod = importlib.import_module(MODEL_MODULE)
    cls = getattr(mod, name)
    params = getattr(cls, "__dataclass_params__")
    assert params.frozen is True, f"{name} must be a frozen dataclass"


@pytest.mark.parametrize("name", NESTED_TYPES + ("RepoAnalysis",))
def test_model_type_is_exported(name: str) -> None:
    mod = importlib.import_module(MODEL_MODULE)
    assert name in mod.__all__, f"{name} not in {MODEL_MODULE}.__all__"
    pkg = importlib.import_module(PACKAGE)
    assert hasattr(pkg, name), f"{name} not re-exported from {PACKAGE}"


def test_schema_version_exported_from_module_and_package() -> None:
    mod = importlib.import_module(MODEL_MODULE)
    assert "REPO_ANALYSIS_SCHEMA_VERSION" in mod.__all__
    pkg = importlib.import_module(PACKAGE)
    assert hasattr(pkg, "REPO_ANALYSIS_SCHEMA_VERSION")


# --------------------------------------------------------------------------- #
# Field shape pins (design "The frozen seam (the planner consumes EXACTLY this)")
# --------------------------------------------------------------------------- #


def _field_names(cls) -> tuple[str, ...]:
    return tuple(f.name for f in dataclasses.fields(cls))


def test_language_stat_fields() -> None:
    mod = importlib.import_module(MODEL_MODULE)
    assert _field_names(mod.LanguageStat) == ("language", "files", "loc")


def test_directory_summary_fields() -> None:
    mod = importlib.import_module(MODEL_MODULE)
    assert _field_names(mod.DirectorySummary) == (
        "path",
        "file_count",
        "dominant_language",
        "role",
    )


def test_entrypoint_fields() -> None:
    mod = importlib.import_module(MODEL_MODULE)
    assert _field_names(mod.Entrypoint) == ("path", "kind", "name")


def test_build_file_fields() -> None:
    mod = importlib.import_module(MODEL_MODULE)
    assert _field_names(mod.BuildFile) == ("path", "kind")


def test_ci_workflow_fields() -> None:
    mod = importlib.import_module(MODEL_MODULE)
    assert _field_names(mod.CIWorkflow) == ("path", "provider")


def test_test_layout_fields() -> None:
    mod = importlib.import_module(MODEL_MODULE)
    assert _field_names(mod.TestLayout) == ("present", "frameworks", "paths")


def test_dependency_fields() -> None:
    mod = importlib.import_module(MODEL_MODULE)
    assert _field_names(mod.Dependency) == (
        "name",
        "version_spec",
        "source",
        "scope",
    )


def test_component_fields() -> None:
    mod = importlib.import_module(MODEL_MODULE)
    assert _field_names(mod.Component) == ("name", "path", "representative_files")


def test_public_symbol_fields() -> None:
    mod = importlib.import_module(MODEL_MODULE)
    assert _field_names(mod.PublicSymbol) == ("name", "kind", "source")


def test_doc_presence_fields() -> None:
    mod = importlib.import_module(MODEL_MODULE)
    assert _field_names(mod.DocPresence) == (
        "has_readme",
        "readme_paths",
        "doc_dirs",
        "other_docs",
    )


def test_artifact_fields() -> None:
    mod = importlib.import_module(MODEL_MODULE)
    assert _field_names(mod.Artifact) == ("path", "kind")


def test_scan_stats_fields() -> None:
    mod = importlib.import_module(MODEL_MODULE)
    assert _field_names(mod.ScanStats) == (
        "files_scanned",
        "files_skipped",
        "bytes_scanned",
        "limit_reached",
        "notes",
    )


def test_enrichment_fields() -> None:
    mod = importlib.import_module(MODEL_MODULE)
    assert _field_names(mod.Enrichment) == ("architecture_summary", "model_id")


def test_repo_analysis_fields() -> None:
    """The aggregate root carries every field the design pins, in order."""
    mod = importlib.import_module(MODEL_MODULE)
    assert _field_names(mod.RepoAnalysis) == (
        "schema_version",
        "repo_path",
        "languages",
        "primary_languages",
        "total_loc",
        "total_files",
        "structure",
        "entrypoints",
        "build_files",
        "ci_workflows",
        "tests",
        "dependencies",
        "components",
        "public_surface",
        "docs",
        "artifacts",
        "scan_stats",
        "enrichment",
    )


def test_repo_analysis_enrichment_defaults_to_none() -> None:
    """Enrichment is the only field with a default (None) — Req 9.4."""
    mod = importlib.import_module(MODEL_MODULE)
    fields = {f.name: f for f in dataclasses.fields(mod.RepoAnalysis)}
    enrichment = fields["enrichment"]
    assert enrichment.default is None


# --------------------------------------------------------------------------- #
# Immutability (Req 6.2): instances reject mutation
# --------------------------------------------------------------------------- #


def _build_repo_analysis(mod):
    """Build a fully-populated RepoAnalysis using only tuple collections."""
    return mod.RepoAnalysis(
        schema_version=mod.REPO_ANALYSIS_SCHEMA_VERSION,
        repo_path="/abs/repo",
        languages=(mod.LanguageStat(language="Go", files=3, loc=120),),
        primary_languages=("Go",),
        total_loc=120,
        total_files=3,
        structure=(
            mod.DirectorySummary(
                path="",
                file_count=3,
                dominant_language="Go",
                role="source",
            ),
        ),
        entrypoints=(mod.Entrypoint(path="main.go", kind="main", name=""),),
        build_files=(mod.BuildFile(path="go.mod", kind="go_mod"),),
        ci_workflows=(
            mod.CIWorkflow(path=".github/workflows/ci.yml", provider="github_actions"),
        ),
        tests=mod.TestLayout(
            present=True,
            frameworks=("go_testing",),
            paths=("main_test.go",),
        ),
        dependencies=(
            mod.Dependency(
                name="cobra",
                version_spec="v1.0.0",
                source="go.mod",
                scope="runtime",
            ),
        ),
        components=(
            mod.Component(
                name="internal",
                path="internal",
                representative_files=("internal/a.go",),
            ),
        ),
        public_surface=(
            mod.PublicSymbol(name="Run", kind="exported_symbol", source="main.go"),
        ),
        docs=mod.DocPresence(
            has_readme=True,
            readme_paths=("README.md",),
            doc_dirs=(),
            other_docs=(),
        ),
        artifacts=(mod.Artifact(path="LICENSE", kind="license"),),
        scan_stats=mod.ScanStats(
            files_scanned=3,
            files_skipped=0,
            bytes_scanned=4096,
            limit_reached=False,
            notes=(),
        ),
    )


def test_repo_analysis_constructs_fully_typed() -> None:
    """Importing the model yields a fully-typed RepoAnalysis aggregate (Obs)."""
    mod = importlib.import_module(MODEL_MODULE)
    analysis = _build_repo_analysis(mod)
    assert analysis.schema_version == mod.REPO_ANALYSIS_SCHEMA_VERSION
    assert analysis.enrichment is None
    assert isinstance(analysis.languages, tuple)
    assert isinstance(analysis.tests, mod.TestLayout)
    assert isinstance(analysis.docs, mod.DocPresence)
    assert isinstance(analysis.scan_stats, mod.ScanStats)


def test_repo_analysis_rejects_mutation() -> None:
    """Frozen aggregate: attribute assignment raises (Req 6.2)."""
    mod = importlib.import_module(MODEL_MODULE)
    analysis = _build_repo_analysis(mod)
    with pytest.raises(dataclasses.FrozenInstanceError):
        analysis.total_loc = 999  # type: ignore[misc]


def test_nested_records_reject_mutation() -> None:
    mod = importlib.import_module(MODEL_MODULE)
    stat = mod.LanguageStat(language="Go", files=1, loc=10)
    with pytest.raises(dataclasses.FrozenInstanceError):
        stat.loc = 11  # type: ignore[misc]


def test_repo_analysis_supports_dataclasses_replace_for_enrichment() -> None:
    """The enrichment region is attachable via dataclasses.replace (design enrich)."""
    mod = importlib.import_module(MODEL_MODULE)
    core = _build_repo_analysis(mod)
    enriched = dataclasses.replace(
        core,
        enrichment=mod.Enrichment(architecture_summary="A CLI.", model_id="m"),
    )
    assert core.enrichment is None  # core untouched
    assert enriched.enrichment is not None
    assert enriched.enrichment.architecture_summary == "A CLI."
    # Every other field is unchanged by the replace.
    assert dataclasses.replace(enriched, enrichment=None) == core


def test_equal_inputs_yield_equal_instances() -> None:
    """Structural equality holds for two independently-built equal aggregates."""
    mod = importlib.import_module(MODEL_MODULE)
    assert _build_repo_analysis(mod) == _build_repo_analysis(mod)


# --------------------------------------------------------------------------- #
# Collection fields are tuple-typed (Req 6.2: deeply immutable)
# --------------------------------------------------------------------------- #

# (field-owning type, field name) for every collection field across the seam.
TUPLE_FIELDS = (
    ("RepoAnalysis", "languages"),
    ("RepoAnalysis", "primary_languages"),
    ("RepoAnalysis", "structure"),
    ("RepoAnalysis", "entrypoints"),
    ("RepoAnalysis", "build_files"),
    ("RepoAnalysis", "ci_workflows"),
    ("RepoAnalysis", "dependencies"),
    ("RepoAnalysis", "components"),
    ("RepoAnalysis", "public_surface"),
    ("RepoAnalysis", "artifacts"),
    ("TestLayout", "frameworks"),
    ("TestLayout", "paths"),
    ("Component", "representative_files"),
    ("DocPresence", "readme_paths"),
    ("DocPresence", "doc_dirs"),
    ("DocPresence", "other_docs"),
    ("ScanStats", "notes"),
)


@pytest.mark.parametrize("type_name,field_name", TUPLE_FIELDS)
def test_collection_fields_are_tuple_typed(type_name: str, field_name: str) -> None:
    """Every collection field is annotated ``tuple[...]`` (never ``list``)."""
    mod = importlib.import_module(MODEL_MODULE)
    hints = typing.get_type_hints(getattr(mod, type_name))
    annotation = hints[field_name]
    origin = typing.get_origin(annotation)
    assert origin is tuple, (
        f"{type_name}.{field_name} must be tuple-typed, got {annotation!r}"
    )
