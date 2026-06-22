"""Deterministic serialize / deserialize for the ``RepoAnalysis`` seam (task 1.2).

This module gives the frozen :class:`~docuharnessx.analysis.model.RepoAnalysis`
contract a plain, ordered, JSON-compatible serialization and a round-trip
deserialization, so the downstream ``classification-coverage-planner`` can persist
and reload the analysis without depending on the in-memory model classes (design
"serde — deterministic serialization"; Req 6.3, 6.4, 6.5, 6.6).

Three functions form the public surface:

* :func:`to_dict` — convert a ``RepoAnalysis`` to a plain ``dict`` of JSON
  primitives. Nested frozen records become nested dicts; every ``tuple`` becomes a
  ``list`` *preserving the analyzer's sort order* (the model is already pre-sorted,
  so serde never re-orders collection elements); an absent enrichment region
  becomes ``None``/``null`` (Req 6.4, 9.4).
* :func:`from_dict` — reconstruct an **equal** ``RepoAnalysis`` from such a dict
  (round-trip equality, Req 6.5). It first checks ``schema_version``: an unknown or
  missing version raises :class:`RepoAnalysisVersionError` naming the offending
  version so a consumer reading a future/foreign contract fails loudly rather than
  mis-reconstructing the seam (Req 6.3, 6.6).
* :func:`to_json` — ``json.dumps(to_dict(...), sort_keys=True, ensure_ascii=False)``.
  ``sort_keys`` makes the emitted key order independent of dict insertion order and
  the pre-sorted collections make element order stable, so two runs over an
  unchanged repo serialize **byte-identically** (Req 6.4).

Determinism rests on two pins: the analyzer produces pre-sorted tuples (the model
never sorts, and neither does serde), and JSON emission uses ``sort_keys=True``.
No nondeterministic dict iteration leaks into the output.

This module owns serialization only — the model (task 1.1), the error hierarchy
(task 1.5), and the scanner/analyzer/stages live elsewhere.
"""

from __future__ import annotations

import dataclasses
import json
from typing import Any

from docuharnessx.analysis.errors import RepoAnalysisVersionError
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

__all__ = [
    "to_dict",
    "from_dict",
    "to_json",
]


# --------------------------------------------------------------------------- #
# Serialization tables                                                         #
# --------------------------------------------------------------------------- #

# The nested-record types whose fields are JSON primitives or tuples of those
# primitives. ``to_dict`` turns each into a plain dict; ``from_dict`` rebuilds the
# frozen instance from that dict. The aggregate root and the two singular nested
# records (``TestLayout``, ``DocPresence``, ``ScanStats``, ``Enrichment``) are
# handled explicitly because they nest other records / the optional region.
_LEAF_RECORD_TYPES: tuple[type, ...] = (
    LanguageStat,
    DirectorySummary,
    Entrypoint,
    BuildFile,
    CIWorkflow,
    Dependency,
    Component,
    PublicSymbol,
    Artifact,
)

# RepoAnalysis fields that hold a ``tuple`` of a single leaf-record type. Mapping
# the field name to its element type lets ``from_dict`` reconstruct the right frozen
# record for each element without per-field branching (Req 6.5).
_TUPLE_RECORD_FIELDS: dict[str, type] = {
    "languages": LanguageStat,
    "structure": DirectorySummary,
    "entrypoints": Entrypoint,
    "build_files": BuildFile,
    "ci_workflows": CIWorkflow,
    "dependencies": Dependency,
    "components": Component,
    "public_surface": PublicSymbol,
    "artifacts": Artifact,
}

# RepoAnalysis fields that hold a ``tuple`` of plain strings (no nested records).
_TUPLE_STR_FIELDS: tuple[str, ...] = ("primary_languages",)

# RepoAnalysis fields that are scalar (int / str) carried through unchanged.
_SCALAR_FIELDS: tuple[str, ...] = (
    "schema_version",
    "repo_path",
    "total_loc",
    "total_files",
)


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #


def _record_to_dict(record: Any) -> dict[str, Any]:
    """Convert a leaf frozen record to a plain dict, tuples -> lists.

    Iterates ``dataclasses.fields`` so the emitted key order follows the field
    declaration order; any tuple-valued field (e.g. a representative-file set)
    becomes a list preserving its pre-sorted order.
    """
    out: dict[str, Any] = {}
    for field in dataclasses.fields(record):
        value = getattr(record, field.name)
        out[field.name] = list(value) if isinstance(value, tuple) else value
    return out


def _test_layout_to_dict(layout: TestLayout) -> dict[str, Any]:
    return {
        "present": layout.present,
        "frameworks": list(layout.frameworks),
        "paths": list(layout.paths),
    }


def _doc_presence_to_dict(docs: DocPresence) -> dict[str, Any]:
    return {
        "has_readme": docs.has_readme,
        "readme_paths": list(docs.readme_paths),
        "doc_dirs": list(docs.doc_dirs),
        "other_docs": list(docs.other_docs),
    }


def _scan_stats_to_dict(stats: ScanStats) -> dict[str, Any]:
    return {
        "files_scanned": stats.files_scanned,
        "files_skipped": stats.files_skipped,
        "bytes_scanned": stats.bytes_scanned,
        "limit_reached": stats.limit_reached,
        "notes": list(stats.notes),
    }


def _enrichment_to_dict(enrichment: Enrichment | None) -> dict[str, Any] | None:
    if enrichment is None:
        return None
    return {
        "architecture_summary": enrichment.architecture_summary,
        "model_id": enrichment.model_id,
    }


# --------------------------------------------------------------------------- #
# Public API                                                                   #
# --------------------------------------------------------------------------- #


def to_dict(analysis: RepoAnalysis) -> dict[str, Any]:
    """Serialize a ``RepoAnalysis`` to a plain, ordered, JSON-compatible dict.

    Every tuple becomes a list (preserving the analyzer's pre-sorted order); every
    nested frozen record becomes a nested dict; the optional enrichment region
    becomes ``None`` when absent (Req 6.4, 9.4). The result contains only JSON
    primitives, so :func:`json.dumps` accepts it without a custom encoder.
    """
    return {
        "schema_version": analysis.schema_version,
        "repo_path": analysis.repo_path,
        "languages": [_record_to_dict(s) for s in analysis.languages],
        "primary_languages": list(analysis.primary_languages),
        "total_loc": analysis.total_loc,
        "total_files": analysis.total_files,
        "structure": [_record_to_dict(d) for d in analysis.structure],
        "entrypoints": [_record_to_dict(e) for e in analysis.entrypoints],
        "build_files": [_record_to_dict(b) for b in analysis.build_files],
        "ci_workflows": [_record_to_dict(c) for c in analysis.ci_workflows],
        "tests": _test_layout_to_dict(analysis.tests),
        "dependencies": [_record_to_dict(d) for d in analysis.dependencies],
        "components": [_record_to_dict(c) for c in analysis.components],
        "public_surface": [_record_to_dict(p) for p in analysis.public_surface],
        "docs": _doc_presence_to_dict(analysis.docs),
        "artifacts": [_record_to_dict(a) for a in analysis.artifacts],
        "scan_stats": _scan_stats_to_dict(analysis.scan_stats),
        "enrichment": _enrichment_to_dict(analysis.enrichment),
    }


def from_dict(data: dict[str, Any]) -> RepoAnalysis:
    """Reconstruct an equal ``RepoAnalysis`` from a :func:`to_dict` payload.

    The ``schema_version`` is validated first: a missing or unrecognized version
    raises :class:`RepoAnalysisVersionError` naming the offending value, so a
    consumer reading a future/foreign contract fails loudly rather than silently
    mis-reconstructing the seam (Req 6.3, 6.6). For a recognized version, every
    collection is rebuilt as a tuple of the appropriate frozen record so
    ``from_dict(to_dict(a)) == a`` (round-trip equality, Req 6.5).
    """
    version = data.get("schema_version")
    if version != REPO_ANALYSIS_SCHEMA_VERSION:
        raise RepoAnalysisVersionError(
            "unsupported RepoAnalysis schema_version "
            f"{version!r}; this build understands "
            f"version {REPO_ANALYSIS_SCHEMA_VERSION}"
        )

    tests = data["tests"]
    docs = data["docs"]
    scan_stats = data["scan_stats"]
    enrichment = data["enrichment"]

    return RepoAnalysis(
        schema_version=data["schema_version"],
        repo_path=data["repo_path"],
        languages=tuple(LanguageStat(**s) for s in data["languages"]),
        primary_languages=tuple(data["primary_languages"]),
        total_loc=data["total_loc"],
        total_files=data["total_files"],
        structure=tuple(DirectorySummary(**d) for d in data["structure"]),
        entrypoints=tuple(Entrypoint(**e) for e in data["entrypoints"]),
        build_files=tuple(BuildFile(**b) for b in data["build_files"]),
        ci_workflows=tuple(CIWorkflow(**c) for c in data["ci_workflows"]),
        tests=TestLayout(
            present=tests["present"],
            frameworks=tuple(tests["frameworks"]),
            paths=tuple(tests["paths"]),
        ),
        dependencies=tuple(Dependency(**d) for d in data["dependencies"]),
        components=tuple(
            Component(
                name=c["name"],
                path=c["path"],
                representative_files=tuple(c["representative_files"]),
            )
            for c in data["components"]
        ),
        public_surface=tuple(PublicSymbol(**p) for p in data["public_surface"]),
        docs=DocPresence(
            has_readme=docs["has_readme"],
            readme_paths=tuple(docs["readme_paths"]),
            doc_dirs=tuple(docs["doc_dirs"]),
            other_docs=tuple(docs["other_docs"]),
        ),
        artifacts=tuple(Artifact(**a) for a in data["artifacts"]),
        scan_stats=ScanStats(
            files_scanned=scan_stats["files_scanned"],
            files_skipped=scan_stats["files_skipped"],
            bytes_scanned=scan_stats["bytes_scanned"],
            limit_reached=scan_stats["limit_reached"],
            notes=tuple(scan_stats["notes"]),
        ),
        enrichment=(
            None
            if enrichment is None
            else Enrichment(
                architecture_summary=enrichment["architecture_summary"],
                model_id=enrichment["model_id"],
            )
        ),
    )


def to_json(analysis: RepoAnalysis) -> str:
    """Serialize a ``RepoAnalysis`` to a byte-stable JSON string (Req 6.4).

    Uses ``sort_keys=True`` so the emitted key order is independent of dict
    insertion order, and ``ensure_ascii=False`` so non-ASCII text is emitted
    literally (stable and human-readable). Combined with the analyzer's pre-sorted
    collections, two runs over an unchanged repo produce byte-identical JSON.
    """
    return json.dumps(to_dict(analysis), sort_keys=True, ensure_ascii=False)
