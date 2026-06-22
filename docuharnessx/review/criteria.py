"""The fixed COBESY criteria definition and the deterministic gate rules.

This module is the **gate definition** of the Wave 2 ``quality-review-gate``
review core (design "COBESY criteria definition" + "Verdict Computer"; Req 3.1,
3.5, 6.3). At task 1.2 it pins, as plain importable constants and pure
model-free rule functions, *what* the COBESY gate is and *how* per-criterion
outcomes combine into a single segment verdict — applied identically to every
segment, with no model consulted. The per-segment :class:`SegmentCriteria`
builder (:func:`build_criteria`, task 2.1) is appended here; it derives the
role/intent context from the loaded vocabulary and the evidence anchors from the
matching planned segment (+ analysis), and shares the fixed definition below.

What is pinned here
-------------------
* :data:`COBESY_CRITERIA` — the fixed, named gate (Req 3.1): MECE structure,
  working-memory fit, role-fit, clarity, falsifiability/evidence grounding, and
  absence of AI-slop. These are *quality dimensions*, deliberately free of any
  project's role / intent / subject literals — the role-fit and intent context
  is derived per segment from the loaded :class:`~docuharnessx.ontology.Vocabulary`
  at ``build_criteria`` time (Req 10.1), never from a hardcoded table here.
* :data:`CRITERION_THRESHOLD` — the single, reviewable per-criterion pass
  threshold (Req 3.5). A criterion *passes* when its score is at or above this
  threshold (:func:`meets_threshold`); the threshold is named once here rather
  than scattered through prose so the gate stays deterministic and reviewable.
* The all-of combination rule (:func:`combine_verdict`, Req 3.5): a segment
  *passes* iff **every** criterion's ``passed`` flag is true; otherwise it
  fails. The rule reads the per-criterion ``passed`` flags (already
  threshold-coerced by ``parse``/the verdict computer), independent of any
  raw score value or free-form judge prose (Req 6.1), and is applied identically
  to every segment.
* :data:`DEFAULT_UNAVAILABLE_VERDICT` — the fail-closed default verdict for an
  unavailable judge (Req 6.3): a **reject** (``"fail"``). A quality firewall does
  not pass unjudged content, so a model-less / failed / timed-out / unparseable
  judge yields a deterministic default-reject (applied by the verdict computer
  with ``judge_source="unavailable"``).

The module is pure and model-free: it imports only the frozen value objects from
:mod:`docuharnessx.review.model` and stdlib typing. Equal inputs yield equal
outputs on every run (Req 3.4, 8.3, 10.3).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from docuharnessx.review.model import (
    CriterionScore,
    EvidenceAnchor,
    RoleContext,
    SegmentCriteria,
    Verdict,
)

if TYPE_CHECKING:  # frozen seams consumed verbatim — typing-only imports.
    from docuharnessx.analysis.model import RepoAnalysis
    from docuharnessx.ontology import AxisTerm, Segment, Vocabulary
    from docuharnessx.planning.model import EvidenceRef, PlannedSegment

__all__ = [
    "COBESY_CRITERIA",
    "CRITERION_THRESHOLD",
    "DEFAULT_UNAVAILABLE_VERDICT",
    "meets_threshold",
    "combine_verdict",
    "build_criteria",
]

#: The fixed, named COBESY validation gate applied to every written segment
#: (Req 3.1), in a stable order. Each name is also the ``CriterionScore.name`` /
#: ``CriterionTally.name`` value the judge scores and the report tallies:
#:
#: * ``"mece"`` — MECE structure (mutually exclusive, collectively exhaustive);
#: * ``"working_memory"`` — working-memory fit (digestible chunking / load);
#: * ``"role_fit"`` — the content matches the segment's roles and intent (judged
#:   against the loaded :class:`~docuharnessx.ontology.Vocabulary`, never a
#:   hardcoded role/intent list — Req 3.2, 10.1, 10.2);
#: * ``"clarity"`` — clear, unambiguous writing;
#: * ``"falsifiability"`` — falsifiability / evidence grounding against the
#:   segment's evidence anchors (Req 3.3);
#: * ``"no_ai_slop"`` — absence of AI-slop (filler, hedging, hallucinated detail).
#:
#: An immutable ``tuple[str, ...]`` so the gate definition is deeply immutable and
#: deterministic; intentionally free of any project role/intent/subject literal.
COBESY_CRITERIA: tuple[str, ...] = (
    "mece",
    "working_memory",
    "role_fit",
    "clarity",
    "falsifiability",
    "no_ai_slop",
)

#: The single per-criterion pass threshold (Req 3.5). A criterion *passes* when
#: its bounded ``[0,1]`` score is at or above this value (see
#: :func:`meets_threshold`). Named once here — not inlined in prose — so the gate
#: is reviewable in one place and applied identically to every criterion of every
#: segment. Used both to coerce a missing ``passed`` flag when parsing the judge
#: output and to keep the deterministic verdict independent of free-form prose.
CRITERION_THRESHOLD: float = 0.7

#: The fail-closed default verdict for an unavailable judge (Req 6.3): a
#: **reject** (``"fail"``). When no parseable judge verdict is obtained (a
#: model-less run, a fake judge without a valid verdict, or a failed / timed-out /
#: unparseable judge call), the verdict computer applies this default and marks
#: the entry ``judge_source="unavailable"`` — a quality firewall does not pass
#: unjudged content. A single named constant so the fail-closed policy is pinned
#: in one reviewable place.
DEFAULT_UNAVAILABLE_VERDICT: Verdict = "fail"


def meets_threshold(score: float) -> bool:
    """Return whether a single criterion ``score`` meets the pass threshold.

    The per-criterion threshold rule (Req 3.5): a criterion passes when its
    bounded ``[0,1]`` score is **at or above** :data:`CRITERION_THRESHOLD`
    (inclusive at the threshold). Pure and deterministic; applied identically to
    every criterion. Used to coerce a missing ``passed`` flag when parsing the
    judge output (``parse``) so the per-criterion outcome never depends on
    free-form prose.
    """

    return score >= CRITERION_THRESHOLD


def combine_verdict(scores: tuple[CriterionScore, ...]) -> Verdict:
    """Combine the per-criterion outcomes into a single segment verdict.

    The documented **all-of combination rule** (Req 3.5): a segment *passes*
    (returns ``"pass"``) iff **every** criterion's :attr:`CriterionScore.passed`
    flag is true; otherwise it *fails* (returns ``"fail"``). The rule reads the
    per-criterion ``passed`` flags only — already threshold-coerced by the parser
    / verdict computer — so the verdict is independent of any raw score value or
    free-form judge prose (Req 6.1), and is applied identically to every segment.

    An empty ``scores`` tuple cannot satisfy "every criterion passes" and so
    returns ``"fail"`` (fail-closed, consistent with the unavailable-judge
    default). Pure and deterministic: equal inputs yield an equal verdict on every
    run.
    """

    if not scores:
        return "fail"
    return "pass" if all(s.passed for s in scores) else "fail"


# --------------------------------------------------------------------------- #
# Per-segment criteria builder (task 2.1, design "Criteria Builder")           #
# --------------------------------------------------------------------------- #
#
# Pure and model-free: turns one written ``Segment`` (+ its matching
# ``PlannedSegment``, the optional ``RepoAnalysis``, and the loaded ``Vocabulary``)
# into a deterministic :class:`SegmentCriteria`. The role/intent context is read
# from the loaded vocabulary's ``AxisTerm`` labels/descriptions (never hardcoded,
# Req 3.2, 10.1, 10.2); the evidence anchors are built from the matching planned
# segment's evidence (+ matching analysis finding), mirroring the writer's
# blueprint anchors so the gate judges the same grounding the writer composed
# against (Req 2.5, 3.3). Equal inputs yield equal criteria (Req 3.4).


def _vocab_context(term: "AxisTerm | None", term_id: str) -> RoleContext:
    """Build the loaded-vocabulary :class:`RoleContext` for a role/intent term.

    Reads the display ``label`` and ``description`` from the loaded ``AxisTerm`` (Req 3.2,
    10.2). A ``None`` term (an id the loaded vocabulary does not carry) degrades
    deterministically to ``term_id`` as its own label with an empty description rather
    than raising — the writer guarantees membership, but the builder stays total and pure.
    """

    if term is None:
        return RoleContext(id=term_id, label=term_id, description="")
    return RoleContext(id=term.id, label=term.label, description=term.description)


def _role_term(role_id: str, vocab: "Vocabulary") -> "AxisTerm | None":
    """Return the loaded role ``AxisTerm`` for ``role_id``, or ``None`` if absent."""

    for term in vocab.roles:
        if term.id == role_id:
            return term
    return None


def _intent_term(intent_id: str, vocab: "Vocabulary") -> "AxisTerm | None":
    """Return the loaded intent ``AxisTerm`` for ``intent_id``, or ``None`` if absent."""

    for term in vocab.intents:
        if term.id == intent_id:
            return term
    return None


def _analysis_note(ref: "EvidenceRef", analysis: "RepoAnalysis | None") -> str:
    """A short, deterministic note enriching an evidence ref from a matching finding.

    Tolerates ``analysis is None`` and a non-matching ``detail`` by returning ``""`` — no
    repository fact is invented (Req 2.5). When the analysis carries a finding whose path
    equals ``ref.detail``, a compact note grounds the anchor in that real finding (Req
    3.3). Matching is by ``ref.detail`` against the finding ``path``, scoped to the
    analysis regions the planner cites in its evidence ``kind`` taxonomy — mirroring
    :func:`docuharnessx.composition.blueprint._analysis_note` so the gate grounds against
    the same findings the writer composed against.
    """

    if analysis is None:
        return ""

    detail = ref.detail

    for entry in analysis.entrypoints:
        if entry.path == detail:
            name = f" ({entry.name})" if entry.name else ""
            return f"entrypoint: {entry.kind}{name}"

    for component in analysis.components:
        if component.path == detail:
            return f"component: {component.name}"

    for build_file in analysis.build_files:
        if build_file.path == detail:
            return f"build file: {build_file.kind}"
    for workflow in analysis.ci_workflows:
        if workflow.path == detail:
            return f"ci workflow: {workflow.provider}"
    for artifact in analysis.artifacts:
        if artifact.path == detail:
            return f"artifact: {artifact.kind}"

    # No matching finding: do not invent a fact (Req 2.5).
    return ""


def _evidence_anchors(
    planned: "PlannedSegment | None", analysis: "RepoAnalysis | None"
) -> tuple[EvidenceAnchor, ...]:
    """Build the grounding anchors from the matching planned segment (+ analysis).

    Each anchor copies the planner's ``EvidenceRef.kind``/``detail`` verbatim (read-only,
    Req 2.6) and adds a ``note`` from the matching ``RepoAnalysis`` finding when one is
    present (``""`` otherwise). Order follows ``planned.evidence`` (already sorted by
    ``(kind, detail)``), so anchors are deterministic (Req 3.4). A written segment with no
    matching planned segment yields an empty tuple — criteria are still produced, never
    dropped (tasks.md 2.1).
    """

    if planned is None:
        return ()
    return tuple(
        EvidenceAnchor(
            kind=ref.kind,
            detail=ref.detail,
            note=_analysis_note(ref, analysis),
        )
        for ref in planned.evidence
    )


def build_criteria(
    segment: "Segment",
    planned: "PlannedSegment | None",
    analysis: "RepoAnalysis | None",
    vocab: "Vocabulary",
) -> SegmentCriteria:
    """Build the deterministic per-segment COBESY criteria context (Req 3.1-3.4).

    Pure and model-free: assembles the named :data:`COBESY_CRITERIA` gate, the segment's
    role/intent context (loaded-vocabulary :class:`~docuharnessx.review.model.RoleContext`
    labels/descriptions for the role-fit criterion — never hardcoded, Req 3.2, 10.1,
    10.2), the segment's identity/content, and the evidence anchors derived from the
    matching ``planned`` segment's evidence enriched by a matching ``analysis`` finding
    when present (Req 2.5, 3.3). Reads the role/intent ids from the *written segment*
    (validated upstream as vocabulary members) so the context reflects the content being
    judged.

    Tolerates absent inputs: a missing ``analysis`` falls back to evidence refs alone
    (note ``""``); a written segment with no matching ``planned`` segment still gets
    criteria with empty evidence anchors — never dropped (tasks.md 2.1). An id the loaded
    vocabulary does not carry degrades to the id as its own label rather than raising.

    Preconditions: ``segment.roles``/``intent`` are normally vocabulary members (the
    writer guarantees this); ``planned``/``analysis`` may be ``None``.

    Postconditions: returns a fully-populated, frozen
    :class:`~docuharnessx.review.model.SegmentCriteria`; equal inputs yield an equal
    criteria context and equal evidence anchors (Req 3.4).

    Invariants: never consults a model; never mutates ``segment``, ``planned``,
    ``analysis``, or ``vocab`` (Req 2.6) — the written ``Segment`` is treated read-only.
    """

    roles = tuple(
        _vocab_context(_role_term(role_id, vocab), role_id)
        for role_id in segment.roles
    )
    intent = _vocab_context(_intent_term(segment.intent, vocab), segment.intent)
    anchors = _evidence_anchors(planned, analysis)

    return SegmentCriteria(
        segment_id=segment.id,
        title=segment.title,
        summary=segment.summary,
        body=segment.body,
        criteria=COBESY_CRITERIA,
        roles=roles,
        intent=intent,
        evidence_anchors=anchors,
    )
