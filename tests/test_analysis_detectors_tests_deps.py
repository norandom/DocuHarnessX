"""Unit tests for task 3.2 (test-layout + declared-dependency detectors).

Task 3.2's boundary is the ``docuharnessx.analysis.detectors`` module, extending
it with the two signals that turn a :class:`FileInventory` (plus, for
dependencies, the manifests on disk) into the frozen records the analyzer composes
into :class:`RepoAnalysis` (design "detectors — signal extraction"; Req 4.5, 4.6,
5.1, 5.6):

* ``detect_tests(inv) -> TestLayout`` — recognized test files/dirs/frameworks per
  language; ``present`` plus sorted ``frameworks`` and representative ``paths``
  (Req 4.5, 4.6).
* ``extract_dependencies(inv, repo_path) -> tuple[Dependency, ...]`` — declared
  dependencies parsed from recognized manifests (``pyproject.toml``, ``go.mod``,
  ``requirements*.txt``, ``package.json``) with their source manifest and scope,
  sorted by ``(source, name)``; a malformed/partial manifest yields what is
  parseable and never aborts (Req 5.1, 5.6).
* ``extract_dependencies_with_notes(inv, repo_path)`` — the same parse but also
  returning the sorted "partially parsed" notes the analyzer folds into
  ``ScanStats.notes`` (Req 5.6); the pinned ``extract_dependencies`` is the
  notes-dropping public seam over it.

Like the task-3.1 detector tests these are pure, deterministic, and self-contained:
``detect_tests`` runs against small hand-built inventories, while the dependency
parser is driven against manifests written into a ``tmp_path`` so no parsing
depends on the live filesystem layout. One reference-repo check confirms the real
Go CLI tree (``*_test.go`` present, ``go.mod`` requires parsed) behaves as pinned.
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
# Inventory-building helpers (mirror the task-3.1 detector tests)
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
    """Build an inventory of plain entries for files that exist under ``repo_path``."""
    entries = tuple(_entry(p) for p in rel_paths)
    return _inventory(*entries, repo_path=repo_path)


# --------------------------------------------------------------------------- #
# Module / symbol surface
# --------------------------------------------------------------------------- #


def test_task32_public_symbols_exist() -> None:
    mod = _detectors()
    for name in (
        "detect_tests",
        "extract_dependencies",
        "extract_dependencies_with_notes",
    ):
        assert hasattr(mod, name), name
        assert callable(getattr(mod, name))


def test_task32_in_module_all() -> None:
    mod = _detectors()
    for name in (
        "detect_tests",
        "extract_dependencies",
        "extract_dependencies_with_notes",
    ):
        assert name in mod.__all__


def test_task32_detectors_reexported_from_package() -> None:
    pkg = importlib.import_module(PACKAGE)
    for name in (
        "detect_tests",
        "extract_dependencies",
        "extract_dependencies_with_notes",
    ):
        assert hasattr(pkg, name), name
        assert name in pkg.__all__


# --------------------------------------------------------------------------- #
# detect_tests (Req 4.5, 4.6)
# --------------------------------------------------------------------------- #


def test_tests_empty_inventory_reports_absent() -> None:
    mod = _detectors()
    layout = mod.detect_tests(_inventory())
    assert layout.present is False
    assert layout.frameworks == ()
    assert layout.paths == ()


def test_tests_no_tests_reports_absent() -> None:
    mod = _detectors()
    inv = _inventory(
        _entry("main.go", language="Go", loc=20),
        _entry("internal/hash/hash.go", language="Go", loc=80),
        _entry("README.md", language="Markdown", loc=5),
    )
    layout = mod.detect_tests(inv)
    assert layout.present is False
    assert layout.frameworks == ()
    assert layout.paths == ()


def test_tests_detect_go_test_files() -> None:
    mod = _detectors()
    inv = _inventory(
        _entry("main.go", language="Go", loc=20),
        _entry("main_test.go", language="Go", loc=30),
        _entry("internal/hash/hash_test.go", language="Go", loc=40),
    )
    layout = mod.detect_tests(inv)
    assert layout.present is True
    assert "go_testing" in layout.frameworks
    assert "main_test.go" in layout.paths
    assert "internal/hash/hash_test.go" in layout.paths


def test_tests_detect_pytest_files() -> None:
    mod = _detectors()
    inv = _inventory(
        _entry("pkg/app.py", language="Python", loc=20),
        _entry("tests/test_app.py", language="Python", loc=30),
        _entry("pkg/widget_test.py", language="Python", loc=15),
    )
    layout = mod.detect_tests(inv)
    assert layout.present is True
    assert "pytest" in layout.frameworks
    assert "tests/test_app.py" in layout.paths
    assert "pkg/widget_test.py" in layout.paths


def test_tests_detect_js_ts_test_files() -> None:
    mod = _detectors()
    inv = _inventory(
        _entry("src/app.ts", language="TypeScript", loc=20),
        _entry("src/app.test.ts", language="TypeScript", loc=30),
        _entry("src/util.spec.js", language="JavaScript", loc=15),
    )
    layout = mod.detect_tests(inv)
    assert layout.present is True
    assert "jest" in layout.frameworks
    assert "src/app.test.ts" in layout.paths
    assert "src/util.spec.js" in layout.paths


def test_tests_detect_test_directory_without_naming_convention() -> None:
    mod = _detectors()
    # A conventional tests/ directory holds source-language files that do not match
    # a per-file naming convention; the directory itself signals test presence.
    inv = _inventory(
        _entry("tests/conftest.py", language="Python", loc=10),
        _entry("tests/helpers.py", language="Python", loc=20),
    )
    layout = mod.detect_tests(inv)
    assert layout.present is True
    assert "tests" in layout.paths


def test_tests_frameworks_sorted_and_unique() -> None:
    mod = _detectors()
    inv = _inventory(
        _entry("a_test.go", language="Go", loc=10),
        _entry("b_test.go", language="Go", loc=10),
        _entry("test_x.py", language="Python", loc=10),
    )
    layout = mod.detect_tests(inv)
    assert list(layout.frameworks) == sorted(set(layout.frameworks))
    assert "go_testing" in layout.frameworks
    assert "pytest" in layout.frameworks


def test_tests_paths_sorted() -> None:
    mod = _detectors()
    inv = _inventory(
        _entry("z_test.go", language="Go", loc=10),
        _entry("a_test.go", language="Go", loc=10),
        _entry("m_test.go", language="Go", loc=10),
    )
    layout = mod.detect_tests(inv)
    assert list(layout.paths) == sorted(layout.paths)


def test_tests_deterministic() -> None:
    mod = _detectors()
    inv = _inventory(
        _entry("main_test.go", language="Go", loc=10),
        _entry("tests/test_app.py", language="Python", loc=10),
    )
    assert mod.detect_tests(inv) == mod.detect_tests(inv)


def test_tests_no_false_positive_on_testdata_payload() -> None:
    mod = _detectors()
    # A non-test source file whose name merely contains "test" must not match.
    inv = _inventory(
        _entry("internal/contest.go", language="Go", loc=20),
        _entry("latest.py", language="Python", loc=20),
    )
    layout = mod.detect_tests(inv)
    assert layout.present is False


# --------------------------------------------------------------------------- #
# extract_dependencies — go.mod (Req 5.1, 5.6)
# --------------------------------------------------------------------------- #


def _write(tmp_path, rel: str, content: str) -> None:
    target = tmp_path / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def test_deps_empty_inventory_returns_empty_tuple(tmp_path) -> None:
    mod = _detectors()
    inv = _inventory(repo_path=str(tmp_path))
    assert mod.extract_dependencies(inv, str(tmp_path)) == ()


def test_deps_go_mod_require_block(tmp_path) -> None:
    mod = _detectors()
    _write(
        tmp_path,
        "go.mod",
        "module example.com/x\n\n"
        "go 1.23\n\n"
        "require (\n"
        "\tgithub.com/spf13/cobra v1.10.1\n"
        "\tgithub.com/stretchr/testify v1.9.0\n"
        "\tgithub.com/davecgh/go-spew v1.1.1 // indirect\n"
        ")\n",
    )
    inv = _inventory_from_paths(str(tmp_path), "go.mod")
    deps = mod.extract_dependencies(inv, str(tmp_path))
    by_name = {d.name: d for d in deps}
    assert "github.com/spf13/cobra" in by_name
    assert by_name["github.com/spf13/cobra"].version_spec == "v1.10.1"
    assert by_name["github.com/spf13/cobra"].source == "go.mod"
    assert by_name["github.com/spf13/cobra"].scope == "runtime"


def test_deps_go_mod_single_line_require(tmp_path) -> None:
    mod = _detectors()
    _write(
        tmp_path,
        "go.mod",
        "module example.com/x\n\n"
        "go 1.23\n\n"
        "require github.com/spf13/cobra v1.10.1\n",
    )
    inv = _inventory_from_paths(str(tmp_path), "go.mod")
    deps = mod.extract_dependencies(inv, str(tmp_path))
    names = {d.name for d in deps}
    assert "github.com/spf13/cobra" in names


def test_deps_go_mod_nested_subproject(tmp_path) -> None:
    mod = _detectors()
    _write(
        tmp_path,
        "go.mod",
        "module example.com/x\n\nrequire github.com/spf13/cobra v1.10.1\n",
    )
    _write(
        tmp_path,
        ".dagger/go.mod",
        "module dagger/x\n\nrequire dagger.io/dagger v0.20.6\n",
    )
    inv = _inventory_from_paths(str(tmp_path), "go.mod", ".dagger/go.mod")
    deps = mod.extract_dependencies(inv, str(tmp_path))
    sources = {(d.source, d.name) for d in deps}
    assert ("go.mod", "github.com/spf13/cobra") in sources
    assert (".dagger/go.mod", "dagger.io/dagger") in sources


# --------------------------------------------------------------------------- #
# extract_dependencies — pyproject.toml (Req 5.1, 5.6)
# --------------------------------------------------------------------------- #


def test_deps_pyproject_runtime_and_optional(tmp_path) -> None:
    mod = _detectors()
    _write(
        tmp_path,
        "pyproject.toml",
        "[project]\n"
        'name = "x"\n'
        'dependencies = ["requests>=2.0", "click==8.1.0"]\n\n'
        "[project.optional-dependencies]\n"
        'dev = ["pytest>=7.0", "ruff"]\n',
    )
    inv = _inventory_from_paths(str(tmp_path), "pyproject.toml")
    deps = mod.extract_dependencies(inv, str(tmp_path))
    by_name = {d.name: d for d in deps}
    assert by_name["requests"].version_spec == ">=2.0"
    assert by_name["requests"].scope == "runtime"
    assert by_name["click"].version_spec == "==8.1.0"
    assert by_name["pytest"].scope == "dev"
    assert by_name["ruff"].version_spec == ""
    assert by_name["ruff"].scope == "dev"
    for d in deps:
        assert d.source == "pyproject.toml"


def test_deps_pyproject_poetry_table(tmp_path) -> None:
    mod = _detectors()
    _write(
        tmp_path,
        "pyproject.toml",
        "[tool.poetry.dependencies]\n"
        'python = "^3.12"\n'
        'requests = "^2.31"\n\n'
        "[tool.poetry.group.dev.dependencies]\n"
        'pytest = "^7.0"\n',
    )
    inv = _inventory_from_paths(str(tmp_path), "pyproject.toml")
    deps = mod.extract_dependencies(inv, str(tmp_path))
    by_name = {d.name: d for d in deps}
    # The "python" pseudo-dependency is not a real package dependency.
    assert "python" not in by_name
    assert by_name["requests"].scope == "runtime"
    assert by_name["requests"].version_spec == "^2.31"
    assert by_name["pytest"].scope == "dev"


# --------------------------------------------------------------------------- #
# extract_dependencies — requirements*.txt (Req 5.1)
# --------------------------------------------------------------------------- #


def test_deps_requirements_txt(tmp_path) -> None:
    mod = _detectors()
    _write(
        tmp_path,
        "requirements.txt",
        "# a comment\n"
        "requests>=2.0\n"
        "click==8.1.0\n"
        "\n"
        "-r other.txt\n"
        "flask\n",
    )
    inv = _inventory_from_paths(str(tmp_path), "requirements.txt")
    deps = mod.extract_dependencies(inv, str(tmp_path))
    by_name = {d.name: d for d in deps}
    assert by_name["requests"].version_spec == ">=2.0"
    assert by_name["click"].version_spec == "==8.1.0"
    assert by_name["flask"].version_spec == ""
    # The -r include line is not a dependency.
    assert "-r other.txt" not in by_name
    assert all(d.source == "requirements.txt" for d in deps)


def test_deps_requirements_dev_scope(tmp_path) -> None:
    mod = _detectors()
    _write(tmp_path, "requirements-dev.txt", "pytest>=7.0\n")
    inv = _inventory_from_paths(str(tmp_path), "requirements-dev.txt")
    deps = mod.extract_dependencies(inv, str(tmp_path))
    assert len(deps) == 1
    assert deps[0].name == "pytest"
    assert deps[0].scope == "dev"


# --------------------------------------------------------------------------- #
# extract_dependencies — package.json (Req 5.1)
# --------------------------------------------------------------------------- #


def test_deps_package_json_runtime_and_dev(tmp_path) -> None:
    mod = _detectors()
    _write(
        tmp_path,
        "package.json",
        '{\n'
        '  "name": "x",\n'
        '  "dependencies": {"react": "^18.0.0", "lodash": "4.17.21"},\n'
        '  "devDependencies": {"jest": "^29.0.0"}\n'
        '}\n',
    )
    inv = _inventory_from_paths(str(tmp_path), "package.json")
    deps = mod.extract_dependencies(inv, str(tmp_path))
    by_name = {d.name: d for d in deps}
    assert by_name["react"].version_spec == "^18.0.0"
    assert by_name["react"].scope == "runtime"
    assert by_name["lodash"].version_spec == "4.17.21"
    assert by_name["jest"].scope == "dev"
    assert all(d.source == "package.json" for d in deps)


# --------------------------------------------------------------------------- #
# Sorting + determinism (Req 5.1, 9.1)
# --------------------------------------------------------------------------- #


def test_deps_sorted_by_source_then_name(tmp_path) -> None:
    mod = _detectors()
    _write(
        tmp_path,
        "go.mod",
        "module x\n\nrequire (\n\tz/pkg v1\n\ta/pkg v1\n)\n",
    )
    _write(
        tmp_path,
        "sub/go.mod",
        "module y\n\nrequire b/pkg v1\n",
    )
    inv = _inventory_from_paths(str(tmp_path), "go.mod", "sub/go.mod")
    deps = mod.extract_dependencies(inv, str(tmp_path))
    keys = [(d.source, d.name) for d in deps]
    assert keys == sorted(keys)


def test_deps_deterministic(tmp_path) -> None:
    mod = _detectors()
    _write(
        tmp_path,
        "pyproject.toml",
        '[project]\ndependencies = ["b", "a", "c"]\n',
    )
    inv = _inventory_from_paths(str(tmp_path), "pyproject.toml")
    assert mod.extract_dependencies(inv, str(tmp_path)) == mod.extract_dependencies(
        inv, str(tmp_path)
    )


# --------------------------------------------------------------------------- #
# Malformed / partial parse (Req 5.6)
# --------------------------------------------------------------------------- #


def test_deps_malformed_pyproject_partial_parse_note(tmp_path) -> None:
    mod = _detectors()
    # Valid project deps, then a syntactically broken table — tomllib raises, so the
    # whole file is unparseable; record a partial-parse note and continue.
    _write(
        tmp_path,
        "pyproject.toml",
        "[project]\n"
        'dependencies = ["requests>=2.0"\n'  # missing closing bracket -> TOML error
        "this is not valid toml = = =\n",
    )
    inv = _inventory_from_paths(str(tmp_path), "pyproject.toml")
    deps, notes = mod.extract_dependencies_with_notes(inv, str(tmp_path))
    assert any("partially parsed" in n for n in notes)
    assert any("pyproject.toml" in n for n in notes)
    # The public seam still returns (possibly empty) deps and never raises.
    assert mod.extract_dependencies(inv, str(tmp_path)) == deps


def test_deps_malformed_package_json_partial_parse_note(tmp_path) -> None:
    mod = _detectors()
    _write(tmp_path, "package.json", '{"dependencies": {"react": "^18.0.0"')  # truncated
    inv = _inventory_from_paths(str(tmp_path), "package.json")
    deps, notes = mod.extract_dependencies_with_notes(inv, str(tmp_path))
    assert any("partially parsed" in n for n in notes)
    assert any("package.json" in n for n in notes)


def test_deps_missing_manifest_file_is_skipped_with_note(tmp_path) -> None:
    mod = _detectors()
    # The inventory references a manifest that is not actually on disk (e.g. removed
    # between scan and parse); parsing must not raise.
    inv = _inventory_from_paths(str(tmp_path), "go.mod")
    deps, notes = mod.extract_dependencies_with_notes(inv, str(tmp_path))
    assert deps == ()
    assert any("partially parsed" in n or "could not read" in n for n in notes)


def test_deps_notes_are_sorted(tmp_path) -> None:
    mod = _detectors()
    _write(tmp_path, "package.json", "{ broken")
    _write(tmp_path, "pyproject.toml", "[project\nbad")
    inv = _inventory_from_paths(str(tmp_path), "package.json", "pyproject.toml")
    _deps, notes = mod.extract_dependencies_with_notes(inv, str(tmp_path))
    assert list(notes) == sorted(notes)


def test_deps_well_formed_manifest_has_no_notes(tmp_path) -> None:
    mod = _detectors()
    _write(tmp_path, "go.mod", "module x\n\nrequire a/b v1\n")
    inv = _inventory_from_paths(str(tmp_path), "go.mod")
    _deps, notes = mod.extract_dependencies_with_notes(inv, str(tmp_path))
    assert notes == ()


# --------------------------------------------------------------------------- #
# Reference-repo validation (Req 4.5, 5.1) — real Go CLI tree
# --------------------------------------------------------------------------- #


@pytest.mark.skipif(
    not os.path.isdir(REFERENCE_REPO),
    reason="reference repo not present on this machine",
)
def test_reference_repo_tests_and_deps() -> None:
    from docuharnessx.analysis.scanner import scan

    inv = scan(REFERENCE_REPO)
    mod = _detectors()

    # *_test.go files are reported as present (Req 4.5).
    layout = mod.detect_tests(inv)
    assert layout.present is True
    assert "go_testing" in layout.frameworks
    assert any(p.endswith("_test.go") for p in layout.paths)

    # go.mod requires are parsed, from both root and nested .dagger/go.mod (Req 5.1).
    deps = mod.extract_dependencies(inv, REFERENCE_REPO)
    by_source = {}
    for d in deps:
        by_source.setdefault(d.source, set()).add(d.name)
    assert "github.com/spf13/cobra" in by_source.get("go.mod", set())
    assert "dagger.io/dagger" in by_source.get(".dagger/go.mod", set())
    # Sorted by (source, name) and deterministic.
    keys = [(d.source, d.name) for d in deps]
    assert keys == sorted(keys)
    assert mod.extract_dependencies(inv, REFERENCE_REPO) == deps


@pytest.mark.skipif(
    not os.path.isdir(REFERENCE_REPO),
    reason="reference repo not present on this machine",
)
def test_reference_repo_tests_deps_deterministic() -> None:
    from docuharnessx.analysis.scanner import scan

    inv = scan(REFERENCE_REPO)
    mod = _detectors()
    assert mod.detect_tests(inv) == mod.detect_tests(inv)
    assert mod.extract_dependencies(inv, REFERENCE_REPO) == mod.extract_dependencies(
        inv, REFERENCE_REPO
    )
