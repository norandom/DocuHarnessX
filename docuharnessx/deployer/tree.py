"""The target-tree writer (design "Target-tree writer"; task 2.3).

This module is the deterministic, model-free, network-free *Target-tree writer* of the Wave 3
``github-pages-deploy`` core. For the *emit-ci-workflow* mode (the default — Req 4) it copies
the assembled Material for MkDocs source the upstream ``mkdocs-site-assembler`` produced into
the **target repository's working tree** and writes the rendered GitHub Actions workflow
alongside it, so the target self-publishes its docs to GitHub Pages on push, with **no auto-push
and no commit** (Req 4.1, 4.2, 4.5).

:func:`write_target_tree` consumes the frozen
:class:`~docuharnessx.assembler.model.AssembledSite` verbatim, read-only — its
:attr:`~docuharnessx.assembler.model.AssembledSite.mkdocs_yml_path` and
:attr:`~docuharnessx.assembler.model.AssembledSite.docs_dir` (so the per-target ``site_url`` /
``/<repo>/`` base-path the assembler already baked into ``mkdocs.yml`` travel into the target
verbatim, never re-derived — Req 4.4) — plus the resolved ``target_repo`` path and the rendered
workflow YAML (from :func:`~docuharnessx.deployer.workflow.render_pages_workflow`), and writes
exactly three artifacts under ``target_repo``:

#. ``<target>/mkdocs.yml`` — a verbatim copy of the assembled ``mkdocs.yml``;
#. ``<target>/docs/`` — a verbatim recursive copy of the assembled ``docs/`` tree;
#. ``<target>/.github/workflows/docs.yml`` — the rendered build-and-deploy-pages workflow.

It returns the three absolute written paths in a fixed (deterministic) order — the
``mkdocs.yml`` path, the ``docs/`` directory path, then the workflow path — so the orchestrator
records a stable :attr:`~docuharnessx.deployer.model.DeployResult.written_paths` tuple.

Isolation (Req 4.6, 9.1): the **only** write target is the passed ``target_repo`` — the caller
guarantees it is the run's resolved target, never DocuHarnessX's own repo. Read-only on the
source: the assembled tree is copied, never moved or mutated.

No git (Req 4.5): the writer is pure filesystem I/O — :mod:`shutil` / :mod:`pathlib` — and never
pushes, commits, or invokes any git command. It deliberately imports no :mod:`subprocess` and no
git surface; the optional ``gh-deploy`` push lives behind the mockable command runner
(:mod:`docuharnessx.deployer.commands`, a later task), never here. The written files are left
staged in the working tree for the operator to review and commit (Req 4.5).

Determinism: the file copies are byte-for-byte verbatim and the returned tuple order is fixed,
so identical inputs yield an identical target tree and an identical written-paths tuple across
runs, mirroring the byte-stable emission in :mod:`docuharnessx.assembler.writer` and
:mod:`docuharnessx.deployer.workflow`.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # the consumed seam, read-only — no runtime import dependency.
    from docuharnessx.assembler.model import AssembledSite

__all__ = ["write_target_tree"]

#: The ``docs/`` directory name under both the assembled site root and the target repo root
#: (the MkDocs ``docs_dir`` default the assembler emits and the workflow builds against).
_DOCS_SUBDIR: str = "docs"

#: The mkdocs configuration filename copied to the target repo root.
_MKDOCS_YML: str = "mkdocs.yml"

#: The workflow path under the target repo, as POSIX-joined OS path segments. The emitted
#: GitHub Actions workflow must live at ``.github/workflows/docs.yml`` for GitHub to discover it.
_WORKFLOW_REL_PARTS: tuple[str, ...] = (".github", "workflows", "docs.yml")


def _write_text(path: Path, content: str) -> None:
    """Write ``content`` to ``path`` as UTF-8 with verbatim newlines, creating parents.

    Newlines are written verbatim (``newline=""``) so the on-disk workflow bytes equal the
    renderer's byte-stable output on every platform (the renderer ends the file with a single
    ``\\n``), mirroring :func:`docuharnessx.assembler.writer._write_text`.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as handle:
        handle.write(content)


def write_target_tree(
    site: "AssembledSite", target_repo: str, workflow_yaml: str
) -> tuple[str, ...]:
    """Write the emit-ci-workflow artifacts into the target tree (Req 4.1, 4.5, 4.6, 9.1).

    Copies the assembled ``mkdocs.yml`` to ``<target_repo>/mkdocs.yml`` and the assembled
    ``docs/`` tree to ``<target_repo>/docs/`` (both verbatim copies — the per-target ``site_url``
    / ``/<repo>/`` base-path the assembler baked into ``mkdocs.yml`` travels in unchanged, never
    re-derived — Req 4.4), and writes ``workflow_yaml`` to
    ``<target_repo>/.github/workflows/docs.yml``.

    Args:
        site: The frozen :class:`~docuharnessx.assembler.model.AssembledSite`, consumed verbatim
            and read-only — its
            :attr:`~docuharnessx.assembler.model.AssembledSite.mkdocs_yml_path` and
            :attr:`~docuharnessx.assembler.model.AssembledSite.docs_dir` are the copy sources
            (Req 4.1). Never mutated or moved.
        target_repo: The run's resolved target repository working-tree path — the **only** write
            target (Req 4.6, 9.1). The caller guarantees this is the run's target, never
            DocuHarnessX's own repo. An existing tree is overwritten in place; unrelated files
            are left untouched.
        workflow_yaml: The rendered ``.github/workflows/docs.yml`` content (from
            :func:`~docuharnessx.deployer.workflow.render_pages_workflow`), written verbatim.

    Returns:
        The three absolute written paths in deterministic order — the copied ``mkdocs.yml``, the
        copied ``docs/`` directory, then the workflow file
        (:attr:`~docuharnessx.deployer.model.DeployResult.written_paths`). Byte-stable for equal
        inputs.

    Notes:
        Never pushes, commits, or invokes any git command (Req 4.5) — the written files are left
        staged in the working tree for the operator to review and commit. The only network
        action in the deploy core is the ``gh-deploy`` push, which lives behind the command
        runner and is never reached here.
    """
    target_root = Path(target_repo)
    target_root.mkdir(parents=True, exist_ok=True)

    # 1. mkdocs.yml — verbatim copy to the target repo root.
    mkdocs_dst = target_root / _MKDOCS_YML
    shutil.copyfile(site.mkdocs_yml_path, mkdocs_dst)

    # 2. docs/ — verbatim recursive copy to the target repo. ``dirs_exist_ok`` so an
    #    existing target docs/ tree is overwritten in place (the assembled tree is the source
    #    of truth) while leaving unrelated target files untouched.
    docs_dst = target_root / _DOCS_SUBDIR
    shutil.copytree(site.docs_dir, docs_dst, dirs_exist_ok=True)

    # 3. .github/workflows/docs.yml — the rendered workflow, written verbatim (parents created).
    workflow_dst = target_root.joinpath(*_WORKFLOW_REL_PARTS)
    _write_text(workflow_dst, workflow_yaml)

    # Deterministic order: mkdocs.yml, docs/, workflow.
    return (
        os.path.abspath(str(mkdocs_dst)),
        os.path.abspath(str(docs_dst)),
        os.path.abspath(str(workflow_dst)),
    )
