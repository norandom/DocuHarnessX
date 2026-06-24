"""The bounded writer-harness factory (agentic-codebase-writer task 2.3).

``docuharnessx.composition.harness_factory`` owns the *harness_factory* boundary of the
Wave 2.5 ``agentic-codebase-writer``: :func:`build_writer_harness` composes the
**model-free** :class:`harnessx.core.harness.HarnessConfig` the per-segment writer agent
runs against — the *behaviour* pipeline (which processors run) plus the exploration tools
and the read-only repository workspace, but never the model (design "build_writer_harness",
lines 356-388; Req 3.1, 3.2, 3.6, 5.1).

This module is the **single place** the agentic writer touches the HarnessX configuration
APIs (the design's "Centralize harnessx imports here" directive): the context, window-
management, and bounded-control bundles, the default exploration tool registry, and the
:class:`~harnessx.workspace.workspace.Workspace`. The downstream
:class:`~docuharnessx.composition.agent.AgenticProseRunner` (task 2.4) binds the model onto
the returned config via ``ModelConfig(main=...).agentic(config)`` and runs the bounded
:class:`~harnessx.core.harness.BaseTask`; it imports the config builder from here rather than
reaching into HarnessX itself.

**What the config wires (and what it deliberately does not):**

* **Tools (Req 3.1).** ``build_default_tools()`` registers the built-in read/grep/glob/bash
  exploration tools (alongside the rest of the default set), all sandbox-aware so they route
  through the workspace jail at run time. The agent reads *real* source through these tools.
* **Read-only workspace (Req 3.2).** A ``Workspace(agent_id="docuharnessx-writer",
  root=repo_path, home=<throwaway>, mode="readonly")`` roots the agent's file-system view at
  the target repository and jails it: ``mode="readonly"`` makes any write/edit raise
  :class:`~harnessx.workspace.workspace.WorkspaceWriteError`, so the agent reads the source
  but cannot modify the target repository. The target repository also stays **pristine** at
  the run level: ``Harness.run`` would otherwise write a ``harness_config.yaml``
  reproducibility snapshot into the workspace root (the repo); the throwaway ``home`` diverts
  that snapshot to ``home/workspaces/<agent_id>`` and ``init_workspace=False`` skips the
  workspace-initializer write, so nothing is ever written under ``repo_path`` — keeping a
  re-analysis of the same repo (and therefore the deterministic plan) byte-stable.
* **Bounded control (Req 5.1).** ``make_control`` adds the reliability processors (including
  loop detection at :data:`WRITER_LOOP_THRESHOLD` so a repeating tool-call pattern halts) and
  a ``CostGuardProcessor`` at ``max_cost_usd``; ``make_window_mgmt`` adds context compaction
  at :data:`WRITER_TOKEN_THRESHOLD` so the running context stays bounded. Together with the
  per-run ``BaseTask`` caps the runner sets (steps/cost/token), one segment's run cannot run
  away in cost, steps, or context (Req 5.1, 5.3).
* **No model (steering rule).** :class:`~harnessx.core.harness.HarnessConfig` is a behaviour-
  only pipeline and carries no model field; the caller binds the runtime model separately.
* **No RAG / embedding / vector index (Req 3.6).** Nothing here wires a memory backend,
  retrieval processor, embedding model, or vector store — repository context is obtained
  agentically through the exploration tools only.

The bundles are composed with ``|`` and the scalar slots set with ``.slot(...)``, mirroring
the steering "compose with ``|``; append, do not replace" rule. ``include_budget`` is left
*off* in ``make_control`` because the window-management bundle is composed in separately; the
two paths register the same singleton processors (compaction, tool-failure guard), so enabling
both would raise a :class:`~harnessx.core.builder.HarnessConflictError` on merge.
"""

from __future__ import annotations

# Centralized HarnessX configuration imports (design directive): the bundles, the default
# tool registry, the workspace, and the config type the agentic writer composes.
from harnessx.bundles.context import context, make_window_mgmt
from harnessx.bundles.control import make_control
from harnessx.core.config_schema import NullTracerConfig
from harnessx.core.harness import HarnessConfig
from harnessx.tools.builtin import build_default_tools
from harnessx.workspace.workspace import Workspace

from docuharnessx.composition.budgets import (
    WRITER_LOOP_THRESHOLD,
    WRITER_MAX_COST_USD,
    WRITER_TOKEN_THRESHOLD,
)

import atexit
import os
import shutil
import tempfile

__all__ = ["build_writer_harness", "WRITER_AGENT_ID"]


#: The stable workspace ``agent_id`` for the writer agent. A fixed, filesystem-safe label
#: (the workspace validator allows only letters/digits/``-``/``_``/``.``); it identifies the
#: writer's read-only view of the target repository and never derives from project vocabulary.
WRITER_AGENT_ID: str = "docuharnessx-writer"


#: Process-wide throwaway snapshot home, created lazily once and reused across segments.
_SNAPSHOT_HOME: str | None = None


def _snapshot_home() -> str:
    """Return the process-wide throwaway ``home`` for the writer agent's workspace.

    ``Harness.run`` writes a ``harness_config.yaml`` reproducibility snapshot into the
    workspace ``home``; we divert that ``home`` to a throwaway temp directory (away from the
    read-only target repo) so the repo stays pristine. Because the writer agent uses a fixed
    :data:`WRITER_AGENT_ID` and the Write stage composes segments **sequentially**, a single
    reused home is race-free and keeps the temp footprint at exactly one directory for the
    whole process — no per-segment accumulation. The directory is removed at interpreter exit.
    """
    global _SNAPSHOT_HOME
    if _SNAPSHOT_HOME is None:
        _SNAPSHOT_HOME = tempfile.mkdtemp(prefix="docuharnessx-writer-")
        atexit.register(shutil.rmtree, _SNAPSHOT_HOME, ignore_errors=True)
    return _SNAPSHOT_HOME


def build_writer_harness(
    repo_path: str,
    *,
    loop_threshold: int = WRITER_LOOP_THRESHOLD,
    max_cost_usd: float = WRITER_MAX_COST_USD,
    token_threshold: int = WRITER_TOKEN_THRESHOLD,
) -> HarnessConfig:
    """Build the bounded, model-free :class:`HarnessConfig` for the writer agent.

    Composes the context, window-management, and bounded-control bundles, slots in the
    default exploration tool registry and a read-only :class:`Workspace` rooted at
    ``repo_path``, and returns the resulting :class:`HarnessConfig`. The model is **not**
    embedded (steering rule); the caller binds it via ``ModelConfig(main=...).agentic(config)``
    (design "build_writer_harness").

    Args:
        repo_path: The target-repository path. Must resolve to an existing directory; the
            agent's read-only workspace is rooted here (Req 3.2).
        loop_threshold: Identical-fingerprint count before the loop-detection processor halts
            the run; defaults to :data:`WRITER_LOOP_THRESHOLD` (Req 5.1).
        max_cost_usd: US-dollar ceiling the ``CostGuardProcessor`` enforces on the run;
            defaults to :data:`WRITER_MAX_COST_USD` (Req 5.1).
        token_threshold: Token count above which the context-compaction processor fires,
            keeping the working context bounded; defaults to :data:`WRITER_TOKEN_THRESHOLD`
            (Req 5.1).

    Returns:
        A fresh, model-free :class:`HarnessConfig` whose ``tool_registry`` offers the built-in
        read/grep/glob/bash exploration tools, whose ``workspace`` is a read-only descriptor
        rooted at ``repo_path``, and whose processor pipeline carries the bounded control
        budget (loop detection + cost guard + context compaction). Each call returns an
        independent config (one bounded Harness per segment; Req 5.3).

    Raises:
        ValueError: ``repo_path`` does not resolve to an existing directory (precondition).

    Invariants: never embeds a model; never enables a write tool against the real repo (the
    read-only workspace enforces this); never wires any embedding/vector/retrieval store
    (Req 3.6).
    """
    if not repo_path or not os.path.isdir(repo_path):
        raise ValueError(
            f"build_writer_harness: repo_path {repo_path!r} must resolve to an existing "
            "directory; the writer agent's read-only workspace roots there."
        )

    # Compose the behaviour pipeline with `|` (steering: compose, don't replace).
    #   * context           — system-prompt + user-wrapper assembly.
    #   * window management  — context compaction (token_threshold) + tool-failure guard.
    #   * bounded control    — reliability (incl. loop detection at loop_threshold) + cost
    #                          guard at max_cost_usd. include_budget stays False so window
    #                          management is wired exactly once (avoids a singleton conflict).
    builder = (
        context
        | make_window_mgmt(token_threshold=token_threshold)
        | make_control(
            loop_threshold=loop_threshold,
            include_budget=False,
            max_cost_usd=max_cost_usd,
        )
    )

    # Slot the exploration tools and the read-only repo workspace. The workspace jails the
    # agent at repo_path and blocks writes (mode="readonly"); the default tool set is
    # sandbox-aware so reads route through that jail at run time.
    #
    # The target repository must stay PRISTINE: the agent reads it read-only and may never
    # mutate it (Req 3.2). ``Harness.run`` would otherwise write a ``harness_config.yaml``
    # reproducibility snapshot into the workspace root — i.e. straight into the target repo —
    # which both violates the read-only guarantee and perturbs a re-analysis of that repo
    # (a stray file shifts the file inventory and the deterministic plan). Giving the
    # workspace a throwaway ``home`` diverts that snapshot to ``home/workspaces/<agent_id>``
    # instead of ``root``, and ``init_workspace=False`` skips the workspace-initializer write,
    # so nothing is ever written under ``repo_path``. The ``root`` still pins the agent's
    # read-only file-system view at the target repository. The throwaway home is a single
    # process-wide directory (reused across sequential segments, removed at exit) so the temp
    # footprint stays at one directory rather than accumulating one per segment.
    snapshot_home = _snapshot_home()
    builder = builder.slot(
        tool_registry=build_default_tools(),
        workspace=Workspace(
            agent_id=WRITER_AGENT_ID,
            root=repo_path,
            home=snapshot_home,
            mode="readonly",
        ),
        init_workspace=False,
        # The per-segment agentic run is a transient exploration loop, not a journaled run:
        # its bounded telemetry is carried by AgentRunStats and folded into the pipeline's own
        # journal by the Write stage. A NullTracer keeps the run from writing a ``sessions/``
        # trace directory into the workspace root (the target repo), so the repo stays pristine
        # (Req 3.2) and a re-analysis of it stays byte-stable.
        tracer=NullTracerConfig(),
    )

    # build() produces the model-free HarnessConfig; the caller binds the model separately.
    return builder.build()
