"""DocuHarnessX ontology subpackage — the stable public API surface.

The tri-modal ontology model — Role, Subject tags, Intent — plus the segment
front-matter schema, vocabulary loader, validation, tag emission, the segment
store port with its adapters, and role-view derivation.

This module re-exports the stable public surface of the ontology engine so
downstream consumers (notably harness-bundle-skeleton) import from a single
namespace, ``docuharnessx.ontology``, rather than reaching into private
submodules. The two *frozen* contract seams — the ``Vocabulary`` loader API
(``Vocabulary``/``load_vocabulary``/``vocabulary_to_config``) and the store port
(``SegmentStore``/``AxisFilter``) — are importable directly from here verbatim
(task 6.1; Req 1.2, 1.4, 4.1, 5.1, 9.1, 11.3).

Everything exported here is deterministic, pure-library code with no network or
LLM dependency.
"""

from docuharnessx.ontology.errors import (
    DuplicateIdError,
    IdConflictError,
    MalformedConfigError,
    MalformedFrontmatterError,
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
from docuharnessx.ontology.model import AxisTerm, Subject, normalize_prefix
from docuharnessx.ontology.schema import (
    FROZEN_FIELDS_BY_VERSION,
    REQUIRED_FIELDS,
    SCHEMA_VERSION,
    Segment,
    check_version,
    is_version_compatible,
)
from docuharnessx.ontology.serializer import (
    ParsedSegment,
    parse_segment,
    serialize_segment,
    to_segment,
)
from docuharnessx.ontology.store import (
    AxisFilter,
    FilesystemSegmentStore,
    InMemorySegmentStore,
    SegmentStore,
)
from docuharnessx.ontology.tags import emit_tags
from docuharnessx.ontology.validation import (
    resolve_links,
    validate_segment,
    validate_segment_set,
)
from docuharnessx.ontology.views import build_role_view
from docuharnessx.ontology.vocabulary import (
    Vocabulary,
    default_profile,
    default_profile_config,
    load_vocabulary,
    vocabulary_to_config,
)

__all__ = [
    # errors.py — base + every discriminated error type + result aggregates
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
    # model.py — axis primitives + the canonical prefix normalizer
    "AxisTerm",
    "Subject",
    "normalize_prefix",
    # schema.py — segment value object + version contract
    "Segment",
    "SCHEMA_VERSION",
    "REQUIRED_FIELDS",
    "FROZEN_FIELDS_BY_VERSION",
    "is_version_compatible",
    "check_version",
    # vocabulary.py — FROZEN loader / profile / config-serializer seam
    "Vocabulary",
    "load_vocabulary",
    "default_profile",
    "default_profile_config",
    "vocabulary_to_config",
    # serializer.py — front-matter parse / build / serialize
    "ParsedSegment",
    "parse_segment",
    "to_segment",
    "serialize_segment",
    # validation.py — single-segment + set validation + link resolution
    "validate_segment",
    "validate_segment_set",
    "resolve_links",
    # tags.py — namespaced tag emission
    "emit_tags",
    # store.py — FROZEN store port + AxisFilter + both adapters
    "SegmentStore",
    "AxisFilter",
    "InMemorySegmentStore",
    "FilesystemSegmentStore",
    # views.py — role-view derivation
    "build_role_view",
]
