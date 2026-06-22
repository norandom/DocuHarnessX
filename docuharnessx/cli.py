"""The ``dhx`` command-line entry point (task 1.1 scaffold; tasks 4.1–4.2).

This module is the **dhx CLI** boundary. Task 1.1 scaffolded the argparse surface
so the ``dhx`` console-script (declared in ``pyproject.toml`` as
``docuharnessx.cli:main``) is runnable and ``dhx --help`` works. Task 4.1 fleshes
out the ``run`` subcommand's argument parsing, validation, ontology loading,
config loading, role validation, model resolution, and **model binding**. Task 4.2
adds the run *orchestration*: populating the run-context slots, executing the
composed pipeline once, writing/reporting the journal, and mapping exit reasons to
exit codes. Task 4.3 wires the ``init`` subcommand to
:func:`docuharnessx.ontology_setup.run_init` (build/seed the vocabulary, write
``.docuharnessx/ontology.yaml``, report the path; refused overwrite → non-zero).

What the ``run`` path does (task 4.1, in order)
-----------------------------------------------
1. **Validate the target** is an existing directory *before any run*
   (:class:`TargetRepoError`, mapped to a non-zero exit; Req 4.7). This happens
   first so an invalid target aborts before any ontology/model work.
2. **Load the project vocabulary** via
   :func:`docuharnessx.ontology_loader.load_project_vocabulary`: an absent
   ``.docuharnessx/ontology.yaml`` falls back to the ``ontology-engine`` default
   profile and a ``dhx init`` hint is printed (Req 10.3); a present-but-invalid
   file raises :class:`OntologyConfigError` → non-zero exit (Req 10.4).
3. **Load the config** (``--config`` YAML overlaid with CLI overrides) and
   **validate roles** against the loaded ``Vocabulary``: an unknown ``--roles``
   value raises :class:`ConfigError` listing the valid roles (Req 7.3, 7.5, 7.6).
4. **Resolve the model** via :func:`docuharnessx.model_resolver.resolve_model`
   (config-then-env; :class:`ModelResolutionError` when none; Req 3.2–3.4).
5. **Bind the model** via ``ModelConfig(main=...).agentic(make_docgen(...))`` —
   the model is bound on the resulting ``Harness``, never placed into the
   ``HarnessConfig`` (Req 3.1). Cost/step budgets are applied through the baseline
   Control capability composed by ``make_docgen`` (Req 2.3).

What the ``run`` orchestration does (task 4.2, in order)
-------------------------------------------------------
1. **Populate the run-context slots** on a fresh harness :class:`State`: the
   validated target-repository path, the resolved output dir, and the loaded
   ``Vocabulary`` at ``SLOT_VOCABULARY`` — *before* the run so stages can read
   them (Req 6.2, 10.2).
2. **Execute the pipeline once** with a minimal skeleton ``BaseTask``. The slotted
   ``State`` is handed to ``harness.run(..., _resume_state=state)`` so the slots
   are present on the run's state; the empty pipeline drives one model turn and
   exits.
3. **Locate the journal trace** HarnessJournal wrote under the resolved output dir
   (``<out>/<session_id>/<run_id>.jsonl``) and **report it** on success (Req 4.4,
   8.1).
4. **Map the exit reason to an exit code** (Req 4.5, 4.6, 8.3–8.5): ``done`` → 0;
   ``budget_exceeded`` (recorded in the journal) and every other terminal reason
   (loop_detected, error, interrupted, …) → non-zero.

Test-injected model
-------------------
:func:`prepare_run` / :func:`main` accept an optional ``model_config`` keyword.
Production callers (the console script) pass nothing, so the real resolver runs.
Tests pass a no-network fake provider here so credential-free runs are possible
*without* baking any fake into the production resolution path (the resolver is
only called when ``model_config`` is ``None``).

Error strategy
-------------
Every boundary failure raises a typed :class:`DocuHarnessXError`; :func:`main`
catches the whole family, prints ``<ErrorType>: <message>`` to stderr, and returns
a non-zero exit code (design "Error Handling"). The required-dependency check
(Req 1.4) still runs before any real command is dispatched.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from docuharnessx.config import DocgenConfig, load_config
from docuharnessx.errors import DocuHarnessXError, TargetRepoError
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
#: ``dhx init`` (and ``dhx run``) keep working.
_SUBCOMMANDS: frozenset[str] = frozenset({"run", "init"})


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

    return parser


@dataclass(frozen=True)
class PreparedRun:
    """The product of :func:`prepare_run`: everything wired up to the bind point.

    Task 4.1 owns producing this (validation → ontology → config → model bind);
    task 4.2 consumes it to populate the run-context slots and invoke the run.

    Attributes:
        harness: The model-bound :class:`~harnessx.core.harness.Harness`, produced
            by ``ModelConfig(main=...).agentic(make_docgen(...))``. The model lives
            on ``harness.model_config``; ``harness.config`` (the ``HarnessConfig``)
            carries no model (Req 3.1).
        config: The validated :class:`DocgenConfig` (roles already checked).
        vocabulary: The loaded project ``Vocabulary`` (default profile when absent).
        used_default: ``True`` when the default profile was used (no ontology file);
            the CLI prints a ``dhx init`` hint on this flag (Req 10.3).
        target_repo: The validated absolute target-repository path.
        out_dir: The resolved output directory (the journal/docs root).
    """

    harness: "Harness"
    config: DocgenConfig
    vocabulary: "Vocabulary"
    used_default: bool
    target_repo: str
    out_dir: str


@dataclass(frozen=True)
class RunOutcome:
    """The product of :func:`orchestrate_run`: the run's result and exit mapping.

    Task 4.2 produces this after driving ``harness.run`` once; :func:`_run_command`
    consumes it to report the journal path and return the exit code.

    Attributes:
        exit_reason: The HarnessX ``TaskEndEvent.exit_reason`` (``done``,
            ``budget_exceeded``, ``error``, …).
        exit_code: The process exit code mapped from *exit_reason* via
            :func:`exit_code_for_reason` (``0`` only for ``done``; Req 4.6, 8.5).
        journal_path: The conversation-trace ``.jsonl`` HarnessJournal wrote under
            the output dir, or ``None`` if none could be located.
        out_dir: The resolved output directory the journal is rooted at.
        run_context: The :class:`~docuharnessx.context.RunContext` whose ``State``
            carries the populated run-data slots (target-repo, out-dir, vocabulary),
            exposed so callers/tests can assert the slots were set (Req 6.2, 10.2).
    """

    exit_reason: str
    exit_code: int
    journal_path: str | None
    out_dir: str
    run_context: "RunContext"


#: The output directory used when ``--out`` is omitted (documented default).
#: Resolved relative to the target repo so a run is self-contained there.
_DEFAULT_OUT_RELPATH = os.path.join(".docuharnessx", "out")

#: The skeleton's minimal run task description. The empty pipeline performs no real
#: documentation work yet (every stage is a no-op stub), so the task is a single
#: placeholder turn that drives the run loop once to prove the wiring end to end.
_SKELETON_TASK_DESCRIPTION = (
    "DocuHarnessX skeleton run: drive the empty documentation pipeline once."
)

#: Default per-run step budget for the skeleton task. The no-op pipeline completes
#: in a single model turn; this is a small ceiling so a degenerate run cannot spin.
_SKELETON_MAX_STEPS = 4

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
    """Validate inputs, load ontology/config, resolve and bind the model.

    This is the task-4.1 core: it performs every step from target validation up to
    and including model binding, and returns a :class:`PreparedRun`. It does NOT
    run the harness (task 4.2).

    Ordering is significant and matches the design: the target is validated
    *before* any ontology/model work so a bad target aborts cleanly (Req 4.7).

    Args:
        args: The parsed ``run`` namespace (``target_repo``/``out``/``config``/``roles``).
        model_config: An optional pre-built ``ModelConfig`` (used by tests to inject
            a no-network fake provider). When ``None``, the real resolver builds the
            ``ModelConfig`` from config-then-env (Req 3.2–3.4).
        stream: Where the ``dhx init`` hint is printed. ``None`` (the default)
            resolves to ``sys.stdout`` *at call time* so test capture works.

    Returns:
        A :class:`PreparedRun` with the model-bound ``Harness`` and resolved inputs.

    Raises:
        TargetRepoError: The target is missing or not a directory (Req 4.7).
        OntologyConfigError: A present ontology file failed to load (Req 10.4).
        ConfigError: Malformed/unknown config, or a role not in the vocabulary
            (Req 7.3, 7.6).
        ModelResolutionError: No model resolvable from config or environment
            (Req 3.4).
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
    if model_config is None:
        from docuharnessx.model_resolver import resolve_model

        model_config = resolve_model(config.model)

    # 6. Bind the model via .agentic(make_docgen(...)): the model is bound on the
    #    Harness, never placed in the HarnessConfig (Req 3.1). Cost/step budgets are
    #    applied through the baseline Control capability composed by make_docgen.
    from docuharnessx.bundle import make_docgen

    harness_config = make_docgen(
        max_cost_usd=config.max_cost_usd,
        max_steps=config.max_steps,
        journal_dir=out_dir,
    )
    harness = model_config.agentic(harness_config)

    return PreparedRun(
        harness=harness,
        config=config,
        vocabulary=vocabulary,
        used_default=used_default,
        target_repo=target_repo,
        out_dir=out_dir,
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


def orchestrate_run(
    prepared: PreparedRun,
    *,
    max_steps: int | None = None,
    task_description: str = _SKELETON_TASK_DESCRIPTION,
) -> RunOutcome:
    """Drive the prepared run once, journal it, and map the exit reason (task 4.2).

    Populates the run-context slots (target-repo, output dir, loaded ``Vocabulary``
    at ``SLOT_VOCABULARY``) on a fresh harness :class:`State` *before* the run
    (Req 6.2, 10.2), executes the composed pipeline once with a minimal
    ``BaseTask`` (passing the slotted ``State`` so the slots are present during the
    run), locates the journal trace under the output dir, and maps the run's
    ``exit_reason`` to an exit code (Req 4.4–4.6, 8.1, 8.3–8.5).

    Args:
        prepared: The :class:`PreparedRun` from :func:`prepare_run` (validated
            inputs + model-bound ``Harness``).
        max_steps: Per-run step budget for the skeleton task. ``None`` uses the
            small default ceiling. ``0`` makes ``State.budget_exceeded()`` true
            before the first step, so the run loop exits with
            ``exit_reason='budget_exceeded'`` *without any model call* — the
            credential-free way to exercise the budget-exceeded mapping (Req 8.4).
        task_description: The skeleton task's single user turn.

    Returns:
        A :class:`RunOutcome` with the exit reason/code, the located journal path,
        the output dir, and the :class:`~docuharnessx.context.RunContext` whose
        ``State`` carries the populated slots.
    """
    # Local HarnessX imports (drift-mitigation: keep HarnessX coupling local).
    from harnessx.core.events import make_run_id
    from harnessx.core.harness import BaseTask
    from harnessx.core.state import State

    # Local ontology import (drift-mitigation: keep ontology-engine coupling local,
    # mirroring the local HarnessX imports above). The CLI owns the concrete
    # SegmentStore adapter choice; stages consume only the SegmentStore port.
    from docuharnessx.ontology import FilesystemSegmentStore

    from docuharnessx.context import RunContext

    os.makedirs(prepared.out_dir, exist_ok=True)

    # 1. Populate the run-context slots on a fresh State BEFORE the run (Req 6.2,
    #    10.2). A fresh run_id lets us pass the slotted State as _resume_state so
    #    the slots are present on the run's state for the registered stages to read.
    state = State(run_id=make_run_id())
    run_context = RunContext(state)
    run_context.set_target_repo(prepared.target_repo)
    run_context.set_output_dir(prepared.out_dir)
    run_context.set_vocabulary(prepared.vocabulary)

    # Provision the SegmentStore the Write stage (Wave 2 cobesy-writer) requires:
    # a filesystem-backed store rooted at <out_dir>/segments and bound to the loaded
    # vocabulary, placed in the run context BEFORE the run so write/review/assemble
    # can read it (Req 6.3, 6.4). Persisting each segment as <id>.md under the output
    # dir is the intended inspectable artifact. Without this the now-real Write stage
    # halts on the unset SLOT_SEGMENT_STORE and review has nothing to review — this is
    # the CLI orchestration concern that wires the store, not a stage-boundary change.
    segment_store = FilesystemSegmentStore(
        os.path.join(prepared.out_dir, "segments"),
        prepared.vocabulary,
    )
    run_context.set_segment_store(segment_store)

    # github-pages-deploy task 4.3: thread the configured deploy mode onto the live
    # Deploy-stage processor instance(s) on the run harness BEFORE the run, so the
    # stage reads it from its per-instance ``_deploy_mode`` accessor (the same seam
    # the deploy integration suite drives, and the same per-instance injection
    # HarnessX itself uses for ``_model_config``). A bare ``dhx <repo>`` run threads
    # the emit-ci-workflow default; a ``--deploy-mode`` flag threads the selection.
    # The string's validity is checked at the stage boundary by the deploy-mode
    # resolver (Req 3.2, 3.3, 3.4).
    _thread_deploy_mode(prepared.harness, prepared.config.deploy_mode)

    steps = _SKELETON_MAX_STEPS if max_steps is None else max_steps
    task = BaseTask(description=task_description, max_steps=steps)

    # 2. Execute the composed pipeline ONCE. Passing _resume_state hands our
    #    slotted State to the run loop directly (no disk wake()), so the slots are
    #    live during the run while the journal still records the full trajectory.
    result = prepared.harness.run(task, _resume_state=state)
    harness_result = asyncio.run(result)

    exit_reason = harness_result.task_end.exit_reason

    # 3. Locate the journal trace HarnessJournal wrote under the output dir. The
    #    budget-exceeded outcome is recorded there too (the task_end record carries
    #    exit_reason='budget_exceeded'; Req 8.4).
    journal_path = _locate_journal_jsonl(prepared.out_dir, state.run_id)

    return RunOutcome(
        exit_reason=exit_reason,
        exit_code=exit_code_for_reason(exit_reason),
        journal_path=journal_path,
        out_dir=prepared.out_dir,
        run_context=run_context,
    )


def _run_command(
    args: argparse.Namespace,
    *,
    model_config: "ModelConfig | None",
    max_steps: int | None = None,
) -> int:
    """Handle ``dhx run``: prepare (4.1) → orchestrate + report + map exit (4.2).

    Validates/loads/binds via :func:`prepare_run`, then drives the run via
    :func:`orchestrate_run`, reports the journal path on success, and returns the
    exit code mapped from the run's exit reason (Req 4.4–4.6, 8.3–8.5).

    The configured step budget (Req 7.5) is applied to the run: the operator's
    ``max_steps`` (from ``--config`` YAML) becomes the run's step ceiling, so a run
    that exceeds it terminates with ``budget_exceeded`` (mapped to a non-zero exit;
    Req 8.4). When no step budget is configured, the small skeleton default ceiling
    is used.

    *max_steps* is a test seam: when given it overrides the configured budget so a
    test can force ``budget_exceeded`` (``max_steps=0``) without a network call.
    Production callers leave it ``None``, so the configured budget (or the default)
    applies.
    """
    prepared = prepare_run(args, model_config=model_config)
    # Req 7.5: apply the configured step budget. The explicit test-seam value wins;
    # otherwise the operator's configured max_steps; otherwise the default ceiling.
    effective_max_steps = (
        max_steps if max_steps is not None else prepared.config.max_steps
    )
    outcome = orchestrate_run(prepared, max_steps=effective_max_steps)

    if outcome.exit_code == EXIT_OK:
        where = outcome.journal_path or outcome.out_dir
        print(
            f"dhx run: completed (exit_reason={outcome.exit_reason}). "
            f"Journal trace: {where}"
        )
    else:
        # The run reached a non-clean terminal state (budget exceeded, loop, …).
        # The full outcome is recorded in the journal under the output dir.
        where = outcome.journal_path or outcome.out_dir
        print(
            f"dhx run: ended with exit_reason='{outcome.exit_reason}'. "
            f"See the run journal for details: {where}",
            file=sys.stderr,
        )
    return outcome.exit_code


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
