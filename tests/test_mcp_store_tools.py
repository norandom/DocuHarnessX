"""Unit tests for the read-only, model-free store tools (mcp-refine task 3.1).

Task 3.1 owns three handlers over a :class:`~docuharnessx.mcp.session.RefineSession`'s
:class:`~docuharnessx.ontology.FilesystemSegmentStore` — the on-disk **source of truth** —
none of which consults a model:

* ``list_segments(session)`` — every stored segment in the store's deterministic **by-id**
  order, each carrying at least ``id`` / ``title`` / ``roles`` / ``intent`` / ``subjects``
  (Req 4.1, 4.4, 4.5);
* ``get_segment(session, id)`` — the full stored segment incl. ``summary`` + ``body``; a
  missing id yields a **structured tool error** naming the id (it never raises out of the
  handler) (Req 4.2, 4.3, 4.4);
* ``validate_segment(session, id)`` — the deterministic structure gate
  (:func:`~docuharnessx.composition.validate_agent_body`) over the body, returning
  ``accepted`` / ``mermaid_blocks`` / ``cited_files`` / ``reason`` at the **same**
  ``min_citations`` threshold the rewrite path enforces; a missing id yields the same
  structured error (Req 6.1-6.4).

These tests build a real :class:`FilesystemSegmentStore` over a tmp directory (the same
on-disk truth a batch run produces) and a :class:`RefineSession` carrying it, then pin the
documented shapes, the by-id order, the threshold parity, the missing-id error envelope, and
that no model is ever consulted — all credential-free, with no network.
"""

from __future__ import annotations

import hashlib

import pytest

from docuharnessx import mcp
from docuharnessx.composition import MIN_CITED_FILES, validate_agent_body
from docuharnessx.composition.blueprint import build_blueprint
from docuharnessx.composition.model import ProseResult
from docuharnessx.composition.wiring import wire_segment
from docuharnessx.mcp import handlers
from docuharnessx.mcp.session import RefineSession
from docuharnessx.ontology import (
    AxisTerm,
    FilesystemSegmentStore,
    Segment,
    Subject,
    Vocabulary,
)
from docuharnessx.planning.model import PlannedSegment

_PREFIXES = frozenset({"component", "tech", "artifact", "topic"})


def _subject(raw: str) -> Subject:
    return Subject.parse(raw, _PREFIXES)


def _vocab() -> Vocabulary:
    return Vocabulary(
        roles=(
            AxisTerm("platform-dev", "Platform Developer", "Builds on the platform."),
            AxisTerm("auditor", "Compliance Auditor", "Assesses compliance."),
            AxisTerm("adopter", "Adopter", "Adopts the project."),
        ),
        intents=(
            AxisTerm("extend", "Extend", "Add capabilities."),
            AxisTerm("review", "Review", "Judge quality."),
            AxisTerm("understand", "Understand", "Build a mental model."),
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


# A grounded body that PASSES the structure gate: one valid mermaid diagram + >= the minimum
# distinct file:line citations.
_GROUNDED_BODY = (
    "## Overview\n\n"
    "```mermaid\n"
    "graph TD\n"
    "  A --> B\n"
    "```\n\n"
    "The CLI entrypoint lives in cli.py:10 and dispatches to the runner in "
    "agent.py:42, validated by gate.py:7.\n"
)

# A body that FAILS the structure gate: no mermaid, one citation only.
_UNGROUNDED_BODY = "Just prose mentioning cli.py:10 and nothing else.\n"


def _stored_segment(
    vocab: Vocabulary,
    *,
    roles: tuple[str, ...],
    intent: str,
    subjects: tuple[Subject, ...],
    body: str,
    summary: str,
) -> Segment:
    """A Segment as the real pipeline persists it: planner key -> wire_segment."""
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


def _session_with_segments(tmp_path, segments: tuple[Segment, ...]) -> RefineSession:
    """A RefineSession over a real FilesystemSegmentStore seeded with ``segments``.

    The store is the on-disk source of truth; model_config is None (these tools are
    model-free), so nothing here requires a provider or network.
    """
    vocab = _vocab()
    store = FilesystemSegmentStore(str(tmp_path / "segments"), vocab)
    for seg in segments:
        store.put(seg)
    # A minimal, model-free session; identity/analysis are irrelevant to the store tools.
    return RefineSession(
        out_dir=str(tmp_path / "out"),
        target_repo=str(tmp_path),
        vocab=vocab,
        store=store,
        model_config=None,
        identity=object(),  # unused by the read/validate handlers
        analysis=None,
    )


def _three_segments(vocab: Vocabulary) -> tuple[Segment, ...]:
    return (
        _stored_segment(
            vocab,
            roles=("platform-dev", "auditor"),
            intent="extend",
            subjects=(_subject("component:cli"), _subject("tech:python")),
            body=_GROUNDED_BODY,
            summary="A grounded segment.",
        ),
        _stored_segment(
            vocab,
            roles=("adopter",),
            intent="understand",
            subjects=(_subject("topic:onboarding"),),
            body=_UNGROUNDED_BODY,
            summary="An ungrounded segment.",
        ),
        _stored_segment(
            vocab,
            roles=("auditor",),
            intent="review",
            subjects=(_subject("topic:security"),),
            body=_GROUNDED_BODY,
            summary="Another grounded segment.",
        ),
    )


# --------------------------------------------------------------------------- #
# Package surface (3.1): the handlers module is importable from the package.    #
# --------------------------------------------------------------------------- #


def test_handlers_module_exposes_the_three_read_tools() -> None:
    assert hasattr(handlers, "list_segments")
    assert hasattr(handlers, "get_segment")
    assert hasattr(handlers, "validate_segment")


# --------------------------------------------------------------------------- #
# list_segments: by-id order, documented axes, model-free (Req 4.1, 4.4, 4.5).  #
# --------------------------------------------------------------------------- #


def test_list_segments_returns_axes_in_by_id_order(tmp_path) -> None:
    vocab = _vocab()
    segs = _three_segments(vocab)
    session = _session_with_segments(tmp_path, segs)

    listed = handlers.list_segments(session)

    # The store's deterministic by-id order is the authority.
    expected_ids = [s.id for s in session.store.list_segments()]
    assert [entry["id"] for entry in listed] == expected_ids
    assert sorted(expected_ids) == expected_ids  # by-id

    by_id = {s.id: s for s in segs}
    for entry in listed:
        seg = by_id[entry["id"]]
        # Each entry carries at least id/title/roles/intent/subjects (Req 4.1).
        assert entry["title"] == seg.title
        assert list(entry["roles"]) == list(seg.roles)
        assert entry["intent"] == seg.intent
        assert list(entry["subjects"]) == [s.canonical() for s in seg.subjects]
        # list_segments does NOT carry the full body (that is get_segment's job).
        assert "body" not in entry


def test_list_segments_empty_store_yields_empty_list(tmp_path) -> None:
    session = _session_with_segments(tmp_path, ())
    assert handlers.list_segments(session) == []


def test_list_segments_consults_no_model(tmp_path, monkeypatch) -> None:
    # A model-free tool: even a session with a None model lists fine, and we assert the
    # store is the only thing read (the session.model() provider is never touched).
    session = _session_with_segments(tmp_path, _three_segments(_vocab()))

    def _boom() -> None:  # pragma: no cover - must never be called
        raise AssertionError("list_segments must not consult a model")

    monkeypatch.setattr(session, "model", _boom)
    handlers.list_segments(session)


# --------------------------------------------------------------------------- #
# get_segment: full body + summary; missing id -> structured error (Req 4.2-4.4)#
# --------------------------------------------------------------------------- #


def test_get_segment_returns_full_segment(tmp_path) -> None:
    vocab = _vocab()
    segs = _three_segments(vocab)
    session = _session_with_segments(tmp_path, segs)
    target = session.store.list_segments()[0]

    got = handlers.get_segment(session, target.id)

    assert got["id"] == target.id
    assert got["title"] == target.title
    assert list(got["roles"]) == list(target.roles)
    assert got["intent"] == target.intent
    assert list(got["subjects"]) == [s.canonical() for s in target.subjects]
    assert got["summary"] == target.summary
    assert got["body"] == target.body
    # A successful result is NOT an error envelope.
    assert not got.get("error")


def test_get_segment_missing_id_returns_structured_error_not_raise(tmp_path) -> None:
    session = _session_with_segments(tmp_path, _three_segments(_vocab()))
    # No exception escapes the handler (Req 4.3).
    result = handlers.get_segment(session, "no-such-id")
    assert result.get("error") is True
    # The missing id is named in the error so the client can act on it.
    assert "no-such-id" in result["message"]


def test_get_segment_consults_no_model(tmp_path, monkeypatch) -> None:
    session = _session_with_segments(tmp_path, _three_segments(_vocab()))
    target = session.store.list_segments()[0]

    def _boom() -> None:  # pragma: no cover - must never be called
        raise AssertionError("get_segment must not consult a model")

    monkeypatch.setattr(session, "model", _boom)
    handlers.get_segment(session, target.id)


# --------------------------------------------------------------------------- #
# validate_segment: gate verdict shape, threshold parity, missing-id error      #
# (Req 6.1-6.4).                                                                 #
# --------------------------------------------------------------------------- #


def test_validate_segment_accepts_a_grounded_body(tmp_path) -> None:
    vocab = _vocab()
    segs = _three_segments(vocab)
    session = _session_with_segments(tmp_path, segs)
    # Find the grounded segment.
    grounded = next(s for s in session.store.list_segments() if s.body == _GROUNDED_BODY)

    verdict = handlers.validate_segment(session, grounded.id)

    expected = validate_agent_body(grounded.body, min_citations=session.min_citations)
    assert verdict["accepted"] is True
    assert verdict["accepted"] == expected.accepted
    assert verdict["mermaid_blocks"] == expected.mermaid_blocks
    assert verdict["cited_files"] == expected.cited_files
    assert verdict["reason"] == expected.reason


def test_validate_segment_rejects_an_ungrounded_body(tmp_path) -> None:
    vocab = _vocab()
    segs = _three_segments(vocab)
    session = _session_with_segments(tmp_path, segs)
    ungrounded = next(
        s for s in session.store.list_segments() if s.body == _UNGROUNDED_BODY
    )

    verdict = handlers.validate_segment(session, ungrounded.id)
    assert verdict["accepted"] is False
    assert verdict["mermaid_blocks"] == 0
    assert not verdict.get("error")  # a rejection is a verdict, not a tool error


def test_validate_segment_uses_session_min_citations_threshold(tmp_path) -> None:
    # Req 6.4: validate uses the SAME minimum-citations threshold the rewrite path enforces
    # (session.min_citations). Raise the bar above what the body provides -> rejection.
    vocab = _vocab()
    segs = _three_segments(vocab)
    session = _session_with_segments(tmp_path, segs)
    session.min_citations = 99  # impossibly high bar
    grounded = next(s for s in session.store.list_segments() if s.body == _GROUNDED_BODY)

    verdict = handlers.validate_segment(session, grounded.id)
    expected = validate_agent_body(grounded.body, min_citations=99)
    assert verdict["accepted"] is False
    assert verdict["accepted"] == expected.accepted
    assert verdict["reason"] == expected.reason


def test_validate_segment_default_threshold_is_min_cited_files(tmp_path) -> None:
    # The session default bar equals MIN_CITED_FILES (the gate's documented default).
    session = _session_with_segments(tmp_path, _three_segments(_vocab()))
    assert session.min_citations == MIN_CITED_FILES


def test_validate_segment_missing_id_returns_structured_error(tmp_path) -> None:
    session = _session_with_segments(tmp_path, _three_segments(_vocab()))
    result = handlers.validate_segment(session, "ghost")
    assert result.get("error") is True
    assert "ghost" in result["message"]


def test_validate_segment_consults_no_model(tmp_path, monkeypatch) -> None:
    session = _session_with_segments(tmp_path, _three_segments(_vocab()))
    target = session.store.list_segments()[0]

    def _boom() -> None:  # pragma: no cover - must never be called
        raise AssertionError("validate_segment must not consult a model")

    monkeypatch.setattr(session, "model", _boom)
    handlers.validate_segment(session, target.id)
