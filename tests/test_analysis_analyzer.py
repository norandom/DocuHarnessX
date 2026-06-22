"""Unit tests for task 4.1 (compose the deterministic analyzer).

Task 4.1's boundary is the new ``docuharnessx.analysis.analyzer`` module. It is the
pure, model-free composition layer that takes the scanner's
:class:`~docuharnessx.analysis.scanner.FileInventory` and assembles a single,
fully **pre-sorted** :class:`~docuharnessx.analysis.model.RepoAnalysis` by feeding
the inventory through the language aggregation and every detector (design
"analyzer — inventory to RepoAnalysis"; Req 3.1-3.3, 4.1-4.6, 5.1-5.6, 9.1, 9.2).

What these tests pin (the analyzer's contract):

* ``analyze(inv) -> RepoAnalysis`` exists, is re-exported from the package, and
  needs no model and no network (Req 9.1).
* The result carries the schema version, the inventory's ``repo_path``, and
  ``enrichment is None`` — a complete deterministic core analysis (Req 9.4).
* ``total_loc`` / ``total_files`` are computed from the inventory entries.
* Every collection field is populated from the matching detector / language layer
  in that layer's documented sort order — the analyzer owns assembly, the layers
  own their own sort (Req 9.1).
* Empty detection categories are present as empty tuples / falsey records rather
  than omitted, so the model shape is stable (Req 4.6).
* Dependency-parse "partially parsed" notes are folded into ``scan_stats.notes``
  alongside the scanner's own notes, sorted and deduplicated (Req 5.6).
* Determinism: analyzing the same inventory twice yields **equal** ``RepoAnalysis``
  objects whose JSON serializes byte-identically (Req 9.1, 9.2).

The tests are pure and self-contained: most run against small hand-built
inventories; the manifest-/source-reading detectors are exercised against files
written into a ``tmp_path`` whose ``repo_path`` the analyzer reads from the
inventory, so no parse depends on the live filesystem layout.
"""

from __future__ import annotations

import importlib

from docuharnessx.analysis import detectors, languages
from docuharnessx.analysis.model import (
    REPO_ANALYSIS_SCHEMA_VERSION,
    RepoAnalysis,
    ScanStats,
)
from docuharnessx.analysis.scanner import FileEntry, FileInventory
from docuharnessx.analysis.serde import to_json

ANALYZER_MODULE = "docuharnessx.analysis.analyzer"
PACKAGE = "docuharnessx.analysis"


# --------------------------------------------------------------------------- #
# Inventory-building helpers (mirror the detector tests)
# --------------------------------------------------------------------------- #


def _analyzer():
    return importlib.import_module(ANALYZER_MODULE)


def _entry(
    path: str,
    *,
    language: str = "Other",
    loc: int = 1,
    size: int = 10,
    is_binary: bool = False,
    read_truncated: bool = False,
) -> FileEntry:
    return FileEntry(
        path=path,
        size=size,
        is_binary=is_binary,
        language=language,
        loc=loc,
        read_truncated=read_truncated,
    )


def _inventory(
    *entries: FileEntry,
    repo_path: str = "/repo",
    files_skipped: int = 0,
    limit_reached: bool = False,
    notes: tuple[str, ...] = (),
) -> FileInventory:
    stats = ScanStats(
        files_scanned=len(entries),
        files_skipped=files_skipped,
        bytes_scanned=sum(e.size for e in entries),
        limit_reached=limit_reached,
        notes=tuple(sorted(notes)),
    )
    sorted_entries = tuple(sorted(entries, key=lambda e: e.path))
    return FileInventory(repo_path=repo_path, entries=sorted_entries, stats=stats)


def _write(tmp_path, rel: str, content: str) -> None:
    target = tmp_path / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


# --------------------------------------------------------------------------- #
# Module / symbol surface
# --------------------------------------------------------------------------- #


def test_task41_analyze_symbol_exists() -> None:
    mod = _analyzer()
    assert hasattr(mod, "analyze")
    assert callable(mod.analyze)
    assert "analyze" in mod.__all__


def test_task41_analyze_reexported_from_package() -> None:
    pkg = importlib.import_module(PACKAGE)
    assert hasattr(pkg, "analyze")
    assert "analyze" in pkg.__all__


# --------------------------------------------------------------------------- #
# Aggregate root scalars / provenance (Req 6.1, 9.4)
# --------------------------------------------------------------------------- #


def test_analyze_returns_repo_analysis_with_version_and_no_enrichment() -> None:
    mod = _analyzer()
    inv = _inventory(_entry("main.go", language="Go", loc=10))
    analysis = mod.analyze(inv)

    assert isinstance(analysis, RepoAnalysis)
    assert analysis.schema_version == REPO_ANALYSIS_SCHEMA_VERSION
    assert analysis.repo_path == "/repo"
    assert analysis.enrichment is None


def test_analyze_computes_total_loc_and_total_files() -> None:
    mod = _analyzer()
    inv = _inventory(
        _entry("a.go", language="Go", loc=10),
        _entry("b.go", language="Go", loc=5),
        _entry("c.py", language="Python", loc=7),
    )
    analysis = mod.analyze(inv)

    assert analysis.total_files == 3
    assert analysis.total_loc == 22


def test_analyze_empty_inventory_yields_stable_empty_shape() -> None:
    mod = _analyzer()
    inv = _inventory(repo_path="/empty")
    analysis = mod.analyze(inv)

    assert analysis.total_files == 0
    assert analysis.total_loc == 0
    assert analysis.languages == ()
    assert analysis.primary_languages == ()
    assert analysis.structure == ()
    assert analysis.entrypoints == ()
    assert analysis.build_files == ()
    assert analysis.ci_workflows == ()
    assert analysis.dependencies == ()
    assert analysis.components == ()
    assert analysis.public_surface == ()
    assert analysis.artifacts == ()
    # Singular records are present (not None) as their stable empty form.
    assert analysis.tests.present is False
    assert analysis.tests.frameworks == ()
    assert analysis.tests.paths == ()
    assert analysis.docs.has_readme is False
    assert analysis.docs.readme_paths == ()
    assert analysis.enrichment is None


# --------------------------------------------------------------------------- #
# Composition: each field matches the underlying layer (Req 9.1)
# --------------------------------------------------------------------------- #


def test_analyze_languages_match_aggregate_languages() -> None:
    mod = _analyzer()
    inv = _inventory(
        _entry("a.go", language="Go", loc=30),
        _entry("b.go", language="Go", loc=10),
        _entry("r.md", language="Markdown", loc=100),
    )
    analysis = mod.analyze(inv)

    expected_stats, expected_primary = languages.aggregate_languages(inv.entries)
    assert analysis.languages == expected_stats
    assert analysis.primary_languages == expected_primary
    # Higher-LOC source vs many docs: Markdown has the most LOC here, so it leads.
    assert analysis.languages[0].language == "Markdown"
    assert analysis.primary_languages == ("Markdown",)


def test_analyze_detector_fields_match_each_detector() -> None:
    mod = _analyzer()
    inv = _inventory(
        _entry("main.go", language="Go", loc=20),
        _entry("internal/hash/hash.go", language="Go", loc=40),
        _entry("internal/hash/hash_test.go", language="Go", loc=15),
        _entry(".github/workflows/ci.yml", language="YAML", loc=5),
        _entry("Makefile", language="Makefile", loc=8),
        _entry("README.md", language="Markdown", loc=30),
        _entry("LICENSE", language="Other", loc=20),
        repo_path="/repo",
    )
    analysis = mod.analyze(inv)

    assert analysis.structure == detectors.summarize_structure(inv)
    assert analysis.entrypoints == detectors.detect_entrypoints(inv)
    assert analysis.build_files == detectors.detect_build_files(inv)
    assert analysis.ci_workflows == detectors.detect_ci(inv)
    assert analysis.tests == detectors.detect_tests(inv)
    assert analysis.components == detectors.map_components(inv)
    assert analysis.docs == detectors.detect_docs(inv)
    assert analysis.artifacts == detectors.detect_artifacts(inv)

    # Sanity: the detectors actually found the expected signals.
    assert any(e.kind == "main" for e in analysis.entrypoints)
    assert any(w.provider == "github_actions" for w in analysis.ci_workflows)
    assert analysis.tests.present is True
    assert analysis.docs.has_readme is True
    assert any(a.kind == "license" for a in analysis.artifacts)


def test_analyze_reads_dependencies_and_public_surface_from_disk(tmp_path) -> None:
    mod = _analyzer()
    repo = str(tmp_path)
    _write(
        tmp_path,
        "go.mod",
        "module example.com/x\n\ngo 1.22\n\nrequire (\n\tgithub.com/spf13/cobra v1.8.0\n)\n",
    )
    _write(
        tmp_path,
        "main.go",
        'package main\n\nfunc Run() {}\n\ntype Config struct{}\n',
    )

    inv = _inventory(
        _entry("go.mod", language="GoMod", loc=7),
        _entry("main.go", language="Go", loc=5),
        repo_path=repo,
    )
    analysis = mod.analyze(inv)

    assert analysis.dependencies == detectors.extract_dependencies(inv, repo)
    assert any(d.name == "github.com/spf13/cobra" for d in analysis.dependencies)

    assert analysis.public_surface == detectors.detect_public_surface(inv, repo)
    assert any(
        s.name == "Run" and s.kind == "exported_symbol"
        for s in analysis.public_surface
    )


# --------------------------------------------------------------------------- #
# Note folding (Req 5.6)
# --------------------------------------------------------------------------- #


def test_analyze_folds_partial_parse_notes_into_scan_stats(tmp_path) -> None:
    mod = _analyzer()
    repo = str(tmp_path)
    # A malformed pyproject.toml triggers a "partially parsed" dependency note.
    _write(tmp_path, "pyproject.toml", "this is not = valid = toml [[[")

    inv = _inventory(
        _entry("pyproject.toml", language="TOML", loc=1),
        repo_path=repo,
        notes=("skipped unreadable entry: secret.bin",),
    )
    analysis = mod.analyze(inv)

    # The scanner's own note is preserved.
    assert "skipped unreadable entry: secret.bin" in analysis.scan_stats.notes
    # And the dependency parser's partial-parse note is folded in.
    assert any(
        "partially parsed" in note and "pyproject.toml" in note
        for note in analysis.scan_stats.notes
    )
    # Notes are sorted and deduplicated.
    assert list(analysis.scan_stats.notes) == sorted(set(analysis.scan_stats.notes))


def test_analyze_preserves_scan_stats_counters() -> None:
    mod = _analyzer()
    inv = _inventory(
        _entry("a.go", language="Go", loc=3, size=40),
        _entry("b.go", language="Go", loc=2, size=20),
        files_skipped=4,
        limit_reached=True,
        notes=("scan stopped: total-file limit reached",),
    )
    analysis = mod.analyze(inv)

    assert analysis.scan_stats.files_scanned == inv.stats.files_scanned
    assert analysis.scan_stats.files_skipped == 4
    assert analysis.scan_stats.bytes_scanned == inv.stats.bytes_scanned
    assert analysis.scan_stats.limit_reached is True
    assert "scan stopped: total-file limit reached" in analysis.scan_stats.notes


# --------------------------------------------------------------------------- #
# Determinism (Req 9.1, 9.2)
# --------------------------------------------------------------------------- #


def test_analyze_is_deterministic_across_runs(tmp_path) -> None:
    mod = _analyzer()
    repo = str(tmp_path)
    _write(tmp_path, "go.mod", "module x\n\nrequire github.com/a/b v1.0.0\n")
    _write(tmp_path, "main.go", "package main\n\nfunc Main() {}\n")
    _write(tmp_path, "README.md", "# Title\n")

    inv = _inventory(
        _entry("go.mod", language="GoMod", loc=3),
        _entry("main.go", language="Go", loc=3),
        _entry("README.md", language="Markdown", loc=1),
        repo_path=repo,
    )

    first = mod.analyze(inv)
    second = mod.analyze(inv)

    assert first == second
    assert to_json(first) == to_json(second)


def test_analyze_is_model_free_and_offline(monkeypatch) -> None:
    """The analyzer must not open a network socket (Req 9.1)."""
    import socket

    def _boom(*_args, **_kwargs):  # pragma: no cover - only fires on a violation
        raise AssertionError("analyze() must not perform network access")

    monkeypatch.setattr(socket.socket, "connect", _boom)
    inv = _inventory(_entry("main.go", language="Go", loc=4))
    analysis = _analyzer().analyze(inv)
    assert analysis.enrichment is None


# --------------------------------------------------------------------------- #
# Reference-repo smoke (Req 9.2) — the real Go CLI tree
# --------------------------------------------------------------------------- #


def test_analyze_reference_repo_is_go_and_deterministic() -> None:
    import os

    reference = "/home/mc/Source/malware_hashes"
    if not os.path.isdir(reference):  # pragma: no cover - env-dependent
        import pytest

        pytest.skip("reference repo not present")

    from docuharnessx.analysis.scanner import scan

    inv = scan(reference)
    mod = _analyzer()
    first = mod.analyze(inv)
    second = mod.analyze(scan(reference))

    # Go is the dominant *source* language of the real CLI tree (the repo also
    # ships a large .kiro spec corpus, so Markdown may carry more total LOC; the
    # primary-language pin against the full source tree is task 6.3's concern).
    source_langs = {"Go", "Python", "TypeScript", "JavaScript", "Rust", "C", "C++"}
    source_stats = [s for s in first.languages if s.language in source_langs]
    assert source_stats, "expected at least one source language"
    assert source_stats[0].language == "Go"

    # Determinism over the real polyglot tree: two scans + analyses are equal and
    # serialize byte-identically (Req 9.2).
    assert first == second
    assert to_json(first) == to_json(second)
