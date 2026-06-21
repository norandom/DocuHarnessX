"""Tests for the single-source-of-truth prefix normalizer (cleanup task).

Prefix normalization previously lived in three sites: ``model._normalize_prefix``
(private), an inline copy in ``tags.py``, and an import of the private name in
``validation.py``. The cleanup promotes ONE public ``model.normalize_prefix`` and
converges tags + validation onto it.

These tests assert that:

* ``normalize_prefix`` is part of the model's PUBLIC surface,
* it is deterministic and idempotent,
* the private ``_normalize_prefix`` alias still resolves to it (internal callers
  keep working), and
* tag emission and segment validation agree with it — a subject whose prefix
  differs only by case/colon is treated identically across ``emit_tags`` and
  ``validate_segment``.
"""

from __future__ import annotations

from docuharnessx.ontology import model
from docuharnessx.ontology.model import Subject, normalize_prefix
from docuharnessx.ontology.schema import Segment
from docuharnessx.ontology.tags import emit_tags
from docuharnessx.ontology.validation import validate_segment
from docuharnessx.ontology.vocabulary import default_profile


# --------------------------------------------------------------------------- #
# Public surface + single source of truth                                      #
# --------------------------------------------------------------------------- #


def test_normalize_prefix_is_public() -> None:
    """``normalize_prefix`` is exported as part of the model's public API."""
    assert "normalize_prefix" in model.__all__
    assert callable(model.normalize_prefix)


def test_private_alias_delegates_to_public() -> None:
    """The legacy private name resolves to the one public normalizer."""
    assert model._normalize_prefix is model.normalize_prefix


# --------------------------------------------------------------------------- #
# Normalization semantics: bare/colon/case folding + idempotence              #
# --------------------------------------------------------------------------- #


def test_normalize_prefix_strips_trailing_colon() -> None:
    assert normalize_prefix("component:") == "component"
    assert normalize_prefix("component") == "component"


def test_normalize_prefix_casefolds_and_trims() -> None:
    assert normalize_prefix("  COMPONENT:  ") == "component"
    assert normalize_prefix("Tech") == "tech"


def test_normalize_prefix_is_idempotent() -> None:
    for raw in ("component:", "  TECH: ", "Artifact", "topic:"):
        once = normalize_prefix(raw)
        assert normalize_prefix(once) == once


def test_normalize_prefix_collapses_equivalent_written_forms() -> None:
    """Bare, colon, and cased forms of one prefix all map together."""
    forms = ["component", "component:", "Component", "COMPONENT:", "  component:  "]
    normalized = {normalize_prefix(f) for f in forms}
    assert normalized == {"component"}


# --------------------------------------------------------------------------- #
# tags + validation are consistent with the normalizer                         #
# --------------------------------------------------------------------------- #


def _segment_with_subject(subject: Subject) -> Segment:
    return Segment(
        id="seg-1",
        title="Title",
        roles=["developer"],
        subjects=[subject],
        intent="install",
    )


def test_tags_and_validation_agree_on_case_colon_variant_prefix() -> None:
    """A subject whose prefix differs only by case/colon is treated identically
    by emit_tags and validate_segment, because both route through
    normalize_prefix.

    The default profile's prefixes are stored in colon form (``component:``).
    A ``Subject`` carrying an upper-cased/bare ``COMPONENT`` prefix normalizes to
    the same canonical prefix, so it must be (a) emitted as a tag and (b) accepted
    by validation.
    """
    vocab = default_profile()
    # Constructed directly to carry a non-canonical prefix form, bypassing
    # Subject.parse's own normalization.
    variant = Subject(prefix="COMPONENT", local="auth")
    assert normalize_prefix(variant.prefix) in {
        normalize_prefix(p) for p in vocab.subject_prefixes
    }

    seg = _segment_with_subject(variant)

    # tags: the variant-prefixed subject IS emitted (prefix is vocab-valid).
    tags = emit_tags(seg, vocab)
    assert any(t.startswith("subject:") for t in tags)

    # validation: no MalformedSubjectError is raised for this subject.
    result = validate_segment(seg, vocab)
    from docuharnessx.ontology.errors import MalformedSubjectError

    assert not any(isinstance(e, MalformedSubjectError) for e in result.errors)


def test_tags_and_validation_agree_on_truly_unknown_prefix() -> None:
    """A prefix that normalizes to something NOT in the vocabulary is rejected by
    both surfaces, again consistently via normalize_prefix."""
    vocab = default_profile()
    rogue = Subject(prefix="bogus", local="thing")
    assert normalize_prefix(rogue.prefix) not in {
        normalize_prefix(p) for p in vocab.subject_prefixes
    }

    seg = _segment_with_subject(rogue)

    # tags: no subject tag is emitted for the rogue-prefixed subject.
    tags = emit_tags(seg, vocab)
    assert not any(t.startswith("subject:") for t in tags)

    # validation: a MalformedSubjectError IS reported for it.
    from docuharnessx.ontology.errors import MalformedSubjectError

    result = validate_segment(seg, vocab)
    assert any(isinstance(e, MalformedSubjectError) for e in result.errors)
