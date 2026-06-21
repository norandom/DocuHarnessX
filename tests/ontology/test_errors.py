"""Tests for the typed error and result model (task 1.2).

These cover the discriminated error types listed in design.md's `errors`
component plus the `ValidationResult` / `SetValidationResult` aggregates.

Per design.md (Error Strategy): the error types carry the offending
value/field and the segment-or-config identifier where applicable, and are
both structured records and raisable exceptions (the serializer and
`Subject.parse` raise them; validation collects them into results).
"""

from __future__ import annotations

import pytest

from docuharnessx.ontology import errors


# --------------------------------------------------------------------------- #
# Base / discriminated-error contract                                         #
# --------------------------------------------------------------------------- #


def test_all_designed_error_types_are_exported():
    for name in (
        "OntologyError",
        "MalformedConfigError",
        "MalformedFrontmatterError",
        "MissingFieldError",
        "UnknownRoleError",
        "UnknownIntentError",
        "MalformedSubjectError",
        "VersionMismatchError",
        "DuplicateIdError",
        "UnresolvedLinkError",
        "SelfReferenceError",
        "IdConflictError",
        "ValidationResult",
        "SetValidationResult",
    ):
        assert hasattr(errors, name), f"errors.{name} is missing"


def test_every_error_type_is_an_exception_subclass():
    error_types = [
        errors.MalformedConfigError,
        errors.MalformedFrontmatterError,
        errors.MissingFieldError,
        errors.UnknownRoleError,
        errors.UnknownIntentError,
        errors.MalformedSubjectError,
        errors.VersionMismatchError,
        errors.DuplicateIdError,
        errors.UnresolvedLinkError,
        errors.SelfReferenceError,
        errors.IdConflictError,
    ]
    for et in error_types:
        assert issubclass(et, errors.OntologyError)
        assert issubclass(et, Exception)


# --------------------------------------------------------------------------- #
# Config-level error (Req 1.6)                                                 #
# --------------------------------------------------------------------------- #


def test_malformed_config_error_carries_config_identifier():
    err = errors.MalformedConfigError(
        config_path=".docuharnessx/ontology.yaml",
        reason="missing required key: roles",
    )
    assert err.config_path == ".docuharnessx/ontology.yaml"
    assert err.reason == "missing required key: roles"
    # it must be raisable and carry the identifier in its message
    with pytest.raises(errors.MalformedConfigError) as excinfo:
        raise err
    assert ".docuharnessx/ontology.yaml" in str(excinfo.value)


# --------------------------------------------------------------------------- #
# Frontmatter / field / axis errors (Req 6.2-6.5)                             #
# --------------------------------------------------------------------------- #


def test_malformed_frontmatter_error_identifies_segment():
    err = errors.MalformedFrontmatterError(segment_id="seg-1", reason="no fence")
    assert err.segment_id == "seg-1"
    assert err.reason == "no fence"
    assert "seg-1" in str(err)


def test_missing_field_error_carries_field_and_segment():
    err = errors.MissingFieldError(field="title", segment_id="seg-2")
    assert err.field == "title"
    assert err.segment_id == "seg-2"
    assert "title" in str(err)


def test_unknown_role_error_carries_value_and_field_and_segment():
    err = errors.UnknownRoleError(value="wizard", field="roles", segment_id="seg-3")
    assert err.value == "wizard"
    assert err.field == "roles"
    assert err.segment_id == "seg-3"
    assert "wizard" in str(err)


def test_unknown_intent_error_carries_value_and_field_and_segment():
    err = errors.UnknownIntentError(value="teleport", field="intent", segment_id="seg-4")
    assert err.value == "teleport"
    assert err.field == "intent"
    assert err.segment_id == "seg-4"
    assert "teleport" in str(err)


def test_malformed_subject_error_identifies_offending_value():
    err = errors.MalformedSubjectError(value="nope-no-prefix", segment_id="seg-5")
    assert err.value == "nope-no-prefix"
    assert err.segment_id == "seg-5"
    assert "nope-no-prefix" in str(err)


def test_malformed_subject_error_segment_id_optional():
    # Subject.parse raises this before any segment context exists.
    err = errors.MalformedSubjectError(value="bad:")
    assert err.value == "bad:"
    assert err.segment_id is None


def test_version_mismatch_error_carries_declared_and_supported():
    err = errors.VersionMismatchError(declared=99, supported=1, segment_id="seg-6")
    assert err.declared == 99
    assert err.supported == 1
    assert err.segment_id == "seg-6"
    assert "99" in str(err)


# --------------------------------------------------------------------------- #
# Set-level errors (Req 4.6, 7.2, 7.4)                                         #
# --------------------------------------------------------------------------- #


def test_duplicate_id_error_carries_duplicated_id():
    err = errors.DuplicateIdError(segment_id="dup-1")
    assert err.segment_id == "dup-1"
    assert "dup-1" in str(err)


def test_unresolved_link_error_carries_target_and_source():
    err = errors.UnresolvedLinkError(target_id="ghost", segment_id="seg-7")
    assert err.target_id == "ghost"
    assert err.segment_id == "seg-7"
    assert "ghost" in str(err)


def test_self_reference_error_identifies_segment():
    err = errors.SelfReferenceError(segment_id="seg-8")
    assert err.segment_id == "seg-8"
    assert "seg-8" in str(err)


def test_id_conflict_error_carries_conflicting_id():
    err = errors.IdConflictError(segment_id="seg-9")
    assert err.segment_id == "seg-9"
    assert "seg-9" in str(err)


# --------------------------------------------------------------------------- #
# ValidationResult (per-segment) — Req 6.6                                     #
# --------------------------------------------------------------------------- #


def test_empty_validation_result_is_valid():
    result = errors.ValidationResult(segment_id="seg-1", errors=())
    assert result.is_valid is True
    assert tuple(result.errors) == ()


def test_validation_result_with_errors_is_invalid_and_keeps_order():
    e1 = errors.MissingFieldError(field="title", segment_id="seg-1")
    e2 = errors.UnknownRoleError(value="wizard", field="roles", segment_id="seg-1")
    result = errors.ValidationResult(segment_id="seg-1", errors=(e1, e2))
    assert result.is_valid is False
    assert tuple(result.errors) == (e1, e2)  # ordered, preserved


def test_validation_result_default_errors_empty_is_valid():
    result = errors.ValidationResult(segment_id="seg-1")
    assert result.is_valid is True
    assert tuple(result.errors) == ()


# --------------------------------------------------------------------------- #
# SetValidationResult (per-set) — Req 6.6                                      #
# --------------------------------------------------------------------------- #


def test_empty_set_validation_result_is_valid():
    result = errors.SetValidationResult(errors=())
    assert result.is_valid is True
    assert tuple(result.errors) == ()


def test_set_validation_result_with_errors_is_invalid_and_ordered():
    e1 = errors.DuplicateIdError(segment_id="dup")
    e2 = errors.SelfReferenceError(segment_id="seg-2")
    result = errors.SetValidationResult(errors=(e1, e2))
    assert result.is_valid is False
    assert tuple(result.errors) == (e1, e2)


def test_set_validation_result_default_errors_empty_is_valid():
    result = errors.SetValidationResult()
    assert result.is_valid is True
    assert tuple(result.errors) == ()
