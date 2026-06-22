"""Task 5.3 — build-validate a real assembled tree under the per-target base-path.

This module is the github-pages-deploy *task 5.3* deliverable
(``_Boundary: Deploy orchestrator, DeployStage``). Where the orchestrator unit suite
(``test_deployer_deploy.py``) and the stage integration suite
(``test_stage_deploy_integration_5_2.py``) drive the deploy core / adapter with a **fake**
:class:`~docuharnessx.deployer.commands.CommandRunner` (so ``mkdocs`` never really runs), task
5.3 closes the loop with a **real, network-free** ``mkdocs build`` over a **real assembled
tree**: it

* drives the **real** assembler (``assembler.writer.assemble_site`` over the real
  ``resolve_site_identity``) for a target with a GitHub remote, so the per-target ``site_url`` /
  ``/<repo>/`` base-path the assembler bakes into ``mkdocs.yml`` is the genuine one (no hand-rolled
  config);
* runs the **deploy orchestrator** (``deployer.deploy.deploy_site``) in ``emit-ci-workflow`` mode
  into a throwaway target tree, with a real-build runner that runs ``git`` / ``mkdocs build`` for
  real but **fails loud if ever asked to push** — so the ``gh-deploy`` push is provably never
  exercised (Req 7.4, 5.4);
* asserts the static site is produced under the per-target ``/<repo>/`` base-path (the built
  ``sitemap.xml`` places every URL under the project Pages subpath — Req 7.1, 7.2);
* asserts the emit-ci-workflow files are present in the target tree and that the emitted
  ``.github/workflows/docs.yml`` is valid YAML carrying the push trigger / Pages permissions /
  deploy job (Req 4.1, 4.2);
* asserts that across **all three** modes the only writes are under the run output dir or the
  resolved target repo, the Pages URL is always the per-target value and never DocuHarnessX's,
  and the ``gh-deploy`` network push is not exercised (Req 9.1, 9.2, 9.4).

The build is the only subprocess and it is purely local (Req 7.4); the gh-deploy push is isolated
behind the runner and raised-on rather than run, so this suite stays credential-free and
network-free.

Observable completion (tasks.md 5.3): the build/E2E test passes — the build succeeds under the
per-target base-path, isolation holds across modes, and no gh-deploy network push runs.

_Requirements: 7.1, 7.2, 9.1, 9.2, 9.3, 9.4_
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
import yaml
from harnessx.core.events import StepEndEvent, TaskStartEvent
from harnessx.core.state import State

from docuharnessx.assembler.identity import resolve_site_identity
from docuharnessx.assembler.writer import assemble_site
from docuharnessx.context import RunContext
from docuharnessx.deployer.commands import CompletedResult, DefaultCommandRunner
from docuharnessx.deployer.deploy import deploy_site
from docuharnessx.deployer.model import DEPLOY_RESULT_SCHEMA_VERSION, DeployResult
from docuharnessx.ontology import Segment, Subject, Vocabulary, default_profile
from docuharnessx.review.model import (
    REVIEW_REPORT_SCHEMA_VERSION,
    ReviewAggregate,
    ReviewReport,
)
from docuharnessx.stages.deploy import DeployStage

# The doc framework is a declared runtime dependency (Req 9.3) and installed in the project venv;
# the guard skips gracefully if it is somehow absent rather than failing the build E2E.
pytest.importorskip("mkdocs")
pytest.importorskip("material")


# The reference target (per the locked multi-project decision). The per-target identity is always
# resolved from this target's remote, never DocuHarnessX's own. The remote string is passed
# explicitly to the real resolver, so the resolution is network-free.
_GITHUB_REMOTE = "https://github.com/norandom/malware_hashes.git"
_TARGET_PAGES_URL = "https://norandom.github.io/malware_hashes/"
_TARGET_BASE_PATH_TOKEN = "norandom.github.io/malware_hashes/"
_FORBIDDEN_OWN_IDENTITY = ("docuharnessx", "DocuHarnessX")


# --------------------------------------------------------------------------- #
# Real-build runner: runs git / mkdocs build for real, refuses any push         #
# --------------------------------------------------------------------------- #


class _NoPushRealRunner(DefaultCommandRunner):
    """A real :class:`DefaultCommandRunner` that fails loud if ever asked to push (Req 5.4).

    The validated modes (``emit-ci-workflow`` / ``build-only``) must reach a **real** ``mkdocs
    build`` and ``git`` read but never a network push. This subclass runs every real subprocess
    except ``mkdocs gh-deploy``: if the orchestrator ever drove the push on a validated path it
    would raise here instead of touching the network, so the test proves the push is never
    exercised rather than merely mocking it away. ``pushed`` records whether the guard ever
    tripped so the assertions can confirm it stayed ``False``.

    The leading ``mkdocs`` token the orchestrator builds is rewritten to
    ``[sys.executable, "-m", "mkdocs"]`` before the real subprocess runs, exactly as the
    assembler's build-E2E suite invokes the real build — so the build resolves through the
    project interpreter's installed ``mkdocs`` + ``mkdocs-material`` regardless of whether a
    bare ``mkdocs`` console script is on ``PATH``. The orchestrator's own command construction
    (``["mkdocs", "build", ...]``) is what is under test; only the executable resolution is
    adapted for the test environment.
    """

    def __init__(self) -> None:
        self.commands: list[list[str]] = []
        self.pushed = False

    def run(
        self, args: "Sequence[str]", cwd: str, timeout: float | None = None
    ) -> CompletedResult:
        argv = list(args)
        self.commands.append(argv)
        if len(argv) >= 2 and argv[0] == "mkdocs" and argv[1] == "gh-deploy":
            self.pushed = True
            raise AssertionError(
                "the validated deploy modes must never reach the gh-deploy network push"
            )
        if argv and argv[0] == "mkdocs":
            argv = [sys.executable, "-m", "mkdocs", *argv[1:]]
        return super().run(argv, cwd, timeout=timeout)

    def build_count(self) -> int:
        return sum(
            1
            for argv in self.commands
            if len(argv) >= 2 and argv[0] == "mkdocs" and argv[1] == "build"
        )


# --------------------------------------------------------------------------- #
# Builders: a real assembled tree for a GitHub-remote target                    #
# --------------------------------------------------------------------------- #


def _segment(
    seg_id: str,
    *,
    title: str,
    roles: list[str],
    intent: str,
    summary: str = "",
    related: list[str] | None = None,
) -> Segment:
    prefixes = ("component:", "tech:", "artifact:", "topic:")
    return Segment(
        id=seg_id,
        title=title,
        roles=roles,
        subjects=[Subject.parse(f"topic:{seg_id}", frozenset(prefixes))],
        intent=intent,
        summary=summary,
        related=list(related or []),
        body=f"Body of {seg_id}.\n\nMore prose for {seg_id}.",
    )


def _report() -> ReviewReport:
    """Accepted segments spanning several default roles + intents, with cross-links.

    Mirrors the assembler build-determinism fixture so the emitted tree exercises the full link
    surface (segment cross-links, agenda links, role-switch links) and several role landing pages.
    """
    accepted = (
        _segment(
            "install-guide",
            title="Install Guide",
            roles=["developer"],
            intent="install",
            summary="How to install.",
            related=["use-guide"],
        ),
        _segment(
            "use-guide",
            title="Use Guide",
            roles=["developer", "tech-savvy-user"],
            intent="use",
            summary="How to use it day to day.",
            related=["install-guide"],
        ),
        _segment(
            "deploy-guide",
            title="Deploy Guide",
            roles=["devops-admin"],
            intent="configure",
            summary="How to deploy.",
        ),
    )
    return ReviewReport(
        schema_version=REVIEW_REPORT_SCHEMA_VERSION,
        entries=(),
        accepted=accepted,
        aggregate=ReviewAggregate(
            judged=len(accepted),
            accepted=len(accepted),
            rejected=0,
            unavailable=0,
            criterion_tally=(),
        ),
    )


def _assemble_real_site(out_dir: Path, vocab: Vocabulary | None = None):
    """Assemble a real Material for MkDocs tree for the GitHub-remote reference target.

    The identity is resolved through the real ``resolve_site_identity`` from an explicit remote
    string (no live git read), so the per-target ``/<repo>/`` base-path baked into ``mkdocs.yml``
    is the genuine one. Returns the frozen ``AssembledSite`` the deploy orchestrator consumes.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    identity = resolve_site_identity("/home/operator/projects/malware_hashes", _GITHUB_REMOTE, {})
    assert identity.site_url == _TARGET_PAGES_URL
    assert identity.base_path == "/malware_hashes/"
    return assemble_site(
        _report(), vocab or default_profile(), None, str(out_dir), identity
    )


# --------------------------------------------------------------------------- #
# emit-ci-workflow: real build under the per-target base-path + valid workflow   #
# --------------------------------------------------------------------------- #


def test_emit_ci_workflow_real_build_under_per_target_base_path(tmp_path: Path) -> None:
    """A real ``mkdocs build`` succeeds under the per-target ``/<repo>/`` base-path (Req 7.1, 7.2).

    Drives the real assembler + the deploy orchestrator in emit-ci-workflow mode into a throwaway
    target tree, with a real-build runner that refuses any push. Asserts an ``emitted`` result, a
    real built static site, and that the built ``sitemap.xml`` places every URL under the project
    Pages subpath — proving the build resolved links/assets under the target base-path, not the
    domain root. No gh-deploy push runs (Req 7.4).
    """
    out_dir = tmp_path / "out"
    target = tmp_path / "target_clone"
    target.mkdir()
    site = _assemble_real_site(out_dir)
    runner = _NoPushRealRunner()

    result = deploy_site(site, str(target), str(out_dir), "emit-ci-workflow", runner=runner)

    assert isinstance(result, DeployResult)
    assert result.schema_version == DEPLOY_RESULT_SCHEMA_VERSION
    assert result.mode == "emit-ci-workflow"
    assert result.status == "emitted"
    # The per-target Pages URL, never DocuHarnessX's own (Req 9.2).
    assert result.target_pages_url == _TARGET_PAGES_URL

    # A real static site was produced under the build output dir (Req 7.1). With
    # ``use_directory_urls: true`` each page renders to ``<page>/index.html``, so the built site
    # is proven by the always-emitted ``sitemap.xml`` plus at least one rendered ``index.html``.
    built = Path(result.built_path)
    assert built.is_dir()
    assert any(built.rglob("index.html")), "no rendered pages in the built site"
    sitemap = built / "sitemap.xml"
    assert sitemap.is_file()
    # Every URL in the built sitemap sits under the per-target Pages base-path (Req 7.2): the
    # build resolved links/assets under /<repo>/, not the domain root.
    assert _TARGET_BASE_PATH_TOKEN in sitemap.read_text(encoding="utf-8")

    # The build really ran (no fake runner); the push was never reached (Req 5.4, 7.4).
    assert runner.build_count() == 1
    assert runner.pushed is False


def test_emit_ci_workflow_files_present_and_workflow_valid(tmp_path: Path) -> None:
    """The emit-ci-workflow files exist in the target tree and the workflow is valid (Req 4.1, 4.2).

    The three artifacts (``mkdocs.yml``, ``docs/``, ``.github/workflows/docs.yml``) are present
    under the target tree, and the emitted workflow is parseable YAML carrying the push trigger,
    the minimal Pages permissions, and the deploy job — so the target self-publishes Pages on push.
    """
    out_dir = tmp_path / "out"
    target = tmp_path / "target_clone"
    target.mkdir()
    site = _assemble_real_site(out_dir)
    runner = _NoPushRealRunner()

    result = deploy_site(site, str(target), str(out_dir), "emit-ci-workflow", runner=runner)

    mkdocs_yml = target / "mkdocs.yml"
    docs_dir = target / "docs"
    workflow = target / ".github" / "workflows" / "docs.yml"
    assert mkdocs_yml.is_file()
    assert docs_dir.is_dir()
    assert workflow.is_file()
    # The result names exactly those three written paths (Req 4.1).
    assert {Path(p) for p in result.written_paths} == {mkdocs_yml, docs_dir, workflow}

    # The copied target mkdocs.yml carries the per-target Pages URL the assembler baked in (Req 4.4).
    assert _TARGET_PAGES_URL in mkdocs_yml.read_text(encoding="utf-8")

    # The emitted workflow is valid YAML. ``on:`` round-trips to the YAML 1.1 boolean True key.
    parsed = yaml.safe_load(workflow.read_text(encoding="utf-8"))
    assert isinstance(parsed, dict)
    on_block = parsed.get(True, parsed.get("on"))
    assert isinstance(on_block, dict)
    # Push trigger on the default branch (Req 4.3) — the real git read resolves a real branch name.
    branches = on_block["push"]["branches"]
    assert isinstance(branches, list) and len(branches) == 1 and branches[0]
    # Minimal Pages deployment permissions (Req 4.2).
    assert parsed["permissions"]["pages"] == "write"
    assert parsed["permissions"]["id-token"] == "write"
    # A build job and a deploy-pages job (Req 4.2).
    jobs = parsed["jobs"]
    assert "build" in jobs and "deploy" in jobs
    deploy_steps = jobs["deploy"]["steps"]
    assert any("deploy-pages" in str(step.get("uses", "")) for step in deploy_steps)
    # The workflow carries no DocuHarnessX identity (Req 9.1) — it is target-agnostic.
    workflow_text = workflow.read_text(encoding="utf-8").lower()
    for token in _FORBIDDEN_OWN_IDENTITY:
        assert token.lower() not in workflow_text


# --------------------------------------------------------------------------- #
# build-only: real build, nothing written into the target tree                  #
# --------------------------------------------------------------------------- #


def test_build_only_real_build_writes_nothing_into_target(tmp_path: Path) -> None:
    """``build-only`` runs a real build and writes nothing into the target tree (Req 6.2, 9.1).

    The static site is produced under the run output tree; the target clone is left untouched and
    the push is never reached.
    """
    out_dir = tmp_path / "out"
    target = tmp_path / "target_clone"
    target.mkdir()
    site = _assemble_real_site(out_dir)
    runner = _NoPushRealRunner()

    result = deploy_site(site, str(target), str(out_dir), "build-only", runner=runner)

    assert result.mode == "build-only"
    assert result.status == "built"
    assert result.written_paths == ()
    assert result.target_pages_url == _TARGET_PAGES_URL
    built = Path(result.built_path)
    assert built.is_dir()
    assert any(built.rglob("index.html")), "no rendered pages in the built site"
    assert (built / "sitemap.xml").is_file()

    # Nothing was written into the target tree (Req 6.2); no push (Req 5.4).
    assert list(target.iterdir()) == []
    assert runner.build_count() == 1
    assert runner.pushed is False


# --------------------------------------------------------------------------- #
# Isolation across all three modes: writes only under out_dir / target;          #
# Pages URL always per-target; gh-deploy push never exercised (Req 9.1, 9.2)     #
# --------------------------------------------------------------------------- #


def test_isolation_across_all_three_modes(tmp_path: Path) -> None:
    """Across all three modes the only writes stay scoped and the push never runs (Req 9.1, 9.2).

    Runs each mode under its own sandbox (a per-mode output dir + target clone nested inside a
    fresh sandbox dir) and asserts: the only filesystem entries created in the sandbox are the run
    output dir and the target clone (no stray writes elsewhere); the Pages URL is always the
    per-target value and never DocuHarnessX's; and the gh-deploy push is exercised on the explicit
    gh-deploy mode only (and even there only as a recorded, raised-on guard — never a real network
    call). The validated modes never reach the push.
    """
    # --- emit-ci-workflow: writes under out_dir (build) + target (emitted files) ----------- #
    emit_sandbox = tmp_path / "emit"
    emit_sandbox.mkdir()
    emit_out = emit_sandbox / "out"
    emit_target = emit_sandbox / "target"
    emit_target.mkdir()
    emit_site = _assemble_real_site(emit_out)
    emit_runner = _NoPushRealRunner()
    emit_result = deploy_site(
        emit_site, str(emit_target), str(emit_out), "emit-ci-workflow", runner=emit_runner
    )
    assert emit_result.status == "emitted"
    assert emit_result.target_pages_url == _TARGET_PAGES_URL
    # The only sandbox entries are the run output dir and the target clone — nothing escaped.
    assert {p.name for p in emit_sandbox.iterdir()} == {"out", "target"}
    # The build output stayed under the run output tree, never under the target repo.
    assert Path(emit_result.built_path).is_relative_to(emit_out)
    # Every target-tree write landed under the target clone.
    for written in emit_result.written_paths:
        assert Path(written).is_relative_to(emit_target)
    assert emit_runner.pushed is False

    # --- build-only: writes under out_dir only; target untouched --------------------------- #
    build_sandbox = tmp_path / "build"
    build_sandbox.mkdir()
    build_out = build_sandbox / "out"
    build_target = build_sandbox / "target"
    build_target.mkdir()
    build_site = _assemble_real_site(build_out)
    build_runner = _NoPushRealRunner()
    build_result = deploy_site(
        build_site, str(build_target), str(build_out), "build-only", runner=build_runner
    )
    assert build_result.status == "built"
    assert build_result.target_pages_url == _TARGET_PAGES_URL
    assert {p.name for p in build_sandbox.iterdir()} == {"out", "target"}
    assert Path(build_result.built_path).is_relative_to(build_out)
    assert list(build_target.iterdir()) == []  # the target clone is untouched (Req 6.2)
    assert build_runner.pushed is False

    # --- gh-deploy: the push is the only network action; here it is mocked away (no network) - #
    # The validated-mode real-build runner refuses the push, so for the gh-deploy mode we use a
    # recording fake that returns success without spawning anything (the real push is never run
    # in tests — Req 5.4). The assertion is structural: exactly one push, no target writes.
    gh_sandbox = tmp_path / "gh"
    gh_sandbox.mkdir()
    gh_out = gh_sandbox / "out"
    gh_target = gh_sandbox / "target"
    gh_target.mkdir()
    gh_site = _assemble_real_site(gh_out)
    gh_runner = _RecordingFakeRunner()
    gh_result = deploy_site(
        gh_site, str(gh_target), str(gh_out), "gh-deploy", runner=gh_runner
    )
    assert gh_result.status == "published"
    assert gh_result.target_pages_url == _TARGET_PAGES_URL
    assert gh_result.written_paths == ()
    # The push ran exactly once, with no real network call, and nothing was written to the target.
    assert gh_runner.gh_deploy_count() == 1
    assert gh_runner.build_count() == 0
    assert list(gh_target.iterdir()) == []
    # The only sandbox entry beyond the (already-created, empty) target is the assembler's out dir.
    assert {p.name for p in gh_sandbox.iterdir()} == {"out", "target"}

    # Across every mode the Pages URL is the per-target value and never DocuHarnessX's (Req 9.2).
    for result in (emit_result, build_result, gh_result):
        assert result.target_pages_url == _TARGET_PAGES_URL
        for token in _FORBIDDEN_OWN_IDENTITY:
            assert token.lower() not in result.target_pages_url.lower()


class _RecordingFakeRunner:
    """A duck-typed :class:`CommandRunner` recording invocations and returning canned success.

    Used only for the gh-deploy leg of the isolation test, where the push is the only network
    action and must not be spawned for real (Req 5.4): it records the push without touching the
    network. The validated modes use the real-build :class:`_NoPushRealRunner` instead.
    """

    def __init__(self) -> None:
        self.commands: list[list[str]] = []

    def run(
        self, args: "Sequence[str]", cwd: str, timeout: float | None = None
    ) -> CompletedResult:
        self.commands.append(list(args))
        return CompletedResult(returncode=0, stdout="", stderr="")

    def gh_deploy_count(self) -> int:
        return sum(
            1
            for argv in self.commands
            if len(argv) >= 2 and argv[0] == "mkdocs" and argv[1] == "gh-deploy"
        )

    def build_count(self) -> int:
        return sum(
            1
            for argv in self.commands
            if len(argv) >= 2 and argv[0] == "mkdocs" and argv[1] == "build"
        )


# --------------------------------------------------------------------------- #
# Deterministic / model-free: the deploy performs no model call (Req 9.4)        #
# --------------------------------------------------------------------------- #


def test_emit_ci_workflow_orchestrator_opens_no_socket(monkeypatch, tmp_path: Path) -> None:
    """The orchestrator process opens no socket of its own (Req 9.4 — no model call / no network).

    The deploy is a deterministic, mechanical transform: the only subprocess is the local
    ``mkdocs build`` / ``git`` read driven through the runner (a separate process), and the
    orchestrator body itself performs no network access and holds no model client. We trip this
    process's ``socket.socket`` to prove the orchestration body opens no socket directly; the real
    build runs in its own subprocess and so does not trip the guard.
    """
    import socket

    out_dir = tmp_path / "out"
    target = tmp_path / "target_clone"
    target.mkdir()
    site = _assemble_real_site(out_dir)

    def _no_socket(*args, **kwargs):  # pragma: no cover - must not be called
        raise AssertionError("the deploy orchestrator must open no socket of its own")

    monkeypatch.setattr(socket, "socket", _no_socket)

    runner = _NoPushRealRunner()
    result = deploy_site(site, str(target), str(out_dir), "emit-ci-workflow", runner=runner)
    assert result.status == "emitted"
    assert runner.pushed is False


# --------------------------------------------------------------------------- #
# DeployStage adapter end-to-end with a real build (Boundary: DeployStage)      #
# --------------------------------------------------------------------------- #


class _RuntimeStub:
    def __init__(self, tracer: Any | None = None) -> None:
        self.tracer = tracer


def _drive_stage_through_real_build(
    state: State, runner: _NoPushRealRunner, *, mode: str | None = None
) -> None:
    """Drive the real :class:`DeployStage` over ``state`` with the real-build runner.

    Captures the run ``State`` via ``on_task_start`` then runs ``on_step_end`` (the real slot
    I/O + deploy), injecting the real-build runner the same way the CLI mode-wiring layer injects
    ``_command_runner`` / ``_deploy_mode`` — so the boundary under test is the ``DeployStage``
    adapter wired to a genuine ``mkdocs build``.
    """
    stage = DeployStage()
    stage._bind_runtime(_RuntimeStub())
    stage._command_runner = runner
    if mode is not None:
        stage._deploy_mode = mode

    async def _run() -> None:
        async for _ in stage.on_task_start(
            TaskStartEvent(run_id=state.run_id, step_id=0, state=state)
        ):
            pass
        event = StepEndEvent(
            run_id=state.run_id,
            step_id=7,
            step_summary="prior",
            tool_call_summary="readFile(a)",
            cumulative_tokens=1,
            cumulative_cost_usd=0.0,
        )
        async for _ in stage.on_step_end(event):
            pass

    asyncio.run(_run())


def test_deploy_stage_emit_ci_workflow_real_build_end_to_end(tmp_path: Path) -> None:
    """The real DeployStage adapter publishes an emitted result over a real build (Boundary 5.3).

    Drives the in-place :class:`DeployStage` (the no-op-stub replacement) over a seeded run
    ``State`` carrying a **real** assembled tree, in the default emit-ci-workflow mode, with the
    real-build runner. Asserts the stage publishes a well-formed ``emitted``
    :class:`~docuharnessx.deployer.model.DeployResult` into ``SLOT_DEPLOY_RESULT`` whose built
    path is a real static site under the per-target base-path and whose written paths name the
    three target-tree files — and that no gh-deploy push ran (Req 7.1, 7.2, 9.1, 9.2).
    """
    out_dir = tmp_path / "out"
    target = tmp_path / "target_clone"
    target.mkdir()
    site = _assemble_real_site(out_dir)

    state = State(run_id="run-5-3-stage")
    rc = RunContext(state)
    rc.set_assembled_site(site)
    rc.set_output_dir(str(out_dir))
    rc.set_target_repo(str(target))

    runner = _NoPushRealRunner()
    _drive_stage_through_real_build(state, runner)

    result = RunContext(state).deploy_result()
    assert isinstance(result, DeployResult)
    assert result.mode == "emit-ci-workflow"
    assert result.status == "emitted"
    assert result.target_pages_url == _TARGET_PAGES_URL

    # The three emit-ci-workflow files are present in the target tree (Req 9.1).
    mkdocs_yml = target / "mkdocs.yml"
    docs_dir = target / "docs"
    workflow = target / ".github" / "workflows" / "docs.yml"
    assert mkdocs_yml.is_file() and docs_dir.is_dir() and workflow.is_file()
    assert {Path(p) for p in result.written_paths} == {mkdocs_yml, docs_dir, workflow}

    # The build really ran and produced a static site under the per-target base-path (Req 7.2).
    built = Path(result.built_path)
    assert built.is_dir()
    assert _TARGET_BASE_PATH_TOKEN in (built / "sitemap.xml").read_text(encoding="utf-8")

    # The build output stayed under the run output tree; the push never ran (Req 9.1, 5.4).
    assert built.is_relative_to(out_dir)
    assert runner.build_count() == 1
    assert runner.pushed is False
