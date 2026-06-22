"""Tests for the bounded Deploy-stage journal summary (github-pages-deploy task 4.2).

Task 4.2 makes :meth:`~docuharnessx.stages.deploy.DeployStage.on_step_end` emit a single,
*bounded* ``ProcessorTriggerEvent`` to the run tracer (reusing the ``NoOpStage`` tracer
resolution) carrying a **summary-level** detail only: the stage name, the resolved deploy
``mode``, the ``status``, the per-target ``target_pages_url``, the count of files written into
the target tree (``written_path_count``), and a boolean ``built`` flag. It never writes full
written-path lists, page bodies, or the site tree to the trace, and it is a no-op when no tracer
is bound (Req 8.2).

These tests are credential-free and harness-free: ``on_step_end`` is driven directly with a tiny
capturing-tracer runtime stub bound via ``_bind_runtime`` (exactly like
``tests/test_stage_review_journal.py`` / ``tests/test_stage_write_journal.py``). The deploy-input
slots are seeded on a real run ``State`` and captured through
:meth:`~docuharnessx.stages.deploy.DeployStage.on_task_start`; an injected **fake**
:class:`~docuharnessx.deployer.commands.CommandRunner` returns canned success so no real ``git`` /
``mkdocs`` process is spawned and the ``gh-deploy`` push is never exercised (Req 5.4, 7.4).
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Sequence

from harnessx.core.events import ProcessorTriggerEvent, StepEndEvent, TaskStartEvent
from harnessx.core.state import State

from docuharnessx.assembler.model import (
    ASSEMBLED_SITE_SCHEMA_VERSION,
    AssembledSite,
    SiteIdentity,
)
from docuharnessx.context import RunContext
from docuharnessx.deployer.commands import CompletedResult
from docuharnessx.deployer.model import DeployResult
from docuharnessx.stages.base import STAGE_PARTICIPATION_ACTION
from docuharnessx.stages.deploy import STAGE_NAME, DeployStage


# --------------------------------------------------------------------------- #
# Harness-free drivers + a capturing-tracer runtime stub + a fake runner        #
# --------------------------------------------------------------------------- #


class _CapturingTracer:
    """A minimal tracer that records every event ``on_event`` is called with."""

    def __init__(self) -> None:
        self.events: list[Any] = []

    async def on_event(self, event: Any) -> None:
        self.events.append(event)


class _RuntimeStub:
    def __init__(self, tracer: Any | None) -> None:
        self.tracer = tracer


class _FakeRunner:
    """A duck-typed :class:`CommandRunner` returning canned success (no real subprocess)."""

    def __init__(self) -> None:
        self.invocations: list[tuple[list[str], str]] = []

    def run(
        self, args: "Sequence[str]", cwd: str, timeout: float | None = None
    ) -> CompletedResult:
        self.invocations.append((list(args), cwd))
        return CompletedResult(returncode=0, stdout="", stderr="")


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
    stage._command_runner = runner
    if mode is not None:
        stage._deploy_mode = mode
    _start_task(stage, state)
    return stage


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


def _seed_assembled_site(out_dir: Path) -> AssembledSite:
    site_dir = out_dir / "site"
    docs_dir = site_dir / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    (docs_dir / "index.md").write_text("# Home\n", encoding="utf-8")
    mkdocs_yml = site_dir / "mkdocs.yml"
    mkdocs_yml.write_text("site_name: malware_hashes\n", encoding="utf-8")
    return AssembledSite(
        schema_version=ASSEMBLED_SITE_SCHEMA_VERSION,
        site_dir=str(site_dir),
        docs_dir=str(docs_dir),
        mkdocs_yml_path=str(mkdocs_yml),
        identity=_identity(),
        page_count=1,
        role_page_count=0,
    )


def _seed_state(*, run_id: str, out_dir: str, target_repo: str) -> State:
    state = State(run_id=run_id)
    rc = RunContext(state)
    rc.set_assembled_site(_seed_assembled_site(Path(out_dir)))
    rc.set_output_dir(out_dir)
    rc.set_target_repo(target_repo)
    return state


def _triggers(tracer: _CapturingTracer) -> list[ProcessorTriggerEvent]:
    return [e for e in tracer.events if isinstance(e, ProcessorTriggerEvent)]


def _deploy_trigger(tracer: _CapturingTracer) -> ProcessorTriggerEvent:
    triggers = [
        e
        for e in _triggers(tracer)
        if e.action == STAGE_PARTICIPATION_ACTION
        and e.detail.get("stage") == STAGE_NAME
    ]
    assert len(triggers) == 1, f"expected exactly one Deploy trigger, got {triggers!r}"
    return triggers[0]


# --------------------------------------------------------------------------- #
# Records exactly one bounded Deploy-stage trigger with the summary fields       #
# --------------------------------------------------------------------------- #


def test_records_one_bounded_deploy_trigger_with_summary_fields(tmp_path) -> None:
    out_dir = tmp_path / "out"
    target = tmp_path / "repo"
    target.mkdir()
    state = _seed_state(
        run_id="run-deploy", out_dir=str(out_dir), target_repo=str(target)
    )
    tracer = _CapturingTracer()
    # No mode configured -> default emit-ci-workflow.
    stage = _bound_stage(state, runner=_FakeRunner(), tracer=tracer)

    _drive(stage, _sample_event())

    trigger = _deploy_trigger(tracer)
    # A real participation trigger bound to the pipeline hook + this processor.
    assert trigger.processor == "DeployStage"
    assert trigger.run_id == "run-deploy"
    assert trigger.step_id == 9

    detail = trigger.detail
    assert detail["stage"] == STAGE_NAME
    assert detail["mode"] == "emit-ci-workflow"
    assert detail["status"] == "emitted"
    # The per-target Pages URL, never DocuHarnessX's own.
    assert detail["target_pages_url"] == "https://norandom.github.io/malware_hashes/"
    # The three target-tree files: mkdocs.yml + docs/ + the workflow.
    assert detail["written_path_count"] == 3
    assert detail["built"] is True


def test_journal_summary_matches_published_deploy_result(tmp_path) -> None:
    out_dir = tmp_path / "out"
    target = tmp_path / "repo"
    target.mkdir()
    state = _seed_state(
        run_id="run-match", out_dir=str(out_dir), target_repo=str(target)
    )
    tracer = _CapturingTracer()
    stage = _bound_stage(state, runner=_FakeRunner(), tracer=tracer)

    _drive(stage, _sample_event())

    result = RunContext(state).deploy_result()
    assert isinstance(result, DeployResult)
    detail = _deploy_trigger(tracer).detail
    # The bounded summary fields are exactly the published seam's values.
    assert detail["mode"] == result.mode
    assert detail["status"] == result.status
    assert detail["target_pages_url"] == result.target_pages_url
    assert detail["written_path_count"] == len(result.written_paths)
    assert detail["built"] == bool(result.built_path)


# --------------------------------------------------------------------------- #
# Per-mode bounded summaries: build-only / gh-deploy                            #
# --------------------------------------------------------------------------- #


def test_build_only_summary_has_zero_written_and_built_true(tmp_path) -> None:
    out_dir = tmp_path / "out"
    target = tmp_path / "repo"
    target.mkdir()
    state = _seed_state(
        run_id="run-build", out_dir=str(out_dir), target_repo=str(target)
    )
    tracer = _CapturingTracer()
    stage = _bound_stage(
        state, runner=_FakeRunner(), mode="build-only", tracer=tracer
    )

    _drive(stage, _sample_event())

    detail = _deploy_trigger(tracer).detail
    assert detail["mode"] == "build-only"
    assert detail["status"] == "built"
    assert detail["written_path_count"] == 0
    assert detail["built"] is True


def test_gh_deploy_summary_has_zero_written_and_built_false(tmp_path) -> None:
    out_dir = tmp_path / "out"
    target = tmp_path / "repo"
    target.mkdir()
    state = _seed_state(run_id="run-gh", out_dir=str(out_dir), target_repo=str(target))
    tracer = _CapturingTracer()
    stage = _bound_stage(state, runner=_FakeRunner(), mode="gh-deploy", tracer=tracer)

    _drive(stage, _sample_event())

    detail = _deploy_trigger(tracer).detail
    assert detail["mode"] == "gh-deploy"
    assert detail["status"] == "published"
    assert detail["written_path_count"] == 0
    # gh-deploy pushes the built site straight to gh-pages; no validated built_path is recorded.
    assert detail["built"] is False


# --------------------------------------------------------------------------- #
# Bounded: no page bodies / no full written-path list leak into the detail       #
# --------------------------------------------------------------------------- #


def test_journal_detail_is_bounded_scalar_only(tmp_path) -> None:
    out_dir = tmp_path / "out"
    target = tmp_path / "repo"
    target.mkdir()
    state = _seed_state(
        run_id="run-bounded", out_dir=str(out_dir), target_repo=str(target)
    )
    tracer = _CapturingTracer()
    stage = _bound_stage(state, runner=_FakeRunner(), tracer=tracer)

    _drive(stage, _sample_event())

    detail = _deploy_trigger(tracer).detail
    result = RunContext(state).deploy_result()
    assert isinstance(result, DeployResult)

    # Every value is a scalar (str / int / bool) — no tuples, lists, dicts, or path bodies.
    for value in detail.values():
        assert isinstance(value, (str, int, bool))

    # The full written-path list (the file bodies' locations) is NOT serialized into the detail;
    # only the count is recorded.
    serialized = repr(detail)
    assert result.written_paths  # emit-ci-workflow wrote files
    for written in result.written_paths:
        assert written not in serialized
    # The built-site path is likewise not leaked into the bounded summary.
    assert result.built_path
    assert result.built_path not in serialized


# --------------------------------------------------------------------------- #
# No tracer / no runtime bound: no journal emission, no error (Req 8.2)          #
# --------------------------------------------------------------------------- #


def test_no_op_when_no_tracer_is_bound(tmp_path) -> None:
    out_dir = tmp_path / "out"
    target = tmp_path / "repo"
    target.mkdir()
    state = _seed_state(
        run_id="run-no-tracer", out_dir=str(out_dir), target_repo=str(target)
    )
    # Runtime bound with tracer=None -> the journal emission is a graceful no-op.
    stage = _bound_stage(state, runner=_FakeRunner(), tracer=None)

    out = _drive(stage, _sample_event())
    assert len(out) == 1  # event forwarded unchanged, no raise
    # The deploy result is still published; only the journal emission is a no-op.
    assert RunContext(state).deploy_result() is not None


def test_no_op_when_no_runtime_bound_at_all(tmp_path) -> None:
    out_dir = tmp_path / "out"
    target = tmp_path / "repo"
    target.mkdir()
    state = _seed_state(
        run_id="run-no-runtime", out_dir=str(out_dir), target_repo=str(target)
    )
    stage = DeployStage()  # never _bind_runtime'd
    stage._command_runner = _FakeRunner()
    _start_task(stage, state)

    out = _drive(stage, _sample_event())
    assert len(out) == 1  # forwarded unchanged, journal is a graceful no-op
    assert RunContext(state).deploy_result() is not None
