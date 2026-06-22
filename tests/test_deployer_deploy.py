"""Unit tests for the per-mode deploy orchestrator (github-pages-deploy task 3.1).

These tests pin the *Deploy orchestrator* boundary (design "Deploy orchestrator"):
:func:`docuharnessx.deployer.deploy.deploy_site` — the single deterministic transform that
runs the selected :data:`~docuharnessx.deployer.model.DeployMode` end to end using the
components from task 2 (the mode-resolved value, the workflow renderer, the target-tree
writer, and the isolated command runner) and returns a frozen
:class:`~docuharnessx.deployer.model.DeployResult`:

* ``emit-ci-workflow`` (default): read the default branch, render the workflow, write the
  target tree (``mkdocs.yml`` + ``docs/`` + ``.github/workflows/docs.yml``), then run
  ``mkdocs build`` validation — no push (Req 4.x, 7.x);
* ``build-only``: run ``mkdocs build`` validation only — writes nothing into the target tree
  and pushes nothing (Req 6.x);
* ``gh-deploy``: run the ``mkdocs gh-deploy`` network push only — the one network action,
  invoked exactly once and never on the validated modes (Req 5.x).

Every per-target parameter is derived from the consumed
:class:`~docuharnessx.assembler.model.AssembledSite` identity (``site_url`` / ``base_path`` /
``repo_name``) and the target path — never a hardcoded DocuHarnessX value (Req 9.1, 9.2). The
``gh-deploy`` push is isolated behind the injected fake :class:`CommandRunner`, so no real
``git`` / ``mkdocs`` process is spawned and the network push is never exercised (Req 5.4,
7.4). The orchestrator performs no model call (Req 9.4).

Observable completion (tasks.md 3.1): each mode returns a ``DeployResult`` with the matching
mode/status (emitted, built, published) and the per-target Pages URL; emit-ci-workflow lists
the three written paths and a built path; build-only lists no written paths; gh-deploy
invokes the (injected) push exactly once and is never invoked on the other modes.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import pytest

import docuharnessx.deployer as deployer
from docuharnessx.assembler.model import AssembledSite, SiteIdentity
from docuharnessx.deployer import (
    DEPLOY_RESULT_SCHEMA_VERSION,
    DeployError,
    DeployResult,
)
from docuharnessx.deployer import deploy as deploy_mod
from docuharnessx.deployer.commands import CompletedResult
from docuharnessx.deployer.deploy import deploy_site


# --------------------------------------------------------------------------- #
# Fixtures: a seeded assembled site + a recording fake runner                  #
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


def _site(tmp_path, *, identity: SiteIdentity | None = None) -> AssembledSite:
    """Seed a minimal-but-real assembled site source tree under ``tmp_path/out/site``."""
    out_dir = tmp_path / "out"
    site_dir = out_dir / "site"
    docs_dir = site_dir / "docs"
    docs_dir.mkdir(parents=True)
    (docs_dir / "index.md").write_text("# Home\n\nHello.\n", encoding="utf-8")
    mkdocs_yml = site_dir / "mkdocs.yml"
    mkdocs_yml.write_text(
        "site_name: malware_hashes\n"
        "site_url: https://norandom.github.io/malware_hashes/\n"
        "docs_dir: docs\n",
        encoding="utf-8",
    )
    return AssembledSite(
        schema_version=1,
        site_dir=str(site_dir),
        docs_dir=str(docs_dir),
        mkdocs_yml_path=str(mkdocs_yml),
        identity=identity if identity is not None else _identity(),
        page_count=1,
        role_page_count=1,
    )


@dataclass
class _Invocation:
    args: tuple[str, ...]
    cwd: str
    timeout: float | None = None


class _FakeRunner:
    """A recording fake :class:`CommandRunner` — never spawns a real process.

    Each call records the argument vector + cwd + the per-call ``timeout``. The result for a
    call is taken from ``results`` in order; an ``Exception`` result is raised (to simulate a
    missing executable / non-runnable tool), otherwise it is returned as the
    :class:`CompletedResult`.
    """

    def __init__(self, results: list) -> None:
        self._results = list(results)
        self.calls: list[_Invocation] = []

    def run(self, args, cwd: str, timeout: float | None = None) -> CompletedResult:
        self.calls.append(_Invocation(tuple(args), cwd, timeout))
        if not self._results:
            # Default to success when not explicitly programmed so a mode that makes more
            # calls than a test pre-seeded still records them rather than blowing up.
            return CompletedResult(returncode=0)
        outcome = self._results.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def _ok(stdout: str = "", stderr: str = "") -> CompletedResult:
    return CompletedResult(returncode=0, stdout=stdout, stderr=stderr)


def _fail(returncode: int = 1, stdout: str = "", stderr: str = "boom") -> CompletedResult:
    return CompletedResult(returncode=returncode, stdout=stdout, stderr=stderr)


def _gh_deploy_calls(runner: _FakeRunner) -> list[_Invocation]:
    return [c for c in runner.calls if "gh-deploy" in c.args]


def _build_calls(runner: _FakeRunner) -> list[_Invocation]:
    return [c for c in runner.calls if "build" in c.args and "mkdocs" in (c.args[0], *c.args)]


# --------------------------------------------------------------------------- #
# Package / module surface                                                     #
# --------------------------------------------------------------------------- #


def test_package_reexports_deploy_site() -> None:
    assert "deploy_site" in deployer.__all__
    assert hasattr(deployer, "deploy_site")


def test_reexport_is_identity_equal_to_submodule() -> None:
    assert deployer.deploy_site is deploy_mod.deploy_site


def test_module_all_is_self_consistent() -> None:
    assert len(deploy_mod.__all__) == len(set(deploy_mod.__all__))
    for name in deploy_mod.__all__:
        assert hasattr(deploy_mod, name), name


# --------------------------------------------------------------------------- #
# emit-ci-workflow (default): write target tree + build validation, no push     #
# --------------------------------------------------------------------------- #


def test_emit_ci_workflow_returns_emitted_result_with_three_written_paths(tmp_path) -> None:
    site = _site(tmp_path)
    target = tmp_path / "target"
    target.mkdir()
    out_dir = tmp_path / "out"
    # branch read + build validation both succeed.
    runner = _FakeRunner([_ok(stdout="main\n"), _ok()])

    result = deploy_site(site, str(target), str(out_dir), "emit-ci-workflow", runner=runner)

    assert isinstance(result, DeployResult)
    assert result.schema_version == DEPLOY_RESULT_SCHEMA_VERSION
    assert result.mode == "emit-ci-workflow"
    assert result.status == "emitted"
    assert result.target_pages_url == site.identity.site_url
    # Exactly three written paths: mkdocs.yml, docs/, workflow.
    assert len(result.written_paths) == 3
    for path in result.written_paths:
        assert os.path.isabs(path)
        assert os.path.exists(path)
    # The three artifacts live under the target tree and exist on disk.
    assert os.path.isfile(str(target / "mkdocs.yml"))
    assert os.path.isdir(str(target / "docs"))
    assert os.path.isfile(str(target / ".github" / "workflows" / "docs.yml"))
    # A built path was produced by the build validation.
    assert result.built_path
    assert os.path.isabs(result.built_path)


def test_emit_ci_workflow_runs_build_validation_and_no_push(tmp_path) -> None:
    site = _site(tmp_path)
    target = tmp_path / "target"
    target.mkdir()
    runner = _FakeRunner([_ok(stdout="main\n"), _ok()])

    deploy_site(site, str(target), str(tmp_path / "out"), "emit-ci-workflow", runner=runner)

    # A build invocation happened; no gh-deploy push ever did (Req 7.1, 5.4).
    assert any("build" in c.args for c in runner.calls)
    assert _gh_deploy_calls(runner) == []
    for c in runner.calls:
        assert "push" not in c.args


def test_emit_ci_workflow_threads_default_branch_into_workflow(tmp_path) -> None:
    site = _site(tmp_path)
    target = tmp_path / "target"
    target.mkdir()
    # The branch read returns a non-default branch; it must appear in the emitted workflow.
    runner = _FakeRunner([_ok(stdout="trunk\n"), _ok()])

    deploy_site(site, str(target), str(tmp_path / "out"), "emit-ci-workflow", runner=runner)

    workflow = (target / ".github" / "workflows" / "docs.yml").read_text(encoding="utf-8")
    assert "trunk" in workflow


def test_emit_ci_workflow_writes_only_under_target_not_docuharnessx(tmp_path) -> None:
    site = _site(tmp_path)
    target = tmp_path / "target"
    target.mkdir()
    runner = _FakeRunner([_ok(stdout="main\n"), _ok()])

    result = deploy_site(site, str(target), str(tmp_path / "out"), "emit-ci-workflow", runner=runner)

    target_abs = os.path.abspath(str(target))
    for path in result.written_paths:
        assert os.path.abspath(path).startswith(target_abs + os.sep)
    # Per-target Pages URL, never DocuHarnessX's own.
    assert result.target_pages_url == "https://norandom.github.io/malware_hashes/"
    assert "docuharnessx" not in result.target_pages_url.lower()


def test_emit_ci_workflow_fails_loud_on_build_failure(tmp_path) -> None:
    site = _site(tmp_path)
    target = tmp_path / "target"
    target.mkdir()
    # branch read ok, then build validation fails — success must never be declared.
    runner = _FakeRunner([_ok(stdout="main\n"), _fail(returncode=2, stderr="strict warning")])

    with pytest.raises(DeployError):
        deploy_site(site, str(target), str(tmp_path / "out"), "emit-ci-workflow", runner=runner)


# --------------------------------------------------------------------------- #
# build-only: build validation only, no target writes, no push                  #
# --------------------------------------------------------------------------- #


def test_build_only_returns_built_result_with_no_written_paths(tmp_path) -> None:
    site = _site(tmp_path)
    target = tmp_path / "target"
    target.mkdir()
    runner = _FakeRunner([_ok()])

    result = deploy_site(site, str(target), str(tmp_path / "out"), "build-only", runner=runner)

    assert result.mode == "build-only"
    assert result.status == "built"
    assert result.written_paths == ()
    assert result.built_path
    assert os.path.isabs(result.built_path)
    assert result.target_pages_url == site.identity.site_url


def test_build_only_writes_nothing_into_target_tree(tmp_path) -> None:
    site = _site(tmp_path)
    target = tmp_path / "target"
    target.mkdir()
    runner = _FakeRunner([_ok()])

    deploy_site(site, str(target), str(tmp_path / "out"), "build-only", runner=runner)

    # No emit-ci-workflow artifacts leaked into the target tree (Req 6.2).
    assert not (target / "mkdocs.yml").exists()
    assert not (target / "docs").exists()
    assert not (target / ".github").exists()


def test_build_only_never_pushes(tmp_path) -> None:
    site = _site(tmp_path)
    target = tmp_path / "target"
    target.mkdir()
    runner = _FakeRunner([_ok()])

    deploy_site(site, str(target), str(tmp_path / "out"), "build-only", runner=runner)

    assert _gh_deploy_calls(runner) == []


def test_build_only_fails_loud_on_build_failure(tmp_path) -> None:
    site = _site(tmp_path)
    target = tmp_path / "target"
    target.mkdir()
    runner = _FakeRunner([_fail(returncode=1, stderr="config error")])

    with pytest.raises(DeployError):
        deploy_site(site, str(target), str(tmp_path / "out"), "build-only", runner=runner)


# --------------------------------------------------------------------------- #
# gh-deploy: the only network push, invoked exactly once                        #
# --------------------------------------------------------------------------- #


def test_gh_deploy_returns_published_result_and_pushes_exactly_once(tmp_path) -> None:
    site = _site(tmp_path)
    target = tmp_path / "target"
    target.mkdir()
    runner = _FakeRunner([_ok()])

    result = deploy_site(site, str(target), str(tmp_path / "out"), "gh-deploy", runner=runner)

    assert result.mode == "gh-deploy"
    assert result.status == "published"
    assert result.target_pages_url == site.identity.site_url
    # No target-tree writes, no built path for the push-only mode.
    assert result.written_paths == ()
    # The push happened exactly once.
    assert len(_gh_deploy_calls(runner)) == 1


def test_gh_deploy_writes_nothing_into_target_tree(tmp_path) -> None:
    site = _site(tmp_path)
    target = tmp_path / "target"
    target.mkdir()
    runner = _FakeRunner([_ok()])

    deploy_site(site, str(target), str(tmp_path / "out"), "gh-deploy", runner=runner)

    assert not (target / "mkdocs.yml").exists()
    assert not (target / "docs").exists()
    assert not (target / ".github").exists()


def test_gh_deploy_fails_loud_on_push_failure(tmp_path) -> None:
    site = _site(tmp_path)
    target = tmp_path / "target"
    target.mkdir()
    runner = _FakeRunner([_fail(stderr="no upstream configured")])

    with pytest.raises(DeployError):
        deploy_site(site, str(target), str(tmp_path / "out"), "gh-deploy", runner=runner)


def test_validated_modes_never_invoke_the_push(tmp_path) -> None:
    # emit-ci-workflow and build-only must never reach the gh-deploy push surface (Req 5.4).
    site = _site(tmp_path)
    target = tmp_path / "target"
    target.mkdir()

    emit_runner = _FakeRunner([_ok(stdout="main\n"), _ok()])
    deploy_site(site, str(target), str(tmp_path / "out"), "emit-ci-workflow", runner=emit_runner)
    assert _gh_deploy_calls(emit_runner) == []

    build_runner = _FakeRunner([_ok()])
    deploy_site(site, str(target / "b"), str(tmp_path / "out2"), "build-only", runner=build_runner)
    assert _gh_deploy_calls(build_runner) == []


# --------------------------------------------------------------------------- #
# Per-target derivation + no model call                                         #
# --------------------------------------------------------------------------- #


def test_pages_url_is_always_the_per_target_identity(tmp_path) -> None:
    custom = _identity(
        site_url="https://acme.github.io/widgets/",
        base_path="/widgets/",
        repo_name="acme/widgets",
    )
    site = _site(tmp_path, identity=custom)
    target = tmp_path / "target"
    target.mkdir()
    runner = _FakeRunner([_ok(stdout="main\n"), _ok()])

    result = deploy_site(site, str(target), str(tmp_path / "out"), "emit-ci-workflow", runner=runner)

    assert result.target_pages_url == "https://acme.github.io/widgets/"


def test_deploy_site_works_without_an_explicit_runner(tmp_path, monkeypatch) -> None:
    # The runner defaults to DefaultCommandRunner when omitted; patch the module so no real
    # subprocess is spawned, proving the default-runner path is wired without touching git/mkdocs.
    site = _site(tmp_path)
    target = tmp_path / "target"
    target.mkdir()
    default_runner = _FakeRunner([_ok(stdout="main\n"), _ok()])
    monkeypatch.setattr(deploy_mod, "DefaultCommandRunner", lambda: default_runner)

    result = deploy_site(site, str(target), str(tmp_path / "out"), "emit-ci-workflow")

    assert result.status == "emitted"
    assert len(default_runner.calls) >= 1
