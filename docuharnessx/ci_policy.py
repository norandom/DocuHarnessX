"""CI and hook policy: when to generate docs, when to evolve, how to break loops.

Designed for repositories where coding agents also commit. Generation and
evolution are separate planes:

* A **docs bot** may update living pages / MkDocs after a source commit.
* **Harness evolution** never lands on the same branch as an agent code
  commit; it opens a PR, and only from operator-kept journals.

Loop breakers: skip when the commit message contains ``[dhx]``, skip evolve
when a ``dhx/evolve`` PR is already open, and never run evolve from a hook.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

__all__ = [
    "BOT_MARK",
    "DOC_PATH_PREFIXES",
    "SOURCE_SUFFIXES",
    "HookDecision",
    "EvolveDecision",
    "has_model_credentials",
    "is_bot_commit",
    "should_run_hook",
    "should_evolve_in_ci",
]

BOT_MARK = "[dhx]"
EVOLVE_BRANCH = "dhx/evolve"

#: Paths the hook itself may restage. Commits that only touch these must not
#: re-enter generation (local hook loop and CI bot loop).
DOC_PATH_PREFIXES: tuple[str, ...] = (
    "docs/",
    "docs\\",
    ".docuharnessx/pages/",
    ".docuharnessx\\pages\\",
    ".docuharnessx/journals/",
    ".docuharnessx/harnesses/",
    ".docuharnessx/out/",
    "mkdocs.yml",
    ".github/workflows/docs.yml",
    ".github/workflows/dhx.yml",
)

SOURCE_SUFFIXES: frozenset[str] = frozenset(
    {
        ".py",
        ".go",
        ".rs",
        ".ts",
        ".tsx",
        ".js",
        ".jsx",
        ".java",
        ".kt",
        ".c",
        ".h",
        ".cc",
        ".cpp",
        ".cs",
        ".rb",
        ".php",
        ".swift",
        ".toml",
        ".gradle",
        ".mod",
        ".sum",
    }
)


@dataclass(frozen=True)
class HookDecision:
    run: bool
    reason: str


@dataclass(frozen=True)
class EvolveDecision:
    run: bool
    reason: str


def has_model_credentials(environ: Mapping[str, str]) -> bool:
    """True when an API key is present for an OpenAI-compatible (or other) provider."""
    return bool(
        environ.get("OPENAI_API_KEY")
        or environ.get("ANTHROPIC_API_KEY")
        or environ.get("LITELLM_API_KEY")
    )


def is_bot_commit(commit_message: str, actor: str = "") -> bool:
    """True when this commit was produced by DocuHarnessX CI/hook restaging."""
    message = commit_message or ""
    if BOT_MARK in message:
        return True
    actor_l = actor.lower()
    return actor_l in {"github-actions[bot]", "docuharnessx-bot"}


def _is_doc_path(path: str) -> bool:
    normalized = path.replace("\\", "/").lstrip("./")
    if normalized in {"mkdocs.yml", ".github/workflows/docs.yml", ".github/workflows/dhx.yml"}:
        return True
    return any(normalized.startswith(prefix.replace("\\", "/")) for prefix in DOC_PATH_PREFIXES)


def _is_source_path(path: str) -> bool:
    if _is_doc_path(path):
        return False
    name = path.replace("\\", "/").rsplit("/", 1)[-1]
    if "." not in name:
        return False
    suffix = "." + name.rsplit(".", 1)[-1].lower()
    return suffix in SOURCE_SUFFIXES


def should_run_hook(
    staged_paths: Sequence[str],
    *,
    environ: Mapping[str, str],
    commit_message: str = "",
    actor: str = "",
) -> HookDecision:
    """Decide whether a pre-commit / CI generate step should run."""
    if is_bot_commit(commit_message, actor):
        return HookDecision(False, "skip: bot or [dhx] commit")
    if not has_model_credentials(environ):
        return HookDecision(False, "skip: no API key (hook is fail-open)")
    paths = [p for p in staged_paths if p]
    if not paths:
        return HookDecision(False, "skip: no staged files")
    if paths and all(_is_doc_path(p) for p in paths):
        return HookDecision(False, "skip: docs-only change")
    if not any(_is_source_path(p) for p in paths):
        return HookDecision(False, "skip: no source files staged")
    return HookDecision(True, "run: source change with credentials")


def should_evolve_in_ci(
    *,
    evolve_mode: str,
    journals_changed: bool,
    actor: str = "",
    commit_message: str = "",
    evolve_pr_open: bool = False,
) -> EvolveDecision:
    """Decide whether CI may propose a harness snapshot.

    Evolution is never in-place on an agent branch. ``evolve_mode`` is
    ``off`` or ``pr``. Journals must have changed (operator-kept traces),
    and an existing ``dhx/evolve`` PR blocks another run.
    """
    mode = (evolve_mode or "off").strip().lower()
    if mode in {"off", "false", "0", "no"}:
        return EvolveDecision(False, "skip: evolve mode is off")
    if mode not in {"pr", "on", "true", "yes"}:
        return EvolveDecision(False, f"skip: unknown evolve mode {evolve_mode!r}")
    if is_bot_commit(commit_message, actor):
        return EvolveDecision(False, "skip: bot or [dhx] commit")
    if evolve_pr_open:
        return EvolveDecision(False, "skip: evolve PR already open")
    if not journals_changed:
        return EvolveDecision(
            False,
            "skip: journals did not change (do not evolve from agent code commits)",
        )
    return EvolveDecision(True, "run: open evolve PR from journals")
