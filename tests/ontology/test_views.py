"""Tests for role-view derivation (task 5.1).

Covers Req 10.1-10.5:

* ``build_role_view`` returns all segments carrying the given role id (Req 10.1).
* The view is ordered by the loaded ``Vocabulary``'s intent order (Req 10.2)
  with a stable secondary key (segment id) for intent ties (Req 10.4).
* A multi-role segment appears in EVERY role view it carries, without
  duplicating stored content (Req 10.3).
* A role with no matching segments yields an empty view, NOT an error (Req 10.5).
* Identical inputs produce identical ordered output (determinism, Req 11.2).
"""

from __future__ import annotations

from docuharnessx.ontology.model import Subject
from docuharnessx.ontology.schema import Segment
from docuharnessx.ontology.store import InMemorySegmentStore
from docuharnessx.ontology.views import build_role_view
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
) -> Segment:
    return Segment(
        id=seg_id,
        title=f"Title {seg_id}",
        roles=list(roles),
        subjects=[_subject(s) for s in subjects],
        intent=intent,
    )


# --------------------------------------------------------------------------- #
# Req 10.1: all segments carrying the role appear in its view                  #
# --------------------------------------------------------------------------- #


def test_role_view_returns_all_segments_with_role():
    store = InMemorySegmentStore(VOCAB)
    store.put(_segment("a", roles=("developer",)))
    store.put(_segment("b", roles=("developer",), intent="use"))
    store.put(_segment("c", roles=("manager",)))
    view = build_role_view(store, "developer", VOCAB)
    assert {s.id for s in view} == {"a", "b"}


def test_role_view_returns_tuple():
    store = InMemorySegmentStore(VOCAB)
    store.put(_segment("a"))
    view = build_role_view(store, "developer", VOCAB)
    assert isinstance(view, tuple)


# --------------------------------------------------------------------------- #
# Req 10.3: a multi-role segment appears in EACH of its roles' views           #
# --------------------------------------------------------------------------- #


def test_multi_role_segment_appears_in_each_role_view():
    store = InMemorySegmentStore(VOCAB)
    multi = _segment("shared", roles=("developer", "manager", "researcher"))
    store.put(multi)
    store.put(_segment("dev-only", roles=("developer",), intent="use"))

    dev_view = build_role_view(store, "developer", VOCAB)
    mgr_view = build_role_view(store, "manager", VOCAB)
    res_view = build_role_view(store, "researcher", VOCAB)

    assert "shared" in {s.id for s in dev_view}
    assert "shared" in {s.id for s in mgr_view}
    assert "shared" in {s.id for s in res_view}
    # No duplication of stored content: the same Segment object/value is reused.
    (mgr_seg,) = mgr_view
    assert mgr_seg.id == "shared"
    assert mgr_seg.roles == ["developer", "manager", "researcher"]


# --------------------------------------------------------------------------- #
# Req 10.2 + 10.4: ordered by intent order, then a stable secondary key (id)   #
# --------------------------------------------------------------------------- #


def test_role_view_ordered_by_intent_order():
    store = InMemorySegmentStore(VOCAB)
    # Insert in an order that is NOT the intent order; intent_order() is
    # (install, configure, use, troubleshoot, ...).
    store.put(_segment("seg-use", intent="use"))
    store.put(_segment("seg-install", intent="install"))
    store.put(_segment("seg-configure", intent="configure"))
    view = build_role_view(store, "developer", VOCAB)
    assert [s.intent for s in view] == ["install", "configure", "use"]


def test_role_view_tie_break_is_stable_by_id():
    store = InMemorySegmentStore(VOCAB)
    # Three segments share the same intent; tie-break must be by id.
    store.put(_segment("z", intent="install"))
    store.put(_segment("a", intent="install"))
    store.put(_segment("m", intent="install"))
    view = build_role_view(store, "developer", VOCAB)
    assert [s.id for s in view] == ["a", "m", "z"]


def test_role_view_intent_order_then_tie_break_combined():
    store = InMemorySegmentStore(VOCAB)
    # Two intents, two segments each, inserted out of order.
    store.put(_segment("use-z", intent="use"))
    store.put(_segment("install-z", intent="install"))
    store.put(_segment("use-a", intent="use"))
    store.put(_segment("install-a", intent="install"))
    view = build_role_view(store, "developer", VOCAB)
    # install (order 0) before use (order 2); within each, id ascending.
    assert [s.id for s in view] == ["install-a", "install-z", "use-a", "use-z"]


# --------------------------------------------------------------------------- #
# Req 10.5: a role with no matching segments yields an empty view, NOT error   #
# --------------------------------------------------------------------------- #


def test_role_with_no_segments_yields_empty_view():
    store = InMemorySegmentStore(VOCAB)
    store.put(_segment("a", roles=("developer",)))
    # 'manager' is a valid role but carries no segments.
    view = build_role_view(store, "manager", VOCAB)
    assert view == ()


def test_empty_store_yields_empty_view():
    store = InMemorySegmentStore(VOCAB)
    view = build_role_view(store, "developer", VOCAB)
    assert view == ()


# --------------------------------------------------------------------------- #
# Determinism (Req 11.2)                                                       #
# --------------------------------------------------------------------------- #


def test_role_view_is_deterministic_across_runs():
    store = InMemorySegmentStore(VOCAB)
    store.put(_segment("use-b", intent="use"))
    store.put(_segment("install-a", intent="install"))
    store.put(_segment("use-a", intent="use"))
    first = [s.id for s in build_role_view(store, "developer", VOCAB)]
    second = [s.id for s in build_role_view(store, "developer", VOCAB)]
    assert first == second
    assert first == ["install-a", "use-a", "use-b"]


# --------------------------------------------------------------------------- #
# Unknown-intent segment ordered deterministically (placed last, then by id)   #
# --------------------------------------------------------------------------- #


def test_unknown_intent_segment_ordered_last_then_by_id():
    store = InMemorySegmentStore(VOCAB)
    # Build segments directly and inject into the store's backing map, bypassing
    # validate-on-put, because an unknown intent would be rejected by put().
    known = _segment("known", intent="install")
    unknown_z = _segment("zzz", intent="install")
    unknown_a = _segment("aaa", intent="install")
    # Mutate intent to an id NOT in the vocabulary after construction.
    object.__setattr__(unknown_z, "intent", "not-an-intent")
    object.__setattr__(unknown_a, "intent", "not-an-intent")
    store._segments[known.id] = known  # type: ignore[attr-defined]
    store._segments[unknown_z.id] = unknown_z  # type: ignore[attr-defined]
    store._segments[unknown_a.id] = unknown_a  # type: ignore[attr-defined]

    view = build_role_view(store, "developer", VOCAB)
    # Known intent first; unknown-intent segments sorted last, by id.
    assert [s.id for s in view] == ["known", "aaa", "zzz"]
