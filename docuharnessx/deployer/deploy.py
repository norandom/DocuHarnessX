"""The per-mode deploy orchestrator (design "Deploy orchestrator"; task 3.1).

This module is the orchestration boundary of the Wave 3 ``github-pages-deploy`` pure core. It
is the single deterministic, model-free transform that runs the operator-selected
:data:`~docuharnessx.deployer.model.DeployMode` end to end — wiring together the deterministic
components built in task 2 (the GitHub Actions workflow renderer, the target-tree writer, and
the isolated command runner) — and returns the frozen
:class:`~docuharnessx.deployer.model.DeployResult` the
:class:`~docuharnessx.stages.deploy.DeployStage` adapter publishes to ``SLOT_DEPLOY_RESULT``
and journals. It mirrors the assembler's :func:`docuharnessx.assembler.writer.assemble_site`
orchestration boundary: it is the only place the per-mode component wiring lives, and it holds
no global state.

:func:`deploy_site` consumes the frozen
:class:`~docuharnessx.assembler.model.AssembledSite` verbatim, read-only — its
``mkdocs_yml_path`` / ``docs_dir`` (the build/copy sources, whose per-target ``site_url`` /
``/<repo>/`` base-path the assembler already baked in) and its resolved
:class:`~docuharnessx.assembler.model.SiteIdentity` (the per-target ``site_url`` that becomes
:attr:`~docuharnessx.deployer.model.DeployResult.target_pages_url`) — plus the resolved
``target_repo`` path, the run ``out_dir``, the already-resolved/validated
:data:`~docuharnessx.deployer.model.DeployMode`, and the injected
:class:`~docuharnessx.deployer.commands.CommandRunner`, and runs one of three modes:

* ``emit-ci-workflow`` (the default — Req 4): read the target's default branch
  (:func:`~docuharnessx.deployer.commands.read_default_branch`), render the workflow
  (:func:`~docuharnessx.deployer.workflow.render_pages_workflow`), write the target tree —
  ``mkdocs.yml`` + ``docs/`` + ``.github/workflows/docs.yml``
  (:func:`~docuharnessx.deployer.tree.write_target_tree`) — then run ``mkdocs build`` build
  validation (:func:`~docuharnessx.deployer.commands.run_mkdocs_build`). No push, no commit
  (Req 4.5). Returns ``status="emitted"`` with the three written paths and the built path;
* ``build-only`` (Req 6): run ``mkdocs build`` build validation only — writes nothing into the
  target tree and pushes nothing (Req 6.2). Returns ``status="built"`` with no written paths
  and the built path;
* ``gh-deploy`` (Req 5): run the ``mkdocs gh-deploy`` push
  (:func:`~docuharnessx.deployer.commands.run_mkdocs_gh_deploy`) — the **only** network action,
  invoked exactly once and never on the validated modes (Req 5.4). Returns
  ``status="published"`` with no written paths and no built path.

Build validation runs for the ``emit-ci-workflow`` and ``build-only`` modes before success is
declared (Req 7.1); a failed build or push raises a
:class:`~docuharnessx.deployer.model.DeployError` and never declares success (Req 5.3, 7.3) —
the orchestrator re-raises so the run records the failure honestly at the stage boundary.

Per-project isolation (Req 9.1, 9.2): every per-target parameter comes from ``site.identity``
and ``target_repo`` — never a hardcoded DocuHarnessX value. The only target-tree writes happen
in ``emit-ci-workflow`` mode under ``target_repo``; the ``mkdocs build`` output stays under the
run output tree (a nested ``site`` subdir of the assembled ``site_dir``, per
:mod:`docuharnessx.deployer.commands`); the only network action is the ``gh-deploy`` push. The
orchestrator performs no model call (Req 9.4) — it is a deterministic, mechanical transform
over the assembled site and the run inputs (deterministic except for that single push).

The isolated command runner makes the validated modes credential-free and unit-testable: tests
inject a fake :class:`CommandRunner` so no real ``git`` / ``mkdocs`` process is spawned and the
``gh-deploy`` push is never exercised (Req 5.4, 7.4).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from docuharnessx.deployer.commands import (
    DefaultCommandRunner,
    read_default_branch,
    run_mkdocs_build,
    run_mkdocs_gh_deploy,
)
from docuharnessx.deployer.model import (
    DEPLOY_RESULT_SCHEMA_VERSION,
    DeployMode,
    DeployResult,
)
from docuharnessx.deployer.tree import write_target_tree
from docuharnessx.deployer.workflow import render_pages_workflow

if TYPE_CHECKING:  # the consumed seam + the runner protocol, read-only / typing-only.
    from docuharnessx.assembler.model import AssembledSite
    from docuharnessx.deployer.commands import CommandRunner

__all__ = ["deploy_site"]


def deploy_site(
    site: "AssembledSite",
    target_repo: str,
    out_dir: str,
    mode: DeployMode,
    runner: "CommandRunner | None" = None,
) -> DeployResult:
    """Run the selected deploy mode end to end and return the frozen seam (task 3.1).

    Args:
        site: The consumed frozen :class:`~docuharnessx.assembler.model.AssembledSite`, read
            verbatim and read-only (Req 2.2). Its ``mkdocs_yml_path`` / ``docs_dir`` are the
            build/copy sources (carrying the per-target ``site_url`` / ``/<repo>/`` base-path
            the assembler already baked in), and its
            :attr:`~docuharnessx.assembler.model.AssembledSite.identity` supplies the per-target
            Pages URL recorded on the result. The stage adapter pins
            ``site.schema_version`` before calling this (design precondition).
        target_repo: The run's resolved target repository working-tree path — the **only**
            target-tree write surface (``emit-ci-workflow`` mode) and the directory the default
            branch is read from. Never DocuHarnessX's own repo (Req 9.1).
        out_dir: The run's resolved output directory. The ``mkdocs build`` static-site output
            stays under the run output tree (a nested ``site`` subdir of the assembled
            ``site_dir``); accepted here for symmetry and to keep the seam stable.
        mode: The already-resolved/validated :data:`~docuharnessx.deployer.model.DeployMode`
            (the stage resolves it via :func:`~docuharnessx.deployer.mode.resolve_deploy_mode`
            before calling this, so a bad value never reaches here).
        runner: The :class:`~docuharnessx.deployer.commands.CommandRunner` seam isolating the
            only process-touching surface (git default-branch read, ``mkdocs build``, ``mkdocs
            gh-deploy``). Defaults to a production
            :class:`~docuharnessx.deployer.commands.DefaultCommandRunner`; tests inject a fake
            so no real process is spawned and the ``gh-deploy`` push is never exercised
            (Req 5.4, 7.4).

    Returns:
        A frozen :class:`~docuharnessx.deployer.model.DeployResult` whose ``mode`` / ``status``
        / ``written_paths`` / ``built_path`` / ``target_pages_url`` reflect the action taken:

        * ``emit-ci-workflow`` → ``status="emitted"``, the three written target-tree paths, the
          built path, and the per-target Pages URL;
        * ``build-only`` → ``status="built"``, no written paths, the built path, the Pages URL;
        * ``gh-deploy`` → ``status="published"``, no written paths, no built path, the Pages URL.

    Raises:
        DeployError: When ``mkdocs build`` validation fails on the validated modes (Req 7.3) or
            the ``gh-deploy`` push fails / its prerequisites are missing (Req 5.3). Success is
            never declared on a failed build/push; the error is re-raised so the stage records
            the failure honestly.
    """
    active_runner: "CommandRunner" = runner if runner is not None else DefaultCommandRunner()
    pages_url = site.identity.site_url

    if mode == "emit-ci-workflow":
        # Read the target's default branch (graceful "main" fallback) and thread it into the
        # rendered workflow's push trigger — the workflow never re-parses the remote (Req 4.3,
        # 4.4). Write the three artifacts into the target tree (no push — Req 4.5), then run
        # build validation under the per-target base-path before declaring success (Req 7.1).
        default_branch = read_default_branch(target_repo, active_runner)
        workflow_yaml = render_pages_workflow(site.identity, default_branch)
        written_paths = write_target_tree(site, target_repo, workflow_yaml)
        built_path = run_mkdocs_build(site, active_runner)
        return DeployResult(
            schema_version=DEPLOY_RESULT_SCHEMA_VERSION,
            mode="emit-ci-workflow",
            status="emitted",
            target_pages_url=pages_url,
            written_paths=written_paths,
            built_path=built_path,
            detail=(
                f"Emitted self-publishing files into the target tree "
                f"(branch {default_branch!r}) and validated the build."
            ),
        )

    if mode == "build-only":
        # Build validation only — no target-tree writes, no push (Req 6.1, 6.2).
        built_path = run_mkdocs_build(site, active_runner)
        return DeployResult(
            schema_version=DEPLOY_RESULT_SCHEMA_VERSION,
            mode="build-only",
            status="built",
            target_pages_url=pages_url,
            written_paths=(),
            built_path=built_path,
            detail="Built the static site (no publish).",
        )

    if mode == "gh-deploy":
        # The only network action — push the built site to the target gh-pages branch (Req 5.1).
        # Invoked exactly once and never on the validated modes' paths (Req 5.4).
        run_mkdocs_gh_deploy(site, active_runner)
        return DeployResult(
            schema_version=DEPLOY_RESULT_SCHEMA_VERSION,
            mode="gh-deploy",
            status="published",
            target_pages_url=pages_url,
            written_paths=(),
            built_path="",
            detail="Pushed the built site to the target gh-pages branch.",
        )

    # Defensive: the stage resolves/validates the mode before calling here, so an unknown mode
    # should be unreachable. Surface it explicitly rather than silently returning nothing.
    raise ValueError(f"Unsupported deploy mode reached the orchestrator: {mode!r}")
