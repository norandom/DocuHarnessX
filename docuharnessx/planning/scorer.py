"""Deterministic cell scoring + the total ordering key (task 3.1, boundary: scorer).

This is the *scorer* component of the deterministic planning core. It turns an
activated :class:`~docuharnessx.planning.model.CandidateCell` into a single integer
``priority`` and defines the **total** ordering key the planner sorts
:class:`~docuharnessx.planning.model.PlannedSegment` values by — so two runs over equal
inputs produce byte-identical scores and ordering, with no ties left unbroken (design
"scorer — deterministic scoring and ordering"; Req 5.1, 5.2, 5.3).

Scoring model (all integer arithmetic — no floats, so no platform-dependent
formatting, Req 5.1)
---------------------------------------------------------------------------------
A cell's ``priority`` combines two deterministic signals:

* **Evidence** — the count *and* strength of the activating findings. Each
  :class:`~docuharnessx.planning.model.EvidenceRef` contributes a positive
  *kind-strength* weight (``_EVIDENCE_KIND_WEIGHT``), defaulting to ``1`` for an
  unrecognized kind so every additional finding raises the score. Summed across the
  cell's evidence, this guarantees that a cell with *more* supporting evidence scores
  *strictly higher* than an otherwise-equal cell (Req 5.1).
* **Role / intent position** — a *documented* role weight and intent weight resolved
  **purely by id position in the loaded** :class:`~docuharnessx.ontology.Vocabulary`
  (an earlier-declared role/intent weighs more). This is never a hardcoded role/intent
  table: a custom vocabulary's own ordering drives the weighting, so the same analysis
  yields a project-specific ranking (Req 5.1, 4.1, 4.2). A cell may serve several roles;
  its role weight is the *strongest* (earliest-positioned) member so adding a
  higher-priority role never lowers the score.

The evidence term is scaled by the full positional budget
(``max_role_weight + max_intent_weight + 1``) so that one extra unit of evidence always
dominates the entire role+intent contribution — i.e. evidence strength is the primary
score signal and position only ever breaks evidence ties. The result is a plain ``int``.

Total ordering (Req 5.2, 5.3)
-----------------------------
:func:`order_key` returns ``(-priority, role_rank, intent_rank, segment_key)``:

* ``-priority`` — higher priority sorts first (descending);
* ``role_rank`` — the cell's strongest role's position in ``vocab.roles`` (earlier
  first); an id absent from the vocabulary gets a stable sentinel rank that sorts after
  every known id;
* ``intent_rank`` — the intent's position in ``vocab.intent_order()`` (the documented
  intent ordering reused as the stable secondary key, Req 4.4); unknown ids likewise
  sort last;
* ``segment_key`` — the deterministic plan-local key, the final stable tie-breaker so
  the order is **total**: distinct segments never collide.

This module is pure, model-free, and side-effect-free; it imports only this spec's model
records and the ontology :class:`~docuharnessx.ontology.Vocabulary` (read-only).
"""

from __future__ import annotations

from docuharnessx.ontology import Vocabulary
from docuharnessx.planning.model import CandidateCell, PlannedSegment

__all__ = ["score_cell", "order_key"]


# Per-kind evidence *strength* weights. Each activating finding contributes its weight;
# an unrecognized kind contributes the floor weight ``1`` so every additional finding
# still raises the score (monotonic-in-count, Req 5.1). The relative ordering encodes a
# documented, auditable judgement of how directly a finding evidences a coverage cell:
# a concrete entrypoint/integration surface is the strongest signal; a bare language
# stat the weakest. These are deterministic integers, not learned weights.
_EVIDENCE_KIND_WEIGHT: dict[str, int] = {
    "entrypoint": 5,
    "api": 5,
    "exported_symbol": 5,
    "integration": 5,
    "ci": 4,
    "build": 4,
    "test": 3,
    "component": 3,
    "artifact": 3,
    "dependency": 2,
    "doc": 2,
    "topic": 2,
    "language": 1,
}

#: Floor weight for an evidence ref whose ``kind`` is not in the table above. Positive so
#: every additional finding strictly increases the evidence sum (Req 5.1).
_DEFAULT_EVIDENCE_WEIGHT: int = 1


def _evidence_weight(cell: CandidateCell) -> int:
    """Sum the kind-strength weights of every activating finding (>= 0)."""
    return sum(
        _EVIDENCE_KIND_WEIGHT.get(ref.kind, _DEFAULT_EVIDENCE_WEIGHT)
        for ref in cell.evidence
    )


def _position_weight(item_id: str, ordered_ids: tuple[str, ...]) -> int:
    """Positional weight of ``item_id`` within ``ordered_ids`` (earlier = heavier).

    A member at position ``i`` of ``n`` declared ids weighs ``n - i`` (so the first id
    weighs ``n`` and the last weighs ``1``). An id absent from ``ordered_ids`` weighs
    ``0`` — it never out-weighs any declared id but keeps scoring total and crash-free
    for ids outside the loaded vocabulary.
    """
    try:
        index = ordered_ids.index(item_id)
    except ValueError:
        return 0
    return len(ordered_ids) - index


def _role_ids(vocab: Vocabulary) -> tuple[str, ...]:
    """The loaded vocabulary's role ids in declared order."""
    return tuple(role.id for role in vocab.roles)


def _strongest_role_weight(roles: tuple[str, ...], role_ids: tuple[str, ...]) -> int:
    """The heaviest (earliest-positioned) role weight among ``roles`` (0 if none)."""
    if not roles:
        return 0
    return max(_position_weight(role_id, role_ids) for role_id in roles)


def score_cell(cell: CandidateCell, vocab: Vocabulary) -> int:
    """Assign ``cell`` a deterministic integer priority (higher = more important).

    Combines the cell's evidence strength/count with role/intent position weights drawn
    from the loaded ``vocab`` (Req 5.1). The evidence term is scaled by the full
    positional budget so one extra unit of evidence always outweighs the entire
    role+intent contribution — evidence is the primary signal, position only breaks
    evidence ties. Pure and deterministic: equal inputs always yield the identical
    ``int`` (Req 5.3).
    """
    role_ids = _role_ids(vocab)
    intent_ids = vocab.intent_order()

    # The maximum positional weight on each axis is the count of declared ids (the first
    # position). The positional budget is the largest role+intent weight a cell can ever
    # carry; scaling evidence by (budget + 1) makes evidence strictly dominant.
    max_role_weight = len(role_ids)
    max_intent_weight = len(intent_ids)
    positional_budget = max_role_weight + max_intent_weight
    evidence_scale = positional_budget + 1

    evidence_weight = _evidence_weight(cell)
    role_weight = _strongest_role_weight(cell.roles, role_ids)
    intent_weight = _position_weight(cell.intent, intent_ids)

    return evidence_weight * evidence_scale + role_weight + intent_weight


def _rank(item_id: str, ordered_ids: tuple[str, ...]) -> int:
    """Sort rank of ``item_id`` within ``ordered_ids`` (earlier = smaller).

    A declared id ranks by its position; an id absent from the vocabulary ordering gets
    a sentinel rank one past the end so it sorts deterministically *after* every known
    id without raising — keeping the ordering total even for out-of-vocabulary ids.
    """
    try:
        return ordered_ids.index(item_id)
    except ValueError:
        return len(ordered_ids)


def order_key(seg: PlannedSegment, vocab: Vocabulary) -> tuple[int, int, int, str]:
    """The total ordering key for a planned ``seg``: ``(-priority, role, intent, key)``.

    Sorting a sequence of :class:`~docuharnessx.planning.model.PlannedSegment` by this
    key yields the plan's documented order: descending priority, then the loaded
    vocabulary's role order, then its ``intent_order()``, then the stable ``segment_key``
    (Req 5.2). Because ``segment_key`` is unique per planned cell, the order is **total**
    — distinct segments never produce equal keys — and reproducible across runs (Req 5.3).
    """
    role_ids = _role_ids(vocab)
    intent_ids = vocab.intent_order()
    # The cell's strongest (earliest) role drives ordering, matching the strongest-role
    # weighting used in scoring; an empty roles tuple sorts after every known role.
    role_rank = min((_rank(r, role_ids) for r in seg.roles), default=len(role_ids))
    intent_rank = _rank(seg.intent, intent_ids)
    return (-seg.priority, role_rank, intent_rank, seg.segment_key)
