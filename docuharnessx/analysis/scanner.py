"""The bounded, deterministic repository scanner (task 2.1).

``docuharnessx.analysis.scanner`` walks a target repository on local disk into a
bounded, classified, deterministically-sorted :class:`FileInventory` — the
repo-shaped input the Analyze stage's detectors and language aggregation consume
(design "scanner — repository walk and inventory"; Req 1.3-1.7, 2.1-2.5). It is
pure, model-free, stdlib-only, and harness-free: the only model type it touches is
the frozen :class:`~docuharnessx.analysis.model.ScanStats` it carries on the
inventory (the shared scan-counters seam).

What the scan produces, per retained file (a :class:`FileEntry`):

* the repo-relative **POSIX** path (forward slashes regardless of platform),
* the byte **size**,
* a **binary-vs-text** classification from a bounded head sample (Req 2.1),
* a coarse **language/file-type tag** (``"Other"`` when unknown; the canonical
  per-language aggregation is task 2.2's ``languages`` module),
* the **line count** for in-cap text files (``0`` for binary or over-cap files),
* a **read-truncated** flag set when the file exceeds the per-file read cap.

Determinism by construction (Req 1.6, 9.1): the walk sorts directory and file
names at every level, the final ``entries`` tuple is sorted by path, and every
scan note is sorted — so two scans of an unchanged tree produce equal inventories.

Boundedness and resilience (Req 2.2, 2.3, 1.5): a per-file read cap, a total-file
cap, and a total-byte cap each stop adding further detail and mark
``stats.limit_reached`` with a note while still returning a well-formed inventory;
unreadable entries are counted in ``stats.files_skipped`` and noted, never raised;
noise directories are excluded without descending; symlinks are never followed out
of the repo root (``os.walk(followlinks=False)`` plus a realpath-within-root guard).

The scanner does **not** validate that ``repo_path`` exists or is a directory —
that is the Ingest stage's precondition (it raises :class:`IngestError` before
calling; design "scanner ... Preconditions"). It is given a real directory.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from docuharnessx.analysis.model import ScanStats

__all__ = [
    "FileEntry",
    "FileInventory",
    "ScanLimits",
    "DEFAULT_EXCLUDED_DIRS",
    "scan",
]


# --------------------------------------------------------------------------- #
# Scan limits                                                                  #
# --------------------------------------------------------------------------- #

#: Common non-source noise directories excluded from the walk without descending
#: (Req 1.4). Matched by exact directory *name* at any depth, so a nested
#: ``src/__pycache__`` is skipped just like a top-level ``.git``.
DEFAULT_EXCLUDED_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        "node_modules",
        "vendor",
        ".venv",
        "venv",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        ".idea",
        ".vscode",
        "dist",
        "build",
        "target",
        ".gradle",
        ".next",
        ".cache",
        "site",
    }
)

#: Size of the head sample read for binary detection (Req 2.1). Bounded so a
#: pathological file cannot drive the per-file read; deterministic by construction.
_HEAD_SAMPLE_BYTES: int = 8192


@dataclass(frozen=True)
class ScanLimits:
    """Bounds that keep the scan resilient on large/polyglot repos (Req 2.2, 2.3).

    Defaults match the design's pinned values. ``excluded_dirs`` is a frozenset of
    directory *names* skipped without descending (Req 1.4).
    """

    max_file_bytes: int = 1_000_000  # per-file read cap (Req 2.2)
    max_total_files: int = 50_000  # inventory cap (Req 2.3)
    max_total_bytes: int = 500_000_000  # total scanned-bytes cap (Req 2.3)
    excluded_dirs: frozenset[str] = field(default=DEFAULT_EXCLUDED_DIRS)


# --------------------------------------------------------------------------- #
# Inventory value objects                                                      #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class FileEntry:
    """One retained file's bounded, classified record (design scanner seam)."""

    path: str  # repo-relative POSIX path
    size: int  # bytes (full on-disk size, even if over the read cap)
    is_binary: bool
    language: str  # coarse language/file-type tag, "Other" when unknown
    loc: int  # line count for in-cap text files, else 0
    read_truncated: bool  # True when size exceeded the per-file read cap


@dataclass(frozen=True)
class FileInventory:
    """The deterministically-sorted, bounded result of a repository scan."""

    repo_path: str  # absolute realpath of the scanned root (provenance)
    entries: tuple[FileEntry, ...]  # sorted by path asc
    stats: ScanStats


# --------------------------------------------------------------------------- #
# Coarse language tagging (self-contained; canonical mapping is task 2.2)      #
# --------------------------------------------------------------------------- #

# A small, deterministic extension/filename table. This is a *coarse* per-file
# hint carried on FileEntry; the analyzer's canonical per-language aggregation
# lives in the ``languages`` module (task 2.2). Unknown -> "Other" (Req 2.4).
_EXTENSION_LANGUAGES: dict[str, str] = {
    ".go": "Go",
    ".py": "Python",
    ".pyi": "Python",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".mjs": "JavaScript",
    ".cjs": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".rs": "Rust",
    ".java": "Java",
    ".kt": "Kotlin",
    ".rb": "Ruby",
    ".c": "C",
    ".h": "C",
    ".cc": "C++",
    ".cpp": "C++",
    ".cxx": "C++",
    ".hpp": "C++",
    ".cs": "C#",
    ".sh": "Shell",
    ".bash": "Shell",
    ".md": "Markdown",
    ".markdown": "Markdown",
    ".rst": "reStructuredText",
    ".txt": "Text",
    ".json": "JSON",
    ".yaml": "YAML",
    ".yml": "YAML",
    ".toml": "TOML",
    ".ini": "INI",
    ".cfg": "INI",
    ".xml": "XML",
    ".html": "HTML",
    ".htm": "HTML",
    ".css": "CSS",
    ".sql": "SQL",
    ".proto": "Protobuf",
    ".tf": "Terraform",
}

# Special exact filenames (no/odd extension) mapped to a canonical tag.
_FILENAME_LANGUAGES: dict[str, str] = {
    "Dockerfile": "Dockerfile",
    "Makefile": "Makefile",
    "makefile": "Makefile",
    "GNUmakefile": "Makefile",
    "go.mod": "GoMod",
    "go.sum": "GoSum",
}


def _tag_language(rel_path: str) -> str:
    """Map a repo-relative path to a coarse language tag; ``"Other"`` fallback."""
    base = rel_path.rsplit("/", 1)[-1]
    special = _FILENAME_LANGUAGES.get(base)
    if special is not None:
        return special
    dot = base.rfind(".")
    if dot > 0:  # a leading-dot dotfile (".gitignore") has no real extension
        ext = base[dot:].lower()
        mapped = _EXTENSION_LANGUAGES.get(ext)
        if mapped is not None:
            return mapped
    return "Other"


# --------------------------------------------------------------------------- #
# Content classification                                                        #
# --------------------------------------------------------------------------- #


def _is_binary_sample(sample: bytes) -> bool:
    """Classify a head sample as binary (Req 2.1), deterministically.

    A NUL byte is a strong binary signal; otherwise we attempt a UTF-8 then a
    Latin-1 decode of the sample and treat an undecodable sample as binary. Pure
    function of the bytes, so classification is reproducible.
    """
    if b"\x00" in sample:
        return True
    try:
        sample.decode("utf-8")
        return False
    except UnicodeDecodeError:
        # A truncated multi-byte sequence at the sample boundary is not proof of
        # binary content; fall back to a permissive Latin-1 decode (always
        # succeeds for any byte string), so text with odd bytes stays text.
        try:
            sample.decode("latin-1")
            return False
        except UnicodeDecodeError:  # pragma: no cover - latin-1 never fails
            return True


def _count_lines(data: bytes) -> int:
    """Count lines in a text byte string (Req 3.2 LOC primitive).

    Each newline terminates a line; a final unterminated line counts as one more.
    Empty content is zero lines. Pure function of the bytes.
    """
    if not data:
        return 0
    count = data.count(b"\n")
    if not data.endswith(b"\n"):
        count += 1
    return count


# --------------------------------------------------------------------------- #
# Walk                                                                          #
# --------------------------------------------------------------------------- #


def _within_root(path: str, root_real: str) -> bool:
    """True when ``path``'s realpath stays inside ``root_real`` (symlink guard).

    Resolves symlinks via :func:`os.path.realpath` and checks containment with a
    trailing-separator prefix test (so ``/repo`` does not match ``/repo-evil``).
    Used to drop any entry a symlink would reach outside the repo root (Req 1.5).
    """
    real = os.path.realpath(path)
    if real == root_real:
        return True
    return real.startswith(root_real + os.sep)


def _classify_file(
    abs_path: str, rel_path: str, limits: ScanLimits
) -> FileEntry | None:
    """Read + classify one file into a :class:`FileEntry`, or ``None`` if unreadable.

    Returns ``None`` (the caller counts it as skipped) when the file cannot be
    stat'd or opened — an unreadable entry never aborts the walk (Req 1.5).
    """
    try:
        size = os.path.getsize(abs_path)
    except OSError:
        return None

    language = _tag_language(rel_path)
    read_truncated = size > limits.max_file_bytes

    if read_truncated:
        # Over the per-file read cap: record the file but do not read its content
        # for binary detection or line counting (Req 2.2). It is conservatively
        # treated as text (is_binary=False) with loc=0.
        return FileEntry(
            path=rel_path,
            size=size,
            is_binary=False,
            language=language,
            loc=0,
            read_truncated=True,
        )

    try:
        with open(abs_path, "rb") as handle:
            head = handle.read(_HEAD_SAMPLE_BYTES)
            is_binary = _is_binary_sample(head)
            if is_binary:
                loc = 0
            else:
                # Within the per-file cap, so reading the remainder is bounded.
                rest = handle.read()
                loc = _count_lines(head + rest)
    except OSError:
        return None

    return FileEntry(
        path=rel_path,
        size=size,
        is_binary=is_binary,
        language=language,
        loc=loc,
        read_truncated=False,
    )


def scan(repo_path: str, limits: ScanLimits = ScanLimits()) -> FileInventory:
    """Walk ``repo_path`` into a bounded, classified, sorted :class:`FileInventory`.

    The walk (design "scanner"; Req 1.3-1.7, 2.1-2.5):

    * resolves the root to an absolute realpath used both for provenance and the
      symlink-escape guard;
    * descends with ``os.walk(followlinks=False)``, sorting directory and file
      names at each level for a deterministic traversal, and prunes any directory
      whose name is in ``limits.excluded_dirs`` without descending (Req 1.4);
    * drops any file whose realpath escapes the root — a symlink pointing outside
      the repo is not counted as a repo file (Req 1.5);
    * classifies each retained file (binary/text, language tag, LOC, truncation)
      and accumulates byte/file counters;
    * enforces the total-file and total-byte caps: once either is reached it stops
      adding further entries, sets ``limit_reached`` and records a note, and still
      returns a well-formed, sorted inventory (Req 2.3);
    * counts unreadable entries in ``files_skipped`` with a note rather than
      raising (Req 1.5).

    The returned ``entries`` tuple is sorted by path and the notes are sorted, so
    two scans of an unchanged tree are byte-identical (Req 1.6, 9.1).
    """
    root_real = os.path.realpath(repo_path)

    entries: list[FileEntry] = []
    notes: set[str] = set()
    files_scanned = 0
    files_skipped = 0
    bytes_scanned = 0
    limit_reached = False

    for current_dir, dirnames, filenames in os.walk(
        root_real, followlinks=False
    ):
        # Deterministic traversal: sort and prune excluded dirs in place so
        # os.walk does not descend into them (Req 1.4). Sorting dirnames keeps the
        # walk order stable across runs/platforms.
        dirnames[:] = sorted(d for d in dirnames if d not in limits.excluded_dirs)

        for name in sorted(filenames):
            abs_path = os.path.join(current_dir, name)

            # A directory-name match also catches a symlinked dir listed among
            # filenames on some platforms; the realpath guard below is the
            # authoritative symlink-escape defense (Req 1.5).
            if not _within_root(abs_path, root_real):
                files_skipped += 1
                notes.add("skipped symlink escaping repo root")
                continue

            # Total-file cap: once reached, stop adding further detail but keep the
            # inventory well-formed (Req 2.3). Subsequent files are not enumerated.
            if files_scanned >= limits.max_total_files:
                limit_reached = True
                notes.add("scan stopped: total-file limit reached")
                continue

            rel_path = os.path.relpath(abs_path, root_real).replace(os.sep, "/")
            entry = _classify_file(abs_path, rel_path, limits)
            if entry is None:
                files_skipped += 1
                notes.add(f"skipped unreadable entry: {rel_path}")
                continue

            # Total-byte cap: adding this file would exceed the cap, so stop
            # adding detail rather than blowing the bound (Req 2.3). The traversal
            # order is deterministic (sorted), so which files land before the cap
            # trips is reproducible across runs.
            if bytes_scanned + entry.size > limits.max_total_bytes:
                limit_reached = True
                notes.add("scan stopped: total-byte limit reached")
                continue

            entries.append(entry)
            files_scanned += 1
            bytes_scanned += entry.size

    entries.sort(key=lambda e: e.path)

    stats = ScanStats(
        files_scanned=files_scanned,
        files_skipped=files_skipped,
        bytes_scanned=bytes_scanned,
        limit_reached=limit_reached,
        notes=tuple(sorted(notes)),
    )
    return FileInventory(
        repo_path=root_real,
        entries=tuple(entries),
        stats=stats,
    )
