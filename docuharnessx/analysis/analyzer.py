"""Compose the deterministic, model-free analyzer (task 4.1).

``docuharnessx.analysis.analyzer`` is the single composition layer that turns the
scanner's :class:`~docuharnessx.analysis.scanner.FileInventory` into one frozen
:class:`~docuharnessx.analysis.model.RepoAnalysis` — the planner-facing seam
(design "analyzer — inventory to RepoAnalysis"; Req 3.1-3.3, 4.1-4.6, 5.1-5.6,
9.1, 9.2). It owns *assembly only*: it feeds the inventory through the language
aggregation (task 2.2) and every detector (tasks 3.1-3.3) and slots their results
into the aggregate root. It performs **no** model call and **no** network access
(Req 9.1) — the optional, gated LLM enrichment is a *separate* surface (task 4.2)
that wraps this core, never the other way around, so ``enrichment`` is always
``None`` here (Req 9.4).

Determinism is by composition, not by re-sorting. Each underlying layer already
returns its collection in the order :class:`RepoAnalysis` documents for that field
(``languages`` LOC-desc then name-asc; ``structure`` by path; ``entrypoints`` by
``(path, kind)``; and so on), so the analyzer simply places each pre-sorted tuple
into the matching field — it never re-sorts a layer's output. The model stays a
passive value object whose collections were sorted upstream (design "the analyzer
is responsible for producing pre-sorted tuples ... the model performs no sorting
itself"). Two runs over an unchanged inventory therefore yield **equal**
``RepoAnalysis`` objects that serialize byte-identically (Req 9.1, 9.2).

The analyzer is a pure function of the inventory plus the (small, recognized)
manifest and source files the inventory already lists: :func:`extract_dependencies`
and :func:`detect_public_surface` re-read those files under ``inv.repo_path``
because the scanner does not carry file bodies on ``FileEntry`` (design
"extract_dependencies ... re-reads files from disk"). It stays bounded and
deterministic — it reads only listed files, parses them with stdlib parsers, and
relies on the detectors' own sort/dedup.

Two assembly responsibilities beyond plain composition:

* ``total_loc`` / ``total_files`` are derived directly from the inventory entries
  (summed LOC; entry count, which equals ``stats.files_scanned``) so the aggregate
  carries the project size without the planner re-deriving it (Req 3.2).
* The "partially parsed" notes the dependency parser surfaces
  (:func:`extract_dependencies_with_notes`) are *folded into* the scanner's own
  ``ScanStats.notes`` — the model record the detectors cannot write to directly —
  re-sorted and deduplicated so a malformed manifest is auditable in the single
  ``scan_stats.notes`` field without losing the scanner's skip/limit notes
  (Req 5.6, 10.2). Every other ``ScanStats`` counter is carried through unchanged.
"""

from __future__ import annotations

from docuharnessx.analysis.detectors import (
    detect_artifacts,
    detect_build_files,
    detect_ci,
    detect_docs,
    detect_entrypoints,
    detect_public_surface,
    detect_tests,
    extract_dependencies_with_notes,
    map_components,
    summarize_structure,
)
from docuharnessx.analysis.languages import aggregate_languages
from docuharnessx.analysis.model import (
    REPO_ANALYSIS_SCHEMA_VERSION,
    RepoAnalysis,
    ScanStats,
)
from docuharnessx.analysis.scanner import FileInventory

__all__ = [
    "analyze",
]


def _merge_notes(scan_notes: tuple[str, ...], extra_notes: tuple[str, ...]) -> tuple[str, ...]:
    """Union the scanner's notes with the detector notes, sorted + deduplicated.

    The scanner records skip/limit notes on ``ScanStats.notes``; the dependency
    parser surfaces "partially parsed" notes the detectors cannot write to the
    model directly. Folding them into one sorted, deduplicated tuple keeps every
    scan note in the single auditable ``scan_stats.notes`` field (Req 5.6, 10.2)
    and stays deterministic across runs (Req 9.1).
    """
    return tuple(sorted(set(scan_notes) | set(extra_notes)))


def analyze(inv: FileInventory) -> RepoAnalysis:
    """Compose ``inv`` into a single deterministic core :class:`RepoAnalysis`.

    Feeds the inventory through the language aggregation and every detector and
    assembles a fully **pre-sorted** aggregate root with:

    * the schema version and the inventory's ``repo_path`` for provenance;
    * ``total_loc`` / ``total_files`` derived from the inventory entries;
    * every collection field placed from its layer in that layer's documented sort
      order — the analyzer never re-sorts a layer's output (Req 9.1);
    * empty detection categories present as empty tuples / falsey singular records
      rather than omitted, so the model shape is stable (Req 4.6);
    * the dependency parser's partial-parse notes folded into ``scan_stats.notes``
      alongside the scanner's own notes, sorted and deduplicated (Req 5.6);
    * ``enrichment=None`` — a complete deterministic core with no model, no network
      (Req 9.1, 9.4). The optional gated enrichment is layered on separately
      (task 4.2) and never gates this core.

    Pure and deterministic: two runs over an unchanged inventory return equal
    objects that serialize byte-identically (Req 9.1, 9.2).
    """
    repo_path = inv.repo_path
    entries = inv.entries

    # Language / LOC: aggregate_languages returns (stats LOC-desc/name-asc, primary
    # languages asc) already in the order the model documents (Req 3.2, 3.3).
    language_stats, primary_languages = aggregate_languages(entries)

    # Project size, derived directly from the inventory entries (Req 3.2). The
    # entry count equals stats.files_scanned by construction; LOC is summed over
    # the retained entries (binary/over-cap files contribute their loc==0).
    total_files = len(entries)
    total_loc = sum(int(entry.loc) for entry in entries)

    # Detectors that read only the inventory (pure, pre-sorted by each detector).
    structure = summarize_structure(inv)
    entrypoints = detect_entrypoints(inv)
    build_files = detect_build_files(inv)
    ci_workflows = detect_ci(inv)
    tests = detect_tests(inv)
    components = map_components(inv)
    docs = detect_docs(inv)
    artifacts = detect_artifacts(inv)

    # Detectors that re-read recognized files under repo_path (Req 5.1, 5.3).
    dependencies, dependency_notes = extract_dependencies_with_notes(inv, repo_path)
    public_surface = detect_public_surface(inv, repo_path)

    # Fold the dependency parser's partial-parse notes into the scanner's notes so
    # the single scan_stats.notes field carries every auditable scan note (Req 5.6).
    scan_stats = ScanStats(
        files_scanned=inv.stats.files_scanned,
        files_skipped=inv.stats.files_skipped,
        bytes_scanned=inv.stats.bytes_scanned,
        limit_reached=inv.stats.limit_reached,
        notes=_merge_notes(inv.stats.notes, dependency_notes),
    )

    return RepoAnalysis(
        schema_version=REPO_ANALYSIS_SCHEMA_VERSION,
        repo_path=repo_path,
        languages=language_stats,
        primary_languages=primary_languages,
        total_loc=total_loc,
        total_files=total_files,
        structure=structure,
        entrypoints=entrypoints,
        build_files=build_files,
        ci_workflows=ci_workflows,
        tests=tests,
        dependencies=dependencies,
        components=components,
        public_surface=public_surface,
        docs=docs,
        artifacts=artifacts,
        scan_stats=scan_stats,
        enrichment=None,
    )
