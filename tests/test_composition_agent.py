"""Unit tests for the bounded agentic prose runner (agentic-codebase-writer task 2.4).

Task 2.4 (boundary: *AgenticProseRunner*, Req 3.4, 3.5, 5.2, 5.3, 6.1, 8.2) adds
:class:`docuharnessx.composition.agent.AgenticProseRunner`, which runs one bounded HarnessX
agent per planned segment: it builds the read-only repo harness (2.3), binds the run's
model, builds the scoped task (2.1), drives the real agentic loop so tool outputs become
model context, takes the final answer as the body, and runs it through the structure gate
(2.2). It returns a model-sourced :class:`~docuharnessx.composition.model.ProseResult` on an
accepted body or ``None`` on raise/timeout/empty/over-budget/rejected, alongside per-run
:class:`~docuharnessx.composition.agent.AgentRunStats` telemetry (steps, cost, exit reason,
accepted) that never carries the body, tool outputs, or transcript.

These tests drive the REAL run loop with the offline :class:`ScriptedAgentProvider` over the
crafted fixture repo (``tests/fixtures/agentic_repo``), so they need neither credentials nor
a network. The deterministic fallback paths use trivial stand-in providers.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from docuharnessx.composition.agent import AgentRunStats, AgenticProseRunner
from docuharnessx.composition.budgets import MIN_CITED_FILES
from docuharnessx.composition.model import (
    Chunk,
    CompositionBlueprint,
    EvidenceAnchor,
    ProseResult,
    SCQAOpener,
)
from docuharnessx.composition.structure_gate import validate_agent_body
from docuharnessx.ontology import Subject

from tests._fakes import SCRIPTED_AGENT_BODY, ScriptedAgentProvider

_FIXTURE_REPO = Path(__file__).parent / "fixtures" / "agentic_repo"
_PREFIXES = frozenset({"component", "tech", "artifact", "topic"})


def _subject(raw: str) -> Subject:
    return Subject.parse(raw, _PREFIXES)


def _blueprint() -> CompositionBlueprint:
    """A fully-populated blueprint whose evidence anchors name the fixture files."""
    key_message = "Start at the entry point; the engine loads config then runs one cycle."
    return CompositionBlueprint(
        segment_key="platform-dev__understand__abc123",
        roles=("platform-dev",),
        intent="understand",
        subjects=(_subject("component:app"),),
        title="How the application starts",
        scqa=SCQAOpener(
            situation="You are reading the application.",
            complication="The startup wiring is unclear.",
            question="How does the app start?",
            answer=key_message,
        ),
        key_message=key_message,
        chunks=(
            Chunk(heading="Entry point", points=("Application wires the engine.",)),
            Chunk(heading="Engine", points=("Engine.start loads config.",)),
        ),
        fast_path=("Read app.py.", "Follow into engine.py.", "Read config.py."),
        andragogy=True,
        evidence_anchors=(
            EvidenceAnchor(kind="entrypoint", detail="app.py", note="entrypoint"),
            EvidenceAnchor(kind="module", detail="engine.py", note="work engine"),
            EvidenceAnchor(kind="module", detail="config.py", note="configuration"),
        ),
        role_labels=("Platform Developer",),
        intent_label="Understand",
    )


def _rooted_copy(tmp_path: Path) -> str:
    """Copy the pristine fixture into *tmp_path* so the run can root there cleanly.

    ``Harness.run`` writes a ``harness_config.yaml`` runtime snapshot into the workspace
    root, so rooting at a throwaway copy keeps the committed fixture clean.
    """
    tmp_path.mkdir(parents=True, exist_ok=True)
    dest = tmp_path / "agentic_repo"
    shutil.copytree(_FIXTURE_REPO, dest)
    return str(dest)


# --------------------------------------------------------------------------- #
# AgentRunStats — frozen telemetry value object                                #
# --------------------------------------------------------------------------- #


def test_agent_run_stats_is_a_frozen_value_object() -> None:
    stats = AgentRunStats(steps=3, cost_usd=0.01, exit_reason="done", accepted=True)
    assert stats.steps == 3
    assert stats.cost_usd == 0.01
    assert stats.exit_reason == "done"
    assert stats.accepted is True
    # Frozen: assignment raises.
    with pytest.raises(Exception):
        stats.steps = 5  # type: ignore[misc]
    # Compares by value.
    assert stats == AgentRunStats(steps=3, cost_usd=0.01, exit_reason="done", accepted=True)


# --------------------------------------------------------------------------- #
# Happy path — accepted body yields a model-sourced ProseResult                #
# --------------------------------------------------------------------------- #


def test_accepted_body_yields_model_sourced_result(tmp_path: Path) -> None:
    runner = AgenticProseRunner()
    provider = ScriptedAgentProvider()
    result, stats = runner.run(_blueprint(), repo_path=_rooted_copy(tmp_path), model=provider)

    assert isinstance(result, ProseResult)
    # The body is the agent's final answer verbatim (Req 3.5, 4.5).
    assert result.body == SCRIPTED_AGENT_BODY
    # Provenance is "model" on an accepted body (Req 6.2).
    assert result.source == "model"
    # The summary is a non-empty, deterministic one-liner derived from the body.
    assert result.summary
    assert "\n" not in result.summary
    # The accepted body really clears the structure gate (Mermaid + citations).
    gate = validate_agent_body(result.body)
    assert gate.accepted

    # Telemetry: the scripted run exercised real steps, ended cleanly, and is accepted.
    assert isinstance(stats, AgentRunStats)
    assert stats.accepted is True
    assert stats.exit_reason == "done"
    assert stats.steps >= 1


def test_real_run_loop_drove_real_tools(tmp_path: Path) -> None:
    # The scripted provider counts its complete calls — one per step — so a non-trivial
    # step count proves the real run loop executed the scripted read/grep turns (Req 3.4).
    runner = AgenticProseRunner()
    provider = ScriptedAgentProvider()
    _result, stats = runner.run(_blueprint(), repo_path=_rooted_copy(tmp_path), model=provider)
    # Three scripted tool-call turns + the final end-turn body.
    assert provider.complete_calls == 4
    assert stats.steps >= 3


# --------------------------------------------------------------------------- #
# Telemetry never carries the body / tool outputs / transcript (Req 8.2)       #
# --------------------------------------------------------------------------- #


def test_telemetry_excludes_the_body(tmp_path: Path) -> None:
    runner = AgenticProseRunner()
    result, stats = runner.run(_blueprint(), repo_path=_rooted_copy(tmp_path), model=ScriptedAgentProvider())
    assert result is not None
    # AgentRunStats carries only scalars — no field equals or contains the body.
    import dataclasses

    for field in dataclasses.fields(stats):
        value = getattr(stats, field.name)
        assert isinstance(value, (int, float, str, bool))
        if isinstance(value, str):
            assert SCRIPTED_AGENT_BODY not in value
            assert "```mermaid" not in value


# --------------------------------------------------------------------------- #
# Fallback paths — no result, but telemetry is still returned (Req 6.1)        #
# --------------------------------------------------------------------------- #


class _RejectedBodyProvider:
    """A provider that ends the turn immediately with a body that fails the gate."""

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


class _EmptyBodyProvider:
    """A provider that ends the turn with an empty final answer."""

    async def complete(self, messages, tools, stream_callback=None):
        from harnessx.core.events import ModelResponseEvent

        return ModelResponseEvent(
            run_id="empty-run", step_id=0, content="", finish_reason="end_turn"
        )

    def count_tokens(self, messages) -> int:
        return 1


class _RaisingProvider:
    """A provider whose completion raises — the agent run must absorb it."""

    async def complete(self, messages, tools, stream_callback=None):
        raise RuntimeError("provider blew up")

    def count_tokens(self, messages) -> int:
        return 1


def test_rejected_body_yields_no_result_plus_telemetry(tmp_path: Path) -> None:
    runner = AgenticProseRunner()
    result, stats = runner.run(_blueprint(), repo_path=_rooted_copy(tmp_path), model=_RejectedBodyProvider())
    # A body failing the structure gate is unusable: no result, fallback follows (Req 6.1).
    assert result is None
    assert isinstance(stats, AgentRunStats)
    assert stats.accepted is False
    # The run still completed, so the exit reason is recorded.
    assert stats.exit_reason


def test_empty_body_yields_no_result_plus_telemetry(tmp_path: Path) -> None:
    runner = AgenticProseRunner()
    result, stats = runner.run(_blueprint(), repo_path=_rooted_copy(tmp_path), model=_EmptyBodyProvider())
    assert result is None
    assert stats.accepted is False


def test_raising_provider_is_absorbed(tmp_path: Path) -> None:
    runner = AgenticProseRunner()
    # Never raises: a provider exception becomes (None, stats) so the caller falls back.
    result, stats = runner.run(_blueprint(), repo_path=_rooted_copy(tmp_path), model=_RaisingProvider())
    assert result is None
    assert isinstance(stats, AgentRunStats)
    assert stats.accepted is False


def test_missing_repo_path_yields_no_result(tmp_path: Path) -> None:
    runner = AgenticProseRunner()
    missing = str(tmp_path / "does-not-exist")
    result, stats = runner.run(_blueprint(), repo_path=missing, model=ScriptedAgentProvider())
    # An invalid repo path cannot root a workspace: absorbed, no result (Req 2.6 driver).
    assert result is None
    assert stats.accepted is False


def test_none_model_yields_no_result(tmp_path: Path) -> None:
    runner = AgenticProseRunner()
    result, stats = runner.run(_blueprint(), repo_path=_rooted_copy(tmp_path), model=None)
    # No model bound: the run is not attempted (Req 5.4); the caller falls back.
    assert result is None
    assert stats.accepted is False


# --------------------------------------------------------------------------- #
# Bounded per segment — each run builds its own harness (Req 5.3)              #
# --------------------------------------------------------------------------- #


def test_each_run_is_independent_and_bounded(tmp_path: Path) -> None:
    runner = AgenticProseRunner()
    first, _ = runner.run(_blueprint(), repo_path=_rooted_copy(tmp_path / "a"), model=ScriptedAgentProvider())
    second, _ = runner.run(_blueprint(), repo_path=_rooted_copy(tmp_path / "b"), model=ScriptedAgentProvider())
    assert first is not None and second is not None
    # Deterministic: equal inputs and the same scripted provider yield the same body.
    assert first.body == second.body
