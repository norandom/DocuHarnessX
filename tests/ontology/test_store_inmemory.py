"""Tests for the frozen ``SegmentStore`` port and ``InMemorySegmentStore`` (task 4.1).

Covers Req 9.1-9.5, 9.7:

* :class:`SegmentStore` is a runtime-checkable ``Protocol`` with the frozen
  method set (``put``/``query``/``list_segments``/``resolve_cross_links``) and
  :class:`AxisFilter` is a frozen dataclass with the pinned field shape and
  match-all empty-tuple defaults.
* ``put`` validates against the bound vocabulary and rejects an invalid segment
  (Req 9.2) and an id conflict (Req 9.7).
* ``query`` applies per-axis OR and cross-axis AND; an empty filter returns all
  (Req 9.3, 9.4).
* ``list_segments`` returns a deterministic order (Req 9.5).
* ``resolve_cross_links`` returns the declared related targets deterministically
  (Req 7.3 via the store seam).
"""

from __future__ import annotations

from dataclasses import fields, is_dataclass
from typing import Protocol, runtime_checkable

import pytest

from docuharnessx.ontology.errors import IdConflictError, OntologyError
from docuharnessx.ontology.model import Subject
from docuharnessx.ontology.schema import Segment
from docuharnessx.ontology.store import (
    AxisFilter,
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
# Frozen contract shape (Req 9.1)                                              #
# --------------------------------------------------------------------------- #


def test_axis_filter_is_frozen_dataclass_with_pinned_fields():
    assert is_dataclass(AxisFilter)
    names = {f.name for f in fields(AxisFilter)}
    assert names == {"roles", "intents", "subjects"}
    # frozen: assignment raises
    f = AxisFilter()
    with pytest.raises(Exception):
        f.roles = ("developer",)  # type: ignore[misc]


def test_axis_filter_defaults_are_empty_tuples():
    f = AxisFilter()
    assert f.roles == ()
    assert f.intents == ()
    assert f.subjects == ()


def test_segment_store_is_protocol():
    assert issubclass(SegmentStore, Protocol)  # type: ignore[arg-type]


def test_in_memory_store_satisfies_protocol_structurally():
    store = InMemorySegmentStore(VOCAB)
    for method in ("put", "query", "list_segments", "resolve_cross_links"):
        assert callable(getattr(store, method))


# --------------------------------------------------------------------------- #
# put: validate-on-put (Req 9.2) + id conflict (Req 9.7)                       #
# --------------------------------------------------------------------------- #


def test_put_rejects_invalid_segment():
    store = InMemorySegmentStore(VOCAB)
    bad = _segment("s-bad", roles=("not-a-role",))
    with pytest.raises(OntologyError):
        store.put(bad)
    # rejected segment is not stored
    assert store.list_segments() == ()


def test_put_rejects_id_conflict():
    store = InMemorySegmentStore(VOCAB)
    store.put(_segment("dup"))
    with pytest.raises(IdConflictError) as exc:
        store.put(_segment("dup", roles=("manager",)))
    assert exc.value.segment_id == "dup"
    # original retained, not overwritten
    (stored,) = store.list_segments()
    assert stored.roles == ["developer"]


# --------------------------------------------------------------------------- #
# query semantics (Req 9.3, 9.4)                                              #
# --------------------------------------------------------------------------- #


def test_empty_filter_returns_all():
    store = InMemorySegmentStore(VOCAB)
    store.put(_segment("a"))
    store.put(_segment("b", roles=("manager",), intent="use"))
    result = store.query(AxisFilter())
    assert {s.id for s in result} == {"a", "b"}


def test_single_axis_multi_value_is_or():
    store = InMemorySegmentStore(VOCAB)
    store.put(_segment("dev", roles=("developer",)))
    store.put(_segment("mgr", roles=("manager",)))
    store.put(_segment("res", roles=("researcher",)))
    result = store.query(AxisFilter(roles=("developer", "manager")))
    assert {s.id for s in result} == {"dev", "mgr"}


def test_multi_axis_is_and():
    store = InMemorySegmentStore(VOCAB)
    store.put(_segment("hit", roles=("developer",), intent="install"))
    store.put(_segment("wrong-intent", roles=("developer",), intent="use"))
    store.put(_segment("wrong-role", roles=("manager",), intent="install"))
    result = store.query(AxisFilter(roles=("developer",), intents=("install",)))
    assert {s.id for s in result} == {"hit"}


def test_subject_axis_query():
    store = InMemorySegmentStore(VOCAB)
    store.put(_segment("core", subjects=("component:core",)))
    store.put(_segment("cli", subjects=("component:cli",)))
    where = AxisFilter(subjects=(_subject("component:core"),))
    result = store.query(where)
    assert {s.id for s in result} == {"core"}


def test_multi_value_subject_axis_is_or():
    store = InMemorySegmentStore(VOCAB)
    store.put(_segment("core", subjects=("component:core",)))
    store.put(_segment("cli", subjects=("component:cli",)))
    store.put(_segment("other", subjects=("tech:python",)))
    where = AxisFilter(
        subjects=(_subject("component:core"), _subject("component:cli"))
    )
    result = store.query(where)
    assert {s.id for s in result} == {"core", "cli"}


# --------------------------------------------------------------------------- #
# list_segments determinism (Req 9.5)                                         #
# --------------------------------------------------------------------------- #


def test_list_segments_deterministic_order():
    store = InMemorySegmentStore(VOCAB)
    # Insert out of sorted order.
    for sid in ("c", "a", "b"):
        store.put(_segment(sid))
    first = [s.id for s in store.list_segments()]
    second = [s.id for s in store.list_segments()]
    assert first == second
    assert first == sorted(first)


def test_query_results_are_deterministic_and_tuple():
    store = InMemorySegmentStore(VOCAB)
    for sid in ("z", "y", "x"):
        store.put(_segment(sid))
    result = store.query(AxisFilter())
    assert isinstance(result, tuple)
    assert [s.id for s in result] == ["x", "y", "z"]


# --------------------------------------------------------------------------- #
# resolve_cross_links (Req 7.3 via store)                                      #
# --------------------------------------------------------------------------- #


def test_resolve_cross_links_returns_declared_targets():
    store = InMemorySegmentStore(VOCAB)
    store.put(_segment("a", related=("b", "c")))
    store.put(_segment("b"))
    store.put(_segment("c"))
    result = store.resolve_cross_links("a")
    assert isinstance(result, tuple)
    assert [s.id for s in result] == ["b", "c"]


def test_resolve_cross_links_skips_self_and_unknown():
    store = InMemorySegmentStore(VOCAB)
    store.put(_segment("a", related=("a", "missing", "b")))
    store.put(_segment("b"))
    result = store.resolve_cross_links("a")
    assert [s.id for s in result] == ["b"]


def test_resolve_cross_links_unknown_segment_returns_empty():
    store = InMemorySegmentStore(VOCAB)
    store.put(_segment("a"))
    assert store.resolve_cross_links("nope") == ()
