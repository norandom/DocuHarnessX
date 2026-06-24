"""Unit tests for the crafted fixture repository (agentic-codebase-writer task 1.3).

Task 1.3 (boundary: *test fixtures*, Req 9.3) adds a small but realistic fixture
repository under ``tests/fixtures/agentic_repo`` whose contents make the scripted
fake-agent provider's reads and the produced ``file:line`` citations DETERMINISTIC and
self-consistent: the cited paths and line numbers point at real fixture content.

The observable completion (task 1.3) is that a unit test reads the fixture files THROUGH
THE REAL read/grep tools rooted at the fixture directory and confirms the citations in the
scripted body resolve to existing lines in the fixture. These tests therefore drive the real
:class:`~harnessx.core.harness.Harness` (with the scripted provider) over a read-only
``Workspace`` rooted at the fixture repo using only the in-process builtin tools, so they
require neither credentials nor a network. The fixture is also exercised structurally (it is
a realistic repo: a build manifest, an entrypoint, source files with stable symbols, and a
README) and for self-consistency (every cited line is the symbol the scripted body claims).
"""

from __future__ import annotations

import asyncio
import re
import shutil
from pathlib import Path

from harnessx.core.config_schema import NullTracerConfig
from harnessx.core.harness import BaseTask, HarnessConfig
from harnessx.core.model_config import ModelConfig
from harnessx.providers.base import BaseModelProvider
from harnessx.tools.builtin import build_default_tools
from harnessx.workspace.workspace import Workspace

from docuharnessx.composition.budgets import MIN_CITED_FILES

from tests._fakes import (
    SCRIPTED_AGENT_BODY,
    SCRIPTED_AGENT_READS,
    ScriptedAgentProvider,
)

#: The crafted fixture repository under test (task 1.3).
_FIXTURE_REPO = Path(__file__).parent / "fixtures" / "agentic_repo"

#: A "path:line" citation token — a relative path ending in a known source extension followed
#: by ``:<digits>``. Mirrors the structure gate's notion of a ``file:line`` citation.
_CITATION_RE = re.compile(r"([\w./-]+\.(?:py|md|txt|toml|yaml|yml|json)):(\d+)")

#: The exact symbol the scripted body anchors each cited line to (path, line) -> substring
#: that MUST appear on that fixture line. This makes the fixture/script pairing self-checking:
#: if a future edit shifts a symbol's line, this mapping fails loudly.
_CITED_SYMBOLS: dict[tuple[str, int], str] = {
    ("app.py", 11): "class Application",
    ("app.py", 17): "def run",
    ("engine.py", 16): "def start",
    ("config.py", 10): "def load_config",
}


def _build_harness(provider: BaseModelProvider, repo: Path):
    """Compose a minimal, model-free harness over a read-only workspace rooted at *repo*.

    Uses only the in-process builtin tool registry and a null tracer, so the run is fully
    offline. The model is bound by the caller via ``ModelConfig(main=provider).agentic(...)``.
    """
    config = HarnessConfig(
        tool_registry=build_default_tools(),
        tracer=NullTracerConfig(),
        workspace=Workspace(agent_id="fixture-reader", root=repo, mode="readonly"),
        init_workspace=False,
    )
    return ModelConfig(main=provider).agentic(config)


def _run(provider: BaseModelProvider, repo: Path):
    """Drive the harness to completion on its own event loop and clean it up."""

    async def _drive():
        harness = _build_harness(provider, repo)
        try:
            return await harness.run(
                BaseTask(description="Read the fixture repository.", max_steps=8)
            )
        finally:
            await harness.cleanup()

    return asyncio.run(_drive())


def _rooted_copy(tmp_path: Path) -> Path:
    """Copy the pristine committed fixture into *tmp_path* so a run can root there.

    ``Harness.run`` writes a ``{workspace_root}/harness_config.yaml`` runtime snapshot into
    whatever directory the workspace is rooted at. Rooting the harness at a throwaway copy
    keeps the committed fixture clean and machine-independent, so the fixture stays
    deterministic across repeated runs and across CI.
    """
    dest = tmp_path / "agentic_repo"
    shutil.copytree(_FIXTURE_REPO, dest)
    return dest


def _tool_messages(result, name: str) -> list:
    return [
        m
        for m in result.task_end.final_messages
        if getattr(m, "role", None) == "tool" and getattr(m, "name", None) == name
    ]


def _text(message) -> str:
    content = message.content
    return content if isinstance(content, str) else str(content)


# --------------------------------------------------------------------------- #
# The fixture is a small but realistic repo (Req 9.3)                          #
# --------------------------------------------------------------------------- #


def test_fixture_repo_has_realistic_layout() -> None:
    """A build manifest, an entrypoint, a couple of source files, and a README all exist."""
    assert _FIXTURE_REPO.is_dir()
    # Build manifest (portable, no machine-specific absolute paths).
    assert (_FIXTURE_REPO / "pyproject.toml").is_file()
    # Entrypoint + source modules with the cited symbols.
    assert (_FIXTURE_REPO / "app.py").is_file()
    assert (_FIXTURE_REPO / "engine.py").is_file()
    assert (_FIXTURE_REPO / "config.py").is_file()
    # A README so the repo reads like a real project.
    assert (_FIXTURE_REPO / "README.md").is_file()


def test_fixture_repo_carries_no_machine_specific_absolute_paths() -> None:
    """No fixture file may pin a machine-specific absolute path (keeps it portable).

    A fixture that embeds ``/home/<user>/...`` is non-deterministic across machines and CI;
    the agentic writer roots its read-only workspace at the repo path at runtime, so the
    fixture must never hardcode one.
    """
    for path in _FIXTURE_REPO.rglob("*"):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        assert "/home/" not in text, f"{path.name} must not pin a machine-specific path"


# --------------------------------------------------------------------------- #
# Real read/grep tools rooted at the fixture resolve the scripted reads (9.3)  #
# --------------------------------------------------------------------------- #


def test_real_read_tool_rooted_at_fixture_returns_real_content(tmp_path) -> None:
    """Driving the scripted provider executes the REAL Read tool over the fixture files.

    Each scripted ``Read`` turn resolves a RELATIVE path against the read-only workspace
    rooted at the fixture and returns the real, line-numbered fixture content — proving the
    reads resolve at the fixture directory (not an error, not an empty body).
    """
    provider = ScriptedAgentProvider()
    result = _run(provider, _rooted_copy(tmp_path))

    # One real Read tool message per scripted Read call across every scripted turn.
    expected_reads = sum(
        1 for turn in SCRIPTED_AGENT_READS for (name, _input) in turn if name == "Read"
    )
    reads = _tool_messages(result, "Read")
    assert len(reads) == len(provider.read_paths) == expected_reads

    # Each scripted Read returned the real fixture file, line-numbered, with no error.
    contents = [_text(m) for m in reads]
    joined = "\n".join(contents)
    assert all("Error" not in c for c in contents)
    assert all("\t" in c for c in contents)  # the read tool prefixes "<n>\t" per line
    # The real symbols the body cites appear in the read tool output.
    assert "class Application" in joined
    assert "def run" in joined
    assert "def start" in joined
    assert "def load_config" in joined


def test_real_grep_tool_rooted_at_fixture_finds_the_symbol(tmp_path) -> None:
    """The scripted Grep turn executes the REAL grep tool rooted at the fixture.

    The scripted turn greps for ``def load_config``; the real grep, rooted at the fixture,
    must locate it in ``config.py`` — confirming grep resolves against the fixture directory.
    """
    provider = ScriptedAgentProvider()
    result = _run(provider, _rooted_copy(tmp_path))

    greps = _tool_messages(result, "Grep")
    assert greps, "the scripted Grep turn must execute the real grep tool"
    assert "config.py" in _text(greps[0])


# --------------------------------------------------------------------------- #
# Every scripted-body citation resolves to a real fixture line (Req 9.3)       #
# --------------------------------------------------------------------------- #


def test_scripted_body_citations_resolve_to_existing_fixture_lines() -> None:
    """Each ``file:line`` citation in the scripted body points at an existing fixture line."""
    citations = _CITATION_RE.findall(SCRIPTED_AGENT_BODY)
    assert citations, "the scripted body must carry file:line citations"

    distinct_files = {path for (path, _line) in citations}
    assert len(distinct_files) >= MIN_CITED_FILES

    for path, line_str in citations:
        target = _FIXTURE_REPO / path
        assert target.is_file(), f"cited file {path!r} must exist in the fixture repo"
        lines = target.read_text(encoding="utf-8").splitlines()
        line = int(line_str)
        assert 1 <= line <= len(lines), f"cited {path}:{line} must resolve to a real line"


def test_scripted_body_citations_are_self_consistent_with_symbols() -> None:
    """Each cited line actually contains the symbol the scripted body claims it does.

    This is the deterministic, self-consistency guarantee of task 1.3: the script and the
    fixture are pinned together, so a future edit that shifts ``run`` / ``start`` /
    ``load_config`` / ``Application`` off its cited line fails this test loudly.
    """
    for (path, line), symbol in _CITED_SYMBOLS.items():
        # Every pinned (path, line) is actually cited by the scripted body.
        assert f"{path}:{line}" in SCRIPTED_AGENT_BODY, f"{path}:{line} must be cited"
        lines = (_FIXTURE_REPO / path).read_text(encoding="utf-8").splitlines()
        assert symbol in lines[line - 1], f"{path}:{line} must contain {symbol!r}"
