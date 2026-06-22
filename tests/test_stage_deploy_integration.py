"""Credential-free stage integration tests for the real Deploy stage (github-pages-deploy task 4.1).

This suite drives the **real** :class:`~docuharnessx.stages.deploy.DeployStage` — the thin
HarnessX adapter that replaces the no-op ``deploy`` stub in place — over a seeded run
``State`` with an injected **fake** :class:`~docuharnessx.deployer.commands.CommandRunner`, so
no real ``git`` / ``mkdocs`` process is spawned and the ``gh-deploy`` push is never exercised.
It mirrors ``tests/test_stage_assemble_integration.py`` (the sibling Assemble adapter test):
the stage is driven directly through ``on_task_start`` (to capture the run ``State``) +
``on_step_end`` (the real slot I/O), so the boundary under test stays the ``DeployStage``
adapter rather than the whole pipeline.

Task 4.1 pins (design "DeployStage", Req 1.1-1.4, 2.1-2.5, 8.1):

* with a bound run ``State`` carrying a seeded :class:`AssembledSite`, an output dir, and a
  target path -> the default mode (``emit-ci-workflow``) writes the three target-tree files,
  runs the (mocked) build, publishes a well-formed :class:`DeployResult` to
  ``SLOT_DEPLOY_RESULT``, and yields the lifecycle event unchanged;
* ``build-only`` writes nothing into the target tree and yields a ``built`` result;
* ``gh-deploy`` invokes the mocked push exactly once and yields a ``published`` result with
  no real network call;
* a missing assembled-site / output-dir / target-repo slot, an unsupported ``AssembledSite``
  schema version, and an unsupported configured mode each raise the fatal
  :class:`DeployInputError` and publish **no** result;
* driven outside a harness (no ``task_start`` to bind a run ``State``) the stage forwards the
  event unchanged and produces nothing, exactly like the no-op base (Req 1.3).
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Sequence

import pytest
from harnessx.core.events import StepEndEvent, TaskStartEvent
from harnessx.core.state import State

from docuharnessx.assembler.model import (
    ASSEMBLED_SITE_SCHEMA_VERSION,
    AssembledSite,
    SiteIdentity,
)
from docuharnessx.context import RunContext
from docuharnessx.deployer.commands import CompletedResult
from docuharnessx.deployer.model import (
    DEPLOY_RESULT_SCHEMA_VERSION,
    DeployInputError,
    DeployResult,
)
from docuharnessx.stages.deploy import (
    STAGE_NAME,
    DeployStage,
    make_deploy_stage,
)


# --------------------------------------------------------------------------- #
# Harness-free drivers + a runtime stub (mirror test_stage_assemble_integration)
# --------------------------------------------------------------------------- #


class _RuntimeStub:
    def __init__(self, tracer: Any | None = None) -> None:
        self.tracer = tracer


class _FakeRunner:
    """A duck-typed :class:`CommandRunner` that records every invocation.

    Returns a canned success result so no real ``git`` / ``mkdocs`` process is spawned and the
    ``gh-deploy`` push is never reached (Req 5.4, 7.4). ``invocations`` records ``(args, cwd)``
    so tests can assert exactly which subprocesses the stage drove.
    """

    def __init__(self) -> None:
        self.invocations: list[tuple[list[str], str]] = []

    def run(
        self, args: "Sequence[str]", cwd: str, timeout: float | None = None
    ) -> CompletedResult:
        self.invocations.append((list(args), cwd))
        return CompletedResult(returncode=0, stdout="", stderr="")

    def commands(self) -> list[str]:
        return [args[0] if args else "" for args, _cwd in self.invocations]

    def gh_deploy_count(self) -> int:
        return sum(
            1
            for args, _cwd in self.invocations
            if len(args) >= 2 and args[0] == "mkdocs" and args[1] == "gh-deploy"
        )


def _start_task(stage: DeployStage, state: State) -> None:
    async def _collect() -> None:
        async for _ in stage.on_task_start(
            TaskStartEvent(run_id=state.run_id, step_id=0, state=state)
        ):
            pass

    asyncio.run(_collect())


def _bound_stage(
    state: State,
    *,
    runner: _FakeRunner,
    mode: str | None = None,
    tracer: Any | None = None,
) -> DeployStage:
    stage = DeployStage()
    stage._bind_runtime(_RuntimeStub(tracer))
    # Inject the fake command runner + configured mode through the per-instance accessors the
    # stage reads (the way ReviewStage reads its bound _model_config).
    stage._command_runner = runner
    if mode is not None:
        stage._deploy_mode = mode
    _start_task(stage, state)
    return stage


def _sample_event() -> StepEndEvent:
    return StepEndEvent(
        run_id="run-deploy",
        step_id=9,
        step_summary="prior summary",
        tool_call_summary="readFile(a)",
        cumulative_tokens=10,
        cumulative_cost_usd=0.1,
    )


def _drive(stage: DeployStage, event: StepEndEvent) -> list[Any]:
    async def _collect() -> list[Any]:
        return [out async for out in stage.on_step_end(event)]

    return asyncio.run(_collect())


# --------------------------------------------------------------------------- #
# Fixtures: a seeded AssembledSite written under <out>/site                     #
# --------------------------------------------------------------------------- #


def _identity() -> SiteIdentity:
    return SiteIdentity(
        site_name="malware_hashes",
        repo_name="norandom/malware_hashes",
        repo_url="https://github.com/norandom/malware_hashes.git",
        site_url="https://norandom.github.io/malware_hashes/",
        base_path="/malware_hashes/",
        edit_uri="edit/main/docs/",
    )


def _seed_assembled_site(
    out_dir: Path, *, schema_version: int = ASSEMBLED_SITE_SCHEMA_VERSION
) -> AssembledSite:
    """Write a minimal site tree under ``<out>/site`` and return the frozen seam.

    The tree is a real (tiny) MkDocs source so the path fields are valid; the build itself is
    mocked through the fake runner, so the actual files only need to exist for the seam to be
    well-formed.
    """
    site_dir = out_dir / "site"
    docs_dir = site_dir / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    (docs_dir / "index.md").write_text("# Home\n", encoding="utf-8")
    mkdocs_yml = site_dir / "mkdocs.yml"
    mkdocs_yml.write_text("site_name: malware_hashes\n", encoding="utf-8")
    return AssembledSite(
        schema_version=schema_version,
        site_dir=str(site_dir),
        docs_dir=str(docs_dir),
        mkdocs_yml_path=str(mkdocs_yml),
        identity=_identity(),
        page_count=1,
        role_page_count=0,
    )


def _seed_state(
    *,
    run_id: str,
    out_dir: str,
    target_repo: str,
    site: AssembledSite | None,
    set_output: bool = True,
    set_target: bool = True,
) -> State:
    state = State(run_id=run_id)
    rc = RunContext(state)
    if site is not None:
        rc.set_assembled_site(site)
    if set_output:
        rc.set_output_dir(out_dir)
    if set_target:
        rc.set_target_repo(target_repo)
    return state


# --------------------------------------------------------------------------- #
# Happy path: default mode emit-ci-workflow                                     #
# --------------------------------------------------------------------------- #


def test_default_mode_emits_files_builds_and_publishes_result(tmp_path) -> None:
    out_dir = tmp_path / "out"
    target = tmp_path / "repo"
    target.mkdir()
    site = _seed_assembled_site(out_dir)
    state = _seed_state(
        run_id="run-emit",
        out_dir=str(out_dir),
        target_repo=str(target),
        site=site,
    )
    runner = _FakeRunner()
    # No mode configured -> the stage defaults to emit-ci-workflow (Req 3.2).
    stage = _bound_stage(state, runner=runner)
    event = _sample_event()
    out = _drive(stage, event)

    # The lifecycle event is forwarded unchanged (Req 1.4).
    assert out == [event]
    assert out[0] is event

    result = RunContext(state).deploy_result()
    assert isinstance(result, DeployResult)
    assert result.schema_version == DEPLOY_RESULT_SCHEMA_VERSION
    assert result.mode == "emit-ci-workflow"
    assert result.status == "emitted"
    # The per-target Pages URL, never DocuHarnessX's own (Req 9.2).
    assert result.target_pages_url == "https://norandom.github.io/malware_hashes/"
    # The three target-tree files: mkdocs.yml + docs/ + the workflow.
    assert len(result.written_paths) == 3
    assert result.built_path != ""

    # The three artifacts exist under the target tree, and nowhere else (Req 4.1, 4.2, 4.6).
    assert (target / "mkdocs.yml").is_file()
    assert (target / "docs").is_dir()
    assert (target / ".github" / "workflows" / "docs.yml").is_file()

    # The build was driven (mocked); the gh-deploy push was never reached (Req 5.4, 7.4).
    assert "mkdocs" in runner.commands()
    assert runner.gh_deploy_count() == 0


# --------------------------------------------------------------------------- #
# build-only mode                                                              #
# --------------------------------------------------------------------------- #


def test_build_only_writes_nothing_into_target_and_yields_built(tmp_path) -> None:
    out_dir = tmp_path / "out"
    target = tmp_path / "repo"
    target.mkdir()
    site = _seed_assembled_site(out_dir)
    state = _seed_state(
        run_id="run-build",
        out_dir=str(out_dir),
        target_repo=str(target),
        site=site,
    )
    runner = _FakeRunner()
    stage = _bound_stage(state, runner=runner, mode="build-only")
    _drive(stage, _sample_event())

    result = RunContext(state).deploy_result()
    assert result.mode == "build-only"
    assert result.status == "built"
    assert result.written_paths == ()
    assert result.built_path != ""

    # Nothing written into the target tree (Req 6.2).
    assert not (target / "mkdocs.yml").exists()
    assert not (target / ".github").exists()
    assert runner.gh_deploy_count() == 0


# --------------------------------------------------------------------------- #
# gh-deploy mode: the mocked push is invoked exactly once                       #
# --------------------------------------------------------------------------- #


def test_gh_deploy_invokes_mocked_push_exactly_once_and_yields_published(
    tmp_path,
) -> None:
    out_dir = tmp_path / "out"
    target = tmp_path / "repo"
    target.mkdir()
    site = _seed_assembled_site(out_dir)
    state = _seed_state(
        run_id="run-gh",
        out_dir=str(out_dir),
        target_repo=str(target),
        site=site,
    )
    runner = _FakeRunner()
    stage = _bound_stage(state, runner=runner, mode="gh-deploy")
    _drive(stage, _sample_event())

    result = RunContext(state).deploy_result()
    assert result.mode == "gh-deploy"
    assert result.status == "published"
    assert result.written_paths == ()
    assert result.built_path == ""
    # The mocked push ran exactly once (Req 5.1, 5.4); no real network call happens under the
    # fake runner.
    assert runner.gh_deploy_count() == 1
    # gh-deploy mode writes nothing into the target tree.
    assert not (target / ".github").exists()


# --------------------------------------------------------------------------- #
# Fatal input paths: missing slot / unsupported version / bad mode -> no result #
# --------------------------------------------------------------------------- #


def test_missing_assembled_site_raises_and_publishes_no_result(tmp_path) -> None:
    state = _seed_state(
        run_id="run-no-site",
        out_dir=str(tmp_path / "out"),
        target_repo=str(tmp_path / "repo"),
        site=None,
    )
    runner = _FakeRunner()
    stage = _bound_stage(state, runner=runner)
    with pytest.raises(DeployInputError):
        _drive(stage, _sample_event())
    assert RunContext(state).deploy_result() is None
    assert runner.invocations == []


def test_missing_output_dir_raises_and_publishes_no_result(tmp_path) -> None:
    out_dir = tmp_path / "out"
    site = _seed_assembled_site(out_dir)
    state = _seed_state(
        run_id="run-no-out",
        out_dir=str(out_dir),
        target_repo=str(tmp_path / "repo"),
        site=site,
        set_output=False,
    )
    runner = _FakeRunner()
    stage = _bound_stage(state, runner=runner)
    with pytest.raises(DeployInputError):
        _drive(stage, _sample_event())
    assert RunContext(state).deploy_result() is None
    assert runner.invocations == []


def test_missing_target_repo_raises_and_publishes_no_result(tmp_path) -> None:
    out_dir = tmp_path / "out"
    site = _seed_assembled_site(out_dir)
    state = _seed_state(
        run_id="run-no-target",
        out_dir=str(out_dir),
        target_repo=str(tmp_path / "repo"),
        site=site,
        set_target=False,
    )
    runner = _FakeRunner()
    stage = _bound_stage(state, runner=runner)
    with pytest.raises(DeployInputError):
        _drive(stage, _sample_event())
    assert RunContext(state).deploy_result() is None
    assert runner.invocations == []


def test_unsupported_assembled_site_version_raises_and_publishes_no_result(
    tmp_path,
) -> None:
    out_dir = tmp_path / "out"
    target = tmp_path / "repo"
    target.mkdir()
    site = _seed_assembled_site(
        out_dir, schema_version=ASSEMBLED_SITE_SCHEMA_VERSION + 999
    )
    state = _seed_state(
        run_id="run-bad-version",
        out_dir=str(out_dir),
        target_repo=str(target),
        site=site,
    )
    runner = _FakeRunner()
    stage = _bound_stage(state, runner=runner)
    with pytest.raises(DeployInputError):
        _drive(stage, _sample_event())
    assert RunContext(state).deploy_result() is None
    assert runner.invocations == []


def test_unsupported_mode_raises_and_publishes_no_result(tmp_path) -> None:
    out_dir = tmp_path / "out"
    target = tmp_path / "repo"
    target.mkdir()
    site = _seed_assembled_site(out_dir)
    state = _seed_state(
        run_id="run-bad-mode",
        out_dir=str(out_dir),
        target_repo=str(target),
        site=site,
    )
    runner = _FakeRunner()
    stage = _bound_stage(state, runner=runner, mode="push-to-prod")
    with pytest.raises(DeployInputError):
        _drive(stage, _sample_event())
    assert RunContext(state).deploy_result() is None
    # The bad mode is rejected before any subprocess (Req 3.4).
    assert runner.invocations == []


# --------------------------------------------------------------------------- #
# Out-of-harness pass-through: no bound State -> forward event, no result        #
# --------------------------------------------------------------------------- #


def test_out_of_harness_drive_forwards_event_and_produces_nothing() -> None:
    stage = make_deploy_stage()  # never task_start'd, no runtime bound
    event = _sample_event()
    out = _drive(stage, event)
    assert len(out) == 1
    assert out[0] is event


def test_out_of_harness_drive_does_not_raise_even_with_runtime_bound() -> None:
    stage = DeployStage()
    stage._bind_runtime(_RuntimeStub())
    event = _sample_event()
    out = _drive(stage, event)
    assert len(out) == 1
    assert out[0] is event


def test_process_entrypoint_is_a_passthrough_off_harness() -> None:
    stage = make_deploy_stage()
    event = _sample_event()

    async def _collect() -> list[Any]:
        return [out async for out in stage.process(event)]

    out = asyncio.run(_collect())
    assert len(out) == 1
    assert out[0] is event


# --------------------------------------------------------------------------- #
# Default command runner: absent injection -> a DefaultCommandRunner is used     #
# --------------------------------------------------------------------------- #


def test_command_runner_defaults_to_default_command_runner() -> None:
    from docuharnessx.deployer.commands import DefaultCommandRunner

    stage = DeployStage()
    assert isinstance(stage._resolve_command_runner(), DefaultCommandRunner)


# --------------------------------------------------------------------------- #
# Stable replaceability: unchanged public surface (Req 1.1, 1.2)               #
# --------------------------------------------------------------------------- #


def test_public_surface_names_are_stable() -> None:
    import docuharnessx.stages.deploy as deploy_module
    from docuharnessx.stages.base import NoOpStage

    assert STAGE_NAME == "deploy"
    assert DeployStage.__name__ == "DeployStage"
    assert DeployStage.stage_name == "deploy"
    assert make_deploy_stage.__name__ == "make_deploy_stage"
    assert deploy_module.__name__ == "docuharnessx.stages.deploy"
    assert "make_noop_stage" in deploy_module.__all__
    for name in ("STAGE_NAME", "DeployStage", "make_deploy_stage"):
        assert name in deploy_module.__all__
    assert issubclass(DeployStage, NoOpStage)
    instance = make_deploy_stage()
    assert isinstance(instance, DeployStage)


def test_registry_and_bundle_need_no_edits() -> None:
    from docuharnessx.stages import STAGES, stage_class_for

    names = [name for name, _ in STAGES]
    assert names == [
        "ingest",
        "analyze",
        "classify",
        "plan",
        "write",
        "review",
        "assemble",
        "deploy",
    ]
    assert dict(STAGES)["deploy"] is make_deploy_stage
    assert stage_class_for("deploy") is DeployStage
