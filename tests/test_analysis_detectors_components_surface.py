"""Unit tests for task 3.3 (component map + public surface + docs + artifacts).

Task 3.3's boundary is the ``docuharnessx.analysis.detectors`` module, extending
it additively with the four signals that turn a :class:`FileInventory` (plus, for
public surface, the files on disk) into the frozen records the analyzer composes
into :class:`RepoAnalysis` (design "detectors — signal extraction"; Req 5.2, 5.3,
5.4, 5.5, 4.6):

* ``map_components(inv) -> tuple[Component, ...]`` — a component/module map derived
  from the directory/package structure, each unit with its repo-relative path and a
  small sorted set of representative files, sorted by path (Req 5.2).
* ``detect_public_surface(inv, repo_path) -> tuple[PublicSymbol, ...]`` —
  cheaply-detectable public surface (CLI flags/subcommands, exported symbols) via
  shallow signals only, omitting anything needing deep semantic analysis, sorted by
  ``(source, kind, name)`` (Req 5.3).
* ``detect_docs(inv) -> DocPresence`` — README presence, ``docs/`` directories, and
  other recognized documentation files (Req 5.4).
* ``detect_artifacts(inv) -> tuple[Artifact, ...]`` — notable artifacts (license,
  dockerfile, schema/spec, generated markers) by filename/pattern, sorted by path
  (Req 5.5).

Each category is recorded as empty (empty tuple / falsey ``DocPresence``) rather
than omitted when there are no matches, keeping the model shape stable (Req 4.6).

Like the earlier detector tests these are pure, deterministic, and self-contained:
the structure/docs/artifact detectors run against small hand-built inventories,
while the public-surface parser is driven against files written into a ``tmp_path``
so no parse depends on the live filesystem layout. One reference-repo check
confirms the real Go CLI tree behaves as pinned.
"""

from __future__ import annotations

import importlib
import os

import pytest

from docuharnessx.analysis.model import ScanStats
from docuharnessx.analysis.scanner import FileEntry, FileInventory

DETECTORS_MODULE = "docuharnessx.analysis.detectors"
PACKAGE = "docuharnessx.analysis"

REFERENCE_REPO = "/home/mc/Source/malware_hashes"


# --------------------------------------------------------------------------- #
# Inventory-building helpers (mirror the earlier detector tests)
# --------------------------------------------------------------------------- #


def _detectors():
    return importlib.import_module(DETECTORS_MODULE)


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


def _inventory(*entries: FileEntry, repo_path: str = "/repo") -> FileInventory:
    stats = ScanStats(
        files_scanned=len(entries),
        files_skipped=0,
        bytes_scanned=sum(e.size for e in entries),
        limit_reached=False,
        notes=(),
    )
    sorted_entries = tuple(sorted(entries, key=lambda e: e.path))
    return FileInventory(repo_path=repo_path, entries=sorted_entries, stats=stats)


def _inventory_from_paths(repo_path: str, *rel_paths: str) -> FileInventory:
    entries = tuple(_entry(p) for p in rel_paths)
    return _inventory(*entries, repo_path=repo_path)


def _write(tmp_path, rel: str, content: str) -> None:
    target = tmp_path / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


# --------------------------------------------------------------------------- #
# Module / symbol surface
# --------------------------------------------------------------------------- #


def test_task33_public_symbols_exist() -> None:
    mod = _detectors()
    for name in (
        "map_components",
        "detect_public_surface",
        "detect_docs",
        "detect_artifacts",
    ):
        assert hasattr(mod, name), name
        assert callable(getattr(mod, name))


def test_task33_in_module_all() -> None:
    mod = _detectors()
    for name in (
        "map_components",
        "detect_public_surface",
        "detect_docs",
        "detect_artifacts",
    ):
        assert name in mod.__all__


def test_task33_detectors_reexported_from_package() -> None:
    pkg = importlib.import_module(PACKAGE)
    for name in (
        "map_components",
        "detect_public_surface",
        "detect_docs",
        "detect_artifacts",
    ):
        assert hasattr(pkg, name), name
        assert name in pkg.__all__


# --------------------------------------------------------------------------- #
# map_components (Req 5.2)
# --------------------------------------------------------------------------- #


def test_components_empty_inventory_returns_empty_tuple() -> None:
    mod = _detectors()
    assert mod.map_components(_inventory()) == ()


def test_components_for_main_package() -> None:
    mod = _detectors()
    inv = _inventory(
        _entry("main.go", language="Go", loc=50),
        _entry("internal/hash/hash.go", language="Go", loc=80),
        _entry("internal/hash/hash_test.go", language="Go", loc=40),
        _entry("internal/report/report.go", language="Go", loc=60),
    )
    comps = mod.map_components(inv)
    by_path = {c.path: c for c in comps}
    # The leaf packages are components.
    assert "internal/hash" in by_path
    assert "internal/report" in by_path
    # The repo root (where main.go lives) is a component too.
    assert "" in by_path


def test_components_carry_name_and_representative_files() -> None:
    mod = _detectors()
    inv = _inventory(
        _entry("internal/hash/hash.go", language="Go", loc=80),
        _entry("internal/hash/util.go", language="Go", loc=20),
    )
    by_path = {c.path: c for c in mod.map_components(inv)}
    comp = by_path["internal/hash"]
    # Name is the package directory basename.
    assert comp.name == "hash"
    # Representative files are repo-relative and a subset of this component's files.
    assert all(f.startswith("internal/hash/") for f in comp.representative_files)
    assert len(comp.representative_files) >= 1


def test_components_representative_files_sorted_and_bounded() -> None:
    mod = _detectors()
    # A directory with many files: the representative set must be sorted and small.
    files = [
        _entry(f"pkg/f{i:02d}.go", language="Go", loc=10) for i in range(20)
    ]
    inv = _inventory(*files)
    by_path = {c.path: c for c in mod.map_components(inv)}
    rep = by_path["pkg"].representative_files
    assert list(rep) == sorted(rep)
    # Conservative, bounded representative set (design "small set").
    assert len(rep) <= 10


def test_components_root_name_is_stable() -> None:
    mod = _detectors()
    inv = _inventory(_entry("main.go", language="Go", loc=10))
    by_path = {c.path: c for c in mod.map_components(inv)}
    assert "" in by_path
    # The root component carries a non-empty name (not the empty path).
    assert by_path[""].name != ""


def test_components_excludes_pure_noise_dirs() -> None:
    mod = _detectors()
    # A directory of only docs/markdown is not a code component; conservative
    # component mapping is over code-bearing package directories.
    inv = _inventory(
        _entry("internal/hash/hash.go", language="Go", loc=80),
        _entry("docs/guide.md", language="Markdown", loc=200),
        _entry("docs/intro.md", language="Markdown", loc=100),
    )
    paths = {c.path for c in mod.map_components(inv)}
    assert "internal/hash" in paths
    assert "docs" not in paths


def test_components_sorted_by_path() -> None:
    mod = _detectors()
    inv = _inventory(
        _entry("zeta/a.go", language="Go", loc=10),
        _entry("alpha/b.go", language="Go", loc=10),
        _entry("mid/c.go", language="Go", loc=10),
    )
    paths = [c.path for c in mod.map_components(inv)]
    assert paths == sorted(paths)


def test_components_deterministic() -> None:
    mod = _detectors()
    inv = _inventory(
        _entry("internal/hash/hash.go", language="Go", loc=80),
        _entry("internal/report/report.go", language="Go", loc=60),
        _entry("main.go", language="Go", loc=50),
    )
    assert mod.map_components(inv) == mod.map_components(inv)


# --------------------------------------------------------------------------- #
# detect_public_surface (Req 5.3)
# --------------------------------------------------------------------------- #


def test_public_surface_empty_inventory_returns_empty_tuple(tmp_path) -> None:
    mod = _detectors()
    inv = _inventory(repo_path=str(tmp_path))
    assert mod.detect_public_surface(inv, str(tmp_path)) == ()


def test_public_surface_python_argparse_flags_and_subcommands(tmp_path) -> None:
    mod = _detectors()
    _write(
        tmp_path,
        "cli.py",
        "import argparse\n"
        "def build():\n"
        "    p = argparse.ArgumentParser()\n"
        "    sub = p.add_subparsers()\n"
        "    run = sub.add_parser('run')\n"
        "    run.add_argument('--verbose')\n"
        "    p.add_argument('--config')\n"
        "    return p\n",
    )
    inv = _inventory_from_paths(str(tmp_path), "cli.py")
    surface = mod.detect_public_surface(inv, str(tmp_path))
    flags = {s.name for s in surface if s.kind == "cli_flag"}
    subs = {s.name for s in surface if s.kind == "cli_subcommand"}
    assert "--verbose" in flags
    assert "--config" in flags
    assert "run" in subs
    assert all(s.source == "cli.py" for s in surface)


def test_public_surface_python_dunder_all_exported_symbols(tmp_path) -> None:
    mod = _detectors()
    _write(
        tmp_path,
        "pkg/__init__.py",
        '__all__ = ["public_fn", "PublicClass"]\n'
        "def public_fn():\n    pass\n",
    )
    inv = _inventory_from_paths(str(tmp_path), "pkg/__init__.py")
    surface = mod.detect_public_surface(inv, str(tmp_path))
    exported = {s.name for s in surface if s.kind == "exported_symbol"}
    assert "public_fn" in exported
    assert "PublicClass" in exported


def test_public_surface_go_exported_symbols(tmp_path) -> None:
    mod = _detectors()
    _write(
        tmp_path,
        "internal/hash/hash.go",
        "package hash\n\n"
        "type CryptoHashes struct {\n}\n\n"
        "func Compute(data []byte) CryptoHashes {\n"
        "    return CryptoHashes{}\n"
        "}\n\n"
        "func unexported() {}\n",
    )
    inv = _inventory_from_paths(str(tmp_path), "internal/hash/hash.go")
    surface = mod.detect_public_surface(inv, str(tmp_path))
    exported = {s.name for s in surface if s.kind == "exported_symbol"}
    assert "Compute" in exported
    assert "CryptoHashes" in exported
    # Unexported (lowercase) symbols are omitted.
    assert "unexported" not in exported


def test_public_surface_go_cobra_flags(tmp_path) -> None:
    mod = _detectors()
    _write(
        tmp_path,
        "main.go",
        "package main\n\n"
        "func run() {\n"
        '    rootCmd.PersistentFlags().BoolVar(&jsonOutput, "json", false, "JSON")\n'
        "}\n",
    )
    inv = _inventory_from_paths(str(tmp_path), "main.go")
    surface = mod.detect_public_surface(inv, str(tmp_path))
    flags = {s.name for s in surface if s.kind == "cli_flag"}
    assert "json" in flags or "--json" in flags


def test_public_surface_omits_go_test_symbols(tmp_path) -> None:
    mod = _detectors()
    # *_test.go files declare exported Test/Benchmark funcs, which are NOT real
    # public surface; the detector must skip test files entirely (Req 5.3 spirit).
    _write(
        tmp_path,
        "hash_test.go",
        "package hash\n\n"
        "func TestCompute(t *testing.T) {}\n"
        "func BenchmarkCompute(b *testing.B) {}\n",
    )
    inv = _inventory_from_paths(str(tmp_path), "hash_test.go")
    surface = mod.detect_public_surface(inv, str(tmp_path))
    names = {s.name for s in surface}
    assert "TestCompute" not in names
    assert "BenchmarkCompute" not in names


def test_public_surface_conservative_no_false_positive(tmp_path) -> None:
    mod = _detectors()
    # An ordinary text/markdown file yields no public surface (no deep parse, no
    # guessing) — detection is conservative and omits on doubt (Req 5.3).
    _write(tmp_path, "README.md", "# Title\n\nSome prose with func words.\n")
    inv = _inventory_from_paths(str(tmp_path), "README.md")
    assert mod.detect_public_surface(inv, str(tmp_path)) == ()


def test_public_surface_sorted_by_source_kind_name(tmp_path) -> None:
    mod = _detectors()
    _write(
        tmp_path,
        "a.go",
        "package a\n\nfunc Zeta() {}\nfunc Alpha() {}\n",
    )
    _write(
        tmp_path,
        "cli.py",
        "import argparse\n"
        "p = argparse.ArgumentParser()\n"
        "p.add_argument('--zoom')\n"
        "p.add_argument('--apex')\n",
    )
    inv = _inventory_from_paths(str(tmp_path), "a.go", "cli.py")
    surface = mod.detect_public_surface(inv, str(tmp_path))
    keys = [(s.source, s.kind, s.name) for s in surface]
    assert keys == sorted(keys)


def test_public_surface_deterministic(tmp_path) -> None:
    mod = _detectors()
    _write(tmp_path, "x.go", "package x\n\nfunc Foo() {}\ntype Bar struct{}\n")
    inv = _inventory_from_paths(str(tmp_path), "x.go")
    assert mod.detect_public_surface(inv, str(tmp_path)) == mod.detect_public_surface(
        inv, str(tmp_path)
    )


def test_public_surface_missing_file_skipped(tmp_path) -> None:
    mod = _detectors()
    # Inventory references a file removed between scan and parse; must not raise.
    inv = _inventory_from_paths(str(tmp_path), "gone.go")
    assert mod.detect_public_surface(inv, str(tmp_path)) == ()


def test_public_surface_binary_file_skipped(tmp_path) -> None:
    mod = _detectors()
    # A binary entry is never parsed for public surface.
    binary_entry = _entry("blob.go", language="Go", is_binary=True, loc=0)
    inv = _inventory(binary_entry, repo_path=str(tmp_path))
    assert mod.detect_public_surface(inv, str(tmp_path)) == ()


# --------------------------------------------------------------------------- #
# detect_docs (Req 5.4)
# --------------------------------------------------------------------------- #


def test_docs_empty_inventory_reports_absent() -> None:
    mod = _detectors()
    docs = mod.detect_docs(_inventory())
    assert docs.has_readme is False
    assert docs.readme_paths == ()
    assert docs.doc_dirs == ()
    assert docs.other_docs == ()


def test_docs_detect_root_readme() -> None:
    mod = _detectors()
    inv = _inventory(
        _entry("README.md", language="Markdown", loc=20),
        _entry("main.go", language="Go", loc=20),
    )
    docs = mod.detect_docs(inv)
    assert docs.has_readme is True
    assert "README.md" in docs.readme_paths


def test_docs_detect_readme_variants() -> None:
    mod = _detectors()
    inv = _inventory(
        _entry("README.rst", language="reStructuredText", loc=10),
        _entry("docs/README", language="Other", loc=10),
    )
    docs = mod.detect_docs(inv)
    assert docs.has_readme is True
    assert "README.rst" in docs.readme_paths
    assert "docs/README" in docs.readme_paths


def test_docs_detect_doc_directories() -> None:
    mod = _detectors()
    inv = _inventory(
        _entry("docs/guide.md", language="Markdown", loc=10),
        _entry("docs/api/ref.md", language="Markdown", loc=10),
    )
    docs = mod.detect_docs(inv)
    assert "docs" in docs.doc_dirs


def test_docs_other_docs_files() -> None:
    mod = _detectors()
    inv = _inventory(
        _entry("CONTRIBUTING.md", language="Markdown", loc=10),
        _entry("CHANGELOG.md", language="Markdown", loc=10),
        _entry("main.go", language="Go", loc=10),
    )
    docs = mod.detect_docs(inv)
    assert "CONTRIBUTING.md" in docs.other_docs
    assert "CHANGELOG.md" in docs.other_docs
    # A README is reported under readme_paths, not other_docs.
    assert "main.go" not in docs.other_docs


def test_docs_collections_sorted() -> None:
    mod = _detectors()
    inv = _inventory(
        _entry("z/docs/a.md", language="Markdown", loc=1),
        _entry("a/docs/b.md", language="Markdown", loc=1),
        _entry("README.md", language="Markdown", loc=1),
        _entry("CHANGELOG.md", language="Markdown", loc=1),
    )
    docs = mod.detect_docs(inv)
    assert list(docs.readme_paths) == sorted(docs.readme_paths)
    assert list(docs.doc_dirs) == sorted(docs.doc_dirs)
    assert list(docs.other_docs) == sorted(docs.other_docs)


def test_docs_no_readme_but_doc_dir() -> None:
    mod = _detectors()
    inv = _inventory(_entry("docs/guide.md", language="Markdown", loc=10))
    docs = mod.detect_docs(inv)
    assert docs.has_readme is False
    assert "docs" in docs.doc_dirs


def test_docs_deterministic() -> None:
    mod = _detectors()
    inv = _inventory(
        _entry("README.md", language="Markdown", loc=10),
        _entry("docs/guide.md", language="Markdown", loc=10),
    )
    assert mod.detect_docs(inv) == mod.detect_docs(inv)


# --------------------------------------------------------------------------- #
# detect_artifacts (Req 5.5)
# --------------------------------------------------------------------------- #


def test_artifacts_empty_inventory_returns_empty_tuple() -> None:
    mod = _detectors()
    assert mod.detect_artifacts(_inventory()) == ()


def test_artifacts_detect_license() -> None:
    mod = _detectors()
    inv = _inventory(
        _entry("LICENSE", language="Other", loc=20),
        _entry("main.go", language="Go", loc=20),
    )
    arts = {a.path: a.kind for a in mod.detect_artifacts(inv)}
    assert arts.get("LICENSE") == "license"


def test_artifacts_detect_license_variants() -> None:
    mod = _detectors()
    inv = _inventory(
        _entry("LICENSE.md", language="Markdown", loc=20),
        _entry("COPYING", language="Other", loc=20),
    )
    arts = {a.path: a.kind for a in mod.detect_artifacts(inv)}
    assert arts.get("LICENSE.md") == "license"
    assert arts.get("COPYING") == "license"


def test_artifacts_detect_dockerfile() -> None:
    mod = _detectors()
    inv = _inventory(_entry("Dockerfile", language="Dockerfile", loc=20))
    arts = {a.path: a.kind for a in mod.detect_artifacts(inv)}
    assert arts.get("Dockerfile") == "dockerfile"


def test_artifacts_detect_schema_files() -> None:
    mod = _detectors()
    inv = _inventory(
        _entry("api/openapi.yaml", language="YAML", loc=20),
        _entry("schema.json", language="JSON", loc=20),
        _entry("types.proto", language="Protobuf", loc=20),
    )
    arts = {a.path: a.kind for a in mod.detect_artifacts(inv)}
    assert arts.get("api/openapi.yaml") == "schema"
    assert arts.get("schema.json") == "schema"
    assert arts.get("types.proto") == "schema"


def test_artifacts_detect_generated_markers() -> None:
    mod = _detectors()
    inv = _inventory(
        _entry("api/service.pb.go", language="Go", loc=200),
        _entry("api/types_generated.go", language="Go", loc=100),
    )
    arts = {a.path: a.kind for a in mod.detect_artifacts(inv)}
    assert arts.get("api/service.pb.go") == "generated"
    assert arts.get("api/types_generated.go") == "generated"


def test_artifacts_ignore_plain_source() -> None:
    mod = _detectors()
    inv = _inventory(
        _entry("main.go", language="Go", loc=20),
        _entry("internal/hash/hash.go", language="Go", loc=80),
    )
    assert mod.detect_artifacts(inv) == ()


def test_artifacts_sorted_by_path() -> None:
    mod = _detectors()
    inv = _inventory(
        _entry("z/LICENSE", language="Other", loc=1),
        _entry("a/Dockerfile", language="Dockerfile", loc=1),
        _entry("LICENSE", language="Other", loc=1),
    )
    paths = [a.path for a in mod.detect_artifacts(inv)]
    assert paths == sorted(paths)


def test_artifacts_deterministic() -> None:
    mod = _detectors()
    inv = _inventory(
        _entry("LICENSE", language="Other", loc=1),
        _entry("Dockerfile", language="Dockerfile", loc=1),
        _entry("schema.json", language="JSON", loc=1),
    )
    assert mod.detect_artifacts(inv) == mod.detect_artifacts(inv)


# --------------------------------------------------------------------------- #
# Reference-repo validation (Req 5.2, 5.3, 5.4, 5.5) — real Go CLI tree
# --------------------------------------------------------------------------- #


@pytest.mark.skipif(
    not os.path.isdir(REFERENCE_REPO),
    reason="reference repo not present on this machine",
)
def test_reference_repo_components_surface_docs_artifacts() -> None:
    from docuharnessx.analysis.scanner import scan

    inv = scan(REFERENCE_REPO)
    mod = _detectors()

    # Components: a component exists for the main package (repo root holds main.go)
    # and for the internal sub-packages (Req 5.2).
    comps = {c.path for c in mod.map_components(inv)}
    assert "" in comps  # main package at the repo root
    assert "internal/hash" in comps

    # Docs: the README is detected (Req 5.4).
    docs = mod.detect_docs(inv)
    assert docs.has_readme is True
    assert any(p == "README.md" for p in docs.readme_paths)

    # Public surface: conservative exported Go symbols + the cobra --json flag,
    # with no deep-parse signals (Req 5.3).
    surface = mod.detect_public_surface(inv, REFERENCE_REPO)
    exported = {s.name for s in surface if s.kind == "exported_symbol"}
    assert "Compute" in exported  # internal/hash exported func
    # No Test* exported symbols leak in from *_test.go files.
    assert not any(s.name.startswith("Test") for s in surface)
    # Sorted by (source, kind, name).
    keys = [(s.source, s.kind, s.name) for s in surface]
    assert keys == sorted(keys)


@pytest.mark.skipif(
    not os.path.isdir(REFERENCE_REPO),
    reason="reference repo not present on this machine",
)
def test_reference_repo_components_surface_deterministic() -> None:
    from docuharnessx.analysis.scanner import scan

    inv = scan(REFERENCE_REPO)
    mod = _detectors()
    assert mod.map_components(inv) == mod.map_components(inv)
    assert mod.detect_public_surface(inv, REFERENCE_REPO) == mod.detect_public_surface(
        inv, REFERENCE_REPO
    )
    assert mod.detect_docs(inv) == mod.detect_docs(inv)
    assert mod.detect_artifacts(inv) == mod.detect_artifacts(inv)
