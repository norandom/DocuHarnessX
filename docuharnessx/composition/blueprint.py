"""The deterministic COBESY blueprint builder (cobesy-writer task 2.1).

This module owns the *Blueprint Builder* boundary of the Wave 2 ``cobesy-writer``:
:func:`build_blueprint` turns one frozen :class:`~docuharnessx.planning.model.PlannedSegment`
(plus the optional :class:`~docuharnessx.analysis.model.RepoAnalysis` and the loaded
:class:`~docuharnessx.ontology.Vocabulary`) into a deterministic
:class:`~docuharnessx.composition.model.CompositionBlueprint` — the COBESY structure built
*before* any prose (design "Blueprint Builder"; Req 3.1).

It is a **pure function**: no model, no I/O, no global state, never mutates its inputs
(Req 2.6, 3.1, 3.6). Every structural decision — the SCQA opener, the Minto
lead-with-conclusion key message, the working-memory chunking plan, the REDUCE-barrier
fast path, the andragogy (expert-framing) flag, and the title — is derived from the
segment's ``roles``/``intent`` looked up in the **loaded** ``Vocabulary``
(:class:`~docuharnessx.ontology.AxisTerm` ``label``/``description``), never from a
hardcoded role/intent/subject literal (Req 3.2, 9.1, 9.2). The configurable-vocabulary
principle is load-bearing: the same builder writes correct structure for any project
profile, so a renamed/redescribed term changes the output without a code change.

Andragogy is decided per the loaded vocabulary term, not a closed role set (Req 3.4):
:func:`_is_expert_role` is a documented heuristic over the loaded ``AxisTerm``'s
``id``/``label``/``description`` text — a project that redescribes a role as expert work
flips the flag with no code edit (see ``test_andragogy_follows_vocabulary_not_role_id``).

Evidence anchors are built from ``planned.evidence`` verbatim (``kind``/``detail``) and
enriched with a short ``note`` from the *matching* ``RepoAnalysis`` finding when one is
present; an absent ``analysis`` (or no match) is tolerated and the note falls back to
``""`` so no repository fact is invented (Req 2.5, 3.5).

Determinism is structural: the builder reads only frozen, pre-ordered inputs and emits a
frozen :class:`CompositionBlueprint`, so equal inputs always produce an equal — and
hashable — blueprint (Req 3.6, 9.3). It is the deterministic backbone the prompt assembler
(task 2.2), the wiring (task 2.3), and the fallback renderer (task 2.4) all consume.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from docuharnessx.composition.model import (
    Chunk,
    CompositionBlueprint,
    EvidenceAnchor,
    SCQAOpener,
)

if TYPE_CHECKING:  # frozen seams consumed verbatim — typing-only imports.
    from docuharnessx.analysis.model import RepoAnalysis
    from docuharnessx.ontology import AxisTerm, Subject, Vocabulary
    from docuharnessx.planning.model import EvidenceRef, PlannedSegment

__all__ = ["build_blueprint"]


# --------------------------------------------------------------------------- #
# Andragogy heuristic (Req 3.4, 9.2) — over the LOADED vocabulary term         #
# --------------------------------------------------------------------------- #

#: Documented expert-signal tokens matched (case-insensitively, as substrings)
#: against a role's loaded ``AxisTerm`` ``id``/``label``/``description``. This is a
#: heuristic over the *loaded* vocabulary text — NOT a closed set of role ids — so a
#: project that describes a role as expert/builder/operator work gets andragogy framing
#: without a code change (Req 3.4, 9.2). A reader whose role text signals deep,
#: hands-on, build/operate/assess work is treated as an adult expert (Knowles: respect
#: prior knowledge, problem-centered framing).
_EXPERT_SIGNAL_TOKENS: tuple[str, ...] = (
    "develop",
    "build",
    "internals",
    "extend",
    "contribut",
    "integrat",
    "operat",
    "admin",
    "sre",
    "on-call",
    "research",
    "security",
    "compliance",
    "audit",
    "architect",
    "engineer",
    "expert",
    "advanced",
    "deep",
    "maintain",
    "deploy",
)


def _is_expert_role(term: "AxisTerm") -> bool:
    """Return whether a role's loaded ``AxisTerm`` signals an expert audience.

    Documented heuristic (Req 3.4, 9.2): the role's ``id``, ``label``, and
    ``description`` are scanned (case-insensitively) for any
    :data:`_EXPERT_SIGNAL_TOKENS` substring. This reads the *loaded* vocabulary term
    rather than a closed role-id enum, so re-describing a role as expert work flips the
    result with no code change. Deterministic and side-effect-free.
    """
    haystack = f"{term.id} {term.label} {term.description}".casefold()
    return any(token in haystack for token in _EXPERT_SIGNAL_TOKENS)


# --------------------------------------------------------------------------- #
# Vocabulary lookups (Req 9.1, 9.2) — labels read from the LOADED vocabulary   #
# --------------------------------------------------------------------------- #


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


def _role_labels(planned: "PlannedSegment", vocab: "Vocabulary") -> tuple[str, ...]:
    """The display labels for the segment's roles, in the planner's declared order.

    Reads each label from the loaded ``Vocabulary`` (Req 9.2); an id the vocabulary
    does not carry deterministically falls back to the id itself rather than raising
    (the planner guarantees membership, but the builder stays total and pure).
    """
    labels: list[str] = []
    for role_id in planned.roles:
        term = _role_term(role_id, vocab)
        labels.append(term.label if term is not None else role_id)
    return tuple(labels)


def _intent_label(planned: "PlannedSegment", vocab: "Vocabulary") -> str:
    """The display label for the segment's intent, read from the loaded vocabulary."""
    term = _intent_term(planned.intent, vocab)
    return term.label if term is not None else planned.intent


# --------------------------------------------------------------------------- #
# Subject helpers                                                              #
# --------------------------------------------------------------------------- #


def _leading_subject(planned: "PlannedSegment") -> "Subject | None":
    """The primary subject (the first in the planner's canonical order), or ``None``.

    ``PlannedSegment.subjects`` is pre-sorted by ``Subject.canonical()``, so the head is
    a deterministic primary subject the title/SCQA/fast-path can anchor on.
    """
    return planned.subjects[0] if planned.subjects else None


def _subject_phrase(subject: "Subject | None") -> str:
    """A human phrase for a subject, deterministic; ``"the project"`` when absent."""
    if subject is None:
        return "the project"
    return subject.local


# --------------------------------------------------------------------------- #
# Evidence anchors (Req 2.5, 3.5)                                              #
# --------------------------------------------------------------------------- #


def _analysis_note(ref: "EvidenceRef", analysis: "RepoAnalysis | None") -> str:
    """A short, deterministic note enriching an evidence ref from a matching finding.

    Tolerates ``analysis is None`` and a non-matching ``detail`` by returning ``""`` —
    no repository fact is invented (Req 2.5). When the analysis carries a finding whose
    path/detail equals ``ref.detail``, a compact note grounds the anchor in that real
    finding (Req 3.5). Matching is by ``ref.detail`` against the finding ``path``, scoped
    to the analysis regions the planner cites in its evidence ``kind`` taxonomy.
    """
    if analysis is None:
        return ""

    detail = ref.detail

    # entrypoints: detail is a repo-relative path; enrich with kind + symbolic name.
    for entry in analysis.entrypoints:
        if entry.path == detail:
            name = f" ({entry.name})" if entry.name else ""
            return f"entrypoint: {entry.kind}{name}"

    # components: detail may be a component path; enrich with the component name.
    for component in analysis.components:
        if component.path == detail:
            return f"component: {component.name}"

    # build files / CI / artifacts: enrich with the classified kind/provider.
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
    planned: "PlannedSegment", analysis: "RepoAnalysis | None"
) -> tuple[EvidenceAnchor, ...]:
    """Build the grounding anchors from ``planned.evidence`` (+ matching analysis).

    Each anchor copies the planner's ``EvidenceRef.kind``/``detail`` verbatim (read-only,
    Req 2.6, 3.5) and adds a ``note`` from the matching ``RepoAnalysis`` finding when one
    is present (``""`` otherwise). Order follows ``planned.evidence`` (already sorted by
    ``(kind, detail)``), so anchors are deterministic.
    """
    return tuple(
        EvidenceAnchor(
            kind=ref.kind,
            detail=ref.detail,
            note=_analysis_note(ref, analysis),
        )
        for ref in planned.evidence
    )


# --------------------------------------------------------------------------- #
# COBESY structure (Req 3.2, 3.3) — derived from the loaded vocabulary labels  #
# --------------------------------------------------------------------------- #


def _join_roles(role_labels: tuple[str, ...]) -> str:
    """Join role labels into a deterministic phrase (oxford-free, comma + 'and')."""
    if not role_labels:
        return "the reader"
    if len(role_labels) == 1:
        return role_labels[0]
    if len(role_labels) == 2:
        return f"{role_labels[0]} and {role_labels[1]}"
    return ", ".join(role_labels[:-1]) + f", and {role_labels[-1]}"


def _key_message(intent_label: str, subject_phrase: str, role_phrase: str) -> str:
    """The Minto lead-with-conclusion key message (Req 3.3).

    A single declarative sentence stating the conclusion up front: what the reader does
    with the subject for this intent. Built only from vocabulary-derived labels.
    """
    return (
        f"{intent_label}: the fastest path for {role_phrase} to work with "
        f"{subject_phrase} is the short sequence below."
    )


def _build_scqa(
    intent_label: str,
    subject_phrase: str,
    role_phrase: str,
    key_message: str,
) -> SCQAOpener:
    """The SCQA opener tuned to the role(s)+intent labels (Req 3.2, 3.3).

    The ``answer`` echoes the Minto lead conclusion (``key_message``) so the body leads
    with the conclusion. All four moves are built only from vocabulary-derived labels.
    """
    return SCQAOpener(
        situation=(
            f"You are {role_phrase} working with {subject_phrase}."
        ),
        complication=(
            f"Reaching the {intent_label} goal for {subject_phrase} is unclear "
            "without a guided path."
        ),
        question=(
            f"How do you {intent_label} {subject_phrase} on the shortest path?"
        ),
        answer=key_message,
    )


def _build_chunks(
    intent_label: str,
    subject_phrase: str,
    role_phrase: str,
    anchors: tuple[EvidenceAnchor, ...],
) -> tuple[Chunk, ...]:
    """The working-memory chunking plan (Req 3.3): a small, MECE set of chunks.

    Kept bounded (orientation, the core path, and — only when evidence exists — an
    evidence-grounding chunk) so the reader holds the structure within working memory
    (the 7+/-2 rule). Every point is built only from vocabulary-derived labels and the
    (verbatim) evidence anchors, so the chunks are deterministic.
    """
    chunks: list[Chunk] = [
        Chunk(
            heading="Orientation",
            points=(
                f"Who this is for: {role_phrase}.",
                f"Goal: {intent_label} {subject_phrase}.",
            ),
        ),
        Chunk(
            heading=f"{intent_label}: the core path",
            points=(
                f"Start with {subject_phrase}.",
                f"Follow the fast path to {intent_label}.",
                "Confirm the result before moving on.",
            ),
        ),
    ]
    if anchors:
        chunks.append(
            Chunk(
                heading="Grounding",
                points=tuple(
                    f"{anchor.kind}: {anchor.detail}"
                    + (f" — {anchor.note}" if anchor.note else "")
                    for anchor in anchors
                ),
            )
        )
    return tuple(chunks)


def _build_fast_path(intent_label: str, subject_phrase: str) -> tuple[str, ...]:
    """The REDUCE-barrier fast-path cues to first success (Req 3.3).

    A short, ordered list of barrier-removing steps to first success — REDUCE keeps the
    reader moving instead of pushing more content. Deterministic, label-only.
    """
    return (
        f"Locate {subject_phrase}.",
        f"Run the smallest action that makes progress toward {intent_label}.",
        "Verify you reached first success, then stop.",
    )


def _build_title(intent_label: str, subject_phrase: str) -> str:
    """A deterministic title from the intent label applied to the leading subject."""
    return f"{intent_label}: {subject_phrase}"


# --------------------------------------------------------------------------- #
# Public entry point                                                          #
# --------------------------------------------------------------------------- #


def build_blueprint(
    planned: "PlannedSegment",
    analysis: "RepoAnalysis | None",
    vocab: "Vocabulary",
) -> CompositionBlueprint:
    """Build the deterministic COBESY blueprint for one planned segment (Req 3.1).

    Pure and model-free: derives the SCQA opener, the Minto key message, the
    working-memory chunks, the REDUCE-barrier fast path, the andragogy flag, the title,
    and the evidence anchors from the segment's ``roles``/``intent`` looked up in the
    **loaded** ``Vocabulary`` (``AxisTerm`` labels/descriptions) — never from a hardcoded
    role/intent/subject literal (Req 3.2, 9.1, 9.2). Andragogy is decided per the loaded
    term, not a closed role set (Req 3.4). Evidence anchors copy ``planned.evidence``
    verbatim and enrich with a matching ``RepoAnalysis`` finding when present, tolerating
    ``analysis is None`` (Req 2.5, 3.5).

    Preconditions: ``planned.roles``/``intent`` are normally vocabulary members (planner
    guarantees this); an absent id degrades to its own string deterministically rather
    than raising. ``analysis`` may be ``None``.

    Postconditions: returns a fully-populated, frozen :class:`CompositionBlueprint`; equal
    inputs yield an equal blueprint (Req 3.6). Invariants: never consults a model; never
    mutates ``planned``, ``analysis``, or ``vocab`` (Req 2.6).
    """
    role_labels = _role_labels(planned, vocab)
    intent_label = _intent_label(planned, vocab)
    role_phrase = _join_roles(role_labels)
    leading_subject = _leading_subject(planned)
    subject_phrase = _subject_phrase(leading_subject)

    anchors = _evidence_anchors(planned, analysis)
    key_message = _key_message(intent_label, subject_phrase, role_phrase)
    scqa = _build_scqa(intent_label, subject_phrase, role_phrase, key_message)
    chunks = _build_chunks(intent_label, subject_phrase, role_phrase, anchors)
    fast_path = _build_fast_path(intent_label, subject_phrase)
    title = _build_title(intent_label, subject_phrase)

    # Andragogy: expert when ANY of the segment's roles signals expert work in the
    # loaded vocabulary (Req 3.4). A missing term defaults to non-expert.
    andragogy = any(
        _is_expert_role(term)
        for term in (_role_term(role_id, vocab) for role_id in planned.roles)
        if term is not None
    )

    return CompositionBlueprint(
        segment_key=planned.segment_key,
        roles=planned.roles,
        intent=planned.intent,
        subjects=planned.subjects,
        title=title,
        scqa=scqa,
        key_message=key_message,
        chunks=chunks,
        fast_path=fast_path,
        andragogy=andragogy,
        evidence_anchors=anchors,
        role_labels=role_labels,
        intent_label=intent_label,
    )
