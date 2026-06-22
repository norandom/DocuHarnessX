"""Unit tests for the GitHub Actions Pages workflow renderer (github-pages-deploy task 2.2).

These tests pin the *workflow renderer boundary* (design "Workflow renderer") of the Wave 3
``github-pages-deploy`` core: :func:`docuharnessx.deployer.workflow.render_pages_workflow`,
which renders the byte-stable ``.github/workflows/docs.yml`` GitHub Actions workflow that the
target tree writer (task 2.3) writes into the target repository's working tree so the target
self-publishes Pages on push.

Observable completion (tasks.md 2.2): for a given identity and branch the rendered workflow
contains the push trigger on that branch, a build step, and a Pages deploy job with the
write/id-token permissions, and is identical across repeated renders.

The renderer is **pure** — it derives the workflow only from the passed
:class:`~docuharnessx.assembler.model.SiteIdentity` and ``default_branch`` (so the workflow
never re-parses the remote, Req 4.4) and never carries DocuHarnessX's own identity (Req 9.1).
This file asserts only the renderer contract; the tree writer / orchestrator / stage are
later tasks and are not exercised here.
"""

from __future__ import annotations

import yaml

import docuharnessx.deployer as deployer
from docuharnessx.assembler.model import SiteIdentity
from docuharnessx.deployer import workflow as workflow_mod
from docuharnessx.deployer.workflow import render_pages_workflow


# --------------------------------------------------------------------------- #
# Sample identities                                                            #
# --------------------------------------------------------------------------- #


def _identity(
    *,
    site_name: str = "malware_hashes",
    repo_name: str = "norandom/malware_hashes",
    repo_url: str = "https://github.com/norandom/malware_hashes",
    site_url: str = "https://norandom.github.io/malware_hashes/",
    base_path: str = "/malware_hashes/",
    edit_uri: str = "edit/main/docs/",
) -> SiteIdentity:
    return SiteIdentity(
        site_name=site_name,
        repo_name=repo_name,
        repo_url=repo_url,
        site_url=site_url,
        base_path=base_path,
        edit_uri=edit_uri,
    )


def _render(default_branch: str = "main") -> str:
    return render_pages_workflow(_identity(), default_branch)


def _parsed(default_branch: str = "main") -> dict:
    return yaml.safe_load(_render(default_branch))


# --------------------------------------------------------------------------- #
# Package surface                                                              #
# --------------------------------------------------------------------------- #


def test_render_pages_workflow_is_exported_from_package() -> None:
    assert "render_pages_workflow" in deployer.__all__
    assert hasattr(deployer, "render_pages_workflow")


def test_package_reexport_is_identity_equal_to_submodule() -> None:
    assert deployer.render_pages_workflow is workflow_mod.render_pages_workflow


# --------------------------------------------------------------------------- #
# Return type / shape                                                          #
# --------------------------------------------------------------------------- #


def test_render_returns_a_str() -> None:
    assert isinstance(_render(), str)


def test_render_ends_in_exactly_one_trailing_newline() -> None:
    body = _render()
    assert body.endswith("\n")
    assert not body.endswith("\n\n")


def test_render_is_valid_yaml() -> None:
    doc = _parsed()
    assert isinstance(doc, dict)


def test_workflow_has_a_name() -> None:
    assert isinstance(_parsed().get("name"), str)
    assert _parsed()["name"]


# --------------------------------------------------------------------------- #
# Push trigger on the passed default branch (Req 4.3)                          #
# --------------------------------------------------------------------------- #


def _on_block(doc: dict) -> dict:
    # PyYAML parses the bare ``on:`` key as the boolean True (YAML 1.1), so accept either.
    if "on" in doc:
        return doc["on"]
    return doc[True]


def test_push_trigger_on_the_passed_default_branch() -> None:
    on = _on_block(_parsed("main"))
    assert "push" in on
    assert on["push"]["branches"] == ["main"]


def test_push_trigger_follows_a_non_main_default_branch() -> None:
    on = _on_block(_parsed("trunk"))
    assert on["push"]["branches"] == ["trunk"]


def test_branch_appears_in_the_raw_text() -> None:
    assert "develop" in render_pages_workflow(_identity(), "develop")


# --------------------------------------------------------------------------- #
# Minimal Pages deployment permissions (Req 4.2)                               #
# --------------------------------------------------------------------------- #


def test_workflow_grants_pages_write_and_id_token_write_permissions() -> None:
    perms = _parsed()["permissions"]
    assert perms.get("pages") == "write"
    assert perms.get("id-token") == "write"


def test_workflow_grants_contents_read() -> None:
    # Reading the repo to build it needs contents:read; assert it is present and minimal.
    perms = _parsed()["permissions"]
    assert perms.get("contents") == "read"


# --------------------------------------------------------------------------- #
# Build job: checkout, setup-python, install mkdocs-material, mkdocs build,    #
# upload-pages-artifact (Req 4.2)                                              #
# --------------------------------------------------------------------------- #


def _jobs(doc: dict) -> dict:
    return doc["jobs"]


def _all_steps(jobs: dict) -> list[dict]:
    steps: list[dict] = []
    for job in jobs.values():
        steps.extend(job.get("steps", []))
    return steps


def _uses(jobs: dict) -> list[str]:
    return [s["uses"] for s in _all_steps(jobs) if isinstance(s, dict) and "uses" in s]


def _runs(jobs: dict) -> list[str]:
    return [s["run"] for s in _all_steps(jobs) if isinstance(s, dict) and "run" in s]


def test_build_job_checks_out_the_repo() -> None:
    uses = _uses(_jobs(_parsed()))
    assert any(u.startswith("actions/checkout@") for u in uses)


def test_build_job_sets_up_python() -> None:
    uses = _uses(_jobs(_parsed()))
    assert any(u.startswith("actions/setup-python@") for u in uses)


def test_build_job_installs_mkdocs_material() -> None:
    runs = "\n".join(_runs(_jobs(_parsed())))
    assert "mkdocs-material" in runs
    assert "pip install" in runs


def test_build_job_runs_mkdocs_build() -> None:
    runs = "\n".join(_runs(_jobs(_parsed())))
    assert "mkdocs build" in runs


def test_build_job_uploads_the_pages_artifact() -> None:
    uses = _uses(_jobs(_parsed()))
    assert any(u.startswith("actions/upload-pages-artifact@") for u in uses)


# --------------------------------------------------------------------------- #
# Deploy job: deploy-pages on the github-pages environment (Req 4.2)           #
# --------------------------------------------------------------------------- #


def test_workflow_has_a_deploy_pages_step() -> None:
    uses = _uses(_jobs(_parsed()))
    assert any(u.startswith("actions/deploy-pages@") for u in uses)


def test_deploy_job_targets_the_github_pages_environment() -> None:
    jobs = _jobs(_parsed())
    envs = []
    for job in jobs.values():
        env = job.get("environment")
        if isinstance(env, str):
            envs.append(env)
        elif isinstance(env, dict) and "name" in env:
            envs.append(env["name"])
    assert "github-pages" in envs


def test_deploy_job_depends_on_the_build_job() -> None:
    # The deploy job must run after the build job so it has the artifact (a Pages
    # deploy job following the upload). Assert a needs edge exists between two jobs.
    jobs = _jobs(_parsed())
    needs_edges = [job.get("needs") for job in jobs.values() if job.get("needs")]
    assert needs_edges, "expected a deploy job depending on the build job"


# --------------------------------------------------------------------------- #
# Determinism / byte-stability (Req 4.2)                                       #
# --------------------------------------------------------------------------- #


def test_render_is_byte_stable_across_repeated_renders() -> None:
    assert _render("main") == _render("main")


def test_render_byte_stable_for_an_independently_built_equal_identity() -> None:
    a = render_pages_workflow(_identity(), "main")
    b = render_pages_workflow(_identity(), "main")
    assert a == b


def test_different_branch_changes_the_output() -> None:
    assert render_pages_workflow(_identity(), "main") != render_pages_workflow(
        _identity(), "trunk"
    )


# --------------------------------------------------------------------------- #
# No DocuHarnessX identity leaks (Req 9.1) — independent of the target value   #
# --------------------------------------------------------------------------- #


def test_workflow_carries_no_docuharnessx_identity() -> None:
    body = render_pages_workflow(_identity(), "main").lower()
    assert "docuharnessx" not in body
    assert "docu-harness" not in body


def test_workflow_is_target_agnostic_no_target_repo_name_hardcoded() -> None:
    # The renderer takes only identity + branch; the workflow builds/deploys the
    # tree it is checked out into, so a different target identity yields the same
    # workflow body for the same branch (the per-target site_url lives in mkdocs.yml,
    # not in the workflow — Req 4.4). Assert the body does not embed the repo name.
    other = SiteIdentity(
        site_name="other_project",
        repo_name="someone/other_project",
        repo_url="https://github.com/someone/other_project",
        site_url="https://someone.github.io/other_project/",
        base_path="/other_project/",
        edit_uri="edit/main/docs/",
    )
    body_mh = render_pages_workflow(_identity(), "main")
    body_other = render_pages_workflow(other, "main")
    assert body_mh == body_other
    assert "malware_hashes" not in body_other
    assert "norandom" not in body_other


# --------------------------------------------------------------------------- #
# No git push/commit logic in the renderer surface                            #
# --------------------------------------------------------------------------- #


def test_workflow_does_not_perform_a_git_push() -> None:
    runs = "\n".join(_runs(_jobs(_parsed())))
    assert "git push" not in runs
    assert "gh-deploy" not in runs
