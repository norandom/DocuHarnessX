"""The pure, model-free repository scanning + analysis core (Wave 1).

``docuharnessx.analysis`` is the deterministic, side-effect-free core that turns a
target repository on local disk into a frozen :class:`RepoAnalysis`. It is
stdlib-only and unit-testable without any harness; only the two stage adapters
(``docuharnessx/stages/ingest.py`` and ``analyze.py``) know about HarnessX
(design "deterministic pipeline-stage adapters over a pure scanning core").

This package is built up across the Wave 1 tasks. Task 1.1 establishes the frozen
seam — :class:`RepoAnalysis` and its nested record types plus
:data:`REPO_ANALYSIS_SCHEMA_VERSION` — re-exported here so downstream consumers
import from the single ``docuharnessx.analysis`` namespace rather than reaching
into submodules. Task 1.5 adds the stage-scoped error hierarchy
(:class:`AnalysisError` and its leaves), re-exported here for the same reason.
Task 1.2 adds the deterministic serde surface (:func:`to_dict`, :func:`from_dict`,
:func:`to_json`), re-exported here too. Task 2.2 adds the language layer
(:func:`detect_language`, :func:`aggregate_languages`). Task 3.1 adds the first
detectors (:func:`summarize_structure`, :func:`detect_entrypoints`,
:func:`detect_build_files`, :func:`detect_ci`). Task 3.2 adds the test-layout and
declared-dependency detectors (:func:`detect_tests`, :func:`extract_dependencies`,
and :func:`extract_dependencies_with_notes`). Task 3.3 adds the remaining detectors
(:func:`map_components`, :func:`detect_public_surface`, :func:`detect_docs`,
:func:`detect_artifacts`). Task 4.1 adds the composition layer (:func:`analyze`),
which feeds an inventory through the language layer and every detector to assemble
a single, fully pre-sorted, model-free :class:`RepoAnalysis`. Task 4.2 adds the
optional, gated enrichment surface (:func:`enrich`) to this same package additively:
the only place a model may touch the analysis, and built so it can never gate or
alter the deterministic core.
"""

from __future__ import annotations

from docuharnessx.analysis.analyzer import analyze
from docuharnessx.analysis.errors import (
    AnalysisError,
    AnalyzeError,
    IngestError,
    RepoAnalysisVersionError,
)
from docuharnessx.analysis.detectors import (
    detect_artifacts,
    detect_build_files,
    detect_ci,
    detect_docs,
    detect_entrypoints,
    detect_public_surface,
    detect_tests,
    extract_dependencies,
    extract_dependencies_with_notes,
    map_components,
    summarize_structure,
)
from docuharnessx.analysis.enrich import enrich
from docuharnessx.analysis.languages import (
    aggregate_languages,
    detect_language,
)
from docuharnessx.analysis.model import (
    REPO_ANALYSIS_SCHEMA_VERSION,
    Artifact,
    BuildFile,
    CIWorkflow,
    Component,
    Dependency,
    DirectorySummary,
    DocPresence,
    Enrichment,
    Entrypoint,
    LanguageStat,
    PublicSymbol,
    RepoAnalysis,
    ScanStats,
    TestLayout,
)
from docuharnessx.analysis.scanner import (
    DEFAULT_EXCLUDED_DIRS,
    FileEntry,
    FileInventory,
    ScanLimits,
    scan,
)
from docuharnessx.analysis.serde import from_dict, to_dict, to_json

__all__ = [
    "DEFAULT_EXCLUDED_DIRS",
    "REPO_ANALYSIS_SCHEMA_VERSION",
    "AnalysisError",
    "AnalyzeError",
    "Artifact",
    "BuildFile",
    "CIWorkflow",
    "Component",
    "Dependency",
    "DirectorySummary",
    "DocPresence",
    "Enrichment",
    "Entrypoint",
    "FileEntry",
    "FileInventory",
    "IngestError",
    "LanguageStat",
    "PublicSymbol",
    "RepoAnalysis",
    "RepoAnalysisVersionError",
    "ScanLimits",
    "ScanStats",
    "TestLayout",
    "aggregate_languages",
    "analyze",
    "detect_artifacts",
    "detect_build_files",
    "detect_ci",
    "detect_docs",
    "detect_entrypoints",
    "detect_language",
    "detect_public_surface",
    "detect_tests",
    "enrich",
    "extract_dependencies",
    "extract_dependencies_with_notes",
    "from_dict",
    "map_components",
    "summarize_structure",
    "scan",
    "to_dict",
    "to_json",
]
