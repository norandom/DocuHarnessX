"""Segment validation against a loaded vocabulary (the ``validation`` component).

This module owns the validation entry points:

* :func:`validate_segment` (task 3.1) — validate a single
  :class:`~docuharnessx.ontology.schema.Segment` against a loaded
  :class:`~docuharnessx.ontology.vocabulary.Vocabulary` and return a
  :class:`~docuharnessx.ontology.errors.ValidationResult` that aggregates *every*
  detected error rather than stopping at the first (Req 6.1, 6.6).
* :func:`validate_segment_set` / :func:`resolve_links` (task 3.2) — set-level
  validation and cross-link resolution: enforce unique ``id`` across a set
  (Req 4.6) then resolve each ``related`` entry against the id index, reporting
  self-references (Req 7.4) and unknown targets (Req 7.1, 7.2) while valid links
  resolve deterministically (Req 7.3).

The checks performed, in a stable documented order (Req 6.7):

1. **Version compatibility** — an incompatible declared ``schema_version`` yields a
   :class:`~docuharnessx.ontology.errors.VersionMismatchError` (Req 5.2). An omitted
   (``None``) version is treated as the current version (Req 5.3).
2. **Required-field presence** — each required field that is missing or empty (empty
   string / empty list, per the serializer's missing→empty defaulting) yields a
   :class:`~docuharnessx.ontology.errors.MissingFieldError` (Req 6.2). Non-empty
   ``roles``/``subjects`` (Req 4.5) is folded into this check: an empty ``roles`` or
   ``subjects`` is reported as a missing field for that axis.
3. **Role membership** — each role id absent from the vocabulary yields an
   :class:`~docuharnessx.ontology.errors.UnknownRoleError` (Req 6.4).
4. **Intent membership** — an intent id absent from the vocabulary yields an
   :class:`~docuharnessx.ontology.errors.UnknownIntentError` (Req 6.4).
5. **Subject-prefix membership** — each subject whose prefix is not a vocabulary
   prefix yields a :class:`~docuharnessx.ontology.errors.MalformedSubjectError`
   (Req 6.5).

Validation never raises for content-level problems — it collects typed errors into
the result so callers see all problems at once (Req 6.6). It is fully deterministic:
identical ``(segment, vocab)`` inputs always yield identical aggregated results in an
identical order (Req 6.7, 11.2). The segment id stamped on each collected error is
``segment.id`` when present, else ``None`` (so a missing-id segment produces errors
with ``segment_id=None``).
"""

from __future__ import annotations

from typing import Mapping, Sequence

from docuharnessx.ontology.errors import (
    DuplicateIdError,
    MalformedSubjectError,
    MissingFieldError,
    OntologyError,
    SelfReferenceError,
    SetValidationResult,
    UnknownIntentError,
    UnknownRoleError,
    UnresolvedLinkError,
    ValidationResult,
    VersionMismatchError,
)
from docuharnessx.ontology.model import normalize_prefix
from docuharnessx.ontology.schema import (
    REQUIRED_FIELDS,
    SCHEMA_VERSION,
    Segment,
    is_version_compatible,
)
from docuharnessx.ontology.vocabulary import Vocabulary

__all__ = ["validate_segment", "validate_segment_set", "resolve_links"]


def _is_present(field_name: str, value: object) -> bool:
    """Return whether a required field value counts as present.

    The serializer defaults missing required fields to empty strings / empty
    lists (task 2.5 guidance), so validation must treat empty/whitespace-only
    strings and empty lists as *missing* (Req 6.2, 4.5). A segment may also be
    built programmatically, so this check is the single authority on presence.
    """
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip() != ""
    if isinstance(value, (list, tuple)):
        return len(value) > 0
    return True


def validate_segment(segment: Segment, vocab: Vocabulary) -> ValidationResult:
    """Validate ``segment`` against ``vocab``, aggregating every detected error.

    Returns a :class:`ValidationResult` whose ``errors`` tuple lists *all* detected
    problems in a stable documented order (version → required fields → roles →
    intent → subjects) and whose ``is_valid`` flag is ``True`` only when no error
    was detected (Req 6.1, 6.6, 6.7). Never raises for content-level errors.

    Role/intent ids and subject prefixes are judged against the *supplied*
    ``vocab`` (Req 6.4, 6.5), so the same value can be accepted under one
    vocabulary and rejected under another. The ``segment_id`` carried by each
    error is ``segment.id`` when present, otherwise ``None``.
    """
    # Effective segment id: present id, else None (so errors on an id-less
    # segment carry segment_id=None, per the error contract).
    segment_id = segment.id if _is_present("id", segment.id) else None

    errors: list[OntologyError] = []

    # 1. Version compatibility (Req 5.2, 5.3). An omitted (None) version is
    #    treated as current and passes.
    if not is_version_compatible(segment.schema_version):
        errors.append(
            VersionMismatchError(
                declared=segment.schema_version,
                supported=SCHEMA_VERSION,
                segment_id=segment_id,
            )
        )

    # 2. Required-field presence, including non-empty roles/subjects (Req 6.2,
    #    4.5). Iterate REQUIRED_FIELDS for a stable, documented order.
    for field_name in REQUIRED_FIELDS:
        value = getattr(segment, field_name)
        if not _is_present(field_name, value):
            errors.append(MissingFieldError(field_name, segment_id=segment_id))

    # 3. Role membership (Req 6.4): each role id absent from the vocabulary.
    #    Iterate in declared order for determinism. Skip non-string/blank values
    #    (already reported as a missing 'roles' field above when empty).
    for role_id in segment.roles:
        if isinstance(role_id, str) and role_id.strip() and not vocab.has_role(role_id):
            errors.append(
                UnknownRoleError(role_id, field="roles", segment_id=segment_id)
            )

    # 4. Intent membership (Req 6.4): a present intent absent from the vocabulary.
    if (
        isinstance(segment.intent, str)
        and segment.intent.strip()
        and not vocab.has_intent(segment.intent)
    ):
        errors.append(
            UnknownIntentError(segment.intent, field="intent", segment_id=segment_id)
        )

    # 5. Subject-prefix membership (Req 6.5): each subject whose prefix is not a
    #    vocabulary prefix. Compare against the normalized allowed-prefix set via
    #    the single public model.normalize_prefix the model also uses for
    #    parsing, so colon/bare/case differences do not diverge.
    allowed = {normalize_prefix(p) for p in vocab.subject_prefixes}
    for subject in segment.subjects:
        if normalize_prefix(subject.prefix) not in allowed:
            errors.append(
                MalformedSubjectError(subject.canonical(), segment_id=segment_id)
            )

    return ValidationResult(segment_id=segment_id, errors=tuple(errors))


def validate_segment_set(
    segments: Sequence[Segment], vocab: Vocabulary
) -> SetValidationResult:
    """Validate a segment *set*: id uniqueness then ``related`` cross-links.

    Performs the two set-level checks the design assigns to this component
    (single-segment content validation is :func:`validate_segment`, run
    separately by the store):

    1. **Id uniqueness** (Req 4.6) — every segment ``id`` must be unique within
       the set. Each occurrence of an id *after* its first appearance yields a
       :class:`~docuharnessx.ontology.errors.DuplicateIdError` naming that id
       (so a triple-duplicate reports two errors). Segments are scanned in input
       order for a stable, documented report.
    2. **Cross-link resolution** (Req 7.1, 7.2, 7.4) — for each segment, each
       ``related`` entry is resolved against the id index built from the set:
       a target equal to the segment's own id yields a
       :class:`~docuharnessx.ontology.errors.SelfReferenceError` (Req 7.4); a
       target absent from the index yields an
       :class:`~docuharnessx.ontology.errors.UnresolvedLinkError` naming the
       missing target id and the referencing segment (Req 7.2); a valid target
       resolves silently. A self-reference is reported *only* as a self-reference
       (never also as unresolved), even when the id is otherwise absent.

    Error order is fully deterministic (Req 6.7, 11.2): all id-uniqueness errors
    first (segments in input order), then all cross-link errors (segments in
    input order, ``related`` entries in declared order). Identical input sets
    therefore always yield an identical :class:`SetValidationResult`. The id
    index maps each id to its *first* occurrence, so cross-links resolve against
    a single deterministic target even when duplicates are present.
    """
    errors: list[OntologyError] = []

    # 1. Id uniqueness (Req 4.6). Build the id index from FIRST occurrences and
    #    report every later occurrence of an already-seen id as a duplicate.
    index: dict[str, Segment] = {}
    for segment in segments:
        seg_id = segment.id
        if seg_id in index:
            errors.append(DuplicateIdError(seg_id))
        else:
            index[seg_id] = segment

    # 2. Cross-link resolution (Req 7.1, 7.2, 7.4). Scan segments in input order
    #    and their related entries in declared order for a stable report.
    for segment in segments:
        owner_id = segment.id if _is_present("id", segment.id) else None
        for target_id in segment.related:
            if target_id == segment.id:
                errors.append(SelfReferenceError(segment.id))
            elif target_id not in index:
                errors.append(
                    UnresolvedLinkError(target_id, segment_id=owner_id)
                )

    return SetValidationResult(errors=tuple(errors))


def resolve_links(
    segment: Segment, index: Mapping[str, Segment]
) -> list[Segment]:
    """Resolve ``segment.related`` to target segments, deterministically.

    Returns the segments named in ``segment.related``, in the order they are
    declared (Req 7.3), looked up in ``index`` (an id→segment mapping for the
    set). Entries that cannot resolve cleanly are skipped rather than raising:
    a self-reference (target equal to the segment's own id) and an unknown
    target (absent from ``index``) are both omitted from the returned list — the
    set validator (:func:`validate_segment_set`) is the component that *reports*
    those as errors. Identical inputs always yield an identical list.
    """
    resolved: list[Segment] = []
    for target_id in segment.related:
        if target_id == segment.id:
            continue
        target = index.get(target_id)
        if target is not None:
            resolved.append(target)
    return resolved
