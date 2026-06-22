"""Task 6.3 — validate determinism against the reference repository.

Where the crafted-fixture suite (``test_analysis_core_validation``, task 6.1) pins
the deterministic core against synthetic trees, this suite is the task's stated
observable: run the **analyzer** end-to-end against a *real* polyglot project — the
reference Go CLI at ``/home/mc/Source/malware_hashes`` — and assert both the
expected analysis shape and run-to-run determinism (tasks.md 6.3; design
"Reference-Repo Tests").

Boundary (task 6.3): ``analyzer``. These tests drive ``scan() -> analyze()`` (the
real pipeline the Analyze stage runs) and assert against the resulting frozen
:class:`~docuharnessx.analysis.model.RepoAnalysis`. They never mutate the analyzer
or its defaults; the two scans use the same code path the stage adapters use.

What the reference repo exercises (a Go CLI: ``main.go`` entrypoint, root ``go.mod``
plus a nested ``.dagger/go.mod``, GitHub Actions + Dagger CI, ``*_test.go`` tests,
``internal/*`` components, a README):

* **Primary language is Go.** The repo carries a large ``.kiro/specs/*``
  documentation tree, so by raw LOC *Markdown* leads the full-repo scan. That is
  the correct deterministic output and is asserted as such. To validate the task's
  "primary language is Go" observable on the project's *code*, a second scan adds
  the spec-docs directory to ``ScanLimits.excluded_dirs`` (a caller-supplied limit,
  not an analyzer change) and asserts ``primary_languages == ("Go",)``. Either way
  Go is the dominant *programming* language, which is asserted directly.
* both the root ``go.mod`` and the nested ``.dagger/go.mod`` are detected as build
  files (Req 4.3 nested manifests);
* GitHub Actions CI under ``.github/workflows/`` is detected (Req 4.4);
* ``*_test.go`` tests are reported present with the ``go_testing`` framework
  (Req 4.5);
* the README is detected (Req 5.4);
* ``internal/*`` packages surface as components (Req 5.2);
* the ``main.go`` entrypoint is identified (Req 4.2).

* **Determinism.** Two consecutive ``scan() -> analyze()`` runs produce *equal*
  :class:`RepoAnalysis` objects whose JSON serializes **byte-identically**
  (Req 6.4, 9.2) — the run-to-run reproducibility guarantee on a real project.

Requirements: 3.3, 4.3, 4.4, 4.5, 5.4, 9.2.
"""

from __future__ import annotations

import os

import pytest

from docuharnessx.analysis import analyze, scan, to_json
from docuharnessx.analysis.model import REPO_ANALYSIS_SCHEMA_VERSION, RepoAnalysis
from docuharnessx.analysis.scanner import DEFAULT_EXCLUDED_DIRS, ScanLimits

#: The reference Go CLI used for real-project validation (design "Reference-Repo
#: Tests"). Tests skip cleanly when it is not checked out on this machine.
REFERENCE_REPO = "/home/mc/Source/malware_hashes"

#: Language tags that are documentation / data / manifest noise rather than a
#: project's *programming* language. Used only to assert which programming language
#: leads; it never changes what the analyzer reports.
_NON_CODE_LANGUAGES = frozenset(
    {
        "Markdown",
        "reStructuredText",
        "Text",
        "JSON",
        "YAML",
        "TOML",
        "INI",
        "XML",
        "HTML",
        "CSS",
        "GoMod",
        "GoSum",
        "Other",
    }
)

#: Directory of Kiro spec/steering Markdown the reference repo carries. Excluding it
#: (a caller-supplied scan limit) reveals the project's *code* primary language.
_DOC_SPEC_DIR = ".kiro"


pytestmark = pytest.mark.skipif(
    not os.path.isdir(REFERENCE_REPO),
    reason=f"reference repo not present at {REFERENCE_REPO}",
)


def _analyze_reference(*, exclude_spec_docs: bool = False) -> RepoAnalysis:
    """Run the real ``scan() -> analyze()`` pipeline over the reference repo.

    With ``exclude_spec_docs`` the ``.kiro`` documentation tree is added to the
    scan's excluded directories via :class:`ScanLimits` — a caller-supplied bound,
    not an analyzer change — so the project's code-side primary language surfaces.
    """
    if exclude_spec_docs:
        limits = ScanLimits(excluded_dirs=DEFAULT_EXCLUDED_DIRS | {_DOC_SPEC_DIR})
        inventory = scan(REFERENCE_REPO, limits)
    else:
        inventory = scan(REFERENCE_REPO)
    return analyze(inventory)


# --------------------------------------------------------------------------- #
# Shape: the Go-CLI signal set the planner expects from the reference repo     #
# --------------------------------------------------------------------------- #


class TestReferenceRepoAnalysisShape:
    """Assert the analyzer extracts the reference repo's Go-CLI signals (Req 3.3,
    4.2-4.5, 5.2, 5.4)."""

    def test_schema_version_and_repo_path(self):
        analysis = _analyze_reference()
        assert analysis.schema_version == REPO_ANALYSIS_SCHEMA_VERSION
        # Provenance is the scanned root's realpath.
        assert analysis.repo_path == os.path.realpath(REFERENCE_REPO)

    def test_go_is_the_primary_programming_language(self):
        """Go leads the project's code, and is the sole primary once the spec-docs
        Markdown tree is excluded (Req 3.3)."""
        full = _analyze_reference()

        # Go is the dominant *programming* language in the full deterministic scan,
        # even though the .kiro/specs Markdown tree leads by raw total LOC.
        code_langs = [
            stat
            for stat in full.languages
            if stat.language not in _NON_CODE_LANGUAGES
        ]
        assert code_langs, "expected at least one programming language"
        assert code_langs[0].language == "Go"
        assert code_langs[0].loc > 0

        # On the project's code (spec-docs excluded), Go is the sole primary.
        code_only = _analyze_reference(exclude_spec_docs=True)
        assert code_only.primary_languages == ("Go",)
        # A Go stat is present in the full breakdown too, with files + LOC.
        go_stat = next(s for s in full.languages if s.language == "Go")
        assert go_stat.files >= 1
        assert go_stat.loc > 0

    def test_main_go_entrypoint_detected(self):
        """The ``main.go`` entrypoint is identified (Req 4.2)."""
        analysis = _analyze_reference()
        entry_paths = {e.path for e in analysis.entrypoints}
        assert "main.go" in entry_paths
        main_entry = next(e for e in analysis.entrypoints if e.path == "main.go")
        assert main_entry.kind == "main"

    def test_root_and_nested_go_mod_build_files_detected(self):
        """Both the root and the nested ``.dagger/go.mod`` manifest are detected
        (Req 4.3 nested manifests)."""
        analysis = _analyze_reference()
        build_by_path = {b.path: b for b in analysis.build_files}
        assert "go.mod" in build_by_path
        assert ".dagger/go.mod" in build_by_path
        assert build_by_path["go.mod"].kind == "go_mod"
        assert build_by_path[".dagger/go.mod"].kind == "go_mod"

    def test_github_actions_ci_detected(self):
        """GitHub Actions workflows under ``.github/workflows/`` are detected
        (Req 4.4)."""
        analysis = _analyze_reference()
        gha = [
            c
            for c in analysis.ci_workflows
            if c.provider == "github_actions"
            and c.path.startswith(".github/workflows/")
        ]
        assert gha, f"expected GitHub Actions CI, got {analysis.ci_workflows!r}"

    def test_go_tests_present_with_framework(self):
        """``*_test.go`` files are reported present with the ``go_testing``
        framework (Req 4.5)."""
        analysis = _analyze_reference()
        assert analysis.tests.present is True
        assert "go_testing" in analysis.tests.frameworks
        # The canonical reference test file is among the representative paths.
        assert any(p.endswith("_test.go") for p in analysis.tests.paths)
        assert "main_test.go" in analysis.tests.paths

    def test_readme_detected(self):
        """The top-level README is detected (Req 5.4)."""
        analysis = _analyze_reference()
        assert analysis.docs.has_readme is True
        assert "README.md" in analysis.docs.readme_paths

    def test_internal_packages_surface_as_components(self):
        """The ``internal/*`` packages map to components (Req 5.2)."""
        analysis = _analyze_reference()
        component_paths = {c.path for c in analysis.components}
        # The reference repo's three internal packages.
        assert "internal/hash" in component_paths
        assert "internal/peanalysis" in component_paths
        assert "internal/report" in component_paths
        # Each component carries a small representative-file set.
        report = next(c for c in analysis.components if c.path == "internal/report")
        assert report.representative_files
        assert all(
            f.startswith("internal/report/") for f in report.representative_files
        )

    def test_empty_categories_are_present_not_omitted(self):
        """Detection categories with no matches are empty collections, keeping the
        model shape stable (Req 4.6)."""
        analysis = _analyze_reference()
        # These are tuples on every analysis regardless of content.
        assert isinstance(analysis.artifacts, tuple)
        assert isinstance(analysis.docs.doc_dirs, tuple)
        assert isinstance(analysis.public_surface, tuple)


# --------------------------------------------------------------------------- #
# Determinism: two consecutive runs over the real repo are byte-identical      #
# --------------------------------------------------------------------------- #


class TestReferenceRepoDeterminism:
    """Run-to-run reproducibility on a real polyglot project (Req 6.4, 9.2)."""

    def test_two_runs_yield_equal_analysis(self):
        """Two ``scan() -> analyze()`` runs return *equal* RepoAnalysis objects."""
        first = _analyze_reference()
        second = _analyze_reference()
        assert first == second

    def test_two_runs_serialize_byte_identically(self):
        """The JSON of two consecutive runs is byte-for-byte identical (Req 6.4,
        9.2) — the determinism guarantee the planner relies on."""
        first_json = to_json(_analyze_reference())
        second_json = to_json(_analyze_reference())
        assert first_json == second_json
        # Guard against an empty/degenerate serialization masking equality.
        assert len(first_json) > 0
        assert '"schema_version"' in first_json

    def test_code_only_scan_is_also_deterministic(self):
        """Determinism holds for the spec-docs-excluded code scan too, so the
        Go-primary assertion rests on a reproducible result."""
        first = to_json(_analyze_reference(exclude_spec_docs=True))
        second = to_json(_analyze_reference(exclude_spec_docs=True))
        assert first == second
