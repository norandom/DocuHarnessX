"""Install a consuming repo's GitHub Actions workflow that calls DocuHarnessX."""

from __future__ import annotations

from pathlib import Path

from docuharnessx.hooks import default_rev

__all__ = ["CONSUMER_WORKFLOW_RELPATH", "install_ci_workflow", "render_consumer_ci_workflow"]

CONSUMER_WORKFLOW_RELPATH = ".github/workflows/dhx.yml"


def render_consumer_ci_workflow(
    *,
    rev: str | None = None,
    evolve: str = "pr",
    default_branch: str = "main",
) -> str:
    """Thin caller workflow. Generation + optional evolve PR live in the reusable workflow."""
    pin = rev or default_rev()
    evolve_mode = evolve if evolve in {"off", "pr"} else "pr"
    # Keep this file hand-editable. The reusable workflow is the policy engine.
    return f"""name: DocuHarnessX
on:
  push:
    branches: [{default_branch}]
  workflow_dispatch: {{}}
permissions:
  contents: write
  pull-requests: write
jobs:
  adopt:
    uses: norandom/DocuHarnessX/.github/workflows/adopt.yml@{pin}
    secrets:
      OPENAI_API_KEY: ${{{{ secrets.OPENAI_API_KEY }}}}
    with:
      evolve: {evolve_mode}
      dhx_ref: {pin}
      openai_api_base: ${{{{ vars.OPENAI_API_BASE || 'https://api.deepseek.com' }}}}
      openai_default_main_model: ${{{{ vars.OPENAI_DEFAULT_MAIN_MODEL || 'deepseek-v4-flash' }}}}
"""


def install_ci_workflow(
    project_dir: str,
    *,
    rev: str | None = None,
    evolve: str = "pr",
    default_branch: str = "main",
    force: bool = False,
) -> str:
    """Write ``.github/workflows/dhx.yml``. Refuses to overwrite unless ``force``."""
    path = Path(project_dir) / CONSUMER_WORKFLOW_RELPATH
    if path.is_file() and not force:
        raise FileExistsError(
            f"{path} already exists; pass --force to overwrite"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        render_consumer_ci_workflow(
            rev=rev, evolve=evolve, default_branch=default_branch
        ),
        encoding="utf-8",
    )
    return str(path)
