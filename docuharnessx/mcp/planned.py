"""Reconstruct a stable-id ``PlannedSegment`` from a stored ``Segment`` (mcp task 2.1).

This is a **pure, model-free** glue module of the ``docuharnessx-mcp-refine`` server.
:func:`planned_from_segment` turns a persisted
:class:`~docuharnessx.ontology.Segment` back into the
:class:`~docuharnessx.planning.model.PlannedSegment` the deterministic
:func:`~docuharnessx.composition.blueprint.build_blueprint` consumes, so a
``rewrite_segment`` can rebuild the segment's COBESY blueprint and re-run the bounded
agentic writer over it (the human guidance reaches the agent through the writer's
``guidance`` keyword, never through the blueprint).

The load-bearing contract is the **stable-id round-trip**::

    segment_id(planned_from_segment(seg)) == seg.id

so a later rewrite re-wires the *same* id in place. This matters because the
:class:`~docuharnessx.ontology.FilesystemSegmentStore` has **no update** method and
``put`` raises :class:`~docuharnessx.ontology.IdConflictError` on an existing id — a
rewrite cannot re-``put`` the same id, so it must reproduce the stored id exactly and
re-serialise ``<id>.md`` in place. Since
:func:`~docuharnessx.composition.wiring.segment_id` is a pure function of
``PlannedSegment.segment_key`` alone, the round-trip is guaranteed by reconstructing the
**same** ``segment_key`` the planner originally built.

How the original ``segment_key`` is recovered
----------------------------------------------
The ``segment_key`` is **not** persisted on a ``Segment`` (the front-matter schema carries
only ``id`` / ``title`` / ``roles`` / ``subjects`` / ``intent`` / ``summary`` / ``related``
/ ``schema_version`` / ``body``). But the planner builds the key **deterministically** from
fields that *are* persisted — its documented form is
``"<roles-joined>__<intent>__<subjects-digest>"``
(``docuharnessx/planning/planner.py``), where:

* ``roles`` are joined with ``","`` in the vocabulary-declared order the planner emitted
  (and the wiring/serializer preserve verbatim);
* ``intent`` is the intent id;
* ``subjects-digest`` is a ``blake2b`` digest (6 bytes -> 12 hex chars) over the
  newline-joined ``Subject.canonical()`` strings, taken in canonical-sorted order.

All three inputs survive on the stored ``Segment``, so this module re-derives the *identical*
key with a local, self-contained reimplementation of that construction (it imports no
planner-private symbol and edits nothing in ``planning`` — the planning boundary is
untouched). Re-deriving the same key yields the same ``segment_id``, so the round-trip holds
for every planner-produced segment.

Purity and tolerated-absence guarantees
----------------------------------------
* **Model-free / pure**: consults no model, performs no I/O, and never mutates the input
  ``Segment`` (it reads ``roles`` / ``intent`` / ``subjects`` and copies them into fresh,
  immutable tuples). Deterministic: equal segments yield equal planned segments.
* **Evidence is best-effort**: a stored ``Segment`` does not retain the planner's
  ``EvidenceRef`` provenance, so :attr:`PlannedSegment.evidence` is reconstructed as the
  empty tuple. ``build_blueprint`` tolerates empty evidence (it simply omits the optional
  *Grounding* chunk), and the agent re-explores the repository from its read-only workspace
  during a rewrite — so no repository fact is invented here (the anti-slop discipline is
  preserved: grounding comes from the live re-run, not from this pure reconstruction).
* **priority** is reconstructed as ``0`` (a neutral, deterministic value): the rewrite path
  builds a blueprint and wires a single segment in place, so the planner's cross-segment
  ordering score is irrelevant to the round-trip and to the blueprint shape (``priority`` is
  not consumed by ``build_blueprint``).
"""

from __future__ import annotations

import hashlib

from docuharnessx.ontology import Segment, Subject
from docuharnessx.planning.model import PlannedSegment

__all__ = ["planned_from_segment"]

#: Length (bytes) of the subjects digest the planner embeds in a ``segment_key``. The
#: planner uses 12 hex chars (``digest_size = 12 // 2 = 6`` bytes); we mirror that exactly
#: so the re-derived key — and therefore the derived id — matches the stored one. See
#: ``docuharnessx/planning/planner.py`` (``_SUBJECT_DIGEST_LEN``).
_SUBJECT_DIGEST_BYTES: int = 6


def _sorted_subjects(subjects: tuple[Subject, ...]) -> tuple[Subject, ...]:
    """Subjects sorted by ``canonical()`` — the planner's documented subject order.

    The planner sorts a cell's subjects by ``Subject.canonical()`` before computing the
    digest (and stores them in that order). Re-sorting here makes the re-derived digest
    independent of the order the subjects happen to appear on the stored ``Segment``.
    """
    return tuple(sorted(subjects, key=lambda s: s.canonical()))


def _subjects_digest(sorted_subjects: tuple[Subject, ...]) -> str:
    """A short, stable hash over the sorted canonical subject strings (planner-identical).

    Computed over the newline-joined, already-sorted ``canonical()`` strings, so it is
    independent of input order and identical across runs. An empty subject set yields the
    digest of the empty string — a stable, well-defined value (the planner's behaviour).
    """
    payload = "\n".join(s.canonical() for s in sorted_subjects)
    return hashlib.blake2b(
        payload.encode("utf-8"), digest_size=_SUBJECT_DIGEST_BYTES
    ).hexdigest()


def _segment_key(
    roles: tuple[str, ...], intent: str, sorted_subjects: tuple[Subject, ...]
) -> str:
    """Re-derive the planner's deterministic ``"<roles>__<intent>__<subjects-digest>"`` key.

    ``roles`` are joined with ``","`` in their stored (vocabulary-declared) order — the same
    order the planner emitted and the wiring/serializer preserved — so the key, and the id
    :func:`~docuharnessx.composition.wiring.segment_id` derives from it, match the stored
    segment's id.
    """
    roles_part = ",".join(roles)
    return f"{roles_part}__{intent}__{_subjects_digest(sorted_subjects)}"


def planned_from_segment(segment: Segment) -> PlannedSegment:
    """Reconstruct a stable-id :class:`PlannedSegment` from a stored ``Segment``.

    Copies the stored segment's ``roles`` / ``intent`` / ``subjects`` and derives the same
    deterministic ``segment_key`` the planner originally built, so::

        segment_id(planned_from_segment(seg)) == seg.id

    round-trips for every planner-produced segment — a later ``rewrite_segment`` therefore
    re-wires the *same* ``<id>.md`` in place (the store has no update method and rejects a
    re-``put`` of an existing id). Evidence is reconstructed best-effort as the empty tuple
    (tolerated by ``build_blueprint``; the agent re-grounds from the live repository on a
    rewrite, so nothing is invented here), and ``priority`` is a neutral ``0``.

    Pure, deterministic, and model-free: consults no model, performs no I/O, and never
    mutates ``segment`` (``roles`` / ``subjects`` are copied into fresh immutable tuples).
    """
    sorted_subjects = _sorted_subjects(tuple(segment.subjects))
    roles = tuple(segment.roles)
    return PlannedSegment(
        segment_key=_segment_key(roles, segment.intent, sorted_subjects),
        roles=roles,
        intent=segment.intent,
        subjects=sorted_subjects,
        priority=0,
        evidence=(),
    )
