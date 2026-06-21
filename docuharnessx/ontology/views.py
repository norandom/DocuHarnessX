"""Role-view derivation (the ``views`` component).

A *role view* is one role-targeted slice of the corpus: all segments that carry
a given role, ordered so the role's reader meets them in a sensible sequence.
This is how one corpus produces many role-targeted views through *reuse* rather
than duplication (Req 10): a multi-role segment is included in every role view it
carries, referencing the same stored segment — its content is never copied.

The single entry point is :func:`build_role_view`. It is a thin *consumer* of the
:class:`~docuharnessx.ontology.store.SegmentStore` port and the loaded
:class:`~docuharnessx.ontology.vocabulary.Vocabulary`; it owns no storage and
adds no new I/O. It:

* queries the store for every segment carrying ``role_id`` via an
  :class:`~docuharnessx.ontology.store.AxisFilter` (Req 10.1, 10.3);
* orders the result by the vocabulary's documented intent order
  (``vocab.intent_order()``), with the segment ``id`` as a stable secondary key
  for intent ties (Req 10.2, 10.4); a segment whose intent is not in the
  vocabulary's intent order is placed deterministically *after* all known-intent
  segments, then by id;
* returns an empty tuple — NOT an error — when no segment carries the role
  (Req 10.5).

Ordering is fully deterministic: identical inputs yield an identical ordered
tuple across runs (Req 11.2).
"""

from __future__ import annotations

from docuharnessx.ontology.schema import Segment
from docuharnessx.ontology.store import AxisFilter, SegmentStore
from docuharnessx.ontology.vocabulary import Vocabulary

__all__ = ["build_role_view"]


def build_role_view(
    store: SegmentStore, role_id: str, vocab: Vocabulary
) -> tuple[Segment, ...]:
    """Return the role view for ``role_id`` as an ordered tuple of segments.

    Queries ``store`` for every segment that carries ``role_id`` (per-axis OR
    over a single value), then orders the matches by the vocabulary's intent
    order with the segment ``id`` as a stable tie-break (Req 10.1-10.4). A
    segment whose ``intent`` is not a member of ``vocab.intent_order()`` is
    ordered after all known-intent segments (then by id), so the result stays
    total and deterministic. When no segment carries the role, an empty tuple is
    returned rather than raising (Req 10.5).

    The returned segments are the stored segments themselves — a multi-role
    segment appears in each of its roles' views without its content being
    duplicated (Req 10.3).
    """
    matches = store.query(AxisFilter(roles=(role_id,)))

    intent_order = vocab.intent_order()
    # Index lookup is O(1) and the fallback rank (len) sorts unknown intents
    # last while keeping the key total and comparable (Req 10.2, 10.4).
    rank = {intent_id: position for position, intent_id in enumerate(intent_order)}
    unknown_rank = len(intent_order)

    return tuple(
        sorted(
            matches,
            key=lambda segment: (rank.get(segment.intent, unknown_rank), segment.id),
        )
    )
