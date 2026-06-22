"""Unit tests for the isolated command runner (github-pages-deploy task 2.4).

These tests pin the *Command runner* boundary (design "Command runner"):
:mod:`docuharnessx.deployer.commands` — the only process-touching surface of the Wave 3
``github-pages-deploy`` core. It isolates the three subprocess calls behind one mockable
:class:`~docuharnessx.deployer.commands.CommandRunner` so the tested paths run credential-free
and the ``mkdocs gh-deploy`` network push is **never** exercised:

* :func:`read_default_branch` — read the target's default branch with a safe ``"main"``
  fallback when git is unavailable / fails (Req 4.3);
* :func:`run_mkdocs_build` — run ``mkdocs build`` as build validation against the assembled
  ``mkdocs.yml`` (carrying the per-target base-path), raising :class:`DeployError` on a
  non-zero exit or missing tooling (Req 7.1, 7.3); no network (Req 7.4);
* :func:`run_mkdocs_gh_deploy` — run the ``mkdocs gh-deploy`` push, the only network action,
  raising :class:`DeployError` naming the missing prerequisite when the remote/tooling is
  unavailable (Req 5.1, 5.3).

Observable completion (tasks.md 2.4): with an injected fake runner, the default-branch read
falls back when git fails, the build raises the deploy error on a simulated non-zero exit,
and the gh-deploy entry point is callable but performs no real network call under the fake
runner.

Task 2.4 owns only the command runner — not the orchestrator or the stage adapter (later
tasks). This file asserts only the command-runner contract and never spawns a real ``git`` /
``mkdocs`` process (every test injects a fake runner).
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

import docuharnessx.deployer as deployer
from docuharnessx.assembler.model import AssembledSite, SiteIdentity
from docuharnessx.deployer import DeployError
from docuharnessx.deployer import commands as commands_mod
from docuharnessx.deployer.commands import (
    CommandRunner,
    CompletedResult,
    DefaultCommandRunner,
    read_default_branch,
    run_mkdocs_build,
    run_mkdocs_gh_deploy,
)


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


def _site(tmp_path) -> AssembledSite:
    site_dir = tmp_path / "site"
    docs_dir = site_dir / "docs"
    docs_dir.mkdir(parents=True)
    mkdocs_yml = site_dir / "mkdocs.yml"
    mkdocs_yml.write_text("site_name: malware_hashes\n", encoding="utf-8")
    return AssembledSite(
        schema_version=1,
        site_dir=str(site_dir),
        docs_dir=str(docs_dir),
        mkdocs_yml_path=str(mkdocs_yml),
        identity=_identity(),
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

    Each call records the argument vector + cwd + the per-call ``timeout`` ceiling. The result
    returned for a call is taken from ``results`` in order; if a result is an ``Exception`` it
    is raised (to simulate a missing executable / ``FileNotFoundError``); otherwise it is
    returned as the ``CompletedResult``.
    """

    def __init__(self, results: list) -> None:
        self._results = list(results)
        self.calls: list[_Invocation] = []

    def run(self, args, cwd: str, timeout: float | None = None) -> CompletedResult:
        self.calls.append(_Invocation(tuple(args), cwd, timeout))
        if not self._results:
            raise AssertionError("FakeRunner called more times than configured")
        outcome = self._results.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def _ok(stdout: str = "", stderr: str = "") -> CompletedResult:
    return CompletedResult(returncode=0, stdout=stdout, stderr=stderr)


def _fail(returncode: int = 1, stdout: str = "", stderr: str = "boom") -> CompletedResult:
    return CompletedResult(returncode=returncode, stdout=stdout, stderr=stderr)


# --------------------------------------------------------------------------- #
# Package / module surface                                                     #
# --------------------------------------------------------------------------- #


def test_package_reexports_command_runner_surface() -> None:
    for name in (
        "CommandRunner",
        "DefaultCommandRunner",
        "CompletedResult",
        "read_default_branch",
        "run_mkdocs_build",
        "run_mkdocs_gh_deploy",
    ):
        assert name in deployer.__all__, name
        assert hasattr(deployer, name), name


def test_reexports_are_identity_equal_to_submodule() -> None:
    assert deployer.read_default_branch is commands_mod.read_default_branch
    assert deployer.run_mkdocs_build is commands_mod.run_mkdocs_build
    assert deployer.run_mkdocs_gh_deploy is commands_mod.run_mkdocs_gh_deploy
    assert deployer.DefaultCommandRunner is commands_mod.DefaultCommandRunner
    assert deployer.CommandRunner is commands_mod.CommandRunner
    assert deployer.CompletedResult is commands_mod.CompletedResult


def test_module_all_is_self_consistent() -> None:
    assert len(commands_mod.__all__) == len(set(commands_mod.__all__))
    for name in commands_mod.__all__:
        assert hasattr(commands_mod, name), name


def test_command_runner_is_runtime_checkable_protocol() -> None:
    # DefaultCommandRunner and the fake both satisfy the protocol.
    assert isinstance(DefaultCommandRunner(), CommandRunner)
    assert isinstance(_FakeRunner([]), CommandRunner)


def test_completed_result_is_frozen_value_object() -> None:
    a = CompletedResult(returncode=0, stdout="x", stderr="y")
    b = CompletedResult(returncode=0, stdout="x", stderr="y")
    assert a == b
    with pytest.raises(Exception):
        a.returncode = 1  # type: ignore[misc]


# --------------------------------------------------------------------------- #
# Req 4.3 — read_default_branch: success + graceful fallback                    #
# --------------------------------------------------------------------------- #


def test_read_default_branch_returns_symbolic_ref(tmp_path) -> None:
    runner = _FakeRunner([_ok(stdout="develop\n")])
    branch = read_default_branch(str(tmp_path), runner)
    assert branch == "develop"
    # The read is a git invocation scoped to the target via -C, read-only.
    call = runner.calls[0]
    assert call.args[0] == "git"
    assert "-C" in call.args
    assert str(tmp_path) in call.args
    # No write/commit/push verb in the read.
    assert "push" not in call.args
    assert "commit" not in call.args


def test_read_default_branch_falls_back_to_main_on_nonzero_exit(tmp_path) -> None:
    runner = _FakeRunner([_fail(), _fail()])
    assert read_default_branch(str(tmp_path), runner) == "main"


def test_read_default_branch_falls_back_to_main_on_missing_git(tmp_path) -> None:
    # A FileNotFoundError simulates no git executable on PATH — must degrade, not abort.
    # Both the primary (symbolic-ref) and fallback (remote show) reads fail with no git.
    runner = _FakeRunner([FileNotFoundError("no git"), FileNotFoundError("no git")])
    assert read_default_branch(str(tmp_path), runner) == "main"


def test_read_default_branch_falls_back_to_main_on_oserror(tmp_path) -> None:
    runner = _FakeRunner([OSError("io error"), OSError("io error")])
    assert read_default_branch(str(tmp_path), runner) == "main"


def test_read_default_branch_falls_back_when_stdout_blank(tmp_path) -> None:
    runner = _FakeRunner([_ok(stdout="   \n"), _ok(stdout="")])
    assert read_default_branch(str(tmp_path), runner) == "main"


def test_read_default_branch_trims_whitespace(tmp_path) -> None:
    runner = _FakeRunner([_ok(stdout="  release-1.0  \n")])
    assert read_default_branch(str(tmp_path), runner) == "release-1.0"


def test_read_default_branch_uses_remote_head_when_head_detached(tmp_path) -> None:
    # symbolic-ref fails (detached HEAD) so the read falls back to parsing the remote's
    # advertised HEAD branch rather than degrading straight to "main".
    remote_show = (
        "* remote origin\n"
        "  Fetch URL: https://github.com/norandom/malware_hashes\n"
        "  HEAD branch: trunk\n"
        "  Remote branches:\n    trunk tracked\n"
    )
    runner = _FakeRunner([_fail(stderr="ref HEAD is not a symbolic ref"), _ok(stdout=remote_show)])
    assert read_default_branch(str(tmp_path), runner) == "trunk"
    # The fallback read is a read-only 'remote show', never a push.
    assert any("remote" in call.args and "show" in call.args for call in runner.calls)
    for call in runner.calls:
        assert "push" not in call.args


def test_read_default_branch_ignores_unknown_remote_head(tmp_path) -> None:
    remote_show = "* remote origin\n  HEAD branch: (unknown)\n"
    runner = _FakeRunner([_fail(), _ok(stdout=remote_show)])
    assert read_default_branch(str(tmp_path), runner) == "main"


def test_read_default_branch_never_pushes(tmp_path) -> None:
    runner = _FakeRunner([_ok(stdout="main\n")])
    read_default_branch(str(tmp_path), runner)
    for call in runner.calls:
        assert "push" not in call.args
        assert "gh-deploy" not in call.args


def test_read_default_branch_uses_short_git_timeout(tmp_path) -> None:
    # Req 4.3 graceful degradation: a hung/wedged git read must time out at the short
    # default-branch ceiling (a few seconds), NOT the generous mkdocs build ceiling, so a
    # pathological target degrades to the "main" fallback quickly rather than stalling the run.
    runner = _FakeRunner([_fail(), _ok(stdout="trunk\n")])
    read_default_branch(str(tmp_path), runner)
    for call in runner.calls:
        assert call.timeout == commands_mod._GIT_BRANCH_READ_TIMEOUT_SECONDS
        # And explicitly NOT the long mkdocs ceiling.
        assert call.timeout != commands_mod._MKDOCS_TIMEOUT_SECONDS


# --------------------------------------------------------------------------- #
# Req 7.1, 7.3, 7.4 — run_mkdocs_build: validation, fail-loud, no network       #
# --------------------------------------------------------------------------- #


def test_run_mkdocs_build_invokes_mkdocs_build_against_assembled_config(tmp_path) -> None:
    site = _site(tmp_path)
    runner = _FakeRunner([_ok()])
    built = run_mkdocs_build(site, runner)
    call = runner.calls[0]
    assert "mkdocs" in call.args[0] or call.args[0] == "mkdocs"
    assert "build" in call.args
    # Build is driven against the assembled mkdocs.yml (the per-target base-path lives in it).
    assert site.mkdocs_yml_path in call.args
    # Returns an absolute built-site directory path.
    import os

    assert built
    assert os.path.isabs(built)


def test_run_mkdocs_build_never_pushes(tmp_path) -> None:
    site = _site(tmp_path)
    runner = _FakeRunner([_ok()])
    run_mkdocs_build(site, runner)
    for call in runner.calls:
        assert "gh-deploy" not in call.args
        assert "push" not in call.args


def test_run_mkdocs_build_uses_generous_mkdocs_timeout(tmp_path) -> None:
    # A real build may process many pages, so the build runs under the generous mkdocs ceiling
    # (not the short git default-branch ceiling). The build leaves the per-call timeout unset
    # so the runner inherits its generous default (_MKDOCS_TIMEOUT_SECONDS); either way it must
    # NOT be clamped to the short git ceiling.
    site = _site(tmp_path)
    runner = _FakeRunner([_ok()])
    run_mkdocs_build(site, runner)
    recorded = runner.calls[0].timeout
    assert recorded != commands_mod._GIT_BRANCH_READ_TIMEOUT_SECONDS
    assert recorded in (None, commands_mod._MKDOCS_TIMEOUT_SECONDS)


def test_run_mkdocs_build_raises_deploy_error_on_nonzero_exit(tmp_path) -> None:
    site = _site(tmp_path)
    runner = _FakeRunner([_fail(returncode=2, stderr="config error")])
    with pytest.raises(DeployError) as exc_info:
        run_mkdocs_build(site, runner)
    # The error names the failed build / the cause (Req 7.3).
    message = str(exc_info.value)
    assert "build" in message.lower()


def test_run_mkdocs_build_raises_deploy_error_on_missing_tooling(tmp_path) -> None:
    site = _site(tmp_path)
    runner = _FakeRunner([FileNotFoundError("no mkdocs")])
    with pytest.raises(DeployError):
        run_mkdocs_build(site, runner)


def test_run_mkdocs_build_runs_under_per_target_base_path(tmp_path) -> None:
    # The validation builds the assembled mkdocs.yml whose site_url/base_path is already the
    # per-target value, so the runner must point at that config (Req 7.2). The per-target
    # base-path is not DocuHarnessX's — assert the build targets the assembled config only.
    site = _site(tmp_path)
    runner = _FakeRunner([_ok()])
    run_mkdocs_build(site, runner)
    flat = " ".join(runner.calls[0].args)
    assert site.mkdocs_yml_path in flat
    assert "docuharnessx" not in flat.lower() or site.mkdocs_yml_path in flat


def test_run_mkdocs_build_output_dir_is_nested_inside_site_dir(tmp_path) -> None:
    # Design line 117 mandates the build output at <out>/site/site/ — a 'site' subdir INSIDE
    # the assembled source tree (site_dir), NOT a sibling. A sibling would collide with the
    # assembler's own <out>/site source dir (dirname(site_dir) == <out>; <out>/site == site_dir),
    # which mkdocs --strict rejects ("docs_dir should not be within the site_dir"). Catch the
    # collision by path inspection without spawning a real build.
    import os

    site = _site(tmp_path)
    runner = _FakeRunner([_ok()])
    built = run_mkdocs_build(site, runner)

    site_dir = os.path.abspath(site.site_dir)
    built_abs = os.path.abspath(built)
    # The built dir must never equal the source site_dir (the collision the remediation fixes).
    assert built_abs != site_dir
    # The built dir must be nested strictly inside the source site_dir.
    common = os.path.commonpath([site_dir, built_abs])
    assert common == site_dir
    assert built_abs.startswith(site_dir + os.sep)
    # Specifically the design's <out>/site/site/ layout.
    assert built_abs == os.path.join(site_dir, "site")
    # The --site-dir argument passed to mkdocs is exactly this nested dir.
    call = runner.calls[0]
    assert built in call.args


def test_run_mkdocs_build_real_build_under_seeded_tree(tmp_path, monkeypatch) -> None:
    # Credential-free proof that the chosen build output dir actually builds: seed a tiny
    # real mkdocs tree at the assembler's <out>/site layout and run a REAL `mkdocs build`
    # through the DefaultCommandRunner. No network (mkdocs build is purely local). Skips if
    # mkdocs is unavailable. This guards against the source/output dir collision regressing.
    import os
    import shutil
    import sys

    # The mkdocs console shim lives next to the running interpreter (e.g. the venv bin dir);
    # ensure it is resolvable on PATH for the shell=False subprocess in DefaultCommandRunner.
    bin_dir = os.path.dirname(os.path.abspath(sys.executable))
    monkeypatch.setenv("PATH", bin_dir + os.pathsep + os.environ.get("PATH", ""))
    if shutil.which("mkdocs") is None:
        pytest.skip("mkdocs CLI not available")

    out_dir = tmp_path / "out"
    site_dir = out_dir / "site"
    docs_dir = site_dir / "docs"
    docs_dir.mkdir(parents=True)
    (docs_dir / "index.md").write_text("# Home\n\nHello.\n", encoding="utf-8")
    mkdocs_yml = site_dir / "mkdocs.yml"
    mkdocs_yml.write_text(
        "site_name: seeded\n"
        "site_url: https://example.github.io/seeded/\n"
        "docs_dir: docs\n",
        encoding="utf-8",
    )
    site = AssembledSite(
        schema_version=1,
        site_dir=str(site_dir),
        docs_dir=str(docs_dir),
        mkdocs_yml_path=str(mkdocs_yml),
        identity=_identity(),
        page_count=1,
        role_page_count=1,
    )

    built = run_mkdocs_build(site, DefaultCommandRunner())

    # The build produced a static site at the nested dir and did not delete the source docs.
    assert os.path.isfile(os.path.join(built, "index.html"))
    assert os.path.isfile(str(docs_dir / "index.md"))
    assert os.path.abspath(built) == os.path.join(os.path.abspath(str(site_dir)), "site")


# --------------------------------------------------------------------------- #
# Req 5.1, 5.3, 5.4 — run_mkdocs_gh_deploy: the only push, isolated + fail-loud  #
# --------------------------------------------------------------------------- #


def test_run_mkdocs_gh_deploy_is_callable_and_invokes_runner_once(tmp_path) -> None:
    # The push entry point is callable under the fake runner and performs NO real network
    # call — it only goes through the injected runner (Req 5.4).
    site = _site(tmp_path)
    runner = _FakeRunner([_ok()])
    result = run_mkdocs_gh_deploy(site, runner)
    assert result is None
    assert len(runner.calls) == 1
    call = runner.calls[0]
    assert "mkdocs" in call.args[0] or call.args[0] == "mkdocs"
    assert "gh-deploy" in call.args


def test_run_mkdocs_gh_deploy_uses_generous_mkdocs_timeout(tmp_path) -> None:
    # The push leaves the per-call timeout unset so the runner inherits its generous default;
    # it must NOT be clamped to the short git default-branch ceiling.
    site = _site(tmp_path)
    runner = _FakeRunner([_ok()])
    run_mkdocs_gh_deploy(site, runner)
    recorded = runner.calls[0].timeout
    assert recorded != commands_mod._GIT_BRANCH_READ_TIMEOUT_SECONDS
    assert recorded in (None, commands_mod._MKDOCS_TIMEOUT_SECONDS)


def test_run_mkdocs_gh_deploy_raises_deploy_error_on_nonzero_exit(tmp_path) -> None:
    site = _site(tmp_path)
    runner = _FakeRunner([_fail(stderr="no upstream configured for branch")])
    with pytest.raises(DeployError) as exc_info:
        run_mkdocs_gh_deploy(site, runner)
    # The error names the missing prerequisite / the failed push (Req 5.3).
    message = str(exc_info.value)
    assert "gh-deploy" in message.lower() or "deploy" in message.lower()


def test_run_mkdocs_gh_deploy_raises_deploy_error_on_missing_tooling(tmp_path) -> None:
    site = _site(tmp_path)
    runner = _FakeRunner([FileNotFoundError("no mkdocs")])
    with pytest.raises(DeployError):
        run_mkdocs_gh_deploy(site, runner)


def test_gh_deploy_not_invoked_by_build_or_branch_read(tmp_path) -> None:
    # The validated modes (build / branch read) must never reach the push surface.
    site = _site(tmp_path)
    build_runner = _FakeRunner([_ok()])
    run_mkdocs_build(site, build_runner)
    for call in build_runner.calls:
        assert "gh-deploy" not in call.args

    branch_runner = _FakeRunner([_ok(stdout="main\n")])
    read_default_branch(str(tmp_path), branch_runner)
    for call in branch_runner.calls:
        assert "gh-deploy" not in call.args


# --------------------------------------------------------------------------- #
# DefaultCommandRunner: structural — must not be exercised against real tools   #
# --------------------------------------------------------------------------- #


def test_default_command_runner_exposes_run() -> None:
    runner = DefaultCommandRunner()
    assert callable(runner.run)


def test_default_command_runner_run_signature_accepts_args_and_cwd() -> None:
    import inspect

    sig = inspect.signature(DefaultCommandRunner.run)
    params = sig.parameters
    # self, args, cwd, and an optional per-call timeout ceiling.
    assert "args" in params
    assert "cwd" in params
    assert "timeout" in params
    # timeout is optional (has a default) so the design-stated run(args, cwd) contract still
    # holds for callers that pass only the two positional args.
    assert params["timeout"].default is not inspect.Parameter.empty


def test_default_command_runner_applies_short_git_timeout_for_branch_read(tmp_path, monkeypatch) -> None:
    # The real DefaultCommandRunner must thread the short git ceiling through to the actual
    # subprocess.run for the default-branch read (mirroring the assembler's read_origin_remote),
    # rather than silently inheriting the 600s mkdocs ceiling. Capture the timeout passed to
    # subprocess.run without spawning a real process.
    captured: dict[str, float | None] = {}

    def _fake_subprocess_run(args, **kwargs):
        captured["timeout"] = kwargs.get("timeout")

        class _CP:
            returncode = 0
            stdout = "main\n"
            stderr = ""

        return _CP()

    monkeypatch.setattr(commands_mod.subprocess, "run", _fake_subprocess_run)
    read_default_branch(str(tmp_path), DefaultCommandRunner())
    assert captured["timeout"] == commands_mod._GIT_BRANCH_READ_TIMEOUT_SECONDS
