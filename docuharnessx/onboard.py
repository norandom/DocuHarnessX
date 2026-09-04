"""Post-init onboarding: hooks, CI workflow, and operator next steps.

``dhx init`` writes ontology + adoption, then calls :func:`install_onboarding`.
Hook/CI failures are reported and skipped so setup still succeeds.
"""

from __future__ import annotations

from docuharnessx.ci_install import CONSUMER_WORKFLOW_RELPATH, install_ci_workflow
from docuharnessx.hooks import install_git_hook, install_pre_commit_config

__all__ = ["ONBOARDING_NEXT_STEPS", "install_onboarding"]

ONBOARDING_NEXT_STEPS: tuple[str, ...] = (
    "dhx init: next: commit .docuharnessx/ontology.yaml "
    ".docuharnessx/adoption.yaml .pre-commit-config.yaml "
    f"{CONSUMER_WORKFLOW_RELPATH}  (never commit .env)",
    "dhx init: next: GitHub Actions Secret OPENAI_API_KEY "
    "(never a Variable); Variables OPENAI_API_BASE and "
    "OPENAI_DEFAULT_MAIN_MODEL (DeepSeek defaults if unset)",
    "dhx init: next: run 'pre-commit install' if you use the "
    "pre-commit framework (the git hook is already executable)",
)


def install_onboarding(project_dir: str) -> list[str]:
    """Install pre-commit config, git hook, and CI workflow. Never raises."""
    lines: list[str] = []

    try:
        path = install_pre_commit_config(project_dir)
        lines.append(f"dhx init: wrote pre-commit config: {path}")
    except FileExistsError as exc:
        lines.append(f"dhx init: skipped pre-commit config: {exc}")
    except OSError as exc:
        lines.append(f"dhx init: skipped pre-commit config: {exc}")

    try:
        path = install_git_hook(project_dir)
        lines.append(f"dhx init: wrote git hook: {path}")
    except FileNotFoundError:
        lines.append(
            "dhx init: skipped git hook: project is not a git checkout"
        )
    except FileExistsError as exc:
        lines.append(f"dhx init: skipped git hook: {exc}")
    except OSError as exc:
        lines.append(f"dhx init: skipped git hook: {exc}")

    try:
        path = install_ci_workflow(project_dir)
        lines.append(f"dhx init: wrote CI workflow: {path}")
    except FileExistsError:
        lines.append(
            f"dhx init: skipped CI workflow: {CONSUMER_WORKFLOW_RELPATH} "
            "already exists"
        )
    except OSError as exc:
        lines.append(f"dhx init: skipped CI workflow: {exc}")

    lines.extend(ONBOARDING_NEXT_STEPS)
    return lines
