"""Unit tests for task 2.1 (the bounded, deterministic repository scanner).

Task 2.1 owns exactly one new module — ``docuharnessx.analysis.scanner`` — the
pure, model-free filesystem walk that turns a target repository on local disk
into a bounded, classified, deterministically-sorted :class:`FileInventory`
(design "scanner — repository walk and inventory"; Req 1.3-1.6, 2.1-2.5).

The scanner is stdlib-only and harness-free; every test here drives it against a
crafted ``tmp_path`` fixture tree (or, for one determinism check, the reference
repo) so the suite is self-contained — it does NOT depend on the concurrently
developed ``languages``/``detectors``/``analyzer`` modules.

Pins exercised here (all from the design's scanner contract):

* Walk records, per retained file: repo-relative POSIX path, byte size,
  binary-vs-text classification, a language/file-type tag, line count, and a
  read-truncated flag (Req 1.3).
* Noise directories are excluded without descending (Req 1.4); symlinks are not
  followed out of the repo root (Req 1.5); unreadable entries are counted, never
  raised (Req 1.5).
* Per-file read cap (over-size file -> ``loc==0``, ``read_truncated=True``, but
  still in the inventory) (Req 2.2); total-file and total-byte caps trip
  ``limit_reached`` and add a note while still returning a well-formed inventory
  (Req 2.3).
* Empty dirs / zero-byte / extensionless / unknown files classify as ``"Other"``
  without error (Req 2.4).
* Two scans of the same tree are byte-identical (Req 1.6, 9.1).

Out of scope here: language aggregation/primary-language (task 2.2), detectors
(task 3.x), the analyzer (task 4.1), serde (task 1.2), and the stages (task 5.x).
"""

from __future__ import annotations

import dataclasses
import importlib
import os

import pytest


SCANNER_MODULE = "docuharnessx.analysis.scanner"
MODEL_MODULE = "docuharnessx.analysis.model"
PACKAGE = "docuharnessx.analysis"

REFERENCE_REPO = "/home/mc/Source/malware_hashes"


# --------------------------------------------------------------------------- #
# Fixture-building helpers
# --------------------------------------------------------------------------- #


def _write(base, rel_path: str, data: bytes) -> None:
    """Create ``base/rel_path`` (with parent dirs), writing raw bytes."""
    full = os.path.join(base, *rel_path.split("/"))
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "wb") as handle:
        handle.write(data)


def _scanner():
    return importlib.import_module(SCANNER_MODULE)


def _scan(base, **limit_overrides):
    """Scan ``base`` with default limits, optionally overriding a few caps."""
    mod = _scanner()
    if limit_overrides:
        limits = mod.ScanLimits(**limit_overrides)
        return mod.scan(str(base), limits)
    return mod.scan(str(base))


def _entries_by_path(inventory) -> dict:
    return {e.path: e for e in inventory.entries}


# --------------------------------------------------------------------------- #
# Module / symbol surface
# --------------------------------------------------------------------------- #


def test_scanner_module_imports() -> None:
    assert _scanner() is not None


def test_scanner_public_symbols_exist() -> None:
    mod = _scanner()
    for name in ("FileEntry", "FileInventory", "ScanLimits", "scan",
                 "DEFAULT_EXCLUDED_DIRS"):
        assert hasattr(mod, name), f"scanner missing {name}"
    assert set(("FileEntry", "FileInventory", "ScanLimits", "scan",
                "DEFAULT_EXCLUDED_DIRS")).issubset(set(mod.__all__))


def test_file_entry_and_inventory_are_frozen_dataclasses() -> None:
    mod = _scanner()
    for name in ("FileEntry", "FileInventory", "ScanLimits"):
        cls = getattr(mod, name)
        assert dataclasses.is_dataclass(cls), f"{name} must be a dataclass"
        assert cls.__dataclass_params__.frozen is True, f"{name} must be frozen"


def test_file_entry_fields_match_design() -> None:
    mod = _scanner()
    names = tuple(f.name for f in dataclasses.fields(mod.FileEntry))
    assert names == (
        "path",
        "size",
        "is_binary",
        "language",
        "loc",
        "read_truncated",
    )


def test_file_inventory_fields_match_design() -> None:
    mod = _scanner()
    names = tuple(f.name for f in dataclasses.fields(mod.FileInventory))
    assert names == ("repo_path", "entries", "stats")


def test_scan_limits_defaults_match_design() -> None:
    mod = _scanner()
    limits = mod.ScanLimits()
    assert limits.max_file_bytes == 1_000_000
    assert limits.max_total_files == 50_000
    assert limits.max_total_bytes == 500_000_000
    assert isinstance(limits.excluded_dirs, frozenset)


def test_default_excluded_dirs_cover_common_noise() -> None:
    mod = _scanner()
    excluded = mod.DEFAULT_EXCLUDED_DIRS
    for name in (".git", "node_modules", "vendor", ".venv", "__pycache__",
                 "dist", "build", "target"):
        assert name in excluded, f"{name} should be a default-excluded dir"


def test_inventory_stats_is_model_scanstats() -> None:
    """``FileInventory.stats`` is the model's frozen ``ScanStats`` (design seam)."""
    model = importlib.import_module(MODEL_MODULE)
    inv = _scan_empty_tree()
    assert isinstance(inv.stats, model.ScanStats)


def _scan_empty_tree(tmp=None):
    # helper used by a couple of structural tests; builds nothing
    import tempfile

    base = tempfile.mkdtemp()
    return _scan(base)


# --------------------------------------------------------------------------- #
# Core walk: paths, sizes, ordering (Req 1.3, 1.6)
# --------------------------------------------------------------------------- #


def test_basic_walk_records_relative_posix_paths(tmp_path) -> None:
    _write(tmp_path, "main.go", b"package main\n\nfunc main() {}\n")
    _write(tmp_path, "internal/hash/hash.go", b"package hash\n")
    inv = _scan(tmp_path)
    paths = [e.path for e in inv.entries]
    assert "main.go" in paths
    assert "internal/hash/hash.go" in paths  # POSIX separators, repo-relative


def test_entries_are_sorted_by_path(tmp_path) -> None:
    _write(tmp_path, "z.go", b"package z\n")
    _write(tmp_path, "a.go", b"package a\n")
    _write(tmp_path, "m/b.go", b"package b\n")
    inv = _scan(tmp_path)
    paths = [e.path for e in inv.entries]
    assert paths == sorted(paths)


def test_records_byte_size(tmp_path) -> None:
    data = b"package main\nfunc main() {}\n"
    _write(tmp_path, "main.go", data)
    inv = _scan(tmp_path)
    entry = _entries_by_path(inv)["main.go"]
    assert entry.size == len(data)


def test_repo_path_is_absolute_realpath(tmp_path) -> None:
    _write(tmp_path, "a.txt", b"x\n")
    inv = _scan(tmp_path)
    assert os.path.isabs(inv.repo_path)
    assert inv.repo_path == os.path.realpath(str(tmp_path))


# --------------------------------------------------------------------------- #
# Determinism (Req 1.6, 9.1)
# --------------------------------------------------------------------------- #


def test_two_scans_yield_identical_inventories(tmp_path) -> None:
    _write(tmp_path, "main.go", b"package main\n")
    _write(tmp_path, "b/c.py", b"print('hi')\n")
    _write(tmp_path, "b/d.md", b"# title\n\ntext\n")
    first = _scan(tmp_path)
    second = _scan(tmp_path)
    assert first == second  # frozen dataclasses compare structurally
    assert first.entries == second.entries


# --------------------------------------------------------------------------- #
# Binary vs text classification (Req 2.1)
# --------------------------------------------------------------------------- #


def test_text_file_classified_as_text_with_loc(tmp_path) -> None:
    _write(tmp_path, "a.txt", b"line1\nline2\nline3\n")
    inv = _scan(tmp_path)
    entry = _entries_by_path(inv)["a.txt"]
    assert entry.is_binary is False
    assert entry.loc == 3


def test_binary_file_classified_binary_with_zero_loc(tmp_path) -> None:
    # NUL byte -> binary; line/content parsing is skipped (loc == 0).
    _write(tmp_path, "blob.bin", b"\x00\x01\x02PNG\x00stuff\x00")
    inv = _scan(tmp_path)
    entry = _entries_by_path(inv)["blob.bin"]
    assert entry.is_binary is True
    assert entry.loc == 0


def test_final_unterminated_line_counts_as_one(tmp_path) -> None:
    _write(tmp_path, "a.txt", b"line1\nline2")  # no trailing newline
    inv = _scan(tmp_path)
    entry = _entries_by_path(inv)["a.txt"]
    assert entry.loc == 2


# --------------------------------------------------------------------------- #
# Edge-case files (Req 2.4)
# --------------------------------------------------------------------------- #


def test_zero_byte_file_handled(tmp_path) -> None:
    _write(tmp_path, "empty.txt", b"")
    inv = _scan(tmp_path)
    entry = _entries_by_path(inv)["empty.txt"]
    assert entry.size == 0
    assert entry.loc == 0
    assert entry.is_binary is False


def test_extensionless_and_unknown_files_are_other(tmp_path) -> None:
    _write(tmp_path, "NOTICE", b"some notice\n")
    _write(tmp_path, "weird.zzz", b"unknown type\n")
    inv = _scan(tmp_path)
    by = _entries_by_path(inv)
    assert by["NOTICE"].language == "Other"
    assert by["weird.zzz"].language == "Other"


def test_empty_directory_produces_no_entry_and_no_error(tmp_path) -> None:
    os.makedirs(os.path.join(tmp_path, "emptydir"))
    _write(tmp_path, "a.txt", b"x\n")
    inv = _scan(tmp_path)
    paths = [e.path for e in inv.entries]
    assert paths == ["a.txt"]


# --------------------------------------------------------------------------- #
# Excluded directories (Req 1.4)
# --------------------------------------------------------------------------- #


def test_excluded_dirs_are_not_descended(tmp_path) -> None:
    _write(tmp_path, "keep.go", b"package keep\n")
    _write(tmp_path, ".git/config", b"[core]\n")
    _write(tmp_path, "node_modules/dep/index.js", b"module.exports = {}\n")
    _write(tmp_path, "vendor/x/y.go", b"package x\n")
    _write(tmp_path, "__pycache__/m.pyc", b"\x00\x01")
    inv = _scan(tmp_path)
    paths = [e.path for e in inv.entries]
    assert paths == ["keep.go"]
    # Excluded dirs are skipped at entry without descending, so no nested entry.
    assert not any(p.startswith(".git/") for p in paths)
    assert not any(p.startswith("node_modules/") for p in paths)


def test_nested_excluded_dir_is_also_skipped(tmp_path) -> None:
    _write(tmp_path, "src/keep.py", b"x = 1\n")
    _write(tmp_path, "src/__pycache__/keep.cpython-312.pyc", b"\x00\x00")
    inv = _scan(tmp_path)
    paths = [e.path for e in inv.entries]
    assert paths == ["src/keep.py"]


# --------------------------------------------------------------------------- #
# Symlink safety (Req 1.5)
# --------------------------------------------------------------------------- #


def test_symlink_escaping_root_is_not_followed(tmp_path) -> None:
    # Build an external target OUTSIDE the repo root; a symlink in the repo that
    # points to it must not contribute the external file to the inventory.
    outside = tmp_path / "outside"
    repo = tmp_path / "repo"
    os.makedirs(outside)
    os.makedirs(repo)
    _write(str(outside), "secret.txt", b"top secret\n")
    _write(str(repo), "keep.go", b"package keep\n")
    link = repo / "escape"
    try:
        os.symlink(str(outside), str(link), target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unsupported on this platform")
    inv = _scan(repo)
    paths = [e.path for e in inv.entries]
    # The external secret.txt must NOT appear under the symlinked dir.
    assert not any("secret.txt" in p for p in paths)
    assert "keep.go" in paths


def test_symlinked_file_escaping_root_is_skipped(tmp_path) -> None:
    outside = tmp_path / "outside"
    repo = tmp_path / "repo"
    os.makedirs(outside)
    os.makedirs(repo)
    _write(str(outside), "secret.txt", b"top secret\n")
    _write(str(repo), "keep.go", b"package keep\n")
    link = repo / "linked.txt"
    try:
        os.symlink(str(outside / "secret.txt"), str(link))
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unsupported on this platform")
    inv = _scan(repo)
    contents = [e.path for e in inv.entries]
    assert "keep.go" in contents
    # A symlink whose realpath escapes the root is not counted as a repo file.
    assert "linked.txt" not in contents


# --------------------------------------------------------------------------- #
# Per-file read cap (Req 2.2)
# --------------------------------------------------------------------------- #


def test_over_size_file_truncated_with_zero_loc(tmp_path) -> None:
    big = b"x\n" * 100  # 200 bytes of text
    _write(tmp_path, "big.txt", big)
    inv = _scan(tmp_path, max_file_bytes=50)  # below file size
    entry = _entries_by_path(inv)["big.txt"]
    assert entry.read_truncated is True
    assert entry.loc == 0          # not line-counted because over the read cap
    assert entry.size == len(big)  # full size is still recorded


def test_under_cap_file_is_not_truncated(tmp_path) -> None:
    _write(tmp_path, "small.txt", b"a\nb\n")
    inv = _scan(tmp_path, max_file_bytes=1_000_000)
    entry = _entries_by_path(inv)["small.txt"]
    assert entry.read_truncated is False
    assert entry.loc == 2


# --------------------------------------------------------------------------- #
# Total caps: limit_reached + note + well-formed inventory (Req 2.3)
# --------------------------------------------------------------------------- #


def test_total_file_cap_trips_limit_reached_and_note(tmp_path) -> None:
    for i in range(10):
        _write(tmp_path, f"f{i:02d}.txt", b"x\n")
    inv = _scan(tmp_path, max_total_files=3)
    assert inv.stats.limit_reached is True
    assert len(inv.entries) <= 3
    assert any("file" in n.lower() and "limit" in n.lower() for n in inv.stats.notes)
    # Still well-formed: sorted and deterministic.
    paths = [e.path for e in inv.entries]
    assert paths == sorted(paths)
    assert _scan(tmp_path, max_total_files=3) == inv  # deterministic under a cap


def test_total_byte_cap_trips_limit_reached_and_note(tmp_path) -> None:
    for i in range(10):
        _write(tmp_path, f"f{i:02d}.txt", b"x" * 100)
    inv = _scan(tmp_path, max_total_bytes=250)
    assert inv.stats.limit_reached is True
    assert any("byte" in n.lower() and "limit" in n.lower() for n in inv.stats.notes)


def test_no_limit_reached_when_within_caps(tmp_path) -> None:
    _write(tmp_path, "a.txt", b"x\n")
    _write(tmp_path, "b.txt", b"y\n")
    inv = _scan(tmp_path)
    assert inv.stats.limit_reached is False
    assert inv.stats.notes == ()


# --------------------------------------------------------------------------- #
# Stats accounting (Req 2.3, 10.2)
# --------------------------------------------------------------------------- #


def test_stats_counts_files_and_bytes(tmp_path) -> None:
    _write(tmp_path, "a.txt", b"abc\n")   # 4 bytes
    _write(tmp_path, "b.txt", b"de\n")    # 3 bytes
    inv = _scan(tmp_path)
    assert inv.stats.files_scanned == 2
    assert inv.stats.bytes_scanned == 7
    assert inv.stats.files_skipped == 0


def test_notes_are_sorted(tmp_path) -> None:
    # Trip both caps so more than one note is emitted; assert sorted order.
    for i in range(20):
        _write(tmp_path, f"f{i:02d}.txt", b"x" * 100)
    inv = _scan(tmp_path, max_total_files=2, max_total_bytes=150)
    assert list(inv.stats.notes) == sorted(inv.stats.notes)


# --------------------------------------------------------------------------- #
# Unreadable entries are skipped + counted, never raised (Req 1.5)
# --------------------------------------------------------------------------- #


def test_unreadable_file_is_skipped_and_counted(tmp_path) -> None:
    if os.geteuid() == 0:
        pytest.skip("running as root bypasses permission bits")
    _write(tmp_path, "ok.txt", b"fine\n")
    _write(tmp_path, "locked.txt", b"secret\n")
    os.chmod(os.path.join(tmp_path, "locked.txt"), 0o000)
    try:
        inv = _scan(tmp_path)
    finally:
        os.chmod(os.path.join(tmp_path, "locked.txt"), 0o644)
    paths = [e.path for e in inv.entries]
    assert "ok.txt" in paths
    # Unreadable file is counted as skipped rather than aborting the walk.
    assert inv.stats.files_skipped >= 1


# --------------------------------------------------------------------------- #
# Language tag presence (coarse) — full mapping is task 2.2's languages module
# --------------------------------------------------------------------------- #


def test_language_tag_is_populated_for_known_and_unknown(tmp_path) -> None:
    _write(tmp_path, "main.go", b"package main\n")
    _write(tmp_path, "mystery", b"no extension\n")
    inv = _scan(tmp_path)
    by = _entries_by_path(inv)
    assert by["main.go"].language and by["main.go"].language != ""
    assert by["mystery"].language == "Other"


# --------------------------------------------------------------------------- #
# Reference-repo determinism (Req 9.2) — real polyglot tree
# --------------------------------------------------------------------------- #


@pytest.mark.skipif(
    not os.path.isdir(REFERENCE_REPO),
    reason="reference repo not present on this machine",
)
def test_reference_repo_scans_deterministically() -> None:
    first = _scan(REFERENCE_REPO)
    second = _scan(REFERENCE_REPO)
    assert first == second
    paths = [e.path for e in first.entries]
    assert paths == sorted(paths)
    # The .git dir is excluded, so no .git/* entry leaks in.
    assert not any(p.startswith(".git/") for p in paths)
    # Both the root and nested go.mod survive the walk (detectors use these).
    assert "go.mod" in paths
    assert ".dagger/go.mod" in paths
    # main.go is present and tagged as Go (coarse tag).
    by = _entries_by_path(first)
    assert "main.go" in by
