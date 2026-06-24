"""Unit tests for the bounded writer-harness factory (task 2.3).

Task 2.3 (agentic-codebase-writer, boundary: *harness_factory*) adds
:func:`docuharnessx.composition.harness_factory.build_writer_harness`, which composes a
**model-free** :class:`harnessx.core.harness.HarnessConfig` from the context,
window-management, and bounded control bundles, with the default exploration tool set
(read/grep/glob/bash) and a :class:`harnessx.workspace.workspace.Workspace` rooted
**read-only** at the target repository (Req 3.1, 3.2, 3.6, 5.1; design "build_writer_harness",
lines 356-388).

Observable completion (tasks.md 2.3): the configuration offers the exploration tools, roots a
read-only workspace at the given repo path (a write attempt against the workspace is blocked),
enables the bounded control budget, carries no model, and wires no embedding/vector
index/retrieval store — repository context is obtained agentically through the tools only.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from harnessx.core.harness import HarnessConfig
from harnessx.workspace.workspace import Workspace, WorkspaceWriteError

from docuharnessx.composition.budgets import (
    WRITER_LOOP_THRESHOLD,
    WRITER_MAX_COST_USD,
    WRITER_TOKEN_THRESHOLD,
)
from docuharnessx.composition.harness_factory import build_writer_harness


# --------------------------------------------------------------------------- #
# Fixtures                                                                     #
# --------------------------------------------------------------------------- #


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    """A throwaway directory standing in for the target repository."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("print('hello')\n", encoding="utf-8")
    return tmp_path


# --------------------------------------------------------------------------- #
# Tool surface (Req 3.1)                                                        #
# --------------------------------------------------------------------------- #


def test_offers_the_builtin_exploration_tools(repo: Path) -> None:
    config = build_writer_harness(str(repo))
    assert isinstance(config, HarnessConfig)
    registry = config.tool_registry
    assert registry is not None
    names = {n.lower() for n in registry.list_names()}
    # The four exploration tools the design names (Req 3.1).
    for required in ("read", "grep", "glob", "bash"):
        assert required in names, f"missing exploration tool {required!r}; have {sorted(names)}"


# --------------------------------------------------------------------------- #
# Read-only workspace rooted at the repo (Req 3.2)                              #
# --------------------------------------------------------------------------- #


def test_roots_a_readonly_workspace_at_the_repo(repo: Path) -> None:
    config = build_writer_harness(str(repo))
    ws = config.workspace
    assert ws is not None
    # HarnessConfig.__post_init__ normalizes the runtime Workspace to a WorkspaceConfig,
    # preserving root + mode.
    assert ws.mode == "readonly"
    assert Path(ws.root).resolve() == repo.resolve()


def test_a_write_attempt_against_the_workspace_is_blocked(repo: Path) -> None:
    config = build_writer_harness(str(repo))
    ws = config.workspace
    # Reconstruct a live Workspace from the persisted descriptor and confirm a write is jailed.
    live = Workspace(agent_id=ws.agent_id, root=Path(ws.root), mode=ws.mode)
    with pytest.raises(WorkspaceWriteError):
        live.check_write()


# --------------------------------------------------------------------------- #
# Bounded control budget (Req 5.1)                                             #
# --------------------------------------------------------------------------- #


def _processor_targets(config: HarnessConfig) -> list[str]:
    """All processor _target_ paths, from both serialized dicts and runtime instances."""
    targets: list[str] = []
    for proc in config.processors:
        if isinstance(proc, dict):
            targets.append(proc.get("_target_", ""))
        else:
            targets.append(f"{type(proc).__module__}.{type(proc).__qualname__}")
    for proc in getattr(config, "_rt_procs", []) or []:
        targets.append(f"{type(proc).__module__}.{type(proc).__qualname__}")
    return targets


def test_enables_the_bounded_control_budget(repo: Path) -> None:
    config = build_writer_harness(str(repo))
    targets = _processor_targets(config)
    blob = "\n".join(targets)
    # Cost guard (max_cost_usd) + loop detection are the bounded-run guards (Req 5.1).
    assert "CostGuardProcessor" in blob, f"no cost guard; have {targets}"
    assert "LoopDetectionProcessor" in blob, f"no loop detection; have {targets}"
    # Window management (compaction) keeps the context bounded (Req 5.1).
    assert "CompactionProcessor" in blob, f"no compaction; have {targets}"


def test_threshold_overrides_are_accepted(repo: Path) -> None:
    # Non-default bounds must build without conflict.
    config = build_writer_harness(
        str(repo),
        loop_threshold=WRITER_LOOP_THRESHOLD + 1,
        max_cost_usd=WRITER_MAX_COST_USD + 0.1,
        token_threshold=WRITER_TOKEN_THRESHOLD + 1000,
    )
    assert isinstance(config, HarnessConfig)


# --------------------------------------------------------------------------- #
# Model-free + no RAG/embedding/retrieval (Req 3.6, steering)                   #
# --------------------------------------------------------------------------- #


def test_carries_no_model(repo: Path) -> None:
    config = build_writer_harness(str(repo))
    # HarnessConfig is a behaviour-only pipeline with no model field at all.
    field_names = {f.name for f in dataclasses.fields(config)}
    assert "model" not in field_names and "model_config" not in field_names
    # And the builder never stashed a model_config on it.
    assert getattr(config, "model_config", None) is None
    assert getattr(config, "_model_config", None) is None


def test_wires_no_embedding_vector_index_or_retrieval_store(repo: Path) -> None:
    config = build_writer_harness(str(repo))
    blob = "\n".join(_processor_targets(config)).lower()
    # Repository context is obtained agentically through the tools only (Req 3.6).
    for forbidden in ("memory", "retrieval", "embedding", "vector", "rag"):
        assert forbidden not in blob, f"unexpected {forbidden!r} component wired: {blob}"


# --------------------------------------------------------------------------- #
# Missing / invalid repo path                                                  #
# --------------------------------------------------------------------------- #


def test_missing_repo_path_is_rejected(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist"
    with pytest.raises(ValueError):
        build_writer_harness(str(missing))


def test_repo_path_that_is_a_file_is_rejected(tmp_path: Path) -> None:
    a_file = tmp_path / "f.txt"
    a_file.write_text("x", encoding="utf-8")
    with pytest.raises(ValueError):
        build_writer_harness(str(a_file))


# --------------------------------------------------------------------------- #
# Centralized harnessx imports + determinism                                   #
# --------------------------------------------------------------------------- #


def test_repeated_builds_are_independent(repo: Path) -> None:
    # Each call must yield a fresh config (one bounded Harness per segment, Req 5.3),
    # not a shared mutable singleton.
    a = build_writer_harness(str(repo))
    b = build_writer_harness(str(repo))
    assert a is not b
    assert a.tool_registry is not b.tool_registry
