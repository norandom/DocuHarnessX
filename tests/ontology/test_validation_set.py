"""Unit tests for segment-set validation and cross-link resolution (task 3.2).

Covers, from ``docuharnessx/ontology/validation.py``:

* ``validate_segment_set(segments, vocab) -> SetValidationResult`` — enforces
  unique ``id`` across the set (Req 4.6) then resolves each ``related`` entry
  against the id index, reporting unknown targets (Req 7.1, 7.2) and
  self-references (Req 7.4); a clean set is valid.
* ``resolve_links(segment, index) -> list[Segment]`` — deterministic resolution
  of a segment's ``related`` entries to the target segments (Req 7.3).

Determinism: identical input sets yield identical ``SetValidationResult.errors``
order and identical resolution output (Req 6.7, 7.3, 11.2).
"""

from __future__ import annotations

from docuharnessx.ontology.errors import (
    DuplicateIdError,
    SelfReferenceError,
    SetValidationResult,
    UnresolvedLinkError,
)
from docuharnessx.ontology.model import Subject
from docuharnessx.ontology.schema import Segment
from docuharnessx.ontology.validation import resolve_links, validate_segment_set
from docuharnessx.ontology.vocabulary import default_profile


def _subject(local: str = "loader") -> Subject:
    return Subject.parse(f"component:{local}", frozenset({"component:"}))


def _seg(seg_id: str, related: list[str] | None = None) -> Segment:
    return Segment(
        id=seg_id,
        title=f"Title {seg_id}",
        roles=["developer"],
        subjects=[_subject()],
        intent="install",
        related=list(related or []),
    )


# --------------------------------------------------------------------------- #
# Clean set (Req 7.1, 7.3)                                                     #
# --------------------------------------------------------------------------- #


def test_clean_set_is_valid() -> None:
    segments = [_seg("a", ["b"]), _seg("b", ["a"]), _seg("c")]
    result = validate_segment_set(segments, default_profile())
    assert isinstance(result, SetValidationResult)
    assert result.is_valid is True
    assert result.errors == ()


# --------------------------------------------------------------------------- #
# Duplicate id (Req 4.6)                                                       #
# --------------------------------------------------------------------------- #


def test_duplicate_id_rejected_naming_the_id() -> None:
    segments = [_seg("a"), _seg("b"), _seg("a")]
    result = validate_segment_set(segments, default_profile())
    assert result.is_valid is False
    dup = [e for e in result.errors if isinstance(e, DuplicateIdError)]
    assert len(dup) == 1
    assert dup[0].segment_id == "a"


def test_triple_duplicate_reports_each_occurrence_after_first() -> None:
    # Three 'a' entries -> two DuplicateIdError (2nd and 3rd occurrences).
    segments = [_seg("a"), _seg("a"), _seg("a")]
    result = validate_segment_set(segments, default_profile())
    dup = [e for e in result.errors if isinstance(e, DuplicateIdError)]
    assert len(dup) == 2
    assert all(e.segment_id == "a" for e in dup)


# --------------------------------------------------------------------------- #
# Unresolved related target (Req 7.1, 7.2)                                     #
# --------------------------------------------------------------------------- #


def test_unresolved_related_target_rejected_naming_missing_id() -> None:
    segments = [_seg("a", ["ghost"]), _seg("b")]
    result = validate_segment_set(segments, default_profile())
    assert result.is_valid is False
    unresolved = [e for e in result.errors if isinstance(e, UnresolvedLinkError)]
    assert len(unresolved) == 1
    assert unresolved[0].target_id == "ghost"
    assert unresolved[0].segment_id == "a"


# --------------------------------------------------------------------------- #
# Self-reference (Req 7.4)                                                     #
# --------------------------------------------------------------------------- #


def test_self_reference_rejected() -> None:
    segments = [_seg("a", ["a"]), _seg("b")]
    result = validate_segment_set(segments, default_profile())
    assert result.is_valid is False
    selfrefs = [e for e in result.errors if isinstance(e, SelfReferenceError)]
    assert len(selfrefs) == 1
    assert selfrefs[0].segment_id == "a"
    # A self-reference is NOT also reported as unresolved.
    assert not any(isinstance(e, UnresolvedLinkError) for e in result.errors)


# --------------------------------------------------------------------------- #
# Valid link resolution in stable order (Req 7.3)                             #
# --------------------------------------------------------------------------- #


def test_resolve_links_returns_targets_in_declared_order() -> None:
    a = _seg("a", ["c", "b"])
    b = _seg("b")
    c = _seg("c")
    index = {s.id: s for s in (a, b, c)}
    resolved = resolve_links(a, index)
    # Declared order preserved: c then b.
    assert [s.id for s in resolved] == ["c", "b"]
    assert resolved[0] is c
    assert resolved[1] is b


def test_resolve_links_skips_unresolved_and_self() -> None:
    a = _seg("a", ["a", "b", "ghost"])
    b = _seg("b")
    index = {s.id: s for s in (a, b)}
    resolved = resolve_links(a, index)
    # Self and unknown targets are dropped from resolution output.
    assert [s.id for s in resolved] == ["b"]


def test_resolve_links_empty_related_returns_empty() -> None:
    a = _seg("a")
    index = {"a": a}
    assert resolve_links(a, index) == []


# --------------------------------------------------------------------------- #
# Determinism (Req 6.7, 7.3, 11.2)                                            #
# --------------------------------------------------------------------------- #


def test_repeated_runs_produce_identical_results() -> None:
    vocab = default_profile()
    segments = [
        _seg("a", ["a", "ghost"]),  # self + unresolved
        _seg("b", ["x"]),  # unresolved
        _seg("a"),  # duplicate id
    ]

    def fingerprint(result: SetValidationResult) -> list[str]:
        return [f"{type(e).__name__}:{str(e)}" for e in result.errors]

    first = validate_segment_set(segments, vocab)
    second = validate_segment_set(segments, vocab)
    assert fingerprint(first) == fingerprint(second)


def test_error_ordering_duplicates_before_cross_links() -> None:
    segments = [_seg("a", ["ghost"]), _seg("a")]
    result = validate_segment_set(segments, default_profile())
    order = [type(e).__name__ for e in result.errors]
    # Id-uniqueness errors precede cross-link errors.
    assert order.index("DuplicateIdError") < order.index("UnresolvedLinkError")
