"""Unit tests for namespaced MkDocs tag emission (task 2.4).

Covers ``emit_tags(segment, vocab)`` from ``docuharnessx/ontology/tags.py``
(Req 8.1-8.5): exact ``role:`` / ``intent:`` / ``subject:`` namespacing, typed
subject-prefix preservation, deterministic ordering, and emission only for axis
values that are valid members of the supplied ``Vocabulary``.
"""

from __future__ import annotations

from docuharnessx.ontology.model import Subject
from docuharnessx.ontology.schema import Segment
from docuharnessx.ontology.tags import emit_tags
from docuharnessx.ontology.vocabulary import default_profile


def _subject(raw: str) -> Subject:
    """Parse ``raw`` against the default profile's prefixes."""
    return Subject.parse(raw, frozenset(default_profile().subject_prefixes))


def _segment(**overrides) -> Segment:
    base = dict(
        id="seg-1",
        title="Install the harness",
        roles=["developer", "manager"],
        subjects=[_subject("component:auth"), _subject("tech:python")],
        intent="install",
    )
    base.update(overrides)
    return Segment(**base)


# --------------------------------------------------------------------------- #
# Exact namespaced tag strings (Req 8.1, 8.2)                                  #
# --------------------------------------------------------------------------- #


def test_emit_tags_exact_strings_for_multi_role_multi_subject_segment() -> None:
    vocab = default_profile()
    seg = _segment()

    tags = emit_tags(seg, vocab)

    assert tags == (
        "role:developer",
        "role:manager",
        "intent:install",
        "subject:component:auth",
        "subject:tech:python",
    )


def test_emit_tags_returns_a_tuple() -> None:
    assert isinstance(emit_tags(_segment(), default_profile()), tuple)


def test_emit_tags_only_uses_role_intent_subject_namespaces() -> None:
    tags = emit_tags(_segment(), default_profile())
    for tag in tags:
        assert tag.split(":", 1)[0] in {"role", "intent", "subject"}


# --------------------------------------------------------------------------- #
# Subject prefix preservation (Req 8.3)                                        #
# --------------------------------------------------------------------------- #


def test_emit_tags_preserves_typed_subject_prefix() -> None:
    seg = _segment(subjects=[_subject("component:auth")])
    tags = emit_tags(seg, default_profile())
    # The typed prefix is preserved: subject:component:auth, NOT subject:auth.
    assert "subject:component:auth" in tags
    assert "subject:auth" not in tags


# --------------------------------------------------------------------------- #
# Vocabulary-valid-only emission (Req 8.5)                                     #
# --------------------------------------------------------------------------- #


def test_emit_tags_skips_role_not_in_vocabulary() -> None:
    seg = _segment(roles=["developer", "not-a-real-role"])
    tags = emit_tags(seg, default_profile())
    assert "role:developer" in tags
    assert "role:not-a-real-role" not in tags
    assert not any(t == "role:not-a-real-role" for t in tags)


def test_emit_tags_skips_intent_not_in_vocabulary() -> None:
    seg = _segment(intent="not-a-real-intent")
    tags = emit_tags(seg, default_profile())
    assert not any(t.startswith("intent:") for t in tags)


def test_emit_tags_skips_subject_with_prefix_not_in_vocabulary() -> None:
    # Build a Subject whose prefix is NOT a member of the vocabulary's prefixes.
    # (Constructed directly to bypass parse-time prefix validation.)
    rogue = Subject(prefix="bogus", local="thing")
    seg = _segment(subjects=[_subject("component:auth"), rogue])
    tags = emit_tags(seg, default_profile())
    assert "subject:component:auth" in tags
    assert "subject:bogus:thing" not in tags


def test_emit_tags_emits_valid_subject_alongside_invalid() -> None:
    rogue = Subject(prefix="bogus", local="thing")
    seg = _segment(
        roles=["developer"],
        subjects=[rogue, _subject("topic:onboarding")],
    )
    tags = emit_tags(seg, default_profile())
    assert tags == (
        "role:developer",
        "intent:install",
        "subject:topic:onboarding",
    )


# --------------------------------------------------------------------------- #
# Determinism (Req 8.4)                                                        #
# --------------------------------------------------------------------------- #


def test_emit_tags_is_deterministic_across_repeated_calls() -> None:
    vocab = default_profile()
    seg = _segment()
    first = emit_tags(seg, vocab)
    for _ in range(5):
        assert emit_tags(seg, vocab) == first


def test_emit_tags_preserves_declared_axis_order() -> None:
    # Roles and subjects are emitted in the segment's declared order.
    seg = _segment(
        roles=["manager", "developer"],
        subjects=[_subject("topic:onboarding"), _subject("component:auth")],
    )
    tags = emit_tags(seg, default_profile())
    assert tags == (
        "role:manager",
        "role:developer",
        "intent:install",
        "subject:topic:onboarding",
        "subject:component:auth",
    )


def test_emit_tags_empty_when_no_axis_value_is_valid() -> None:
    seg = _segment(
        roles=["nope"],
        subjects=[Subject(prefix="bogus", local="x")],
        intent="nope",
    )
    assert emit_tags(seg, default_profile()) == ()
