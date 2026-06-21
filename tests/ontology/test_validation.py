"""Unit tests for single-segment validation against a vocabulary (task 3.1).

Covers ``validate_segment(segment, vocab) -> ValidationResult`` from
``docuharnessx/ontology/validation.py``: parseability/version compatibility,
required-field presence, non-empty ``roles``/``subjects``, role/intent id
membership, subject-prefix membership, error aggregation (all errors, not just
the first), and determinism (Req 6.1-6.7).
"""

from __future__ import annotations

from docuharnessx.ontology.errors import (
    MalformedSubjectError,
    MissingFieldError,
    UnknownIntentError,
    UnknownRoleError,
    ValidationResult,
    VersionMismatchError,
)
from docuharnessx.ontology.model import AxisTerm, Subject
from docuharnessx.ontology.schema import SCHEMA_VERSION, Segment
from docuharnessx.ontology.validation import validate_segment
from docuharnessx.ontology.vocabulary import Vocabulary, default_profile


def _subject(prefix: str = "component", local: str = "loader") -> Subject:
    return Subject.parse(f"{prefix}:{local}", frozenset({prefix}))


def _valid_segment() -> Segment:
    return Segment(
        id="seg-1",
        title="Install the harness",
        roles=["developer", "manager"],
        subjects=[_subject()],
        intent="install",
        summary="A short summary.",
        related=[],
        body="Body text.",
    )


def _small_vocab() -> Vocabulary:
    """A custom vocabulary that defines 'developer'/'install' but not 'manager'."""
    return Vocabulary(
        roles=(AxisTerm("developer", "Developer"),),
        intents=(AxisTerm("install", "Install"),),
        subject_prefixes=("component:",),
    )


# --------------------------------------------------------------------------- #
# Happy path (Req 6.1)                                                         #
# --------------------------------------------------------------------------- #


def test_valid_segment_is_valid_with_no_errors() -> None:
    result = validate_segment(_valid_segment(), default_profile())
    assert isinstance(result, ValidationResult)
    assert result.is_valid is True
    assert result.errors == ()
    assert result.segment_id == "seg-1"


# --------------------------------------------------------------------------- #
# Error aggregation: ALL errors, not just the first (Req 6.6)                  #
# --------------------------------------------------------------------------- #


def test_multiple_faults_returns_all_errors() -> None:
    vocab = default_profile()
    # Faults: missing title, unknown role, unknown intent, empty subjects.
    # Build a subject with a prefix not in the vocab to also force a subject
    # fault — construct directly to bypass parse-time rejection.
    bad_subject = Subject(prefix="bogus", local="x")
    seg = Segment(
        id="seg-x",
        title="",  # missing required field
        roles=["developer", "nope-role"],  # one unknown role
        subjects=[bad_subject],  # bad prefix
        intent="not-an-intent",  # unknown intent
    )
    result = validate_segment(seg, vocab)

    assert result.is_valid is False
    types = [type(e) for e in result.errors]
    # Missing title.
    assert MissingFieldError in types
    assert any(
        isinstance(e, MissingFieldError) and e.field == "title"
        for e in result.errors
    )
    # Unknown role.
    assert any(
        isinstance(e, UnknownRoleError) and e.value == "nope-role"
        for e in result.errors
    )
    # Unknown intent.
    assert any(
        isinstance(e, UnknownIntentError) and e.value == "not-an-intent"
        for e in result.errors
    )
    # Malformed subject (bad prefix).
    assert any(
        isinstance(e, MalformedSubjectError) for e in result.errors
    )


def test_empty_subjects_and_roles_reported_as_missing_fields() -> None:
    vocab = default_profile()
    seg = Segment(
        id="seg-empty",
        title="Title",
        roles=[],
        subjects=[],
        intent="install",
    )
    result = validate_segment(seg, vocab)
    fields = [e.field for e in result.errors if isinstance(e, MissingFieldError)]
    assert "roles" in fields
    assert "subjects" in fields


def test_missing_id_reported_and_segment_id_none() -> None:
    vocab = default_profile()
    seg = Segment(
        id="",
        title="Title",
        roles=["developer"],
        subjects=[_subject()],
        intent="install",
    )
    result = validate_segment(seg, vocab)
    assert result.segment_id is None
    assert any(
        isinstance(e, MissingFieldError) and e.field == "id"
        for e in result.errors
    )
    # Every collected error carries segment_id None when the id is missing.
    for err in result.errors:
        assert getattr(err, "segment_id", None) is None


# --------------------------------------------------------------------------- #
# Vocabulary-relative membership (Req 6.4)                                     #
# --------------------------------------------------------------------------- #


def test_role_intent_accepted_under_one_vocab_rejected_under_another() -> None:
    seg = Segment(
        id="seg-2",
        title="Title",
        roles=["developer", "manager"],
        subjects=[_subject()],
        intent="install",
    )
    # default_profile defines manager + install -> valid.
    assert validate_segment(seg, default_profile()).is_valid is True

    # small vocab does NOT define 'manager' -> rejected; 'developer'/'install' ok.
    result = validate_segment(seg, _small_vocab())
    assert result.is_valid is False
    assert any(
        isinstance(e, UnknownRoleError) and e.value == "manager"
        for e in result.errors
    )
    # developer is accepted under the small vocab.
    assert not any(
        isinstance(e, UnknownRoleError) and e.value == "developer"
        for e in result.errors
    )


def test_subject_prefix_membership_is_vocab_relative() -> None:
    # 'tech:' is valid in the default profile but not in the small vocab.
    seg = Segment(
        id="seg-3",
        title="Title",
        roles=["developer"],
        subjects=[Subject(prefix="tech", local="python")],
        intent="install",
    )
    assert validate_segment(seg, default_profile()).is_valid is True

    result = validate_segment(seg, _small_vocab())
    assert any(isinstance(e, MalformedSubjectError) for e in result.errors)


# --------------------------------------------------------------------------- #
# Version compatibility (Req 5.2 -> reported in validation)                    #
# --------------------------------------------------------------------------- #


def test_version_mismatch_reported() -> None:
    seg = _valid_segment()
    seg.schema_version = SCHEMA_VERSION + 99
    result = validate_segment(seg, default_profile())
    assert result.is_valid is False
    assert any(isinstance(e, VersionMismatchError) for e in result.errors)


def test_omitted_version_is_compatible() -> None:
    seg = _valid_segment()
    seg.schema_version = None  # treated as current
    result = validate_segment(seg, default_profile())
    assert not any(isinstance(e, VersionMismatchError) for e in result.errors)


# --------------------------------------------------------------------------- #
# Determinism (Req 6.7)                                                        #
# --------------------------------------------------------------------------- #


def test_repeated_runs_produce_identical_results() -> None:
    vocab = default_profile()
    bad_subject = Subject(prefix="bogus", local="x")
    seg = Segment(
        id="seg-d",
        title="",
        roles=["developer", "nope-role"],
        subjects=[bad_subject],
        intent="not-an-intent",
    )
    first = validate_segment(seg, vocab)
    second = validate_segment(seg, vocab)

    def fingerprint(result: ValidationResult) -> list[str]:
        return [f"{type(e).__name__}:{str(e)}" for e in result.errors]

    assert fingerprint(first) == fingerprint(second)
    # Stable, documented order: version, required-fields, roles, intent, subjects.
    assert len(first.errors) == len(second.errors)


def test_documented_error_ordering() -> None:
    vocab = default_profile()
    seg = Segment(
        id="seg-order",
        title="",  # missing field
        roles=["nope-role"],  # unknown role
        subjects=[Subject(prefix="bogus", local="x")],  # bad subject
        intent="not-an-intent",  # unknown intent
    )
    seg.schema_version = SCHEMA_VERSION + 1  # version mismatch first
    result = validate_segment(seg, vocab)
    order = [type(e).__name__ for e in result.errors]
    # Version error precedes required-field errors which precede role/intent/subject.
    assert order.index("VersionMismatchError") < order.index("MissingFieldError")
    assert order.index("MissingFieldError") < order.index("UnknownRoleError")
    assert order.index("UnknownRoleError") < order.index("UnknownIntentError")
    assert order.index("UnknownIntentError") < order.index("MalformedSubjectError")
