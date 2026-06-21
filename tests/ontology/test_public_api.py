"""Public API surface tests for ``docuharnessx.ontology`` (task 6.1).

Asserts that the package re-exports the stable public surface: every name in
``docuharnessx.ontology.__all__`` is importable directly from the package and is
usable (callable function, instantiable class, or a usable constant), and that
the two frozen contract seams — the ``Vocabulary`` loader API and the
``SegmentStore`` port + ``AxisFilter`` — import directly from the package
namespace verbatim (Req 1.2, 1.4, 4.1, 5.1, 9.1, 11.3).
"""

import inspect

import docuharnessx.ontology as ontology

# The names that MUST resolve to a callable (function or class).
_CALLABLE_NAMES = {
    # errors
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
    # model
    "AxisTerm",
    "Subject",
    "normalize_prefix",
    # schema
    "Segment",
    "is_version_compatible",
    "check_version",
    # vocabulary
    "Vocabulary",
    "load_vocabulary",
    "default_profile",
    "default_profile_config",
    "vocabulary_to_config",
    # serializer
    "ParsedSegment",
    "parse_segment",
    "to_segment",
    "serialize_segment",
    # validation
    "validate_segment",
    "validate_segment_set",
    "resolve_links",
    # tags
    "emit_tags",
    # store
    "SegmentStore",
    "AxisFilter",
    "InMemorySegmentStore",
    "FilesystemSegmentStore",
    # views
    "build_role_view",
}

# The names that are usable *constants* rather than callables.
_CONSTANT_NAMES = {
    "SCHEMA_VERSION",
    "REQUIRED_FIELDS",
    "FROZEN_FIELDS_BY_VERSION",
}


def test_all_is_the_documented_public_surface():
    """``__all__`` is exactly the callable + constant surface, no drift."""
    assert set(ontology.__all__) == _CALLABLE_NAMES | _CONSTANT_NAMES
    # No accidental duplicates in __all__.
    assert len(ontology.__all__) == len(set(ontology.__all__))


def test_every_public_name_is_present_on_the_package():
    """Every name in ``__all__`` is an attribute of ``docuharnessx.ontology``."""
    for name in ontology.__all__:
        assert hasattr(ontology, name), f"missing public export: {name}"


def test_callable_exports_are_callable():
    """Every documented function/class export is callable/usable."""
    for name in _CALLABLE_NAMES:
        obj = getattr(ontology, name)
        assert callable(obj), f"public export {name} is not callable"


def test_constant_exports_are_usable():
    """The documented constant exports hold the expected, usable values."""
    assert isinstance(ontology.SCHEMA_VERSION, int)
    assert isinstance(ontology.REQUIRED_FIELDS, tuple)
    assert ontology.REQUIRED_FIELDS == ("id", "title", "roles", "subjects", "intent")
    assert isinstance(ontology.FROZEN_FIELDS_BY_VERSION, dict)
    assert ontology.SCHEMA_VERSION in ontology.FROZEN_FIELDS_BY_VERSION


def test_frozen_vocabulary_seam_imports_directly_from_package():
    """The frozen Vocabulary loader API is importable directly from the package."""
    from docuharnessx.ontology import (  # noqa: F401
        Vocabulary,
        load_vocabulary,
        vocabulary_to_config,
    )

    # And it is actually usable end-to-end: the default profile round-trips
    # through the config serializer via the package-level names.
    vocab = ontology.default_profile()
    assert isinstance(vocab, Vocabulary)
    assert load_vocabulary(vocabulary_to_config(vocab)) == vocab


def test_frozen_store_seam_imports_directly_from_package():
    """The frozen SegmentStore port + AxisFilter import directly from the package."""
    from docuharnessx.ontology import AxisFilter, SegmentStore  # noqa: F401

    # The default AxisFilter is the empty (match-all) filter.
    empty = AxisFilter()
    assert (empty.roles, empty.intents, empty.subjects) == ((), (), ())

    # The in-memory adapter is a structural SegmentStore (runtime-checkable Protocol).
    store = ontology.InMemorySegmentStore(ontology.default_profile())
    assert isinstance(store, SegmentStore)


def test_public_api_is_usable_end_to_end():
    """A representative slice of the API works through the package namespace only.

    Build a segment, validate it against the default profile, emit its tags,
    store it, query it back, and derive a role view — all via
    ``docuharnessx.ontology`` exports — to confirm the re-exported surface is
    wired and usable, not merely importable.
    """
    vocab = ontology.default_profile()

    subject = ontology.Subject.parse("component:loader", frozenset(vocab.subject_prefixes))
    segment = ontology.Segment(
        id="seg-1",
        title="Getting started",
        roles=["developer"],
        subjects=[subject],
        intent="install",
    )

    result = ontology.validate_segment(segment, vocab)
    assert isinstance(result, ontology.ValidationResult)
    assert result.is_valid

    tags = ontology.emit_tags(segment, vocab)
    assert "role:developer" in tags
    assert "intent:install" in tags
    assert "subject:component:loader" in tags

    store = ontology.InMemorySegmentStore(vocab)
    store.put(segment)
    assert store.query(ontology.AxisFilter(roles=("developer",))) == (segment,)

    view = ontology.build_role_view(store, "developer", vocab)
    assert view == (segment,)


def test_axisterm_is_a_constructible_value_object():
    """``AxisTerm`` re-export constructs and keeps id stable across labels."""
    term = ontology.AxisTerm("developer", "Developer")
    assert term.id == "developer"
    # Signature sanity: AxisTerm takes (id, label, description="").
    params = list(inspect.signature(ontology.AxisTerm).parameters)
    assert params[:2] == ["id", "label"]
