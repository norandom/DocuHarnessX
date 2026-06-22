"""Task 5.2 — integration-test the Deploy stage across modes and fatal-input paths.

This module is the github-pages-deploy *task 5.2* deliverable (``_Boundary: DeployStage``).
Where the per-task adapter suites (``test_stage_deploy_integration.py`` for task 4.1, the
bounded-journal suite ``test_stage_deploy_journal.py`` for task 4.2, and the append-only seam
suite ``test_deploy_result_seam.py`` for task 1.2) pin each lower task in isolation, task 5.2
drives the **real** :class:`~docuharnessx.stages.deploy.DeployStage` adapter — the thin HarnessX
adapter that replaces the no-op ``deploy`` stub in place — over a seeded run ``State`` with an
injected **fake** :class:`~docuharnessx.deployer.commands.CommandRunner` and asserts, as one
consolidated stage-integration suite, the cross-cutting acceptance behaviours the task text
enumerates:

* the **default** mode (``emit-ci-workflow``) publishes an ``emitted`` result whose three
  written paths name the three target-tree files actually written under the target tree
  (Req 1.4, 2.1, 2.2, 4.1, 4.2, 8.1);
* ``build-only`` writes **nothing** into the target tree and yields a ``built`` result
  (Req 6.1, 6.2);
* ``gh-deploy`` invokes the mocked push **exactly once** and yields a ``published`` result with
  **no real network call** and no target-tree writes (Req 5.1, 5.2, 5.4);
* every **fatal-input path** — a missing assembled-site / output-dir / target-repo slot, an
  unsupported ``AssembledSite`` schema version, and an unsupported configured mode — raises the
  fatal :class:`~docuharnessx.deployer.model.DeployInputError`, publishes **no** result, and
  drives **no** subprocess (Req 2.3, 2.4, 2.5, 3.4);
* an **out-of-harness** drive (no ``task_start`` to bind a run ``State``) forwards the lifecycle
  event unchanged and does nothing, exactly like the no-op base (Req 1.3);
* the append-only :class:`~docuharnessx.deployer.model.DeployResult` **slot round-trips** through
  the stage and the existing sibling seams are **unchanged** after a deploy (Req 8.2, 8.4).

The suite is credential-free and harness-free: the stage is driven directly through
``on_task_start`` (to capture the run ``State``) + ``on_step_end`` (the real slot I/O), so the
boundary under test stays the ``DeployStage`` adapter, and every ``git`` / ``mkdocs`` touch goes
through the injected :class:`_FakeRunner`, which records its calls so no real subprocess is
spawned and the ``gh-deploy`` push is never exercised.

Observable completion (tasks.md 5.2): the stage integration suite passes, covering all three
modes, every fatal-input path, the out-of-harness pass-through, and the append-only seam
round-trip.

_Requirements: 1.1, 1.2, 1.3, 1.4, 2.1, 2.2, 2.3, 2.4, 2.5, 5.1, 5.2, 5.4, 6.1, 6.2, 8.1,
8.2, 8.4_
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Sequence

import pytest
from harnessx.core.events import ProcessorTriggerEvent, StepEndEvent, TaskStartEvent
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
from docuharnessx.stages.base import STAGE_PARTICIPATION_ACTION
from docuharnessx.stages.deploy import STAGE_NAME, DeployStage, make_deploy_stage

# The reference target throughout (per the locked multi-project decision): the per-target
# identity is always derived from the consumed AssembledSite, never DocuHarnessX's own.
_TARGET_PAGES_URL = "https://norandom.github.io/malware_hashes/"


# --------------------------------------------------------------------------- #
# Harness-free drivers + a capturing-tracer runtime stub + a recording runner   #
# --------------------------------------------------------------------------- #


class _CapturingTracer:
    """A minimal tracer that records every event ``on_event`` is called with."""

    def __init__(self) -> None:
        self.events: list[Any] = []

    async def on_event(self, event: Any) -> None:
        self.events.append(event)


class _RuntimeStub:
    def __init__(self, tracer: Any | None = None) -> None:
        self.tracer = tracer


class _FakeRunner:
    """A duck-typed :class:`CommandRunner` recording every invocation.

    Returns canned success so no real ``git`` / ``mkdocs`` process is spawned and the
    ``gh-deploy`` push is never reached (Req 5.4, 7.4). ``invocations`` records ``(args, cwd)``
    so tests can assert exactly which subprocesses the stage drove — in particular that the push
    runs exactly once on the gh-deploy mode and never on the validated modes.
    """

    def __init__(self) -> None:
        self.invocations: list[tuple[list[str], str]] = []

    def run(
        self, args: "Sequence[str]", cwd: str, timeout: float | None = None
    ) -> CompletedResult:
        self.invocations.append((list(args), cwd))
        return CompletedResult(returncode=0, stdout="", stderr="")

    def gh_deploy_count(self) -> int:
        return sum(
            1
            for args, _cwd in self.invocations
            if len(args) >= 2 and args[0] == "mkdocs" and args[1] == "gh-deploy"
        )

    def build_count(self) -> int:
        return sum(
            1
            for args, _cwd in self.invocations
            if len(args) >= 2 and args[0] == "mkdocs" and args[1] == "build"
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
    """Build a DeployStage bound to ``state`` with the fake runner + optional mode/tracer.

    Mirrors the per-instance injection the CLI mode-wiring layer uses (``_deploy_mode`` /
    ``_command_runner``), exactly the way ``ReviewStage`` reads its bound ``_model_config``, so
    no real subprocess and no model is reached.
    """
    stage = DeployStage()
    stage._bind_runtime(_RuntimeStub(tracer))
    stage._command_runner = runner
    if mode is not None:
        stage._deploy_mode = mode
    _start_task(stage, state)
    return stage


def _sample_event() -> StepEndEvent:
    return StepEndEvent(
        run_id="run-deploy-5-2",
        step_id=12,
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
        site_url=_TARGET_PAGES_URL,
        base_path="/malware_hashes/",
        edit_uri="edit/main/docs/",
    )


def _seed_assembled_site(
    out_dir: Path, *, schema_version: int = ASSEMBLED_SITE_SCHEMA_VERSION
) -> AssembledSite:
    """Write a minimal real MkDocs source tree under ``<out>/site`` and return the seam.

    The build itself is mocked through the fake runner, so the files only need to exist for the
    seam's path fields to be well-formed.
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
# Mode coverage: emit-ci-workflow (default) — the three target-tree files        #
# --------------------------------------------------------------------------- #


def test_default_mode_publishes_emitted_result_with_three_target_tree_files(
    tmp_path,
) -> None:
    """No configured mode -> default emit-ci-workflow; three files written + emitted result."""
    out_dir = tmp_path / "out"
    target = tmp_path / "repo"
    target.mkdir()
    site = _seed_assembled_site(out_dir)
    state = _seed_state(
        run_id="run-emit", out_dir=str(out_dir), target_repo=str(target), site=site
    )
    runner = _FakeRunner()
    stage = _bound_stage(state, runner=runner)  # no mode -> default (Req 3.2)
    event = _sample_event()

    out = _drive(stage, event)

    # The content-free lifecycle event is forwarded unchanged (Req 1.4).
    assert out == [event]
    assert out[0] is event

    result = RunContext(state).deploy_result()
    assert isinstance(result, DeployResult)
    assert result.schema_version == DEPLOY_RESULT_SCHEMA_VERSION
    assert result.mode == "emit-ci-workflow"
    assert result.status == "emitted"
    # The per-target Pages URL, never DocuHarnessX's own (Req 2.2, 8.1).
    assert result.target_pages_url == _TARGET_PAGES_URL

    # The three written paths name exactly the three target-tree files, which exist under the
    # target tree and nowhere else (Req 4.1, 4.2).
    assert len(result.written_paths) == 3
    mkdocs_yml = target / "mkdocs.yml"
    docs_dir = target / "docs"
    workflow = target / ".github" / "workflows" / "docs.yml"
    assert mkdocs_yml.is_file()
    assert docs_dir.is_dir()
    assert workflow.is_file()
    written = {Path(p) for p in result.written_paths}
    assert written == {mkdocs_yml, docs_dir, workflow}
    assert result.built_path != ""

    # The (mocked) build ran; the gh-deploy push was never reached on the validated mode
    # (Req 5.4, 7.4).
    assert runner.build_count() == 1
    assert runner.gh_deploy_count() == 0


# --------------------------------------------------------------------------- #
# Mode coverage: build-only — writes nothing into the target tree                #
# --------------------------------------------------------------------------- #


def test_build_only_writes_nothing_into_target_and_yields_built(tmp_path) -> None:
    out_dir = tmp_path / "out"
    target = tmp_path / "repo"
    target.mkdir()
    site = _seed_assembled_site(out_dir)
    state = _seed_state(
        run_id="run-build", out_dir=str(out_dir), target_repo=str(target), site=site
    )
    runner = _FakeRunner()
    stage = _bound_stage(state, runner=runner, mode="build-only")

    _drive(stage, _sample_event())

    result = RunContext(state).deploy_result()
    assert isinstance(result, DeployResult)
    assert result.mode == "build-only"
    assert result.status == "built"
    assert result.written_paths == ()
    assert result.built_path != ""
    assert result.target_pages_url == _TARGET_PAGES_URL

    # Nothing written into the target tree, nothing pushed (Req 6.2).
    assert not (target / "mkdocs.yml").exists()
    assert not (target / "docs").exists()
    assert not (target / ".github").exists()
    assert runner.build_count() == 1
    assert runner.gh_deploy_count() == 0


# --------------------------------------------------------------------------- #
# Mode coverage: gh-deploy — the mocked push runs exactly once, no network       #
# --------------------------------------------------------------------------- #


def test_gh_deploy_invokes_mocked_push_exactly_once_no_network(tmp_path) -> None:
    out_dir = tmp_path / "out"
    target = tmp_path / "repo"
    target.mkdir()
    site = _seed_assembled_site(out_dir)
    state = _seed_state(
        run_id="run-gh", out_dir=str(out_dir), target_repo=str(target), site=site
    )
    runner = _FakeRunner()
    stage = _bound_stage(state, runner=runner, mode="gh-deploy")

    _drive(stage, _sample_event())

    result = RunContext(state).deploy_result()
    assert isinstance(result, DeployResult)
    assert result.mode == "gh-deploy"
    assert result.status == "published"
    assert result.written_paths == ()
    assert result.built_path == ""
    assert result.target_pages_url == _TARGET_PAGES_URL

    # The mocked push ran exactly once (Req 5.1, 5.4); no real network call under the fake runner.
    assert runner.gh_deploy_count() == 1
    # gh-deploy runs only the push — no validated build, no target-tree writes.
    assert runner.build_count() == 0
    assert not (target / "mkdocs.yml").exists()
    assert not (target / ".github").exists()


# --------------------------------------------------------------------------- #
# Fatal-input paths: each raises DeployInputError, no result, no subprocess       #
# --------------------------------------------------------------------------- #


def test_missing_assembled_site_raises_input_error_no_deploy(tmp_path) -> None:
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


def test_missing_output_dir_raises_input_error_no_deploy(tmp_path) -> None:
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


def test_missing_target_repo_raises_input_error_no_deploy(tmp_path) -> None:
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


def test_unsupported_assembled_site_version_raises_input_error_no_deploy(
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


def test_unsupported_mode_raises_input_error_no_deploy(tmp_path) -> None:
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
    # The bad mode is rejected before any subprocess (Req 3.4); nothing written either.
    assert runner.invocations == []
    assert not (target / "mkdocs.yml").exists()
    assert not (target / ".github").exists()


# --------------------------------------------------------------------------- #
# Out-of-harness drive: no bound State -> forward event, do nothing              #
# --------------------------------------------------------------------------- #


def test_out_of_harness_drive_forwards_event_and_does_nothing() -> None:
    stage = make_deploy_stage()  # never task_start'd, no runtime bound
    event = _sample_event()
    out = _drive(stage, event)
    assert len(out) == 1
    assert out[0] is event


def test_out_of_harness_drive_with_runtime_but_no_state_does_nothing() -> None:
    stage = DeployStage()
    stage._bind_runtime(_RuntimeStub())  # runtime bound, but no task_start -> no State
    event = _sample_event()
    out = _drive(stage, event)
    assert len(out) == 1
    assert out[0] is event


# --------------------------------------------------------------------------- #
# Append-only seam round-trip through the stage + existing seams unchanged        #
# --------------------------------------------------------------------------- #


def test_deploy_result_slot_round_trips_through_the_stage(tmp_path) -> None:
    """After a deploy the published DeployResult round-trips through the slot accessor (8.4)."""
    out_dir = tmp_path / "out"
    target = tmp_path / "repo"
    target.mkdir()
    site = _seed_assembled_site(out_dir)
    state = _seed_state(
        run_id="run-roundtrip",
        out_dir=str(out_dir),
        target_repo=str(target),
        site=site,
    )
    # A fresh slot is explicitly absent before the stage runs (Req 8.4).
    assert RunContext(state).deploy_result() is None

    stage = _bound_stage(state, runner=_FakeRunner())
    _drive(stage, _sample_event())

    # Two independent reads return the same published instance — the slot round-trips (Req 8.4).
    first = RunContext(state).deploy_result()
    second = RunContext(state).deploy_result()
    assert isinstance(first, DeployResult)
    assert first is second
    assert first == second


def test_deploy_leaves_existing_sibling_seams_unchanged(tmp_path) -> None:
    """Publishing the deploy result disturbs no existing sibling slot accessor (8.4)."""
    out_dir = tmp_path / "out"
    target = tmp_path / "repo"
    target.mkdir()
    site = _seed_assembled_site(out_dir)
    state = _seed_state(
        run_id="run-siblings",
        out_dir=str(out_dir),
        target_repo=str(target),
        site=site,
    )
    stage = _bound_stage(state, runner=_FakeRunner())
    _drive(stage, _sample_event())

    rc = RunContext(state)
    # The deploy result is published...
    assert rc.deploy_result() is not None
    # ...the consumed assembled site is unchanged (still the seeded seam, read-only)...
    assert rc.assembled_site() is site
    # ...the input slots the stage reads are untouched...
    assert rc.output_dir() == str(out_dir)
    assert rc.target_repo() == str(target)
    # ...and the upstream seams the stage never touches stay absent (no spillover).
    assert rc.review_report() is None
    assert rc.written_segments() is None
    assert rc.coverage_plan() is None
    assert rc.vocabulary() is None


def test_journal_records_one_bounded_deploy_summary(tmp_path) -> None:
    """The deploy is observable in the journal as one bounded participation entry (Req 8.2)."""
    out_dir = tmp_path / "out"
    target = tmp_path / "repo"
    target.mkdir()
    site = _seed_assembled_site(out_dir)
    state = _seed_state(
        run_id="run-journal",
        out_dir=str(out_dir),
        target_repo=str(target),
        site=site,
    )
    tracer = _CapturingTracer()
    stage = _bound_stage(state, runner=_FakeRunner(), tracer=tracer)

    _drive(stage, _sample_event())

    trigger = _deploy_trigger(tracer)
    detail = trigger.detail
    result = RunContext(state).deploy_result()
    assert isinstance(result, DeployResult)
    # The bounded summary carries the mode / status / Pages URL / counts (Req 8.2)...
    assert detail["mode"] == result.mode
    assert detail["status"] == result.status
    assert detail["target_pages_url"] == result.target_pages_url
    assert detail["written_path_count"] == len(result.written_paths)
    assert detail["built"] == bool(result.built_path)
    # ...and only scalars — no page bodies / no full written-path list leaks into the trace.
    for value in detail.values():
        assert isinstance(value, (str, int, bool))
    serialized = repr(detail)
    for written in result.written_paths:
        assert written not in serialized
    assert result.built_path
    assert result.built_path not in serialized


# --------------------------------------------------------------------------- #
# Stable replaceability: the stage drops into the registry slot unchanged         #
# --------------------------------------------------------------------------- #


def test_stage_registry_and_surface_unchanged(tmp_path) -> None:
    """The real stage preserves the single-stage-swap contract (Req 1.1, 1.2)."""
    from docuharnessx.stages import STAGES, stage_class_for
    from docuharnessx.stages.base import NoOpStage

    assert STAGE_NAME == "deploy"
    assert issubclass(DeployStage, NoOpStage)
    assert dict(STAGES)["deploy"] is make_deploy_stage
    assert stage_class_for("deploy") is DeployStage
    assert [name for name, _ in STAGES] == [
        "ingest",
        "analyze",
        "classify",
        "plan",
        "write",
        "review",
        "assemble",
        "deploy",
    ]
