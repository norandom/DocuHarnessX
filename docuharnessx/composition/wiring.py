"""Deterministic segment wiring: the planned-segment -> ontology ``Segment`` bridge.

This module is one of the pure, model-free core components of the Wave 2
``cobesy-writer`` (task 2.3, design "Segment Wiring"). It owns two deterministic
functions and touches no model:

* :func:`segment_id` derives a deterministic, **filesystem-safe**, unique id from one
  :class:`~docuharnessx.planning.model.PlannedSegment`. It is the **matching key** the
  Wave 2 ``quality-review-gate`` uses to align a written :class:`~docuharnessx.ontology.Segment`
  back to its planned source, so two writer runs over an equal plan yield equal ids
  (Req 4.4) and the id is a valid single-segment filename for
  :class:`~docuharnessx.ontology.FilesystemSegmentStore` (no ``/``, ``\\``, ``.``/``..``).
* :func:`wire_segment` maps the **non-body** fields (``id``/``roles``/``subjects``/
  ``intent``/``related``/``title``/``schema_version``) from the planned segment and the
  COBESY :class:`~docuharnessx.composition.model.CompositionBlueprint` into a *new*
  ontology ``Segment``; ``body``/``summary`` come **only** from the
  :class:`~docuharnessx.composition.model.ProseResult`. The prose source never affects any
  non-body field (Req 4.3, 4.5, 5.5).

Design constraints pinned here
------------------------------
* **Deterministic & pure.** ``segment_id`` and ``wire_segment`` consult no model, perform
  no I/O, and never mutate their inputs (the consumed ``PlannedSegment``/``CompositionBlueprint``
  are treated read-only, Req 2.6). The ontology ``Segment`` is a *non-frozen* dataclass
  with mutable ``list`` fields, so ``wire_segment`` builds **fresh** ``list`` instances for
  ``roles``/``subjects``/``related`` (never aliasing the frozen planner tuples).
* **Filesystem-safe ids.** ``segment_id`` sanitizes the human-scannable ``segment_key``
  (lowercasing and collapsing every character outside ``[a-z0-9-]`` to ``-``) and appends a
  short, stable hash of the *raw* ``segment_key`` so distinct keys always yield distinct
  ids — even when two keys sanitize to the same prefix — and the id is never ``""``,
  ``"."``, or ``".."``.
* **The model contributes only ``body``/``summary``** (Req 5.5): every non-body field is
  fixed by the deterministic wiring regardless of whether the prose came from the model,
  the deterministic fallback, or a fake/recorded provider.
"""

from __future__ import annotations

import hashlib
import re

from docuharnessx.composition.model import CompositionBlueprint, ProseResult
from docuharnessx.ontology import SCHEMA_VERSION, Segment
from docuharnessx.planning.model import PlannedSegment

__all__ = ["segment_id", "wire_segment"]

#: Length (hex chars) of the stable id-disambiguation hash appended to a sanitized
#: ``segment_key``. 12 hex chars (48 bits) keeps the id compact and human-scannable while
#: making an accidental collision between two distinct ``segment_key`` values vanishingly
#: unlikely (the ``segment_key`` is itself already unique per planned cell).
_ID_HASH_LEN: int = 12

#: Every character outside this safe class is collapsed to a single ``-`` so the id is a
#: valid single-segment filename (no path separators, no leading dot-traversal). Lowercase
#: only because ``segment_key`` axis ids are already lowercased upstream; we lowercase
#: defensively so case never affects the sanitized prefix.
_UNSAFE_RUN = re.compile(r"[^a-z0-9]+")


def _short_hash(value: str) -> str:
    """A short, stable hex digest over ``value`` (deterministic across runs/processes)."""
    return hashlib.blake2b(
        value.encode("utf-8"), digest_size=_ID_HASH_LEN // 2
    ).hexdigest()


def _sanitize(segment_key: str) -> str:
    """Collapse ``segment_key`` to a lowercase ``[a-z0-9-]`` slug (no leading/trailing ``-``).

    Returns ``""`` when nothing safe survives (an all-symbol key); the caller always
    appends a non-empty hash so the final id is never empty.
    """
    slug = _UNSAFE_RUN.sub("-", segment_key.lower())
    return slug.strip("-")


def segment_id(planned: PlannedSegment) -> str:
    """Derive a deterministic, filesystem-safe, unique id from ``planned`` (Req 4.4).

    The id is ``"<sanitized-segment_key>-<short-hash>"`` (or just ``"<short-hash>"`` when
    the sanitized key is empty). It is:

    * **Deterministic** — depends only on ``planned.segment_key``, so two distinct-but-equal
      planned segments (and two writer runs over an equal plan) yield equal ids.
    * **Filesystem-safe** — composed solely of ``[a-z0-9-]`` and never ``""``/``"."``/``".."``,
      so :class:`~docuharnessx.ontology.FilesystemSegmentStore` accepts it as a
      single-segment filename.
    * **Unique** — the appended hash is computed over the *raw* ``segment_key`` (already
      unique per planned cell), so two keys that sanitize to the same prefix still differ.

    Never mutates ``planned``.
    """
    digest = _short_hash(planned.segment_key)
    slug = _sanitize(planned.segment_key)
    return f"{slug}-{digest}" if slug else digest


def wire_segment(
    planned: PlannedSegment,
    blueprint: CompositionBlueprint,
    prose: ProseResult,
) -> Segment:
    """Map ``planned`` + ``blueprint`` + ``prose`` into a new ontology ``Segment``.

    Sets the **non-body** fields deterministically — ``id`` (:func:`segment_id`),
    ``roles``/``subjects``/``intent`` (copied from ``planned``), ``title`` (from the
    ``blueprint``), ``related`` (an empty list — this stage emits no cross-links),
    ``schema_version`` (:data:`~docuharnessx.ontology.SCHEMA_VERSION`) — and takes
    ``body``/``summary`` **only** from ``prose`` (Req 4.3, 4.5, 5.5).

    Treats every input as read-only (Req 2.6): the mutable ``roles``/``subjects``/``related``
    lists on the returned ``Segment`` are *fresh* instances, so mutating the new segment
    never reaches back into the frozen planner tuples or the blueprint.
    """
    return Segment(
        id=segment_id(planned),
        title=blueprint.title,
        roles=list(planned.roles),  # fresh list; never alias the frozen tuple
        subjects=list(planned.subjects),  # fresh list of the typed Subject values
        intent=planned.intent,
        summary=prose.summary,  # prose-only (Req 5.5)
        related=[],  # this stage emits no cross-links (default empty, Req 4.3)
        body=prose.body,  # prose-only (Req 5.5)
        schema_version=SCHEMA_VERSION,
    )
