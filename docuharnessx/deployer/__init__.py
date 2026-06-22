"""The pure, model-free MkDocs deploy core (Wave 3, spec #2: ``github-pages-deploy``).

``docuharnessx.deployer`` is the deterministic, harness-free deploy core behind the thin
:class:`~docuharnessx.stages.deploy.DeployStage` adapter. It consumes the frozen
:class:`~docuharnessx.assembler.model.AssembledSite` (verbatim, read-only) — the emitted
site source dir, the ``docs/`` dir, the ``mkdocs.yml`` path, and the already-resolved
per-target :class:`~docuharnessx.assembler.model.SiteIdentity` (``site_url``,
``base_path`` = ``/<repo>/``, ``repo_url``, ``repo_name``, ``edit_uri``, ``site_name``) —
plus the run output dir and the target repo path, and runs one of three configurable
deploy modes against the **target project** (never DocuHarnessX's own repo/Pages):

* ``emit-ci-workflow`` (default) — write ``mkdocs.yml`` + ``docs/`` +
  ``.github/workflows/docs.yml`` into the target working tree, no push;
* ``gh-deploy`` — ``mkdocs gh-deploy`` push to the target ``gh-pages`` branch (the only
  network action, isolated behind the mockable command runner and never exercised in tests);
* ``build-only`` — ``mkdocs build`` only, no publish.

It runs ``mkdocs build`` as build validation under the per-target base-path before
declaring success on the validated modes, and records a frozen
:class:`~docuharnessx.deployer.model.DeployResult` in the journal and the new append-only
``SLOT_DEPLOY_RESULT`` slot. All work is deterministic and unit-testable without a model
or network — the only process-touching surface (the git default-branch read, ``mkdocs
build``, ``mkdocs gh-deploy``) is isolated behind one mockable command runner (a later
task).

This module is the **single public namespace** for the deploy core (mirroring
:mod:`docuharnessx.assembler`, :mod:`docuharnessx.review`, :mod:`docuharnessx.composition`,
and :mod:`docuharnessx.planning`). Downstream consumers — the ``DeployStage`` adapter and
the tests — import from ``docuharnessx.deployer`` rather than reaching into submodules.

Each re-export is identity-equal to its submodule definition (no shadow copies). Later
tasks populate the namespace further:

* task 1.1 (this task) — the frozen output seam from :mod:`docuharnessx.deployer.model`
  (:class:`DeployResult`, the :data:`DeployMode` / :data:`DeployStatus` literals, the
  single :data:`DEPLOY_RESULT_SCHEMA_VERSION` authority, and the
  :class:`DeployError` / :class:`DeployInputError` family);
* task 2.1 — the deploy-mode resolver (:func:`resolve_deploy_mode`) from
  :mod:`docuharnessx.deployer.mode`;
* task 2.2 — the GitHub Actions Pages workflow renderer (:func:`render_pages_workflow`)
  from :mod:`docuharnessx.deployer.workflow`;
* task 2.3 — the target-tree writer (:func:`write_target_tree`) from
  :mod:`docuharnessx.deployer.tree`;
* task 2.4 — the mockable command runner (``CommandRunner`` / ``DefaultCommandRunner`` /
  :func:`read_default_branch` / :func:`run_mkdocs_build` / :func:`run_mkdocs_gh_deploy`)
  from :mod:`docuharnessx.deployer.commands`;
* task 3.1 — the deploy orchestrator (:func:`deploy_site`) from
  :mod:`docuharnessx.deployer.deploy`.

:data:`__all__` is the authoritative, self-consistent contract for the package (mirroring
the sibling pure-core packages).
"""

from __future__ import annotations

from docuharnessx.deployer.model import (
    DEPLOY_RESULT_SCHEMA_VERSION,
    DeployError,
    DeployInputError,
    DeployMode,
    DeployResult,
    DeployStatus,
)
from docuharnessx.deployer.mode import resolve_deploy_mode
from docuharnessx.deployer.tree import write_target_tree
from docuharnessx.deployer.workflow import render_pages_workflow
from docuharnessx.deployer.commands import (
    CommandRunner,
    CompletedResult,
    DefaultCommandRunner,
    read_default_branch,
    run_mkdocs_build,
    run_mkdocs_gh_deploy,
)
from docuharnessx.deployer.deploy import deploy_site

__all__ = [
    # frozen deploy data model (task 1.1)
    "DEPLOY_RESULT_SCHEMA_VERSION",
    "DeployMode",
    "DeployStatus",
    "DeployResult",
    "DeployError",
    "DeployInputError",
    # deploy-mode resolver (task 2.1)
    "resolve_deploy_mode",
    # GitHub Actions Pages workflow renderer (task 2.2)
    "render_pages_workflow",
    # target-tree writer (task 2.3)
    "write_target_tree",
    # isolated command runner (task 2.4)
    "CompletedResult",
    "CommandRunner",
    "DefaultCommandRunner",
    "read_default_branch",
    "run_mkdocs_build",
    "run_mkdocs_gh_deploy",
    # deploy orchestrator (task 3.1)
    "deploy_site",
]
