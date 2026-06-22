"""Unit tests for task 2.2 (deterministic language detection + LOC aggregation).

Task 2.2 owns exactly one new module — ``docuharnessx.analysis.languages`` — the
deterministic, model-free language layer the analyzer composes (design
"languages — language detection and LOC mapping"; Req 3.1, 3.2, 3.3, 3.4, 3.5):

* ``detect_language(rel_path) -> str`` — an extension-and-special-filename rule
  set mapping a repo-relative path to a canonical language name, falling back to
  ``"Other"`` for unknown/extensionless/unrecognized files (Req 3.1, 3.4).
* ``aggregate_languages(entries) -> (stats, primary)`` — aggregates per-language
  file counts and total LOC over an iterable of file entries, returning the
  ``LanguageStat`` tuple sorted by LOC desc then language asc, and the primary
  language(s) (those tied for the greatest LOC) sorted asc (Req 3.2, 3.3, 3.5).

This task's boundary is ``languages`` only. To stay decoupled from the
concurrently-built scanner (design: ``scanner`` depends on ``languages``, not the
reverse), ``aggregate_languages`` consumes anything exposing ``.language`` and
``.loc`` — these tests feed a tiny local stub rather than importing the scanner's
``FileEntry``. The mapping is a pure function of the path string; aggregation is a
pure function of the entries; both are deterministic (Req 3.5).
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass

import pytest

from docuharnessx.analysis import model as model_mod


LANGUAGES_MODULE = "docuharnessx.analysis.languages"
PACKAGE = "docuharnessx.analysis"


# --------------------------------------------------------------------------- #
# A minimal entry stub: aggregate_languages only needs .language and .loc, so
# the languages layer must not depend on the scanner's FileEntry (Req: pure core,
# scanner depends on languages not the reverse).
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class _Entry:
    language: str
    loc: int


# --------------------------------------------------------------------------- #
# Module import + public surface
# --------------------------------------------------------------------------- #


def test_languages_module_imports() -> None:
    mod = importlib.import_module(LANGUAGES_MODULE)
    assert mod is not None


def test_languages_exports_the_two_public_functions() -> None:
    mod = importlib.import_module(LANGUAGES_MODULE)
    assert hasattr(mod, "detect_language")
    assert hasattr(mod, "aggregate_languages")
    assert callable(mod.detect_language)
    assert callable(mod.aggregate_languages)


def test_languages_is_reexported_from_package() -> None:
    pkg = importlib.import_module(PACKAGE)
    assert hasattr(pkg, "detect_language")
    assert hasattr(pkg, "aggregate_languages")
    assert "detect_language" in pkg.__all__
    assert "aggregate_languages" in pkg.__all__


# --------------------------------------------------------------------------- #
# detect_language: extension-based mapping (Req 3.1)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("rel_path", "expected"),
    [
        ("main.go", "Go"),
        ("internal/hash/hash.go", "Go"),
        ("docuharnessx/cli.py", "Python"),
        ("app.ts", "TypeScript"),
        ("app.tsx", "TypeScript"),
        ("index.js", "JavaScript"),
        ("index.jsx", "JavaScript"),
        ("README.md", "Markdown"),
        ("config.yml", "YAML"),
        ("config.yaml", "YAML"),
        ("data.json", "JSON"),
        ("pyproject.toml", "TOML"),
        ("lib.rs", "Rust"),
        ("Main.java", "Java"),
        ("main.c", "C"),
        ("main.h", "C"),
        ("widget.cpp", "C++"),
        ("script.sh", "Shell"),
        ("notes.txt", "Text"),
        ("page.html", "HTML"),
        ("style.css", "CSS"),
    ],
)
def test_detect_language_by_extension(rel_path: str, expected: str) -> None:
    mod = importlib.import_module(LANGUAGES_MODULE)
    assert mod.detect_language(rel_path) == expected


# --------------------------------------------------------------------------- #
# detect_language: special-filename mapping (Req 3.1)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("rel_path", "expected"),
    [
        ("Makefile", "Makefile"),
        ("sub/Makefile", "Makefile"),
        ("Dockerfile", "Dockerfile"),
        ("docker/Dockerfile", "Dockerfile"),
        # Canonical names align with the scanner's coarse FileEntry tags so the
        # two layers share one vocabulary for the analyzer (task 4.1).
        ("go.mod", "GoMod"),
        ("go.sum", "GoSum"),
    ],
)
def test_detect_language_by_special_filename(rel_path: str, expected: str) -> None:
    mod = importlib.import_module(LANGUAGES_MODULE)
    assert mod.detect_language(rel_path) == expected


# --------------------------------------------------------------------------- #
# detect_language: "Other" fallback for unknown / edge-case paths (Req 3.4)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "rel_path",
    [
        "LICENSE",          # extensionless, not a recognized special filename
        "bin/run",          # extensionless script-like
        "data.unknownext",  # unrecognized extension
        "archive.xyz",      # unrecognized extension
        "sample_A__092e",   # the reference repo's testdata samples
        "",                 # empty path
        ".",                # dot only
    ],
)
def test_detect_language_unknown_falls_back_to_other(rel_path: str) -> None:
    mod = importlib.import_module(LANGUAGES_MODULE)
    assert mod.detect_language(rel_path) == "Other"


def test_detect_language_is_case_insensitive_on_extension() -> None:
    mod = importlib.import_module(LANGUAGES_MODULE)
    # Extension casing must not change the canonical language (Req 3.5 determinism).
    assert mod.detect_language("MAIN.GO") == "Go"
    assert mod.detect_language("Script.PY") == "Python"


def test_detect_language_dotfile_without_extension_is_other() -> None:
    mod = importlib.import_module(LANGUAGES_MODULE)
    # A leading-dot name with no further extension (e.g. ".gitignore") has no
    # mapped extension and is not a recognized special filename -> "Other".
    assert mod.detect_language(".gitignore") == "Other"
    assert mod.detect_language(".env") == "Other"


def test_detect_language_returns_str() -> None:
    mod = importlib.import_module(LANGUAGES_MODULE)
    assert isinstance(mod.detect_language("main.go"), str)
    assert isinstance(mod.detect_language("weird"), str)


# --------------------------------------------------------------------------- #
# aggregate_languages: counts + LOC totals (Req 3.2)
# --------------------------------------------------------------------------- #


def test_aggregate_counts_files_and_sums_loc_per_language() -> None:
    mod = importlib.import_module(LANGUAGES_MODULE)
    entries = [
        _Entry("Go", 100),
        _Entry("Go", 50),
        _Entry("Python", 30),
    ]
    stats, _primary = mod.aggregate_languages(entries)
    by_lang = {s.language: s for s in stats}
    assert by_lang["Go"].files == 2
    assert by_lang["Go"].loc == 150
    assert by_lang["Python"].files == 1
    assert by_lang["Python"].loc == 30


def test_aggregate_returns_languagestat_instances() -> None:
    mod = importlib.import_module(LANGUAGES_MODULE)
    stats, _primary = mod.aggregate_languages([_Entry("Go", 10)])
    assert all(isinstance(s, model_mod.LanguageStat) for s in stats)


def test_aggregate_returns_tuples_not_lists() -> None:
    mod = importlib.import_module(LANGUAGES_MODULE)
    stats, primary = mod.aggregate_languages([_Entry("Go", 10), _Entry("Python", 5)])
    assert isinstance(stats, tuple)
    assert isinstance(primary, tuple)


def test_aggregate_empty_input_yields_empty_results() -> None:
    mod = importlib.import_module(LANGUAGES_MODULE)
    stats, primary = mod.aggregate_languages([])
    assert stats == ()
    assert primary == ()


def test_aggregate_counts_zero_loc_files() -> None:
    mod = importlib.import_module(LANGUAGES_MODULE)
    # A zero-LOC file (e.g. empty or binary classified "Other") still counts as a
    # file in its bucket and is not dropped from the totals (Req 3.4).
    stats, _primary = mod.aggregate_languages([_Entry("Other", 0), _Entry("Other", 0)])
    by_lang = {s.language: s for s in stats}
    assert by_lang["Other"].files == 2
    assert by_lang["Other"].loc == 0


# --------------------------------------------------------------------------- #
# aggregate_languages: deterministic ordering — LOC desc, then language asc
# (Req 3.5, design "Aggregation sorts by LOC desc then name asc")
# --------------------------------------------------------------------------- #


def test_aggregate_sorts_by_loc_descending() -> None:
    mod = importlib.import_module(LANGUAGES_MODULE)
    stats, _primary = mod.aggregate_languages(
        [_Entry("Python", 30), _Entry("Go", 100), _Entry("Markdown", 60)]
    )
    assert [s.language for s in stats] == ["Go", "Markdown", "Python"]


def test_aggregate_ties_on_loc_break_by_language_ascending() -> None:
    mod = importlib.import_module(LANGUAGES_MODULE)
    # Equal LOC -> alphabetical language order, deterministically.
    stats, _primary = mod.aggregate_languages(
        [_Entry("Python", 40), _Entry("Go", 40), _Entry("Markdown", 40)]
    )
    assert [s.language for s in stats] == ["Go", "Markdown", "Python"]


def test_aggregate_input_order_does_not_change_output() -> None:
    mod = importlib.import_module(LANGUAGES_MODULE)
    a = mod.aggregate_languages([_Entry("Go", 100), _Entry("Python", 30)])
    b = mod.aggregate_languages([_Entry("Python", 30), _Entry("Go", 100)])
    assert a == b


def test_aggregate_is_deterministic_across_repeated_runs() -> None:
    mod = importlib.import_module(LANGUAGES_MODULE)
    entries = [
        _Entry("Go", 100),
        _Entry("Markdown", 60),
        _Entry("Python", 60),
        _Entry("YAML", 5),
        _Entry("Other", 0),
    ]
    first = mod.aggregate_languages(list(entries))
    second = mod.aggregate_languages(list(entries))
    assert first == second


# --------------------------------------------------------------------------- #
# aggregate_languages: primary language(s) = those tied for greatest LOC,
# sorted asc (Req 3.3) — including the docs-vs-source scenario from the task's
# observable.
# --------------------------------------------------------------------------- #


def test_primary_language_is_the_single_max_loc_language() -> None:
    mod = importlib.import_module(LANGUAGES_MODULE)
    _stats, primary = mod.aggregate_languages(
        [_Entry("Go", 100), _Entry("Python", 30)]
    )
    assert primary == ("Go",)


def test_primary_language_handles_ties_returning_all_tied_sorted_asc() -> None:
    mod = importlib.import_module(LANGUAGES_MODULE)
    _stats, primary = mod.aggregate_languages(
        [_Entry("Python", 50), _Entry("Go", 50), _Entry("Markdown", 10)]
    )
    assert primary == ("Go", "Python")


def test_many_docs_files_but_higher_loc_source_reports_source_as_primary() -> None:
    """The task's explicit observable: many docs files, higher-LOC source wins."""
    mod = importlib.import_module(LANGUAGES_MODULE)
    entries = [_Entry("Markdown", 10) for _ in range(20)]  # 20 docs files, 200 LOC
    entries += [_Entry("Go", 100), _Entry("Go", 150)]      # 2 source files, 250 LOC
    stats, primary = mod.aggregate_languages(entries)
    by_lang = {s.language: s for s in stats}
    assert by_lang["Markdown"].files == 20
    assert by_lang["Go"].files == 2
    assert by_lang["Go"].loc == 250
    assert by_lang["Markdown"].loc == 200
    # More docs *files*, but the higher-LOC source language is primary (Req 3.3).
    assert primary == ("Go",)
    # And Go sorts ahead of Markdown in the breakdown (LOC desc).
    assert stats[0].language == "Go"


def test_primary_is_empty_when_no_entries() -> None:
    mod = importlib.import_module(LANGUAGES_MODULE)
    _stats, primary = mod.aggregate_languages([])
    assert primary == ()


def test_primary_excludes_zero_loc_only_when_a_nonzero_language_exists() -> None:
    mod = importlib.import_module(LANGUAGES_MODULE)
    # With a real source language present, a zero-LOC "Other" bucket is never the
    # primary language.
    _stats, primary = mod.aggregate_languages([_Entry("Go", 100), _Entry("Other", 0)])
    assert primary == ("Go",)


# --------------------------------------------------------------------------- #
# Cross-layer seam: detect_language must agree with the coarse language tag the
# scanner already carries on FileEntry, so the analyzer (task 4.1) sees a single
# canonical name per bucket regardless of which layer produced the tag.
# --------------------------------------------------------------------------- #


def test_detect_language_agrees_with_scanner_tags_on_a_polyglot_set() -> None:
    mod = importlib.import_module(LANGUAGES_MODULE)
    scanner = pytest.importorskip("docuharnessx.analysis.scanner")
    tag = getattr(scanner, "_tag_language", None)
    if tag is None:  # pragma: no cover - scanner internals not exposed
        pytest.skip("scanner does not expose a per-file tagger to compare against")
    paths = [
        "main.go",
        "go.mod",
        "go.sum",
        "docuharnessx/cli.py",
        "README.md",
        "config.yaml",
        "data.json",
        "Dockerfile",
        "Makefile",
        "LICENSE",
        "bin/run",
    ]
    for p in paths:
        assert mod.detect_language(p) == tag(p), f"language-tag drift for {p!r}"
