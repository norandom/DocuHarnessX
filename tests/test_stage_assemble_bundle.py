"""Credential-free, bundle-driven integration + input-gating + seam tests for the
Assemble stage (mkdocs-site-assembler task 6.1).

Where ``tests/test_stage_assemble_integration.py`` (tasks 5.1/5.2) drives the real
:class:`~docuharnessx.stages.assemble.AssembleStage` *directly* through
``on_task_start`` + ``on_step_end`` with a tiny runtime stub, **this** suite is the
task 6.1 validation boundary: it drives the real stage end to end **through the
composed ``make_docgen`` bundle**, exactly as ``tests/test_stage_review_integration.py``
and ``tests/test_stage_write_integration.py`` drive Review/Write. It binds the
test-scoped, no-network :class:`tests._fakes.FakeProvider` onto the bundle
(``ModelConfig(main=provider).agentic(make_docgen(journal_dir=out))`` — the exact bind
point the ``dhx`` CLI uses), seeds the assemble-input slots on the run ``State``, and
runs the pipeline once with a minimal ``BaseTask`` passed as ``_resume_state``
(mirroring :func:`docuharnessx.cli.orchestrate_run`).

The AssembleStage thus FIRES inside the live run loop, on the ``step_end`` hook,
reading the slots through the typed :class:`~docuharnessx.context.RunContext` exactly
as it would in production. That is the seam task 6.1 pins (design "Integration Tests:
Stage via the bundle (credential-free)"; Req 2.1-2.6, 5.1, 5.5, 7.4, 7.5, 1.3):

* with a bound run ``State`` carrying a seeded :class:`ReviewReport` (accepted
  segments), the loaded ``Vocabulary``, an output directory, and a target path -> the
  stage publishes a well-formed :class:`AssembledSite` to ``SLOT_ASSEMBLED_SITE`` with
  one page per accepted segment and one landing page per role with accepted content;
* a missing review-report / vocabulary / output-dir slot, or an unsupported
  ``ReviewReport`` schema version, each raise the fatal :class:`AssemblerInputError`
  naming the cause and publish **no** site (Req 2.3, 2.4, 2.6);
* an absent :class:`RepoAnalysis` still produces a site (Req 2.5);
* driven outside a harness (no ``task_start`` to bind a run ``State``) the stage
  forwards the event unchanged and produces nothing, exactly like the no-op base
  (Req 1.3);
* the assembled-site slot round-trips through the run context, a fresh state returns
  the absent value, and the existing slot keys / accessors / exports are unchanged
  (the append-only seam; Req 7.4, 7.5).

Why a directly-seeded ``SLOT_REVIEW_REPORT`` survives a full bundle run
-----------------------------------------------------------------------
Every pipeline stage shares the ``step_end`` hook, firing in canonical order
(ingest…review…assemble). Here only the *Assemble* stage's own inputs are seeded; the
upstream ingest/analyze/classify/plan/write/review stages have **no** slots seeded, so
each raises its own typed input error inside ``step_end`` and the run loop **absorbs
that stage error and continues** to the next stage (the documented crash-skip behavior
that ``tests/test_stage_write_integration.py`` relies on). Crucially the upstream
**Review** stage raises ``ReviewInputError`` on its unset ``SLOT_WRITTEN_SEGMENTS``
*before* it would publish anything, so it never overwrites the seeded
``SLOT_REVIEW_REPORT`` — the AssembleStage then reads exactly the report this suite
seeded. The boundary under test stays the Assemble stage; the report is hand-seeded
(its production producer, Review, is exercised by ``test_stage_review_integration.py``).

Credential-free / network-free: every run binds only :class:`FakeProvider`, and the
target path is a non-git ``tmp_path`` directory, so the only subprocess (the read-only
``git remote get-url origin``) degrades to the no-remote fallback. The production model
resolver is never touched.
"""

from __future__ import annotations

import asyncio
import importlib
import json
import os
import typing
from pathlib import Path
from typing import Any

import pytest
from harnessx.core.events import make_run_id
from harnessx.core.harness import BaseTask
from harnessx.core.model_config import ModelConfig
from harnessx.core.state import State

from docuharnessx.assembler import assemble_site as _assemble_site  # noqa: F401
from docuharnessx.assembler.model import (
    ASSEMBLED_SITE_SCHEMA_VERSION,
    AssembledSite,
    AssemblerInputError,
    SiteIdentity,
)
from docuharnessx.assembler.pages import page_filename
from docuharnessx.bundle import make_docgen
from docuharnessx.context import RunContext
from docuharnessx.ontology import (
    InMemorySegmentStore,
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
from docuharnessx.types import SLOT_ASSEMBLED_SITE

from tests._fakes import FakeProvider


# --------------------------------------------------------------------------- #
# Fixtures: a seeded accepted set + report                                     #
# --------------------------------------------------------------------------- #


def _segment(seg_id: str, *, title: str, roles: list[str], intent: str) -> Segment:
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


def _report(*accepted: Segment, schema_version: int = REVIEW_REPORT_SCHEMA_VERSION) -> ReviewReport:
    return ReviewReport(
        schema_version=schema_version,
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


def _expected_role_pages(vocab: Vocabulary, accepted: tuple[Segment, ...]) -> list[Any]:
    """The vocabulary roles that have at least one accepted segment (non-empty view).

    Computed independently of the stage, against a fresh accepted-only store, so the
    assertion does not just echo the writer's own counting (Req 5.1, 5.5).
    """
    store = InMemorySegmentStore(vocab)
    for seg in accepted:
        store.put(seg)
    return [r for r in vocab.roles if build_role_view(store, r.id, vocab)]


# --------------------------------------------------------------------------- #
# Harness-faithful driver: bind FakeProvider, seed slots, run once via the bundle
# --------------------------------------------------------------------------- #


class _RunResult:
    def __init__(self, *, exit_reason: str, run_context: RunContext, out_dir: str) -> None:
        self.exit_reason = exit_reason
        self.run_context = run_context
        self.out_dir = out_dir

    def assemble_trigger_details(self) -> list[dict[str, Any]]:
        details: list[dict[str, Any]] = []
        for trace in _find_trace_jsonl(self.out_dir):
            for record in _read_jsonl(trace):
                if (
                    record.get("event_type") == "processor_trigger"
                    and record.get("action") == "stage_participated"
                    and record.get("detail", {}).get("stage") == "assemble"
                ):
                    details.append(record["detail"])
        return details


def _drive_assemble_via_bundle(
    *,
    tmp_path,
    report: ReviewReport | None,
    vocab: Vocabulary | None,
    set_output: bool = True,
    set_target: bool = True,
    target_name: str = "repo",
    set_analysis: bool = False,
) -> _RunResult:
    """Run the composed ``make_docgen`` pipeline once with the assemble slots seeded."""
    provider = FakeProvider("done")
    out_dir = str(tmp_path / "out")
    os.makedirs(out_dir, exist_ok=True)

    harness = ModelConfig(main=provider).agentic(make_docgen(journal_dir=out_dir))

    state = State(run_id=make_run_id())
    run_context = RunContext(state)
    if report is not None:
        run_context.set_review_report(report)
    if vocab is not None:
        run_context.set_vocabulary(vocab)
    if set_output:
        run_context.set_output_dir(out_dir)
    if set_target:
        target = tmp_path / target_name
        target.mkdir(exist_ok=True)
        run_context.set_target_repo(str(target))

    task = BaseTask(description="assemble the docs", max_steps=4)
    try:
        harness_result = asyncio.run(harness.run(task, _resume_state=state))
    finally:
        asyncio.run(harness.cleanup())

    return _RunResult(
        exit_reason=harness_result.task_end.exit_reason,
        run_context=run_context,
        out_dir=out_dir,
    )


def _find_trace_jsonl(out_dir: str) -> list[str]:
    found: list[str] = []
    for root, _dirs, files in os.walk(out_dir):
        for name in files:
            if name.endswith("_trace.jsonl"):
                found.append(os.path.join(root, name))
    return found


def _read_jsonl(path: str) -> list[dict]:
    with open(path, "r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


# --------------------------------------------------------------------------- #
# Happy path through the bundle: page + role-page coverage (Req 2.1, 2.2, 5.1, 5.5, 7.1)
# --------------------------------------------------------------------------- #


def test_bundle_run_publishes_assembled_site_with_page_and_role_coverage(tmp_path) -> None:
    vocab = default_profile()
    accepted = _accepted_segments()
    result = _drive_assemble_via_bundle(
        tmp_path=tmp_path, report=_report(*accepted), vocab=vocab
    )
    assert result.exit_reason == "done"

    site = result.run_context.assembled_site()
    assert isinstance(site, AssembledSite)
    assert site.schema_version == ASSEMBLED_SITE_SCHEMA_VERSION

    # One page per accepted segment (Req 4.1).
    assert site.page_count == len(accepted)
    # One landing page per role that has at least one accepted segment, none for empty
    # roles (Req 5.1, 5.5) — computed independently against a fresh accepted-only store.
    expected_roles = _expected_role_pages(vocab, accepted)
    assert site.role_page_count == len(expected_roles)
    assert 0 < site.role_page_count <= len(vocab.roles)

    # The tree exists on disk under <out>/site (the single write target, Req 8.5).
    site_dir = Path(site.site_dir)
    assert site_dir == (Path(result.out_dir) / "site").resolve()
    assert (site_dir / "mkdocs.yml").is_file()
    docs_dir = Path(site.docs_dir)
    assert docs_dir.is_dir()
    for seg in accepted:
        assert (docs_dir / page_filename(seg.id)).is_file()


def test_bundle_run_records_one_bounded_assemble_trigger(tmp_path) -> None:
    # The task 5.2 bounded journal summary is observable through the real journal trace:
    # exactly one assemble participation trigger carrying the counts + identity scalars,
    # never a page body (Req 1.4).
    vocab = default_profile()
    accepted = _accepted_segments()
    result = _drive_assemble_via_bundle(
        tmp_path=tmp_path, report=_report(*accepted), vocab=vocab, target_name="my_target"
    )
    site = result.run_context.assembled_site()

    details = result.assemble_trigger_details()
    assert len(details) == 1
    detail = details[0]
    assert detail["page_count"] == site.page_count
    assert detail["role_page_count"] == site.role_page_count
    assert detail["site_name"] == site.identity.site_name == "my_target"
    assert detail["base_path"] == site.identity.base_path == "/"
    # Bounded: no seeded segment body ("Body of <id>.") leaks into the trace detail.
    serialized = json.dumps(detail)
    for seg in accepted:
        assert seg.body not in serialized


def test_bundle_run_identity_is_per_target_never_docuharnessx(tmp_path) -> None:
    # The resolved identity is per-target (no-remote fallback -> target basename) and
    # never DocuHarnessX's own identity (Req 3.5, 3.8).
    vocab = default_profile()
    result = _drive_assemble_via_bundle(
        tmp_path=tmp_path,
        report=_report(*_accepted_segments()),
        vocab=vocab,
        target_name="malware_hashes",
    )
    site = result.run_context.assembled_site()
    assert isinstance(site.identity, SiteIdentity)
    assert site.identity.site_name == "malware_hashes"
    assert site.identity.base_path == "/"
    assert "docuharnessx" not in site.identity.site_name.lower()
    assert "docuharnessx" not in site.identity.repo_url.lower()
    assert "docuharnessx" not in site.identity.site_url.lower()


def test_bundle_run_absent_analysis_still_produces_a_site(tmp_path) -> None:
    # No RepoAnalysis reaches the analysis slot — driving with no target repo means the
    # upstream Ingest/Analyze stages crash-skip (their inputs unset), so SLOT_REPO_ANALYSIS
    # stays unset. The Assemble stage tolerates the absent slot and still assembles a site
    # (Req 2.5). (With a scannable target the upstream Analyze stage would itself publish a
    # RepoAnalysis; here we pin the genuinely-absent path.)
    vocab = default_profile()
    result = _drive_assemble_via_bundle(
        tmp_path=tmp_path,
        report=_report(*_accepted_segments()),
        vocab=vocab,
        set_target=False,
    )
    assert result.run_context.repo_analysis() is None
    assert result.run_context.assembled_site() is not None


def test_bundle_run_empty_accepted_set_produces_a_buildable_empty_site(tmp_path) -> None:
    # A well-formed empty report (no accepted segments) still yields a site with zero
    # pages and zero role pages (no role has accepted content) (Req 5.5).
    vocab = default_profile()
    result = _drive_assemble_via_bundle(tmp_path=tmp_path, report=_report(), vocab=vocab)
    site = result.run_context.assembled_site()
    assert site is not None
    assert site.page_count == 0
    assert site.role_page_count == 0
    assert (Path(site.site_dir) / "mkdocs.yml").is_file()


# --------------------------------------------------------------------------- #
# Fatal input paths: missing slot / unsupported version -> no site (Req 2.3, 2.4, 2.6)
# --------------------------------------------------------------------------- #
#
# In a full bundle run the run loop absorbs a stage's fatal input error and continues,
# so the OBSERVABLE bundle-level outcome is "no AssembledSite published". To pin that
# the cause is the typed AssemblerInputError (Req 2.3/2.4/2.6) the error itself is also
# asserted on the stage boundary, driven the same way Harness.__init__ + the run loop
# drive it (bind runtime, hand the live State via task_start, then drive step_end
# directly so the raised error propagates rather than being swallowed by ``process``).


class _RuntimeStub:
    tracer = None


def _drive_step_end_raises(state: State) -> None:
    """Drive the real AssembleStage's step_end over *state*, expecting the typed error."""
    from harnessx.core.events import StepEndEvent, TaskStartEvent

    from docuharnessx.stages.assemble import AssembleStage

    stage = AssembleStage()
    stage._bind_runtime(_RuntimeStub())

    async def _start() -> None:
        async for _ in stage.on_task_start(
            TaskStartEvent(run_id=state.run_id, step_id=0, state=state)
        ):
            pass

    asyncio.run(_start())

    async def _step() -> list[Any]:
        event = StepEndEvent(run_id=state.run_id, step_id=1)
        return [out async for out in stage.on_step_end(event)]

    asyncio.run(_step())


def test_missing_review_report_no_site_through_bundle_and_typed_error(tmp_path) -> None:
    # Bundle-level: with no review-report seeded the run completes (Review/Assemble both
    # crash-skip) and publishes NO site (Req 2.3).
    result = _drive_assemble_via_bundle(
        tmp_path=tmp_path, report=None, vocab=default_profile()
    )
    assert result.run_context.assembled_site() is None

    # Boundary-level: the cause is the typed AssemblerInputError, no site produced.
    state = State(run_id="run-no-report")
    rc = RunContext(state)
    rc.set_vocabulary(default_profile())
    rc.set_output_dir(str(tmp_path / "out"))
    rc.set_target_repo(str(tmp_path / "repo"))
    with pytest.raises(AssemblerInputError):
        _drive_step_end_raises(state)
    assert RunContext(state).assembled_site() is None


def test_missing_vocabulary_no_site_through_bundle_and_typed_error(tmp_path) -> None:
    result = _drive_assemble_via_bundle(
        tmp_path=tmp_path, report=_report(*_accepted_segments()), vocab=None
    )
    assert result.run_context.assembled_site() is None

    state = State(run_id="run-no-vocab")
    rc = RunContext(state)
    rc.set_review_report(_report(*_accepted_segments()))
    rc.set_output_dir(str(tmp_path / "out"))
    rc.set_target_repo(str(tmp_path / "repo"))
    with pytest.raises(AssemblerInputError):
        _drive_step_end_raises(state)
    assert RunContext(state).assembled_site() is None


def test_missing_output_dir_no_site_through_bundle_and_typed_error(tmp_path) -> None:
    result = _drive_assemble_via_bundle(
        tmp_path=tmp_path,
        report=_report(*_accepted_segments()),
        vocab=default_profile(),
        set_output=False,
    )
    assert result.run_context.assembled_site() is None

    state = State(run_id="run-no-out")
    rc = RunContext(state)
    rc.set_review_report(_report(*_accepted_segments()))
    rc.set_vocabulary(default_profile())
    rc.set_target_repo(str(tmp_path / "repo"))
    # SLOT_OUTPUT_DIR deliberately unset.
    with pytest.raises(AssemblerInputError):
        _drive_step_end_raises(state)
    assert RunContext(state).assembled_site() is None


def test_unsupported_review_report_version_no_site_through_bundle_and_typed_error(
    tmp_path,
) -> None:
    bad = _report(
        *_accepted_segments(), schema_version=REVIEW_REPORT_SCHEMA_VERSION + 999
    )
    result = _drive_assemble_via_bundle(
        tmp_path=tmp_path, report=bad, vocab=default_profile()
    )
    assert result.run_context.assembled_site() is None

    state = State(run_id="run-bad-version")
    rc = RunContext(state)
    rc.set_review_report(bad)
    rc.set_vocabulary(default_profile())
    rc.set_output_dir(str(tmp_path / "out"))
    rc.set_target_repo(str(tmp_path / "repo"))
    with pytest.raises(AssemblerInputError) as excinfo:
        _drive_step_end_raises(state)
    # The error names the unsupported version (auditable cause, Req 2.4).
    assert str(REVIEW_REPORT_SCHEMA_VERSION + 999) in str(excinfo.value)
    assert RunContext(state).assembled_site() is None


# --------------------------------------------------------------------------- #
# Out-of-harness pass-through: no bound State -> forward event, no site (Req 1.3)
# --------------------------------------------------------------------------- #


def test_out_of_harness_drive_forwards_event_and_produces_nothing() -> None:
    from harnessx.core.events import StepEndEvent

    from docuharnessx.stages.assemble import make_assemble_stage

    stage = make_assemble_stage()  # never task_start'd, no runtime bound
    event = StepEndEvent(run_id="run-off-harness", step_id=3)

    async def _collect() -> list[Any]:
        return [out async for out in stage.process(event)]

    out = asyncio.run(_collect())
    assert len(out) == 1
    assert out[0] is event


# --------------------------------------------------------------------------- #
# Append-only seam: SLOT_ASSEMBLED_SITE round-trip + unchanged surface (Req 7.4, 7.5)
# --------------------------------------------------------------------------- #


CANONICAL_STAGES = (
    "ingest",
    "analyze",
    "classify",
    "plan",
    "write",
    "review",
    "assemble",
    "deploy",
)

_EXISTING_SLOT_KEYS = {
    "SLOT_TARGET_REPO": "docuharnessx.target_repo",
    "SLOT_OUTPUT_DIR": "docuharnessx.output_dir",
    "SLOT_SEGMENT_STORE": "docuharnessx.segment_store",
    "SLOT_VOCABULARY": "docuharnessx.vocabulary",
    "SLOT_FILE_INVENTORY": "docuharnessx.file_inventory",
    "SLOT_REPO_ANALYSIS": "docuharnessx.repo_analysis",
    "SLOT_CLASSIFICATION": "docuharnessx.classification",
    "SLOT_COVERAGE_PLAN": "docuharnessx.coverage_plan",
    "SLOT_WRITTEN_SEGMENTS": "docuharnessx.written_segments",
    "SLOT_REVIEW_REPORT": "docuharnessx.review_report",
}


def _identity() -> SiteIdentity:
    return SiteIdentity(
        site_name="malware_hashes",
        repo_name="norandom/malware_hashes",
        repo_url="https://github.com/norandom/malware_hashes",
        site_url="https://norandom.github.io/malware_hashes/",
        base_path="/malware_hashes/",
        edit_uri="edit/main/docs/",
    )


def _assembled_site() -> AssembledSite:
    return AssembledSite(
        schema_version=ASSEMBLED_SITE_SCHEMA_VERSION,
        site_dir="/tmp/out/site",
        docs_dir="/tmp/out/site/docs",
        mkdocs_yml_path="/tmp/out/site/mkdocs.yml",
        identity=_identity(),
        page_count=3,
        role_page_count=2,
    )


def test_assembled_site_slot_round_trips_through_run_context() -> None:
    state = State(run_id="run-seam")
    ctx = RunContext(state)
    assert ctx.assembled_site() is None  # explicit absent before set (Req 7.4)
    value = _assembled_site()
    ctx.set_assembled_site(value)
    assert ctx.assembled_site() is value
    # Written through the shared SLOT_ASSEMBLED_SITE key (Req 7.5).
    slot = state.get_slot(SLOT_ASSEMBLED_SITE)
    assert slot is not None
    assert slot.content is value


def test_fresh_state_returns_absent_assembled_site() -> None:
    assert RunContext(State(run_id="run-fresh")).assembled_site() is None


def test_assembled_site_slot_does_not_disturb_sibling_accessors() -> None:
    ctx = RunContext(State(run_id="run-indep"))
    ctx.set_assembled_site(_assembled_site())
    assert ctx.review_report() is None
    assert ctx.written_segments() is None
    assert ctx.coverage_plan() is None
    assert ctx.vocabulary() is None
    assert ctx.repo_analysis() is None


def test_existing_slot_keys_and_stage_names_unchanged_by_extension() -> None:
    # The append-only seam extension modified no existing slot key, StageName, or
    # STAGE_NAMES entry (Req 7.5).
    types_mod = importlib.import_module("docuharnessx.types")
    for name, value in _EXISTING_SLOT_KEYS.items():
        assert getattr(types_mod, name) == value
    assert types_mod.SLOT_ASSEMBLED_SITE == "docuharnessx.assembled_site"
    assert "SLOT_ASSEMBLED_SITE" in set(types_mod.__all__)
    assert tuple(typing.get_args(types_mod.StageName)) == CANONICAL_STAGES
    assert tuple(types_mod.STAGE_NAMES) == CANONICAL_STAGES

    # No existing key collides with the new one.
    all_values = list(_EXISTING_SLOT_KEYS.values()) + [types_mod.SLOT_ASSEMBLED_SITE]
    assert len(set(all_values)) == len(all_values)
