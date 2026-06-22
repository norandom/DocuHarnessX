"""Task 5.1 — unit-test the deterministic deploy components as one validation suite.

This module is the github-pages-deploy *task 5.1* deliverable (``_Boundary: Deploy-mode
resolver, Workflow renderer, Target-tree writer, Command runner``). Where the per-component
suites (``test_deployer_{mode,workflow,tree,commands}.py``, tasks 2.1–2.4) pin each component
in isolation, task 5.1 asserts the cross-cutting acceptance behaviours the task text
enumerates for the four deterministic components **together**, with the command runner mocked
so no real ``git`` / ``mkdocs`` process is spawned and the ``mkdocs gh-deploy`` push is never
exercised:

* the mode resolver default / passthrough / reject paths (Req 3.1–3.4);
* the workflow renderer's branch trigger, build step, Pages deploy permissions, byte-stability,
  and absence of DocuHarnessX identity (Req 4.2, 4.3, 4.4, 9.1);
* the tree writer's target-only writes and no-git-push behaviour, including the reference
  target ``norandom/malware_hashes`` resolving to its own ``/malware_hashes/`` project subpath,
  never DocuHarnessX's (Req 4.1, 4.5, 4.6, 9.1, 9.2);
* the command runner's branch fallback, build-failure error, the gh-deploy prerequisite error
  naming the missing prerequisite (Req 4.3, 5.3, 7.2, 7.3, 7.4), and — the central task-5.1
  guarantee — that the fake runner is **never asked to push** on the validated modes
  (emit-ci-workflow's branch-read + build sequence and build-only's build).

Observable completion (tasks.md 5.1): the component unit suite passes and asserts each
referenced acceptance behaviour without spawning a real ``git`` or ``mkdocs`` process — every
process touch goes through the injected :class:`_RecordingRunner`, which records its calls and
fails loudly if ever asked to push on a validated path.

_Requirements: 3.1, 3.2, 3.3, 3.4, 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 5.3, 5.4, 7.2, 7.3, 7.4,
9.1, 9.2_
"""

from __future__ import annotations

import os
import typing
from dataclasses import dataclass
from pathlib import Path

import pytest
import yaml

from docuharnessx.assembler.model import (
    ASSEMBLED_SITE_SCHEMA_VERSION,
    AssembledSite,
    SiteIdentity,
)
from docuharnessx.deployer import (
    DeployError,
    DeployInputError,
    DeployMode,
)
from docuharnessx.deployer.commands import (
    CompletedResult,
    read_default_branch,
    run_mkdocs_build,
    run_mkdocs_gh_deploy,
)
from docuharnessx.deployer.mode import resolve_deploy_mode
from docuharnessx.deployer.tree import write_target_tree
from docuharnessx.deployer.workflow import render_pages_workflow

# The reference target the spec names (the steering example). Per-target everything must
# resolve to *this* identity / subpath — never DocuHarnessX's own repo/Pages (Req 9.1, 9.2).
_REFERENCE_REPO = "norandom/malware_hashes"
_REFERENCE_SITE_URL = "https://norandom.github.io/malware_hashes/"
_REFERENCE_BASE_PATH = "/malware_hashes/"
_VALID_MODES: tuple[str, ...] = ("emit-ci-workflow", "gh-deploy", "build-only")


# --------------------------------------------------------------------------- #
# Shared fixtures: reference identity, seeded assembled site, mocked runner     #
# --------------------------------------------------------------------------- #


def _reference_identity() -> SiteIdentity:
    """The resolved per-target identity for the reference target ``norandom/malware_hashes``."""
    return SiteIdentity(
        site_name="malware_hashes",
        repo_name=_REFERENCE_REPO,
        repo_url="https://github.com/norandom/malware_hashes",
        site_url=_REFERENCE_SITE_URL,
        base_path=_REFERENCE_BASE_PATH,
        edit_uri="edit/main/docs/",
    )


_MKDOCS_YML_BODY = (
    "site_name: malware_hashes\n"
    f"site_url: {_REFERENCE_SITE_URL}\n"
    "docs_dir: docs\n"
)
_INDEX_BODY = "# Home\n\nWelcome.\n"
_ROLE_INDEX_BODY = "# Role landing\n\nAgenda.\n"
_WORKFLOW_YAML = "name: Deploy docs to GitHub Pages\non:\n  push:\n    branches: [main]\n"


def _seed_assembled_site(out_root: Path) -> AssembledSite:
    """Seed a representative assembled tree under ``<out_root>/site`` for the reference target."""
    site_dir = out_root / "site"
    docs_dir = site_dir / "docs"
    (docs_dir / "analyst").mkdir(parents=True, exist_ok=True)

    (site_dir / "mkdocs.yml").write_text(_MKDOCS_YML_BODY, encoding="utf-8")
    (docs_dir / "index.md").write_text(_INDEX_BODY, encoding="utf-8")
    (docs_dir / "analyst" / "index.md").write_text(_ROLE_INDEX_BODY, encoding="utf-8")

    return AssembledSite(
        schema_version=ASSEMBLED_SITE_SCHEMA_VERSION,
        site_dir=os.path.abspath(str(site_dir)),
        docs_dir=os.path.abspath(str(docs_dir)),
        mkdocs_yml_path=os.path.abspath(str(site_dir / "mkdocs.yml")),
        identity=_reference_identity(),
        page_count=1,
        role_page_count=1,
    )


@dataclass
class _Invocation:
    args: tuple[str, ...]
    cwd: str
    timeout: float | None = None


class _RecordingRunner:
    """A mocked :class:`CommandRunner` — records every call and never spawns a process.

    Results are popped in order; an ``Exception`` result is raised (to simulate a missing
    executable / non-zero handling), otherwise the :class:`CompletedResult` is returned.

    Central task-5.1 guarantee: ``forbid_push`` (default ``True``) makes the runner assert if a
    ``gh-deploy`` verb ever reaches it — so a validated-mode path (branch read / build) that
    accidentally pushed would fail loudly here rather than silently reaching the network.
    """

    def __init__(self, results: list, *, forbid_push: bool = True) -> None:
        self._results = list(results)
        self.calls: list[_Invocation] = []
        self._forbid_push = forbid_push

    def run(self, args, cwd: str, timeout: float | None = None) -> CompletedResult:
        argv = tuple(args)
        if self._forbid_push:
            assert "gh-deploy" not in argv, (
                "the fake runner was asked to push on a validated mode path"
            )
            assert "push" not in argv, (
                "the fake runner was asked to git-push on a validated mode path"
            )
        self.calls.append(_Invocation(argv, cwd, timeout))
        if not self._results:
            raise AssertionError("RecordingRunner called more times than configured")
        outcome = self._results.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def _ok(stdout: str = "", stderr: str = "") -> CompletedResult:
    return CompletedResult(returncode=0, stdout=stdout, stderr=stderr)


def _fail(returncode: int = 1, stdout: str = "", stderr: str = "boom") -> CompletedResult:
    return CompletedResult(returncode=returncode, stdout=stdout, stderr=stderr)


def _site(tmp_path: Path) -> AssembledSite:
    return _seed_assembled_site(tmp_path / "out")


# =========================================================================== #
# Deploy-mode resolver — default / passthrough / reject (Req 3.1–3.4)          #
# =========================================================================== #


@pytest.mark.parametrize("absent", [None, "", "   ", "\t", "\n"])
def test_mode_resolver_defaults_to_emit_ci_workflow(absent) -> None:
    # Req 3.2 — absent / empty / whitespace-only defaults to the emit-ci-workflow mode.
    assert resolve_deploy_mode(absent) == "emit-ci-workflow"


@pytest.mark.parametrize("mode", _VALID_MODES)
def test_mode_resolver_passes_through_each_valid_mode(mode: str) -> None:
    # Req 3.3 — a recognised value passes through unchanged.
    assert resolve_deploy_mode(mode) == mode


def test_mode_resolver_admits_exactly_the_three_modes() -> None:
    # Req 3.1 — the resolver admits exactly the three DeployMode literal members.
    assert set(typing.get_args(DeployMode)) == set(_VALID_MODES)
    for mode in typing.get_args(DeployMode):
        assert resolve_deploy_mode(mode) == mode


def test_mode_resolver_rejects_unknown_value_naming_bad_and_valid() -> None:
    # Req 3.4 — an unknown value raises DeployInputError naming the bad value and valid modes.
    with pytest.raises(DeployInputError) as exc_info:
        resolve_deploy_mode("publish-now")
    message = str(exc_info.value)
    assert "publish-now" in message
    for valid in _VALID_MODES:
        assert valid in message


# =========================================================================== #
# Workflow renderer — branch trigger, build step, Pages perms, byte-stability, #
# and no DocuHarnessX identity (Req 4.2, 4.3, 4.4, 9.1)                         #
# =========================================================================== #


def _on_block(doc: dict) -> dict:
    # PyYAML parses the bare ``on:`` key as boolean True (YAML 1.1); accept either spelling.
    return doc["on"] if "on" in doc else doc[True]


def _all_steps(jobs: dict) -> list[dict]:
    steps: list[dict] = []
    for job in jobs.values():
        steps.extend(job.get("steps", []))
    return steps


def test_workflow_triggers_on_the_threaded_default_branch() -> None:
    # Req 4.3 — the push trigger follows the per-target default branch threaded in by the
    # caller (never re-parsed from the remote — Req 4.4).
    doc = yaml.safe_load(render_pages_workflow(_reference_identity(), "release"))
    assert _on_block(doc)["push"]["branches"] == ["release"]


def test_workflow_has_a_build_step_and_pages_deploy_permissions() -> None:
    # Req 4.2 — a build step (mkdocs build) and the minimal Pages deploy permissions.
    doc = yaml.safe_load(render_pages_workflow(_reference_identity(), "main"))
    runs = "\n".join(
        s["run"] for s in _all_steps(doc["jobs"]) if isinstance(s, dict) and "run" in s
    )
    uses = [
        s["uses"] for s in _all_steps(doc["jobs"]) if isinstance(s, dict) and "uses" in s
    ]
    assert "mkdocs build" in runs
    assert any(u.startswith("actions/deploy-pages@") for u in uses)
    perms = doc["permissions"]
    assert perms.get("pages") == "write"
    assert perms.get("id-token") == "write"


def test_workflow_is_byte_stable_for_equal_inputs() -> None:
    # Req 4.2 — identical inputs render byte-identical YAML.
    a = render_pages_workflow(_reference_identity(), "main")
    b = render_pages_workflow(_reference_identity(), "main")
    assert a == b


def test_workflow_carries_no_docuharnessx_identity_and_is_target_agnostic() -> None:
    # Req 9.1 / 4.4 — the workflow body embeds no DocuHarnessX identity and no per-target
    # value (those live in the assembled mkdocs.yml), so two distinct targets render the same
    # workflow for the same branch.
    other = SiteIdentity(
        site_name="other_project",
        repo_name="someone/other_project",
        repo_url="https://github.com/someone/other_project",
        site_url="https://someone.github.io/other_project/",
        base_path="/other_project/",
        edit_uri="edit/main/docs/",
    )
    ref_body = render_pages_workflow(_reference_identity(), "main")
    other_body = render_pages_workflow(other, "main")
    assert ref_body == other_body
    lowered = ref_body.lower()
    assert "docuharnessx" not in lowered
    assert "malware_hashes" not in ref_body
    assert "norandom" not in ref_body


# =========================================================================== #
# Target-tree writer — target-only writes, no git push, and the reference      #
# target resolving to its own project subpath (Req 4.1, 4.5, 4.6, 9.1, 9.2)    #
# =========================================================================== #


def test_tree_writer_writes_only_under_the_target_and_returns_three_paths(tmp_path) -> None:
    # Req 4.1 / 4.6 / 9.1 — exactly the three artifacts under the passed target, nowhere else.
    site = _site(tmp_path)
    target = tmp_path / "target"
    target.mkdir()

    out_root = tmp_path / "out"
    src_before = {str(p): p.read_bytes() for p in out_root.rglob("*") if p.is_file()}

    written = write_target_tree(site, str(target), _WORKFLOW_YAML)

    assert len(written) == 3
    assert (target / "mkdocs.yml").is_file()
    assert (target / "docs" / "index.md").is_file()
    assert (target / ".github" / "workflows" / "docs.yml").is_file()

    # the assembled source tree is untouched (verbatim read-only copy)
    src_after = {str(p): p.read_bytes() for p in out_root.rglob("*") if p.is_file()}
    assert src_before == src_after

    # every written path lives under the target dir, nowhere else
    target_resolved = target.resolve()
    for p in written:
        assert target_resolved in Path(p).resolve().parents


def test_tree_writer_performs_no_git_push_or_commit(tmp_path, monkeypatch) -> None:
    # Req 4.5 — the writer is pure filesystem I/O; any subprocess use is a regression.
    import subprocess

    def _boom(*args, **kwargs):  # pragma: no cover - only fires on a regression
        raise AssertionError("write_target_tree must not spawn a subprocess (no git push/commit)")

    monkeypatch.setattr(subprocess, "run", _boom)
    monkeypatch.setattr(subprocess, "Popen", _boom)
    monkeypatch.setattr(subprocess, "check_call", _boom)
    monkeypatch.setattr(subprocess, "check_output", _boom)

    site = _site(tmp_path)
    target = tmp_path / "target"
    target.mkdir()
    # a pre-existing .git must be left untouched (no commit/push happened)
    (target / ".git").mkdir()
    head = target / ".git" / "HEAD"
    head.write_text("ref: refs/heads/main\n", encoding="utf-8")

    write_target_tree(site, str(target), _WORKFLOW_YAML)

    assert head.read_text(encoding="utf-8") == "ref: refs/heads/main\n"


def test_reference_target_resolves_to_its_own_project_subpath(tmp_path) -> None:
    # Req 9.1 / 9.2 — the copied mkdocs.yml carries the reference target's per-target site_url /
    # /<repo>/ subpath (assembler-resolved), never DocuHarnessX's, and the written paths name
    # the resolved target dir, not DocuHarnessX's repo.
    site = _site(tmp_path)
    target = tmp_path / "target"
    target.mkdir()
    written = write_target_tree(site, str(target), _WORKFLOW_YAML)

    mkdocs = (target / "mkdocs.yml").read_text(encoding="utf-8")
    assert _REFERENCE_SITE_URL in mkdocs
    assert "norandom.github.io/malware_hashes" in mkdocs
    assert "docuharnessx" not in mkdocs.lower()
    for p in written:
        assert "DocuHarnessX" not in p


# =========================================================================== #
# Command runner — branch fallback, build-failure error, gh-deploy prereq      #
# error, and never-push-on-validated-modes (Req 4.3, 5.3, 5.4, 7.2, 7.3, 7.4)  #
# =========================================================================== #


def test_branch_read_falls_back_to_main_when_git_fails(tmp_path) -> None:
    # Req 4.3 — both reads fail (no git / detached / no remote) → graceful "main" fallback.
    runner = _RecordingRunner([FileNotFoundError("no git"), FileNotFoundError("no git")])
    assert read_default_branch(str(tmp_path), runner) == "main"


def test_branch_read_returns_the_target_branch_when_available(tmp_path) -> None:
    # Req 4.3 — a successful symbolic-ref read returns the target's actual branch (read-only).
    runner = _RecordingRunner([_ok(stdout="trunk\n")])
    assert read_default_branch(str(tmp_path), runner) == "trunk"
    assert runner.calls[0].args[0] == "git"


def test_build_validation_raises_deploy_error_on_nonzero_exit(tmp_path) -> None:
    # Req 7.3 — a non-zero mkdocs build exit raises a fail-loud DeployError naming the build.
    site = _site(tmp_path)
    runner = _RecordingRunner([_fail(returncode=2, stderr="config error")])
    with pytest.raises(DeployError) as exc_info:
        run_mkdocs_build(site, runner)
    assert "build" in str(exc_info.value).lower()


def test_build_validation_targets_the_assembled_per_target_config(tmp_path) -> None:
    # Req 7.2 — the validation build is driven against the assembled mkdocs.yml, whose
    # per-target site_url / base-path is already baked in (never DocuHarnessX's).
    site = _site(tmp_path)
    runner = _RecordingRunner([_ok()])
    built = run_mkdocs_build(site, runner)
    flat = " ".join(runner.calls[0].args)
    assert "build" in runner.calls[0].args
    assert site.mkdocs_yml_path in flat
    assert os.path.isabs(built)


def test_gh_deploy_error_names_the_missing_prerequisite(tmp_path) -> None:
    # Req 5.3 — a failed gh-deploy raises a DeployError that names the missing prerequisite
    # (no git remote / no push access) so the stage never silently succeeds. The push runner
    # explicitly permits the gh-deploy verb (forbid_push=False) since this *is* the push path.
    site = _site(tmp_path)
    runner = _RecordingRunner(
        [_fail(stderr="fatal: No configured push destination")], forbid_push=False
    )
    with pytest.raises(DeployError) as exc_info:
        run_mkdocs_gh_deploy(site, runner)
    message = str(exc_info.value).lower()
    assert "gh-deploy" in message
    # names the missing prerequisite: a git remote and/or push access.
    assert "remote" in message
    assert "push access" in message


def test_fake_runner_is_never_asked_to_push_on_the_validated_modes(tmp_path) -> None:
    # Central task-5.1 guarantee (Req 5.4, 7.4): the validated modes — emit-ci-workflow's
    # branch-read + build sequence and build-only's build — must never reach the push surface.
    # The _RecordingRunner asserts on any gh-deploy/push verb, so this drives both validated
    # paths through a push-forbidding runner and confirms no push was ever attempted.
    site = _site(tmp_path)

    # emit-ci-workflow component sequence: read the default branch, then build-validate.
    emit_runner = _RecordingRunner([_ok(stdout="main\n"), _ok()])
    branch = read_default_branch(str(tmp_path), emit_runner)
    assert branch == "main"
    run_mkdocs_build(site, emit_runner)

    # build-only component: build-validate only.
    build_runner = _RecordingRunner([_ok()])
    run_mkdocs_build(site, build_runner)

    # No push verb ever reached either runner (the runner would have asserted); double-check.
    for runner in (emit_runner, build_runner):
        for call in runner.calls:
            assert "gh-deploy" not in call.args
            assert "push" not in call.args


def test_build_validation_performs_no_network_action(tmp_path) -> None:
    # Req 7.4 — build validation goes only through the injected runner (no real subprocess),
    # and the single recorded call is the local mkdocs build, not a network push.
    site = _site(tmp_path)
    runner = _RecordingRunner([_ok()])
    run_mkdocs_build(site, runner)
    assert len(runner.calls) == 1
    assert "gh-deploy" not in runner.calls[0].args
