"""Unit tests for the segment schema and version contract (task 2.3).

Covers the ``Segment`` dataclass, ``SCHEMA_VERSION``, ``REQUIRED_FIELDS``, the
documented per-version frozen field set, and the version-compatibility check
from ``docuharnessx/ontology/schema.py`` (Req 4.1-4.6, 5.1-5.5).
"""

from __future__ import annotations

import dataclasses

import pytest

from docuharnessx.ontology.errors import VersionMismatchError
from docuharnessx.ontology.model import Subject
from docuharnessx.ontology.schema import (
    FROZEN_FIELDS_BY_VERSION,
    REQUIRED_FIELDS,
    SCHEMA_VERSION,
    Segment,
    check_version,
    is_version_compatible,
)


def _subject(prefix: str = "component", local: str = "loader") -> Subject:
    return Subject.parse(f"{prefix}:{local}", frozenset({prefix}))


# --------------------------------------------------------------------------- #
# Segment structure & types (Req 4.1, 4.2, 4.4)                                #
# --------------------------------------------------------------------------- #


def test_segment_holds_full_field_set_with_declared_types() -> None:
    seg = Segment(
        id="seg-1",
        title="Install the harness",
        roles=["developer", "manager"],
        subjects=[_subject()],
        intent="install",
        summary="how to install",
        related=["seg-2"],
        body="# Body\n",
        schema_version=SCHEMA_VERSION,
    )
    assert seg.id == "seg-1"
    assert seg.title == "Install the harness"
    assert seg.roles == ["developer", "manager"]  # role ids (strings), not enums
    assert all(isinstance(s, Subject) for s in seg.subjects)
    assert seg.intent == "install"  # intent id (string), not an enum
    assert seg.summary == "how to install"
    assert seg.related == ["seg-2"]
    assert seg.body == "# Body\n"
    assert seg.schema_version == SCHEMA_VERSION


def test_segment_roles_and_intent_are_string_ids_not_enum_members() -> None:
    seg = Segment(
        id="seg-1",
        title="t",
        roles=["developer"],
        subjects=[_subject()],
        intent="install",
    )
    assert isinstance(seg.intent, str)
    assert all(isinstance(r, str) for r in seg.roles)


# --------------------------------------------------------------------------- #
# Optional-field defaults (Req 4.3)                                            #
# --------------------------------------------------------------------------- #


def test_optional_fields_default_correctly() -> None:
    seg = Segment(
        id="seg-1",
        title="t",
        roles=["developer"],
        subjects=[_subject()],
        intent="install",
    )
    assert seg.summary == ""
    assert seg.related == []
    assert seg.body == ""
    assert seg.schema_version == SCHEMA_VERSION


def test_related_default_is_independent_per_instance() -> None:
    a = Segment(id="a", title="t", roles=["developer"], subjects=[_subject()], intent="install")
    b = Segment(id="b", title="t", roles=["developer"], subjects=[_subject()], intent="install")
    a.related.append("x")
    assert b.related == []  # no shared mutable default


# --------------------------------------------------------------------------- #
# Required-field set (Req 4.2)                                                 #
# --------------------------------------------------------------------------- #


def test_required_fields_set_is_exact() -> None:
    assert REQUIRED_FIELDS == ("id", "title", "roles", "subjects", "intent")


# --------------------------------------------------------------------------- #
# SCHEMA_VERSION & frozen field set (Req 5.1, 5.4)                             #
# --------------------------------------------------------------------------- #


def test_schema_version_is_single_int_constant() -> None:
    assert isinstance(SCHEMA_VERSION, int)


def test_frozen_field_set_documented_for_current_version() -> None:
    assert SCHEMA_VERSION in FROZEN_FIELDS_BY_VERSION
    frozen = FROZEN_FIELDS_BY_VERSION[SCHEMA_VERSION]
    # The frozen frontmatter field set (+ body + schema_version) per design.
    assert set(frozen) == {
        "id",
        "title",
        "roles",
        "subjects",
        "intent",
        "summary",
        "related",
        "body",
        "schema_version",
    }


# --------------------------------------------------------------------------- #
# Version compatibility (Req 5.2, 5.3)                                         #
# --------------------------------------------------------------------------- #


def test_omitted_version_is_treated_as_current() -> None:
    assert is_version_compatible(None) is True


def test_current_version_is_compatible() -> None:
    assert is_version_compatible(SCHEMA_VERSION) is True


def test_incompatible_declared_version_is_reported_incompatible() -> None:
    assert is_version_compatible(SCHEMA_VERSION + 1) is False
    assert is_version_compatible(SCHEMA_VERSION - 1) is False


def test_check_version_passes_for_none_and_current() -> None:
    check_version(None)
    check_version(SCHEMA_VERSION)  # must not raise


def test_check_version_raises_version_mismatch_for_incompatible() -> None:
    with pytest.raises(VersionMismatchError) as exc:
        check_version(SCHEMA_VERSION + 1, segment_id="seg-1")
    assert exc.value.declared == SCHEMA_VERSION + 1
    assert exc.value.supported == SCHEMA_VERSION
    assert exc.value.segment_id == "seg-1"


def test_version_compatibility_is_deterministic() -> None:
    assert [is_version_compatible(None) for _ in range(5)] == [True] * 5
