"""Write-scoped setup harness that proposes ontology (task 2.5).

The workspace is jailed to ``<project>/.docuharnessx/``. The harness **returns**
a :class:`Vocabulary` proposal and does not commit ``ontology.yaml``.
"""

from __future__ import annotations

import asyncio
import os
import re
from typing import Any

import yaml
from harnessx.bundles.context import context, make_window_mgmt
from harnessx.bundles.control import make_control
from harnessx.core.config_schema import NullTracerConfig
from harnessx.core.harness import BaseTask, HarnessConfig
from harnessx.tools.builtin import build_default_tools
from harnessx.workspace.workspace import Workspace

from docuharnessx._ontology import Vocabulary, load_vocabulary
from docuharnessx.composition.budgets import (
    WRITER_LOOP_THRESHOLD,
    WRITER_MAX_COST_USD,
    WRITER_MAX_STEPS,
    WRITER_TOKEN_BUDGET,
    WRITER_TOKEN_THRESHOLD,
)

__all__ = ["SETUP_AGENT_ID", "build_setup_harness", "propose_ontology"]

SETUP_AGENT_ID = "docuharnessx-setup"
_JAIL_RELPATH = os.path.join(".docuharnessx")


def build_setup_harness(project_dir: str) -> HarnessConfig:
    """Build a model-free setup harness jailed to ``.docuharnessx/``."""
    if not project_dir or not os.path.isdir(project_dir):
        raise ValueError(
            f"build_setup_harness: project_dir {project_dir!r} must be a directory"
        )
    jail = os.path.join(project_dir, _JAIL_RELPATH)
    os.makedirs(jail, exist_ok=True)
    builder = (
        context
        | make_window_mgmt(token_threshold=WRITER_TOKEN_THRESHOLD)
        | make_control(
            loop_threshold=WRITER_LOOP_THRESHOLD,
            include_budget=False,
            max_cost_usd=WRITER_MAX_COST_USD,
        )
    )
    builder = builder.slot(
        tool_registry=build_default_tools(),
        workspace=Workspace(
            agent_id=SETUP_AGENT_ID,
            root=jail,
            mode="isolated",
        ),
        init_workspace=False,
        tracer=NullTracerConfig(),
    )
    return builder.build()


def propose_ontology(project_dir: str, *, model: Any) -> Vocabulary:
    """Run the setup harness and return a vocabulary proposal. Does not write YAML."""
    config = build_setup_harness(project_dir)
    task = BaseTask(
        description=(
            "Propose an ontology for this software project as YAML with keys "
            "roles, intents, and subjects. Each role and intent is a mapping "
            "with id, label, and description. subjects is a list of prefixes "
            "ending in a colon. Reply with YAML only."
        ),
        max_steps=WRITER_MAX_STEPS,
        token_budget=WRITER_TOKEN_BUDGET,
        max_cost_usd=WRITER_MAX_COST_USD,
    )
    body, _reason, _steps, _cost, _tokens = _run_bounded(model, config, task)
    return _parse_proposal(body)


def _parse_proposal(body: str) -> Vocabulary:
    text = body.strip()
    fenced = re.search(r"```(?:yaml|yml)?\n(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if fenced:
        text = fenced.group(1)
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ValueError(f"setup harness proposal is not YAML: {exc}") from exc
    try:
        return load_vocabulary(data)
    except Exception as exc:
        raise ValueError(f"setup harness proposal is not a valid vocabulary: {exc}") from exc


def _run_bounded(model: Any, config: Any, task: Any) -> tuple[str, str, int, float, int]:
    from harnessx.core.model_config import ModelConfig

    async def _drive() -> tuple[str, str, int, float, int]:
        harness = ModelConfig(main=model).agentic(config)
        try:
            result = await harness.run(task)
            end = result.task_end
            return (
                getattr(end, "final_output", "") or "",
                getattr(end, "exit_reason", "done") or "done",
                int(getattr(end, "total_steps", 0) or 0),
                float(getattr(end, "total_cost_usd", 0.0) or 0.0),
                int(getattr(end, "total_tokens", 0) or 0),
            )
        finally:
            try:
                await harness.cleanup()
            except Exception:  # pragma: no cover
                pass

    return asyncio.run(_drive())
