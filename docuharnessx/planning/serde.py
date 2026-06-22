"""Deterministic serialize / deserialize for the ``CoveragePlan`` seam (task 1.2).

This module gives the frozen :class:`~docuharnessx.planning.model.CoveragePlan`
contract a plain, ordered, JSON-compatible serialization and a round-trip
deserialization, so the Wave 2 ``cobesy-writer`` can persist and reload the plan
without depending on the in-memory model classes (design "serde — deterministic
serialization"; Req 6.4, 6.5, 6.6).

Three functions form the public surface:

* :func:`to_dict` — convert a ``CoveragePlan`` to a plain ``dict`` of JSON
  primitives. Every ``tuple`` becomes a ``list`` *preserving the planner's order*
  (the model is already pre-ordered, so serde never re-orders collection elements);
  each :class:`~docuharnessx.planning.model.EvidenceRef` becomes a nested dict; and
  each ontology :class:`~docuharnessx.ontology.Subject` becomes its
  ``canonical()`` ``"prefix:local"`` string (design "serde — deterministic
  serialization", Req 6.4).
* :func:`from_dict` — reconstruct an **equal** ``CoveragePlan`` from such a dict
  (round-trip equality, Req 6.5). It first checks ``schema_version``: an unknown or
  missing version raises :class:`~docuharnessx.planning.model.CoveragePlanVersionError`
  naming the offending version so a consumer reading a future/foreign contract fails
  loudly rather than mis-reconstructing the seam (Req 6.5). Each subject string is
  rebuilt via :meth:`~docuharnessx.ontology.Subject.parse`, inferring the allowed
  prefix from the subject's own already-canonical form, so no external vocabulary is
  needed to load a plan.
* :func:`to_json` — ``json.dumps(to_dict(...), sort_keys=True, ensure_ascii=False)``.
  ``sort_keys`` makes the emitted key order independent of dict insertion order and
  the pre-ordered collections make element order stable, so two runs over equal
  inputs serialize **byte-identically** (Req 6.4).

Determinism rests on two pins: the planner produces pre-ordered tuples (the model
never sorts, and neither does serde), and JSON emission uses ``sort_keys=True``. No
nondeterministic dict iteration leaks into the output.

This module owns serialization only — the model (task 1.1), the deterministic
transforms (``subjects`` / ``matrix`` / ``classifier`` / ``scorer`` / ``planner``),
and the stage adapters live elsewhere.
"""

from __future__ import annotations

import json
from typing import Any

from docuharnessx.ontology import Subject
from docuharnessx.planning.model import (
    COVERAGE_PLAN_SCHEMA_VERSION,
    CoveragePlan,
    CoveragePlanVersionError,
    EvidenceRef,
    PlannedSegment,
)

__all__ = [
    "to_dict",
    "from_dict",
    "to_json",
]


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #


def _evidence_to_dict(ref: EvidenceRef) -> dict[str, Any]:
    """Convert one :class:`EvidenceRef` to a plain, ordered dict."""
    return {"kind": ref.kind, "detail": ref.detail}


def _segment_to_dict(segment: PlannedSegment) -> dict[str, Any]:
    """Convert one :class:`PlannedSegment` to a plain, JSON-compatible dict.

    Tuples become lists preserving the planner's order; each ontology ``Subject``
    becomes its ``canonical()`` ``"prefix:local"`` string; each ``EvidenceRef``
    becomes a nested dict. Key order follows the declaration order for readability;
    :func:`to_json` re-sorts keys for byte stability.
    """
    return {
        "segment_key": segment.segment_key,
        "roles": list(segment.roles),
        "intent": segment.intent,
        "subjects": [s.canonical() for s in segment.subjects],
        "priority": segment.priority,
        "evidence": [_evidence_to_dict(e) for e in segment.evidence],
        "relevance_note": segment.relevance_note,
    }


def _subject_from_canonical(canonical: str) -> Subject:
    """Rebuild a :class:`Subject` from its own canonical ``"prefix:local"`` string.

    The allowed-prefix set is inferred from the string's own prefix, so a plan loads
    without an external vocabulary while still going through the ontology
    :meth:`Subject.parse` normalization (the canonical form is idempotent under parse,
    so ``Subject.parse(s.canonical(), {s.prefix}) == s``).
    """
    prefix = canonical.split(":", 1)[0]
    return Subject.parse(canonical, frozenset({prefix}))


def _segment_from_dict(data: dict[str, Any]) -> PlannedSegment:
    """Reconstruct one :class:`PlannedSegment` from a :func:`_segment_to_dict` payload."""
    return PlannedSegment(
        segment_key=data["segment_key"],
        roles=tuple(data["roles"]),
        intent=data["intent"],
        subjects=tuple(_subject_from_canonical(s) for s in data["subjects"]),
        priority=data["priority"],
        evidence=tuple(
            EvidenceRef(kind=e["kind"], detail=e["detail"]) for e in data["evidence"]
        ),
        relevance_note=data.get("relevance_note", ""),
    )


# --------------------------------------------------------------------------- #
# Public API                                                                   #
# --------------------------------------------------------------------------- #


def to_dict(plan: CoveragePlan) -> dict[str, Any]:
    """Serialize a ``CoveragePlan`` to a plain, ordered, JSON-compatible dict.

    Every tuple becomes a list (preserving the planner's order); each
    :class:`PlannedSegment` becomes a nested dict; each ``Subject`` becomes its
    ``canonical()`` string; each ``EvidenceRef`` becomes a nested dict (Req 6.4).
    The result contains only JSON primitives, so :func:`json.dumps` accepts it
    without a custom encoder.
    """
    return {
        "schema_version": plan.schema_version,
        "repo_path": plan.repo_path,
        "vocabulary_fingerprint": plan.vocabulary_fingerprint,
        "segments": [_segment_to_dict(s) for s in plan.segments],
        "relevance_applied": plan.relevance_applied,
    }


def from_dict(data: dict[str, Any]) -> CoveragePlan:
    """Reconstruct an equal ``CoveragePlan`` from a :func:`to_dict` payload.

    The ``schema_version`` is validated first: a missing or unrecognized version
    raises :class:`CoveragePlanVersionError` naming the offending value, so a
    consumer reading a future/foreign contract fails loudly rather than silently
    mis-reconstructing the seam (Req 6.5). For the supported version, every
    collection is rebuilt as a tuple and every subject is parsed back into a typed
    ontology :class:`Subject`, so ``from_dict(to_dict(p)) == p`` (round-trip
    equality, Req 6.5).
    """
    version = data.get("schema_version")
    if version != COVERAGE_PLAN_SCHEMA_VERSION:
        raise CoveragePlanVersionError(
            "unsupported CoveragePlan schema_version "
            f"{version!r}; this build understands "
            f"version {COVERAGE_PLAN_SCHEMA_VERSION}"
        )

    return CoveragePlan(
        schema_version=data["schema_version"],
        repo_path=data["repo_path"],
        vocabulary_fingerprint=data["vocabulary_fingerprint"],
        segments=tuple(_segment_from_dict(s) for s in data["segments"]),
        relevance_applied=data.get("relevance_applied", False),
    )


def to_json(plan: CoveragePlan) -> str:
    """Serialize a ``CoveragePlan`` to a byte-stable JSON string (Req 6.4).

    Uses ``sort_keys=True`` so the emitted key order is independent of dict
    insertion order, and ``ensure_ascii=False`` so non-ASCII text is emitted
    literally (stable and human-readable). Combined with the planner's pre-ordered
    collections, two runs over equal inputs produce byte-identical JSON.
    """
    return json.dumps(to_dict(plan), sort_keys=True, ensure_ascii=False)
