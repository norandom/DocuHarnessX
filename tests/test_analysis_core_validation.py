"""Task 6.1 — unit-test the deterministic core against crafted fixtures.

This is the **validation** suite for Wave 1's deterministic analysis core. Where
the per-module sibling suites (``test_analysis_scanner``, ``test_analysis_languages``,
``test_analysis_serde``, ``test_analysis_model``, ``test_analysis_detectors*``)
each pin one module in isolation, this suite is the cross-cutting determinism gate
the task calls for: it crafts fixture trees, drives them through the *whole* core
(scanner -> languages -> detectors -> serde -> model), and asserts the results are
**byte-identical across two runs over the same fixtures** — the task's stated
observable (tasks.md 6.1; design "Testing Strategy → Unit Tests").

Boundary (task 6.1): ``scanner``, ``languages``, ``detectors``, ``serde``,
``model``. The stages (task 5.x), the analyzer composition (covered by task 4.1's
suite), enrichment (task 4.2), and the reference-repo run (task 6.3) are out of
scope here, except that this suite reuses the reference repo for two cross-cutting
determinism checks that fall squarely inside the scanner/detector boundary.

Coverage map (every clause of tasks.md 6.1):

* excluded-dir non-descent ............... :class:`TestScannerEdgeCases`
* symlink-escape non-follow .............. :class:`TestScannerEdgeCases`
* binary/text classification ............. :class:`TestScannerEdgeCases`
* over-size truncation ................... :class:`TestScannerEdgeCases`
* total-limit trip ....................... :class:`TestScannerEdgeCases`
* edge-case files (empty/0-byte/no-ext) .. :class:`TestScannerEdgeCases`
* language/LOC ordering ................... :class:`TestLanguageOrdering`
* primary-language ties .................. :class:`TestLanguageOrdering`
* serde round-trip ....................... :class:`TestSerdeContract`
* byte-stable JSON ....................... :class:`TestSerdeContract`
* version rejection ...................... :class:`TestSerdeContract`
* nested-manifest detection .............. :class:`TestDetectorSignals`
* CI/test detection ...................... :class:`TestDetectorSignals`
* malformed-manifest partial parse ....... :class:`TestDetectorSignals`
* conservative public-surface extraction . :class:`TestDetectorSignals`
* byte-identical across two runs ......... :class:`TestEndToEndDeterminism`

Requirements: 1.3, 1.4, 1.5, 1.6, 2.1, 2.2, 2.3, 2.4, 3.1, 3.2, 3.3, 3.4, 3.5,
4.3, 4.4, 4.5, 5.1, 5.3, 5.6, 6.4, 6.5, 6.6, 9.1, 9.2.
"""

from __future__ import annotations

import json
import os

import pytest

from docuharnessx.analysis import scanner as scanner_mod
from docuharnessx.analysis.languages import aggregate_languages, detect_language
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
)
from docuharnessx.analysis.model import TestLayout as _TestLayout
from docuharnessx.analysis.detectors import (
    detect_build_files,
    detect_ci,
    detect_public_surface,
    detect_tests,
    extract_dependencies,
    extract_dependencies_with_notes,
)
from docuharnessx.analysis.errors import RepoAnalysisVersionError
from docuharnessx.analysis.scanner import FileEntry, ScanLimits, scan
from docuharnessx.analysis.serde import from_dict, to_dict, to_json

REFERENCE_REPO = "/home/mc/Source/malware_hashes"


# --------------------------------------------------------------------------- #
# Fixture-building helpers (raw-bytes write so binary/edge cases are exact)    #
# --------------------------------------------------------------------------- #


def _write(base, rel_path: str, data: bytes) -> None:
    """Create ``base/rel_path`` (with parents), writing raw bytes verbatim."""
    full = os.path.join(str(base), *rel_path.split("/"))
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "wb") as handle:
        handle.write(data)


def _text(base, rel_path: str, text: str) -> None:
    """Create a UTF-8 text file at ``base/rel_path``."""
    _write(base, rel_path, text.encode("utf-8"))


def _paths(inv) -> list[str]:
    return [e.path for e in inv.entries]


def _entry(inv, rel_path: str) -> FileEntry | None:
    for entry in inv.entries:
        if entry.path == rel_path:
            return entry
    return None


# --------------------------------------------------------------------------- #
# A reusable, realistic polyglot fixture tree                                   #
# --------------------------------------------------------------------------- #


def _build_polyglot_repo(base) -> None:
    """Craft a small polyglot Go+Python repo exercising every detector concern.

    Mirrors the reference-repo shape (root + nested ``go.mod``, GitHub Actions +
    Dagger CI, ``*_test.go`` tests, README) while staying fully synthetic so the
    determinism assertions never depend on an external checkout.
    """
    # Go primary module: entrypoint + an internal component + a test file.
    _text(
        base,
        "main.go",
        "package main\n\n"
        "import \"fmt\"\n\n"
        "func Run() {}\n"
        "func main() { fmt.Println(\"hi\") }\n",
    )
    _text(
        base,
        "internal/hash/hash.go",
        "package hash\n\n"
        "func Sum() int { return 0 }\n"
        "type Hasher struct{}\n"
        "func helper() {}\n",
    )
    _text(
        base,
        "internal/hash/hash_test.go",
        "package hash\n\nimport \"testing\"\n\n"
        "func TestSum(t *testing.T) {}\n",
    )
    # Root and nested manifests (Req 4.3 nested sub-project detection).
    _text(
        base,
        "go.mod",
        "module example.com/poly\n\ngo 1.22\n\n"
        "require (\n\tgithub.com/spf13/cobra v1.8.0\n)\n",
    )
    _text(base, "go.sum", "github.com/spf13/cobra v1.8.0 h1:abc=\n")
    _text(
        base,
        ".dagger/go.mod",
        "module example.com/poly/dagger\n\ngo 1.22\n\n"
        "require (\n\tdagger.io/dagger v0.11.0\n)\n",
    )
    # CI: GitHub Actions (two workflows) + a Dagger config (Req 4.4).
    _text(base, ".github/workflows/ci.yml", "name: ci\non: [push]\n")
    _text(base, ".github/workflows/release.yml", "name: release\non: [tag]\n")
    _text(base, "dagger.json", "{\"name\": \"poly\"}\n")
    # A Python sub-tool with its own manifest + argparse CLI + __all__.
    _text(
        base,
        "tools/util.py",
        "__all__ = [\"main\", \"helper\"]\n\n"
        "import argparse\n\n"
        "def main():\n"
        "    p = argparse.ArgumentParser()\n"
        "    p.add_argument(\"--verbose\")\n"
        "    p.add_argument(\"--out\")\n\n"
        "def helper():\n    pass\n",
    )
    _text(
        base,
        "pyproject.toml",
        "[project]\nname = \"poly-tools\"\nversion = \"0.1.0\"\n"
        "dependencies = [\"requests>=2.0\", \"click\"]\n",
    )
    # Docs + license artifact.
    _text(base, "README.md", "# Poly\n\nA polyglot fixture.\n")
    _text(base, "docs/guide.md", "# Guide\n\nSome docs.\n")
    _text(base, "LICENSE", "MIT License\n\nCopyright\n")


# --------------------------------------------------------------------------- #
# Scanner edge cases (Req 1.3-1.6, 2.1-2.4)                                     #
# --------------------------------------------------------------------------- #


class TestScannerEdgeCases:
    def test_excluded_dir_not_descended(self, tmp_path):
        """A noise directory is pruned and its contents never appear (Req 1.4)."""
        _text(tmp_path, "keep.py", "x = 1\n")
        _text(tmp_path, "node_modules/dep/index.js", "module.exports = {}\n")
        _text(tmp_path, "src/.venv/lib/pkg.py", "y = 2\n")
        _text(tmp_path, ".git/config", "[core]\n")

        inv = scan(str(tmp_path))
        paths = _paths(inv)

        assert "keep.py" in paths
        assert all("node_modules" not in p for p in paths)
        assert all(".venv" not in p for p in paths)
        assert all(p.split("/")[0] != ".git" for p in paths)

    def test_symlink_escaping_root_not_followed(self, tmp_path):
        """A symlink pointing outside the repo root is dropped + noted (Req 1.5)."""
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "secret.txt").write_text("secret\n")

        repo = tmp_path / "repo"
        repo.mkdir()
        _text(repo, "real.py", "z = 3\n")
        link = repo / "escape.txt"
        try:
            os.symlink(str(outside / "secret.txt"), str(link))
        except (OSError, NotImplementedError):  # pragma: no cover
            pytest.skip("symlinks unsupported on this platform")

        inv = scan(str(repo))
        paths = _paths(inv)

        assert "real.py" in paths
        assert "escape.txt" not in paths
        assert inv.stats.files_skipped >= 1
        assert any("symlink" in note for note in inv.stats.notes)

    def test_binary_vs_text_classification(self, tmp_path):
        """A NUL-bearing file is binary with loc==0; UTF-8 text stays text (Req 2.1)."""
        _write(tmp_path, "blob.bin", b"\x00\x01\x02\x03binary\x00data")
        _text(tmp_path, "code.py", "a = 1\nb = 2\n")

        inv = scan(str(tmp_path))
        blob = _entry(inv, "blob.bin")
        code = _entry(inv, "code.py")

        assert blob is not None and blob.is_binary is True and blob.loc == 0
        assert code is not None and code.is_binary is False and code.loc == 2

    def test_over_size_file_truncated(self, tmp_path):
        """An over-cap file is in the inventory with loc==0, read_truncated (Req 2.2)."""
        _write(tmp_path, "big.txt", b"line\n" * 1000)  # 5000 bytes
        _text(tmp_path, "small.txt", "one\ntwo\n")

        inv = scan(str(tmp_path), limits=ScanLimits(max_file_bytes=100))
        big = _entry(inv, "big.txt")
        small = _entry(inv, "small.txt")

        assert big is not None
        assert big.read_truncated is True
        assert big.loc == 0
        assert big.size == 5000  # full on-disk size is still recorded
        assert small is not None and small.read_truncated is False and small.loc == 2

    def test_total_file_limit_trips(self, tmp_path):
        """The total-file cap stops detail, flags limit_reached, still well-formed (Req 2.3)."""
        for i in range(8):
            _text(tmp_path, f"f{i}.py", "x = 1\n")

        inv = scan(str(tmp_path), limits=ScanLimits(max_total_files=3))

        assert inv.stats.limit_reached is True
        assert len(inv.entries) == 3
        assert any("limit" in note for note in inv.stats.notes)
        # Still a well-formed, sorted inventory.
        assert _paths(inv) == sorted(_paths(inv))

    def test_total_byte_limit_trips(self, tmp_path):
        """The total-byte cap also trips limit_reached without aborting (Req 2.3)."""
        _text(tmp_path, "a.txt", "x" * 60)
        _text(tmp_path, "b.txt", "y" * 60)
        _text(tmp_path, "c.txt", "z" * 60)

        inv = scan(str(tmp_path), limits=ScanLimits(max_total_bytes=100))

        assert inv.stats.limit_reached is True
        assert inv.stats.bytes_scanned <= 100
        assert any("limit" in note for note in inv.stats.notes)

    def test_edge_case_files_classified_other_without_error(self, tmp_path):
        """Zero-byte, extensionless, and unknown-type files are 'Other', no error (Req 2.4)."""
        _write(tmp_path, "empty.py", b"")  # zero-byte
        _write(tmp_path, "noext", b"plain content\n")  # extensionless
        _text(tmp_path, "weird.zzz", "unknown type\n")  # unknown extension
        (tmp_path / "empty_dir").mkdir()  # empty directory: produces no entry

        inv = scan(str(tmp_path))
        paths = _paths(inv)

        # Empty directory contributes no entry and does not raise.
        assert "empty_dir" not in paths
        empty = _entry(inv, "empty.py")
        noext = _entry(inv, "noext")
        weird = _entry(inv, "weird.zzz")
        assert empty is not None and empty.size == 0 and empty.loc == 0
        assert noext is not None and noext.language == "Other"
        assert weird is not None and weird.language == "Other"

    def test_scan_is_byte_identical_across_two_runs(self, tmp_path):
        """Two scans of an unchanged tree produce equal inventories (Req 1.6, 9.1)."""
        _build_polyglot_repo(tmp_path)
        first = scan(str(tmp_path))
        second = scan(str(tmp_path))
        assert first == second


# --------------------------------------------------------------------------- #
# Language ordering + primary-language ties (Req 3.1-3.5)                       #
# --------------------------------------------------------------------------- #


class TestLanguageOrdering:
    def test_detect_language_extension_filename_and_other(self):
        """Extension + special-filename mapping with an 'Other' fallback (Req 3.1, 3.4)."""
        assert detect_language("cmd/main.go") == "Go"
        assert detect_language("pkg/util.py") == "Python"
        assert detect_language("README.md") == "Markdown"
        assert detect_language("Dockerfile") == "Dockerfile"
        assert detect_language("Makefile") == "Makefile"
        assert detect_language("go.mod") == "GoMod"
        # Unknown extension, extensionless, dotfile, empty -> Other (Req 3.4).
        assert detect_language("data.zzz") == "Other"
        assert detect_language("LICENSE") == "Other"
        assert detect_language(".gitignore") == "Other"
        assert detect_language("") == "Other"

    def test_aggregate_orders_by_loc_desc_then_name_asc(self):
        """LanguageStats sort by LOC desc, ties broken by name asc (Req 3.2)."""
        entries = [
            FileEntry("a.py", 1, False, "Python", 10, False),
            FileEntry("b.py", 1, False, "Python", 5, False),  # Python = 15 LOC
            FileEntry("c.go", 1, False, "Go", 30, False),  # Go = 30 LOC
            FileEntry("z.rs", 1, False, "Rust", 15, False),  # Rust = 15 LOC (ties Python)
        ]
        stats, _primary = aggregate_languages(entries)

        # Go(30) first; then the 15-LOC tie broken by name asc: Python before Rust.
        assert [s.language for s in stats] == ["Go", "Python", "Rust"]
        assert [s.loc for s in stats] == [30, 15, 15]
        assert [s.files for s in stats] == [1, 2, 1]

    def test_primary_language_is_highest_loc_not_file_count(self):
        """Many docs files but a higher-LOC source language -> source is primary (Req 3.3)."""
        entries = [
            FileEntry(f"doc{i}.md", 1, False, "Markdown", 3, False)
            for i in range(10)  # Markdown: 10 files, 30 LOC total
        ] + [
            FileEntry("core.go", 1, False, "Go", 100, False),  # Go: 1 file, 100 LOC
        ]
        stats, primary = aggregate_languages(entries)

        assert primary == ("Go",)
        assert stats[0].language == "Go"

    def test_primary_language_ties_reported_sorted(self):
        """All languages tied for max LOC are primary, sorted ascending (Req 3.3)."""
        entries = [
            FileEntry("a.go", 1, False, "Go", 40, False),
            FileEntry("b.rs", 1, False, "Rust", 40, False),
            FileEntry("c.py", 1, False, "Python", 40, False),
            FileEntry("d.md", 1, False, "Markdown", 5, False),
        ]
        _stats, primary = aggregate_languages(entries)
        assert primary == ("Go", "Python", "Rust")

    def test_aggregate_empty_and_zero_loc(self):
        """No entries -> empty; only zero-LOC files -> degenerate primaries (Req 3.4)."""
        assert aggregate_languages([]) == ((), ())
        entries = [
            FileEntry("a.go", 1, False, "Go", 0, False),
            FileEntry("b.py", 1, False, "Python", 0, False),
        ]
        _stats, primary = aggregate_languages(entries)
        assert primary == ("Go", "Python")

    def test_aggregation_is_order_independent(self):
        """Permuting the input does not change the aggregation (Req 3.5)."""
        entries = [
            FileEntry("a.go", 1, False, "Go", 10, False),
            FileEntry("b.py", 1, False, "Python", 20, False),
            FileEntry("c.go", 1, False, "Go", 5, False),
        ]
        forward = aggregate_languages(entries)
        backward = aggregate_languages(list(reversed(entries)))
        assert forward == backward


# --------------------------------------------------------------------------- #
# Serde contract: round-trip, byte-stable JSON, version rejection (Req 6.4-6.6) #
# --------------------------------------------------------------------------- #


def _sample_analysis(*, enriched: bool = False) -> RepoAnalysis:
    """A hand-built, fully-populated RepoAnalysis covering every field shape."""
    enrichment = (
        Enrichment(architecture_summary="A layered CLI.", model_id="m-1")
        if enriched
        else None
    )
    return RepoAnalysis(
        schema_version=REPO_ANALYSIS_SCHEMA_VERSION,
        repo_path="/abs/repo",
        languages=(
            LanguageStat("Go", 3, 120),
            LanguageStat("Python", 2, 40),
        ),
        primary_languages=("Go",),
        total_loc=160,
        total_files=5,
        structure=(
            DirectorySummary("", 5, "Go", "source"),
            DirectorySummary("internal", 2, "Go", "source"),
        ),
        entrypoints=(Entrypoint("main.go", "main", ""),),
        build_files=(
            BuildFile("go.mod", "go_mod"),
            BuildFile("pyproject.toml", "pyproject"),
        ),
        ci_workflows=(CIWorkflow(".github/workflows/ci.yml", "github_actions"),),
        tests=_TestLayout(
            present=True,
            frameworks=("go_testing",),
            paths=("internal/hash/hash_test.go",),
        ),
        dependencies=(
            Dependency("cobra", "v1.8.0", "go.mod", "runtime"),
            Dependency("requests", ">=2.0", "pyproject.toml", "runtime"),
        ),
        components=(
            Component("internal", "internal", ("internal/hash/hash.go",)),
        ),
        public_surface=(
            PublicSymbol("Run", "exported_symbol", "main.go"),
            PublicSymbol("--verbose", "cli_flag", "tools/util.py"),
        ),
        docs=DocPresence(
            has_readme=True,
            readme_paths=("README.md",),
            doc_dirs=("docs",),
            other_docs=(),
        ),
        artifacts=(Artifact("LICENSE", "license"),),
        scan_stats=ScanStats(
            files_scanned=5,
            files_skipped=0,
            bytes_scanned=2048,
            limit_reached=False,
            notes=(),
        ),
        enrichment=enrichment,
    )


class TestSerdeContract:
    @pytest.mark.parametrize("enriched", [False, True])
    def test_round_trip_equality(self, enriched):
        """from_dict(to_dict(a)) == a, including the optional enrichment region (Req 6.5)."""
        analysis = _sample_analysis(enriched=enriched)
        assert from_dict(to_dict(analysis)) == analysis

    def test_json_is_byte_stable_for_equal_inputs(self):
        """to_json is byte-identical across repeated calls for equal inputs (Req 6.4)."""
        a = _sample_analysis()
        b = _sample_analysis()  # equal but distinct instance
        assert a == b
        assert to_json(a) == to_json(b)
        assert to_json(a) == to_json(a)
        # And it is valid JSON that re-parses to the to_dict payload.
        assert json.loads(to_json(a)) == to_dict(a)

    def test_unknown_schema_version_rejected(self):
        """from_dict on an unknown schema_version raises the version error (Req 6.3, 6.6)."""
        payload = to_dict(_sample_analysis())
        payload["schema_version"] = REPO_ANALYSIS_SCHEMA_VERSION + 99
        with pytest.raises(RepoAnalysisVersionError) as excinfo:
            from_dict(payload)
        assert str(REPO_ANALYSIS_SCHEMA_VERSION + 99) in str(excinfo.value)

    def test_missing_schema_version_rejected(self):
        """A payload without schema_version is rejected, not silently accepted (Req 6.3)."""
        payload = to_dict(_sample_analysis())
        del payload["schema_version"]
        with pytest.raises(RepoAnalysisVersionError):
            from_dict(payload)

    def test_to_dict_emits_json_primitives_only(self):
        """to_dict yields only JSON-compatible primitives; tuples become lists (Req 6.4)."""
        payload = to_dict(_sample_analysis(enriched=True))
        # Collections serialize to lists (not tuples) so json.dumps accepts them.
        assert isinstance(payload["languages"], list)
        assert isinstance(payload["primary_languages"], list)
        assert isinstance(payload["tests"]["frameworks"], list)
        # The whole payload round-trips through the stdlib json encoder unchanged.
        assert json.loads(json.dumps(payload, sort_keys=True)) == payload


# --------------------------------------------------------------------------- #
# Detector signals over crafted fixtures (Req 4.3-4.5, 5.1, 5.3, 5.6)          #
# --------------------------------------------------------------------------- #


class TestDetectorSignals:
    def test_nested_manifests_and_ci_detected(self, tmp_path):
        """Root + nested go.mod classified; GH Actions + Dagger CI detected (Req 4.3, 4.4)."""
        _build_polyglot_repo(tmp_path)
        inv = scan(str(tmp_path))

        build = {(b.path, b.kind) for b in detect_build_files(inv)}
        assert ("go.mod", "go_mod") in build
        assert (".dagger/go.mod", "go_mod") in build  # nested sub-project manifest
        assert ("pyproject.toml", "pyproject") in build

        ci = {(c.path, c.provider) for c in detect_ci(inv)}
        assert (".github/workflows/ci.yml", "github_actions") in ci
        assert (".github/workflows/release.yml", "github_actions") in ci
        assert ("dagger.json", "dagger") in ci

    def test_go_tests_detected(self, tmp_path):
        """`*_test.go` files mark tests present with the Go testing framework (Req 4.5)."""
        _build_polyglot_repo(tmp_path)
        inv = scan(str(tmp_path))

        layout = detect_tests(inv)
        assert layout.present is True
        assert "go_testing" in layout.frameworks
        assert any(p.endswith("hash_test.go") for p in layout.paths)

    def test_dependencies_extracted_with_source(self, tmp_path):
        """Declared deps come back with their source manifest + scope (Req 5.1)."""
        _build_polyglot_repo(tmp_path)
        inv = scan(str(tmp_path))

        deps = extract_dependencies(inv, str(tmp_path))
        by_name = {(d.name, d.source) for d in deps}
        assert ("github.com/spf13/cobra", "go.mod") in by_name
        assert any(
            d.name == "requests" and d.source == "pyproject.toml" for d in deps
        )
        # Sorted by (source, name) so two runs are equal (Req 9.1).
        assert list(deps) == sorted(
            deps, key=lambda d: (d.source, d.name, d.scope, d.version_spec)
        )

    def test_malformed_manifest_partial_parse_note(self, tmp_path):
        """A malformed pyproject.toml yields a partial-parse note, no abort (Req 5.6)."""
        # Valid go.mod (so something parses) + a broken TOML manifest.
        _text(
            tmp_path,
            "go.mod",
            "module x\n\ngo 1.22\n\nrequire (\n\tgithub.com/x/y v1.0.0\n)\n",
        )
        _text(
            tmp_path,
            "pyproject.toml",
            "[project\nname = oops this is not valid toml = =\n",
        )
        inv = scan(str(tmp_path))

        deps, notes = extract_dependencies_with_notes(inv, str(tmp_path))

        # The good manifest still contributed; the bad one only added a note.
        assert any(d.source == "go.mod" for d in deps)
        assert any("pyproject.toml" in n and "partial" in n.lower() for n in notes)

    def test_public_surface_is_conservative(self, tmp_path):
        """Cheap CLI flags + exported symbols only; no deep-parse noise (Req 5.3)."""
        _build_polyglot_repo(tmp_path)
        inv = scan(str(tmp_path))

        surface = detect_public_surface(inv, str(tmp_path))
        kinds = {s.kind for s in surface}
        names = {(s.name, s.kind, s.source) for s in surface}

        # Go capitalized top-level func/type are exported symbols; lowercase omitted.
        assert ("Run", "exported_symbol", "main.go") in names
        assert all(
            not (s.name == "helper" and s.source == "main.go") for s in surface
        )
        # Python argparse flags are captured as cli_flag.
        assert ("--verbose", "cli_flag", "tools/util.py") in names
        # Only the lightweight kinds appear (no invented categories).
        assert kinds <= {"cli_flag", "cli_subcommand", "exported_symbol"}
        # `*_test.go` symbols are never public surface (Req 5.3 conservative).
        assert all(not s.source.endswith("_test.go") for s in surface)
        # Sorted by (source, kind, name) for determinism (Req 9.1).
        assert list(surface) == sorted(
            surface, key=lambda s: (s.source, s.kind, s.name)
        )

    def test_detectors_byte_identical_across_two_runs(self, tmp_path):
        """Every detector over a fixed inventory is equal across two runs (Req 9.1, 9.2)."""
        _build_polyglot_repo(tmp_path)
        inv = scan(str(tmp_path))
        repo = str(tmp_path)

        assert detect_build_files(inv) == detect_build_files(inv)
        assert detect_ci(inv) == detect_ci(inv)
        assert detect_tests(inv) == detect_tests(inv)
        assert extract_dependencies(inv, repo) == extract_dependencies(inv, repo)
        assert detect_public_surface(inv, repo) == detect_public_surface(inv, repo)


# --------------------------------------------------------------------------- #
# End-to-end determinism: byte-identical across two runs (the 6.1 observable)   #
# --------------------------------------------------------------------------- #


class TestEndToEndDeterminism:
    def test_crafted_fixture_core_is_byte_identical_across_two_runs(self, tmp_path):
        """Scan -> aggregate -> detect, serialized to JSON, is byte-identical (Req 9.1, 9.2).

        This is the task's headline observable: the whole deterministic core run
        twice over the same crafted fixtures yields byte-identical serialized
        output, with no model or network involved.
        """
        _build_polyglot_repo(tmp_path)
        repo = str(tmp_path)

        def _core_payload() -> dict:
            inv = scan(repo)
            langs, primary = aggregate_languages(inv.entries)
            deps, dep_notes = extract_dependencies_with_notes(inv, repo)
            return {
                "inventory": [
                    {
                        "path": e.path,
                        "size": e.size,
                        "is_binary": e.is_binary,
                        "language": e.language,
                        "loc": e.loc,
                        "read_truncated": e.read_truncated,
                    }
                    for e in inv.entries
                ],
                "stats": {
                    "files_scanned": inv.stats.files_scanned,
                    "files_skipped": inv.stats.files_skipped,
                    "bytes_scanned": inv.stats.bytes_scanned,
                    "limit_reached": inv.stats.limit_reached,
                    "notes": list(inv.stats.notes),
                },
                "languages": [
                    {"language": s.language, "files": s.files, "loc": s.loc}
                    for s in langs
                ],
                "primary_languages": list(primary),
                "build_files": [
                    {"path": b.path, "kind": b.kind} for b in detect_build_files(inv)
                ],
                "ci_workflows": [
                    {"path": c.path, "provider": c.provider} for c in detect_ci(inv)
                ],
                "tests": {
                    "present": detect_tests(inv).present,
                    "frameworks": list(detect_tests(inv).frameworks),
                    "paths": list(detect_tests(inv).paths),
                },
                "dependencies": [
                    {
                        "name": d.name,
                        "version_spec": d.version_spec,
                        "source": d.source,
                        "scope": d.scope,
                    }
                    for d in deps
                ],
                "dep_notes": list(dep_notes),
                "public_surface": [
                    {"name": p.name, "kind": p.kind, "source": p.source}
                    for p in detect_public_surface(inv, repo)
                ],
            }

        first = json.dumps(_core_payload(), sort_keys=True)
        second = json.dumps(_core_payload(), sort_keys=True)
        assert first == second

    def test_serde_round_trip_on_crafted_core(self, tmp_path):
        """A RepoAnalysis assembled from a crafted scan survives a serde round-trip.

        Cross-cutting check that the model fields produced from real scanner +
        detector output (not just hand-built records) serialize and reconstruct
        equal (Req 6.5), wiring the scanner/languages/detectors boundary into the
        serde boundary.
        """
        _build_polyglot_repo(tmp_path)
        repo = str(tmp_path)
        inv = scan(repo)
        langs, primary = aggregate_languages(inv.entries)
        deps = extract_dependencies(inv, repo)

        analysis = RepoAnalysis(
            schema_version=REPO_ANALYSIS_SCHEMA_VERSION,
            repo_path=inv.repo_path,
            languages=langs,
            primary_languages=primary,
            total_loc=sum(s.loc for s in langs),
            total_files=len(inv.entries),
            structure=(),
            entrypoints=(),
            build_files=detect_build_files(inv),
            ci_workflows=detect_ci(inv),
            tests=detect_tests(inv),
            dependencies=deps,
            components=(),
            public_surface=detect_public_surface(inv, repo),
            docs=DocPresence(False, (), (), ()),
            artifacts=(),
            scan_stats=inv.stats,
            enrichment=None,
        )

        assert from_dict(to_dict(analysis)) == analysis
        assert to_json(analysis) == to_json(from_dict(to_dict(analysis)))

    @pytest.mark.skipif(
        not os.path.isdir(REFERENCE_REPO),
        reason="reference repo not present",
    )
    def test_reference_repo_scan_and_detect_are_deterministic(self):
        """Two scans + detector passes over the reference repo are equal (Req 9.2).

        A cross-cutting determinism check on a real polyglot project, staying
        inside the scanner/detector boundary of task 6.1 (the full
        reference-repo assertion set is task 6.3).
        """
        inv_a = scan(REFERENCE_REPO)
        inv_b = scan(REFERENCE_REPO)
        assert inv_a == inv_b

        # Detectors over the reference inventory are equal run-to-run.
        assert detect_build_files(inv_a) == detect_build_files(inv_b)
        assert detect_ci(inv_a) == detect_ci(inv_b)
        assert detect_tests(inv_a) == detect_tests(inv_b)
        assert extract_dependencies(inv_a, REFERENCE_REPO) == extract_dependencies(
            inv_b, REFERENCE_REPO
        )

        # And the reference repo exercises the nested-manifest + CI + test signals.
        build_paths = {b.path for b in detect_build_files(inv_a)}
        assert "go.mod" in build_paths
        assert ".dagger/go.mod" in build_paths
        ci_paths = {c.path for c in detect_ci(inv_a)}
        assert any(p.startswith(".github/workflows/") for p in ci_paths)
        assert detect_tests(inv_a).present is True
