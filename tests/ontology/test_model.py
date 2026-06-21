"""Unit tests for the ontology axis primitives and subject namespace (task 2.1).

Covers ``AxisTerm`` (Req 2.4) and ``Subject`` (Req 3.1-3.5) from
``docuharnessx/ontology/model.py``.
"""

from __future__ import annotations

import dataclasses

import pytest

from docuharnessx.ontology.errors import MalformedSubjectError
from docuharnessx.ontology.model import AxisTerm, Subject

# Allowed-prefix sets are supplied by the caller (from a loaded Vocabulary),
# never read from a module constant. The default-profile prefixes are used here
# only as representative test data.
DEFAULT_PREFIXES = frozenset({"component", "tech", "artifact", "topic"})


# --------------------------------------------------------------------------- #
# AxisTerm (Req 2.4)                                                           #
# --------------------------------------------------------------------------- #


def test_axisterm_holds_id_label_description():
    term = AxisTerm(id="developer", label="Developer", description="Writes code")
    assert term.id == "developer"
    assert term.label == "Developer"
    assert term.description == "Writes code"


def test_axisterm_description_defaults_empty():
    term = AxisTerm(id="manager", label="Manager")
    assert term.description == ""


def test_axisterm_id_stable_when_label_changes():
    """The machine ``id`` is distinct from the display ``label`` (Req 2.4)."""
    original = AxisTerm(id="developer", label="Developer")
    relabeled = AxisTerm(id="developer", label="Software Engineer")
    assert original.id == relabeled.id == "developer"
    assert original.label != relabeled.label


def test_axisterm_is_immutable():
    term = AxisTerm(id="developer", label="Developer")
    with pytest.raises(dataclasses.FrozenInstanceError):
        term.label = "changed"  # type: ignore[misc]


def test_axisterm_equality_and_hashable():
    a = AxisTerm(id="developer", label="Developer", description="x")
    b = AxisTerm(id="developer", label="Developer", description="x")
    assert a == b
    assert hash(a) == hash(b)
    # Distinguished by id, not just label.
    assert a != AxisTerm(id="dev", label="Developer", description="x")


# --------------------------------------------------------------------------- #
# Subject parsing (Req 3.1-3.4)                                                #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("prefix", ["component", "tech", "artifact", "topic"])
def test_subject_parses_for_each_supplied_prefix(prefix):
    """Each prefix in the supplied vocabulary is accepted (Req 3.1)."""
    subject = Subject.parse(f"{prefix}:auth-service", DEFAULT_PREFIXES)
    assert subject.prefix == prefix
    assert subject.local == "auth-service"


def test_subject_local_is_open_free_form():
    """The portion after the prefix is open free-form text (Req 3.3)."""
    subject = Subject.parse("topic:anything goes here 123", DEFAULT_PREFIXES)
    assert subject.prefix == "topic"
    # local is not required to be a member of any fixed list.
    assert "anything" in subject.local


def test_subject_unknown_prefix_raises():
    """A prefix not present in the supplied set is malformed (Req 3.2)."""
    with pytest.raises(MalformedSubjectError) as exc:
        Subject.parse("bogus:foo", DEFAULT_PREFIXES)
    assert exc.value.value == "bogus:foo"


def test_subject_no_prefix_raises():
    """A value with no recognized prefix is malformed (Req 3.2)."""
    with pytest.raises(MalformedSubjectError):
        Subject.parse("no-colon-here", DEFAULT_PREFIXES)


def test_subject_empty_local_raises():
    """A recognized prefix with empty local name is malformed (Req 3.4)."""
    with pytest.raises(MalformedSubjectError):
        Subject.parse("component:", DEFAULT_PREFIXES)


def test_subject_whitespace_only_local_raises():
    """A whitespace-only local name is malformed (Req 3.4)."""
    with pytest.raises(MalformedSubjectError):
        Subject.parse("component:   ", DEFAULT_PREFIXES)


def test_subject_prefix_supplied_not_hardcoded():
    """Prefixes come from the caller; a custom set works (no module constant)."""
    custom = frozenset({"service"})
    subject = Subject.parse("service:billing", custom)
    assert subject.prefix == "service"
    # And a default prefix is rejected when not in the custom set.
    with pytest.raises(MalformedSubjectError):
        Subject.parse("component:foo", custom)


def test_subject_allowed_prefixes_tolerate_trailing_colon():
    """Allowed prefixes may be supplied bare or with a trailing colon."""
    with_colon = frozenset({"component:"})
    subject = Subject.parse("component:foo", with_colon)
    assert subject.prefix == "component"


# --------------------------------------------------------------------------- #
# Subject canonical + normalization (Req 3.5)                                  #
# --------------------------------------------------------------------------- #


def test_subject_canonical_is_prefix_colon_local():
    subject = Subject.parse("component:auth", DEFAULT_PREFIXES)
    assert subject.canonical() == "component:auth"


def test_subject_normalization_trims_surrounding_whitespace():
    subject = Subject.parse("  component:auth  ", DEFAULT_PREFIXES)
    assert subject.prefix == "component"
    assert subject.local == "auth"
    assert subject.canonical() == "component:auth"


def test_subject_normalization_is_idempotent():
    """parse(canonical(x)) == x (Req 3.5)."""
    subject = Subject.parse("  Component:Auth Service  ", DEFAULT_PREFIXES)
    again = Subject.parse(subject.canonical(), DEFAULT_PREFIXES)
    assert again == subject
    # A second canonical pass is byte-identical.
    assert again.canonical() == subject.canonical()


def test_subject_same_string_maps_to_same_canonical():
    """The same subject string always maps to the same canonical subject."""
    a = Subject.parse("  TECH:Python  ", DEFAULT_PREFIXES)
    b = Subject.parse("tech:python", DEFAULT_PREFIXES)
    assert a == b
    assert a.canonical() == b.canonical()


def test_subject_is_immutable():
    subject = Subject.parse("component:auth", DEFAULT_PREFIXES)
    with pytest.raises(dataclasses.FrozenInstanceError):
        subject.local = "changed"  # type: ignore[misc]


def test_subject_equality_and_hashable():
    a = Subject.parse("component:auth", DEFAULT_PREFIXES)
    b = Subject.parse("component:auth", DEFAULT_PREFIXES)
    assert a == b
    assert hash(a) == hash(b)
