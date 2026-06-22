"""Credential-free stage integration + gating tests for the Assemble stage (mkdocs-site-assembler task 5.1).

This suite drives the **real** :class:`~docuharnessx.stages.assemble.AssembleStage` — the thin
HarnessX adapter that replaces the no-op ``assemble`` stub in place — over a seeded run
``State``, exactly mirroring ``tests/test_stage_review_replaceability.py`` /
``tests/test_stage_write_integration.py``. The stage is driven directly through
``on_task_start`` (to capture the run ``State``) + ``on_step_end`` (the real slot I/O), so the
boundary under test stays the ``AssembleStage`` adapter rather than the whole pipeline.

Task 5.1 pins (design "AssembleStage", Req 1.1-1.4, 2.1-2.6, 7.1):

* with a bound run ``State`` carrying a seeded :class:`ReviewReport` (accepted segments), the
  loaded ``Vocabulary``, an output directory, and a target path -> the stage resolves the
  per-target identity (no-remote fallback here — ``tmp_path`` is not a git repo), runs the
  site writer, publishes a well-formed :class:`AssembledSite` to ``SLOT_ASSEMBLED_SITE`` with
  the correct per-segment / per-role counts, and yields the lifecycle event unchanged;
* a missing review-report / vocabulary / output-dir slot, or an unsupported ``ReviewReport``
  schema version, each raise the fatal :class:`AssemblerInputError` naming the cause and
  publish **no** site (Req 2.3, 2.4, 2.6);
* an absent :class:`RepoAnalysis` still produces a site (Req 2.5);
* driven outside a harness (no ``task_start`` to bind a run ``State``) the stage forwards the
  event unchanged and produces nothing, exactly like the no-op base (Req 1.3).

Credential-free / network-free: no model is bound and ``read_origin_remote`` degrades to the
no-remote fallback over a non-git ``tmp_path``; the only subprocess (the read-only git remote
read) is exercised against a directory with no ``origin`` remote.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from harnessx.core.events import (
    ProcessorTriggerEvent,
    StepEndEvent,
    TaskStartEvent,
)
from harnessx.core.state import State

from docuharnessx.assembler.model import (
    ASSEMBLED_SITE_SCHEMA_VERSION,
    AssembledSite,
    AssemblerInputError,
    SiteIdentity,
)
from docuharnessx.context import RunContext
from docuharnessx.ontology import (
    AxisTerm,
    Segment,
    Subject,
    Vocabulary,
    build_role_view,
    default_profile,
)
from docuharnessx.review.model import (
    REVIEW_REPORT_SCHEMA_VERSION,
    ReviewAggregate,
    ReviewReport,
)
from docuharnessx.stages.assemble import (
    STAGE_NAME,
    AssembleStage,
    make_assemble_stage,
)
from docuharnessx.stages.base import STAGE_PARTICIPATION_ACTION


# --------------------------------------------------------------------------- #
# Harness-free drivers (mirror tests/test_stage_review_replaceability.py)      #
# --------------------------------------------------------------------------- #


class _RuntimeStub:
    def __init__(self, tracer: Any | None = None) -> None:
        self.tracer = tracer


class _CapturingTracer:
    """A duck-typed run tracer that records every event the stage emits.

    Mirrors ``tests/test_stage_review_gating.py``'s capturing tracer so the bounded
    ``stage_participated`` journal trigger (task 5.2) can be asserted directly.
    """

    events: list[Any]

    def __init__(self) -> None:
        self.events = []

    async def on_event(self, event: Any) -> None:
        self.events.append(event)


def _start_task(stage: AssembleStage, state: State) -> None:
    async def _collect() -> None:
        async for _ in stage.on_task_start(
            TaskStartEvent(run_id=state.run_id, step_id=0, state=state)
        ):
            pass

    asyncio.run(_collect())


def _bound_stage(state: State) -> AssembleStage:
    stage = AssembleStage()
    stage._bind_runtime(_RuntimeStub())
    _start_task(stage, state)
    return stage


def _bound_stage_with_tracer(
    state: State, tracer: _CapturingTracer
) -> AssembleStage:
    stage = AssembleStage()
    stage._bind_runtime(_RuntimeStub(tracer))
    _start_task(stage, state)
    return stage


def _sample_event() -> StepEndEvent:
    return StepEndEvent(
        run_id="run-assemble",
        step_id=7,
        step_summary="prior summary",
        tool_call_summary="readFile(a)",
        cumulative_tokens=10,
        cumulative_cost_usd=0.1,
    )


def _drive(stage: AssembleStage, event: StepEndEvent) -> list[Any]:
    async def _collect() -> list[Any]:
        return [out async for out in stage.on_step_end(event)]

    return asyncio.run(_collect())


# --------------------------------------------------------------------------- #
# Fixtures: a seeded accepted set + report                                     #
# --------------------------------------------------------------------------- #


def _segment(
    seg_id: str, *, title: str, roles: list[str], intent: str
) -> Segment:
    return Segment(
        id=seg_id,
        title=title,
        roles=roles,
        subjects=[Subject(prefix="component", local=seg_id)],
        intent=intent,
        summary=f"Summary {seg_id}.",
        related=[],
        body=f"Body of {seg_id}.\n",
    )


def _accepted_segments() -> tuple[Segment, ...]:
    return (
        _segment("scanner", title="Scanner", roles=["developer"], intent="extend"),
        _segment("core", title="Core", roles=["contributor"], intent="contribute"),
        _segment("runner", title="Runner", roles=["developer"], intent="operate"),
    )


def _report(*accepted: Segment) -> ReviewReport:
    return ReviewReport(
        schema_version=REVIEW_REPORT_SCHEMA_VERSION,
        entries=(),
        accepted=tuple(accepted),
        aggregate=ReviewAggregate(
            judged=len(accepted),
            accepted=len(accepted),
            rejected=0,
            unavailable=0,
            criterion_tally=(),
        ),
    )


def _seed_state(
    *,
    run_id: str,
    out_dir: str,
    target_repo: str,
    report: ReviewReport | None,
    vocab: Vocabulary | None,
    set_output: bool = True,
) -> State:
    state = State(run_id=run_id)
    rc = RunContext(state)
    if report is not None:
        rc.set_review_report(report)
    if vocab is not None:
        rc.set_vocabulary(vocab)
    if set_output:
        rc.set_output_dir(out_dir)
    rc.set_target_repo(target_repo)
    return state


# --------------------------------------------------------------------------- #
# Happy path: a seeded accepted set publishes a well-formed AssembledSite       #
# --------------------------------------------------------------------------- #


def test_seeded_run_publishes_well_formed_assembled_site(tmp_path) -> None:
    vocab = default_profile()
    accepted = _accepted_segments()
    report = _report(*accepted)
    out_dir = str(tmp_path / "out")
    state = _seed_state(
        run_id="run-ok",
        out_dir=out_dir,
        target_repo=str(tmp_path / "repo"),
        report=report,
        vocab=vocab,
    )
    stage = _bound_stage(state)
    event = _sample_event()
    out = _drive(stage, event)

    # The lifecycle event is forwarded unchanged (Req 1.4).
    assert out == [event]
    assert out[0] is event

    site = RunContext(state).assembled_site()
    assert isinstance(site, AssembledSite)
    assert site.schema_version == ASSEMBLED_SITE_SCHEMA_VERSION
    # One page per accepted segment (Req 4.1).
    assert site.page_count == len(accepted)
    # One landing page per vocabulary role that has at least one accepted segment.
    from docuharnessx.assembler import assemble_site as _assemble_site  # noqa: F401

    # The role-page count equals the number of vocabulary roles with a non-empty
    # accepted role view (computed against a fresh accepted-only store).
    from docuharnessx.ontology import InMemorySegmentStore

    store = InMemorySegmentStore(vocab)
    for seg in accepted:
        store.put(seg)
    expected_roles = [r for r in vocab.roles if build_role_view(store, r.id, vocab)]
    assert site.role_page_count == len(expected_roles)

    # The tree exists under <out>/site (the single write target, Req 8.5).
    from pathlib import Path

    site_dir = Path(site.site_dir)
    assert site_dir == (Path(out_dir) / "site").resolve()
    assert (site_dir / "mkdocs.yml").is_file()
    assert Path(site.docs_dir).is_dir()
    # One docs/*.md per accepted segment.
    from docuharnessx.assembler.pages import page_filename

    for seg in accepted:
        assert (Path(site.docs_dir) / page_filename(seg.id)).is_file()


def test_seeded_run_identity_is_per_target_never_docuharnessx(tmp_path) -> None:
    # The resolved identity is per-target (no-remote fallback -> target basename) and never
    # DocuHarnessX's own identity (Req 3.5, 3.8).
    vocab = default_profile()
    report = _report(*_accepted_segments())
    target = tmp_path / "malware_hashes"
    target.mkdir()
    state = _seed_state(
        run_id="run-ident",
        out_dir=str(tmp_path / "out"),
        target_repo=str(target),
        report=report,
        vocab=vocab,
    )
    stage = _bound_stage(state)
    _drive(stage, _sample_event())

    site = RunContext(state).assembled_site()
    assert isinstance(site.identity, SiteIdentity)
    # No git remote on tmp_path -> the no-remote fallback derives site_name from the dir.
    assert site.identity.site_name == "malware_hashes"
    assert site.identity.base_path == "/"
    assert "docuharnessx" not in site.identity.site_name.lower()
    assert "docuharnessx" not in site.identity.repo_url.lower()


def test_absent_analysis_still_produces_a_site(tmp_path) -> None:
    # No RepoAnalysis is seeded; the stage tolerates the absent slot and still assembles a
    # site (Req 2.5).
    vocab = default_profile()
    report = _report(*_accepted_segments())
    state = _seed_state(
        run_id="run-no-analysis",
        out_dir=str(tmp_path / "out"),
        target_repo=str(tmp_path / "repo"),
        report=report,
        vocab=vocab,
    )
    assert RunContext(state).repo_analysis() is None
    stage = _bound_stage(state)
    _drive(stage, _sample_event())
    assert RunContext(state).assembled_site() is not None


def test_empty_accepted_set_produces_a_buildable_empty_site(tmp_path) -> None:
    # A well-formed empty report (no accepted segments) still yields a site with zero pages
    # and zero role pages (no role has accepted content).
    vocab = default_profile()
    report = _report()
    state = _seed_state(
        run_id="run-empty",
        out_dir=str(tmp_path / "out"),
        target_repo=str(tmp_path / "repo"),
        report=report,
        vocab=vocab,
    )
    stage = _bound_stage(state)
    _drive(stage, _sample_event())
    site = RunContext(state).assembled_site()
    assert site is not None
    assert site.page_count == 0
    assert site.role_page_count == 0


# --------------------------------------------------------------------------- #
# Fatal input paths: missing slot / unsupported version -> no site (Req 2.3-2.6)
# --------------------------------------------------------------------------- #


def test_missing_review_report_raises_and_produces_no_site(tmp_path) -> None:
    state = _seed_state(
        run_id="run-no-report",
        out_dir=str(tmp_path / "out"),
        target_repo=str(tmp_path / "repo"),
        report=None,
        vocab=default_profile(),
    )
    stage = _bound_stage(state)
    with pytest.raises(AssemblerInputError):
        _drive(stage, _sample_event())
    assert RunContext(state).assembled_site() is None


def test_missing_vocabulary_raises_and_produces_no_site(tmp_path) -> None:
    state = _seed_state(
        run_id="run-no-vocab",
        out_dir=str(tmp_path / "out"),
        target_repo=str(tmp_path / "repo"),
        report=_report(*_accepted_segments()),
        vocab=None,
    )
    stage = _bound_stage(state)
    with pytest.raises(AssemblerInputError):
        _drive(stage, _sample_event())
    assert RunContext(state).assembled_site() is None


def test_missing_output_dir_raises_and_produces_no_site(tmp_path) -> None:
    state = _seed_state(
        run_id="run-no-out",
        out_dir=str(tmp_path / "out"),
        target_repo=str(tmp_path / "repo"),
        report=_report(*_accepted_segments()),
        vocab=default_profile(),
        set_output=False,
    )
    stage = _bound_stage(state)
    with pytest.raises(AssemblerInputError):
        _drive(stage, _sample_event())
    assert RunContext(state).assembled_site() is None


def test_unsupported_review_report_version_raises_and_produces_no_site(tmp_path) -> None:
    bad = ReviewReport(
        schema_version=REVIEW_REPORT_SCHEMA_VERSION + 999,
        entries=(),
        accepted=_accepted_segments(),
        aggregate=ReviewAggregate(
            judged=3, accepted=3, rejected=0, unavailable=0, criterion_tally=()
        ),
    )
    state = _seed_state(
        run_id="run-bad-version",
        out_dir=str(tmp_path / "out"),
        target_repo=str(tmp_path / "repo"),
        report=bad,
        vocab=default_profile(),
    )
    stage = _bound_stage(state)
    with pytest.raises(AssemblerInputError):
        _drive(stage, _sample_event())
    assert RunContext(state).assembled_site() is None


# --------------------------------------------------------------------------- #
# Out-of-harness pass-through: no bound State -> forward event, no site (Req 1.3)
# --------------------------------------------------------------------------- #


def test_out_of_harness_drive_forwards_event_and_produces_nothing() -> None:
    stage = make_assemble_stage()  # never task_start'd, no runtime bound
    event = _sample_event()
    out = _drive(stage, event)
    assert len(out) == 1
    assert out[0] is event


def test_out_of_harness_drive_does_not_raise_even_with_runtime_bound() -> None:
    stage = AssembleStage()
    stage._bind_runtime(_RuntimeStub())
    event = _sample_event()
    out = _drive(stage, event)
    assert len(out) == 1
    assert out[0] is event


def test_process_entrypoint_is_a_passthrough_off_harness() -> None:
    stage = make_assemble_stage()
    event = _sample_event()

    async def _collect() -> list[Any]:
        return [out async for out in stage.process(event)]

    out = asyncio.run(_collect())
    assert len(out) == 1
    assert out[0] is event


# --------------------------------------------------------------------------- #
# Determinism: two runs over equal inputs publish an equal AssembledSite        #
# --------------------------------------------------------------------------- #


def test_two_runs_over_equal_inputs_publish_equal_assembled_site(tmp_path) -> None:
    vocab = default_profile()

    def _run(run_id: str) -> AssembledSite:
        report = _report(*_accepted_segments())
        out_dir = str(tmp_path / run_id)
        state = _seed_state(
            run_id=run_id,
            out_dir=out_dir,
            target_repo=str(tmp_path / "repo"),
            report=report,
            vocab=vocab,
        )
        stage = _bound_stage(state)
        _drive(stage, _sample_event())
        return RunContext(state).assembled_site()

    s1 = _run("run-a")
    s2 = _run("run-b")
    # Identity + counts are equal across runs (the absolute paths differ by out_dir).
    assert s1.identity == s2.identity
    assert s1.page_count == s2.page_count
    assert s1.role_page_count == s2.role_page_count
    assert s1.schema_version == s2.schema_version


# --------------------------------------------------------------------------- #
# Stable replaceability: unchanged public surface (Req 1.1, 1.2)               #
# --------------------------------------------------------------------------- #


def test_public_surface_names_are_stable() -> None:
    import docuharnessx.stages.assemble as assemble_module
    from docuharnessx.stages.assemble import STAGE_NAME

    assert STAGE_NAME == "assemble"
    assert AssembleStage.__name__ == "AssembleStage"
    assert AssembleStage.stage_name == "assemble"
    assert make_assemble_stage.__name__ == "make_assemble_stage"
    assert assemble_module.__name__ == "docuharnessx.stages.assemble"
    assert "make_noop_stage" in assemble_module.__all__
    for name in ("STAGE_NAME", "AssembleStage", "make_assemble_stage"):
        assert name in assemble_module.__all__
    instance = make_assemble_stage()
    assert isinstance(instance, AssembleStage)


def test_assemble_stage_subclasses_the_shared_noop_base() -> None:
    from docuharnessx.stages.base import NoOpStage

    assert issubclass(AssembleStage, NoOpStage)


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
    assert dict(STAGES)["assemble"] is make_assemble_stage
    assert stage_class_for("assemble") is AssembleStage


# --------------------------------------------------------------------------- #
# Bounded journal summary (task 5.2, Req 1.4)                                  #
# --------------------------------------------------------------------------- #


def _assemble_trigger(tracer: _CapturingTracer) -> ProcessorTriggerEvent:
    """Return the single Assemble ``stage_participated`` trigger, asserting exactly one."""
    triggers = [
        e
        for e in tracer.events
        if isinstance(e, ProcessorTriggerEvent)
        and e.action == STAGE_PARTICIPATION_ACTION
        and isinstance(e.detail, dict)
        and e.detail.get("stage") == STAGE_NAME
    ]
    assert len(triggers) == 1, f"expected exactly one Assemble trigger, got {triggers!r}"
    return triggers[0]


def test_journal_records_bounded_site_summary(tmp_path) -> None:
    # On completion with a bound state + tracer, the stage records ONE participation
    # trigger whose detail carries the bounded site summary: the page count, the
    # role-page count, the resolved site_name, and the base-path (Req 1.4). The summary
    # never carries a page body.
    vocab = default_profile()
    accepted = _accepted_segments()
    report = _report(*accepted)
    out_dir = str(tmp_path / "out")
    target = tmp_path / "my_target"
    target.mkdir()
    state = _seed_state(
        run_id="run-journal",
        out_dir=out_dir,
        target_repo=str(target),
        report=report,
        vocab=vocab,
    )
    tracer = _CapturingTracer()
    stage = _bound_stage_with_tracer(state, tracer)
    _drive(stage, _sample_event())

    site = RunContext(state).assembled_site()
    trigger = _assemble_trigger(tracer)
    detail = trigger.detail

    # The bounded summary carries the counts and the resolved identity, read from the
    # published seam so the journal and the AssembledSite never disagree.
    assert detail["stage"] == STAGE_NAME
    assert detail["page_count"] == site.page_count
    assert detail["role_page_count"] == site.role_page_count
    assert detail["site_name"] == site.identity.site_name
    assert detail["base_path"] == site.identity.base_path
    # No-remote fallback over a non-git target -> site_name from the target dir basename.
    assert detail["site_name"] == "my_target"
    assert detail["base_path"] == "/"

    # The summary is bounded: scalar-only, and never carries any page body. The seeded
    # bodies are "Body of <id>.\n"; no detail value contains that prose.
    flat = repr(detail)
    assert "Body of" not in flat
    for value in detail.values():
        assert not (isinstance(value, str) and "Body of" in value)


def test_journal_summary_is_scalar_and_carries_no_segment_bodies(tmp_path) -> None:
    # Stronger bound: every detail value is a scalar (str/int) — no Segment objects, no
    # page render tuples, no list of bodies leak into the trace (Req 1.4).
    vocab = default_profile()
    report = _report(*_accepted_segments())
    state = _seed_state(
        run_id="run-journal-scalar",
        out_dir=str(tmp_path / "out"),
        target_repo=str(tmp_path / "repo"),
        report=report,
        vocab=vocab,
    )
    tracer = _CapturingTracer()
    stage = _bound_stage_with_tracer(state, tracer)
    _drive(stage, _sample_event())

    detail = _assemble_trigger(tracer).detail
    assert set(detail) == {
        "stage",
        "page_count",
        "role_page_count",
        "site_name",
        "base_path",
    }
    assert isinstance(detail["page_count"], int)
    assert isinstance(detail["role_page_count"], int)
    for key in ("stage", "site_name", "base_path"):
        assert isinstance(detail[key], str)


def test_journal_no_op_when_no_tracer_bound(tmp_path) -> None:
    # With a bound state but no tracer (the _RuntimeStub default), assembly still runs and
    # publishes the site, and the journal step is a silent no-op (no raise).
    vocab = default_profile()
    report = _report(*_accepted_segments())
    state = _seed_state(
        run_id="run-no-tracer",
        out_dir=str(tmp_path / "out"),
        target_repo=str(tmp_path / "repo"),
        report=report,
        vocab=vocab,
    )
    stage = _bound_stage(state)  # binds _RuntimeStub() with tracer=None
    out = _drive(stage, _sample_event())
    assert len(out) == 1
    assert RunContext(state).assembled_site() is not None


def test_no_journal_trigger_on_fatal_input_path(tmp_path) -> None:
    # When a required input slot is missing the stage raises before producing a site, so no
    # participation trigger is recorded for this stage (no site -> no summary).
    state = _seed_state(
        run_id="run-no-report-journal",
        out_dir=str(tmp_path / "out"),
        target_repo=str(tmp_path / "repo"),
        report=None,
        vocab=default_profile(),
    )
    tracer = _CapturingTracer()
    stage = _bound_stage_with_tracer(state, tracer)
    with pytest.raises(AssemblerInputError):
        _drive(stage, _sample_event())
    assemble_triggers = [
        e
        for e in tracer.events
        if isinstance(e, ProcessorTriggerEvent)
        and e.action == STAGE_PARTICIPATION_ACTION
        and isinstance(e.detail, dict)
        and e.detail.get("stage") == STAGE_NAME
    ]
    assert assemble_triggers == []
