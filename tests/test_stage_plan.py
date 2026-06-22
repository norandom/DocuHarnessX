"""Tests for the real Plan stage adapter (task 4.3 boundary: PlanStage).

The Plan stage replaces the no-op stub in ``docuharnessx/stages/plan.py`` with a
thin HarnessX adapter that materializes the frozen :class:`CoveragePlan` as a side
effect of the content-free ``step_end`` lifecycle event (design "PlanStage", "Why
work happens as a step_end side effect"):

* it reaches the run ``State`` through the ``TaskStartEvent`` (``StepEndEvent`` is
  content-free), captured in ``on_task_start`` and wrapped in a ``RunContext`` from
  ``on_step_end`` — the same mechanism the Classify/Analyze stages use;
* reads ``classification()``; if unset it raises :class:`PlanningInputError`,
  halting the run with a clear cause and **no** partial plan (Req 2.4);
* reads ``vocabulary()``, runs the deterministic ``plan_coverage()`` core (no model,
  no network), optionally applies the gated, failure-tolerant ``apply_relevance``
  hook (off by default; Req 8.2-8.4), writes the produced :class:`CoveragePlan` into
  ``SLOT_COVERAGE_PLAN`` (Req 7.3), emits a participation ``ProcessorTriggerEvent``
  plus a bounded plan summary to the journal (Req 9.2, 9.3, 9.4), and yields the
  ``StepEndEvent`` unchanged (Req 1.2, 1.3).

The class name ``PlanStage``, the factory ``make_plan_stage``, the ``STAGE_NAME``
constant, and the module path are kept stable so the stage registry and
``make_docgen`` need no edits (Req 1.1).

These tests are harness-free: they drive ``on_step_end`` directly with a tiny
runtime stub (carrying a capturing ``tracer``) bound via ``_bind_runtime``, and
``on_task_start`` with a ``TaskStartEvent`` carrying the run ``State`` — the same
lifecycle ``Harness.__init__`` / the run loop produce. No credentials, no network.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from typing import Any

import pytest

from harnessx.core.events import (
    ProcessorTriggerEvent,
    StepEndEvent,
    TaskStartEvent,
)
from harnessx.core.processor import Processor
from harnessx.core.state import State

from docuharnessx.analysis.model import (
    Artifact,
    BuildFile,
    CIWorkflow,
    Component,
    Dependency,
    DocPresence,
    Entrypoint,
    LanguageStat,
    PublicSymbol,
    RepoAnalysis,
    ScanStats,
)
from docuharnessx.analysis.model import TestLayout as _TestLayout  # noqa: N813
from docuharnessx.context import RunContext
from docuharnessx.ontology import Vocabulary, default_profile
from docuharnessx.planning import (
    Classification,
    CoveragePlan,
    classify_repo,
    plan_coverage,
)
from docuharnessx.planning.model import PlanningInputError
from docuharnessx.stages.base import (
    NoOpStage,
    PIPELINE_HOOK,
    STAGE_PARTICIPATION_ACTION,
)
from docuharnessx.stages.plan import (
    STAGE_NAME,
    PlanStage,
    make_noop_stage,
    make_plan_stage,
)
from docuharnessx.types import SLOT_COVERAGE_PLAN


# --------------------------------------------------------------------------- #
# Harness-free drivers and a minimal runtime stub                              #
# --------------------------------------------------------------------------- #


@dataclass
class _CapturingTracer:
    """A stand-in run tracer that records every event emitted to ``on_event``."""

    events: list[Any]

    def __init__(self) -> None:
        self.events = []

    async def on_event(self, event: Any) -> None:
        self.events.append(event)


class _RuntimeStub:
    """Minimal ``_HarnessRuntime`` stand-in carrying the run ``tracer``."""

    def __init__(self, tracer: _CapturingTracer | None) -> None:
        self.tracer = tracer


class _ModelConfigStub:
    """A ``ModelConfig`` stand-in exposing a ``main`` provider for the gated hook."""

    def __init__(self, main: Any) -> None:
        self.main = main


class _RerankProvider:
    """A model stub that re-ranks (reverses) the planned segment keys + annotates."""

    async def complete(
        self, messages: Any, tools: Any, stream_callback: object | None = None
    ) -> Any:
        # The brief lists "key=<segment_key> ..." lines; recover the keys and reverse.
        brief = ""
        for msg in messages:
            content = getattr(msg, "content", None)
            if content is None and isinstance(msg, dict):
                content = msg.get("content", "")
            if content and "key=" in content:
                brief = content
        keys: list[str] = []
        for line in brief.splitlines():
            line = line.strip()
            if line.startswith("- key="):
                keys.append(line[len("- key="):].split(" ", 1)[0])
        order = list(reversed(keys))
        notes = {k: f"note-{i}" for i, k in enumerate(order)}
        import json

        payload = json.dumps({"order": order, "notes": notes})
        return _Resp(payload)


class _FailingProvider:
    """A model stub whose ``complete`` always raises (simulated hook failure)."""

    async def complete(
        self, messages: Any, tools: Any, stream_callback: object | None = None
    ) -> Any:
        raise RuntimeError("simulated relevance failure")


@dataclass
class _Resp:
    """A minimal ``ModelResponseEvent``-shaped object: only ``.content`` is read."""

    content: str


def _sample_event() -> StepEndEvent:
    """A representative content-free lifecycle event the stage must not mutate."""
    return StepEndEvent(
        run_id="run-test",
        step_id=9,
        step_summary="prior summary",
        tool_call_summary="readFile(a)",
        cumulative_tokens=10,
        cumulative_cost_usd=0.1,
    )


def _drive(stage: Processor, event: StepEndEvent) -> list[Any]:
    """Run the stage's async ``on_step_end`` generator to completion."""

    async def _collect() -> list[Any]:
        return [out async for out in stage.on_step_end(event)]

    return asyncio.run(_collect())


def _start_task(stage: PlanStage, state: State) -> None:
    """Drive ``on_task_start`` so the stage captures the live run ``State``."""

    async def _collect() -> None:
        async for _ in stage.on_task_start(
            TaskStartEvent(run_id=state.run_id, step_id=0, state=state)
        ):
            pass

    asyncio.run(_collect())


def _bound_stage(
    state: State,
    *,
    tracer: _CapturingTracer | None = None,
    model: Any | None = None,
    relevance_enabled: bool = False,
) -> PlanStage:
    """Build a ``PlanStage`` with the run State captured and a tracer/model bound."""
    stage = PlanStage()
    if relevance_enabled:
        stage.relevance_enabled = True
    rt = _RuntimeStub(tracer)
    stage._bind_runtime(rt)
    if model is not None:
        stage._bind_model_config(_ModelConfigStub(model))
    _start_task(stage, state)
    return stage


# --------------------------------------------------------------------------- #
# Fixtures: crafted RepoAnalysis + a state carrying the Classify handoff slot   #
# --------------------------------------------------------------------------- #


def _empty_analysis() -> RepoAnalysis:
    return RepoAnalysis(
        schema_version=1,
        repo_path="/repo/empty",
        languages=(),
        primary_languages=(),
        total_loc=0,
        total_files=0,
        structure=(),
        entrypoints=(),
        build_files=(),
        ci_workflows=(),
        tests=_TestLayout(present=False, frameworks=(), paths=()),
        dependencies=(),
        components=(),
        public_surface=(),
        docs=DocPresence(
            has_readme=False, readme_paths=(), doc_dirs=(), other_docs=()
        ),
        artifacts=(),
        scan_stats=ScanStats(
            files_scanned=0,
            files_skipped=0,
            bytes_scanned=0,
            limit_reached=False,
            notes=(),
        ),
    )


def _full_analysis() -> RepoAnalysis:
    """A Go-CLI-shaped analysis exercising several rule-table predicates."""
    return replace(
        _empty_analysis(),
        repo_path="/repo/malware_hashes",
        languages=(
            LanguageStat(language="Go", files=12, loc=3400),
            LanguageStat(language="Markdown", files=8, loc=1200),
        ),
        primary_languages=("Go",),
        total_loc=4600,
        total_files=20,
        entrypoints=(Entrypoint(path="cmd/mh/main.go", kind="cli", name="mh"),),
        build_files=(BuildFile(path="go.mod", kind="go_mod"),),
        ci_workflows=(
            CIWorkflow(path=".github/workflows/ci.yml", provider="github_actions"),
        ),
        tests=_TestLayout(
            present=True, frameworks=("go_testing",), paths=("hash_test.go",)
        ),
        dependencies=(
            Dependency(
                name="cobra",
                version_spec="v1.8.0",
                source="go.mod",
                scope="runtime",
            ),
        ),
        components=(
            Component(
                name="hashing",
                path="internal/hashing",
                representative_files=("internal/hashing/hash.go",),
            ),
        ),
        public_surface=(
            PublicSymbol(
                name="scan", kind="cli_subcommand", source="cmd/mh/main.go"
            ),
            PublicSymbol(
                name="Hash",
                kind="exported_symbol",
                source="internal/hashing/hash.go",
            ),
        ),
        docs=DocPresence(
            has_readme=True,
            readme_paths=("README.md",),
            doc_dirs=(),
            other_docs=(),
        ),
        artifacts=(Artifact(path="LICENSE", kind="license"),),
    )


def _state_with_classification(
    analysis: RepoAnalysis | None, vocab: Vocabulary | None
) -> State:
    """Build a run State pre-loaded with a Classification (+ vocabulary) slot.

    Mirrors what the upstream ClassifyStage publishes: it runs the deterministic
    ``classify_repo`` over ``analysis`` and places the result into
    ``SLOT_CLASSIFICATION`` so the Plan stage has its handoff input.
    """
    state = State(run_id="r-plan")
    rc = RunContext(state)
    if vocab is not None:
        rc.set_vocabulary(vocab)
    if analysis is not None and vocab is not None:
        rc.set_classification(classify_repo(analysis, vocab))
    return state


# --------------------------------------------------------------------------- #
# Contract stability (Req 1.1): names/factory/module path/hook unchanged       #
# --------------------------------------------------------------------------- #


def test_stage_name_is_stable() -> None:
    assert STAGE_NAME == "plan"
    assert PlanStage.stage_name == "plan"


def test_factory_returns_a_fresh_plan_stage() -> None:
    proc = make_plan_stage()
    assert isinstance(proc, Processor)
    assert isinstance(proc, PlanStage)
    assert make_plan_stage() is not make_plan_stage()


def test_plan_stage_subclasses_noop_base_on_pipeline_hook() -> None:
    assert issubclass(PlanStage, NoOpStage)
    assert PlanStage._hook == PIPELINE_HOOK


def test_module_path_is_stable() -> None:
    assert PlanStage.__module__ == "docuharnessx.stages.plan"


def test_module_still_reexports_shared_noop_factory() -> None:
    from docuharnessx.stages import base as base_module

    assert make_noop_stage is base_module.make_noop_stage


# --------------------------------------------------------------------------- #
# Happy path: publishes CoveragePlan into the slot (Req 1.2, 7.3)              #
# --------------------------------------------------------------------------- #


def test_publishes_coverage_plan_into_slot() -> None:
    vocab = default_profile()
    state = _state_with_classification(_full_analysis(), vocab)
    stage = _bound_stage(state)
    out = _drive(stage, _sample_event())

    assert len(out) == 1
    published = RunContext(state).coverage_plan()
    assert isinstance(published, CoveragePlan)
    # Equals the deterministic core plan_coverage over the same classification.
    classification = classify_repo(_full_analysis(), vocab)
    assert published == plan_coverage(classification, vocab)
    assert published.relevance_applied is False


def test_published_plan_written_through_named_slot() -> None:
    vocab = default_profile()
    state = _state_with_classification(_full_analysis(), vocab)
    _drive(_bound_stage(state), _sample_event())

    slot = state.get_slot(SLOT_COVERAGE_PLAN)
    assert slot is not None
    assert isinstance(slot.content, CoveragePlan)


def test_event_is_forwarded_unchanged() -> None:
    vocab = default_profile()
    state = _state_with_classification(_full_analysis(), vocab)
    stage = _bound_stage(state)
    event = _sample_event()
    out = _drive(stage, event)
    assert len(out) == 1
    assert out[0] is event  # same object, content-neutral pass-through


def test_two_runs_publish_equal_plan() -> None:
    vocab = default_profile()

    def _publish() -> CoveragePlan:
        state = _state_with_classification(_full_analysis(), vocab)
        _drive(_bound_stage(state), _sample_event())
        return RunContext(state).coverage_plan()

    assert _publish() == _publish()


def test_plan_has_segments_ordered_priority_desc() -> None:
    vocab = default_profile()
    state = _state_with_classification(_full_analysis(), vocab)
    _drive(_bound_stage(state), _sample_event())
    plan = RunContext(state).coverage_plan()
    priorities = [seg.priority for seg in plan.segments]
    assert priorities == sorted(priorities, reverse=True)
    assert len(plan.segments) > 0


# --------------------------------------------------------------------------- #
# Empty-evidence: well-formed empty plan + journaled empty_reason (Req 5.5)     #
# --------------------------------------------------------------------------- #


def test_empty_classification_yields_wellformed_empty_plan() -> None:
    vocab = default_profile()
    state = _state_with_classification(_empty_analysis(), vocab)
    _drive(_bound_stage(state), _sample_event())
    plan = RunContext(state).coverage_plan()
    assert isinstance(plan, CoveragePlan)
    assert plan.segments == ()  # well-formed, no fabricated segments


def test_empty_plan_records_explainable_reason_in_journal() -> None:
    vocab = default_profile()
    state = _state_with_classification(_empty_analysis(), vocab)
    tracer = _CapturingTracer()
    _drive(_bound_stage(state, tracer=tracer), _sample_event())

    trig = [e for e in tracer.events if isinstance(e, ProcessorTriggerEvent)][0]
    detail = trig.detail
    assert detail["total_segments"] == 0
    # An explainable, non-empty reason string for the empty result (Req 9.4).
    assert isinstance(detail["empty_reason"], str)
    assert detail["empty_reason"] != ""


def test_nonempty_plan_has_no_empty_reason() -> None:
    vocab = default_profile()
    state = _state_with_classification(_full_analysis(), vocab)
    tracer = _CapturingTracer()
    _drive(_bound_stage(state, tracer=tracer), _sample_event())

    trig = [e for e in tracer.events if isinstance(e, ProcessorTriggerEvent)][0]
    assert trig.detail["empty_reason"] == ""
    assert trig.detail["total_segments"] > 0


# --------------------------------------------------------------------------- #
# Input errors halt the run with an identifiable cause (Req 2.4)               #
# --------------------------------------------------------------------------- #


def test_missing_classification_raises_planning_input_error() -> None:
    # vocabulary present but no classification published by an upstream Classify.
    state = State(run_id="r-plan")
    RunContext(state).set_vocabulary(default_profile())
    stage = _bound_stage(state)
    with pytest.raises(PlanningInputError):
        _drive(stage, _sample_event())


def test_missing_classification_does_not_publish_partial_plan() -> None:
    state = State(run_id="r-plan")
    RunContext(state).set_vocabulary(default_profile())
    stage = _bound_stage(state)
    with pytest.raises(PlanningInputError):
        _drive(stage, _sample_event())
    assert RunContext(state).coverage_plan() is None


def test_input_error_message_names_the_offending_cause() -> None:
    state = State(run_id="r-plan")
    RunContext(state).set_vocabulary(default_profile())
    stage = _bound_stage(state)
    with pytest.raises(PlanningInputError) as excinfo:
        _drive(stage, _sample_event())
    assert "classification" in str(excinfo.value).lower()


def test_missing_vocabulary_raises_planning_input_error() -> None:
    # A classification exists but the vocabulary slot is unset: the plan core needs
    # the vocabulary for scoring/ordering, so this is a fatal input error.
    state = State(run_id="r-plan")
    vocab = default_profile()
    RunContext(state).set_classification(
        classify_repo(_full_analysis(), vocab)
    )
    stage = _bound_stage(state)
    with pytest.raises(PlanningInputError):
        _drive(stage, _sample_event())


# --------------------------------------------------------------------------- #
# Driven outside a harness (no runtime/State bound): graceful pass-through     #
# --------------------------------------------------------------------------- #


def test_pass_through_when_no_runtime_bound() -> None:
    stage = PlanStage()  # never _bind_runtime'd, no task_start
    event = _sample_event()

    async def _collect() -> list[Any]:
        return [out async for out in stage.process(event)]

    out = asyncio.run(_collect())
    assert len(out) == 1
    assert out[0] is event


# --------------------------------------------------------------------------- #
# Journal participation + bounded summary (Req 9.2, 9.3, 9.4)                  #
# --------------------------------------------------------------------------- #


def test_emits_participation_trigger_with_bounded_summary() -> None:
    vocab = default_profile()
    state = _state_with_classification(_full_analysis(), vocab)
    tracer = _CapturingTracer()
    _drive(_bound_stage(state, tracer=tracer), _sample_event())

    triggers = [e for e in tracer.events if isinstance(e, ProcessorTriggerEvent)]
    assert len(triggers) == 1
    trig = triggers[0]
    assert trig.processor == "PlanStage"
    assert trig.hook == PIPELINE_HOOK
    assert trig.action == STAGE_PARTICIPATION_ACTION
    detail = trig.detail
    assert detail["stage"] == "plan"
    plan = RunContext(state).coverage_plan()
    assert detail["total_segments"] == len(plan.segments)
    assert detail["relevance_applied"] is False
    # top_segment_keys is a bounded list of the highest-priority segment keys.
    top = detail["top_segment_keys"]
    assert isinstance(top, list)
    assert len(top) <= len(plan.segments)
    expected_top = [seg.segment_key for seg in plan.segments][: len(top)]
    assert top == expected_top


def test_summary_does_not_embed_full_plan() -> None:
    vocab = default_profile()
    state = _state_with_classification(_full_analysis(), vocab)
    tracer = _CapturingTracer()
    _drive(_bound_stage(state, tracer=tracer), _sample_event())

    detail = [
        e for e in tracer.events if isinstance(e, ProcessorTriggerEvent)
    ][0].detail
    # Every detail value is a small scalar/list of scalars — not a CoveragePlan.
    for value in detail.values():
        assert isinstance(value, (str, int, bool, list))
    for key in detail["top_segment_keys"]:
        assert isinstance(key, str)
    assert not isinstance(detail.get("plan"), CoveragePlan)


def test_top_segment_keys_is_bounded() -> None:
    vocab = default_profile()
    state = _state_with_classification(_full_analysis(), vocab)
    tracer = _CapturingTracer()
    _drive(_bound_stage(state, tracer=tracer), _sample_event())
    detail = [
        e for e in tracer.events if isinstance(e, ProcessorTriggerEvent)
    ][0].detail
    # Bounded summary: the journal never lists more than a small cap of keys.
    assert len(detail["top_segment_keys"]) <= 5


def test_works_without_a_bound_tracer() -> None:
    vocab = default_profile()
    state = _state_with_classification(_full_analysis(), vocab)
    stage = _bound_stage(state, tracer=None)
    out = _drive(stage, _sample_event())
    assert len(out) == 1
    assert isinstance(RunContext(state).coverage_plan(), CoveragePlan)


# --------------------------------------------------------------------------- #
# The gated relevance hook (Req 8.2, 8.3, 8.4)                                  #
# --------------------------------------------------------------------------- #


def test_relevance_disabled_by_default_keeps_deterministic_plan() -> None:
    # No model bound and the gate off: the published plan is the bare deterministic
    # plan with relevance_applied=False.
    vocab = default_profile()
    state = _state_with_classification(_full_analysis(), vocab)
    stage = _bound_stage(state)  # relevance_enabled defaults to False
    _drive(stage, _sample_event())
    plan = RunContext(state).coverage_plan()
    assert plan.relevance_applied is False
    assert plan == plan_coverage(classify_repo(_full_analysis(), vocab), vocab)


def test_relevance_gate_off_with_model_bound_does_not_call_model() -> None:
    # A model is reachable but the gate is OFF: the model must not be consulted and
    # the deterministic plan is published unchanged.
    vocab = default_profile()
    state = _state_with_classification(_full_analysis(), vocab)
    stage = _bound_stage(
        state, model=_RerankProvider(), relevance_enabled=False
    )
    _drive(stage, _sample_event())
    plan = RunContext(state).coverage_plan()
    assert plan.relevance_applied is False
    assert plan == plan_coverage(classify_repo(_full_analysis(), vocab), vocab)


def test_relevance_enabled_failure_falls_back_to_deterministic_plan() -> None:
    # The gate is ON and a model is bound, but the model raises: the hook absorbs the
    # failure and the deterministic plan is retained (relevance_applied=False).
    vocab = default_profile()
    state = _state_with_classification(_full_analysis(), vocab)
    stage = _bound_stage(
        state, model=_FailingProvider(), relevance_enabled=True
    )
    _drive(stage, _sample_event())
    plan = RunContext(state).coverage_plan()
    assert plan.relevance_applied is False
    assert plan.segments == plan_coverage(
        classify_repo(_full_analysis(), vocab), vocab
    ).segments


def test_relevance_enabled_success_reorders_and_annotates_only() -> None:
    # The gate is ON and a re-ranking model is bound: the plan is reordered and
    # annotated, but every segment's required writer fields are preserved and the
    # set of segments is unchanged (Req 8.2).
    vocab = default_profile()
    state = _state_with_classification(_full_analysis(), vocab)
    stage = _bound_stage(
        state, model=_RerankProvider(), relevance_enabled=True
    )
    _drive(stage, _sample_event())
    plan = RunContext(state).coverage_plan()

    deterministic = plan_coverage(classify_repo(_full_analysis(), vocab), vocab)
    if len(deterministic.segments) >= 2:
        assert plan.relevance_applied is True
        # Same set of segment keys (no add/drop), reordered (reversed) here.
        assert {s.segment_key for s in plan.segments} == {
            s.segment_key for s in deterministic.segments
        }
        # Required writer fields preserved per key.
        det_by_key = {s.segment_key: s for s in deterministic.segments}
        for seg in plan.segments:
            d = det_by_key[seg.segment_key]
            assert seg.roles == d.roles
            assert seg.intent == d.intent
            assert seg.subjects == d.subjects
            assert seg.priority == d.priority
            assert seg.evidence == d.evidence


def test_relevance_applied_flag_in_journal_summary_on_success() -> None:
    vocab = default_profile()
    deterministic = plan_coverage(classify_repo(_full_analysis(), vocab), vocab)
    if len(deterministic.segments) < 2:
        pytest.skip("needs >=2 segments to observe a re-rank")
    state = _state_with_classification(_full_analysis(), vocab)
    tracer = _CapturingTracer()
    _drive(
        _bound_stage(
            state, tracer=tracer, model=_RerankProvider(), relevance_enabled=True
        ),
        _sample_event(),
    )
    trig = [e for e in tracer.events if isinstance(e, ProcessorTriggerEvent)][0]
    assert trig.detail["relevance_applied"] is True
