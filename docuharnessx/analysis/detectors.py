"""Deterministic signal extraction over a :class:`FileInventory` (detectors).

``docuharnessx.analysis.detectors`` is the pure, model-free *signal layer* of the
analysis core: a family of one-function-per-concern detectors that turn the
scanner's :class:`~docuharnessx.analysis.scanner.FileInventory` into the frozen
record tuples the analyzer composes into :class:`RepoAnalysis` (design "detectors
— signal extraction"). Every detector is a pure function of the inventory with no
filesystem access of its own beyond what task-3.2's manifest-reading detectors
need, so detection is reproducible: two runs over an unchanged inventory yield
equal results, and every returned collection is pre-sorted before return so the
analyzer never has to re-sort (design "All detector outputs are sorted before
return").

This module is built up across the three parallel "detectors" tasks; **task 3.1**
owns the four structure/build/CI signals here:

* :func:`summarize_structure` — a per-directory summary (file count, dominant
  language, heuristic role), sorted by path ascending (Req 4.1).
* :func:`detect_entrypoints` — language-appropriate program entrypoints, sorted by
  ``(path, kind)`` (Req 4.2).
* :func:`detect_build_files` — build/config manifests, including those nested in
  sub-projects, sorted by path (Req 4.3).
* :func:`detect_ci` — CI/workflow configuration with provider + path, sorted by
  path (Req 4.4).

Each category is returned as an empty tuple rather than omitted when there are no
matches, so the model shape stays stable regardless of repo contents (Req 4.6).

**Task 3.2** appends the next two signals to this same module additively, reusing
the small path helpers below:

* :func:`detect_tests` — recognized test files/directories/frameworks per language
  rolled into a single :class:`TestLayout` (``present`` + sorted ``frameworks`` +
  representative sorted ``paths``); empty/absent when no tests match (Req 4.5, 4.6).
* :func:`extract_dependencies` — declared dependencies parsed from recognized
  manifests (``pyproject.toml`` via :mod:`tomllib`, ``go.mod``/``requirements*.txt``
  by line parse, ``package.json`` via :mod:`json`) with their source manifest and
  scope, sorted by ``(source, name)`` (Req 5.1). A malformed/partially-parseable
  manifest yields what is extractable and is recorded as "partially parsed" rather
  than aborting (Req 5.6); :func:`extract_dependencies_with_notes` returns those
  notes alongside the deps so the analyzer can fold them into ``ScanStats.notes``,
  while the pinned :func:`extract_dependencies` is the notes-dropping public seam.

Unlike the task-3.1 detectors, :func:`extract_dependencies` is *not* purely a
function of the inventory: a manifest's declared dependencies live in its
*contents*, which the scanner does not carry on :class:`FileEntry`, so the
dependency parser re-reads the (small, recognized) manifest files from disk under
the ``repo_path`` root. It stays deterministic — it reads only files the inventory
already lists, parses them with stdlib parsers, and sorts every output.

**Task 3.3** appends the last four signals to this same module additively, reusing
the small path helpers below:

* :func:`map_components` — a component/module map derived from the directory/package
  structure: each code-bearing package directory (and the repo root when it holds
  top-level code) becomes a :class:`Component` with its path, a name from the
  directory basename, and a small sorted representative-file set, sorted by path
  (Req 5.2).
* :func:`detect_public_surface` — cheaply-detectable public surface only: CLI
  flags/subcommands (argparse / Go cobra / Go ``flag``) and exported symbols (Go
  capitalized top-level ``func``/``type``, Python ``__all__``) via shallow regex,
  omitting anything needing real AST/semantic analysis, sorted by
  ``(source, kind, name)`` (Req 5.3). Like :func:`extract_dependencies` this reads
  recognized source files' *contents* from disk under ``repo_path`` (the scanner
  does not carry file bodies); it stays deterministic and bounded.
* :func:`detect_docs` — documentation presence rolled into a :class:`DocPresence`
  (README presence + sorted README paths, sorted ``docs/`` directories, sorted other
  recognized doc files), empty/absent when nothing matches (Req 5.4, 4.6).
* :func:`detect_artifacts` — notable artifacts (license, dockerfile, schema/spec,
  generated-output markers) by filename/pattern, sorted by path (Req 5.5, 4.6).
"""

from __future__ import annotations

import json
import os
import re
import tomllib

from docuharnessx.analysis.model import (
    Artifact,
    BuildFile,
    CIWorkflow,
    Component,
    Dependency,
    DirectorySummary,
    DocPresence,
    Entrypoint,
    PublicSymbol,
    TestLayout,
)
from docuharnessx.analysis.scanner import FileInventory

__all__ = [
    "summarize_structure",
    "detect_entrypoints",
    "detect_build_files",
    "detect_ci",
    "detect_tests",
    "extract_dependencies",
    "extract_dependencies_with_notes",
    "map_components",
    "detect_public_surface",
    "detect_docs",
    "detect_artifacts",
]


# --------------------------------------------------------------------------- #
# Shared path helpers (reused by all detectors, this task's and later ones')   #
# --------------------------------------------------------------------------- #


def _basename(rel_path: str) -> str:
    """Final path component of a repo-relative POSIX path (``"a/b/c.go" -> "c.go"``)."""
    return rel_path.rsplit("/", 1)[-1]


def _dir_of(rel_path: str) -> str:
    """Directory containing ``rel_path`` (``""`` for a repo-root file)."""
    head, sep, _tail = rel_path.rpartition("/")
    return head if sep else ""


def _ancestor_dirs(rel_path: str) -> tuple[str, ...]:
    """All directory paths that transitively contain ``rel_path``, root first.

    For ``"internal/hash/hash.go"`` this is ``("", "internal", "internal/hash")``
    — the repo root (``""``) plus every intermediate package. Used so a file's LOC
    and count roll up into each enclosing directory's summary (Req 4.1).
    """
    directory = _dir_of(rel_path)
    dirs: list[str] = [""]  # the repo root always contains every file
    if directory:
        parts = directory.split("/")
        accumulated = ""
        for part in parts:
            accumulated = part if not accumulated else f"{accumulated}/{part}"
            dirs.append(accumulated)
    return tuple(dirs)


# --------------------------------------------------------------------------- #
# summarize_structure (Req 4.1)                                                #
# --------------------------------------------------------------------------- #

#: Top-level directory names that map directly to a heuristic role. Checked
#: against the *first* path segment of a directory so a ``tests/unit`` sub-tree
#: still reads as a tests area. Conservative: anything not matched falls through
#: to a language-based / "other" classification below (Req 4.1).
_ROLE_BY_TOP_SEGMENT: dict[str, str] = {
    "test": "tests",
    "tests": "tests",
    "testdata": "tests",
    "doc": "docs",
    "docs": "docs",
    "examples": "docs",
    "example": "docs",
    "src": "source",
    "lib": "source",
    "pkg": "source",
    "internal": "source",
    "cmd": "source",
    "app": "source",
    "bin": "build",
    "scripts": "build",
    "build": "build",
    "dist": "build",
    "ci": "ci",
    ".github": "ci",
    ".circleci": "ci",
    ".gitlab": "ci",
    ".config": "config",
    "config": "config",
    "configs": "config",
    "etc": "config",
}

#: Directory basenames (the last segment) that signal a CI area regardless of
#: where they sit, so ``.github/workflows`` reads as ``ci`` (Req 4.4 alignment).
_CI_DIR_BASENAMES: frozenset[str] = frozenset({"workflows", ".circleci"})

#: Languages that count as documentation/markup when deciding a directory's role
#: from its dominant language (a docs dir need not be named ``docs``).
_DOC_LANGUAGES: frozenset[str] = frozenset(
    {"Markdown", "reStructuredText", "Text", "HTML"}
)

#: Languages that count as configuration when deciding a directory's role.
_CONFIG_LANGUAGES: frozenset[str] = frozenset(
    {"YAML", "TOML", "INI", "JSON", "XML"}
)

#: Source-code languages used to decide whether a dir's role is ``source``.
_SOURCE_LANGUAGES: frozenset[str] = frozenset(
    {
        "Go",
        "Python",
        "TypeScript",
        "JavaScript",
        "Rust",
        "Java",
        "Kotlin",
        "Ruby",
        "PHP",
        "C",
        "C++",
        "C#",
        "Swift",
        "Scala",
        "Shell",
        "SQL",
    }
)


def _classify_role(directory: str, dominant_language: str, has_test_files: bool) -> str:
    """Pick a heuristic role for a directory (Req 4.1).

    Resolution order is deterministic and conservative:

    1. A CI directory basename (e.g. ``workflows``) → ``"ci"``.
    2. A recognized top-segment name (``tests``, ``docs``, ``src``, …) → its role.
    3. Otherwise the directory's *dominant language* decides: a doc/markup
       language → ``"docs"``; a config language → ``"config"``; a source language
       → ``"source"``.
    4. If none of the above but the directory holds recognized test files →
       ``"tests"``.
    5. Anything left → ``"other"`` (Req 4.1: every dir gets a stable role).
    """
    base = _basename(directory) if directory else ""
    if base in _CI_DIR_BASENAMES:
        return "ci"

    first_segment = directory.split("/", 1)[0] if directory else ""
    mapped = _ROLE_BY_TOP_SEGMENT.get(first_segment)
    if mapped is not None:
        return mapped

    if dominant_language in _DOC_LANGUAGES:
        return "docs"
    if dominant_language in _SOURCE_LANGUAGES:
        return "source"
    if dominant_language in _CONFIG_LANGUAGES:
        return "config"
    if has_test_files:
        return "tests"
    return "other"


def _is_test_file(rel_path: str) -> bool:
    """Cheap test-file signal used only to colour a directory's role (Req 4.1).

    Recognizes the common per-language conventions — Go ``*_test.go``, Python
    ``test_*.py`` / ``*_test.py``, and JS/TS ``*.test.*`` / ``*.spec.*``. This is a
    lightweight heuristic for role classification; full test-layout detection is
    task 3.2's :func:`detect_tests`.
    """
    base = _basename(rel_path)
    if base.endswith("_test.go"):
        return True
    if base.startswith("test_") and base.endswith(".py"):
        return True
    if base.endswith("_test.py"):
        return True
    for marker in (".test.", ".spec."):
        if marker in base:
            return True
    return False


def summarize_structure(inv: FileInventory) -> tuple[DirectorySummary, ...]:
    """Summarize every directory in the inventory (Req 4.1).

    Produces one :class:`DirectorySummary` per directory that (transitively)
    contains at least one file, including the repo root (path ``""``). For each
    directory the summary carries:

    * ``file_count`` — files directly **and transitively** under it;
    * ``dominant_language`` — the language with the greatest total LOC under it
      (ties broken by language name ascending), or ``"Other"`` when empty;
    * ``role`` — a heuristic role from :func:`_classify_role`.

    The returned tuple is sorted by path ascending so the analyzer never re-sorts
    and two runs over an unchanged inventory are equal (Req 4.1, 9.1). An empty
    inventory yields an empty tuple (Req 4.6).
    """
    if not inv.entries:
        return ()

    counts: dict[str, int] = {}
    loc_by_dir_lang: dict[str, dict[str, int]] = {}
    has_tests: dict[str, bool] = {}

    for entry in inv.entries:
        is_test = _is_test_file(entry.path)
        for directory in _ancestor_dirs(entry.path):
            counts[directory] = counts.get(directory, 0) + 1
            lang_loc = loc_by_dir_lang.setdefault(directory, {})
            lang_loc[entry.language] = lang_loc.get(entry.language, 0) + int(entry.loc)
            if is_test:
                has_tests[directory] = True

    summaries: list[DirectorySummary] = []
    for directory in sorted(counts):
        lang_loc = loc_by_dir_lang.get(directory, {})
        if lang_loc:
            # Greatest LOC, then language name ascending for a deterministic tie
            # break. A directory of only zero-LOC files still picks a name.
            dominant = sorted(lang_loc, key=lambda lang: (-lang_loc[lang], lang))[0]
        else:  # pragma: no cover - a counted dir always has at least one entry
            dominant = "Other"
        summaries.append(
            DirectorySummary(
                path=directory,
                file_count=counts[directory],
                dominant_language=dominant,
                role=_classify_role(
                    directory, dominant, has_tests.get(directory, False)
                ),
            )
        )
    return tuple(summaries)


# --------------------------------------------------------------------------- #
# detect_entrypoints (Req 4.2)                                                 #
# --------------------------------------------------------------------------- #

#: Exact basenames (case-sensitive where the convention is) that signal a program
#: entrypoint, mapped to their :class:`Entrypoint` kind. Conservative: only
#: well-established conventions are listed so detection produces no noise (Req 4.2).
_ENTRYPOINT_BASENAMES: dict[str, str] = {
    "main.go": "main",
    "__main__.py": "main",
    "main.py": "main",
    "main.rs": "main",
    "cli.py": "cli",
    "__init__.go": "other",
}

#: Top-level directories whose direct, non-binary files are treated as runnable
#: scripts (Req 4.2: ``bin/`` scripts). Matched on the first path segment.
_SCRIPT_DIRS: frozenset[str] = frozenset({"bin", "scripts"})


def detect_entrypoints(inv: FileInventory) -> tuple[Entrypoint, ...]:
    """Detect language-appropriate entrypoints over the inventory (Req 4.2).

    Uses deterministic, conservative filename/path signals:

    * an exact entrypoint basename (``main.go``, ``__main__.py``, ``main.py``,
      ``cli.py``, ``main.rs``) → an :class:`Entrypoint` of the mapped kind;
    * any direct, non-binary file under a ``bin/`` or ``scripts/`` directory →
      a ``"script"`` entrypoint.

    The ``name`` field carries the basename for scripts (a useful symbolic handle)
    and is ``""`` for the filename-convention entrypoints, whose path already names
    them. Console-script / ``package.json bin`` entries that require reading a
    manifest are intentionally **out of scope** here (those come from the
    dependency/manifest detectors); this function stays a pure, cheap path scan.

    The result is sorted by ``(path, kind)`` and is empty when nothing matches
    (Req 4.2, 4.6). Deterministic across runs (Req 9.1).
    """
    found: list[Entrypoint] = []
    seen: set[tuple[str, str]] = set()

    for entry in inv.entries:
        base = _basename(entry.path)

        kind = _ENTRYPOINT_BASENAMES.get(base)
        if kind is not None and kind != "other":
            key = (entry.path, kind)
            if key not in seen:
                seen.add(key)
                found.append(Entrypoint(path=entry.path, kind=kind, name=""))
            continue

        first_segment = entry.path.split("/", 1)[0] if "/" in entry.path else ""
        if first_segment in _SCRIPT_DIRS and not entry.is_binary:
            key = (entry.path, "script")
            if key not in seen:
                seen.add(key)
                found.append(
                    Entrypoint(path=entry.path, kind="script", name=base)
                )

    found.sort(key=lambda e: (e.path, e.kind))
    return tuple(found)


# --------------------------------------------------------------------------- #
# detect_build_files (Req 4.3)                                                 #
# --------------------------------------------------------------------------- #

#: Exact basenames → :class:`BuildFile` kind. Recognized at any depth so a nested
#: sub-project manifest (e.g. ``.dagger/go.mod``) classifies like a top-level one
#: (Req 4.3). Case-sensitive: ``Makefile``/``Dockerfile`` follow their convention.
_BUILD_BASENAMES: dict[str, str] = {
    "pyproject.toml": "pyproject",
    "setup.py": "pyproject",
    "setup.cfg": "pyproject",
    "go.mod": "go_mod",
    "package.json": "package_json",
    "makefile": "makefile",
    "gnumakefile": "makefile",
    "dockerfile": "dockerfile",
    "build.gradle": "other",
    "pom.xml": "other",
    "cargo.toml": "other",
    "cmakelists.txt": "other",
}

#: Exact lockfile basenames → ``"lockfile"`` (Req 4.3). Recognized at any depth.
_LOCKFILE_BASENAMES: frozenset[str] = frozenset(
    {
        "go.sum",
        "package-lock.json",
        "yarn.lock",
        "pnpm-lock.yaml",
        "poetry.lock",
        "pdm.lock",
        "cargo.lock",
        "gemfile.lock",
        "composer.lock",
    }
)

#: ``requirements*.txt`` files are Python dependency manifests (Req 4.3). Matched
#: by a case-folded prefix + ``.txt`` suffix so ``requirements-dev.txt`` counts.
_REQUIREMENTS_PREFIX: str = "requirements"


def _classify_build_file(rel_path: str) -> str | None:
    """Classify a file as a build/config file kind, or ``None`` if it is not one.

    Resolution is deterministic and case-folded on the basename so casing in the
    path never changes the result. Lockfiles are checked before the generic
    basename table; ``requirements*.txt`` is matched by prefix (Req 4.3).
    """
    base = _basename(rel_path)
    folded = base.casefold()

    if folded in _LOCKFILE_BASENAMES:
        return "lockfile"

    kind = _BUILD_BASENAMES.get(folded)
    if kind is not None:
        return kind

    if folded.startswith(_REQUIREMENTS_PREFIX) and folded.endswith(".txt"):
        return "requirements"

    return None


def detect_build_files(inv: FileInventory) -> tuple[BuildFile, ...]:
    """Detect and classify build/config files over the inventory (Req 4.3).

    Recognizes manifests, makefiles, dockerfiles, lockfiles, and
    ``requirements*.txt`` by basename **at any depth**, so a root ``go.mod`` and a
    nested ``.dagger/go.mod`` are both classified (Req 4.3). Unrecognized files —
    ordinary source, docs — are ignored. The result is sorted by path and is empty
    when nothing matches (Req 4.3, 4.6). Deterministic across runs (Req 9.1).
    """
    found: list[BuildFile] = []
    for entry in inv.entries:
        kind = _classify_build_file(entry.path)
        if kind is not None:
            found.append(BuildFile(path=entry.path, kind=kind))

    found.sort(key=lambda b: b.path)
    return tuple(found)


# --------------------------------------------------------------------------- #
# detect_ci (Req 4.4)                                                          #
# --------------------------------------------------------------------------- #

#: Exact repo-root basenames → CI provider, for single-file CI configs (Req 4.4).
#: Matched case-folded on the basename; ``dagger.json`` marks a Dagger pipeline.
_CI_BASENAMES: dict[str, str] = {
    ".gitlab-ci.yml": "gitlab_ci",
    ".gitlab-ci.yaml": "gitlab_ci",
    ".travis.yml": "other",
    "azure-pipelines.yml": "other",
    "azure-pipelines.yaml": "other",
    "jenkinsfile": "other",
    "dagger.json": "dagger",
}


def _classify_ci(rel_path: str) -> str | None:
    """Classify a path as a CI workflow file → its provider, or ``None``.

    Deterministic, conservative path rules (Req 4.4):

    * any file under ``.github/workflows/`` → ``"github_actions"`` (so a non-
      workflow ``.github`` file like an issue template is **not** matched);
    * any file under ``.circleci/`` → ``"circleci"``;
    * a recognized root-level CI basename (``.gitlab-ci.yml``, ``dagger.json``,
      …) → its mapped provider.
    """
    # Normalize to forward slashes defensively; inventory paths are already POSIX.
    norm = rel_path.replace("\\", "/")

    if norm.startswith(".github/workflows/"):
        return "github_actions"
    if norm.startswith(".circleci/"):
        return "circleci"

    base = _basename(norm).casefold()
    return _CI_BASENAMES.get(base)


def detect_ci(inv: FileInventory) -> tuple[CIWorkflow, ...]:
    """Detect CI/workflow configuration with provider + path (Req 4.4).

    Recognizes GitHub Actions (``.github/workflows/*``), CircleCI
    (``.circleci/*``), GitLab CI, Dagger (``dagger.json``), and a few other
    single-file CI configs. A ``.github`` file that is **not** under
    ``workflows/`` is deliberately not matched, so issue templates and the like do
    not masquerade as CI (Req 4.4). The result is sorted by path and is empty when
    nothing matches (Req 4.4, 4.6). Deterministic across runs (Req 9.1).
    """
    found: list[CIWorkflow] = []
    for entry in inv.entries:
        provider = _classify_ci(entry.path)
        if provider is not None:
            found.append(CIWorkflow(path=entry.path, provider=provider))

    found.sort(key=lambda w: w.path)
    return tuple(found)


# --------------------------------------------------------------------------- #
# detect_tests (Req 4.5, 4.6)  -- task 3.2                                     #
# --------------------------------------------------------------------------- #

#: Conventional directory basenames that, on their own, signal a test area even
#: when the files inside follow no per-file naming convention (Req 4.5). Matched
#: case-folded against any path segment, so ``tests/unit/conftest.py`` counts.
#: Deliberately conservative — only ``test``/``tests``-rooted conventions and the
#: unambiguous ``__tests__`` are listed. Ambiguous names like ``spec``/``specs``
#: are *not* directory signals (they collide with non-test "specifications" dirs,
#: e.g. ``.kiro/specs``); JS/TS ``*.spec.*`` files are still caught per-file
#: (design "keep detection conservative and omit on doubt", Req 5.3 spirit).
_TEST_DIR_BASENAMES: frozenset[str] = frozenset(
    {"test", "tests", "testdata", "__tests__"}
)


def _file_test_framework(rel_path: str) -> str | None:
    """Return the test framework a file's *name* signals, or ``None``.

    Conservative per-language naming conventions only (Req 4.5):

    * Go ``*_test.go`` → ``"go_testing"``;
    * Python ``test_*.py`` / ``*_test.py`` → ``"pytest"`` (the dominant runner;
      stdlib ``unittest`` files share the same naming, so we report the common
      ``pytest`` tag rather than guess a runner that needs deeper inspection);
    * JS/TS ``*.test.{js,jsx,ts,tsx}`` / ``*.spec.{...}`` → ``"jest"``.

    A bare filename merely *containing* ``test`` (e.g. ``contest.go``,
    ``latest.py``) does **not** match — only the established suffix/prefix
    conventions do, so detection produces no noise.
    """
    base = _basename(rel_path)

    # Go: foo_test.go
    if base.endswith("_test.go"):
        return "go_testing"

    # Python: test_foo.py or foo_test.py
    if base.endswith(".py"):
        if base.startswith("test_") or base.endswith("_test.py"):
            return "pytest"

    # JS/TS: foo.test.ts / foo.spec.js (and jsx/tsx)
    for marker in (".test.", ".spec."):
        if marker in base:
            for ext in (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"):
                if base.endswith(ext):
                    return "jest"

    return None


def _test_dir_for(rel_path: str) -> str | None:
    """Return the shallowest enclosing conventional test directory, or ``None``.

    Walks the ancestor directories of ``rel_path`` root-first and returns the first
    whose final segment is a recognized test-directory basename — so a file under
    ``tests/`` reports ``"tests"`` and one under ``tests/unit`` still reports the
    top ``tests`` area. Used so a conventional test directory whose files follow no
    naming convention is still recorded as a representative test path (Req 4.5).
    """
    for directory in _ancestor_dirs(rel_path):
        if directory and _basename(directory).casefold() in _TEST_DIR_BASENAMES:
            return directory
    return None


def detect_tests(inv: FileInventory) -> TestLayout:
    """Detect test presence, frameworks, and representative locations (Req 4.5).

    Combines two deterministic, conservative signals over the inventory:

    * a **per-file naming convention** (Go ``*_test.go``, Python
      ``test_*.py``/``*_test.py``, JS/TS ``*.test.*``/``*.spec.*``) → the matched
      file is a representative test path and contributes its framework;
    * a **conventional test directory** (``tests/``, ``test/``, ``testdata/``,
      ``__tests__/``, ``spec/``, …) → the directory itself is a representative test
      path, so a test tree whose files follow no naming convention is still found.

    The returned :class:`TestLayout` carries ``present`` (true iff any signal
    matched), a sorted-unique ``frameworks`` tuple, and a sorted-unique ``paths``
    tuple of representative files/dirs. When nothing matches it is the stable empty
    layout ``TestLayout(present=False, frameworks=(), paths=())`` rather than
    omitted (Req 4.6). Pure and deterministic across runs (Req 9.1).
    """
    frameworks: set[str] = set()
    paths: set[str] = set()

    for entry in inv.entries:
        framework = _file_test_framework(entry.path)
        if framework is not None:
            frameworks.add(framework)
            paths.add(entry.path)

        test_dir = _test_dir_for(entry.path)
        if test_dir is not None:
            paths.add(test_dir)

    present = bool(paths)
    return TestLayout(
        present=present,
        frameworks=tuple(sorted(frameworks)),
        paths=tuple(sorted(paths)),
    )


# --------------------------------------------------------------------------- #
# extract_dependencies (Req 5.1, 5.6)  -- task 3.2                             #
# --------------------------------------------------------------------------- #
#
# Dependency extraction reads the *contents* of recognized manifest files, which
# the scanner does not carry on FileEntry, so this is the one detector that
# re-reads files from disk. It reads only files the inventory already lists, parses
# them with stdlib parsers (tomllib/json/line-parse), absorbs malformed manifests
# into a "partially parsed" note rather than raising (Req 5.6), and sorts the
# result by (source, name) so two runs are equal (Req 9.1).


#: Marker substring used in the partial-parse note so callers/tests can recognize a
#: manifest that could not be fully parsed (design "partially parsed" marker).
_PARTIAL_PARSE_MARKER: str = "partially parsed"

#: Read cap for a manifest file. Manifests are small; this bounds a pathological
#: file masquerading as one so dependency parsing stays bounded (Req 2.2 spirit).
_MANIFEST_READ_CAP: int = 2_000_000


def _partial_note(source: str, reason: str) -> str:
    """A deterministic, source-naming partial-parse note (Req 5.6)."""
    return f"{_PARTIAL_PARSE_MARKER}: {source} ({reason})"


def _read_manifest_text(repo_path: str, source: str) -> str | None:
    """Read a manifest's text under ``repo_path``, or ``None`` if unreadable.

    Returns ``None`` (the caller records a partial-parse note) when the file is
    missing or cannot be read/decoded — a manifest that vanished between scan and
    parse, or holds non-UTF-8 bytes, never aborts the analysis (Req 5.6).
    """
    abs_path = os.path.join(repo_path, source)
    try:
        with open(abs_path, "rb") as handle:
            raw = handle.read(_MANIFEST_READ_CAP)
    except OSError:
        return None
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _classify_manifest(rel_path: str) -> str | None:
    """Classify a manifest path as a dependency-source kind, or ``None``.

    Recognizes the four manifest families the dependency parser understands, by
    case-folded basename so casing in the path never changes the result (Req 5.1):
    ``"pyproject"``, ``"go_mod"``, ``"requirements"`` (``requirements*.txt``),
    ``"package_json"``. Lockfiles, makefiles, dockerfiles, etc. are *not* parsed
    for declared dependencies and return ``None``.
    """
    folded = _basename(rel_path).casefold()
    if folded == "pyproject.toml":
        return "pyproject"
    if folded == "go.mod":
        return "go_mod"
    if folded == "package.json":
        return "package_json"
    if folded.startswith(_REQUIREMENTS_PREFIX) and folded.endswith(".txt"):
        return "requirements"
    return None


# --- go.mod -------------------------------------------------------------------


def _parse_go_mod(text: str, source: str) -> tuple[list[Dependency], list[str]]:
    """Parse a ``go.mod`` ``require`` block into dependencies (Req 5.1).

    Handles both forms: a parenthesised ``require ( ... )`` block and a single-line
    ``require module v1.2.3``. ``// indirect`` markers are scope-mapped to
    ``"build"`` (transitive) vs ``"runtime"`` (direct). The parse is line-based and
    tolerant: a line it cannot read is skipped rather than aborting (Req 5.6), so a
    go.mod never raises. ``go.mod`` is line-structured rather than a formal grammar
    we depend on, so partial readability is expected, not exceptional — no note is
    emitted unless nothing is structurally parseable.
    """
    deps: list[Dependency] = []
    in_block = False

    for raw_line in text.splitlines():
        # Strip a trailing ``// ...`` comment but remember an ``indirect`` marker.
        indirect = "// indirect" in raw_line
        line = raw_line.split("//", 1)[0].strip()
        if not line:
            continue

        if not in_block:
            if line == "require (":
                in_block = True
                continue
            if line.startswith("require ") or line.startswith("require\t"):
                # Single-line: ``require module version`` (optionally ``require (``
                # handled above). Drop the leading keyword and parse the remainder.
                remainder = line[len("require"):].strip()
                if remainder == "(":  # defensive: ``require  (`` with odd spacing
                    in_block = True
                    continue
                dep = _go_require_line(remainder, source, indirect)
                if dep is not None:
                    deps.append(dep)
            continue

        # Inside a require block.
        if line == ")":
            in_block = False
            continue
        dep = _go_require_line(line, source, indirect)
        if dep is not None:
            deps.append(dep)

    return deps, []


def _go_require_line(spec: str, source: str, indirect: bool) -> Dependency | None:
    """Parse a single ``module version`` requirement, or ``None`` if malformed.

    ``indirect`` (a ``// indirect`` transitive dependency) maps to the ``"build"``
    scope; a direct requirement maps to ``"runtime"``. A version-less or empty
    fragment is skipped (returns ``None``) so a stray line never produces noise.
    """
    parts = spec.split()
    if not parts:
        return None
    name = parts[0]
    version = parts[1] if len(parts) >= 2 else ""
    return Dependency(
        name=name,
        version_spec=version,
        source=source,
        scope="build" if indirect else "runtime",
    )


# --- pyproject.toml -----------------------------------------------------------


def _parse_pyproject(text: str, source: str) -> tuple[list[Dependency], list[str]]:
    """Parse ``pyproject.toml`` dependencies via :mod:`tomllib` (Req 5.1, 5.6).

    Extracts three recognized dependency surfaces:

    * PEP 621 ``[project] dependencies`` → ``"runtime"`` scope;
    * PEP 621 ``[project.optional-dependencies]`` groups → ``"dev"`` scope;
    * Poetry ``[tool.poetry.dependencies]`` → ``"runtime"`` (excluding the
      ``python`` pseudo-constraint) and ``[tool.poetry.group.*.dependencies]`` /
      legacy ``[tool.poetry.dev-dependencies]`` → ``"dev"``.

    A TOML syntax error is absorbed: an empty dependency list and a single
    partial-parse note are returned, never an exception (Req 5.6).
    """
    try:
        data = tomllib.loads(text)
    except (tomllib.TOMLDecodeError, ValueError):
        return [], [_partial_note(source, "invalid TOML")]

    deps: list[Dependency] = []

    project = data.get("project")
    if isinstance(project, dict):
        for raw in _as_str_list(project.get("dependencies")):
            deps.append(_pep508_dependency(raw, source, "runtime"))
        optional = project.get("optional-dependencies")
        if isinstance(optional, dict):
            for group in optional.values():
                for raw in _as_str_list(group):
                    deps.append(_pep508_dependency(raw, source, "dev"))

    poetry = _dig(data, "tool", "poetry")
    if isinstance(poetry, dict):
        runtime = poetry.get("dependencies")
        if isinstance(runtime, dict):
            for name, spec in runtime.items():
                if name.casefold() == "python":
                    continue
                deps.append(
                    Dependency(
                        name=name,
                        version_spec=_poetry_version(spec),
                        source=source,
                        scope="runtime",
                    )
                )
        legacy_dev = poetry.get("dev-dependencies")
        if isinstance(legacy_dev, dict):
            for name, spec in legacy_dev.items():
                deps.append(
                    Dependency(
                        name=name,
                        version_spec=_poetry_version(spec),
                        source=source,
                        scope="dev",
                    )
                )
        groups = poetry.get("group")
        if isinstance(groups, dict):
            for group in groups.values():
                group_deps = group.get("dependencies") if isinstance(group, dict) else None
                if isinstance(group_deps, dict):
                    for name, spec in group_deps.items():
                        if name.casefold() == "python":
                            continue
                        deps.append(
                            Dependency(
                                name=name,
                                version_spec=_poetry_version(spec),
                                source=source,
                                scope="dev",
                            )
                        )

    return deps, []


def _poetry_version(spec: object) -> str:
    """Render a Poetry version constraint (a string or a ``{version=...}`` table)."""
    if isinstance(spec, str):
        return spec
    if isinstance(spec, dict):
        version = spec.get("version")
        if isinstance(version, str):
            return version
    return ""


# --- requirements*.txt --------------------------------------------------------


def _parse_requirements(text: str, source: str) -> tuple[list[Dependency], list[str]]:
    """Parse a ``requirements*.txt`` file line by line (Req 5.1).

    Skips blank lines, ``#`` comments, and option lines (``-r``/``-e``/``--*``).
    Each remaining line is a PEP 508 requirement; its scope is ``"dev"`` when the
    filename signals a dev set (``requirements-dev.txt`` / ``requirements-test.txt``)
    and ``"runtime"`` otherwise. A requirements file is plain text, so there is no
    "syntax error" to absorb — unreadable lines are simply skipped.
    """
    folded = _basename(source).casefold()
    scope = "dev" if ("dev" in folded or "test" in folded) else "runtime"

    deps: list[Dependency] = []
    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("-") or line.startswith("--"):
            continue  # -r include / -e editable / --option lines are not deps
        deps.append(_pep508_dependency(line, source, scope))
    return deps, []


# --- package.json -------------------------------------------------------------


def _parse_package_json(text: str, source: str) -> tuple[list[Dependency], list[str]]:
    """Parse ``package.json`` dependency maps via :mod:`json` (Req 5.1, 5.6).

    Reads ``dependencies`` → ``"runtime"``, ``devDependencies`` → ``"dev"``, and
    ``peerDependencies``/``optionalDependencies`` → ``"runtime"``. A JSON syntax
    error is absorbed into a single partial-parse note rather than raising
    (Req 5.6).
    """
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return [], [_partial_note(source, "invalid JSON")]
    if not isinstance(data, dict):
        return [], [_partial_note(source, "manifest is not a JSON object")]

    deps: list[Dependency] = []
    for key, scope in (
        ("dependencies", "runtime"),
        ("devDependencies", "dev"),
        ("peerDependencies", "runtime"),
        ("optionalDependencies", "runtime"),
    ):
        section = data.get(key)
        if isinstance(section, dict):
            for name, version in section.items():
                deps.append(
                    Dependency(
                        name=name,
                        version_spec=version if isinstance(version, str) else "",
                        source=source,
                        scope=scope,
                    )
                )
    return deps, []


# --- shared parse helpers -----------------------------------------------------


def _as_str_list(value: object) -> list[str]:
    """Return ``value`` as a list of strings (an empty list for anything else)."""
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str)]
    return []


def _dig(data: object, *keys: str) -> object | None:
    """Walk nested dicts by ``keys``, returning ``None`` on any missing/non-dict."""
    current: object = data
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


#: Characters that begin a PEP 508 version constraint / extras / marker, used to
#: split a requirement string into its bare distribution name and version spec.
_PEP508_VERSION_CHARS: str = "=<>!~ ([;@"


def _pep508_dependency(raw: str, source: str, scope: str) -> Dependency:
    """Split a PEP 508 requirement string into a :class:`Dependency` (Req 5.1).

    Splits at the first version/extras/marker character so ``requests>=2.0`` →
    name ``requests`` + spec ``>=2.0`` and a bare ``ruff`` → name ``ruff`` + empty
    spec. Extras (``pkg[extra]``) and environment markers are folded into the raw
    version spec rather than dropped, keeping the declaration faithful without deep
    parsing. The split is deterministic.
    """
    text = raw.strip()
    split_at = len(text)
    for index, char in enumerate(text):
        if char in _PEP508_VERSION_CHARS:
            split_at = index
            break
    name = text[:split_at].strip()
    version_spec = text[split_at:].strip()
    return Dependency(
        name=name,
        version_spec=version_spec,
        source=source,
        scope=scope,
    )


#: Manifest kind → its parser. Each parser returns ``(deps, notes)`` and never
#: raises; a malformed manifest yields a partial-parse note instead (Req 5.6).
_MANIFEST_PARSERS = {
    "go_mod": _parse_go_mod,
    "pyproject": _parse_pyproject,
    "requirements": _parse_requirements,
    "package_json": _parse_package_json,
}


def extract_dependencies_with_notes(
    inv: FileInventory, repo_path: str
) -> tuple[tuple[Dependency, ...], tuple[str, ...]]:
    """Parse declared dependencies and return them with partial-parse notes.

    The work behind :func:`extract_dependencies`, additionally surfacing the
    "partially parsed" notes (sorted, deduplicated) so the analyzer (task 4.1) can
    fold them into :attr:`ScanStats.notes` (Req 5.6) — the model record the
    detectors cannot write to directly.

    For every recognized manifest the inventory lists (``pyproject.toml``,
    ``go.mod``, ``requirements*.txt``, ``package.json``, including nested
    sub-project copies), the manifest's text is re-read under ``repo_path`` and
    parsed with the appropriate stdlib parser. A missing/unreadable manifest or a
    malformed one records a partial-parse note and contributes whatever was
    extractable rather than aborting (Req 5.6). The dependency tuple is sorted by
    ``(source, name)`` and the notes tuple is sorted, so two runs over an unchanged
    tree are equal (Req 5.1, 9.1).
    """
    deps: list[Dependency] = []
    notes: set[str] = set()

    for entry in inv.entries:
        kind = _classify_manifest(entry.path)
        if kind is None:
            continue

        text = _read_manifest_text(repo_path, entry.path)
        if text is None:
            notes.add(_partial_note(entry.path, "could not read manifest"))
            continue

        parser = _MANIFEST_PARSERS[kind]
        parsed, parse_notes = parser(text, entry.path)
        deps.extend(parsed)
        notes.update(parse_notes)

    deps.sort(key=lambda d: (d.source, d.name, d.scope, d.version_spec))
    return tuple(deps), tuple(sorted(notes))


def extract_dependencies(
    inv: FileInventory, repo_path: str
) -> tuple[Dependency, ...]:
    """Extract declared dependencies from recognized manifests (Req 5.1, 5.6).

    The pinned, planner-facing seam: the notes-dropping public form of
    :func:`extract_dependencies_with_notes`. Reads ``pyproject.toml``, ``go.mod``,
    ``requirements*.txt``, and ``package.json`` (including nested sub-project
    manifests) under ``repo_path``, recording each dependency with its ``name``,
    raw ``version_spec``, source manifest path, and ``scope``
    (``runtime``/``dev``/``build``/``unknown``). A malformed or partially-parseable
    manifest yields what is extractable and never aborts (Req 5.6). The result is
    sorted by ``(source, name)`` and empty when there are no recognized manifests
    (Req 5.1, 4.6). Deterministic across runs (Req 9.1).
    """
    deps, _notes = extract_dependencies_with_notes(inv, repo_path)
    return deps


# --------------------------------------------------------------------------- #
# map_components (Req 5.2)  -- task 3.3                                         #
# --------------------------------------------------------------------------- #
#
# A component is a code-bearing package directory derived purely from the
# directory/package structure of the inventory — no contents are read. Each
# component carries the directory path, a name (the directory basename, or a
# stable fallback for the repo root), and a small, sorted representative-file set
# (Req 5.2). Detection is conservative: only directories that *directly* contain a
# source-code file become components, so pure docs/config/test directories are not
# mistaken for code modules. Output is sorted by path so the analyzer never
# re-sorts and two runs over an unchanged inventory are equal (Req 9.1).

#: How many representative files a component carries at most (design "small set").
_MAX_REPRESENTATIVE_FILES: int = 5

#: Name used for the repo-root component (path ``""``) so it carries a non-empty,
#: stable :attr:`Component.name` rather than the empty directory path (Req 5.2).
_ROOT_COMPONENT_NAME: str = "root"


def map_components(inv: FileInventory) -> tuple[Component, ...]:
    """Derive a component/module map from the directory/package structure (Req 5.2).

    A *component* is a directory that **directly** contains at least one
    source-code file (a file whose coarse language is a recognized source
    language; see :data:`_SOURCE_LANGUAGES`). This is deliberately conservative: a
    pure ``docs/`` or ``config/`` directory is not a code module and is omitted, so
    the map describes the project's code units rather than every directory (Req 5.2;
    cf. the broader per-directory summary in :func:`summarize_structure`). The repo
    root (path ``""``) becomes a component when it directly holds top-level code
    (e.g. a Go ``main.go``).

    Each :class:`Component` carries:

    * ``path`` — the repo-relative directory path (``""`` for the root);
    * ``name`` — the directory basename, or :data:`_ROOT_COMPONENT_NAME` for the
      root so the name is never empty;
    * ``representative_files`` — a small (``<= _MAX_REPRESENTATIVE_FILES``), sorted
      set of the component's directly-contained source files, so the planner can
      sample a unit without re-reading the tree.

    The result is sorted by ``path`` and is empty when no code-bearing directory
    exists (Req 5.2, 4.6). Pure and deterministic across runs (Req 9.1).
    """
    # Collect, per directory, the source files it *directly* contains (sorted).
    direct_source: dict[str, list[str]] = {}
    for entry in inv.entries:
        if entry.language not in _SOURCE_LANGUAGES:
            continue
        directory = _dir_of(entry.path)
        direct_source.setdefault(directory, []).append(entry.path)

    components: list[Component] = []
    for directory in sorted(direct_source):
        files = sorted(direct_source[directory])
        name = _basename(directory) if directory else _ROOT_COMPONENT_NAME
        components.append(
            Component(
                name=name,
                path=directory,
                representative_files=tuple(files[:_MAX_REPRESENTATIVE_FILES]),
            )
        )
    return tuple(components)


# --------------------------------------------------------------------------- #
# detect_public_surface (Req 5.3)  -- task 3.3                                 #
# --------------------------------------------------------------------------- #
#
# Public-surface detection is intentionally lightweight: it reads the contents of
# recognized source files (the one other detector beyond extract_dependencies that
# re-reads files, since the scanner does not carry file bodies) and applies shallow
# regexes for CLI flags/subcommands and exported symbols. Anything that would need
# a real parser, type resolution, or cross-file analysis is omitted — detection is
# conservative and "omits on doubt" (design Req 5.3). Every output is sorted by
# (source, kind, name) so two runs are equal (Req 9.1).

#: Read cap for a source file scanned for public surface. Source files are small;
#: this bounds a pathological file so surface detection stays bounded (Req 2.2).
_SOURCE_READ_CAP: int = 2_000_000

#: Go func/type/CLI prefixes that must NEVER be reported as public surface even
#: though they are exported (capitalized): test/benchmark/example/fuzz harness
#: entrypoints declared in ``*_test.go`` (and occasionally elsewhere) are not real
#: API. Combined with skipping ``*_test.go`` files entirely, this keeps Go surface
#: free of test noise (design "keep detection conservative", Req 5.3).
_GO_NON_API_PREFIXES: tuple[str, ...] = ("Test", "Benchmark", "Example", "Fuzz")

#: A Go top-level ``func Name(`` / ``type Name `` / ``type Name(`` with a
#: capitalized (exported) name. Anchored at line start so method receivers
#: (``func (r *T) M()``) and indented declarations are not matched.
_GO_EXPORTED_RE = re.compile(
    r"^(?:func|type)\s+([A-Z][A-Za-z0-9_]*)\b", re.MULTILINE
)

#: A Go cobra/pflag/flag flag declaration's flag name, e.g.
#: ``BoolVar(&x, "json", ...)`` or ``flag.String("verbose", ...)``. We capture the
#: double-quoted name that follows a recognized flag-registration call. Shallow by
#: design: it never parses the surrounding expression.
_GO_FLAG_RE = re.compile(
    r"\.(?:Bool|Int|Int64|Uint|Uint64|Float64|String|StringArray|StringSlice|Duration|Count)"
    r"(?:Var|VarP|P)?\s*\(\s*(?:&[A-Za-z_][A-Za-z0-9_.]*\s*,\s*)?\"([A-Za-z][A-Za-z0-9_-]*)\""
)

#: A Python ``argparse`` flag: ``add_argument("--name"...)`` capturing the first
#: long option. Only ``--`` long flags are taken (a positional/short flag needs
#: more context to name meaningfully), keeping detection conservative.
_PY_FLAG_RE = re.compile(
    r"\.add_argument\(\s*[\"'](--[A-Za-z][A-Za-z0-9_-]*)[\"']"
)

#: A Python ``argparse`` subcommand: ``add_parser("name"...)`` capturing the name.
_PY_SUBCMD_RE = re.compile(r"\.add_parser\(\s*[\"']([A-Za-z][A-Za-z0-9_-]*)[\"']")

#: A Python ``__all__`` assignment's bracketed body, captured greedily across
#: lines so a multi-line list is read in full; individual names are then pulled
#: from the body. Only the literal-list form is supported (conservative).
_PY_ALL_RE = re.compile(r"^__all__\s*(?::[^=]+)?=\s*[\(\[](.*?)[\)\]]", re.DOTALL | re.MULTILINE)

#: A quoted name inside an ``__all__`` body.
_PY_ALL_NAME_RE = re.compile(r"[\"']([A-Za-z_][A-Za-z0-9_]*)[\"']")


def _read_source_text(repo_path: str, source: str) -> str | None:
    """Read a source file's text under ``repo_path``, or ``None`` if unreadable.

    Mirrors :func:`_read_manifest_text`: a missing/unreadable/non-UTF-8 file yields
    ``None`` (the caller skips it) so a file that vanished between scan and parse, or
    holds odd bytes, never aborts surface detection (Req 5.3 spirit).
    """
    abs_path = os.path.join(repo_path, source)
    try:
        with open(abs_path, "rb") as handle:
            raw = handle.read(_SOURCE_READ_CAP)
    except OSError:
        return None
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _go_public_symbols(text: str, source: str) -> list[PublicSymbol]:
    """Shallow Go exported-symbol + flag extraction for one ``.go`` file (Req 5.3).

    Exported symbols are capitalized top-level ``func``/``type`` declarations
    (method receivers and indented declarations are excluded by the line anchor),
    minus the test/benchmark/example/fuzz harness prefixes which are never real API.
    CLI flags are double-quoted names in recognized cobra/pflag/``flag`` registration
    calls. No deeper parsing is attempted (design Req 5.3).
    """
    found: list[PublicSymbol] = []
    for name in _GO_EXPORTED_RE.findall(text):
        if name.startswith(_GO_NON_API_PREFIXES):
            continue
        found.append(PublicSymbol(name=name, kind="exported_symbol", source=source))
    for flag in _GO_FLAG_RE.findall(text):
        found.append(PublicSymbol(name=flag, kind="cli_flag", source=source))
    return found


def _python_public_symbols(text: str, source: str) -> list[PublicSymbol]:
    """Shallow Python public-surface extraction for one ``.py`` file (Req 5.3).

    Exported symbols come only from an explicit ``__all__`` literal list (the cheap,
    unambiguous public-API marker); module-level defs without ``__all__`` are *not*
    guessed (conservative, Req 5.3). CLI flags/subcommands come from ``argparse``
    ``add_argument("--flag")`` / ``add_parser("name")`` calls. No import resolution
    or AST walk is performed.
    """
    found: list[PublicSymbol] = []
    for body in _PY_ALL_RE.findall(text):
        for name in _PY_ALL_NAME_RE.findall(body):
            found.append(
                PublicSymbol(name=name, kind="exported_symbol", source=source)
            )
    for flag in _PY_FLAG_RE.findall(text):
        found.append(PublicSymbol(name=flag, kind="cli_flag", source=source))
    for subcmd in _PY_SUBCMD_RE.findall(text):
        found.append(
            PublicSymbol(name=subcmd, kind="cli_subcommand", source=source)
        )
    return found


def detect_public_surface(
    inv: FileInventory, repo_path: str
) -> tuple[PublicSymbol, ...]:
    """Capture cheaply-detectable public surface signals (Req 5.3).

    Reads the contents of recognized source files the inventory lists (Go ``.go``
    excluding ``*_test.go``; Python ``.py``) under ``repo_path`` and applies shallow
    regexes for:

    * **CLI flags** — Go cobra/pflag/``flag`` registration calls and Python
      ``argparse`` ``add_argument("--flag")`` (``kind="cli_flag"``);
    * **CLI subcommands** — Python ``argparse`` ``add_parser("name")``
      (``kind="cli_subcommand"``);
    * **exported symbols** — Go capitalized top-level ``func``/``type`` (minus the
      test/benchmark/example/fuzz harness names) and Python ``__all__`` entries
      (``kind="exported_symbol"``).

    Anything that would need a real parser, type inference, or cross-file resolution
    is deliberately omitted — detection is conservative and omits on doubt (Req 5.3).
    Binary files, ``*_test.go`` test files, and unreadable/missing files are skipped
    without error. The result is sorted by ``(source, kind, name)`` and deduplicated,
    and is empty when nothing matches (Req 5.3, 4.6). Deterministic across runs
    (Req 9.1).
    """
    found: set[PublicSymbol] = set()

    for entry in inv.entries:
        if entry.is_binary or entry.read_truncated:
            continue

        base = _basename(entry.path)
        if base.endswith("_test.go"):
            continue  # test harness symbols are not public surface

        if base.endswith(".go"):
            extractor = _go_public_symbols
        elif base.endswith(".py") or base.endswith(".pyi"):
            extractor = _python_public_symbols
        else:
            continue

        text = _read_source_text(repo_path, entry.path)
        if text is None:
            continue
        found.update(extractor(text, entry.path))

    return tuple(
        sorted(found, key=lambda s: (s.source, s.kind, s.name))
    )


# --------------------------------------------------------------------------- #
# detect_docs (Req 5.4)  -- task 3.3                                           #
# --------------------------------------------------------------------------- #

#: Doc directory basenames that signal a documentation area (matched case-folded
#: against any path segment, so ``project/docs/api`` counts) (Req 5.4).
_DOC_DIR_BASENAMES: frozenset[str] = frozenset({"doc", "docs"})

#: Recognized standalone documentation filenames (case-folded basename), beyond
#: READMEs, recorded under ``other_docs`` (Req 5.4). Conservative: only
#: well-established project-doc conventions.
_OTHER_DOC_BASENAMES: frozenset[str] = frozenset(
    {
        "contributing",
        "changelog",
        "changes",
        "history",
        "authors",
        "code_of_conduct",
        "security",
        "support",
        "maintainers",
        "notice",
    }
)

#: Documentation file extensions used to recognize a markup doc file by suffix.
_DOC_EXTENSIONS: tuple[str, ...] = (".md", ".markdown", ".rst", ".txt", ".adoc")


def _is_readme(rel_path: str) -> bool:
    """True when a file's basename is a README in any recognized form (Req 5.4).

    Matches ``README`` with or without a doc extension (``README``, ``README.md``,
    ``README.rst``, ``readme.txt``, …), case-folded. Conservative: a file merely
    *containing* ``readme`` mid-name does not match.
    """
    folded = _basename(rel_path).casefold()
    if folded == "readme":
        return True
    if folded.startswith("readme."):
        stem_ext = folded[len("readme"):]
        return stem_ext in _DOC_EXTENSIONS
    return False


def _other_doc_basename(rel_path: str) -> bool:
    """True when a file is a recognized standalone doc (CONTRIBUTING, …) (Req 5.4).

    Matches the case-folded basename with or without a doc extension, so both
    ``CONTRIBUTING`` and ``CONTRIBUTING.md`` count. READMEs are handled separately by
    :func:`_is_readme` and are not reported here.
    """
    folded = _basename(rel_path).casefold()
    stem = folded
    for ext in _DOC_EXTENSIONS:
        if folded.endswith(ext):
            stem = folded[: -len(ext)]
            break
    return stem in _OTHER_DOC_BASENAMES


def detect_docs(inv: FileInventory) -> DocPresence:
    """Record documentation presence over the inventory (Req 5.4).

    Produces a :class:`DocPresence` with three deterministic, conservative signals:

    * ``has_readme`` / ``readme_paths`` — any ``README`` file (with or without a doc
      extension, at any depth), sorted;
    * ``doc_dirs`` — repo-relative directories whose final segment is ``doc``/
      ``docs``, sorted-unique;
    * ``other_docs`` — recognized standalone docs (``CONTRIBUTING``, ``CHANGELOG``,
      ``SECURITY``, …), sorted, excluding READMEs.

    When nothing matches it is the stable empty presence
    ``DocPresence(has_readme=False, readme_paths=(), doc_dirs=(), other_docs=())``
    rather than omitted (Req 4.6). Pure and deterministic across runs (Req 9.1).
    """
    readme_paths: set[str] = set()
    doc_dirs: set[str] = set()
    other_docs: set[str] = set()

    for entry in inv.entries:
        if _is_readme(entry.path):
            readme_paths.add(entry.path)
        elif _other_doc_basename(entry.path):
            other_docs.add(entry.path)

        for directory in _ancestor_dirs(entry.path):
            if directory and _basename(directory).casefold() in _DOC_DIR_BASENAMES:
                doc_dirs.add(directory)

    return DocPresence(
        has_readme=bool(readme_paths),
        readme_paths=tuple(sorted(readme_paths)),
        doc_dirs=tuple(sorted(doc_dirs)),
        other_docs=tuple(sorted(other_docs)),
    )


# --------------------------------------------------------------------------- #
# detect_artifacts (Req 5.5)  -- task 3.3                                      #
# --------------------------------------------------------------------------- #

#: License filename stems (case-folded, with or without a doc extension) → the
#: ``"license"`` artifact kind (Req 5.5).
_LICENSE_STEMS: frozenset[str] = frozenset(
    {"license", "licence", "copying", "copyright", "unlicense"}
)

#: Schema/spec filename suffixes → the ``"schema"`` artifact kind (Req 5.5).
_SCHEMA_SUFFIXES: tuple[str, ...] = (
    ".proto",
    ".graphql",
    ".gql",
    ".avsc",
    ".xsd",
    ".thrift",
)

#: Schema/spec filename markers (substring, case-folded) → ``"schema"`` (Req 5.5).
#: Catches ``openapi.yaml``, ``swagger.json``, ``*.schema.json``, ``jsonschema`` etc.
_SCHEMA_MARKERS: tuple[str, ...] = (
    "openapi",
    "swagger",
    ".schema.",
    "json-schema",
    "jsonschema",
)

#: Generated-output filename markers (substring, case-folded) → ``"generated"``
#: (Req 5.5). Catches protobuf/grpc Go stubs (``*.pb.go``, ``*_grpc.pb.go``) and the
#: common ``*_generated.*`` / ``*.gen.*`` / ``*.generated.*`` conventions.
_GENERATED_MARKERS: tuple[str, ...] = (
    ".pb.go",
    ".pb.cc",
    ".pb.h",
    "_pb2.py",
    "_generated.",
    ".generated.",
    ".gen.",
    "_gen.",
)


def _classify_artifact(rel_path: str) -> str | None:
    """Classify a file as a notable artifact kind, or ``None`` (Req 5.5).

    Resolution is deterministic and conservative, checked in a fixed order so a file
    matching more than one rule gets a single stable kind:

    1. a license filename → ``"license"``;
    2. a Dockerfile → ``"dockerfile"``;
    3. a generated-output marker → ``"generated"``;
    4. a schema/spec suffix or marker → ``"schema"``.

    Ordinary source/docs/config files return ``None`` and are not artifacts.
    """
    base = _basename(rel_path)
    folded = base.casefold()

    # 1. License (LICENSE, LICENSE.md, COPYING, …).
    stem = folded
    for ext in _DOC_EXTENSIONS:
        if folded.endswith(ext):
            stem = folded[: -len(ext)]
            break
    if stem in _LICENSE_STEMS:
        return "license"

    # 2. Dockerfile (``Dockerfile``, ``Dockerfile.prod``, ``api.dockerfile``).
    if folded == "dockerfile" or folded.startswith("dockerfile.") or folded.endswith(
        ".dockerfile"
    ):
        return "dockerfile"

    # 3. Generated output (checked before schema so a generated ``.pb.go`` reads as
    #    generated rather than schema).
    for marker in _GENERATED_MARKERS:
        if marker in folded:
            return "generated"

    # 4. Schema / spec. A bare ``schema.<ext>`` basename is itself a strong signal.
    for suffix in _SCHEMA_SUFFIXES:
        if folded.endswith(suffix):
            return "schema"
    for marker in _SCHEMA_MARKERS:
        if marker in folded:
            return "schema"
    if folded == "schema" or folded.startswith("schema."):
        return "schema"

    return None


def detect_artifacts(inv: FileInventory) -> tuple[Artifact, ...]:
    """Detect notable artifacts by filename/pattern (Req 5.5).

    Recognizes, by basename/suffix/marker at any depth, license files, Dockerfiles,
    generated-output files (``*.pb.go``, ``*_generated.*``, …), and schema/spec files
    (``*.proto``, ``openapi.yaml``, ``*.schema.json``, …). Each match becomes an
    :class:`Artifact` with its repo-relative path and a single stable kind from
    :func:`_classify_artifact`. Ordinary source/docs/config files are ignored. The
    result is sorted by ``path`` and is empty when nothing matches (Req 5.5, 4.6).
    Pure and deterministic across runs (Req 9.1).
    """
    found: list[Artifact] = []
    for entry in inv.entries:
        kind = _classify_artifact(entry.path)
        if kind is not None:
            found.append(Artifact(path=entry.path, kind=kind))

    found.sort(key=lambda a: a.path)
    return tuple(found)
