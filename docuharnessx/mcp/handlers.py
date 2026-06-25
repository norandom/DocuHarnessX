"""The MCP tool handlers over a :class:`RefineSession` (mcp-refine task 3.1+).

Each handler is a plain Python function taking the bound
:class:`~docuharnessx.mcp.session.RefineSession` (the per-target state) and returning a
**structured result** — a JSON-serialisable mapping the server factory (task 4.1) wraps as
MCP content. A handler **never raises out of itself** for an expected domain condition (a
missing segment id, a no-model session); it returns a structured *result* (a verdict, or an
error envelope) instead, so the dispatch loop stays alive (Req 3.4, 4.3, 6.3).

Task 3.1 owns the three **read-only, model-free** tools — none consults a model, none touches
the network, all read only from the session's :class:`~docuharnessx.ontology.FilesystemSegmentStore`
(the on-disk **single source of truth** the batch run produced; Req 4.5):

* :func:`list_segments` — every stored segment in the store's deterministic **by-id** order,
  each carrying at least ``id`` / ``title`` / ``roles`` / ``intent`` / ``subjects`` (Req 4.1,
  4.4);
* :func:`get_segment` — the full stored segment incl. ``summary`` + ``body``; a missing id
  yields a structured tool error naming the id rather than raising (Req 4.2, 4.3, 4.4);
* :func:`validate_segment` — the deterministic structure gate
  (:func:`~docuharnessx.composition.validate_agent_body`) over the body, returning the verdict
  (``accepted`` / ``mermaid_blocks`` / ``cited_files`` / ``reason``) at the **same**
  ``session.min_citations`` threshold the rewrite path enforces (Req 6.4), so a body that
  validates here is one the rewrite path would accept; a missing id yields the same structured
  error (Req 6.1-6.4).

The later model-touching / persisting / assembling handlers (``rewrite_segment``,
``draft_overview`` / ``refine_overview`` / ``get_overview``, ``reassemble_site``) are added in
tasks 3.2-3.4 over the same session, reusing the bounded agentic writer and the structure gate
as their only model surface and gate (no second generation engine; Req 1.4, 9.1).
"""

from __future__ import annotations

import asyncio
import os
from typing import TYPE_CHECKING, Any

from docuharnessx.composition import (
    AgenticProseRunner,
    build_blueprint,
    render_fallback_body,
    validate_agent_body,
    wire_segment,
)
from docuharnessx.mcp.overview import (
    OVERVIEW_SEGMENT_ID,
    build_overview_blueprint,
    load_overview,
    persist_overview,
    wire_overview_segment,
)
from docuharnessx.assembler import assemble_site
from docuharnessx.mcp.planned import planned_from_segment
from docuharnessx.ontology import (
    OntologyError,
    Segment,
    Subject,
    normalize_prefix,
    serialize_segment,
)
from docuharnessx.ontology import validate_segment as _validate_segment_against_vocab
from docuharnessx.review.model import (
    REVIEW_REPORT_SCHEMA_VERSION,
    ReviewAggregate,
    ReviewReport,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from docuharnessx.composition.model import CompositionBlueprint
    from docuharnessx.mcp.session import RefineSession

__all__ = [
    "list_segments",
    "get_segment",
    "validate_segment",
    "rewrite_segment",
    "draft_overview",
    "refine_overview",
    "get_overview",
    "reassemble_site",
]


# --------------------------------------------------------------------------- #
# Structured error envelope                                                   #
# --------------------------------------------------------------------------- #
#
# A handler signals an expected domain failure (a missing segment id) by RETURNING this
# envelope rather than raising, so the dispatch loop never crashes (Req 3.4, 4.3, 6.3). The
# server factory (task 4.1) maps an ``error: True`` result to an MCP structured tool error;
# the typed schemas/envelopes it owns are a superset of this minimal shape.


def _missing_segment_error(segment_id: str) -> dict[str, Any]:
    """A structured "segment not found" tool-error result naming the missing id.

    Returned (never raised) by :func:`get_segment` / :func:`validate_segment` when ``id`` is
    not present in the store, so the client learns exactly which id was missing without the
    dispatch loop crashing (Req 4.3, 6.3).
    """
    return {
        "error": True,
        "code": "segment_not_found",
        "segment_id": segment_id,
        "message": f"no segment with id {segment_id!r} in the store",
    }


def _no_model_result() -> dict[str, Any]:
    """An explicit "no model configured" result for a model-touching tool (Req 5.6).

    Returned (never raised, and **not** an ``error`` tool envelope — a no-model session is a
    valid state the server starts in, not a protocol error) by :func:`rewrite_segment` when
    ``session.model()`` is ``None``, so the human learns how to bind a model rather than the
    server silently producing or persisting content. ``accepted`` is ``False`` so a caller can
    treat it uniformly with a rejected run.
    """
    return {
        "accepted": False,
        "no_model": True,
        "code": "no_model",
        "message": (
            "no model configured for this refine session; bind one via the model "
            "config/env (the same resolution path as `dhx run`) and reconnect, or use the "
            "model-free tools (list_segments / get_segment / validate_segment / "
            "reassemble_site)"
        ),
    }


# --------------------------------------------------------------------------- #
# Internal helpers (pure; read only from the bound store)                      #
# --------------------------------------------------------------------------- #


def _subject_strings(segment: Segment) -> list[str]:
    """The segment's subjects as canonical ``"prefix:local"`` strings (JSON-friendly).

    A :class:`~docuharnessx.ontology.model.Subject` is a typed value object; the MCP surface
    speaks JSON, so the handlers emit each subject's canonical string. The subject namespace
    stays project-configurable (it comes from the stored segment, never a hardcoded literal).
    """
    return [subject.canonical() for subject in segment.subjects]


def _axes(segment: Segment) -> dict[str, Any]:
    """The segment's targeting axes — id/title/roles/intent/subjects — as a JSON mapping.

    The shared shape both :func:`list_segments` (per entry) and :func:`get_segment` (the
    summary fields) return, so the two read tools agree on the axis representation (Req 4.1,
    4.2). ``roles`` is copied into a fresh list (the stored value is not mutated).
    """
    return {
        "id": segment.id,
        "title": segment.title,
        "roles": list(segment.roles),
        "intent": segment.intent,
        "subjects": _subject_strings(segment),
    }


def _find_segment(session: "RefineSession", segment_id: str) -> Segment | None:
    """Return the stored segment for ``segment_id``, or ``None`` when absent.

    Reads only the session's store (the on-disk source of truth, read lazily on each call),
    consults no model, and never raises for an absent id — the caller turns ``None`` into the
    structured :func:`_missing_segment_error` envelope (Req 4.5, 4.3, 6.3).
    """
    for segment in session.store.list_segments():
        if segment.id == segment_id:
            return segment
    return None


# --------------------------------------------------------------------------- #
# Read-only, model-free tools                                                 #
# --------------------------------------------------------------------------- #


def workspace_summary(session: "RefineSession") -> dict[str, Any]:
    """A compact, model-free description of an open workspace (returned by ``open_workspace``).

    Confirms to the agent which workspace is now active — the resolved target repo and output
    dir (set by the agent, not hardcoded at launch), the stored-segment count, the per-target
    site name (never DocuHarnessX), and whether a model is configured (so the agent knows the
    model-touching tools are usable). Reads only the session + store; consults no model.
    """
    return {
        "opened": True,
        "repo": session.target_repo,
        "out": session.out_dir,
        "segment_count": len(session.store.list_segments()),
        "site_name": session.identity.site_name,
        "model_available": session.model() is not None,
    }


def list_segments(session: "RefineSession") -> list[dict[str, Any]]:
    """Enumerate the stored segments in by-id order with their targeting axes (Req 4.1).

    Returns one mapping per stored segment — ``id`` / ``title`` / ``roles`` / ``intent`` /
    ``subjects`` — in the store's deterministic **by-id** order (the store is the single
    authority for ordering; this handler does not re-sort). The full body is **not** included
    (that is :func:`get_segment`'s job), keeping the listing compact.

    Reads only ``session.store`` — the on-disk source of truth — and consults **no model**, so
    it is fully usable credential-free (Req 4.4, 4.5).
    """
    return [_axes(segment) for segment in session.store.list_segments()]


def get_segment(session: "RefineSession", segment_id: str) -> dict[str, Any]:
    """Return the full stored segment for ``segment_id`` (axes + summary + body) (Req 4.2).

    On a present id, returns the segment's ``id`` / ``title`` / ``roles`` / ``intent`` /
    ``subjects`` plus its ``summary`` and full Markdown ``body``. On an id **not** present in
    the store, returns the structured :func:`_missing_segment_error` envelope naming the id —
    it does **not** raise out of the handler (Req 4.3). Consults no model (Req 4.4).
    """
    segment = _find_segment(session, segment_id)
    if segment is None:
        return _missing_segment_error(segment_id)
    result = _axes(segment)
    result["summary"] = segment.summary
    result["body"] = segment.body
    return result


def validate_segment(session: "RefineSession", segment_id: str) -> dict[str, Any]:
    """Run the deterministic structure gate over a stored segment's body (Req 6.1).

    On a present id, runs :func:`~docuharnessx.composition.validate_agent_body` over the
    segment's body at the **same** ``session.min_citations`` threshold the rewrite path
    enforces (Req 6.4), and returns the verdict: ``accepted`` (bool), ``mermaid_blocks``
    (int), ``cited_files`` (distinct files cited as ``file:line``), and the human-readable
    ``reason``. A rejection is a *verdict*, not a tool error (it carries no ``error`` flag).

    On an id **not** present in the store, returns the structured
    :func:`_missing_segment_error` envelope naming the id rather than raising (Req 6.3).
    Consults no model and performs no network access (Req 6.2).
    """
    segment = _find_segment(session, segment_id)
    if segment is None:
        return _missing_segment_error(segment_id)
    verdict = validate_agent_body(segment.body, min_citations=session.min_citations)
    return {
        "id": segment.id,
        "accepted": verdict.accepted,
        "mermaid_blocks": verdict.mermaid_blocks,
        "cited_files": verdict.cited_files,
        "reason": verdict.reason,
    }


# --------------------------------------------------------------------------- #
# Replace-in-place persistence (the rewrite path's load-bearing helper)        #
# --------------------------------------------------------------------------- #


def _replace_segment_in_place(session: "RefineSession", segment: Segment) -> None:
    """Overwrite the stored ``<id>.md`` for ``segment`` with its re-serialised content.

    This is load-bearing for an accepted rewrite: the :class:`SegmentStore` Protocol has
    **no ``update``** method, and :meth:`FilesystemSegmentStore.put` raises
    :class:`~docuharnessx.ontology.IdConflictError` on an existing id — so a rewrite cannot
    re-``put`` the same id. Instead this helper mirrors ``put``'s **validate-then-write**
    order against the bound vocabulary and re-serialises through
    :func:`~docuharnessx.ontology.serialize_segment` (the store's own on-disk format) directly
    to the existing ``<out>/segments/<id>.md`` path, overwriting in place. Because
    ``FilesystemSegmentStore`` reads the directory **lazily on every call**, the next
    ``list_segments`` / ``get_segment`` reflects the new body immediately and the id stays
    stable (Req 5.4, 5.8).

    Validation runs first: an invalid wired segment raises the first aggregated
    :class:`~docuharnessx.ontology.OntologyError` and **nothing is written** (so a malformed
    rewrite never corrupts the store), exactly as ``put`` guarantees.
    """
    result = _validate_segment_against_vocab(segment, session.vocab)
    if not result.is_valid:
        first = result.errors[0]
        if isinstance(first, OntologyError):
            raise first
        raise OntologyError(str(first))  # pragma: no cover - defensive

    # Re-serialise to the existing <id>.md path under the store's segments directory. The id
    # round-tripped from the stored segment (planned_from_segment) is filesystem-safe by
    # construction (it is the same id the store already persisted), so the path is the one the
    # batch run wrote and the store reads lazily on the next call.
    path = session.store._path_for(segment.id)  # noqa: SLF001 — the store has no public path API
    path.write_text(serialize_segment(segment), encoding="utf-8")


# --------------------------------------------------------------------------- #
# Re-grounded segment rewrite (capability A core; anti-slop)                  #
# --------------------------------------------------------------------------- #


async def rewrite_segment(
    session: "RefineSession", segment_id: str, guidance: str = ""
) -> dict[str, Any]:
    """Rewrite one stored segment — re-grounded, gated, replace-in-place (Req 5.1-5.9).

    Never free-writes: it reconstructs the stored segment's deterministic blueprint and
    re-runs the bounded agentic writer over the **read-only** target repo, delivering the
    human ``guidance`` through the writer's additive ``guidance`` keyword (an applied,
    never-echoed author instruction near the mission — **never** the frozen blueprint), and
    persists the new body **only** when the deterministic structure gate accepts it:

    #. a missing ``segment_id`` -> the structured :func:`_missing_segment_error` (Req 4.3 shape);
    #. no model bound (``session.model() is None``) -> the explicit :func:`_no_model_result`
       without producing or persisting content (Req 5.6);
    #. otherwise ``planned_from_segment`` -> ``build_blueprint`` (the same-id blueprint),
       then ``AgenticProseRunner().run(blueprint, repo_path=session.target_repo,
       model=session.model(), guidance=guidance, min_citations=session.min_citations)`` —
       **offloaded off the async loop via :func:`asyncio.to_thread`** so the runner's private
       event loop never nests in the dispatch loop (design "Server"); the run is bounded by
       the reused writer Control budgets and reads the repo read-only (Req 5.7, 9.5, 9.6);
    #. on an accepted ``ProseResult`` -> :func:`~docuharnessx.composition.wire_segment` carries
       the new ``body``/``summary`` (every non-body field fixed; Req 5.8) and
       :func:`_replace_segment_in_place` overwrites the existing ``<id>.md`` (Req 5.4); the
       result reports ``accepted=True`` with the gate verdict;
    #. on ``None`` (raise / timeout / empty / over-budget / gate-reject) -> the gate verdict
       over the deterministic :func:`~docuharnessx.composition.render_fallback_body` plus that
       fallback body are surfaced and **nothing is persisted** (the stored segment is left
       unchanged; Req 5.5, 9.3) — never a silent pass.

    Returns a JSON-serialisable structured result; it never raises out of itself for an
    expected domain condition (the runner absorbs every agentic failure to ``None``).
    """
    segment = _find_segment(session, segment_id)
    if segment is None:
        return _missing_segment_error(segment_id)

    # No model: degrade explicitly without producing content (Req 5.6).
    model = session.model()
    if model is None:
        return _no_model_result()

    # Reconstruct the SAME-id deterministic blueprint (the guidance does NOT flow through it).
    planned = planned_from_segment(segment)
    blueprint = build_blueprint(planned, session.analysis, session.vocab)

    # Re-ground through the bounded agentic writer over the read-only target repo. The runner
    # is synchronous and drives its own private event loop, so offload it off the dispatch
    # loop with asyncio.to_thread (design "Server"). The runner absorbs every failure to
    # (None, stats); it never raises.
    runner = AgenticProseRunner()
    prose, stats = await asyncio.to_thread(
        runner.run,
        blueprint,
        repo_path=session.target_repo,
        model=model,
        guidance=guidance,
        min_citations=session.min_citations,
    )

    # Reject / failure path: surface the verdict + the deterministic fallback, persist NOTHING.
    if prose is None:
        fallback_body = render_fallback_body(blueprint)
        verdict = validate_agent_body(fallback_body, min_citations=session.min_citations)
        return {
            "id": segment.id,
            "accepted": False,
            "exit_reason": stats.exit_reason,
            "mermaid_blocks": verdict.mermaid_blocks,
            "cited_files": verdict.cited_files,
            "reason": verdict.reason,
            "fallback_body": fallback_body,
            "message": (
                "the agentic rewrite did not produce a gate-passing body "
                f"(exit_reason={stats.exit_reason!r}); nothing was persisted and the stored "
                "segment is unchanged — review the deterministic fallback below"
            ),
        }

    # Accept path: wire the new body/summary (non-body fields fixed) and replace in place.
    rewritten = wire_segment(planned, blueprint, prose)
    _replace_segment_in_place(session, rewritten)
    accepted_verdict = validate_agent_body(
        rewritten.body, min_citations=session.min_citations
    )
    return {
        "id": rewritten.id,
        "accepted": True,
        "exit_reason": stats.exit_reason,
        "steps": stats.steps,
        "cost_usd": stats.cost_usd,
        "mermaid_blocks": accepted_verdict.mermaid_blocks,
        "cited_files": accepted_verdict.cited_files,
        "reason": accepted_verdict.reason,
        "summary": rewritten.summary,
        "message": "the rewritten body passed the structure gate and replaced the segment in place",
    }


# --------------------------------------------------------------------------- #
# Grounded narrative overview (capability B; anti-slop)                       #
# --------------------------------------------------------------------------- #
#
# The overview is the project's human-friendly FRONT DOOR (Purpose / Use cases / Features /
# Design choices), grounded in the real repository through the SAME bounded agentic writer +
# deterministic structure gate the rewrite path uses — no second generation engine (Req 7.8,
# 1.4). It is persisted as the RESERVED first-class entry ``overview`` (id
# :data:`~docuharnessx.mcp.overview.OVERVIEW_SEGMENT_ID`) under ``<out>/segments``, distinct
# from the per-role segment pages: a first ``draft_overview`` writes ``overview.md``, a later
# ``refine_overview`` re-serialises it in place. The reserved entry is intentionally role-free
# (it targets every reader), so the persistence helpers in :mod:`docuharnessx.mcp.overview`
# write it directly with the store's on-disk format rather than through the role-validating
# ``FilesystemSegmentStore.put`` (mirroring the rewrite path's replace-in-place discipline).


def _overview_store_dir(session: "RefineSession") -> str:
    """The session's ``<out>/segments`` directory — where the reserved overview is persisted.

    The overview is persisted into the SAME on-disk directory the
    :class:`~docuharnessx.ontology.FilesystemSegmentStore` reads (``<out>/segments``), so it
    is read back lazily on each :func:`get_overview` call and surfaced by the reassembled site
    (task 3.4). Derived from ``session.out_dir`` to match how ``resolve_session`` provisions
    the store.
    """
    return os.path.join(session.out_dir, "segments")


async def _run_overview(
    session: "RefineSession", guidance: str
) -> dict[str, Any]:
    """Build the overview blueprint, run the bounded writer, gate, and persist on accept.

    The single anti-slop core shared by :func:`draft_overview` (``guidance=""``) and
    :func:`refine_overview` (the human ``guidance``): it builds the overview-shaped blueprint
    (:func:`~docuharnessx.mcp.overview.build_overview_blueprint`) and runs the **reused**
    :class:`~docuharnessx.composition.AgenticProseRunner` over the **read-only** target repo,
    delivering the human ``guidance`` through the writer's additive ``guidance`` keyword (an
    applied, never-echoed author instruction near the mission — **never** the frozen blueprint;
    Req 7.2, 9.7). The synchronous runner is offloaded off the async dispatch loop via
    :func:`asyncio.to_thread` (design "Server"), is bounded by the reused Control budgets, and
    reads the repo read-only (Req 7.8, 9.5, 9.6). On a gate-accepted body it persists the
    reserved overview entry in place and returns the accepted verdict; on ``None`` (raise /
    timeout / empty / over-budget / gate-reject) it surfaces the gate verdict over the
    deterministic fallback and persists **nothing**, leaving any prior overview unchanged
    (Req 7.6, 9.3). A no-model session returns the explicit :func:`_no_model_result` (Req 7.7).
    """
    model = session.model()
    if model is None:
        return _no_model_result()

    blueprint = build_overview_blueprint(
        session.identity, session.vocab, session.analysis, guidance=guidance
    )

    runner = AgenticProseRunner()
    prose, stats = await asyncio.to_thread(
        runner.run,
        blueprint,
        repo_path=session.target_repo,
        model=model,
        guidance=guidance,
        min_citations=session.min_citations,
    )

    # Reject / failure: surface the verdict + the deterministic fallback, persist NOTHING (so
    # any prior accepted overview is left unchanged).
    if prose is None:
        fallback_body = render_fallback_body(blueprint)
        verdict = validate_agent_body(fallback_body, min_citations=session.min_citations)
        return {
            "id": OVERVIEW_SEGMENT_ID,
            "accepted": False,
            "exit_reason": stats.exit_reason,
            "mermaid_blocks": verdict.mermaid_blocks,
            "cited_files": verdict.cited_files,
            "reason": verdict.reason,
            "fallback_body": fallback_body,
            "message": (
                "the agentic overview run did not produce a gate-passing body "
                f"(exit_reason={stats.exit_reason!r}); nothing was persisted and any prior "
                "overview is unchanged — review the deterministic fallback below"
            ),
        }

    # Accept: wire the reserved overview entry (body/summary from the gated prose) and persist
    # it in place under <out>/segments/overview.md.
    overview_segment = wire_overview_segment(blueprint, prose)
    persist_overview(_overview_store_dir(session), overview_segment)
    accepted_verdict = validate_agent_body(
        overview_segment.body, min_citations=session.min_citations
    )
    return {
        "id": OVERVIEW_SEGMENT_ID,
        "accepted": True,
        "exit_reason": stats.exit_reason,
        "steps": stats.steps,
        "cost_usd": stats.cost_usd,
        "mermaid_blocks": accepted_verdict.mermaid_blocks,
        "cited_files": accepted_verdict.cited_files,
        "reason": accepted_verdict.reason,
        "summary": overview_segment.summary,
        "message": (
            "the overview body passed the structure gate and was persisted as the reserved "
            "front-door entry"
        ),
    }


async def draft_overview(session: "RefineSession") -> dict[str, Any]:
    """Draft the grounded narrative overview from scratch (``guidance=""``) (Req 7.1).

    Runs the bounded agentic writer over the read-only target repo with the overview-shaped
    blueprint (Purpose / Use cases / Features / Design choices) and **no** human guidance, gates
    the body, and on accept persists it as the reserved first-class overview entry; on reject
    surfaces the gate verdict + the deterministic fallback without persisting; with no model
    bound returns the explicit :func:`_no_model_result` (Req 7.1, 7.3, 7.4, 7.6, 7.7). Never
    free-writes — the body comes only from the reused writer + gate (Req 9.1, 9.2).
    """
    return await _run_overview(session, guidance="")


async def refine_overview(
    session: "RefineSession", guidance: str = ""
) -> dict[str, Any]:
    """Refine the overview to human ``guidance``, re-grounded and gated (Req 7.2).

    Re-runs the bounded agentic writer over the overview-shaped blueprint, delivering the human
    ``guidance`` through the writer's additive ``guidance`` keyword (applied to WHAT the
    overview covers and emphasises, **never** echoed as a heading/section, and **never** routed
    through the frozen blueprint; Req 7.2, 9.7). Gate-before-persist and surface-the-verdict are
    identical to :func:`draft_overview`: an accepted body replaces the reserved overview entry
    in place, a rejected/failed run persists nothing and leaves any prior overview unchanged
    (Req 7.6), and a no-model session returns the explicit :func:`_no_model_result` (Req 7.7).
    """
    return await _run_overview(session, guidance=guidance)


def get_overview(session: "RefineSession") -> dict[str, Any]:
    """Return the persisted overview body, or an explicit "none yet" result (Req 7.5).

    Reads the reserved ``<out>/segments/overview.md`` entry lazily (so it reflects the latest
    accepted overview) and returns its ``id`` / ``title`` / ``summary`` / ``body`` with
    ``exists=True``; when no overview has been drafted yet it returns an explicit
    ``exists=False`` result naming that none exists, rather than an error envelope. Consults
    **no model** and performs no network access (model-free surface; Req 7.5).
    """
    segment = load_overview(_overview_store_dir(session), session.vocab)
    if segment is None:
        return {
            "exists": False,
            "id": OVERVIEW_SEGMENT_ID,
            "message": (
                "no overview drafted yet; call draft_overview to produce the grounded "
                "front-door overview (a model must be configured)"
            ),
        }
    return {
        "exists": True,
        "id": segment.id,
        "title": segment.title,
        "summary": segment.summary,
        "body": segment.body,
    }


# --------------------------------------------------------------------------- #
# Reassemble the themed Material site from the live store (model-free)         #
# --------------------------------------------------------------------------- #
#
# ``reassemble_site`` is the ONLY assembling handler and is strictly model-free (Req 8.4): it
# builds a ``ReviewReport`` whose accepted set is the CURRENT store segments (the on-disk single
# source of truth) plus the persisted reserved overview entry when present, and calls the REUSED
# deterministic ``assemble_site`` over the session's vocab / optional analysis / out dir /
# per-target identity. It writes ONLY under ``<out>/site`` and reuses the per-target identity,
# so it never derives DocuHarnessX's own identity and never writes into the target repo (Req
# 8.5). It consults no model and never free-writes — assembly is a pure transform of bodies the
# rewrite/overview paths already gated and persisted (Req 9.1, 9.4).


def _project_scoped_subject(session: "RefineSession") -> Subject | None:
    """A single project-wide nav subject ``<first-prefix>:<site_name>`` (or ``None``).

    Built from the vocabulary's **first declared** subject prefix and the per-target
    ``identity.site_name``, so the role-free / analysis-less overview can still carry a
    vocab-valid ``subjects`` axis and surface as the front door (see
    :func:`_overview_accepted_entry`). This is a project-scoped *tag*, not a code-level claim —
    the overview targets the whole project, so subjecting it with the project's own name under a
    declared prefix invents no repository fact. Returns ``None`` when the vocabulary declares no
    subject prefix (no valid axis can be built) or the resulting subject is malformed.
    """
    prefixes = session.vocab.subject_prefixes
    if not prefixes:
        return None
    prefix = normalize_prefix(prefixes[0])
    site_name = getattr(session.identity, "site_name", "") or "project"
    try:
        return Subject.parse(f"{prefix}:{site_name}", frozenset({prefix}))
    except OntologyError:  # pragma: no cover - defensive; a normalized prefix + name parses
        return None


def _overview_accepted_entry(
    session: "RefineSession", store_segments: tuple[Segment, ...]
) -> Segment | None:
    """Adapt the persisted reserved overview into an ``assemble_site``-acceptable entry.

    The reserved overview entry is persisted **role-free** (it is the project's front door for
    every reader, so :func:`~docuharnessx.mcp.overview.wire_overview_segment` pins ``roles=[]``)
    and may carry **no subjects** (when no :class:`RepoAnalysis` is available). But
    :func:`~docuharnessx.assembler.assemble_site` builds an in-memory accepted store via
    ``put``, which validates against the vocabulary and rejects an empty ``roles`` or
    ``subjects`` axis (both are required fields). So to surface the overview through the
    **frozen, reused** ``assemble_site`` — without editing the assembler — this builds a
    reassembly-only copy of the overview that is valid for ``put`` while inventing **no**
    repository fact:

    * ``roles`` becomes **every vocabulary role** so the front-door page is reachable from each
      role's nav section (vocab-driven; no hardcoded role literal). It falls back to the
      overview's own roles when the vocabulary declares none.
    * ``subjects`` reuses the overview's own subjects when present; else the **union of
      subjects already present on the accepted store segments** (real repository facts the
      rewrite/overview paths already grounded and persisted, vocab-valid by construction); and
      as a last resort, when neither is available (an overview drafted with no analysis over an
      otherwise-empty store), a single **project-scoped** subject ``<first-prefix>:<site_name>``
      built from the vocabulary's first declared subject prefix and the per-target
      ``identity.site_name``. The last resort is a project-wide *nav tag*, not a fabricated
      repository claim — the overview targets the whole project, so subjecting it with the
      project's own name under a declared prefix is truthful and keeps it surfacing as the front
      door (Req 8.1, 8.3) without inventing a code-level fact.

    Returns the adapted :class:`Segment` (the persisted ``overview.md`` itself is left
    untouched), or ``None`` when no overview is persisted, or when the vocabulary declares no
    role / no subject prefix at all — in which case no valid axis can be supplied and the
    overview is simply not surfaced this reassembly rather than corrupting the accepted set.
    """
    overview = load_overview(_overview_store_dir(session), session.vocab)
    if overview is None:
        return None

    # Roles: every vocabulary role (vocab-driven front door), else the overview's own roles.
    roles = [role.id for role in session.vocab.roles] or list(overview.roles)
    if not roles:
        return None  # the vocabulary declares no role — no valid axis to attach

    # Subjects: the overview's own, else the union of subjects already on the store segments
    # (real, vocab-valid repository facts), in a deterministic by-canonical order; else a single
    # project-scoped nav tag from the vocabulary's first subject prefix + the per-target name.
    subjects = list(overview.subjects)
    if not subjects:
        seen: dict[str, Any] = {}
        for seg in store_segments:
            for subject in seg.subjects:
                seen.setdefault(subject.canonical(), subject)
        subjects = [seen[key] for key in sorted(seen)]
    if not subjects:
        project_subject = _project_scoped_subject(session)
        if project_subject is None:
            return None  # the vocabulary declares no subject prefix — no valid axis to attach
        subjects = [project_subject]

    return Segment(
        id=overview.id,
        title=overview.title,
        roles=roles,
        subjects=subjects,
        intent=overview.intent,
        summary=overview.summary,
        related=list(overview.related),
        body=overview.body,  # the gated, persisted overview body — never free-written here
        schema_version=overview.schema_version,
    )


def reassemble_site(session: "RefineSession") -> dict[str, Any]:
    """Rebuild the themed Material site from the live store + overview, model-free (Req 8.1-8.6).

    Builds a :class:`~docuharnessx.review.model.ReviewReport` whose ``accepted`` set is the
    current ``session.store.list_segments()`` (the on-disk single source of truth) plus the
    persisted reserved overview entry when one exists (adapted via
    :func:`_overview_accepted_entry` so the **frozen** ``assemble_site`` can surface it), with a
    well-formed :class:`~docuharnessx.review.model.ReviewAggregate` (``judged == accepted == N``,
    ``rejected == unavailable == 0``, empty ``criterion_tally`` — this is the human-approved
    accepted set, not a fresh judge run). It then calls the **reused**
    :func:`~docuharnessx.assembler.assemble_site` with the session's loaded ``Vocabulary``,
    optional ``RepoAnalysis``, output dir, and per-target ``SiteIdentity``, and returns the
    produced ``site_dir`` plus the per-segment ``page_count`` and per-role ``role_page_count``.

    Consults **no model** (assembly is deterministic; Req 8.4), writes only under
    ``<out>/site`` and reuses the per-target identity (never DocuHarnessX's; Req 8.5), and on an
    empty store with no overview produces a well-formed empty site reporting a zero page count
    (Req 8.6). Returns a JSON-serialisable structured result.
    """
    # The FilesystemSegmentStore reads EVERY ``<out>/segments/*.md`` lazily, including the
    # reserved ``overview.md`` (it lives in the same directory). The raw overview entry is
    # role-free (and possibly subject-free) and would fail ``assemble_site``'s validate-on-put,
    # so the reserved id is excluded from the raw store list here and re-added once — adapted —
    # below, so the overview is surfaced exactly once as a valid front-door page.
    store_segments = tuple(
        seg
        for seg in session.store.list_segments()
        if seg.id != OVERVIEW_SEGMENT_ID
    )

    accepted: list[Segment] = list(store_segments)
    overview_entry = _overview_accepted_entry(session, store_segments)
    if overview_entry is not None:
        accepted.append(overview_entry)

    accepted_count = len(accepted)
    report = ReviewReport(
        schema_version=REVIEW_REPORT_SCHEMA_VERSION,
        entries=(),
        accepted=tuple(accepted),
        aggregate=ReviewAggregate(
            judged=accepted_count,
            accepted=accepted_count,
            rejected=0,
            unavailable=0,
            criterion_tally=(),
        ),
    )

    site = assemble_site(
        report,
        session.vocab,
        session.analysis,
        session.out_dir,
        session.identity,
    )

    return {
        "site_dir": site.site_dir,
        "page_count": site.page_count,
        "role_page_count": site.role_page_count,
        "overview_included": overview_entry is not None,
        "message": (
            f"reassembled the themed site at {site.site_dir!r} with {site.page_count} "
            f"page(s) across {site.role_page_count} role landing page(s)"
        ),
    }
