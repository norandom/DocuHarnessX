"""Unit tests for ``rewrite_segment`` — re-grounded, gated, replace-in-place (mcp task 3.2).

``rewrite_segment(session, id, guidance)`` is the first **model-touching** refine handler.
It NEVER free-writes: it reconstructs the stored segment's deterministic blueprint
(:func:`~docuharnessx.mcp.planned.planned_from_segment` +
:func:`~docuharnessx.composition.blueprint.build_blueprint`), re-runs the bounded agentic
writer (:class:`~docuharnessx.composition.AgenticProseRunner`) over the **read-only** target
repo — delivering the human ``guidance`` through the writer's additive ``guidance`` keyword
(never the frozen blueprint) — and gates the body with the deterministic structure gate. Only
on accept does it wire the new ``body``/``summary`` (every non-body field fixed) and
**replace the existing ``<id>.md`` in place** (the store has no ``update`` and ``put`` raises
``IdConflictError`` on an existing id, so it re-serialises through ``serialize_segment`` after
validating against the vocab, mirroring ``put``'s validate-then-write order). On a
``None``/reject/empty run it surfaces the gate verdict + the deterministic fallback and
persists NOTHING (anti-slop, never silent-pass); a no-model session returns an explicit
"no model configured" result without producing content.

These tests drive the REAL :class:`~docuharnessx.composition.AgenticProseRunner` run loop with
the offline :class:`tests._fakes.ScriptedAgentProvider` over a throwaway copy of the crafted
fixture repo (``tests/fixtures/agentic_repo``) — so the whole path is exercised with NO
network and NO credentials (Req 10.1, 10.2). The store is a real
:class:`~docuharnessx.ontology.FilesystemSegmentStore` over a tmp directory (the on-disk
source of truth a batch run produces).
"""

from __future__ import annotations

import asyncio
import hashlib
import shutil
from pathlib import Path

import pytest

from docuharnessx.composition import MIN_CITED_FILES, validate_agent_body
from docuharnessx.composition.blueprint import build_blueprint
from docuharnessx.composition.model import ProseResult
from docuharnessx.composition.wiring import segment_id, wire_segment
from docuharnessx.mcp import handlers
from docuharnessx.mcp.planned import planned_from_segment
from docuharnessx.mcp.session import RefineSession
from docuharnessx.ontology import (
    AxisTerm,
    FilesystemSegmentStore,
    Segment,
    Subject,
    Vocabulary,
)
from docuharnessx.planning.model import PlannedSegment
from tests._fakes import SCRIPTED_AGENT_BODY, ScriptedAgentProvider

_FIXTURE_REPO = Path(__file__).parent / "fixtures" / "agentic_repo"
_PREFIXES = frozenset({"component", "tech", "artifact", "topic"})


def _subject(raw: str) -> Subject:
    return Subject.parse(raw, _PREFIXES)


def _vocab() -> Vocabulary:
    return Vocabulary(
        roles=(
            AxisTerm("platform-dev", "Platform Developer", "Builds on the platform."),
            AxisTerm("adopter", "Adopter", "Adopts the project."),
        ),
        intents=(
            AxisTerm("understand", "Understand", "Build a mental model."),
            AxisTerm("extend", "Extend", "Add capabilities."),
        ),
        subject_prefixes=("component:", "tech:", "artifact:", "topic:"),
    )


def _planner_segment_key(
    roles: tuple[str, ...], intent: str, subjects: tuple[Subject, ...]
) -> str:
    sorted_subjects = tuple(sorted(subjects, key=lambda s: s.canonical()))
    payload = "\n".join(s.canonical() for s in sorted_subjects)
    digest = hashlib.blake2b(payload.encode("utf-8"), digest_size=6).hexdigest()
    return f"{','.join(roles)}__{intent}__{digest}"


# An initial stored body (a deterministic fallback-shaped body) the rewrite will REPLACE.
_INITIAL_BODY = (
    "# How the application starts\n\n"
    "Understand: the fastest path is the short sequence below.\n\n"
    "This page documents app.\n"
)


def _stored_segment(
    vocab: Vocabulary,
    *,
    roles: tuple[str, ...],
    intent: str,
    subjects: tuple[Subject, ...],
    body: str,
    summary: str,
) -> Segment:
    """A Segment as the real pipeline persists it: planner key -> build_blueprint -> wire."""
    sorted_subjects = tuple(sorted(subjects, key=lambda s: s.canonical()))
    planned = PlannedSegment(
        segment_key=_planner_segment_key(roles, intent, sorted_subjects),
        roles=roles,
        intent=intent,
        subjects=sorted_subjects,
        priority=0,
        evidence=(),
    )
    blueprint = build_blueprint(planned, None, vocab)
    return wire_segment(
        planned, blueprint, ProseResult(body=body, summary=summary, source="fake")
    )


def _rooted_copy(tmp_path: Path) -> str:
    """Copy the pristine fixture repo into ``tmp_path`` so the run can root there cleanly.

    ``Harness.run`` writes a runtime snapshot into the workspace root, so rooting at a
    throwaway copy keeps the committed fixture clean.
    """
    tmp_path.mkdir(parents=True, exist_ok=True)
    dest = tmp_path / "agentic_repo"
    shutil.copytree(_FIXTURE_REPO, dest)
    return str(dest)


def _session(
    tmp_path: Path,
    *,
    model: object | None,
    segments: tuple[Segment, ...],
) -> RefineSession:
    """A RefineSession over a real FilesystemSegmentStore, rooted at a fixture-repo copy."""
    vocab = _vocab()
    store_dir = tmp_path / "out" / "segments"
    store = FilesystemSegmentStore(str(store_dir), vocab)
    for seg in segments:
        store.put(seg)
    repo = _rooted_copy(tmp_path / "repo")

    class _Cfg:
        def __init__(self, provider: object) -> None:
            self.main = provider

    return RefineSession(
        out_dir=str(tmp_path / "out"),
        target_repo=repo,
        vocab=vocab,
        store=store,
        model_config=_Cfg(model) if model is not None else None,
        identity=object(),  # unused by the rewrite handler
        analysis=None,
    )


def _the_segment(vocab: Vocabulary) -> Segment:
    return _stored_segment(
        vocab,
        roles=("platform-dev",),
        intent="understand",
        subjects=(_subject("component:app"),),
        body=_INITIAL_BODY,
        summary="The initial, to-be-replaced summary.",
    )


# --------------------------------------------------------------------------- #
# Package surface: rewrite_segment is exposed from the handlers + the package.  #
# --------------------------------------------------------------------------- #


def test_handlers_expose_rewrite_segment() -> None:
    from docuharnessx import mcp

    assert hasattr(handlers, "rewrite_segment")
    assert hasattr(mcp, "rewrite_segment")
    assert mcp.rewrite_segment is handlers.rewrite_segment


# --------------------------------------------------------------------------- #
# Accepted rewrite: re-grounded, gated, replace-in-place (Req 5.1-5.4, 5.7, 5.8)#
# --------------------------------------------------------------------------- #


def test_accepted_rewrite_replaces_segment_in_place(tmp_path: Path) -> None:
    vocab = _vocab()
    seg = _the_segment(vocab)
    session = _session(tmp_path, model=ScriptedAgentProvider(), segments=(seg,))
    original_id = seg.id

    result = asyncio.run(handlers.rewrite_segment(session, original_id, ""))

    # An accepted rewrite is not an error envelope and reports acceptance.
    assert not result.get("error")
    assert result["accepted"] is True
    assert result["id"] == original_id

    # Replace-in-place: same id, body CHANGED to the grounded agentic body.
    stored = next(s for s in session.store.list_segments() if s.id == original_id)
    assert stored.id == original_id
    assert stored.body == SCRIPTED_AGENT_BODY
    assert stored.body != _INITIAL_BODY
    # The persisted body really clears the structure gate (Mermaid + citations).
    assert validate_agent_body(stored.body, min_citations=session.min_citations).accepted
    # Exactly one segment still on disk (no second id was created).
    assert len([s for s in session.store.list_segments()]) == 1


def test_accepted_rewrite_changes_only_body_and_summary(tmp_path: Path) -> None:
    vocab = _vocab()
    seg = _the_segment(vocab)
    session = _session(tmp_path, model=ScriptedAgentProvider(), segments=(seg,))

    asyncio.run(handlers.rewrite_segment(session, seg.id, ""))

    stored = next(s for s in session.store.list_segments() if s.id == seg.id)
    # Every non-body field is fixed by the deterministic wiring (Req 5.8).
    assert stored.id == seg.id
    assert stored.title == seg.title
    assert list(stored.roles) == list(seg.roles)
    assert stored.intent == seg.intent
    assert [s.canonical() for s in stored.subjects] == [
        s.canonical() for s in seg.subjects
    ]
    assert stored.schema_version == seg.schema_version
    # Only body + summary changed.
    assert stored.body == SCRIPTED_AGENT_BODY
    assert stored.summary != seg.summary
    assert stored.summary  # a derived, non-empty one-liner


def test_rewrite_reconstructs_the_same_id_blueprint(tmp_path: Path) -> None:
    # The replace-in-place id MUST be the round-tripped stored id (Req 5.8 / planned glue).
    vocab = _vocab()
    seg = _the_segment(vocab)
    planned = planned_from_segment(seg)
    assert segment_id(planned) == seg.id


# --------------------------------------------------------------------------- #
# Guidance is APPLIED, not echoed (Req 5.9, 9.7).                               #
# --------------------------------------------------------------------------- #


def test_guidance_reaches_the_agent_task_but_is_not_echoed(tmp_path: Path) -> None:
    # A recording provider captures the rendered task description so we can assert the
    # guidance reached the agent's task; the accepted body must NOT echo it as a heading.
    guidance = "Emphasise the bounded work cycle and the configuration defaults."

    class _RecordingProvider(ScriptedAgentProvider):
        def __init__(self) -> None:
            super().__init__()
            self.seen_text = ""

        async def complete(self, messages, tools, stream_callback=None):
            for m in messages:
                content = getattr(m, "content", None)
                if content:
                    self.seen_text += str(content) + "\n"
            return await super().complete(messages, tools, stream_callback)

    provider = _RecordingProvider()
    seg = _the_segment(_vocab())
    session = _session(tmp_path, model=provider, segments=(seg,))

    result = asyncio.run(handlers.rewrite_segment(session, seg.id, guidance))
    assert result["accepted"] is True

    # (a) The guidance reached the agent's task (the applied author-guidance instruction).
    assert guidance in provider.seen_text
    assert "Apply this refinement guidance" in provider.seen_text

    # (b) The verbatim guidance text is NOT a heading/section line in the accepted body.
    stored = next(s for s in session.store.list_segments() if s.id == seg.id)
    for line in stored.body.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            assert guidance not in stripped


# --------------------------------------------------------------------------- #
# Rejected / empty run: surface verdict + fallback, persist NOTHING (Req 5.5).  #
# --------------------------------------------------------------------------- #


class _RejectedBodyProvider:
    """A provider whose end-turn body fails the structure gate (no mermaid / citations)."""

    async def complete(self, messages, tools, stream_callback=None):
        from harnessx.core.events import ModelResponseEvent

        return ModelResponseEvent(
            run_id="rejected-run",
            step_id=0,
            content="Just some prose with no mermaid and no citations.",
            finish_reason="end_turn",
        )

    def count_tokens(self, messages) -> int:
        return 1


def test_rejected_run_persists_nothing_and_surfaces_verdict_plus_fallback(
    tmp_path: Path,
) -> None:
    vocab = _vocab()
    seg = _the_segment(vocab)
    session = _session(tmp_path, model=_RejectedBodyProvider(), segments=(seg,))

    result = asyncio.run(handlers.rewrite_segment(session, seg.id, ""))

    # Not accepted: the verdict is surfaced and a deterministic fallback is offered.
    assert result["accepted"] is False
    assert result.get("error") is not True  # a reject is a verdict, not a tool error
    assert "reason" in result  # the gate verdict
    assert result.get("fallback_body")  # the deterministic fallback body is surfaced
    # The fallback is NOT persisted: the stored segment is unchanged.
    stored = next(s for s in session.store.list_segments() if s.id == seg.id)
    assert stored.body == _INITIAL_BODY
    assert stored.summary == seg.summary


def test_empty_run_persists_nothing(tmp_path: Path) -> None:
    class _EmptyBodyProvider:
        async def complete(self, messages, tools, stream_callback=None):
            from harnessx.core.events import ModelResponseEvent

            return ModelResponseEvent(
                run_id="empty-run", step_id=0, content="", finish_reason="end_turn"
            )

        def count_tokens(self, messages) -> int:
            return 1

    vocab = _vocab()
    seg = _the_segment(vocab)
    session = _session(tmp_path, model=_EmptyBodyProvider(), segments=(seg,))

    result = asyncio.run(handlers.rewrite_segment(session, seg.id, ""))
    assert result["accepted"] is False
    stored = next(s for s in session.store.list_segments() if s.id == seg.id)
    assert stored.body == _INITIAL_BODY


# --------------------------------------------------------------------------- #
# No model: explicit "no model configured" result, no content (Req 5.6).        #
# --------------------------------------------------------------------------- #


def test_no_model_returns_explicit_result_without_producing_content(
    tmp_path: Path,
) -> None:
    vocab = _vocab()
    seg = _the_segment(vocab)
    session = _session(tmp_path, model=None, segments=(seg,))

    result = asyncio.run(handlers.rewrite_segment(session, seg.id, "do something"))

    assert result.get("no_model") is True or result.get("code") == "no_model"
    assert result["accepted"] is False
    # No content produced; the stored segment is unchanged.
    stored = next(s for s in session.store.list_segments() if s.id == seg.id)
    assert stored.body == _INITIAL_BODY


# --------------------------------------------------------------------------- #
# Missing id: structured tool error, never a raise (mirrors the read tools).    #
# --------------------------------------------------------------------------- #


def test_missing_id_returns_structured_error(tmp_path: Path) -> None:
    session = _session(
        tmp_path, model=ScriptedAgentProvider(), segments=(_the_segment(_vocab()),)
    )
    result = asyncio.run(handlers.rewrite_segment(session, "no-such-id", ""))
    assert result.get("error") is True
    assert "no-such-id" in result["message"]


# --------------------------------------------------------------------------- #
# The handler never free-writes: a body only ever comes from the runner.        #
# --------------------------------------------------------------------------- #


def test_default_min_citations_matches_the_gate(tmp_path: Path) -> None:
    session = _session(
        tmp_path, model=ScriptedAgentProvider(), segments=(_the_segment(_vocab()),)
    )
    assert session.min_citations == MIN_CITED_FILES
