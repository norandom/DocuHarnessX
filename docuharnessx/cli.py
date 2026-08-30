"""The ``dhx`` command-line entry point.

This module is the **dhx CLI** boundary. ``dhx --help`` works. ``run`` validates
the target, optionally resolves a writer model, and drives
:func:`docuharnessx.pipeline.run.run_pipeline`. ``init`` scaffolds ontology.
``mcp`` launches the refine server.

What the ``run`` path does (in order)
-------------------------------------
1. **Validate the target** is an existing directory *before any run*
   (:class:`TargetRepoError`, mapped to a non-zero exit). An invalid target
   writes no documentation pages (Req 1.2).
2. **Load config** (``--config`` YAML overlaid with CLI overrides). Ontology may
   still load for config/role validation; it is not a write prerequisite and
   reader-role selection is not required (Req 1.4, 10.3).
3. **Resolve the model** via :func:`docuharnessx.model_resolver.resolve_model`
   when none is injected. Absence is an honest-empty run (zero pages + report),
   not a hard resolution failure and not outline substitution (Req 1.3).
4. **Run the explore-first pipeline** — not a dummy ``BaseTask`` that replies
   ``DONE`` and forbids tools.

What the ``run`` orchestration does
-----------------------------------
:func:`orchestrate_run` calls ``run_pipeline`` (imported under an alias so it
does not smash this module's :class:`RunOutcome`). Completed runs including
honest-empty exit 0. Invalid target exits non-zero. Optional publish modes are
offered only after at least one accepted page (Req 8.5).

Test-injected model
-------------------
:func:`prepare_run` / :func:`main` accept an optional ``model_config`` keyword.
Production callers pass nothing. Tests inject ``None`` (no-model) or a
``ModelConfig`` wrapping a no-network fake / inspecting provider.

Error strategy
-------------
Every boundary failure raises a typed :class:`DocuHarnessXError`; :func:`main`
catches the whole family, prints ``<ErrorType>: <message>`` to stderr, and returns
a non-zero exit code. The required-dependency check still runs before any real
command is dispatched.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from docuharnessx.config import DocgenConfig, load_config
from docuharnessx.errors import DocuHarnessXError, ModelResolutionError, TargetRepoError
from docuharnessx.ontology_loader import (
    ONTOLOGY_CONFIG_RELPATH,
    load_project_vocabulary,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from harnessx.core.harness import Harness
    from harnessx.core.model_config import ModelConfig

    from docuharnessx._ontology import Vocabulary
    from docuharnessx.context import RunContext

__all__ = [
    "build_parser",
    "main",
    "prepare_run",
    "PreparedRun",
    "orchestrate_run",
    "RunOutcome",
    "exit_code_for_reason",
    "resolve_session",
]

#: Process exit code on a refused/failed ``dhx init`` (existing file without
#: ``--force``, or nothing to build). Non-zero so callers/CI can detect refusal
#: (Req 9.6). Reuses the single non-zero failure contract of the CLI.
EXIT_INIT_FAILED: int = 1

_PROG = "dhx"
_DESCRIPTION = (
    "DocuHarnessX: human-centric, role-based documentation generator built on "
    "HarnessX."
)

#: The recognised subcommand names. The bare CLI form
#: ``dhx <target-repo> --out DIR --config YAML`` (Req 4.1, 4.8) is supported by
#: defaulting to ``run`` when the first positional token is NOT one of these — so a
#: target path is accepted directly without an explicit ``run`` subcommand, while
#: ``dhx init``, ``dhx run`` (and ``dhx mcp``) keep working. ``mcp`` is listed here so
#: the bare-form normaliser leaves ``dhx mcp <repo>`` intact rather than rewriting it to
#: ``run mcp <repo>`` (mcp-refine Req 1.3).
_SUBCOMMANDS: frozenset[str] = frozenset({"run", "init", "mcp"})

_log = logging.getLogger(__name__)


def _normalize_argv(argv: Sequence[str] | None) -> list[str] | None:
    """Insert the implicit ``run`` subcommand for the bare CLI form (Req 4.1, 4.8).

    The spec mandates the bare invocation ``dhx <target-repo> --out DIR --config YAML``
    (literal acceptance: ``dhx /home/mc/Source/malware_hashes --out /tmp/out``), so a
    leading target path must route to the run pipeline *without* an explicit ``run``
    token. This prepends ``run`` when the first command-line token is a positional
    that is not a known subcommand, leaving every other form untouched:

    * ``dhx run ...`` / ``dhx init ...`` — first token is a subcommand → unchanged.
    * ``dhx`` (no args) / ``dhx -h`` / ``dhx --help`` — no positional first token →
      unchanged (argparse prints help / the no-command path runs).
    * ``dhx <path> --out DIR`` — first token is a positional non-subcommand →
      becomes ``run <path> --out DIR``.

    Returns the (possibly rewritten) argument list, or ``None`` when *argv* is
    ``None`` so the caller's ``None`` default (``sys.argv[1:]``) is preserved.
    """
    if argv is None:
        return None
    args = list(argv)
    if not args:
        return args
    first = args[0]
    # A leading flag (e.g. -h/--help) or an explicit subcommand is left as-is.
    if first.startswith("-") or first in _SUBCOMMANDS:
        return args
    # First token is a positional that is not a subcommand → it is the target repo
    # of the implicit bare run form. Prepend the implicit ``run`` subcommand.
    return ["run", *args]


def _require_harnessx() -> None:
    """Fail with an explicit, dependency-naming error if HarnessX is missing.

    Implements Requirement 1.4 at the CLI boundary: rather than failing silently
    (or with an opaque ImportError deep in the bundle), raise the typed
    :class:`~docuharnessx.errors.DependencyError` naming the missing runtime
    dependency and how to install it. ``DependencyError`` is a
    :class:`~docuharnessx.errors.DocuHarnessXError`, so :func:`main` maps it to the
    standard non-zero CLI exit. Import is deferred to call time so that
    ``dhx --help`` and unit tests of the parser do not require HarnessX.
    """
    try:
        import harnessx  # noqa: F401
    except ImportError as exc:  # pragma: no cover - exercised when dep absent
        from docuharnessx.errors import DependencyError

        raise DependencyError(
            "DocuHarnessX requires the 'harnessx' runtime dependency, which is "
            "not importable. Install it with "
            "'uv pip install \"harnessx @ git+https://github.com/Darwin-Agent/HarnessX.git\"' "
            "(or 'pip install -e .')."
        ) from exc


def build_parser() -> argparse.ArgumentParser:
    """Build the ``dhx`` argument parser.

    The parser exposes two subcommands:

    * ``run`` — run the documentation pipeline against a target repository
      (parsing/validation/binding here in task 4.1; orchestration in 4.2).
    * ``init`` — scaffold the project ontology file (dispatched via
      :func:`_init_command` to ``ontology_setup.run_init``).

    The spec's bare invocation form ``dhx <target-repo> --out DIR --config YAML``
    (Req 4.1, 4.8) is supported by :func:`_normalize_argv`, which prepends the
    implicit ``run`` subcommand when the first token is a target path rather than a
    known subcommand — so the parser itself only ever sees the subcommand forms.
    """
    parser = argparse.ArgumentParser(prog=_PROG, description=_DESCRIPTION)
    subparsers = parser.add_subparsers(dest="command", metavar="<command>")

    # run subcommand.
    run = subparsers.add_parser(
        "run",
        help="Run the documentation pipeline against a target repository.",
    )
    run.add_argument(
        "target_repo",
        nargs="?",
        metavar="<target-repo>",
        help="Path to the target repository to document.",
    )
    run.add_argument(
        "--out",
        metavar="DIR",
        help="Output directory for generated docs and the run journal.",
    )
    run.add_argument(
        "--config",
        metavar="YAML",
        help="Path to a YAML configuration file.",
    )
    run.add_argument(
        "--roles",
        metavar="ROLES",
        help="Comma-separated subset of roles to generate for.",
    )
    # github-pages-deploy task 4.3 (append-only): the Deploy-stage publish mode.
    # Omitted (default None) → the config surface applies the emit-ci-workflow
    # default (Req 3.2); a supplied value is carried through and validated at the
    # stage boundary by the deploy-mode resolver (Req 3.3, 3.4).
    run.add_argument(
        "--deploy-mode",
        dest="deploy_mode",
        metavar="MODE",
        default=None,
        help=(
            "How the Deploy stage publishes the assembled site: 'emit-ci-workflow' "
            "(default — write mkdocs.yml + docs/ + a Pages workflow into the target "
            "tree, no push), 'gh-deploy' (push the built site to the target gh-pages "
            "branch), or 'build-only' (build the static site, no publish)."
        ),
    )
    run.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help=(
            "Show detailed run logs (HarnessX pipeline events and LiteLLM model "
            "calls). Off by default: only warnings, errors, and the run summary "
            "are printed."
        ),
    )

    # init subcommand (dispatched in task 4.3).
    init = subparsers.add_parser(
        "init",
        help="Scaffold the project's .docuharnessx/ontology.yaml.",
    )
    init.add_argument(
        "project_dir",
        nargs="?",
        default=".",
        metavar="[project-dir]",
        help="Project directory to initialize (default: current directory).",
    )
    init.add_argument(
        "--default",
        action="store_true",
        help="Seed the default ontology profile instead of prompting.",
    )
    init.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing ontology file.",
    )
    init.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Show detailed logs (off by default).",
    )

    # mcp subcommand (mcp-refine task 5.2): launch the stdio refine MCP server rooted
    # at a target repo + output dir. The argument surface mirrors ``run``
    # (``target_repo`` / ``--out`` / ``--config`` / ``-v``) so an author refines exactly
    # the docs a prior ``dhx run`` produced under the same ``<out>`` (Req 2.1). The
    # target is an optional positional (validated by ``_mcp_command`` before launch,
    # exactly as ``run`` validates its target; Req 2.2), so a missing target surfaces a
    # ``TargetRepoError`` rather than an argparse usage error.
    mcp = subparsers.add_parser(
        "mcp",
        help=(
            "Launch the stdio MCP refine server for a target repository's generated "
            "docs (refine segments/overview interactively in an MCP client)."
        ),
    )
    mcp.add_argument(
        "target_repo",
        nargs="?",
        metavar="<target-repo>",
        help="Path to the target repository whose generated docs to refine.",
    )
    mcp.add_argument(
        "--out",
        metavar="DIR",
        help=(
            "Output directory the prior run wrote (segments + site). Defaults to the "
            "documented per-target path when omitted (same as 'dhx run')."
        ),
    )
    mcp.add_argument(
        "--config",
        metavar="YAML",
        help="Path to a YAML configuration file (model selection, budgets).",
    )
    mcp.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help=(
            "Show detailed server logs on stderr (off by default). stdout always "
            "stays the MCP protocol channel."
        ),
    )

    return parser


@dataclass(frozen=True)
class PreparedRun:
    """The product of :func:`prepare_run`: validated inputs plus optional model.

    The documentation run no longer binds ``ModelConfig.agentic(make_docgen())``.
    ``model`` is the writer provider, or ``None`` for a no-model honest-empty run.

    Attributes:
        config: The validated :class:`DocgenConfig`.
        vocabulary: The loaded project ``Vocabulary`` (default profile when absent).
        used_default: ``True`` when the default profile was used (no ontology file).
        target_repo: The validated absolute target-repository path.
        out_dir: The resolved output directory (report and optional site root).
        model: Writer provider (``ModelConfig.main``) or ``None`` when unresolved.
    """

    config: DocgenConfig
    vocabulary: "Vocabulary"
    used_default: bool
    target_repo: str
    out_dir: str
    model: object | None


@dataclass(frozen=True)
class RunOutcome:
    """The product of :func:`orchestrate_run`: the run's result and exit mapping.

    Honest-empty (zero accepted pages) is ``exit_code=0``. ``journal_path`` and
    ``run_context`` remain on the type for older callers; they are ``None`` on
    the explore-first path (the dummy outer harness is no longer the run).
    """

    exit_reason: str
    exit_code: int
    journal_path: str | None
    out_dir: str
    run_context: "RunContext | None" = None


#: The output directory used when ``--out`` is omitted (documented default).
#: Resolved relative to the target repo so a run is self-contained there.
_DEFAULT_OUT_RELPATH = os.path.join(".docuharnessx", "out")


def _env_int_default(name: str, default: int) -> int:
    """Positive integer from environment variable *name*, else *default*."""
    raw = os.environ.get(name, "").strip()
    if raw.isdigit() and int(raw) > 0:
        return int(raw)
    return default


#: The single user turn that drives the pipeline. The eight stages do all the work as
#: processors firing on ``on_step_end``, so the model itself must do **nothing** and end its
#: turn immediately: every extra model step re-fires the whole expensive pipeline (the
#: agentic writer + the per-segment judges run again) and risks ``budget_exceeded`` before a
#: clean ``done``. The instruction is therefore explicit — take no action, call no tools,
#: answer in one word — so an agentic model does not treat "drive the pipeline" as a task and
#: rabbit-hole on the ``todo_write`` tool the Control bundle exposes.
_SKELETON_TASK_DESCRIPTION = (
    "DocuHarnessX runs its entire documentation pipeline automatically through background "
    "processors that execute the moment this turn ends. You do not need to do anything, and "
    "you must NOT call any tools or write any todos. Reply with exactly the single word "
    "DONE and nothing else."
)

#: Default per-run step budget for the skeleton task. The pipeline completes in a single
#: model turn (the stages run on that turn's ``on_step_end``); this is a small ceiling so a
#: degenerate, tool-looping run cannot spin and re-run the pipeline. Overridable via
#: ``DHX_MAX_STEPS`` (or ``--config`` ``max_steps``) for a model that needs more turns.
_SKELETON_MAX_STEPS = _env_int_default("DHX_MAX_STEPS", 4)

#: Process exit code on a clean run (exit_reason 'done').
EXIT_OK: int = 0
#: Process exit code for any non-clean terminal reason (budget/loop/error/…). A
#: single non-zero code keeps the CLI contract simple while still being honest:
#: only ``done`` returns 0; everything else (including unrecognised reasons) is
#: a failure (Req 4.5, 4.6, 8.5).
EXIT_RUN_FAILED: int = 1


def exit_code_for_reason(exit_reason: str) -> int:
    """Map a HarnessX ``TaskEndEvent.exit_reason`` to a process exit code.

    ``done`` maps to :data:`EXIT_OK` (0); every other terminal reason — including
    ``budget_exceeded``, ``loop_detected``, ``error``, ``interrupted``, and any
    reason this skeleton does not explicitly know about — maps to the non-zero
    :data:`EXIT_RUN_FAILED` (Req 4.6, 8.5). An unknown reason is treated as a
    failure rather than silently returning 0, so a new HarnessX terminal state can
    never be misreported as success.
    """
    return EXIT_OK if exit_reason == "done" else EXIT_RUN_FAILED


def _split_roles(roles_arg: str | None) -> list[str] | None:
    """Split a comma-separated ``--roles`` value into a list, or ``None``.

    ``None`` (flag not supplied) is passed through so the config layer applies its
    default-to-all-vocabulary-roles behaviour (Req 7.2). Empty/whitespace entries
    are dropped so ``--roles "developer, manager"`` works.
    """
    if roles_arg is None:
        return None
    return [part.strip() for part in roles_arg.split(",") if part.strip()]


def _validate_target_repo(target_repo: str | None) -> str:
    """Validate the target is an existing directory, before any run (Req 4.7).

    Returns the absolute target path. Raises :class:`TargetRepoError` (mapped to a
    non-zero exit by :func:`main`) when the path is missing, is not a directory, or
    was not supplied at all.
    """
    if not target_repo:
        raise TargetRepoError(
            "No target repository given. Usage: dhx run <target-repo> [--out DIR]."
        )
    if not os.path.exists(target_repo):
        raise TargetRepoError(f"Target repository path does not exist: {target_repo}")
    if not os.path.isdir(target_repo):
        raise TargetRepoError(
            f"Target repository path is not a directory: {target_repo}"
        )
    return os.path.abspath(target_repo)


def prepare_run(
    args: argparse.Namespace,
    *,
    model_config: "ModelConfig | None" = None,
    stream: Any = None,
) -> PreparedRun:
    """Validate inputs, load config, and optionally resolve a writer model.

    Target validation runs first so a bad path aborts before ontology/model work.
    A missing model is ``PreparedRun.model is None`` (honest-empty), not a
    resolution error. This does not bind ``make_docgen`` as the run harness.

    Args:
        args: The parsed ``run`` namespace (``target_repo``/``out``/``config``/``roles``).
        model_config: An optional pre-built ``ModelConfig`` (tests inject a
            no-network fake or inspecting provider). When ``None``, the real
            resolver is tried; failure yields no model rather than aborting.
        stream: Where the ``dhx init`` hint is printed. ``None`` (the default)
            resolves to ``sys.stdout`` *at call time* so test capture works.

    Returns:
        A :class:`PreparedRun` with resolved paths, config, and optional model.

    Raises:
        TargetRepoError: The target is missing or not a directory (Req 1.2).
        OntologyConfigError: A present ontology file failed to load.
        ConfigError: Malformed/unknown config, or a role not in the vocabulary.
    """
    # 1. Validate the target FIRST — before any ontology/model work (Req 4.7).
    target_repo = _validate_target_repo(args.target_repo)

    # 2. Resolve the output directory (documented default when --out is omitted).
    out_dir = (
        os.path.abspath(args.out)
        if args.out
        else os.path.join(target_repo, _DEFAULT_OUT_RELPATH)
    )

    # 3. Load the project vocabulary. Absent file -> default profile + hint (10.3);
    #    present-but-invalid -> OntologyConfigError (10.4, raised by the loader).
    vocabulary, used_default = load_project_vocabulary(target_repo)
    if used_default:
        hint_stream = sys.stdout if stream is None else stream
        print(
            "No "
            f"{ONTOLOGY_CONFIG_RELPATH} found; using the default ontology profile. "
            "Run 'dhx init' to customise roles/intents/subjects for this project.",
            file=hint_stream,
        )

    # 4. Load config (YAML then CLI overrides) and validate roles vs the loaded
    #    Vocabulary (ConfigError listing valid roles on an unknown role; 7.3/7.5/7.6).
    cli_overrides: dict[str, Any] = {
        "out_dir": out_dir,
        "roles": _split_roles(args.roles),
        # github-pages-deploy task 4.3: thread the --deploy-mode flag into the
        # config so DocgenConfig.deploy_mode carries the operator's selection. A
        # None value (flag absent) does not clobber a config-file value, and the
        # config surface then applies the emit-ci-workflow default (Req 3.2, 3.3).
        # ``getattr`` keeps the run path tolerant of a namespace built without the
        # flag (defensive; the run subparser always defines it).
        "deploy_mode": getattr(args, "deploy_mode", None),
    }
    config = load_config(
        config_path=args.config,
        cli_overrides=cli_overrides,
        vocabulary=vocabulary,
    )

    # 5. Resolve the model (config-then-env) unless a ModelConfig was injected.
    #    No usable model is a valid run: the pipeline writes a zero-page report
    #    with reason ``no_model`` instead of substituting outline pages (Req 1.3).
    if model_config is None:
        from docuharnessx.model_resolver import resolve_model

        try:
            model_config = resolve_model(config.model)
        except ModelResolutionError:
            model_config = None

    model = None if model_config is None else getattr(model_config, "main", model_config)

    return PreparedRun(
        config=config,
        vocabulary=vocabulary,
        used_default=used_default,
        target_repo=target_repo,
        out_dir=out_dir,
        model=model,
    )


def _locate_journal_jsonl(out_dir: str, run_id: str) -> str | None:
    """Find the conversation-trace ``.jsonl`` HarnessJournal wrote for *run_id*.

    HarnessJournal lays a run's files out as
    ``<base_dir>/<session_id>/<run_id>.jsonl`` (plus a sibling
    ``<run_id>_trace.jsonl``). The session id is generated inside ``harness.run``,
    so rather than reconstruct it we walk the output tree for the segment file
    named after the run's ``run_id``. Returns its absolute path, or ``None`` when
    no matching trace was produced (e.g. journalling disabled).
    """
    if not os.path.isdir(out_dir):
        return None
    target_name = f"{run_id}.jsonl"
    for root, _dirs, files in os.walk(out_dir):
        if target_name in files:
            return os.path.join(root, target_name)
    # Fall back to any conversation jsonl under the out dir (single-run skeleton).
    for root, _dirs, files in os.walk(out_dir):
        for name in files:
            if name.endswith(".jsonl") and not name.endswith("_trace.jsonl"):
                return os.path.join(root, name)
    return None


def _thread_deploy_mode(harness: "Harness", deploy_mode: str) -> None:
    """Place the configured deploy mode on the run harness's Deploy stage(s).

    The Deploy stage (github-pages-deploy task 4.1) reads its mode from a
    per-instance value via ``getattr(self, "_deploy_mode", None)`` — exactly the way
    the model config is injected onto each processor at ``Harness.__init__``. This
    threads the resolved :attr:`DocgenConfig.deploy_mode` onto every
    :class:`~docuharnessx.stages.deploy.DeployStage` registered on the run harness
    *before* the run, so the stage runs in the operator-selected mode (Req 3.2, 3.3).

    The DeployStage is located on the harness's live processor table
    (``harness._rt.processors``, hook-keyed) rather than re-composing the pipeline,
    so this is purely additive and touches no other stage. The stage's
    :func:`~docuharnessx.deployer.resolve_deploy_mode` still validates the value at
    the run boundary, so a bad mode surfaces there as a ``DeployInputError`` (Req
    3.4) — this CLI step only carries the configured string through. The DeployStage
    import is deferred to call time so ``dhx --help`` / parser unit tests need no
    harness wiring, mirroring the other local imports in this module.
    """
    from docuharnessx.stages.deploy import DeployStage

    runtime = getattr(harness, "_rt", None)
    processors = getattr(runtime, "processors", None)
    if not processors:
        return
    for procs in processors.values():
        for proc in procs:
            if isinstance(proc, DeployStage):
                proc._deploy_mode = deploy_mode


def _publish_if_accepted(
    *,
    pages: tuple[Any, ...],
    repo_path: str,
    out_dir: str,
    deploy_mode: str,
) -> None:
    """Run existing publish modes only after at least one accepted page (Req 8.5).

    ``run_pipeline`` already assembled ``<out>/site`` when accepted ≥ 1. Zero
    accepted pages must not deploy (Req 8.4). Invokes
    :func:`docuharnessx.deployer.deploy_site` against that site — not the dummy
    ``DeployStage`` bus. ``mkdocs`` is launched via ``python -m mkdocs`` so the
    venv-installed package is used even when no ``mkdocs`` console script is on
    ``PATH``.
    """
    if not pages:
        return
    site_dir = os.path.join(out_dir, "site")
    mkdocs_yml = os.path.join(site_dir, "mkdocs.yml")
    docs_dir = os.path.join(site_dir, "docs")
    if not os.path.isfile(mkdocs_yml):
        return

    from docuharnessx.assembler import read_origin_remote, resolve_site_identity
    from docuharnessx.assembler.model import ASSEMBLED_SITE_SCHEMA_VERSION, AssembledSite
    from docuharnessx.deployer import DefaultCommandRunner, deploy_site, resolve_deploy_mode

    class _PythonMkdocsRunner(DefaultCommandRunner):
        def run(self, args, cwd, timeout=None):  # type: ignore[no-untyped-def]
            argv = list(args)
            if argv and argv[0] == "mkdocs":
                argv = [sys.executable, "-m", "mkdocs", *argv[1:]]
            return super().run(argv, cwd, timeout=timeout)

    identity = resolve_site_identity(repo_path, read_origin_remote(repo_path), {})
    site = AssembledSite(
        schema_version=ASSEMBLED_SITE_SCHEMA_VERSION,
        site_dir=os.path.abspath(site_dir),
        docs_dir=os.path.abspath(docs_dir),
        mkdocs_yml_path=os.path.abspath(mkdocs_yml),
        identity=identity,
        page_count=len(pages),
        role_page_count=0,
    )
    _log.info(
        "publishing accepted site under %s (deploy_mode=%s)",
        site_dir,
        deploy_mode,
    )
    deploy_site(
        site,
        repo_path,
        out_dir,
        resolve_deploy_mode(deploy_mode),
        runner=_PythonMkdocsRunner(),
    )


def orchestrate_run(
    prepared: PreparedRun,
    *,
    max_steps: int | None = None,
    task_description: str | None = None,
) -> RunOutcome:
    """Drive the prepared documentation run through the explore-first pipeline.

    Does **not** construct a dummy conversational ``BaseTask`` or bind
    ``make_docgen`` as the outer harness. ``max_steps`` / ``task_description``
    are accepted for call-site compatibility and ignored.

    Returns:
        A :class:`RunOutcome` with ``exit_code=0`` for a completed run, including
        honest-empty (zero accepted pages).
    """
    _ = max_steps
    _ = task_description
    # Alias: this module already exports ``RunOutcome`` for the CLI contract.
    from docuharnessx.pipeline.run import run_pipeline as run_explore_pipeline

    os.makedirs(prepared.out_dir, exist_ok=True)
    pipeline_outcome = run_explore_pipeline(
        repo_path=prepared.target_repo,
        out_dir=prepared.out_dir,
        model=prepared.model,
        deploy_mode=prepared.config.deploy_mode,
    )
    try:
        _publish_if_accepted(
            pages=pipeline_outcome.pages,
            repo_path=prepared.target_repo,
            out_dir=prepared.out_dir,
            deploy_mode=prepared.config.deploy_mode,
        )
    except Exception as exc:
        _log.error("publish after accept failed: %s", exc)
        return RunOutcome(
            exit_reason="error",
            exit_code=EXIT_RUN_FAILED,
            journal_path=None,
            out_dir=prepared.out_dir,
        )
    return RunOutcome(
        exit_reason="done",
        exit_code=EXIT_OK,
        journal_path=None,
        out_dir=prepared.out_dir,
    )


def _run_command(
    args: argparse.Namespace,
    *,
    model_config: "ModelConfig | None",
    max_steps: int | None = None,
) -> int:
    """Handle ``dhx run``: prepare → explore-first pipeline → report.

    Validates/loads via :func:`prepare_run`, drives :func:`orchestrate_run`,
    prints the run-report path on success, and returns the mapped exit code.
    Honest-empty is success. *max_steps* is kept as a test-compatible keyword
    and is not used to drive a dummy outer harness.
    """
    prepared = prepare_run(args, model_config=model_config)
    outcome = orchestrate_run(prepared, max_steps=max_steps)
    report_path = os.path.join(outcome.out_dir, "report.json")
    where = report_path if os.path.isfile(report_path) else outcome.out_dir

    if outcome.exit_code == EXIT_OK:
        print(
            f"dhx run: completed (exit_reason={outcome.exit_reason}). "
            f"Report: {where}"
        )
    else:
        print(
            f"dhx run: ended with exit_reason='{outcome.exit_reason}'. "
            f"See the run report for details: {where}",
            file=sys.stderr,
        )
    return outcome.exit_code


def _require_mcp() -> None:
    """Fail with an explicit, dependency-naming error if the MCP SDK is missing.

    Implements mcp-refine Req 1.4 at the ``mcp``-command boundary, mirroring
    :func:`_require_harnessx`: rather than failing with an opaque ``ImportError`` deep
    in the server factory, raise the typed
    :class:`~docuharnessx.errors.DependencyError` naming the missing SDK and how to
    install it. ``DependencyError`` is a
    :class:`~docuharnessx.errors.DocuHarnessXError`, so :func:`main` maps it to the
    standard non-zero CLI exit. The import is deferred to call time so ``dhx --help``
    and the ``run`` / ``init`` paths never require the MCP SDK.
    """
    try:
        import mcp.server  # noqa: F401
        import mcp.server.stdio  # noqa: F401
    except ImportError as exc:  # pragma: no cover - exercised when dep absent
        from docuharnessx.errors import DependencyError

        raise DependencyError(
            "DocuHarnessX 'mcp' requires the 'mcp' SDK (>=1.28), which is not "
            "importable. Install it with 'pip install \"mcp>=1.28\"' (or "
            "'pip install -e .')."
        ) from exc


def resolve_session(*args: Any, **kwargs: Any) -> Any:
    """Resolve the per-target refine session (lazy, drift-mitigation wrapper).

    Delegates to :func:`docuharnessx.mcp.resolve_session`. The import is deferred to
    call time because :mod:`docuharnessx.mcp.session` imports
    :func:`_validate_target_repo` *from this module* — a module-level import here would
    be circular. Exposing it as a module-level name also lets the ``dhx mcp`` tests
    monkeypatch ``cli.resolve_session`` to a credential-free stub.
    """
    from docuharnessx.mcp import resolve_session as _resolve_session

    return _resolve_session(*args, **kwargs)


def _run_stdio_blocking(session: Any) -> None:
    """Drive the stdio refine server to completion (blocking; mcp-refine task 5.2).

    Wraps the async :func:`docuharnessx.mcp.run_stdio` in :func:`asyncio.run` so the
    ``dhx mcp`` command blocks serving the MCP protocol over the inherited
    ``stdin``/``stdout`` until the client disconnects (Req 2.5). The server logs to
    **stderr** and the stdio transport owns ``stdout``, so the command's stdout stays a
    clean protocol channel. Exposed as a module-level name so the tests can monkeypatch
    it to a credential-free stub (no stdio subprocess, no model).
    """
    from docuharnessx.mcp import run_stdio

    asyncio.run(run_stdio(session))


def _mcp_command(args: argparse.Namespace) -> int:
    """Handle ``dhx mcp``: validate the target, resolve the session, launch stdio.

    In order (mcp-refine Req 2.1, 2.2, 2.5, 2.6):

    1. **Guard the MCP SDK** import with an explicit, dependency-naming error so a
       stripped install reports the missing SDK cleanly (Req 1.4), mirroring
       :func:`_require_harnessx`.
    2. **Validate the target FIRST** — an existing directory — via the same
       :func:`_validate_target_repo` the ``run`` path uses, so a bad target raises
       :class:`TargetRepoError` (mapped to a non-zero exit by :func:`main`) *before any
       session/model work* (Req 2.2).
    3. **Resolve the per-target session** via :func:`resolve_session` (output dir
       defaulting to the documented per-target path when ``--out`` is omitted; the
       project ``Vocabulary``, the ``<out>/segments`` store, the per-target
       ``SiteIdentity``, and the resolved model — a no-model resolution is swallowed to
       ``None`` inside the resolver so the server still starts; Req 2.1, 2.3, 2.4, 2.6).
    4. **Launch the stdio server** via :func:`_run_stdio_blocking`, serving until the
       client disconnects (Req 2.5).

    All human/log output goes to **stderr** (configured in :func:`main` via
    :func:`_configure_run_logging`); the launcher writes nothing to stdout except the
    MCP protocol stream, so the command's stdout stays the MCP channel.

    Returns :data:`EXIT_OK` once the server loop has terminated cleanly (the client
    disconnected). A :class:`TargetRepoError` (or any other typed boundary failure)
    propagates to :func:`main`, which reports it on stderr and maps it to a non-zero
    exit.
    """
    # 1. The SDK guard runs before validation so a stripped install reports the missing
    #    dependency rather than failing later in the launcher.
    _require_mcp()

    # 2. The agent sets the workspace (target repo + output dir) at run time via the
    #    ``open_workspace`` tool, so the launch target is OPTIONAL. When a target repo is
    #    given, pre-open it (the ``dhx mcp <repo> --out`` convenience): validate it first
    #    (TargetRepoError on a bad target), then resolve the per-target session (``--out``
    #    omitted -> the documented per-target default; a ``--config`` ``model:`` honoured
    #    config-then-env, fail-fast on a bad config). Otherwise launch a generic server the
    #    client points with ``open_workspace(repo, out)``.
    session = None
    if args.target_repo:
        target_repo = _validate_target_repo(args.target_repo)
        out_dir = os.path.abspath(args.out) if args.out else None
        session = resolve_session(target_repo, out_dir, config_path=args.config)
        print(
            f"dhx mcp: serving refine MCP server over stdio; workspace pre-opened at "
            f"{target_repo} (the client may switch via open_workspace). Logs -> stderr.",
            file=sys.stderr,
        )
    else:
        print(
            "dhx mcp: serving refine MCP server over stdio; call "
            "open_workspace(repo, out) to choose the docs to refine. Logs -> stderr.",
            file=sys.stderr,
        )

    # 3. Launch the stdio server and serve until the client disconnects (Req 2.5). The
    #    transport owns stdout; the server logs to stderr.
    _run_stdio_blocking(session)
    return EXIT_OK


def _prompt_axis_terms(
    axis_label: str,
    input_fn: "Any",
    out: Any,
) -> list[dict[str, str]]:
    """Interactively gather one ontology axis (roles or intents) as id/label pairs.

    Asks repeatedly for ``<id> = <label>`` style entries until a blank line ends
    the axis (Req 9.2). An entry may be a bare ``id`` (the id doubles as the label)
    or ``id: Label``. Returns a list of ``{"id":, "label":}`` dicts that
    :func:`docuharnessx.ontology_setup.run_init` marshals into ``AxisTerm`` s via the
    ``ontology-engine`` vocabulary API — the skeleton never assembles the schema.
    """
    print(
        f"Enter {axis_label} one per line as 'id' or 'id: Label'. "
        "Blank line to finish.",
        file=out,
    )
    terms: list[dict[str, str]] = []
    while True:
        raw = input_fn(f"  {axis_label} #{len(terms) + 1}: ").strip()
        if not raw:
            break
        term_id, sep, label = raw.partition(":")
        term_id = term_id.strip()
        if not term_id:
            continue
        terms.append({"id": term_id, "label": (label.strip() or term_id)})
    return terms


def _prompt_subjects(input_fn: "Any", out: Any) -> list[str]:
    """Interactively gather the subject prefixes (tags/subjects) (Req 9.2).

    Asks for subject prefixes one per line (e.g. ``component:``), normalising each
    to the trailing-colon form the ``ontology-engine`` serializer expects. Blank
    line ends the list.
    """
    print(
        "Enter subject prefixes one per line (e.g. 'component'). "
        "Blank line to finish.",
        file=out,
    )
    subjects: list[str] = []
    while True:
        raw = input_fn(f"  subject #{len(subjects) + 1}: ").strip()
        if not raw:
            break
        subjects.append(raw if raw.endswith(":") else f"{raw}:")
    return subjects


def _gather_init_answers(input_fn: "Any", out: Any) -> dict[str, Any]:
    """Gather the operator's interactive ``dhx init`` answers (Req 9.2).

    Asks which roles exist, what the intents are, and which tags/subjects apply, and
    returns a plain mapping (``roles``/``intents``/``subjects``) that
    :func:`docuharnessx.ontology_setup.run_init` assembles into an ``ontology-engine``
    :class:`Vocabulary` via the engine vocabulary API. The skeleton only collects
    answers; it does not build the vocabulary or its schema itself.
    """
    return {
        "roles": _prompt_axis_terms("roles", input_fn, out),
        "intents": _prompt_axis_terms("intents", input_fn, out),
        "subjects": _prompt_subjects(input_fn, out),
    }


def _init_command(args: argparse.Namespace, *, input_fn: "Any" = None) -> int:
    """Handle ``dhx init``: dispatch to ``ontology_setup.run_init`` (task 4.3).

    Delegates the whole build-and-write to
    :func:`docuharnessx.ontology_setup.run_init`, passing the resolved project dir,
    the ``--default`` choice, and ``--force`` (Req 9.1, 9.3). On success the written
    ``.docuharnessx/ontology.yaml`` path is reported to stdout and ``0`` is returned
    (Req 9.1). A refused overwrite — an existing file with no ``--force`` — is mapped
    to a non-zero exit with an explicit message naming the file (Req 9.6).

    Mode selection:

    * ``--default`` → seed the shipped default profile (Req 9.3).
    * otherwise, if running **interactively** (a TTY, or an ``input_fn`` is injected
      by tests) → ask which roles exist, what the intents are, and which
      tags/subjects apply, and assemble the answers into a ``Vocabulary`` via the
      ``ontology-engine`` API (Req 9.2).
    * otherwise (non-interactive, no ``--default``) → there is nothing to build, so
      fail gracefully with a non-zero exit and an explicit ``--default`` hint rather
      than letting ``run_init``'s ``ValueError`` surface as a traceback.

    Args:
        args: The parsed ``init`` namespace.
        input_fn: Optional line-reader (defaults to :func:`input`). Tests inject a
            scripted reader to drive the interactive path without a real TTY; its
            presence also forces the interactive branch.

    HarnessX is not required for ``init`` (no harness is run), so it is dispatched
    without the runtime-dependency check that gate the ``run`` path.
    """
    from docuharnessx.ontology_setup import run_init

    answers: Any = None
    if not args.default:
        # Interactive when an input reader is injected (tests) or stdin is a TTY.
        interactive = input_fn is not None or sys.stdin.isatty()
        if not interactive:
            # Non-interactive and no --default: nothing to build. Fail explicitly
            # rather than crashing (Req 9.2 path requires an interactive terminal).
            print(
                "dhx init: nothing to build. Re-run with '--default' to seed the "
                "default ontology profile, or run interactively to enter roles, "
                "intents, and subjects.",
                file=sys.stderr,
            )
            return EXIT_INIT_FAILED
        reader = input_fn if input_fn is not None else input
        answers = _gather_init_answers(reader, sys.stdout)

    try:
        written = run_init(
            args.project_dir,
            use_default=args.default,
            force=args.force,
            answers=answers,
        )
    except FileExistsError as exc:
        # Refused overwrite: existing file without --force (Req 9.6). run_init
        # raises FileExistsError (a stdlib error, not a DocuHarnessXError), so it
        # is handled here with an explicit, file-naming message + non-zero exit.
        print(
            f"dhx init: {exc} Re-run with '--force' to overwrite.",
            file=sys.stderr,
        )
        return EXIT_INIT_FAILED

    print(f"dhx init: wrote ontology config: {written}")
    return EXIT_OK


class _DropHarnessSerializationNoise(logging.Filter):
    """Drop the benign ``tool has no recorded __hx_target__`` serialization warning.

    HarnessX warns (``harnessx.core.harness``, WARNING) when a tool registered as a
    closure — e.g. the control bundle's ``todo_write`` — is serialized name-only,
    because it would not survive a YAML config *round-trip*. The agentic writer builds
    one bounded harness per segment and uses a ``NullTracer``: it never serializes or
    round-trips its config, so the warning is pure noise that would otherwise print
    once per segment. This filter drops *only* that message; every other
    ``harnessx.core.harness`` warning passes through untouched.
    """

    _NEEDLE = "has no recorded __hx_target__"

    def filter(self, record: logging.LogRecord) -> bool:  # True = keep, False = drop
        return self._NEEDLE not in record.getMessage()


class _DropEventLoopClosedNoise(logging.Filter):
    """Drop the benign httpx ``Event loop is closed`` teardown error from ``asyncio``.

    DocuHarnessX drives each per-segment writer agent (``composition.agent``) and each
    review-gate judge call (``review.judge``) via ``asyncio.run()`` on a short-lived loop.
    HarnessX's OpenAI provider creates a fresh ``AsyncOpenAI`` (httpx) client per call and
    never closes it; the client's connection cleanup is scheduled asynchronously and can
    fire *after* that loop has already closed, which asyncio reports as
    ``Task exception was never retrieved`` with a ``RuntimeError('Event loop is closed')``.
    The request already completed and its result was used, so this is pure teardown noise
    (one scary multi-line traceback per call). This filter drops *only* that case; every
    other ``asyncio`` error passes through untouched.
    """

    def filter(self, record: logging.LogRecord) -> bool:  # True = keep, False = drop
        text = record.getMessage()
        exc = record.exc_info[1] if record.exc_info else None
        loop_closed = (
            isinstance(exc, RuntimeError) and "Event loop is closed" in str(exc)
        ) or "Event loop is closed" in text
        return not ("Task exception was never retrieved" in text and loop_closed)


def _configure_run_logging(verbose: bool) -> None:
    """Set console log verbosity for a dispatched command.

    Off by default (``WARNING``): only warnings, errors, and DocuHarnessX's own
    ``print``-ed run summary reach the console — the HarnessX pipeline-event logs
    and LiteLLM's debug firehose are suppressed. ``-v``/``--verbose`` raises the
    level to ``INFO`` and stops silencing LiteLLM, restoring the detailed output.

    Mirrors HarnessX's own CLI logging setup; a safe no-op when HarnessX is not
    importable (the run path guards that separately via :func:`_require_harnessx`).
    """
    import logging as _logging

    level = "INFO" if verbose else "WARNING"
    try:
        from harnessx.logging import configure_logging

        configure_logging(level=level)
    except ImportError:  # pragma: no cover - dependency guarded earlier
        pass

    # HarnessJournal echoes pipeline events (task_start / step_start /
    # processor_trigger / …) via structlog, which is separate from loguru and from
    # the JSONL trace file, and which HarnessX never configures (so it prints at
    # INFO by default). Filter it here. The ``{run_id}_trace.jsonl`` file is written
    # by direct file I/O (HarnessJournal._write_trace), so this only quiets the
    # console echo, never the trace.
    try:
        import structlog

        structlog.configure(
            wrapper_class=structlog.make_filtering_bound_logger(
                _logging.INFO if verbose else _logging.WARNING
            )
        )
    except Exception:  # pragma: no cover - structlog optional / API drift
        pass

    # Always suppress the benign per-segment ``todo_write`` serialization warning
    # (noise even in verbose mode; we never round-trip the harness config). Installed
    # idempotently so repeated dispatches do not stack duplicate filters.
    _hx_harness_log = _logging.getLogger("harnessx.core.harness")
    if not any(
        isinstance(f, _DropHarnessSerializationNoise) for f in _hx_harness_log.filters
    ):
        _hx_harness_log.addFilter(_DropHarnessSerializationNoise())

    # Always suppress the benign "Event loop is closed" httpx teardown traceback that the
    # per-call ``asyncio.run`` of the writer agent and the review judge can emit (the call
    # already returned its result). Installed idempotently on the asyncio logger.
    _asyncio_log = _logging.getLogger("asyncio")
    if not any(
        isinstance(f, _DropEventLoopClosedNoise) for f in _asyncio_log.filters
    ):
        _asyncio_log.addFilter(_DropEventLoopClosedNoise())

    if not verbose:
        import warnings

        _logging.getLogger("LiteLLM").setLevel(_logging.CRITICAL)
        _logging.getLogger("litellm").setLevel(_logging.CRITICAL)
        warnings.filterwarnings("ignore", category=UserWarning)
        try:
            import litellm

            litellm.suppress_debug_info = True
            litellm.set_verbose = False
        except ImportError:  # pragma: no cover - litellm ships with harnessx
            pass


def main(
    argv: Sequence[str] | None = None,
    *,
    model_config: "ModelConfig | None" = None,
    max_steps: int | None = None,
    init_input: "Any" = None,
) -> int:
    """Entry point for the ``dhx`` console script.

    Returns a process exit code. ``--help`` raises ``SystemExit(0)`` via argparse
    (standard behavior). Boundary failures are caught here, reported to stderr as
    ``<ErrorType>: <message>``, and mapped to a non-zero exit code. A clean run
    returns ``0``; a non-clean terminal reason (budget exceeded, …) returns
    non-zero (Req 4.5, 4.6, 8.5).

    Args:
        argv: Command-line arguments (defaults to ``sys.argv[1:]``). The bare form
            ``dhx <target-repo> --out DIR --config YAML`` is accepted (Req 4.1, 4.8)
            and routed to the ``run`` pipeline.
        model_config: Optional pre-built ``ModelConfig`` (tests inject a fake
            provider here). When ``None``, the real model resolver is used.
        max_steps: Test seam threaded to :func:`orchestrate_run` so a test can
            force ``budget_exceeded`` (``max_steps=0``) credential-free. Production
            callers (the console script) leave it ``None``.
        init_input: Optional line-reader injected into the interactive ``dhx init``
            path (Req 9.2) so tests can script answers without a real TTY. Production
            callers leave it ``None`` (``input`` / TTY detection is used).
    """
    parser = build_parser()
    # Support the bare form `dhx <target-repo> --out DIR --config YAML` (Req 4.1,
    # 4.8) by defaulting to the `run` subcommand when the first token is a path
    # rather than a known subcommand. `dhx run`/`dhx init`/`dhx`/`dhx --help` are
    # untouched.
    # Resolve the production default (console script / `python -m`) to sys.argv
    # BEFORE normalizing, so the bare form works at the real entry point and not
    # only for the explicit list form (Req 4.1, 4.8).
    if argv is None:
        argv = sys.argv[1:]
    args = parser.parse_args(_normalize_argv(argv))

    if args.command is None:
        parser.print_help()
        return 2

    # A real command was requested — ensure the runtime dependency is present
    # and fail with an explicit, dependency-naming message if not (Req 1.4).
    _require_harnessx()

    # Quiet third-party logging by default; -v/--verbose restores detail.
    _configure_run_logging(getattr(args, "verbose", False))

    try:
        if args.command == "run":
            return _run_command(
                args, model_config=model_config, max_steps=max_steps
            )
        if args.command == "init":
            return _init_command(args, input_fn=init_input)
        if args.command == "mcp":
            return _mcp_command(args)
        # Unknown subcommand (argparse normally guards this); report honestly.
        print(
            f"dhx {args.command}: unknown command.",
            file=sys.stderr,
        )
        return 1
    except DocuHarnessXError as exc:
        # Every boundary failure is a typed error; report type + message and exit
        # non-zero (design "Error Handling"; Req 3.4, 4.7, 7.3, 7.6, 10.4).
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
