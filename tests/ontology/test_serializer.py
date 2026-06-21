"""Unit tests for the frontmatter serializer (task 2.5).

Covers the ``serializer`` component from ``docuharnessx/ontology/serializer.py``
(Req 4.1, 4.4):

* ``parse_segment(text) -> ParsedSegment`` — split a leading ``---``-fenced YAML
  block into a raw mapping plus an opaque ``body`` (Req 4.1); raise
  ``MalformedFrontmatterError`` when the fence is missing or the YAML is invalid
  or not a mapping (feeds Req 6.3).
* ``to_segment(parsed, vocab) -> Segment`` — keep ``roles``/``intent`` as raw
  ids and coerce ``subjects`` to typed ``Subject`` against the vocabulary's
  prefixes; surface untypable subjects by raising ``MalformedSubjectError``
  rather than dropping them.
* ``serialize_segment(segment) -> str`` — deterministic front matter with a
  stable key order, subjects emitted in canonical ``prefix:local`` form.

Observable completion: a segment round-trips ``serialize -> parse`` to an
equivalent ``Segment`` (with subjects as typed ``Subject``, body preserved), and
malformed front matter raises ``MalformedFrontmatterError``.
"""

from __future__ import annotations

import pytest

from docuharnessx.ontology.errors import (
    MalformedFrontmatterError,
    MalformedSubjectError,
)
from docuharnessx.ontology.model import Subject
from docuharnessx.ontology.schema import SCHEMA_VERSION, Segment
from docuharnessx.ontology.serializer import (
    parse_segment,
    serialize_segment,
    to_segment,
)
from docuharnessx.ontology.vocabulary import default_profile


def _subject(raw: str) -> Subject:
    return Subject.parse(raw, frozenset(default_profile().subject_prefixes))


def _segment(**overrides) -> Segment:
    base = dict(
        id="seg-1",
        title="Install the harness",
        roles=["developer", "manager"],
        subjects=[_subject("component:auth"), _subject("tech:python")],
        intent="install",
        summary="A short summary.",
        related=["seg-2", "seg-3"],
        body="# Heading\n\nSome **markdown** body.\n",
    )
    base.update(overrides)
    return Segment(**base)


# --------------------------------------------------------------------------- #
# Round-trip equivalence (Observable completion; Req 4.1, 4.4)                 #
# --------------------------------------------------------------------------- #


def test_round_trip_serialize_then_parse_yields_equivalent_segment() -> None:
    vocab = default_profile()
    segment = _segment()

    text = serialize_segment(segment)
    parsed = to_segment(parse_segment(text), vocab)

    assert parsed.id == segment.id
    assert parsed.title == segment.title
    assert parsed.roles == segment.roles
    assert parsed.intent == segment.intent
    assert parsed.summary == segment.summary
    assert parsed.related == segment.related
    assert parsed.schema_version == segment.schema_version
    assert parsed.body == segment.body
    # Subjects compare equal as typed Subject value objects.
    assert parsed.subjects == segment.subjects
    assert all(isinstance(s, Subject) for s in parsed.subjects)


def test_round_trip_preserves_body_verbatim() -> None:
    vocab = default_profile()
    body = "Line one\n\n## Section\n\n- a\n- b\n\nTrailing text without newline"
    segment = _segment(body=body)

    parsed = to_segment(parse_segment(serialize_segment(segment)), vocab)

    assert parsed.body == body


def test_round_trip_with_optional_fields_omitted() -> None:
    vocab = default_profile()
    segment = Segment(
        id="seg-min",
        title="Minimal",
        roles=["developer"],
        subjects=[_subject("topic:overview")],
        intent="understand",
    )

    parsed = to_segment(parse_segment(serialize_segment(segment)), vocab)

    assert parsed.summary == ""
    assert parsed.related == []
    assert parsed.body == ""
    assert parsed.schema_version == SCHEMA_VERSION
    assert parsed.subjects == segment.subjects


# --------------------------------------------------------------------------- #
# Determinism + stable key order (Req 4.4)                                     #
# --------------------------------------------------------------------------- #


def test_serialize_is_deterministic_for_identical_segment() -> None:
    a = serialize_segment(_segment())
    b = serialize_segment(_segment())
    assert a == b


def test_serialize_emits_stable_canonical_key_order() -> None:
    text = serialize_segment(_segment())

    # The YAML keys appear in the canonical order before the closing fence.
    front = text.split("---", 2)[1]
    key_positions = {
        key: front.find(f"\n{key}:") if front.find(f"\n{key}:") != -1 else front.find(f"{key}:")
        for key in (
            "id",
            "title",
            "roles",
            "subjects",
            "intent",
            "summary",
            "related",
            "schema_version",
        )
    }
    ordered = [k for k, _ in sorted(key_positions.items(), key=lambda kv: kv[1])]
    assert ordered == [
        "id",
        "title",
        "roles",
        "subjects",
        "intent",
        "summary",
        "related",
        "schema_version",
    ]


def test_serialize_emits_subjects_in_canonical_string_form() -> None:
    text = serialize_segment(_segment())
    assert "component:auth" in text
    assert "tech:python" in text


# --------------------------------------------------------------------------- #
# Malformed frontmatter (feeds Req 6.3)                                        #
# --------------------------------------------------------------------------- #


def test_missing_fence_raises_malformed_frontmatter() -> None:
    with pytest.raises(MalformedFrontmatterError):
        parse_segment("no front matter here, just body text\n")


def test_invalid_yaml_raises_malformed_frontmatter() -> None:
    text = "---\nid: seg-1\n  : : bad: indentation\n: nope\n---\nbody\n"
    with pytest.raises(MalformedFrontmatterError):
        parse_segment(text)


def test_non_mapping_frontmatter_raises_malformed_frontmatter() -> None:
    text = "---\n- just\n- a\n- list\n---\nbody\n"
    with pytest.raises(MalformedFrontmatterError):
        parse_segment(text)


def test_empty_frontmatter_block_raises_malformed_frontmatter() -> None:
    text = "---\n---\nbody\n"
    with pytest.raises(MalformedFrontmatterError):
        parse_segment(text)


# --------------------------------------------------------------------------- #
# Untypable subjects are surfaced, not dropped (Req 4.1 invariant)            #
# --------------------------------------------------------------------------- #


def test_untypable_subject_raises_malformed_subject() -> None:
    vocab = default_profile()
    text = (
        "---\n"
        "id: seg-bad\n"
        "title: Bad subject\n"
        "roles:\n  - developer\n"
        "subjects:\n  - bogus:thing\n"
        "intent: install\n"
        "---\n"
        "body\n"
    )
    parsed = parse_segment(text)
    with pytest.raises(MalformedSubjectError):
        to_segment(parsed, vocab)


def test_untypable_subject_not_dropped_count_preserved_when_valid() -> None:
    vocab = default_profile()
    text = (
        "---\n"
        "id: seg-ok\n"
        "title: Two subjects\n"
        "roles:\n  - developer\n"
        "subjects:\n  - component:auth\n  - tech:python\n"
        "intent: install\n"
        "---\n"
        "body\n"
    )
    segment = to_segment(parse_segment(text), vocab)
    assert len(segment.subjects) == 2


# --------------------------------------------------------------------------- #
# parse_segment retains raw mapping + body (Req 4.1)                           #
# --------------------------------------------------------------------------- #


def test_parse_segment_keeps_roles_and_intent_as_raw_ids() -> None:
    text = (
        "---\n"
        "id: seg-1\n"
        "title: T\n"
        "roles:\n  - developer\n"
        "subjects:\n  - component:auth\n"
        "intent: install\n"
        "---\n"
        "body\n"
    )
    parsed = parse_segment(text)
    assert parsed.frontmatter["roles"] == ["developer"]
    assert parsed.frontmatter["intent"] == "install"
    assert parsed.body == "body\n"
