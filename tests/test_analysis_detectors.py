"""Unit tests for task 3.1 (structure / entrypoints / build-config / CI detectors).

Task 3.1's boundary is the ``docuharnessx.analysis.detectors`` module, and within
it the four signal detectors that operate over a :class:`FileInventory` (design
"detectors — signal extraction"; Req 4.1, 4.2, 4.3, 4.4, 4.6):

* ``summarize_structure(inv) -> tuple[DirectorySummary, ...]`` — a top-level (and
  per-directory) summary: file count, dominant language, and heuristic role,
  sorted by path ascending (Req 4.1).
* ``detect_entrypoints(inv) -> tuple[Entrypoint, ...]`` — language-appropriate
  entrypoints (``main.go``, ``__main__.py``, ``cli.py``, ``bin/`` scripts, …),
  sorted by (path, kind) (Req 4.2).
* ``detect_build_files(inv) -> tuple[BuildFile, ...]`` — build/config manifests
  including those nested in sub-projects, sorted by path (Req 4.3).
* ``detect_ci(inv) -> tuple[CIWorkflow, ...]`` — CI/workflow configuration with
  provider + path, sorted by path (Req 4.4).

Each category is recorded as an empty tuple rather than omitted when there are no
matches, keeping the model shape stable (Req 4.6).

The detectors are pure, model-free, and deterministic; these tests drive them
against small hand-built inventories (and the reference repo for one real-tree
check) so the suite is self-contained — it does not depend on the concurrently
developed languages aggregation, the analyzer, or the stages.
"""

from __future__ import annotations

import importlib
import os

import pytest

from docuharnessx.analysis.scanner import FileEntry, FileInventory
from docuharnessx.analysis.model import ScanStats


DETECTORS_MODULE = "docuharnessx.analysis.detectors"
PACKAGE = "docuharnessx.analysis"

REFERENCE_REPO = "/home/mc/Source/malware_hashes"


# --------------------------------------------------------------------------- #
# Inventory-building helpers
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
    # The real scanner sorts entries by path; mirror that so detectors get the
    # same shape they will see in production.
    sorted_entries = tuple(sorted(entries, key=lambda e: e.path))
    return FileInventory(repo_path=repo_path, entries=sorted_entries, stats=stats)


# --------------------------------------------------------------------------- #
# Module / symbol surface
# --------------------------------------------------------------------------- #


def test_detectors_module_imports() -> None:
    assert _detectors() is not None


def test_detectors_public_symbols_exist() -> None:
    mod = _detectors()
    for name in (
        "summarize_structure",
        "detect_entrypoints",
        "detect_build_files",
        "detect_ci",
    ):
        assert hasattr(mod, name), name
        assert callable(getattr(mod, name))


def test_detectors_in_module_all() -> None:
    mod = _detectors()
    for name in (
        "summarize_structure",
        "detect_entrypoints",
        "detect_build_files",
        "detect_ci",
    ):
        assert name in mod.__all__


def test_task31_detectors_reexported_from_package() -> None:
    pkg = importlib.import_module(PACKAGE)
    for name in (
        "summarize_structure",
        "detect_entrypoints",
        "detect_build_files",
        "detect_ci",
    ):
        assert hasattr(pkg, name), name
        assert name in pkg.__all__


# --------------------------------------------------------------------------- #
# summarize_structure (Req 4.1)
# --------------------------------------------------------------------------- #


def test_structure_empty_inventory_returns_empty_tuple() -> None:
    mod = _detectors()
    assert mod.summarize_structure(_inventory()) == ()


def test_structure_summarizes_top_level_directories() -> None:
    mod = _detectors()
    inv = _inventory(
        _entry("main.go", language="Go", loc=50),
        _entry("internal/hash/hash.go", language="Go", loc=80),
        _entry("internal/hash/hash_test.go", language="Go", loc=40),
        _entry("docs/guide.md", language="Markdown", loc=120),
    )
    structure = mod.summarize_structure(inv)
    by_path = {d.path: d for d in structure}
    # Repo root is summarized with the empty-string path.
    assert "" in by_path
    assert "internal" in by_path
    assert "internal/hash" in by_path
    assert "docs" in by_path


def test_structure_is_sorted_by_path_ascending() -> None:
    mod = _detectors()
    inv = _inventory(
        _entry("zeta/a.go", language="Go", loc=1),
        _entry("alpha/b.go", language="Go", loc=1),
        _entry("main.go", language="Go", loc=1),
    )
    structure = mod.summarize_structure(inv)
    paths = [d.path for d in structure]
    assert paths == sorted(paths)


def test_structure_file_count_is_transitive() -> None:
    mod = _detectors()
    inv = _inventory(
        _entry("internal/a.go", language="Go", loc=1),
        _entry("internal/hash/b.go", language="Go", loc=1),
        _entry("internal/hash/c.go", language="Go", loc=1),
    )
    by_path = {d.path: d for d in mod.summarize_structure(inv)}
    # internal contains a.go plus everything under internal/hash (transitive).
    assert by_path["internal"].file_count == 3
    assert by_path["internal/hash"].file_count == 2
    # Root counts every file transitively.
    assert by_path[""].file_count == 3


def test_structure_dominant_language_is_highest_loc() -> None:
    mod = _detectors()
    inv = _inventory(
        # Two markdown files, but Go has more total LOC in this directory.
        _entry("pkg/a.go", language="Go", loc=200),
        _entry("pkg/notes.md", language="Markdown", loc=50),
        _entry("pkg/readme.md", language="Markdown", loc=50),
    )
    by_path = {d.path: d for d in mod.summarize_structure(inv)}
    assert by_path["pkg"].dominant_language == "Go"


def test_structure_role_classification() -> None:
    mod = _detectors()
    inv = _inventory(
        _entry("src/app.go", language="Go", loc=10),
        _entry("tests/app_test.go", language="Go", loc=10),
        _entry("docs/guide.md", language="Markdown", loc=10),
        _entry(".github/workflows/ci.yml", language="YAML", loc=10),
    )
    by_path = {d.path: d for d in mod.summarize_structure(inv)}
    assert by_path["src"].role == "source"
    assert by_path["tests"].role == "tests"
    assert by_path["docs"].role == "docs"
    # A CI directory is classified as ci.
    assert by_path[".github/workflows"].role == "ci"


def test_structure_roles_are_in_allowed_set() -> None:
    mod = _detectors()
    inv = _inventory(
        _entry("main.go", language="Go", loc=1),
        _entry("internal/x.go", language="Go", loc=1),
        _entry("README.md", language="Markdown", loc=1),
    )
    allowed = {"source", "tests", "docs", "config", "ci", "build", "other"}
    for d in mod.summarize_structure(inv):
        assert d.role in allowed


def test_structure_is_deterministic() -> None:
    mod = _detectors()
    inv = _inventory(
        _entry("internal/hash/hash.go", language="Go", loc=80),
        _entry("main.go", language="Go", loc=50),
        _entry("docs/guide.md", language="Markdown", loc=120),
    )
    assert mod.summarize_structure(inv) == mod.summarize_structure(inv)


# --------------------------------------------------------------------------- #
# detect_entrypoints (Req 4.2)
# --------------------------------------------------------------------------- #


def test_entrypoints_empty_inventory_returns_empty_tuple() -> None:
    mod = _detectors()
    assert mod.detect_entrypoints(_inventory()) == ()


def test_entrypoints_detect_go_main() -> None:
    mod = _detectors()
    inv = _inventory(_entry("main.go", language="Go", loc=20))
    eps = mod.detect_entrypoints(inv)
    assert any(e.path == "main.go" and e.kind == "main" for e in eps)


def test_entrypoints_detect_nested_go_main() -> None:
    mod = _detectors()
    inv = _inventory(
        _entry("main.go", language="Go", loc=20),
        _entry("tools/golden-capture/main.go", language="Go", loc=20),
    )
    paths = {e.path for e in mod.detect_entrypoints(inv)}
    assert "main.go" in paths
    assert "tools/golden-capture/main.go" in paths


def test_entrypoints_detect_python_dunder_main() -> None:
    mod = _detectors()
    inv = _inventory(_entry("pkg/__main__.py", language="Python", loc=10))
    eps = mod.detect_entrypoints(inv)
    assert any(e.path == "pkg/__main__.py" and e.kind == "main" for e in eps)


def test_entrypoints_detect_python_cli_module() -> None:
    mod = _detectors()
    inv = _inventory(_entry("pkg/cli.py", language="Python", loc=10))
    eps = mod.detect_entrypoints(inv)
    assert any(e.path == "pkg/cli.py" and e.kind == "cli" for e in eps)


def test_entrypoints_detect_bin_scripts() -> None:
    mod = _detectors()
    inv = _inventory(_entry("bin/run", language="Other", loc=5))
    eps = mod.detect_entrypoints(inv)
    assert any(e.path == "bin/run" and e.kind == "script" for e in eps)


def test_entrypoints_name_field_present() -> None:
    mod = _detectors()
    inv = _inventory(_entry("main.go", language="Go", loc=20))
    for e in mod.detect_entrypoints(inv):
        assert isinstance(e.name, str)


def test_entrypoints_sorted_by_path_then_kind() -> None:
    mod = _detectors()
    inv = _inventory(
        _entry("tools/x/main.go", language="Go", loc=1),
        _entry("main.go", language="Go", loc=1),
        _entry("app/__main__.py", language="Python", loc=1),
    )
    eps = mod.detect_entrypoints(inv)
    keys = [(e.path, e.kind) for e in eps]
    assert keys == sorted(keys)


def test_entrypoints_no_false_positive_on_ordinary_file() -> None:
    mod = _detectors()
    inv = _inventory(_entry("internal/hash/hash.go", language="Go", loc=80))
    assert mod.detect_entrypoints(inv) == ()


def test_entrypoints_deterministic() -> None:
    mod = _detectors()
    inv = _inventory(
        _entry("main.go", language="Go", loc=1),
        _entry("app/__main__.py", language="Python", loc=1),
    )
    assert mod.detect_entrypoints(inv) == mod.detect_entrypoints(inv)


# --------------------------------------------------------------------------- #
# detect_build_files (Req 4.3)
# --------------------------------------------------------------------------- #


def test_build_files_empty_inventory_returns_empty_tuple() -> None:
    mod = _detectors()
    assert mod.detect_build_files(_inventory()) == ()


def test_build_files_classify_kinds() -> None:
    mod = _detectors()
    inv = _inventory(
        _entry("go.mod", language="GoMod", loc=20),
        _entry("pyproject.toml", language="TOML", loc=20),
        _entry("package.json", language="JSON", loc=20),
        _entry("Makefile", language="Makefile", loc=20),
        _entry("Dockerfile", language="Dockerfile", loc=20),
        _entry("requirements.txt", language="Text", loc=5),
    )
    kinds = {b.path: b.kind for b in mod.detect_build_files(inv)}
    assert kinds["go.mod"] == "go_mod"
    assert kinds["pyproject.toml"] == "pyproject"
    assert kinds["package.json"] == "package_json"
    assert kinds["Makefile"] == "makefile"
    assert kinds["Dockerfile"] == "dockerfile"
    assert kinds["requirements.txt"] == "requirements"


def test_build_files_classify_lockfiles() -> None:
    mod = _detectors()
    inv = _inventory(
        _entry("go.sum", language="GoSum", loc=20),
        _entry("package-lock.json", language="JSON", loc=20),
        _entry("poetry.lock", language="Other", loc=20),
    )
    kinds = {b.path: b.kind for b in mod.detect_build_files(inv)}
    assert kinds["go.sum"] == "lockfile"
    assert kinds["package-lock.json"] == "lockfile"
    assert kinds["poetry.lock"] == "lockfile"


def test_build_files_detect_nested_subproject_manifests() -> None:
    mod = _detectors()
    inv = _inventory(
        _entry("go.mod", language="GoMod", loc=20),
        _entry(".dagger/go.mod", language="GoMod", loc=20),
    )
    paths = {b.path for b in mod.detect_build_files(inv)}
    assert "go.mod" in paths
    assert ".dagger/go.mod" in paths


def test_build_files_sorted_by_path() -> None:
    mod = _detectors()
    inv = _inventory(
        _entry("z/go.mod", language="GoMod", loc=1),
        _entry("a/go.mod", language="GoMod", loc=1),
        _entry("go.mod", language="GoMod", loc=1),
    )
    paths = [b.path for b in mod.detect_build_files(inv)]
    assert paths == sorted(paths)


def test_build_files_ignore_plain_source() -> None:
    mod = _detectors()
    inv = _inventory(_entry("main.go", language="Go", loc=20))
    assert mod.detect_build_files(inv) == ()


def test_build_files_deterministic() -> None:
    mod = _detectors()
    inv = _inventory(
        _entry("go.mod", language="GoMod", loc=1),
        _entry(".dagger/go.mod", language="GoMod", loc=1),
    )
    assert mod.detect_build_files(inv) == mod.detect_build_files(inv)


# --------------------------------------------------------------------------- #
# detect_ci (Req 4.4)
# --------------------------------------------------------------------------- #


def test_ci_empty_inventory_returns_empty_tuple() -> None:
    mod = _detectors()
    assert mod.detect_ci(_inventory()) == ()


def test_ci_detect_github_actions() -> None:
    mod = _detectors()
    inv = _inventory(
        _entry(".github/workflows/ci.yml", language="YAML", loc=20),
        _entry(".github/workflows/release.yaml", language="YAML", loc=20),
    )
    ci = mod.detect_ci(inv)
    providers = {w.path: w.provider for w in ci}
    assert providers[".github/workflows/ci.yml"] == "github_actions"
    assert providers[".github/workflows/release.yaml"] == "github_actions"


def test_ci_detect_gitlab() -> None:
    mod = _detectors()
    inv = _inventory(_entry(".gitlab-ci.yml", language="YAML", loc=20))
    ci = mod.detect_ci(inv)
    assert any(w.provider == "gitlab_ci" for w in ci)


def test_ci_detect_circleci() -> None:
    mod = _detectors()
    inv = _inventory(_entry(".circleci/config.yml", language="YAML", loc=20))
    ci = mod.detect_ci(inv)
    assert any(w.provider == "circleci" for w in ci)


def test_ci_detect_dagger() -> None:
    mod = _detectors()
    inv = _inventory(_entry("dagger.json", language="JSON", loc=10))
    ci = mod.detect_ci(inv)
    assert any(w.provider == "dagger" for w in ci)


def test_ci_does_not_match_non_workflow_github_files() -> None:
    mod = _detectors()
    # A file under .github but NOT under workflows/ is not a CI workflow.
    inv = _inventory(_entry(".github/ISSUE_TEMPLATE.md", language="Markdown", loc=5))
    assert mod.detect_ci(inv) == ()


def test_ci_sorted_by_path() -> None:
    mod = _detectors()
    inv = _inventory(
        _entry(".github/workflows/z.yml", language="YAML", loc=1),
        _entry(".github/workflows/a.yml", language="YAML", loc=1),
    )
    paths = [w.path for w in mod.detect_ci(inv)]
    assert paths == sorted(paths)


def test_ci_deterministic() -> None:
    mod = _detectors()
    inv = _inventory(
        _entry(".github/workflows/ci.yml", language="YAML", loc=1),
        _entry("dagger.json", language="JSON", loc=1),
    )
    assert mod.detect_ci(inv) == mod.detect_ci(inv)


# --------------------------------------------------------------------------- #
# Reference-repo validation (Req 4.3, 4.4) — real Go CLI tree
# --------------------------------------------------------------------------- #


@pytest.mark.skipif(
    not os.path.isdir(REFERENCE_REPO),
    reason="reference repo not present on this machine",
)
def test_reference_repo_detectors() -> None:
    from docuharnessx.analysis.scanner import scan

    inv = scan(REFERENCE_REPO)

    mod = _detectors()

    # Build files: both root and nested go.mod are classified (Req 4.3).
    build = {b.path: b.kind for b in mod.detect_build_files(inv)}
    assert build.get("go.mod") == "go_mod"
    assert build.get(".dagger/go.mod") == "go_mod"

    # CI: GitHub Actions workflows are detected (Req 4.4).
    ci = mod.detect_ci(inv)
    gh = [w for w in ci if w.provider == "github_actions"]
    assert any(w.path.startswith(".github/workflows/") for w in gh)
    # The dagger.json marker is recognized as a dagger CI provider.
    assert any(w.provider == "dagger" for w in ci)

    # Entrypoint: the root main.go is identified as a main entrypoint (Req 4.2).
    eps = mod.detect_entrypoints(inv)
    assert any(e.path == "main.go" and e.kind == "main" for e in eps)

    # Structure: a top-level summary exists and is sorted by path (Req 4.1).
    structure = mod.summarize_structure(inv)
    paths = [d.path for d in structure]
    assert paths == sorted(paths)
    assert "" in paths  # repo root
    assert "internal" in paths


@pytest.mark.skipif(
    not os.path.isdir(REFERENCE_REPO),
    reason="reference repo not present on this machine",
)
def test_reference_repo_detectors_deterministic() -> None:
    from docuharnessx.analysis.scanner import scan

    inv = scan(REFERENCE_REPO)
    mod = _detectors()
    assert mod.summarize_structure(inv) == mod.summarize_structure(inv)
    assert mod.detect_entrypoints(inv) == mod.detect_entrypoints(inv)
    assert mod.detect_build_files(inv) == mod.detect_build_files(inv)
    assert mod.detect_ci(inv) == mod.detect_ci(inv)
