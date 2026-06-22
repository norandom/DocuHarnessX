"""The GitHub Actions Pages workflow renderer (design "Workflow renderer"; task 2.2).

This module is the deterministic, model-free renderer of the Wave 3 ``github-pages-deploy``
core. From the resolved per-target
:class:`~docuharnessx.assembler.model.SiteIdentity` and the target's default branch, it
emits the ``.github/workflows/docs.yml`` GitHub Actions workflow content the target-tree
writer (task 2.3) writes into the target repository's working tree so the target
self-publishes its docs to GitHub Pages on push (Req 4.2, 4.3):

* a ``push`` trigger on the passed ``default_branch`` (the branch the target actually
  publishes from — Req 4.3), threaded in by the caller so the workflow never re-parses the
  target git remote (Req 4.4);
* the minimal GitHub Pages deployment permissions — ``contents: read`` to build and
  ``pages: write`` / ``id-token: write`` to deploy (Req 4.2);
* a **build** job that checks out the repo, sets up Python, ``pip install``s
  ``mkdocs-material`` (which pulls ``mkdocs``), runs ``mkdocs build`` against the
  ``mkdocs.yml`` already written into the target tree (so the per-target ``site_url`` /
  ``/<repo>/`` base-path lives in that config, not in this workflow — Req 4.4), and uploads
  the built ``site/`` with ``actions/upload-pages-artifact``;
* a **deploy** job that ``needs`` the build job, targets the standard ``github-pages``
  deployment environment, and deploys the uploaded artifact with ``actions/deploy-pages``.

The renderer is **pure**: it derives the workflow only from its two arguments, performs no
I/O, and emits byte-identical YAML for equal inputs (Req 4.2 byte-stability). It never injects
DocuHarnessX's own identity — the workflow builds and deploys whatever tree it is checked out
into, and every per-target value (``site_url``, base-path, ``repo_url``, ``edit_uri``) lives
in the assembled ``mkdocs.yml`` the writer copies alongside it, never here (Req 4.4, 9.1). It
performs no ``git push`` / ``git commit`` (the emit-ci-workflow mode never pushes — Req 4.5);
the GitHub-managed ``deploy-pages`` action publishes via the Pages deployment API, not a
branch push.

Determinism note: the workflow is assembled as an ordered ``dict`` and serialized with
``yaml.safe_dump(..., sort_keys=False)`` so key order is preserved and the output is
byte-stable, mirroring the YAML emission in :mod:`docuharnessx.assembler.mkdocs_config` and
:mod:`docuharnessx.assembler.pages`.
"""

from __future__ import annotations

import yaml

from docuharnessx.assembler.model import SiteIdentity

__all__ = ["render_pages_workflow"]

#: The human-facing workflow name shown in the target's Actions UI. Target-agnostic — the
#: per-target identity lives in the assembled ``mkdocs.yml``, never in this workflow (Req 4.4).
_WORKFLOW_NAME: str = "Deploy docs to GitHub Pages"

#: The Python version the build job sets up. Pinned to a string (not a float) so PyYAML emits
#: ``"3.12"`` rather than ``3.12`` and the value round-trips as a version, deterministically.
_PYTHON_VERSION: str = "3.12"

#: Pinned major-version action refs (deterministic; the GitHub-recommended Pages-deploy
#: actions). ``@vN`` floating-major refs match the official GitHub Pages starter workflow.
_CHECKOUT_REF: str = "actions/checkout@v4"
_SETUP_PYTHON_REF: str = "actions/setup-python@v5"
_UPLOAD_PAGES_ARTIFACT_REF: str = "actions/upload-pages-artifact@v3"
_DEPLOY_PAGES_REF: str = "actions/deploy-pages@v4"

#: The runner image. Pinned for byte-stability.
_RUNNER: str = "ubuntu-latest"

#: The standard GitHub Pages deployment environment name (the ``deploy-pages`` action
#: requires the deploy job to run in this environment).
_PAGES_ENVIRONMENT: str = "github-pages"

#: The ``pip install`` payload. ``mkdocs-material`` pulls a compatible ``mkdocs`` as a
#: dependency; both are also DocuHarnessX runtime deps, so the published build matches the
#: validated build (Req 4.2).
_PIP_INSTALL_CMD: str = "python -m pip install --upgrade pip\npython -m pip install mkdocs-material"

#: The build command. Runs against the ``mkdocs.yml`` the writer places at the repo root,
#: producing the static site under ``site/`` (the default ``upload-pages-artifact`` path).
_BUILD_CMD: str = "mkdocs build --strict"


def _on_block(default_branch: str) -> dict:
    """Return the ``on:`` trigger block: ``push`` on the passed default branch (Req 4.3).

    The caller threads ``default_branch`` in (read from the target git repo), so the workflow
    publishes from the branch the target actually uses and never re-parses the remote itself
    (Req 4.4). ``workflow_dispatch`` is added so the operator can trigger a publish manually
    from the Actions UI; both keys are emitted in a fixed order for byte-stability.
    """
    return {
        "push": {"branches": [default_branch]},
        "workflow_dispatch": {},
    }


def _permissions() -> dict:
    """Return the minimal GitHub Pages deployment permissions (Req 4.2).

    ``contents: read`` lets the build job check out and build the repo; ``pages: write`` and
    ``id-token: write`` are exactly the two permissions the GitHub Pages deployment
    (``deploy-pages`` + OIDC) requires — nothing broader is granted.
    """
    return {
        "contents": "read",
        "pages": "write",
        "id-token": "write",
    }


def _build_job() -> dict:
    """Return the build job: checkout, setup-python, install, build, upload the artifact.

    Deterministic; carries no per-target value — it builds whatever tree it is checked out
    into using the ``mkdocs.yml`` the writer placed at the repo root, then uploads the built
    ``site/`` directory for the deploy job (Req 4.2, 4.4).
    """
    return {
        "runs-on": _RUNNER,
        "steps": [
            {"name": "Checkout", "uses": _CHECKOUT_REF},
            {
                "name": "Set up Python",
                "uses": _SETUP_PYTHON_REF,
                "with": {"python-version": _PYTHON_VERSION},
            },
            {"name": "Install MkDocs Material", "run": _PIP_INSTALL_CMD},
            {"name": "Build site", "run": _BUILD_CMD},
            {"name": "Upload Pages artifact", "uses": _UPLOAD_PAGES_ARTIFACT_REF},
        ],
    }


def _deploy_job() -> dict:
    """Return the deploy job: ``needs`` build, runs in ``github-pages``, deploys the artifact.

    The ``deploy-pages`` action publishes the uploaded artifact through the GitHub Pages
    deployment API (no branch push / commit — Req 4.5). It runs in the standard
    ``github-pages`` environment and exposes the live URL as its output, mirroring the
    official GitHub Pages starter workflow. Deterministic.
    """
    return {
        "needs": "build",
        "runs-on": _RUNNER,
        "environment": {
            "name": _PAGES_ENVIRONMENT,
            "url": "${{ steps.deployment.outputs.page_url }}",
        },
        "steps": [
            {
                "name": "Deploy to GitHub Pages",
                "id": "deployment",
                "uses": _DEPLOY_PAGES_REF,
            },
        ],
    }


def render_pages_workflow(identity: SiteIdentity, default_branch: str) -> str:
    """Render the ``.github/workflows/docs.yml`` Pages workflow content (Req 4.2, 4.3, 4.4).

    Args:
        identity: The resolved per-target
            :class:`~docuharnessx.assembler.model.SiteIdentity`. Accepted for symmetry with
            the other renderers and to keep the seam stable if a future per-target workflow
            value is needed; the workflow body itself is target-agnostic — every per-target
            value (``site_url``, ``/<repo>/`` base-path, ``repo_url``, ``edit_uri``) lives in
            the assembled ``mkdocs.yml`` the writer copies alongside the workflow, never in
            this file, so the workflow never re-parses the remote and carries no DocuHarnessX
            identity (Req 4.4, 9.1).
        default_branch: The target's default branch, read from the target git repository by
            the caller and threaded in here as the ``push`` trigger branch (Req 4.3).

    Returns:
        The ``.github/workflows/docs.yml`` content as a single YAML string ending in exactly
        one trailing newline. Byte-stable for equal inputs (Req 4.2). The workflow triggers on
        ``push`` to ``default_branch``, grants the minimal ``contents: read`` /
        ``pages: write`` / ``id-token: write`` permissions, builds the site with
        ``mkdocs build`` after installing ``mkdocs-material``, and deploys it to GitHub Pages
        with ``actions/upload-pages-artifact`` + ``actions/deploy-pages``. It performs no
        ``git push`` / ``git commit`` (Req 4.5).
    """
    # ``identity`` is intentionally not embedded in the workflow body — the per-target
    # configuration lives in the assembled mkdocs.yml the writer copies alongside this file
    # (Req 4.4). Referencing it keeps the parameter live without leaking a value.
    _ = identity

    # Ordered workflow mapping; key order is preserved by sort_keys=False below so the output
    # is byte-stable for equal inputs (Req 4.2).
    workflow: dict = {
        "name": _WORKFLOW_NAME,
        # The bare ``on:`` trigger key (GitHub Actions). Emitted as the string key "on"; it is
        # the YAML 1.1 boolean spelling, so PyYAML round-trips it as the True key on load,
        # which is the documented GitHub Actions behaviour.
        "on": _on_block(default_branch),
        "permissions": _permissions(),
        "jobs": {
            "build": _build_job(),
            "deploy": _deploy_job(),
        },
    }

    body = yaml.safe_dump(
        workflow,
        default_flow_style=False,
        sort_keys=False,
        allow_unicode=True,
    )
    if not body.endswith("\n"):
        body += "\n"
    return body
