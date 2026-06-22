"""Unit tests for the target-tree writer (github-pages-deploy task 2.3).

These tests pin the *Target-tree writer* boundary (design "Target-tree writer") of the Wave 3
``github-pages-deploy`` core: :func:`docuharnessx.deployer.tree.write_target_tree`, which copies
the assembled ``mkdocs.yml`` and the ``docs/`` tree into the target repository's working tree
and writes the rendered ``.github/workflows/docs.yml`` workflow there, returning the written
paths in deterministic order — for the *emit-ci-workflow* mode (Req 4.1, 4.5, 4.6, 9.1).

Observable completion (tasks.md 2.3): after a write the three artifacts (site config, docs
tree, workflow file) exist under the target path and nowhere else, the returned paths name
them, and no git history is modified.

The writer is **pure** filesystem I/O — it copies the assembled tree verbatim (read-only on
the source), writes only under the passed ``target_repo`` (Req 4.6, 9.1), and never pushes,
commits, or invokes any git write command (Req 4.5). This file asserts only the writer
contract over a seeded fake :class:`~docuharnessx.assembler.model.AssembledSite`; the
orchestrator / stage / command runner are later tasks and are not exercised here.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

import docuharnessx.deployer as deployer
from docuharnessx.assembler.model import (
    ASSEMBLED_SITE_SCHEMA_VERSION,
    AssembledSite,
    SiteIdentity,
)
from docuharnessx.deployer import tree as tree_mod
from docuharnessx.deployer.tree import write_target_tree

# --------------------------------------------------------------------------- #
# Fixtures: a seeded assembled site (the source) + an empty target repo tree  #
# --------------------------------------------------------------------------- #

_MKDOCS_YML_BODY = "site_name: malware_hashes\nsite_url: https://norandom.github.io/malware_hashes/\n"
_INDEX_BODY = "# Home\n\nWelcome.\n"
_SEGMENT_BODY = "# A segment\n\nBody text.\n"
_ROLE_INDEX_BODY = "# Role landing\n\nAgenda.\n"
_TAGS_BODY = "# Tags\n\n<!-- material/tags -->\n"
_WORKFLOW_YAML = "name: Deploy docs to GitHub Pages\non:\n  push:\n    branches: [main]\n"


def _identity() -> SiteIdentity:
    return SiteIdentity(
        site_name="malware_hashes",
        repo_name="norandom/malware_hashes",
        repo_url="https://github.com/norandom/malware_hashes",
        site_url="https://norandom.github.io/malware_hashes/",
        base_path="/malware_hashes/",
        edit_uri="edit/main/docs/",
    )


def _seed_assembled_site(out_root: Path) -> AssembledSite:
    """Write a representative assembled site tree under ``<out_root>/site`` and return the seam.

    Mirrors what ``assembler.writer.assemble_site`` produces: ``mkdocs.yml`` at the site root
    and a ``docs/`` tree with a top-level page, a nested role landing page, and a tags index.
    """
    site_dir = out_root / "site"
    docs_dir = site_dir / "docs"
    (docs_dir / "analyst").mkdir(parents=True, exist_ok=True)

    (site_dir / "mkdocs.yml").write_text(_MKDOCS_YML_BODY, encoding="utf-8")
    (docs_dir / "index.md").write_text(_INDEX_BODY, encoding="utf-8")
    (docs_dir / "seg-1.md").write_text(_SEGMENT_BODY, encoding="utf-8")
    (docs_dir / "analyst" / "index.md").write_text(_ROLE_INDEX_BODY, encoding="utf-8")
    (docs_dir / "tags.md").write_text(_TAGS_BODY, encoding="utf-8")

    return AssembledSite(
        schema_version=ASSEMBLED_SITE_SCHEMA_VERSION,
        site_dir=os.path.abspath(str(site_dir)),
        docs_dir=os.path.abspath(str(docs_dir)),
        mkdocs_yml_path=os.path.abspath(str(site_dir / "mkdocs.yml")),
        identity=_identity(),
        page_count=2,
        role_page_count=1,
    )


@pytest.fixture()
def seeded(tmp_path: Path) -> tuple[AssembledSite, Path]:
    """Return a seeded assembled site plus a fresh empty target repo dir."""
    site = _seed_assembled_site(tmp_path / "out")
    target = tmp_path / "target"
    target.mkdir(parents=True, exist_ok=True)
    return site, target


# --------------------------------------------------------------------------- #
# Package surface                                                             #
# --------------------------------------------------------------------------- #


def test_write_target_tree_is_exported_from_package() -> None:
    assert "write_target_tree" in deployer.__all__
    assert hasattr(deployer, "write_target_tree")


def test_package_reexport_is_identity_equal_to_submodule() -> None:
    assert deployer.write_target_tree is tree_mod.write_target_tree


# --------------------------------------------------------------------------- #
# Return type / shape (Req 4.1)                                               #
# --------------------------------------------------------------------------- #


def test_returns_a_tuple_of_three_paths(seeded) -> None:
    site, target = seeded
    written = write_target_tree(site, str(target), _WORKFLOW_YAML)
    assert isinstance(written, tuple)
    assert len(written) == 3
    assert all(isinstance(p, str) for p in written)


def test_returned_paths_are_absolute(seeded) -> None:
    site, target = seeded
    written = write_target_tree(site, str(target), _WORKFLOW_YAML)
    assert all(os.path.isabs(p) for p in written)


def test_returned_paths_all_exist(seeded) -> None:
    site, target = seeded
    written = write_target_tree(site, str(target), _WORKFLOW_YAML)
    for p in written:
        assert os.path.exists(p)


def test_returned_paths_are_deterministic_order(seeded) -> None:
    site, target = seeded
    a = write_target_tree(site, str(target), _WORKFLOW_YAML)
    b = write_target_tree(site, str(target), _WORKFLOW_YAML)
    assert a == b


def test_returned_paths_name_the_three_artifacts(seeded) -> None:
    site, target = seeded
    written = write_target_tree(site, str(target), _WORKFLOW_YAML)
    # deterministic order: mkdocs.yml, docs/ directory, workflow (design "Target-tree writer").
    assert written[0].endswith("mkdocs.yml")
    assert written[1].endswith("docs")
    assert written[2].endswith(os.path.join(".github", "workflows", "docs.yml"))


# --------------------------------------------------------------------------- #
# The three artifacts exist under the target path (Req 4.1, 4.2)              #
# --------------------------------------------------------------------------- #


def test_mkdocs_yml_copied_to_target_root(seeded) -> None:
    site, target = seeded
    write_target_tree(site, str(target), _WORKFLOW_YAML)
    dst = target / "mkdocs.yml"
    assert dst.is_file()
    assert dst.read_text(encoding="utf-8") == _MKDOCS_YML_BODY


def test_docs_tree_copied_to_target(seeded) -> None:
    site, target = seeded
    write_target_tree(site, str(target), _WORKFLOW_YAML)
    assert (target / "docs" / "index.md").read_text(encoding="utf-8") == _INDEX_BODY
    assert (target / "docs" / "seg-1.md").read_text(encoding="utf-8") == _SEGMENT_BODY
    assert (target / "docs" / "tags.md").read_text(encoding="utf-8") == _TAGS_BODY


def test_nested_docs_subdir_copied(seeded) -> None:
    site, target = seeded
    write_target_tree(site, str(target), _WORKFLOW_YAML)
    nested = target / "docs" / "analyst" / "index.md"
    assert nested.is_file()
    assert nested.read_text(encoding="utf-8") == _ROLE_INDEX_BODY


def test_workflow_written_to_target(seeded) -> None:
    site, target = seeded
    write_target_tree(site, str(target), _WORKFLOW_YAML)
    wf = target / ".github" / "workflows" / "docs.yml"
    assert wf.is_file()
    assert wf.read_text(encoding="utf-8") == _WORKFLOW_YAML


# --------------------------------------------------------------------------- #
# Target-only writes; nothing outside target_repo (Req 4.6, 9.1)             #
# --------------------------------------------------------------------------- #


def test_nothing_written_outside_the_target(tmp_path: Path) -> None:
    site = _seed_assembled_site(tmp_path / "out")
    target = tmp_path / "target"
    target.mkdir(parents=True, exist_ok=True)

    # snapshot the source tree before the write
    out_root = tmp_path / "out"
    before = {
        str(p): p.read_bytes() for p in out_root.rglob("*") if p.is_file()
    }

    write_target_tree(site, str(target), _WORKFLOW_YAML)

    # the source (assembled) tree is untouched (read-only copy)
    after = {
        str(p): p.read_bytes() for p in out_root.rglob("*") if p.is_file()
    }
    assert before == after

    # every written file lives under the target dir
    target_resolved = target.resolve()
    for p in target.rglob("*"):
        if p.is_file():
            assert target_resolved in p.resolve().parents or p.resolve() == target_resolved


def test_returned_paths_are_all_under_the_target(seeded) -> None:
    site, target = seeded
    written = write_target_tree(site, str(target), _WORKFLOW_YAML)
    target_resolved = target.resolve()
    for p in written:
        assert target_resolved in Path(p).resolve().parents


# --------------------------------------------------------------------------- #
# No git push/commit/write (Req 4.5)                                          #
# --------------------------------------------------------------------------- #


def test_does_not_create_or_touch_a_git_directory(seeded) -> None:
    site, target = seeded
    write_target_tree(site, str(target), _WORKFLOW_YAML)
    # the writer never runs git; if the target had no .git it stays absent
    assert not (target / ".git").exists()


def test_does_not_modify_existing_git_history(tmp_path: Path) -> None:
    site = _seed_assembled_site(tmp_path / "out")
    target = tmp_path / "target"
    git_dir = target / ".git"
    (git_dir / "refs").mkdir(parents=True, exist_ok=True)
    head = git_dir / "HEAD"
    head.write_text("ref: refs/heads/main\n", encoding="utf-8")
    before = head.read_bytes()

    write_target_tree(site, str(target), _WORKFLOW_YAML)

    # git internals are untouched — no commit/push happened
    assert head.read_bytes() == before


def test_module_imports_no_subprocess_or_git(seeded) -> None:
    # The writer is pure filesystem I/O; it must not bind the subprocess module (the only
    # process-touching surface — git read / mkdocs build / gh-deploy — lives in commands.py).
    assert not hasattr(tree_mod, "subprocess")
    assert "subprocess" not in vars(tree_mod)


def test_writer_runs_no_git_command(seeded, monkeypatch) -> None:
    # Hard guarantee no git/process is spawned: any subprocess entry point blows up if reached.
    import subprocess

    def _boom(*args, **kwargs):  # pragma: no cover - only fires on a regression
        raise AssertionError("write_target_tree must not spawn a subprocess (no git push/commit)")

    monkeypatch.setattr(subprocess, "run", _boom)
    monkeypatch.setattr(subprocess, "Popen", _boom)
    monkeypatch.setattr(subprocess, "check_call", _boom)
    monkeypatch.setattr(subprocess, "check_output", _boom)

    site, target = seeded
    write_target_tree(site, str(target), _WORKFLOW_YAML)
    assert (target / "mkdocs.yml").is_file()


# --------------------------------------------------------------------------- #
# Idempotent re-write (Req 4.1) — overwrites cleanly                          #
# --------------------------------------------------------------------------- #


def test_rewrite_is_idempotent(seeded) -> None:
    site, target = seeded
    write_target_tree(site, str(target), _WORKFLOW_YAML)
    write_target_tree(site, str(target), _WORKFLOW_YAML)
    assert (target / "mkdocs.yml").read_text(encoding="utf-8") == _MKDOCS_YML_BODY
    assert (target / "docs" / "index.md").read_text(encoding="utf-8") == _INDEX_BODY
    assert (
        target / ".github" / "workflows" / "docs.yml"
    ).read_text(encoding="utf-8") == _WORKFLOW_YAML


def test_existing_unrelated_target_files_are_preserved(seeded) -> None:
    site, target = seeded
    keep = target / "README.md"
    keep.write_text("keep me\n", encoding="utf-8")
    write_target_tree(site, str(target), _WORKFLOW_YAML)
    assert keep.read_text(encoding="utf-8") == "keep me\n"


# --------------------------------------------------------------------------- #
# Reference target: per-target subpath, never DocuHarnessX (Req 9.1, 9.2)     #
# --------------------------------------------------------------------------- #


def test_reference_target_resolves_to_its_own_subpath(seeded) -> None:
    site, target = seeded
    written = write_target_tree(site, str(target), _WORKFLOW_YAML)
    # the copied mkdocs.yml carries the per-target site_url (assembler-resolved), never ours
    mkdocs = (target / "mkdocs.yml").read_text(encoding="utf-8")
    assert "norandom.github.io/malware_hashes" in mkdocs
    assert "docuharnessx" not in mkdocs.lower()
    # the written paths name the resolved target dir, not DocuHarnessX's repo
    for p in written:
        assert "DocuHarnessX" not in p
