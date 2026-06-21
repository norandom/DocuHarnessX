"""Typed error and result model for the ontology engine.

This module defines the discriminated set of ontology error types and the two
validation-result aggregates that the rest of the engine produces and consumes.

Design notes (see design.md "Error Handling" and the ``errors`` component):

* The error types are **both** structured records and raisable exceptions.
  ``Subject.parse`` (model), the front-matter serializer, and the vocabulary
  loader *raise* these (e.g. ``MalformedSubjectError``, ``MalformedConfigError``);
  segment validation *collects* the same typed errors into a
  :class:`ValidationResult` / :class:`SetValidationResult` rather than raising,
  so callers see every problem at once (Req 6.6). Making each error an
  ``Exception`` subclass that also exposes structured attributes lets the same
  type serve both roles.
* Each error carries the offending value/field and the segment-or-config
  identifier where applicable, so messages are actionable (Req 1.6, 6.2-6.5,
  7.2, 7.4).

All types are deterministic, side-effect-free data holders (Req 11).
"""

from __future__ import annotations

from typing import Optional, Sequence

__all__ = [
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
]


class OntologyError(Exception):
    """Base class for every typed ontology error.

    Subclasses populate structured attributes (offending value/field and the
    segment-or-config identifier) and pass a human-readable message up to
    ``Exception`` so the error is actionable whether it is raised or collected
    into a result.
    """


# --------------------------------------------------------------------------- #
# Config-level error (Req 1.6)                                                 #
# --------------------------------------------------------------------------- #


class MalformedConfigError(OntologyError):
    """A present-but-invalid ``.docuharnessx/ontology.yaml`` config.

    Raised by the vocabulary loader for unparseable YAML or missing required
    keys; identifies the offending config file (Req 1.6).
    """

    def __init__(self, config_path: str, reason: str = "") -> None:
        self.config_path = config_path
        self.reason = reason
        message = f"malformed ontology config '{config_path}'"
        if reason:
            message += f": {reason}"
        super().__init__(message)


# --------------------------------------------------------------------------- #
# Frontmatter / required-field / axis errors (Req 6.2-6.5)                     #
# --------------------------------------------------------------------------- #


class MalformedFrontmatterError(OntologyError):
    """Segment front matter is missing its fence or is not valid YAML (Req 6.3)."""

    def __init__(self, segment_id: Optional[str] = None, reason: str = "") -> None:
        self.segment_id = segment_id
        self.reason = reason
        message = f"malformed frontmatter in segment '{segment_id}'"
        if reason:
            message += f": {reason}"
        super().__init__(message)


class MissingFieldError(OntologyError):
    """A required segment field is absent (Req 6.2)."""

    def __init__(self, field: str, segment_id: Optional[str] = None) -> None:
        self.field = field
        self.segment_id = segment_id
        super().__init__(
            f"missing required field '{field}' in segment '{segment_id}'"
        )


class UnknownRoleError(OntologyError):
    """A role value is not a member of the loaded ``Vocabulary`` (Req 6.4)."""

    def __init__(
        self, value: str, field: str = "roles", segment_id: Optional[str] = None
    ) -> None:
        self.value = value
        self.field = field
        self.segment_id = segment_id
        super().__init__(
            f"unknown role '{value}' in field '{field}' of segment '{segment_id}'"
        )


class UnknownIntentError(OntologyError):
    """An intent value is not a member of the loaded ``Vocabulary`` (Req 6.4)."""

    def __init__(
        self, value: str, field: str = "intent", segment_id: Optional[str] = None
    ) -> None:
        self.value = value
        self.field = field
        self.segment_id = segment_id
        super().__init__(
            f"unknown intent '{value}' in field '{field}' of segment '{segment_id}'"
        )


class MalformedSubjectError(OntologyError):
    """A subject value has no recognized prefix or an empty local name (Req 6.5).

    Raised by ``Subject.parse`` (before any segment context exists, so
    ``segment_id`` is optional) and collected by validation with the segment id
    filled in.
    """

    def __init__(self, value: str, segment_id: Optional[str] = None) -> None:
        self.value = value
        self.segment_id = segment_id
        super().__init__(
            f"malformed subject '{value}' in segment '{segment_id}'"
        )


class VersionMismatchError(OntologyError):
    """A segment declares a schema version incompatible with the engine (Req 5.2)."""

    def __init__(
        self,
        declared: Optional[int],
        supported: int,
        segment_id: Optional[str] = None,
    ) -> None:
        self.declared = declared
        self.supported = supported
        self.segment_id = segment_id
        super().__init__(
            f"schema version mismatch in segment '{segment_id}': "
            f"declared {declared}, supported {supported}"
        )


# --------------------------------------------------------------------------- #
# Set-level errors (Req 4.6, 7.2, 7.4, 9.7)                                    #
# --------------------------------------------------------------------------- #


class DuplicateIdError(OntologyError):
    """A segment ``id`` appears more than once in a segment set (Req 4.6)."""

    def __init__(self, segment_id: str) -> None:
        self.segment_id = segment_id
        super().__init__(f"duplicate segment id '{segment_id}'")


class UnresolvedLinkError(OntologyError):
    """A ``related`` entry refers to an id absent from the set (Req 7.2)."""

    def __init__(self, target_id: str, segment_id: Optional[str] = None) -> None:
        self.target_id = target_id
        self.segment_id = segment_id
        super().__init__(
            f"unresolved related target '{target_id}' in segment '{segment_id}'"
        )


class SelfReferenceError(OntologyError):
    """A segment lists its own ``id`` in ``related`` (Req 7.4)."""

    def __init__(self, segment_id: str) -> None:
        self.segment_id = segment_id
        super().__init__(f"segment '{segment_id}' references itself in 'related'")


class IdConflictError(OntologyError):
    """A ``put`` targets an id already present in the store (Req 9.7)."""

    def __init__(self, segment_id: str) -> None:
        self.segment_id = segment_id
        super().__init__(f"segment id '{segment_id}' already exists in the store")


# --------------------------------------------------------------------------- #
# Validation result aggregates (Req 6.6)                                       #
# --------------------------------------------------------------------------- #


class ValidationResult:
    """Per-segment validation outcome: an ``is_valid`` flag and ordered errors.

    The error list preserves insertion order so callers get a deterministic,
    actionable report of every detected problem (Req 6.6, 6.7). An empty error
    list means the segment is valid.
    """

    __slots__ = ("segment_id", "_errors")

    def __init__(
        self,
        segment_id: Optional[str] = None,
        errors: Sequence[OntologyError] = (),
    ) -> None:
        self.segment_id = segment_id
        self._errors: tuple[OntologyError, ...] = tuple(errors)

    @property
    def errors(self) -> tuple[OntologyError, ...]:
        return self._errors

    @property
    def is_valid(self) -> bool:
        return len(self._errors) == 0

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return (
            f"ValidationResult(segment_id={self.segment_id!r}, "
            f"is_valid={self.is_valid}, errors={self._errors!r})"
        )


class SetValidationResult:
    """Per-set validation outcome: an ``is_valid`` flag and ordered errors.

    Aggregates set-level errors (duplicate ids, unresolved links,
    self-references) alongside any per-segment errors surfaced during a set
    validation pass; order is preserved for determinism (Req 6.6, 6.7).
    """

    __slots__ = ("_errors",)

    def __init__(self, errors: Sequence[OntologyError] = ()) -> None:
        self._errors: tuple[OntologyError, ...] = tuple(errors)

    @property
    def errors(self) -> tuple[OntologyError, ...]:
        return self._errors

    @property
    def is_valid(self) -> bool:
        return len(self._errors) == 0

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return (
            f"SetValidationResult(is_valid={self.is_valid}, "
            f"errors={self._errors!r})"
        )
