"""Tests for the living page store (task 1.3, boundary: LivingPageStore).

Pins the project-local store that later incremental run / refine will use:

* ``LivingPageStore`` is a protocol; the filesystem adapter lives under
  ``<project>/.docuharnessx/pages/`` (Req 5.1).
* Filenames reuse ``page_filename``; markdown frontmatter is the question-page
  field set plus ``cited_files`` so a ``Page`` round-trips in full.
* ``get`` of a missing id returns ``None`` rather than raising.
* The retired ``<out>/segments`` tree is not the source of truth (Req 5.3).

These tests touch no model and no network.
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml

from docuharnessx.assembler.pages import page_filename
from docuharnessx.pages.model import Page
from docuharnessx.pages.store import (
    PAGES_RELPATH,
    FilesystemLivingPageStore,
    LivingPageStore,
)

_RETIRED_SEGMENTS_RELPATH = os.path.join(".docuharnessx", "out", "segments")


def _page(
    *,
    id: str = "startup:app.py",
    title: str = "How does this program start?",
    summary: str = "The CLI starts in app.py by loading config.",
    body: str = (
        "The program starts in app.py:12 by calling load_config "
        "(config.py:8) and constructing Engine (engine.py:15).\n"
    ),
    subjects: tuple[str, ...] = ("app.py",),
    related: tuple[str, ...] = ("component:engine",),
    cited_files: tuple[str, ...] = ("app.py", "config.py", "engine.py"),
) -> Page:
    return Page(
        id=id,
        title=title,
        summary=summary,
        body=body,
        subjects=subjects,
        related=related,
        cited_files=cited_files,
    )


def _store(project: Path) -> FilesystemLivingPageStore:
    return FilesystemLivingPageStore(project)


def _pages_dir(project: Path) -> Path:
    return project / PAGES_RELPATH


# --------------------------------------------------------------------------- #
# Protocol + documented root (Req 5.1)                                         #
# --------------------------------------------------------------------------- #


def test_filesystem_adapter_is_a_living_page_store(tmp_path: Path) -> None:
    store = _store(tmp_path)
    assert isinstance(store, LivingPageStore)


def test_pages_relpath_is_under_docuharnessx_not_out_segments() -> None:
    assert PAGES_RELPATH == os.path.join(".docuharnessx", "pages")
    assert PAGES_RELPATH != _RETIRED_SEGMENTS_RELPATH


# --------------------------------------------------------------------------- #
# Observable completion: put, list, get, has; missing id is None               #
# --------------------------------------------------------------------------- #


def test_put_list_get_has_round_trip_equal_fields(tmp_path: Path) -> None:
    store = _store(tmp_path)
    original = _page()

    store.put(original)

    listed = store.list()
    assert [page.id for page in listed] == [original.id]
    loaded = store.get(original.id)
    assert loaded == original
    assert loaded is not None
    assert loaded.id == original.id
    assert loaded.title == original.title
    assert loaded.summary == original.summary
    assert loaded.body == original.body
    assert loaded.subjects == original.subjects
    assert loaded.related == original.related
    assert loaded.cited_files == original.cited_files
    assert store.has(original.id) is True


def test_get_missing_id_returns_none_and_has_is_false(tmp_path: Path) -> None:
    store = _store(tmp_path)

    assert store.get("startup:missing") is None
    assert store.has("startup:missing") is False
    assert store.list() == ()

    store.put(_page())
    assert store.get("startup:missing") is None
    assert store.has("startup:missing") is False


def test_empty_collections_round_trip(tmp_path: Path) -> None:
    store = _store(tmp_path)
    original = _page(subjects=(), related=(), cited_files=())

    store.put(original)

    assert store.get(original.id) == original


# --------------------------------------------------------------------------- #
# On-disk layout: page_filename + question-page frontmatter + cited_files      #
# --------------------------------------------------------------------------- #


def test_put_writes_page_filename_under_project_pages_dir(tmp_path: Path) -> None:
    store = _store(tmp_path)
    original = _page()

    store.put(original)

    path = _pages_dir(tmp_path) / page_filename(original.id)
    assert path.is_file()
    assert list(_pages_dir(tmp_path).glob("*.md")) == [path]


def test_on_disk_frontmatter_includes_cited_files_and_body(tmp_path: Path) -> None:
    store = _store(tmp_path)
    original = _page()

    store.put(original)

    text = (_pages_dir(tmp_path) / page_filename(original.id)).read_text(
        encoding="utf-8"
    )
    assert text.startswith("---")
    closing = text.find("\n---", 3)
    assert closing != -1
    meta = yaml.safe_load(text[4:closing])
    assert meta["id"] == original.id
    assert meta["title"] == original.title
    assert meta["subjects"] == list(original.subjects)
    assert meta["summary"] == original.summary
    assert meta["related"] == list(original.related)
    assert meta["cited_files"] == list(original.cited_files)
    assert original.body.strip() in text
    # Living store round-trips the Page value, not assembled site markdown.
    assert "## Related" not in text
    assert "```mermaid" not in text
    assert f"# {original.title}" not in text.split("---", 2)[-1]


def test_list_is_filename_sorted(tmp_path: Path) -> None:
    store = _store(tmp_path)
    first = _page(id="zzz:last", title="Last")
    second = _page(id="aaa:first", title="First")
    store.put(first)
    store.put(second)

    listed = store.list()
    names = [page_filename(page.id) for page in listed]
    assert names == sorted(names)
    assert {page.id for page in listed} == {first.id, second.id}


def test_put_replaces_existing_page(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.put(_page(body="first draft\n"))
    updated = _page(body="refined body grounded in app.py:12\n")

    store.put(updated)

    assert store.get(updated.id) == updated
    assert len(store.list()) == 1


# --------------------------------------------------------------------------- #
# Retired segment store is not the living store (Req 5.3)                      #
# --------------------------------------------------------------------------- #


def test_store_does_not_read_or_write_retired_segments(tmp_path: Path) -> None:
    decoy_dir = tmp_path / _RETIRED_SEGMENTS_RELPATH
    decoy_dir.mkdir(parents=True)
    decoy = decoy_dir / page_filename("startup:app.py")
    decoy.write_text(
        "---\nid: startup:app.py\ntitle: decoy\nsummary: ''\n"
        "subjects: []\nrelated: []\ncited_files: []\n---\ndecoy body\n",
        encoding="utf-8",
    )

    store = _store(tmp_path)
    original = _page()
    store.put(original)

    assert store.get(original.id) == original
    assert decoy.read_text(encoding="utf-8").startswith("---\nid: startup:app.py")
    assert "decoy body" in decoy.read_text(encoding="utf-8")
    assert not any(path.parent == decoy_dir for path in _pages_dir(tmp_path).rglob("*"))
    living = _pages_dir(tmp_path) / page_filename(original.id)
    assert living.is_file()
    assert "decoy body" not in living.read_text(encoding="utf-8")
