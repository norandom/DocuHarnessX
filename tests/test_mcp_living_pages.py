"""Living-page MCP refine session (tasks 5.1–5.4)."""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

from harnessx.core.model_config import ModelConfig

from docuharnessx.mcp import handlers
from docuharnessx.mcp.session import resolve_session
from docuharnessx.pages.model import Page
from docuharnessx.pages.store import FilesystemLivingPageStore
from _fakes import FakeProvider, ScriptedAgentProvider

_FIXTURE_REPO = Path(__file__).parent / "fixtures" / "agentic_repo"

_GROUNDED_BODY = (
    "The `Engine` class loads run settings through `load_config` (`config.py:10`)\n"
    "and then drives a bounded work cycle (`engine.py:16`).\n"
)

_PAGE_ID = "component:root"


def _seeded_session(tmp_path: Path, *, model: object | None = None):
    repo = tmp_path / "repo"
    shutil.copytree(_FIXTURE_REPO, repo)
    store = FilesystemLivingPageStore(str(repo))
    store.put(
        Page(
            id=_PAGE_ID,
            title="What is the root component?",
            summary="Engine",
            body=_GROUNDED_BODY,
            subjects=("component:",),
            related=(),
            cited_files=("config.py", "engine.py"),
        )
    )
    model_config = None if model is None else ModelConfig(main=model)
    session = resolve_session(str(repo), None, model_config=model_config)
    return repo, store, session


def test_session_lists_and_validates_living_pages(tmp_path: Path) -> None:
    _repo, _store, session = _seeded_session(tmp_path)
    listed = handlers.list_pages(session)
    assert any(item["id"] == _PAGE_ID for item in listed)
    got = handlers.get_segment(session, _PAGE_ID)
    assert got["id"] == _PAGE_ID
    assert "Engine" in got["body"]
    missing = handlers.get_segment(session, "no-such")
    assert missing.get("error") is True
    verdict = handlers.validate_segment(session, _PAGE_ID)
    assert "accepted" in verdict
    overview = handlers.get_overview(session)
    assert overview.get("error") is True or overview.get("code") == "unsupported"


def test_no_model_rewrite_is_explicit_and_does_not_change_page(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("LITELLM_API_KEY", raising=False)
    _repo, store, session = _seeded_session(tmp_path, model=None)
    session.model_config = None
    before = store.get(_PAGE_ID)
    assert before is not None
    result = asyncio.run(handlers.rewrite_segment(session, _PAGE_ID, "more detail"))
    assert result.get("no_model") is True
    after = store.get(_PAGE_ID)
    assert after is not None
    assert after.body == before.body


def test_rejected_cycle_keeps_previous_page(tmp_path: Path) -> None:
    _repo, store, session = _seeded_session(
        tmp_path, model=FakeProvider(content="Locate the CLI. Run the smallest action.")
    )
    before = store.get(_PAGE_ID)
    assert before is not None
    result = asyncio.run(handlers.rewrite_segment(session, _PAGE_ID, "more detail"))
    assert result.get("accepted") is False
    after = store.get(_PAGE_ID)
    assert after is not None
    assert after.body == before.body
    assert session.cycles == 1


def test_accepted_later_cycle_updates_store(tmp_path: Path) -> None:
    _repo, store, session = _seeded_session(
        tmp_path, model=ScriptedAgentProvider(body=_GROUNDED_BODY)
    )
    first = asyncio.run(
        handlers.rewrite_segment(
            session, _PAGE_ID, FakeProvider(content="bad")._content
        )
    )
    # First cycle with grounded scripted provider should accept.
    assert first.get("accepted") is True
    after = store.get(_PAGE_ID)
    assert after is not None
    assert "Engine" in after.body
    assert session.cycles >= 1
    journals = list((_repo / ".docuharnessx" / "journals").glob("refine-*.json"))
    assert journals


def test_reassemble_from_living_pages(tmp_path: Path) -> None:
    _repo, store, session = _seeded_session(tmp_path)
    store.put(
        Page(
            id="build:pyproject.toml",
            title="How is the project built?",
            summary="build",
            body="Build uses pyproject.toml.",
            subjects=("artifact:",),
            related=(),
            cited_files=("pyproject.toml",),
        )
    )
    result = handlers.reassemble_site(session)
    assert result.get("assembled") is True
    assert result.get("page_count") == 2
