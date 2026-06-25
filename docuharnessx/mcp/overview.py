"""The deterministic overview-shaped blueprint builder (mcp-refine task 2.2).

This is a **pure, model-free** glue module of the ``docuharnessx-mcp-refine`` server.
:func:`build_overview_blueprint` mirrors
:func:`~docuharnessx.composition.blueprint.build_blueprint` but produces the
**overview-shaped** plan: a single, project-wide
:class:`~docuharnessx.composition.model.CompositionBlueprint` whose four ordered chunk
headings are *Purpose / Use cases / Features / Design choices* (:data:`OVERVIEW_SECTION_HEADINGS`).
``draft_overview`` / ``refine_overview`` build this blueprint and run the **same** bounded
:class:`~docuharnessx.composition.AgenticProseRunner` + structure gate over it, so the
overview is grounded in the real repository exactly like the per-role pages (Req 7.1, 7.8).

Why the blueprint is overview-shaped, not role-shaped
-----------------------------------------------------
A role page targets one ``role(s)`` + ``intent`` cell. The overview is the project's *front
door* for **every** reader — so it carries no role targeting (``roles`` / ``role_labels`` are
empty rather than a hardcoded role literal). Its single intent is derived from the **loaded**
``Vocabulary``: the intent whose loaded ``AxisTerm`` text signals an understand/orient goal
(:func:`_overview_intent_term`, a documented heuristic over the loaded term, mirroring the
andragogy heuristic in :mod:`docuharnessx.composition.blueprint`), falling back to the first
intent and then to the empty string. No role/intent literal is hardcoded: re-describing the
vocabulary changes the derived label without a code edit (Req 7.1).

The four section headings (*Purpose / Use cases / Features / Design choices*) are the overview's
**defined shape** named verbatim by Req 7.1 — they are the overview's section structure (the
chunk headings the writer renders), not a role/intent axis, so they are the one fixed structural
literal this builder owns.

What ``guidance`` does (and does not do) here
---------------------------------------------
The ``guidance`` keyword is accepted **only for call-site uniformity** with the rewrite path —
it is deliberately **not** folded into the frozen blueprint. A
:class:`~docuharnessx.composition.model.CompositionBlueprint` has no guidance field, and a
``chunk`` renders as an output heading, so routing the human guidance through the blueprint
would leak it as a documentation section. The guidance reaches the agent the same applied,
never-echoed way the rewrite path uses: ``AgenticProseRunner.run(..., guidance=...)`` →
``build_agent_task`` → ``_render_description`` (an instruction near the mission, never a
heading). So the blueprint this builder returns is **independent of the guidance value**
(varying ``guidance`` yields an identical blueprint).

Salient subjects + evidence anchors
------------------------------------
* ``subjects`` are the project's **salient subjects** — derived from the optional
  ``RepoAnalysis`` via :func:`~docuharnessx.planning.subjects.derive_subjects`, which is
  vocab-prefix filtered and sorted by ``Subject.canonical()`` (so the subject namespace stays
  project-configurable, never hardcoded). An absent analysis yields an empty tuple.
* ``evidence_anchors`` are derived from the analysis's salient **entrypoints** and
  **components** (sorted by ``(kind, detail)`` for determinism); an absent analysis yields an
  empty tuple. No repository fact is invented — anchors copy real finding paths verbatim, and
  the agent re-grounds from its read-only workspace during the run.

Purity and determinism
-----------------------
Consults no model, performs no I/O, and never mutates ``identity`` / ``vocab`` / ``analysis``.
Equal inputs always yield an equal — and hashable — :class:`CompositionBlueprint` (Req 7.1).
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from docuharnessx.composition.model import (
    Chunk,
    CompositionBlueprint,
    EvidenceAnchor,
    ProseResult,
    SCQAOpener,
)
from docuharnessx.ontology import (
    SCHEMA_VERSION,
    Segment,
    parse_segment,
    serialize_segment,
    to_segment,
)
from docuharnessx.planning.subjects import derive_subjects

if TYPE_CHECKING:  # frozen seams consumed verbatim — typing-only imports.
    from docuharnessx.analysis.model import RepoAnalysis
    from docuharnessx.assembler import SiteIdentity
    from docuharnessx.ontology import AxisTerm, Subject, Vocabulary

__all__ = [
    "OVERVIEW_SECTION_HEADINGS",
    "OVERVIEW_SEGMENT_ID",
    "build_overview_blueprint",
    "wire_overview_segment",
    "persist_overview",
    "load_overview",
    "overview_path",
]

#: The reserved, fixed id of the project overview entry (research.md
#: ``OVERVIEW_SEGMENT_ID = "overview"``). The overview is persisted as a **reserved
#: first-class entry** with this id, distinct from the role-derived segment ids: a
#: ``draft_overview`` writes ``<segments>/overview.md`` and a later ``refine_overview``
#: re-serialises the same file in place. It is intentionally a fixed literal (not a
#: hash-derived id) so the front-door overview always lands at the same, discoverable path.
OVERVIEW_SEGMENT_ID: str = "overview"


#: The overview's four section headings, in render order, named verbatim by Req 7.1. These are
#: the overview's **defined section structure** (the chunk headings the writer renders) — the
#: one fixed structural literal this builder owns. They are NOT a role/intent axis: the per-role
#: labels and the single overview intent are derived from the loaded vocabulary (below).
OVERVIEW_SECTION_HEADINGS: tuple[str, ...] = (
    "Purpose",
    "Use cases",
    "Features",
    "Design choices",
)

#: Documented overview-intent signal tokens matched (case-insensitively, as substrings) against
#: an intent's loaded ``AxisTerm`` ``id``/``label``/``description`` to pick the project-wide
#: overview intent. This is a heuristic over the *loaded* vocabulary text — NOT a closed intent
#: id set — mirroring ``composition.blueprint._EXPERT_SIGNAL_TOKENS``: a project that renames or
#: re-describes its "understand/orient" intent still resolves it without a code change (Req 7.1).
_OVERVIEW_INTENT_SIGNAL_TOKENS: tuple[str, ...] = (
    "understand",
    "orient",
    "overview",
    "evaluate",
    "learn",
    "mental model",
)


def _overview_intent_term(vocab: "Vocabulary") -> "AxisTerm | None":
    """Pick the project-wide overview intent ``AxisTerm`` from the loaded vocabulary.

    Documented heuristic (Req 7.1): scans each intent's ``id``/``label``/``description``
    (case-insensitively) for an :data:`_OVERVIEW_INTENT_SIGNAL_TOKENS` substring and returns
    the first match — so a project that renames/re-describes its understand-intent still
    resolves it without a code change. Falls back to the first declared intent (a real
    vocabulary member, never an invented literal), or ``None`` when the vocabulary declares no
    intents at all. Deterministic and side-effect-free.
    """
    for term in vocab.intents:
        haystack = f"{term.id} {term.label} {term.description}".casefold()
        if any(token in haystack for token in _OVERVIEW_INTENT_SIGNAL_TOKENS):
            return term
    return vocab.intents[0] if vocab.intents else None


def _overview_title(identity: "SiteIdentity") -> str:
    """The project overview title, derived from ``identity.site_name`` (Req 7.1)."""
    return f"{identity.site_name}: Overview"


def _salient_subjects(
    analysis: "RepoAnalysis | None", vocab: "Vocabulary"
) -> "tuple[Subject, ...]":
    """The project's salient subjects, vocab-prefix filtered (empty when no analysis).

    Reuses :func:`~docuharnessx.planning.subjects.derive_subjects` — the deterministic,
    vocab-prefix-filtered subject deriver the planner uses — so the overview's subjects share
    the project-configurable subject namespace and are never hardcoded. ``analysis is None`` is
    tolerated and yields an empty tuple. The pairs are already sorted by ``Subject.canonical()``.
    """
    if analysis is None:
        return ()
    return tuple(subject for subject, _evidence in derive_subjects(analysis, vocab))


def _overview_evidence_anchors(
    analysis: "RepoAnalysis | None",
) -> tuple[EvidenceAnchor, ...]:
    """Evidence anchors from the analysis's salient entrypoints + components (Req 7.1).

    Copies the real finding paths verbatim into :class:`EvidenceAnchor` records — entrypoints
    (``kind="entrypoint"``, ``note`` carrying the detected kind + symbolic name) and components
    (``kind="component"``, ``note`` carrying the component name). No repository fact is invented
    (the paths are real findings; the agent re-grounds from the live repo during the run). An
    absent analysis yields an empty tuple. Anchors are sorted by ``(kind, detail)`` so order is
    deterministic and independent of the analysis tuple order.
    """
    if analysis is None:
        return ()

    anchors: list[EvidenceAnchor] = []
    for entry in analysis.entrypoints:
        name = f" ({entry.name})" if entry.name else ""
        anchors.append(
            EvidenceAnchor(
                kind="entrypoint",
                detail=entry.path,
                note=f"{entry.kind}{name}",
            )
        )
    for component in analysis.components:
        anchors.append(
            EvidenceAnchor(
                kind="component",
                detail=component.path,
                note=component.name,
            )
        )
    return tuple(sorted(anchors, key=lambda a: (a.kind, a.detail)))


def _overview_chunks(
    project: str,
    intent_label: str,
    subjects: "tuple[Subject, ...]",
    anchors: tuple[EvidenceAnchor, ...],
) -> tuple[Chunk, ...]:
    """The four overview chunks (Purpose / Use cases / Features / Design choices), in order.

    Each chunk's heading is the fixed overview section name; its points are deterministic,
    built only from the project name (``identity.site_name``), the vocabulary-derived intent
    label, the salient subjects, and the (verbatim) evidence anchors — no model, no hardcoded
    role/intent literal. The headings come from :data:`OVERVIEW_SECTION_HEADINGS`, so the
    section structure and this constructor can never silently diverge.
    """
    subject_phrases = tuple(subject.local for subject in subjects)
    subject_summary = ", ".join(subject_phrases) if subject_phrases else project

    purpose, use_cases, features, design = OVERVIEW_SECTION_HEADINGS

    purpose_chunk = Chunk(
        heading=purpose,
        points=(
            f"State what {project} is and the problem it solves.",
            f"Lead with the conclusion: why {project} exists, in one sentence.",
        ),
    )
    use_cases_chunk = Chunk(
        heading=use_cases,
        points=(
            f"Show the concrete situations where a reader reaches for {project}.",
            f"Connect each use case to {subject_summary}.",
        ),
    )
    feature_points: list[str] = [
        f"Summarise the capabilities of {project} a reader can rely on."
    ]
    if subject_phrases:
        feature_points.append(
            "Ground the capabilities in the project's salient parts: "
            + ", ".join(subject_phrases)
            + "."
        )
    features_chunk = Chunk(heading=features, points=tuple(feature_points))

    design_points: list[str] = [
        f"Explain the load-bearing design choices behind {project} and why they hold.",
    ]
    if anchors:
        design_points.append(
            "Anchor the choices in real evidence: "
            + ", ".join(
                f"{anchor.kind}: {anchor.detail}"
                + (f" — {anchor.note}" if anchor.note else "")
                for anchor in anchors
            )
            + "."
        )
    design_chunk = Chunk(heading=design, points=tuple(design_points))

    return (purpose_chunk, use_cases_chunk, features_chunk, design_chunk)


def _overview_scqa(project: str, intent_label: str, key_message: str) -> SCQAOpener:
    """The SCQA opener for the overview, built only from project name + key message.

    The ``answer`` echoes the Minto lead conclusion (``key_message``) so the body leads with
    the conclusion. The opener addresses the subject (the project), never a reader role — the
    overview is a project-wide front door, so no role literal appears in the prose.
    """
    return SCQAOpener(
        situation=f"This page is the front door to {project}.",
        complication=(
            f"A new reader cannot tell, at a glance, what {project} is for or how it fits."
        ),
        question=f"What is {project}, and why would you use it?",
        answer=key_message,
    )


def build_overview_blueprint(
    identity: "SiteIdentity",
    vocab: "Vocabulary",
    analysis: "RepoAnalysis | None",
    *,
    guidance: str = "",
) -> CompositionBlueprint:
    """Build the deterministic, overview-shaped COBESY blueprint (Req 7.1, 7.8).

    Mirrors :func:`~docuharnessx.composition.blueprint.build_blueprint` but produces the
    project-wide overview plan rather than a per-role page: its ``title`` is the project
    overview title (from ``identity.site_name``); its ``chunks`` are the four overview sections
    (:data:`OVERVIEW_SECTION_HEADINGS` — *Purpose / Use cases / Features / Design choices*) in
    order; its ``subjects`` are the project's salient subjects (derived from the optional
    ``analysis``, vocab-prefix filtered); and its ``evidence_anchors`` are derived from the
    analysis's salient entrypoints/components (empty tuple when ``analysis is None``). The
    single intent is read from the loaded ``Vocabulary`` (:func:`_overview_intent_term`); roles
    are empty (the overview targets every reader), so no role/intent literal is hardcoded.

    The ``guidance`` keyword is accepted **only for call-site uniformity** with the rewrite
    path and is **not** folded into the frozen blueprint: a ``CompositionBlueprint`` has no
    guidance field, and its chunks render as output headings, so routing the human guidance
    through the blueprint would leak it as a doc section. The guidance reaches the agent the
    same applied, never-echoed way as the rewrite path —
    ``AgenticProseRunner.run(..., guidance=guidance)`` — so this builder's output is
    **independent of the ``guidance`` value**.

    Preconditions: ``analysis`` may be ``None``; ``vocab`` may declare no intents (the overview
    intent then degrades to the empty string deterministically). Postconditions: returns a
    fully-populated, frozen :class:`CompositionBlueprint`; equal inputs yield an equal blueprint
    (and equal regardless of ``guidance``). Invariants: never consults a model; never mutates
    ``identity`` / ``vocab`` / ``analysis``.
    """
    # ``guidance`` is intentionally unused here — it never enters the frozen blueprint (it
    # reaches the agent via the writer's guidance keyword). Referenced so linters do not flag
    # it as dead, and to document that its value cannot perturb the deterministic output.
    _ = guidance

    project = identity.site_name
    intent_term = _overview_intent_term(vocab)
    intent_id = intent_term.id if intent_term is not None else ""
    intent_label = intent_term.label if intent_term is not None else ""

    subjects = _salient_subjects(analysis, vocab)
    anchors = _overview_evidence_anchors(analysis)

    key_message = (
        f"{project} is summarised below: its purpose, the situations it serves, "
        "its capabilities, and the design choices that make it trustworthy."
    )
    scqa = _overview_scqa(project, intent_label, key_message)
    chunks = _overview_chunks(project, intent_label, subjects, anchors)
    fast_path = (
        f"Read the Purpose to learn what {project} is.",
        "Scan the Use cases to find your situation.",
        "Review the Features and Design choices to judge fit, then dive into a role page.",
    )

    return CompositionBlueprint(
        segment_key="overview",
        roles=(),
        intent=intent_id,
        subjects=subjects,
        title=_overview_title(identity),
        scqa=scqa,
        key_message=key_message,
        chunks=chunks,
        fast_path=fast_path,
        andragogy=False,
        evidence_anchors=anchors,
        role_labels=(),
        intent_label=intent_label,
    )


# --------------------------------------------------------------------------- #
# Overview persistence — the reserved first-class entry (Req 7.4, 7.5, 9.4)    #
# --------------------------------------------------------------------------- #
#
# The overview is the project's front door and is intentionally ROLE-FREE (every reader,
# no role targeting — see ``build_overview_blueprint`` above), so it is NOT a role-derived
# segment and is NOT routed through ``FilesystemSegmentStore.put`` (whose vocabulary
# validation requires a non-empty ``roles`` axis). Instead it is persisted directly to the
# store's directory as the reserved ``overview.md`` file, written with the store's own
# on-disk format (:func:`~docuharnessx.ontology.serialize_segment`) so the bytes match what
# the store reads/writes. This mirrors the rewrite path's documented replace-in-place
# discipline (the ``SegmentStore`` port has no ``update`` method): a first ``draft_overview``
# writes the file, a later ``refine_overview`` re-serialises the SAME ``overview.md`` in
# place. Because the file lives in the store directory it is read back lazily on each call,
# so :func:`load_overview` always reflects the latest accepted overview. ``reassemble_site``
# (task 3.4) adds this reserved entry to the assembled site's accepted set as the
# human-friendly front door, distinct from the per-role landing pages.


def overview_path(store_dir: str | Path) -> Path:
    """The reserved ``<store_dir>/overview.md`` path for the persisted overview entry.

    A single, deterministic location derived from the store directory (``<out>/segments``),
    so a draft writes and a refine re-serialises the exact same file, and ``get_overview``
    reads it back. Pure: performs no I/O.
    """
    return Path(store_dir) / f"{OVERVIEW_SEGMENT_ID}.md"


def wire_overview_segment(
    blueprint: CompositionBlueprint, prose: ProseResult
) -> Segment:
    """Wire the gate-passing overview ``prose`` into the reserved ``overview`` :class:`Segment`.

    Mirrors :func:`~docuharnessx.composition.wiring.wire_segment` for the non-body fields, but
    pins the **reserved** :data:`OVERVIEW_SEGMENT_ID` rather than a hash-derived id (the
    overview is a fixed front-door entry, not a role cell). ``body``/``summary`` come **only**
    from ``prose`` (the gated agentic output; the handler never free-writes); ``title`` and
    ``subjects`` come from the overview blueprint; ``roles`` are empty (the overview targets
    every reader — no role/intent literal is hardcoded, and the intent is the
    vocabulary-derived overview intent the blueprint already carries). Pure: never mutates its
    inputs (``subjects`` is copied into a fresh list).
    """
    return Segment(
        id=OVERVIEW_SEGMENT_ID,
        title=blueprint.title,
        roles=[],  # the overview targets every reader — no role targeting
        subjects=list(blueprint.subjects),  # fresh list of typed Subject values
        intent=blueprint.intent,
        summary=prose.summary,  # prose-only (the gated agentic output)
        related=[],
        body=prose.body,  # prose-only (the gated agentic output)
        schema_version=SCHEMA_VERSION,
    )


def persist_overview(store_dir: str | Path, segment: Segment) -> None:
    """Persist the reserved overview ``segment`` to ``<store_dir>/overview.md`` in place.

    Serialises ``segment`` with the store's own on-disk format
    (:func:`~docuharnessx.ontology.serialize_segment`) and writes it to the reserved
    :func:`overview_path`, creating the store directory if absent and **overwriting in
    place** on a refine (replace-in-place; the store has no ``update`` method). Only a
    gate-passing overview ever reaches this function (the handler gates before persisting),
    so the store never holds an ungrounded overview.
    """
    path = overview_path(store_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(serialize_segment(segment), encoding="utf-8")


def load_overview(store_dir: str | Path, vocab: "Vocabulary") -> Segment | None:
    """Load the persisted reserved overview :class:`Segment`, or ``None`` when none exists.

    Reads ``<store_dir>/overview.md`` lazily (so it always reflects the latest accepted
    overview) and parses it through the store's serializer
    (:func:`~docuharnessx.ontology.parse_segment` + :func:`~docuharnessx.ontology.to_segment`)
    with the bound ``vocab``, exactly as the store reads any on-disk segment. Returns ``None``
    when no overview has been drafted yet (the file is absent). Consults no model.
    """
    path = overview_path(store_dir)
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8")
    return to_segment(parse_segment(text), vocab)
