"""Tests for ``FilesystemSegmentStore`` (task 4.2).

Covers Req 9.1-9.7, with 9.6 being the filesystem-specific criterion: the store
reads and writes segments as Markdown files with frontmatter via the serializer,
applies the SAME validation (against the bound vocabulary) and the SAME by-id
query/listing semantics as :class:`InMemorySegmentStore`.

The load-bearing invariant (design "store" component): the filesystem and
in-memory adapters return identical results for identical content. A dedicated
parity test asserts this directly.
"""

from __future__ import annotations

import pytest

from docuharnessx.ontology.errors import IdConflictError, OntologyError
from docuharnessx.ontology.model import Subject
from docuharnessx.ontology.schema import Segment
from docuharnessx.ontology.store import (
    AxisFilter,
    FilesystemSegmentStore,
    InMemorySegmentStore,
    SegmentStore,
)
from docuharnessx.ontology.vocabulary import default_profile


VOCAB = default_profile()


def _subject(raw: str) -> Subject:
    return Subject.parse(raw, frozenset(VOCAB.subject_prefixes))


def _segment(
    seg_id: str,
    *,
    roles=("developer",),
    intent="install",
    subjects=("component:core",),
    related=(),
) -> Segment:
    return Segment(
        id=seg_id,
        title=f"Title {seg_id}",
        roles=list(roles),
        subjects=[_subject(s) for s in subjects],
        intent=intent,
        related=list(related),
    )


# --------------------------------------------------------------------------- #
# Protocol conformance                                                         #
# --------------------------------------------------------------------------- #


def test_filesystem_store_is_a_segment_store(tmp_path):
    store = FilesystemSegmentStore(tmp_path, VOCAB)
    assert isinstance(store, SegmentStore)


def test_missing_directory_is_created(tmp_path):
    target = tmp_path / "does-not-exist-yet"
    assert not target.exists()
    FilesystemSegmentStore(target, VOCAB)
    assert target.is_dir()


# --------------------------------------------------------------------------- #
# Write then read back (Req 9.6, observable completion)                         #
# --------------------------------------------------------------------------- #


def test_write_then_read_back(tmp_path):
    store = FilesystemSegmentStore(tmp_path, VOCAB)
    seg = _segment("alpha")
    store.put(seg)

    # A real Markdown file landed in the directory.
    files = list(tmp_path.glob("*.md"))
    assert len(files) == 1

    # A fresh store over the same directory reads the segment back.
    reread = FilesystemSegmentStore(tmp_path, VOCAB)
    listed = reread.list_segments()
    assert len(listed) == 1
    back = listed[0]
    assert back.id == "alpha"
    assert back.title == "Title alpha"
    assert back.roles == ["developer"]
    assert back.intent == "install"
    assert [s.canonical() for s in back.subjects] == ["component:core"]


# --------------------------------------------------------------------------- #
# put validation + id conflict (Req 9.2, 9.7)                                  #
# --------------------------------------------------------------------------- #


def test_put_rejects_invalid_segment_nothing_written(tmp_path):
    store = FilesystemSegmentStore(tmp_path, VOCAB)
    invalid = _segment("bad", roles=("not-a-real-role",))
    with pytest.raises(OntologyError):
        store.put(invalid)
    # Nothing was written.
    assert list(tmp_path.glob("*.md")) == []
    assert store.list_segments() == ()


def test_put_rejects_id_conflict_no_overwrite(tmp_path):
    store = FilesystemSegmentStore(tmp_path, VOCAB)
    store.put(_segment("dup", intent="install"))
    with pytest.raises(IdConflictError):
        store.put(_segment("dup", intent="configure"))
    # Original is untouched (no overwrite).
    listed = store.list_segments()
    assert len(listed) == 1
    assert listed[0].intent == "install"


# --------------------------------------------------------------------------- #
# Query semantics (Req 9.3, 9.4) + deterministic listing (Req 9.5)            #
# --------------------------------------------------------------------------- #


def test_empty_filter_returns_all(tmp_path):
    store = FilesystemSegmentStore(tmp_path, VOCAB)
    store.put(_segment("a"))
    store.put(_segment("b"))
    assert {s.id for s in store.query(AxisFilter())} == {"a", "b"}


def test_subject_axis_query(tmp_path):
    store = FilesystemSegmentStore(tmp_path, VOCAB)
    store.put(_segment("a", subjects=("component:core",)))
    store.put(_segment("b", subjects=("tech:python",)))
    result = store.query(AxisFilter(subjects=(_subject("component:core"),)))
    assert [s.id for s in result] == ["a"]


def test_multi_axis_and_query(tmp_path):
    store = FilesystemSegmentStore(tmp_path, VOCAB)
    store.put(_segment("a", roles=("developer",), intent="install"))
    store.put(_segment("b", roles=("developer",), intent="configure"))
    store.put(_segment("c", roles=("manager",), intent="install"))
    result = store.query(
        AxisFilter(roles=("developer",), intents=("install",))
    )
    assert [s.id for s in result] == ["a"]


def test_per_axis_or_query(tmp_path):
    store = FilesystemSegmentStore(tmp_path, VOCAB)
    store.put(_segment("a", intent="install"))
    store.put(_segment("b", intent="configure"))
    store.put(_segment("c", intent="use"))
    result = store.query(AxisFilter(intents=("install", "configure")))
    assert [s.id for s in result] == ["a", "b"]


def test_list_segments_deterministic_by_id(tmp_path):
    store = FilesystemSegmentStore(tmp_path, VOCAB)
    for seg_id in ("c", "a", "b"):
        store.put(_segment(seg_id))
    assert [s.id for s in store.list_segments()] == ["a", "b", "c"]


# --------------------------------------------------------------------------- #
# Cross-link resolution (Req 7.3 via the store seam)                           #
# --------------------------------------------------------------------------- #


def test_resolve_cross_links_returns_related_targets(tmp_path):
    store = FilesystemSegmentStore(tmp_path, VOCAB)
    store.put(_segment("a", related=("b", "c")))
    store.put(_segment("b"))
    store.put(_segment("c"))
    resolved = store.resolve_cross_links("a")
    assert [s.id for s in resolved] == ["b", "c"]


def test_resolve_cross_links_unknown_id_empty(tmp_path):
    store = FilesystemSegmentStore(tmp_path, VOCAB)
    assert store.resolve_cross_links("nope") == ()


# --------------------------------------------------------------------------- #
# Parity invariant: fs and in-memory return identical results (design store)   #
# --------------------------------------------------------------------------- #


def test_parity_with_in_memory_store(tmp_path):
    segments = [
        _segment("seg-3", roles=("developer", "manager"), intent="install",
                 subjects=("component:core", "tech:python"), related=("seg-1",)),
        _segment("seg-1", roles=("manager",), intent="configure",
                 subjects=("topic:overview",)),
        _segment("seg-2", roles=("developer",), intent="use",
                 subjects=("artifact:guide",)),
    ]

    fs = FilesystemSegmentStore(tmp_path, VOCAB)
    mem = InMemorySegmentStore(VOCAB)
    for seg in segments:
        fs.put(seg)
        mem.put(seg)

    def ids(result):
        return [s.id for s in result]

    # list_segments identical
    assert ids(fs.list_segments()) == ids(mem.list_segments())

    # Various queries identical
    filters = [
        AxisFilter(),
        AxisFilter(roles=("developer",)),
        AxisFilter(roles=("developer", "manager")),
        AxisFilter(intents=("install", "configure")),
        AxisFilter(subjects=(_subject("component:core"),)),
        AxisFilter(roles=("developer",), intents=("install",)),
    ]
    for where in filters:
        assert ids(fs.query(where)) == ids(mem.query(where))

    # cross-links identical
    assert ids(fs.resolve_cross_links("seg-3")) == ids(
        mem.resolve_cross_links("seg-3")
    )
