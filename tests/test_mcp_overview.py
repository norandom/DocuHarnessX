"""Unit tests for the overview tools: draft / refine / get (mcp-refine task 3.3).

Task 3.3 owns the three overview handlers over a
:class:`~docuharnessx.mcp.session.RefineSession`, each re-grounded through the **same**
bounded :class:`~docuharnessx.composition.AgenticProseRunner` + deterministic structure gate
the rewrite path uses (no second generation engine; Req 7.8, 1.4):

* ``draft_overview(session)`` — build the overview-shaped blueprint
  (:func:`~docuharnessx.mcp.overview.build_overview_blueprint`) and run the writer with
  ``guidance=""``; on a gate-passing body persist the overview as the **reserved first-class
  entry** ``overview`` and return the accepted result; on reject persist nothing and surface
  the verdict + deterministic fallback; no model -> explicit "no model configured" result
  (Req 7.1, 7.3, 7.4, 7.6, 7.7).
* ``refine_overview(session, guidance)`` — the same, but the human guidance reaches the agent
  through the writer's ``guidance`` keyword (``run(..., guidance=guidance)``), never through
  the frozen blueprint; the guidance is **applied, not echoed** — its verbatim text never
  appears as a heading/section in the accepted overview (Req 7.2, 9.7).
* ``get_overview(session)`` — the persisted overview body, or an explicit "no overview drafted
  yet" result when none exists (Req 7.5).

These drive the REAL run loop with the offline :class:`ScriptedAgentProvider` over the crafted
fixture repo (``tests/fixtures/agentic_repo``), so the agentic path runs with no network and no
credentials; the model-free paths use a ``model_config=None`` session.
"""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

import pytest

from docuharnessx import mcp
from docuharnessx.composition import MIN_CITED_FILES, validate_agent_body
from docuharnessx.mcp import handlers, overview
from docuharnessx.mcp.overview import OVERVIEW_SEGMENT_ID
from docuharnessx.mcp.session import RefineSession
from docuharnessx.ontology import (
    AxisTerm,
    FilesystemSegmentStore,
    Vocabulary,
)

from tests._fakes import SCRIPTED_AGENT_BODY, ScriptedAgentProvider

_FIXTURE_REPO = Path(__file__).parent / "fixtures" / "agentic_repo"


# --------------------------------------------------------------------------- #
# Fixtures: a per-target session over a real store + the fixture repo           #
# --------------------------------------------------------------------------- #


def _vocab() -> Vocabulary:
    return Vocabulary(
        roles=(
            AxisTerm("platform-dev", "Platform Developer", "Builds on the platform."),
            AxisTerm("adopter", "Adopter", "Adopts the project."),
        ),
        intents=(
            AxisTerm("extend", "Extend", "Add capabilities."),
            AxisTerm("understand", "Understand", "Build a mental model and orient."),
        ),
        subject_prefixes=("component:", "tech:", "artifact:", "topic:"),
    )


class _Identity:
    """A minimal stand-in for the per-target SiteIdentity (only site_name is read)."""

    site_name = "DemoProject"
    repo_name = "owner/demo"
    repo_url = "https://example.com/owner/demo"
    site_url = ""
    base_path = "/"
    edit_uri = ""


def _rooted_copy(tmp_path: Path) -> str:
    """Copy the pristine fixture repo into tmp so the run roots there cleanly."""
    dest = tmp_path / "agentic_repo"
    shutil.copytree(_FIXTURE_REPO, dest)
    return str(dest)


class _FakeModelConfig:
    """A ModelConfig-shaped object whose ``.main`` is the scripted provider."""

    def __init__(self, provider) -> None:
        self.main = provider


def _session(tmp_path: Path, *, model=True) -> RefineSession:
    vocab = _vocab()
    out_dir = tmp_path / "out"
    store = FilesystemSegmentStore(str(out_dir / "segments"), vocab)
    model_config = _FakeModelConfig(ScriptedAgentProvider()) if model else None
    return RefineSession(
        out_dir=str(out_dir),
        target_repo=_rooted_copy(tmp_path),
        vocab=vocab,
        store=store,
        model_config=model_config,
        identity=_Identity(),
        analysis=None,
    )


# --------------------------------------------------------------------------- #
# Package surface: the three overview handlers are exposed.                      #
# --------------------------------------------------------------------------- #


def test_handlers_module_exposes_the_three_overview_tools() -> None:
    assert hasattr(handlers, "draft_overview")
    assert hasattr(handlers, "refine_overview")
    assert hasattr(handlers, "get_overview")


def test_package_reexports_overview_persistence() -> None:
    # The overview persistence (reserved-entry get/put) is owned by overview.py.
    assert hasattr(overview, "OVERVIEW_SEGMENT_ID")
    assert overview.OVERVIEW_SEGMENT_ID == "overview"


# --------------------------------------------------------------------------- #
# get_overview before any draft: explicit "none yet" result (Req 7.5).          #
# --------------------------------------------------------------------------- #


def test_get_overview_before_any_draft_is_explicit_none(tmp_path: Path) -> None:
    session = _session(tmp_path, model=False)
    result = handlers.get_overview(session)
    # An explicit result, not an error envelope and not a body.
    assert result.get("exists") is False
    assert "body" not in result or not result.get("body")
    assert result.get("message")


# --------------------------------------------------------------------------- #
# draft_overview: gate-passing body persisted as the reserved entry (Req 7.1).  #
# --------------------------------------------------------------------------- #


def test_draft_overview_persists_gate_passing_reserved_entry(tmp_path: Path) -> None:
    session = _session(tmp_path)
    result = asyncio.run(handlers.draft_overview(session))

    # Accepted: the result reports acceptance and carries the gate verdict.
    assert result.get("accepted") is True
    assert not result.get("error")
    # The persisted body is the scripted grounded body and it clears the gate.
    assert validate_agent_body(SCRIPTED_AGENT_BODY).accepted
    # Persisted as the reserved first-class entry, retrievable via get_overview.
    got = handlers.get_overview(session)
    assert got.get("exists") is True
    assert got["body"] == SCRIPTED_AGENT_BODY
    assert got["id"] == OVERVIEW_SEGMENT_ID
    # The reserved overview <id>.md exists on disk under <out>/segments.
    assert (tmp_path / "out" / "segments" / f"{OVERVIEW_SEGMENT_ID}.md").is_file()


def test_draft_overview_result_carries_the_four_section_structure(tmp_path: Path) -> None:
    # The overview is structured around Purpose / Use cases / Features / Design choices: the
    # blueprint the handler ran over carries exactly those four chunk headings, in order.
    session = _session(tmp_path)
    asyncio.run(handlers.draft_overview(session))
    blueprint = overview.build_overview_blueprint(
        session.identity, session.vocab, session.analysis, guidance=""
    )
    assert [c.heading for c in blueprint.chunks] == [
        "Purpose",
        "Use cases",
        "Features",
        "Design choices",
    ]


# --------------------------------------------------------------------------- #
# refine_overview: re-grounded; guidance reaches the task but is NOT echoed.     #
# --------------------------------------------------------------------------- #


def test_refine_overview_persists_and_applies_guidance_not_echoed(tmp_path: Path) -> None:
    session = _session(tmp_path)
    # First draft so there is an overview to refine.
    asyncio.run(handlers.draft_overview(session))

    guidance = "ZZZ_UNIQUE_GUIDANCE_TOKEN emphasise the deployment story"
    result = asyncio.run(handlers.refine_overview(session, guidance))

    assert result.get("accepted") is True
    got = handlers.get_overview(session)
    assert got.get("exists") is True
    # The accepted overview is the re-grounded scripted body (the guidance shaped WHAT the
    # agent wrote; the scripted provider returns the same grounded body deterministically).
    assert got["body"] == SCRIPTED_AGENT_BODY
    # Applied, not echoed: the verbatim guidance text never appears as a heading/section
    # line in the accepted overview body (Req 7.2, 9.7).
    for line in got["body"].splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            assert "ZZZ_UNIQUE_GUIDANCE_TOKEN" not in stripped
    assert "ZZZ_UNIQUE_GUIDANCE_TOKEN" not in got["body"]


def test_refine_guidance_reaches_the_agent_task_not_the_blueprint(tmp_path: Path) -> None:
    # The human guidance flows to the agent through the writer's guidance keyword, rendered
    # into the BaseTask.description by _render_description (applied near the mission), never
    # through the frozen overview blueprint.
    from docuharnessx.composition.task_prompt import build_agent_task

    session = _session(tmp_path)
    guidance = "QQQ_REFINE_TOKEN cover the security model"
    blueprint = overview.build_overview_blueprint(
        session.identity, session.vocab, session.analysis, guidance=guidance
    )
    # The blueprint is independent of the guidance value: the token is NOT in it.
    assert "QQQ_REFINE_TOKEN" not in repr(blueprint)

    task = build_agent_task(blueprint, repo_path=session.target_repo, guidance=guidance)
    # The guidance reaches the rendered task description (applied), but never as a heading.
    assert "QQQ_REFINE_TOKEN" in task.description
    for line in task.description.splitlines():
        if line.strip().startswith("#"):
            assert "QQQ_REFINE_TOKEN" not in line


# --------------------------------------------------------------------------- #
# Rejected run: persist nothing, surface verdict + fallback (Req 7.6, 9.3).      #
# --------------------------------------------------------------------------- #


def test_rejected_overview_persists_nothing_and_surfaces_verdict(tmp_path: Path) -> None:
    session = _session(tmp_path)
    # An ungrounded body that FAILS the gate (no mermaid, too few citations).
    session.model_config = _FakeModelConfig(
        ScriptedAgentProvider(reads=(), body="Just prose mentioning app.py:1 only.\n")
    )

    result = asyncio.run(handlers.draft_overview(session))

    assert result.get("accepted") is False
    # The gate verdict is surfaced (not silently passed).
    assert "reason" in result
    assert result.get("mermaid_blocks") == 0
    # A deterministic fallback body is surfaced to the human.
    assert result.get("fallback_body")
    # Nothing persisted: get_overview still reports none, and no overview.md on disk.
    assert handlers.get_overview(session).get("exists") is False
    assert not (tmp_path / "out" / "segments" / f"{OVERVIEW_SEGMENT_ID}.md").exists()


def test_rejected_refine_leaves_prior_overview_unchanged(tmp_path: Path) -> None:
    session = _session(tmp_path)
    # A good first draft.
    asyncio.run(handlers.draft_overview(session))
    prior = handlers.get_overview(session)["body"]

    # Now a refine that fails the gate must NOT clobber the prior accepted overview.
    session.model_config = _FakeModelConfig(
        ScriptedAgentProvider(reads=(), body="ungrounded refine, no diagram.\n")
    )
    result = asyncio.run(handlers.refine_overview(session, "make it worse"))
    assert result.get("accepted") is False
    # The prior accepted overview is untouched (Req 7.6).
    assert handlers.get_overview(session)["body"] == prior


# --------------------------------------------------------------------------- #
# No model bound: explicit "no model configured" result; nothing produced.      #
# --------------------------------------------------------------------------- #


def test_draft_overview_no_model_returns_explicit_result(tmp_path: Path) -> None:
    session = _session(tmp_path, model=False)
    result = asyncio.run(handlers.draft_overview(session))
    assert result.get("accepted") is not True
    assert result.get("no_model") is True
    assert result.get("message")
    # Nothing produced or persisted.
    assert handlers.get_overview(session).get("exists") is False


def test_refine_overview_no_model_returns_explicit_result(tmp_path: Path) -> None:
    session = _session(tmp_path, model=False)
    result = asyncio.run(handlers.refine_overview(session, "some guidance"))
    assert result.get("no_model") is True
    assert result.get("message")
    assert handlers.get_overview(session).get("exists") is False


# --------------------------------------------------------------------------- #
# get_overview is model-free (Req 7.5 surface).                                 #
# --------------------------------------------------------------------------- #


def test_get_overview_consults_no_model(tmp_path: Path, monkeypatch) -> None:
    session = _session(tmp_path)
    asyncio.run(handlers.draft_overview(session))

    def _boom():  # pragma: no cover - must never be called
        raise AssertionError("get_overview must not consult a model")

    monkeypatch.setattr(session, "model", _boom)
    got = handlers.get_overview(session)
    assert got["body"] == SCRIPTED_AGENT_BODY


# --------------------------------------------------------------------------- #
# Bounded: the overview run is capped by the writer budgets (Req 9.6).          #
# --------------------------------------------------------------------------- #


def test_overview_run_is_bounded_and_never_freewrites(tmp_path: Path) -> None:
    # The handler never free-writes: the persisted body is exactly the agent's gated output,
    # produced by the real run loop (the scripted provider drove read/grep turns).
    provider = ScriptedAgentProvider()
    session = _session(tmp_path)
    session.model_config = _FakeModelConfig(provider)
    asyncio.run(handlers.draft_overview(session))
    # The real run loop executed the scripted exploration turns + the final body turn.
    assert provider.complete_calls >= 2
    assert handlers.get_overview(session)["body"] == SCRIPTED_AGENT_BODY
