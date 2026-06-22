"""Unit tests for deterministic cell scoring + total ordering (task 3.1).

These tests pin the *scorer* boundary of the classification-coverage-planner:
``docuharnessx.planning.scorer`` assigns each :class:`CandidateCell` an integer
``priority`` derived from its evidence strength/count plus role/intent weights resolved
by *id position in the loaded, project-configurable* :class:`~docuharnessx.ontology.Vocabulary`
(never a hardcoded role/intent table), and defines an ``order_key`` of
``(-priority, role_rank, intent_rank, segment_key)`` that yields a total, reproducible
order with no ties left unbroken.

Observable completion (tasks.md 3.1):

* a cell with more supporting evidence scores strictly higher than an otherwise-equal
  cell;
* the ordering key produces a total, reproducible order;
* scores are identical across two runs over equal inputs.

Requirements: 5.1, 5.2, 5.3.
"""

from __future__ import annotations

from docuharnessx.ontology import AxisTerm, Subject, Vocabulary, default_profile
from docuharnessx.planning.model import CandidateCell, EvidenceRef, PlannedSegment
from docuharnessx.planning.scorer import order_key, score_cell


# --------------------------------------------------------------------------- #
# Fixtures                                                                      #
# --------------------------------------------------------------------------- #


def _vocab() -> Vocabulary:
    return default_profile()


def _subject(raw: str, vocab: Vocabulary) -> Subject:
    return Subject.parse(raw, frozenset(vocab.subject_prefixes))


def _cell(
    *,
    roles: tuple[str, ...],
    intent: str,
    subjects: tuple[Subject, ...] = (),
    evidence: tuple[EvidenceRef, ...] = (),
) -> CandidateCell:
    return CandidateCell(
        roles=roles, intent=intent, subjects=subjects, evidence=evidence
    )


def _seg(
    *,
    segment_key: str,
    roles: tuple[str, ...],
    intent: str,
    priority: int,
) -> PlannedSegment:
    return PlannedSegment(
        segment_key=segment_key,
        roles=roles,
        intent=intent,
        subjects=(),
        priority=priority,
        evidence=(),
    )


# --------------------------------------------------------------------------- #
# score_cell: evidence-monotonic, integer, deterministic                        #
# --------------------------------------------------------------------------- #


def test_score_is_a_plain_int() -> None:
    vocab = _vocab()
    cell = _cell(
        roles=("developer",),
        intent="extend",
        evidence=(EvidenceRef(kind="test", detail="x_test.go"),),
    )
    score = score_cell(cell, vocab)
    assert type(score) is int  # not a float; platform-stable formatting (Req 5.1)


def test_more_evidence_scores_strictly_higher() -> None:
    """A cell with more supporting evidence outscores an otherwise-equal cell (Req 5.1)."""
    vocab = _vocab()
    base = _cell(
        roles=("developer",),
        intent="extend",
        evidence=(EvidenceRef(kind="test", detail="a_test.go"),),
    )
    richer = _cell(
        roles=("developer",),
        intent="extend",
        evidence=(
            EvidenceRef(kind="test", detail="a_test.go"),
            EvidenceRef(kind="test", detail="b_test.go"),
        ),
    )
    assert score_cell(richer, vocab) > score_cell(base, vocab)


def test_no_evidence_scores_strictly_lower_than_some_evidence() -> None:
    vocab = _vocab()
    none = _cell(roles=("developer",), intent="extend", evidence=())
    some = _cell(
        roles=("developer",),
        intent="extend",
        evidence=(EvidenceRef(kind="component", detail="pkg/x"),),
    )
    assert score_cell(some, vocab) > score_cell(none, vocab)


def test_role_position_weights_score_when_evidence_equal() -> None:
    """Earlier-declared roles weigh more than later-declared ones (Req 5.1).

    With identical evidence and intent, a cell serving a higher-priority (earlier)
    role id in the loaded vocabulary scores at least as high — and the weighting is
    resolved purely by id position, never a hardcoded role list.
    """
    vocab = _vocab()
    ids = [r.id for r in vocab.roles]
    early, late = ids[0], ids[-1]
    ev = (EvidenceRef(kind="doc", detail="README.md"),)
    early_cell = _cell(roles=(early,), intent="evaluate", evidence=ev)
    late_cell = _cell(roles=(late,), intent="evaluate", evidence=ev)
    assert score_cell(early_cell, vocab) >= score_cell(late_cell, vocab)


def test_score_is_identical_across_two_runs() -> None:
    """Equal inputs yield identical scores across runs (Req 5.3)."""
    vocab = _vocab()
    cell = _cell(
        roles=("tech-savvy-user", "possible-adopter"),
        intent="install",
        subjects=(_subject("tech:go", vocab),),
        evidence=(
            EvidenceRef(kind="entrypoint", detail="main.go"),
            EvidenceRef(kind="ci", detail=".github/workflows/ci.yml"),
        ),
    )
    first = score_cell(cell, _vocab())
    second = score_cell(cell, _vocab())
    assert first == second


def test_score_uses_loaded_vocabulary_not_hardcoded_ids() -> None:
    """A custom vocabulary's own role/intent ids drive the weighting (Req 5.1, 4.1)."""
    custom = Vocabulary(
        roles=(
            AxisTerm(id="alpha", label="Alpha", description=""),
            AxisTerm(id="omega", label="Omega", description=""),
        ),
        intents=(
            AxisTerm(id="first", label="First", description=""),
            AxisTerm(id="last", label="Last", description=""),
        ),
        subject_prefixes=("tech:",),
    )
    ev = (EvidenceRef(kind="doc", detail="README.md"),)
    alpha = _cell(roles=("alpha",), intent="first", evidence=ev)
    omega = _cell(roles=("omega",), intent="last", evidence=ev)
    # Both are scorable against the custom vocab; the earlier role+intent weighs >=.
    assert score_cell(alpha, custom) >= score_cell(omega, custom)
    assert type(score_cell(alpha, custom)) is int


# --------------------------------------------------------------------------- #
# order_key: total, reproducible ordering with no unbroken ties                 #
# --------------------------------------------------------------------------- #


def test_order_key_primary_is_priority_descending() -> None:
    """Higher priority sorts first (Req 5.2)."""
    vocab = _vocab()
    hi = _seg(segment_key="b", roles=("developer",), intent="extend", priority=50)
    lo = _seg(segment_key="a", roles=("developer",), intent="extend", priority=10)
    ordered = sorted([lo, hi], key=lambda s: order_key(s, vocab))
    assert [s.priority for s in ordered] == [50, 10]


def test_order_key_breaks_priority_ties_by_role_then_intent_then_key() -> None:
    """Equal priority resolves by role order, then intent order, then segment_key (Req 5.2)."""
    vocab = _vocab()
    role_ids = [r.id for r in vocab.roles]
    early_role, late_role = role_ids[0], role_ids[1]
    intent_ids = vocab.intent_order()
    early_intent, late_intent = intent_ids[0], intent_ids[1]

    # Same priority everywhere; differ only on tie-break axes.
    by_role = [
        _seg(segment_key="z", roles=(late_role,), intent=early_intent, priority=7),
        _seg(segment_key="a", roles=(early_role,), intent=late_intent, priority=7),
    ]
    ordered = sorted(by_role, key=lambda s: order_key(s, vocab))
    # Role order dominates intent order and key.
    assert ordered[0].roles == (early_role,)

    # When role + intent are equal, the stable segment_key breaks the tie.
    same_cell = [
        _seg(segment_key="m", roles=(early_role,), intent=early_intent, priority=7),
        _seg(segment_key="a", roles=(early_role,), intent=early_intent, priority=7),
    ]
    ordered2 = sorted(same_cell, key=lambda s: order_key(s, vocab))
    assert [s.segment_key for s in ordered2] == ["a", "m"]


def test_order_key_is_total_no_unbroken_ties() -> None:
    """Distinct segments never produce equal order keys (Req 5.3)."""
    vocab = _vocab()
    role_ids = [r.id for r in vocab.roles]
    intent_ids = vocab.intent_order()
    segs = []
    for ri, role in enumerate(role_ids[:3]):
        for ii, intent in enumerate(intent_ids[:3]):
            segs.append(
                _seg(
                    segment_key=f"{role}__{intent}__{ri}{ii}",
                    roles=(role,),
                    intent=intent,
                    priority=(ri + ii) % 3,  # deliberate priority collisions
                )
            )
    keys = [order_key(s, vocab) for s in segs]
    assert len(set(keys)) == len(keys)  # every key unique => total order


def test_order_key_reproducible_across_two_runs() -> None:
    vocab = _vocab()
    seg = _seg(
        segment_key="tech-savvy-user__install__abc",
        roles=("tech-savvy-user",),
        intent="install",
        priority=42,
    )
    assert order_key(seg, _vocab()) == order_key(seg, _vocab())


def test_order_key_priority_dominates_role_order() -> None:
    """A lower-priority earlier-role segment still sorts after a higher-priority one."""
    vocab = _vocab()
    role_ids = [r.id for r in vocab.roles]
    early_role, late_role = role_ids[0], role_ids[-1]
    hi_late = _seg(segment_key="a", roles=(late_role,), intent="use", priority=99)
    lo_early = _seg(segment_key="b", roles=(early_role,), intent="use", priority=1)
    ordered = sorted([lo_early, hi_late], key=lambda s: order_key(s, vocab))
    assert ordered[0].priority == 99


def test_order_key_unknown_role_or_intent_sorts_last_deterministically() -> None:
    """Ids absent from the vocabulary order get a stable sentinel rank, never crash."""
    vocab = _vocab()
    known = _seg(
        segment_key="a", roles=("possible-adopter",), intent="install", priority=5
    )
    unknown = _seg(
        segment_key="b", roles=("not-a-role",), intent="not-an-intent", priority=5
    )
    ordered = sorted([unknown, known], key=lambda s: order_key(s, vocab))
    # Known vocabulary ids rank ahead of unknown ones at equal priority.
    assert ordered[0] is known
    # And it is total + reproducible even with the unknown ids present.
    assert order_key(unknown, vocab) == order_key(unknown, _vocab())
