"""The frozen ``RepoAnalysis`` seam and its nested record types (task 1.1).

This module is the **frozen, versioned contract** the downstream
``classification-coverage-planner`` (Wave 1, spec #2) consumes verbatim. It is
deliberately pure data: model-free, side-effect-free, stdlib-only. The
deterministic scanner/analyzer (later tasks) produces these value objects with
every collection pre-sorted; the model itself performs no sorting (design
"model — RepoAnalysis (the frozen seam)").

Design constraints pinned here
------------------------------
* Every type is a ``@dataclass(frozen=True)`` so instances are immutable value
  objects consumers cannot mutate (Req 6.2).
* Every collection field is a ``tuple[...]`` (never a ``list``) so an instance is
  *deeply* immutable and hashable-friendly (Req 6.2). The analyzer is responsible
  for building each tuple pre-sorted in the order documented on the field, so two
  runs over an unchanged repo yield equal objects (Req 6.4, 9.1).
* :data:`REPO_ANALYSIS_SCHEMA_VERSION` is the single version authority, carried on
  :attr:`RepoAnalysis.schema_version` (Req 6.3). Evolution is additive (new
  optional fields with defaults); the version bumps only when the frozen field set
  changes (Req 6.6).

The aggregate root :class:`RepoAnalysis` aggregates the language/LOC breakdown,
structure summary, entrypoints, build/config files, CI workflows, test layout,
declared dependencies, component/module map, public surface, documentation
presence, notable artifacts, scan statistics, and the *optional* enrichment region
(Req 6.1). The enrichment region is the only field with a default (``None``) so a
fully-deterministic core analysis is constructible without any model (Req 9.4).
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = [
    "REPO_ANALYSIS_SCHEMA_VERSION",
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
    "RepoAnalysis",
]

#: The single schema-version authority for the :class:`RepoAnalysis` seam. Carried
#: on :attr:`RepoAnalysis.schema_version`; bumped only when the frozen field set
#: changes (Req 6.3, 6.6).
REPO_ANALYSIS_SCHEMA_VERSION: int = 1


# --------------------------------------------------------------------------- #
# Language / LOC                                                               #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class LanguageStat:
    """Per-language file count and total lines of code (Req 3.2)."""

    language: str  # canonical language name, e.g. "Go", "Python", "Markdown", "Other"
    files: int  # number of files attributed to this language
    loc: int  # total lines of code across those files


# --------------------------------------------------------------------------- #
# Structure                                                                    #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class DirectorySummary:
    """A directory's file count, dominant language, and heuristic role (Req 4.1)."""

    path: str  # repo-relative POSIX path, "" for repo root
    file_count: int  # files directly + transitively under this directory
    dominant_language: str  # most-LOC language under this directory, or "Other"
    role: str  # "source"|"tests"|"docs"|"config"|"ci"|"build"|"other"


# --------------------------------------------------------------------------- #
# Entrypoints / build / CI                                                     #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Entrypoint:
    """A detected program entrypoint (Req 4.2)."""

    path: str  # repo-relative POSIX path
    kind: str  # "main"|"cli"|"script"|"console_script"|"package_bin"|"other"
    name: str  # symbolic name where known (e.g. console-script name), else ""


@dataclass(frozen=True)
class BuildFile:
    """A detected build/configuration file with its classified kind (Req 4.3)."""

    path: str  # repo-relative POSIX path
    kind: str  # "pyproject"|"requirements"|"go_mod"|"package_json"|
    #          # "makefile"|"dockerfile"|"lockfile"|"other"


@dataclass(frozen=True)
class CIWorkflow:
    """A detected CI/workflow configuration file and its provider (Req 4.4)."""

    path: str  # repo-relative POSIX path
    provider: str  # "github_actions"|"gitlab_ci"|"circleci"|"dagger"|"other"


# --------------------------------------------------------------------------- #
# Tests                                                                        #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class TestLayout:
    """Whether tests are present, the frameworks, and where they live (Req 4.5)."""

    present: bool  # whether any tests were detected
    frameworks: tuple[str, ...]  # detected frameworks, e.g. ("go_testing","pytest"); sorted
    paths: tuple[str, ...]  # representative test files/dirs (repo-relative); sorted


# --------------------------------------------------------------------------- #
# Dependencies / components / public surface                                   #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Dependency:
    """A declared dependency, its raw version spec, source manifest, scope (Req 5.1)."""

    name: str  # declared dependency name
    version_spec: str  # raw declared version/constraint, or "" if none
    source: str  # repo-relative path of the manifest it came from
    scope: str  # "runtime"|"dev"|"build"|"unknown"


@dataclass(frozen=True)
class Component:
    """A module/package unit derived from the directory structure (Req 5.2)."""

    name: str  # module/package name derived from structure
    path: str  # repo-relative POSIX path
    representative_files: tuple[str, ...]  # small sorted set of repo-relative files


@dataclass(frozen=True)
class PublicSymbol:
    """A cheaply-detectable public surface signal (Req 5.3)."""

    name: str  # symbol or CLI flag/subcommand name
    kind: str  # "cli_flag"|"cli_subcommand"|"exported_symbol"
    source: str  # repo-relative path where detected


# --------------------------------------------------------------------------- #
# Docs / artifacts                                                             #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class DocPresence:
    """Documentation presence: README, doc dirs, other recognized docs (Req 5.4)."""

    has_readme: bool
    readme_paths: tuple[str, ...]  # sorted repo-relative README paths
    doc_dirs: tuple[str, ...]  # sorted repo-relative doc directories
    other_docs: tuple[str, ...]  # sorted other recognized doc files


@dataclass(frozen=True)
class Artifact:
    """A notable artifact detected by filename/pattern (Req 5.5)."""

    path: str  # repo-relative POSIX path
    kind: str  # "license"|"dockerfile"|"schema"|"generated"|"other"


# --------------------------------------------------------------------------- #
# Scan statistics                                                              #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ScanStats:
    """Bounded scan counters and human-readable notes (Req 2.3, 10.2)."""

    files_scanned: int
    files_skipped: int  # unreadable / excluded-at-entry
    bytes_scanned: int
    limit_reached: bool  # True if any configured scan limit stopped further detail
    notes: tuple[str, ...]  # sorted human-readable scan notes (partial-parse, skips)


# --------------------------------------------------------------------------- #
# Optional enrichment region                                                   #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Enrichment:
    """The optional, gated LLM enrichment region (Req 9.3).

    Separated from the deterministic core so enabling/disabling it never alters a
    core field. ``architecture_summary`` is ``""`` and ``model_id`` is ``""`` when
    enrichment is disabled or failed (the whole region is ``None`` on
    :class:`RepoAnalysis` when enrichment is absent).
    """

    architecture_summary: str  # narrative summary; "" when enrichment disabled/failed
    model_id: str  # id of the model that produced it, or ""


# --------------------------------------------------------------------------- #
# Aggregate root                                                               #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class RepoAnalysis:
    """The frozen, versioned aggregate the planner consumes verbatim (Req 6.1).

    Every collection field is a pre-sorted ``tuple`` (the analyzer establishes the
    documented order); the model performs no sorting itself. Empty detection
    categories are present as empty tuples rather than omitted, so the model shape
    is stable (Req 4.6). ``enrichment`` is ``None`` when enrichment is disabled or
    absent (Req 9.4) and is the only field with a default.
    """

    schema_version: int  # == REPO_ANALYSIS_SCHEMA_VERSION
    repo_path: str  # absolute path scanned (for provenance)
    languages: tuple[LanguageStat, ...]  # sorted: LOC desc, then language asc
    primary_languages: tuple[str, ...]  # languages tied for max LOC, sorted asc
    total_loc: int
    total_files: int
    structure: tuple[DirectorySummary, ...]  # sorted by path asc
    entrypoints: tuple[Entrypoint, ...]  # sorted by (path, kind)
    build_files: tuple[BuildFile, ...]  # sorted by path
    ci_workflows: tuple[CIWorkflow, ...]  # sorted by path
    tests: TestLayout
    dependencies: tuple[Dependency, ...]  # sorted by (source, name)
    components: tuple[Component, ...]  # sorted by path
    public_surface: tuple[PublicSymbol, ...]  # sorted by (source, kind, name)
    docs: DocPresence
    artifacts: tuple[Artifact, ...]  # sorted by path
    scan_stats: ScanStats
    enrichment: Enrichment | None = None  # None when enrichment disabled (Req 9.4)
