"""Axis primitives and the Subject namespace (the ontology ``model`` component).

This module defines the *structural* units the rest of the engine builds on:

* :class:`AxisTerm` — the value object for a single role or intent: a stable
  machine ``id`` distinct from its display ``label`` (Req 2.4). Roles and
  intents are NOT modelled as closed enums; they are loaded into a
  ``Vocabulary`` (see ``vocabulary.py``) as ``AxisTerm`` instances.
* :class:`Subject` — the prefixed-open subject value object. Its allowed
  prefixes are **supplied by the caller** at parse time (from a loaded
  ``Vocabulary``), never read from a module-level constant. This is what keeps
  the subject namespace project-configurable (Req 3.1-3.5).

Both types are immutable, hashable value objects with deterministic
normalization, so identical inputs always yield identical objects (Req 11).
"""

from __future__ import annotations

from dataclasses import dataclass

from docuharnessx.ontology.errors import MalformedSubjectError

__all__ = ["AxisTerm", "Subject", "normalize_prefix"]


@dataclass(frozen=True)
class AxisTerm:
    """A single role or intent term: a stable machine id plus a display label.

    The ``id`` is the stable machine identifier used for membership checks and
    tag emission; it does NOT change when the human-facing ``label`` changes
    (Req 2.4). ``description`` is optional documentation.

    Being a frozen dataclass makes the term immutable and hashable, and gives
    structural equality keyed on all three fields (so two terms with the same
    ``id`` but different ``label`` are *not* equal — equality is exact, while
    *identity for vocabulary membership* is keyed on ``id`` by the vocabulary).
    """

    id: str
    label: str
    description: str = ""


def normalize_prefix(prefix: str) -> str:
    """Normalize a prefix token to its bare, canonical form.

    This is the **single source of truth** for subject-prefix normalization
    across the engine: subject parsing (:meth:`Subject.parse`), tag emission
    (:func:`docuharnessx.ontology.tags.emit_tags`), and segment validation
    (:func:`docuharnessx.ontology.validation.validate_segment`) all route through
    it, so the bare/colon and case conventions can never silently diverge.

    Allowed prefixes may be supplied either bare (``"component"``) or with a
    trailing colon (``"component:"`` — the form Req 1.4 writes them in). Both
    normalize to the same bare, lower-cased token so the allowed-prefix set is
    tolerant of either convention. The function is idempotent:
    ``normalize_prefix(normalize_prefix(p)) == normalize_prefix(p)``.
    """
    return prefix.strip().rstrip(":").strip().casefold()


# Backwards-compatible private alias for internal callers that imported the
# original private name; both refer to the one public normalizer above.
_normalize_prefix = normalize_prefix


@dataclass(frozen=True)
class Subject:
    """A typed-open subject value: a configured ``prefix`` plus a free ``local``.

    A subject is well-formed only when it begins with one of the prefixes
    supplied at parse time (from the loaded ``Vocabulary``) and has a non-empty
    local name (Req 3.1, 3.2, 3.4). The local name is open free-form text and is
    not checked against any fixed list (Req 3.3).

    Normalization is deterministic and idempotent: surrounding whitespace is
    trimmed and the prefix/local are case-folded, so the same subject string
    always maps to the same canonical subject (Req 3.5) and
    ``Subject.parse(x.canonical(), prefixes) == x``.
    """

    prefix: str  # normalized; a member of the supplied allowed-prefix set
    local: str  # normalized, non-empty

    @classmethod
    def parse(cls, raw: str, allowed_prefixes: frozenset[str]) -> "Subject":
        """Parse ``raw`` into a normalized :class:`Subject`.

        ``allowed_prefixes`` is supplied by the caller from the loaded
        ``Vocabulary`` (never a module constant). Each allowed prefix may be
        bare or carry a trailing colon; both forms are accepted.

        Raises :class:`MalformedSubjectError` (identifying the original value)
        when the value has no ``prefix:local`` split, an unrecognized prefix, or
        an empty/whitespace-only local name (Req 3.2, 3.4).
        """
        value = raw.strip()
        if ":" not in value:
            raise MalformedSubjectError(raw)

        raw_prefix, raw_local = value.split(":", 1)
        prefix = _normalize_prefix(raw_prefix)
        local = raw_local.strip().casefold()

        allowed = {_normalize_prefix(p) for p in allowed_prefixes}
        if not prefix or prefix not in allowed:
            raise MalformedSubjectError(raw)
        if not local:
            raise MalformedSubjectError(raw)

        return cls(prefix=prefix, local=local)

    def canonical(self) -> str:
        """Return the canonical ``"prefix:local"`` string (Req 3.5)."""
        return f"{self.prefix}:{self.local}"
