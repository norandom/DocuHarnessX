"""Deterministic language detection and LOC aggregation (task 2.2).

This module is the pure, model-free *language layer* of the analysis core. It
maps a repo-relative path to a canonical language name and aggregates per-language
file counts and total lines of code into the frozen :class:`LanguageStat` records
the analyzer composes into :class:`RepoAnalysis` (design "languages — language
detection and LOC mapping"; Req 3.1–3.5).

Two pure functions make up the surface:

* :func:`detect_language` — an extension-and-special-filename rule set mapping a
  path string to a canonical language (e.g. ``main.go -> "Go"``,
  ``README.md -> "Markdown"``, ``Dockerfile -> "Dockerfile"``). Anything not in
  the table — unknown extensions, extensionless files, dotfiles, empty paths —
  falls back to ``"Other"`` so no file is ever dropped from the totals
  (Req 3.1, 3.4).
* :func:`aggregate_languages` — folds an iterable of file entries (anything
  exposing ``.language`` and ``.loc``) into per-language ``(files, loc)`` counters,
  emitting a :class:`LanguageStat` tuple sorted **by LOC descending then language
  name ascending**, plus the *primary* language(s) — those tied for the greatest
  LOC — sorted ascending (Req 3.2, 3.3).

Determinism is by construction (Req 3.5): the language table is a frozen mapping,
extension lookup is case-folded, the aggregation totals are independent of input
order, and every returned collection carries a total ordering with a stable
tie-break. Two runs over the same entries therefore yield equal results.

The layer is deliberately decoupled from the scanner: the design has ``scanner``
depend on ``languages`` (not the reverse), so :func:`aggregate_languages` consumes
any object exposing ``.language``/``.loc`` via the structural :class:`_LangEntry`
protocol rather than importing the scanner's ``FileEntry``. This keeps the
language layer importable and testable on its own while the scanner is built.
"""

from __future__ import annotations

import os
from typing import Iterable, Protocol, runtime_checkable

from docuharnessx.analysis.model import LanguageStat

__all__ = [
    "detect_language",
    "aggregate_languages",
    "OTHER_LANGUAGE",
]

#: Canonical bucket for files whose language cannot be determined (Req 3.4). A
#: single shared constant so detection and aggregation agree on the fallback name.
OTHER_LANGUAGE: str = "Other"


@runtime_checkable
class _LangEntry(Protocol):
    """The minimal shape :func:`aggregate_languages` consumes.

    The scanner's ``FileEntry`` satisfies this structurally, but the language
    layer never imports it — it only needs the already-detected ``language`` tag
    and the file's line count. Keeping the dependency this thin is what lets the
    scanner depend on languages without a cycle (design "scanner depends on
    languages, not the reverse").
    """

    language: str
    loc: int


# --------------------------------------------------------------------------- #
# Detection tables (frozen, deterministic)                                     #
# --------------------------------------------------------------------------- #
# Lowercase extension (without the leading dot) -> canonical language name. The
# keys are case-folded at lookup so casing in the path never changes the result
# (Req 3.5). Values are the canonical names that flow into LanguageStat.language
# and ultimately RepoAnalysis.languages / primary_languages.

_EXTENSION_LANGUAGES: dict[str, str] = {
    # Source languages
    "go": "Go",
    "py": "Python",
    "pyi": "Python",
    "ts": "TypeScript",
    "tsx": "TypeScript",
    "js": "JavaScript",
    "jsx": "JavaScript",
    "mjs": "JavaScript",
    "cjs": "JavaScript",
    "rs": "Rust",
    "java": "Java",
    "kt": "Kotlin",
    "kts": "Kotlin",
    "rb": "Ruby",
    "php": "PHP",
    "c": "C",
    "h": "C",
    "cc": "C++",
    "cpp": "C++",
    "cxx": "C++",
    "hpp": "C++",
    "hh": "C++",
    "cs": "C#",
    "swift": "Swift",
    "scala": "Scala",
    "sh": "Shell",
    "bash": "Shell",
    "zsh": "Shell",
    # Markup / docs / config
    "md": "Markdown",
    "markdown": "Markdown",
    "rst": "reStructuredText",
    "txt": "Text",
    "html": "HTML",
    "htm": "HTML",
    "css": "CSS",
    "scss": "CSS",
    "json": "JSON",
    "yml": "YAML",
    "yaml": "YAML",
    "toml": "TOML",
    "ini": "INI",
    "cfg": "INI",
    "xml": "XML",
    "sql": "SQL",
}

# Exact filename (basename) -> canonical language name. Recognized regardless of
# the directory the file sits in, so nested sub-project manifests (e.g. a nested
# ``go.mod``) classify the same as a top-level one (Req 3.1). Matched case-folded.
# NOTE: the special-filename canonical names here intentionally match the coarse
# tags the task-2.1 scanner already carries on ``FileEntry.language`` (``GoMod``,
# ``GoSum``, ``Makefile``, ``Dockerfile``). The scanner is the lower layer that
# populates the language tag; aggregating by an identical vocabulary keeps a single
# canonical name across the layers so the analyzer (task 4.1) never sees two names
# for the same bucket. Extension-based names below already match the scanner table.
_SPECIAL_FILENAMES: dict[str, str] = {
    "makefile": "Makefile",
    "gnumakefile": "Makefile",
    "dockerfile": "Dockerfile",
    "go.mod": "GoMod",
    "go.sum": "GoSum",
    "cmakelists.txt": "CMake",
}


# --------------------------------------------------------------------------- #
# detect_language                                                              #
# --------------------------------------------------------------------------- #


def detect_language(rel_path: str) -> str:
    """Map a repo-relative path to a canonical language name (Req 3.1, 3.4).

    Resolution order is deterministic:

    1. The basename is matched (case-folded) against the special-filename table,
       so extensionless manifests like ``Makefile``, ``Dockerfile``, and
       ``go.mod`` are recognized first.
    2. Otherwise the final extension is matched (case-folded) against the
       extension table.
    3. Anything unmatched — unknown extension, extensionless non-special file,
       dotfile, or empty/`"."`-only path — falls back to :data:`OTHER_LANGUAGE`
       (``"Other"``) so the file is still counted, never dropped (Req 3.4).

    The function is a pure function of the path string with no filesystem access,
    so it is safe to call on inventory entries and is identical across runs
    (Req 3.5).
    """
    # ``os.path.basename`` is the deterministic, POSIX-consistent way to take the
    # final path component for both "a/b/c.go" and bare "c.go".
    name = os.path.basename(rel_path)

    # 1) Special filenames (case-folded exact match on the basename).
    special = _SPECIAL_FILENAMES.get(name.casefold())
    if special is not None:
        return special

    # 2) Extension match. ``os.path.splitext`` treats a leading-dot name with no
    # further dot (e.g. ".gitignore") as all-stem/empty-extension, so dotfiles do
    # not accidentally map via their "extension" — they fall through to "Other".
    _stem, ext = os.path.splitext(name)
    if ext:
        # ext includes the leading dot; strip it and case-fold for the lookup.
        language = _EXTENSION_LANGUAGES.get(ext[1:].casefold())
        if language is not None:
            return language

    # 3) Unknown / extensionless / dotfile / empty -> "Other" (Req 3.4).
    return OTHER_LANGUAGE


# --------------------------------------------------------------------------- #
# aggregate_languages                                                          #
# --------------------------------------------------------------------------- #


def aggregate_languages(
    entries: Iterable[_LangEntry],
) -> tuple[tuple[LanguageStat, ...], tuple[str, ...]]:
    """Aggregate per-language file counts + LOC, with the primary language(s).

    Folds ``entries`` (anything exposing ``.language`` and ``.loc``) into one
    counter per language — file count and summed LOC — and returns a 2-tuple:

    * ``stats``: a ``tuple[LanguageStat, ...]`` sorted by **LOC descending, then
      language name ascending** (the order :class:`RepoAnalysis.languages`
      documents). The tie-break makes the order total and deterministic so two
      runs over the same entries are equal (Req 3.2, 3.5).
    * ``primary``: a ``tuple[str, ...]`` of the language(s) tied for the greatest
      LOC, sorted ascending (Req 3.3). The comparison is on **LOC**, not file
      count, so a project with many docs files but a higher-LOC source language
      reports the source language as primary. Empty when there are no entries; a
      max LOC of ``0`` (only zero-LOC files) yields all such languages as the
      degenerate primaries rather than raising.

    Pure and order-independent: callers may pass the inventory in any order and
    get the same result (Req 3.5). No model, no I/O.
    """
    # Accumulate (files, loc) per language. Plain dict insertion order is never
    # relied upon — every output is explicitly sorted below — so accumulation
    # order does not affect the result.
    files_by_lang: dict[str, int] = {}
    loc_by_lang: dict[str, int] = {}
    for entry in entries:
        language = entry.language
        files_by_lang[language] = files_by_lang.get(language, 0) + 1
        loc_by_lang[language] = loc_by_lang.get(language, 0) + int(entry.loc)

    if not files_by_lang:
        return (), ()

    # Sort by LOC desc, then language name asc. Using -loc as the primary key with
    # the name as the secondary key gives a single, total, stable ordering.
    stats = tuple(
        LanguageStat(
            language=language,
            files=files_by_lang[language],
            loc=loc_by_lang[language],
        )
        for language in sorted(
            files_by_lang, key=lambda lang: (-loc_by_lang[lang], lang)
        )
    )

    # Primary = all languages tied for the greatest LOC, sorted ascending. Compare
    # on LOC (not files) so higher-LOC source beats more-numerous docs (Req 3.3).
    max_loc = max(loc_by_lang.values())
    primary = tuple(
        sorted(lang for lang, loc in loc_by_lang.items() if loc == max_loc)
    )

    return stats, primary
