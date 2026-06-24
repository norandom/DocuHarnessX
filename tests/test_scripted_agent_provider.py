"""Unit tests for the scripted fake-agent provider (agentic-codebase-writer task 1.2).

Task 1.2 (boundary: *test fakes*, Req 9.1, 9.2) adds a ``BaseModelProvider``-shaped test
provider whose ``complete`` returns a DETERMINISTIC sequence of tool-call responses
(read/grep over the crafted fixture repo) followed by a final end-turn response whose
content is a grounded body containing a valid Mermaid fence and at least the minimum number
of ``file:line`` citations (Req 9.1).

The observable completion (task 1.2) is that the provider, run through the REAL HarnessX run
loop, makes the scripted tools EXECUTE (real file reads occur) and the final answer carries
the Mermaid fence and citations, with NO network access (Req 9.2). These tests drive the
real :class:`~harnessx.core.harness.Harness` over a read-only ``Workspace`` rooted at
``tests/fixtures/agentic_repo`` (task 1.3) using only the in-process builtin tools, so they
require neither credentials nor a network.
"""

from __future__ import annotations

import asyncio
import re
import shutil
from pathlib import Path

import pytest

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

#: The crafted fixture repository the scripted reads target (task 1.3).
_FIXTURE_REPO = Path(__file__).parent / "fixtures" / "agentic_repo"

#: A "path:line" citation token — a path ending in a known source extension followed by a
#: colon and a line number. Mirrors the structure gate's notion of a ``file:line`` citation.
_CITATION_RE = re.compile(r"([\w./-]+\.(?:py|md|txt|toml|yaml|yml|json)):(\d+)")


def _build_harness(provider: BaseModelProvider, repo: Path):
    """Compose a minimal, model-free harness over a read-only workspace rooted at *repo*.

    Uses only the in-process builtin tool registry and a null tracer, so the run is fully
    offline. The model is bound by the caller via ``ModelConfig(main=provider).agentic(...)``.
    """
    config = HarnessConfig(
        tool_registry=build_default_tools(),
        tracer=NullTracerConfig(),
        workspace=Workspace(agent_id="scripted-writer", root=repo, mode="readonly"),
        init_workspace=False,
    )
    return ModelConfig(main=provider).agentic(config)


def _run(provider: BaseModelProvider, repo: Path):
    """Drive the harness to completion on its own event loop and clean it up."""

    async def _drive():
        harness = _build_harness(provider, repo)
        try:
            return await harness.run(BaseTask(description="Document this repository.", max_steps=8))
        finally:
            await harness.cleanup()

    return asyncio.run(_drive())


def _rooted_copy(tmp_path: Path) -> Path:
    """Copy the pristine committed fixture into *tmp_path* so a run can root there.

    ``Harness.run`` writes a ``{workspace_root}/harness_config.yaml`` runtime snapshot into
    whatever directory the workspace is rooted at, with a machine-specific absolute path.
    Rooting the harness at a throwaway copy keeps the committed fixture clean and
    deterministic across repeated runs and across CI.
    """
    tmp_path.mkdir(parents=True, exist_ok=True)
    dest = tmp_path / "agentic_repo"
    shutil.copytree(_FIXTURE_REPO, dest)
    return dest


# --------------------------------------------------------------------------- #
# Provider shape — it is a genuine BaseModelProvider                           #
# --------------------------------------------------------------------------- #


def test_scripted_agent_provider_is_a_base_model_provider() -> None:
    provider = ScriptedAgentProvider()
    assert isinstance(provider, BaseModelProvider)
    # The agentic mixin must be available so ModelConfig(main=...).agentic(config) works.
    assert hasattr(provider, "agentic")


# --------------------------------------------------------------------------- #
# Real run loop — scripted tools EXECUTE (real file reads occur), no network   #
# --------------------------------------------------------------------------- #


def test_scripted_provider_drives_real_run_loop_and_reads_fixture_files(tmp_path) -> None:
    provider = ScriptedAgentProvider()
    result = _run(provider, _rooted_copy(tmp_path))

    # The run ended cleanly on the scripted end-turn body.
    assert result.task_end.exit_reason == "done"
    # The provider was called once per step: every scripted tool-call turn plus the final
    # end-turn turn.
    assert provider.complete_calls == len(SCRIPTED_AGENT_READS) + 1

    # Real read tools executed: every scripted Read produced a role=tool message whose
    # content is the real fixture file (line-numbered by the read tool), not an error.
    tool_messages = [m for m in result.task_end.final_messages if getattr(m, "role", None) == "tool"]
    read_results = [m for m in tool_messages if getattr(m, "name", None) == "Read"]
    assert len(read_results) == len(provider.read_paths)
    for msg in read_results:
        text = msg.content if isinstance(msg.content, str) else str(msg.content)
        assert "Error" not in text
        # The read tool prefixes each line with "<n>\t"; real content is present.
        assert "\t" in text

    # A real Grep tool executed too (the scripted turn 2 issued one).
    grep_results = [m for m in tool_messages if getattr(m, "name", None) == "Grep"]
    assert grep_results, "the scripted Grep turn must execute the real grep tool"
    grep_text = grep_results[0].content if isinstance(grep_results[0].content, str) else str(grep_results[0].content)
    assert "config.py" in grep_text  # grep found the load_config definition in the fixture


# --------------------------------------------------------------------------- #
# Final answer — grounded body with Mermaid fence + >= MIN_CITED_FILES files   #
# --------------------------------------------------------------------------- #


def test_final_answer_carries_mermaid_fence_and_citations(tmp_path) -> None:
    provider = ScriptedAgentProvider()
    result = _run(provider, _rooted_copy(tmp_path))

    body = result.task_end.final_output
    # The final answer is the scripted grounded body verbatim.
    assert body == SCRIPTED_AGENT_BODY

    # Exactly one fenced mermaid block whose first content line names a supported type.
    assert "```mermaid" in body
    after_fence = body.split("```mermaid", 1)[1].lstrip("\n")
    first_line = after_fence.splitlines()[0].strip()
    assert first_line.startswith("graph TD")

    # At least MIN_CITED_FILES distinct cited files, all resolving to real fixture content.
    citations = _CITATION_RE.findall(body)
    distinct_files = {path for (path, _line) in citations}
    assert len(distinct_files) >= MIN_CITED_FILES
    for path, line in citations:
        target = _FIXTURE_REPO / path
        assert target.is_file(), f"cited file {path!r} must exist in the fixture repo"
        line_count = len(target.read_text(encoding="utf-8").splitlines())
        assert 1 <= int(line) <= line_count, f"cited {path}:{line} must resolve to a real line"


# --------------------------------------------------------------------------- #
# Determinism — equal inputs yield an equal script                            #
# --------------------------------------------------------------------------- #


def test_scripted_provider_is_deterministic_across_runs(tmp_path) -> None:
    first = _run(ScriptedAgentProvider(), _rooted_copy(tmp_path / "first"))
    second = _run(ScriptedAgentProvider(), _rooted_copy(tmp_path / "second"))
    assert first.task_end.final_output == second.task_end.final_output
    assert first.task_end.exit_reason == second.task_end.exit_reason == "done"


def test_read_paths_expose_the_scripted_fixture_reads() -> None:
    provider = ScriptedAgentProvider()
    # The exposed read paths name the fixture files, in order, before any run.
    assert provider.read_paths == ["app.py", "engine.py", "config.py"]
    for path in provider.read_paths:
        assert (_FIXTURE_REPO / path).is_file()
