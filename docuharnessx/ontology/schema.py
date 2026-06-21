"""Segment frontmatter schema and version contract (the ontology ``schema`` component).

This module is one of the two *frozen* contract surfaces of the engine (the
other being the ``Vocabulary`` loader API in ``vocabulary.py``). It defines:

* :class:`Segment` — the value object every downstream stage reads and writes.
  Roles and the intent are stored as vocabulary **ids** (plain strings),
  validated later against a loaded ``Vocabulary``; they are NOT enum members
  (Req 4.1-4.4). The *vocabulary* is project data and is deliberately NOT part
  of the frozen schema version.
* :data:`REQUIRED_FIELDS` — the required-field set ``(id, title, roles,
  subjects, intent)`` (Req 4.2). ``summary``/``related``/``body``/
  ``schema_version`` are optional with documented defaults (Req 4.3).
* :data:`SCHEMA_VERSION` — the single source-of-truth version identifier for the
  frozen frontmatter contract (Req 5.1).
* :data:`FROZEN_FIELDS_BY_VERSION` — the documented, per-version frozen field set
  (Req 5.4).
* :func:`is_version_compatible` / :func:`check_version` — the version
  compatibility check: an omitted (``None``) version is treated as the current
  ``SCHEMA_VERSION`` (Req 5.3); an incompatible declared version is rejected
  (Req 5.2).

Aggregated segment validation (required-field presence, non-empty ``roles``/
``subjects``, vocabulary membership) lives in the ``validation`` component
(task 3.1). This module only defines the segment *structure*, the required-field
*set*, and the version-compatibility *check*; it performs no vocabulary lookups
and stays vocabulary-free (Req 5.4 invariant).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from docuharnessx.ontology.errors import VersionMismatchError
from docuharnessx.ontology.model import Subject

__all__ = [
    "SCHEMA_VERSION",
    "Segment",
    "REQUIRED_FIELDS",
    "FROZEN_FIELDS_BY_VERSION",
    "is_version_compatible",
    "check_version",
]


# --------------------------------------------------------------------------- #
# Version contract (Req 5.1, 5.4)                                              #
# --------------------------------------------------------------------------- #

#: The single, explicit schema-version identifier for the segment frontmatter
#: contract (Req 5.1). It is the only version authority consumed by every
#: component; bump it (and add an entry to ``FROZEN_FIELDS_BY_VERSION``) when the
#: frozen field set changes so downstream consumers can detect it (Req 5.5).
SCHEMA_VERSION: int = 1

#: The required frontmatter fields that must be present in every valid segment
#: (Req 4.2). Enforcement of presence is performed by the ``validation``
#: component; this set is the authoritative source it consults.
REQUIRED_FIELDS: tuple[str, ...] = ("id", "title", "roles", "subjects", "intent")

#: The documented, per-version frozen field set for the frontmatter contract
#: (Req 5.4). It maps a schema version to the exact set of fields frozen at that
#: version — the segment frontmatter field set ``{id, title, roles, subjects,
#: intent, summary, related}`` plus ``body`` and ``schema_version``. The
#: *vocabulary* (which roles/intents/prefixes a project uses) is explicitly NOT
#: frozen here: it is runtime project data, not part of the schema version.
FROZEN_FIELDS_BY_VERSION: dict[int, tuple[str, ...]] = {
    1: (
        "id",
        "title",
        "roles",
        "subjects",
        "intent",
        "summary",
        "related",
        "body",
        "schema_version",
    ),
}


# --------------------------------------------------------------------------- #
# Segment value object (Req 4.1-4.4)                                           #
# --------------------------------------------------------------------------- #


@dataclass
class Segment:
    """A content segment: frontmatter fields plus an opaque Markdown ``body``.

    ``roles`` and ``intent`` are stored as vocabulary **ids** (plain strings),
    not enum members (Req 4.1, 4.4); they are validated against a loaded
    ``Vocabulary`` by the ``validation`` component, never here. ``subjects`` are
    typed :class:`~docuharnessx.ontology.model.Subject` value objects.

    Required fields (Req 4.2) — see :data:`REQUIRED_FIELDS` — have no defaults so
    they must be supplied. Optional fields (Req 4.3) carry documented defaults:
    ``summary`` and ``body`` default to the empty string, ``related`` to a fresh
    empty list (per-instance, never shared), and ``schema_version`` to the
    current :data:`SCHEMA_VERSION`.
    """

    id: str
    title: str
    roles: list[str]  # role ids, validated against a loaded Vocabulary
    subjects: list[Subject]
    intent: str  # intent id, validated against a loaded Vocabulary
    summary: str = ""
    related: list[str] = field(default_factory=list)
    body: str = ""
    schema_version: int = SCHEMA_VERSION


# --------------------------------------------------------------------------- #
# Version-compatibility check (Req 5.2, 5.3)                                   #
# --------------------------------------------------------------------------- #


def is_version_compatible(declared: Optional[int]) -> bool:
    """Return whether a declared schema version is compatible with the engine.

    An omitted version (``None``) is treated as the current
    :data:`SCHEMA_VERSION` and is therefore compatible (Req 5.3). Any other
    declared value is compatible only if it equals :data:`SCHEMA_VERSION`;
    anything else is incompatible (Req 5.2). Pure and deterministic.
    """
    if declared is None:
        return True
    return declared == SCHEMA_VERSION


def check_version(declared: Optional[int], segment_id: Optional[str] = None) -> None:
    """Raise :class:`VersionMismatchError` if ``declared`` is incompatible.

    A convenience wrapper over :func:`is_version_compatible` for call sites that
    prefer raising over branching. An omitted version passes silently (treated
    as current, Req 5.3); an incompatible declared version raises with the
    declared/supported pair and the optional ``segment_id`` (Req 5.2).
    """
    if not is_version_compatible(declared):
        raise VersionMismatchError(declared, SCHEMA_VERSION, segment_id=segment_id)
