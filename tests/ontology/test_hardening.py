"""Robustness hardening regressions (typed errors for spec-silent edge cases).

These pin two edge cases the adversarial validation lens surfaced: malformed
inputs must surface as typed ``OntologyError`` subclasses, never raw
``ValueError`` / ``FileNotFoundError``.
"""

import pytest

from docuharnessx.ontology import (
    FilesystemSegmentStore,
    MalformedFrontmatterError,
    OntologyError,
    Segment,
    Subject,
    default_profile,
    parse_segment,
    to_segment,
)

VOCAB = default_profile()


def _markdown(version: str) -> str:
    return (
        "---\n"
        "id: seg-a\n"
        "title: A\n"
        "roles:\n  - developer\n"
        "subjects:\n  - component:auth\n"
        "intent: install\n"
        f"schema_version: {version}\n"
        "---\n"
        "body\n"
    )


def test_non_integer_schema_version_raises_typed_error():
    parsed = parse_segment(_markdown("abc"))
    with pytest.raises(MalformedFrontmatterError) as exc:
        to_segment(parsed, VOCAB)
    # typed, names the segment, and not a raw ValueError leak
    assert isinstance(exc.value, OntologyError)
    assert exc.value.segment_id == "seg-a"
    assert "schema_version" in str(exc.value)


def test_integer_schema_version_still_parses():
    seg = to_segment(parse_segment(_markdown("1")), VOCAB)
    assert seg.schema_version == 1


def test_filesystem_store_rejects_path_separator_id(tmp_path):
    store = FilesystemSegmentStore(tmp_path / "segments", VOCAB)
    bad = Segment(
        id="a/b",
        title="A",
        roles=["developer"],
        subjects=[Subject.parse("component:auth", frozenset(VOCAB.subject_prefixes))],
        intent="install",
    )
    with pytest.raises(MalformedFrontmatterError) as exc:
        store.put(bad)
    assert isinstance(exc.value, OntologyError)
    # nothing escaped the store directory
    assert not (tmp_path / "a").exists()


def test_filesystem_store_rejects_dotdot_id(tmp_path):
    store = FilesystemSegmentStore(tmp_path / "segments", VOCAB)
    bad = Segment(
        id="..",
        title="A",
        roles=["developer"],
        subjects=[Subject.parse("component:auth", frozenset(VOCAB.subject_prefixes))],
        intent="install",
    )
    with pytest.raises(MalformedFrontmatterError):
        store.put(bad)


def test_filesystem_store_accepts_safe_id(tmp_path):
    store = FilesystemSegmentStore(tmp_path / "segments", VOCAB)
    good = Segment(
        id="seg-ok",
        title="A",
        roles=["developer"],
        subjects=[Subject.parse("component:auth", frozenset(VOCAB.subject_prefixes))],
        intent="install",
    )
    store.put(good)
    assert store.list_segments()[0].id == "seg-ok"
