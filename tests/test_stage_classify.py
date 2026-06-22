"""Tests for the real Classify stage adapter (task 4.2 boundary: ClassifyStage).

The Classify stage replaces the no-op stub in ``docuharnessx/stages/classify.py``
with a thin HarnessX adapter that does the real classification as a side effect of
the content-free ``step_end`` lifecycle event (design "ClassifyStage", "Why work
happens as a step_end side effect"):

* it reaches the run ``State`` through the ``TaskStartEvent`` (``StepEndEvent`` is
  content-free), captured in ``on_task_start`` and wrapped in a ``RunContext`` from
  ``on_step_end`` — the same mechanism the Analyze stage uses;
* reads ``repo_analysis()`` and ``vocabulary()``; if either is unset, or the
  analysis declares an unsupported ``schema_version``, it raises
  :class:`PlanningInputError`, halting the run with a clear cause and **no** partial
  classification (Req 2.3, 2.4, 2.5);
* otherwise runs the deterministic ``classify_repo()`` core (no model, no network),
  writes the produced :class:`Classification` into ``SLOT_CLASSIFICATION`` (Req 7.x),
  emits a participation ``ProcessorTriggerEvent`` plus a bounded classify summary to
  the journal (Req 9.1, 9.3), and yields the ``StepEndEvent`` unchanged (Req 1.2,
  1.3).

The class name ``ClassifyStage``, the factory ``make_classify_stage``, the
``STAGE_NAME`` constant, and the module path are kept stable so the stage registry
and ``make_docgen`` need no edits (Req 1.1).

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
from docuharnessx.planning import Classification, classify_repo
from docuharnessx.planning.model import PlanningInputError
from docuharnessx.stages.base import (
    NoOpStage,
    PIPELINE_HOOK,
    STAGE_PARTICIPATION_ACTION,
)
from docuharnessx.stages.classify import (
    STAGE_NAME,
    ClassifyStage,
    make_classify_stage,
    make_noop_stage,
)
from docuharnessx.types import SLOT_CLASSIFICATION


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


def _sample_event() -> StepEndEvent:
    """A representative content-free lifecycle event the stage must not mutate."""
    return StepEndEvent(
        run_id="run-test",
        step_id=7,
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


def _start_task(stage: ClassifyStage, state: State) -> None:
    """Drive ``on_task_start`` so the stage captures the live run ``State``."""

    async def _collect() -> None:
        async for _ in stage.on_task_start(
            TaskStartEvent(run_id=state.run_id, step_id=0, state=state)
        ):
            pass

    asyncio.run(_collect())


def _bound_stage(
    state: State, *, tracer: _CapturingTracer | None = None
) -> ClassifyStage:
    """Build a ``ClassifyStage`` with the run State captured and a tracer bound."""
    stage = ClassifyStage()
    stage._bind_runtime(_RuntimeStub(tracer))
    _start_task(stage, state)
    return stage


# --------------------------------------------------------------------------- #
# Fixtures: crafted RepoAnalysis + a state carrying analysis + vocabulary      #
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


def _state_with(
    analysis: RepoAnalysis | None, vocab: Vocabulary | None
) -> State:
    """Build a run State pre-loaded with the given analysis + vocabulary slots."""
    state = State(run_id="r-classify")
    rc = RunContext(state)
    if analysis is not None:
        rc.set_repo_analysis(analysis)
    if vocab is not None:
        rc.set_vocabulary(vocab)
    return state


# --------------------------------------------------------------------------- #
# Contract stability (Req 1.1): names/factory/module path/hook unchanged       #
# --------------------------------------------------------------------------- #


def test_stage_name_is_stable() -> None:
    assert STAGE_NAME == "classify"
    assert ClassifyStage.stage_name == "classify"


def test_factory_returns_a_fresh_classify_stage() -> None:
    proc = make_classify_stage()
    assert isinstance(proc, Processor)
    assert isinstance(proc, ClassifyStage)
    assert make_classify_stage() is not make_classify_stage()


def test_classify_stage_subclasses_noop_base_on_pipeline_hook() -> None:
    assert issubclass(ClassifyStage, NoOpStage)
    assert ClassifyStage._hook == PIPELINE_HOOK


def test_module_path_is_stable() -> None:
    assert ClassifyStage.__module__ == "docuharnessx.stages.classify"


def test_module_still_reexports_shared_noop_factory() -> None:
    # The shared stage suite asserts every stage module re-exports the base
    # make_noop_stage; keep it importable from this module.
    from docuharnessx.stages import base as base_module

    assert make_noop_stage is base_module.make_noop_stage


# --------------------------------------------------------------------------- #
# Happy path: publishes Classification into the slot (Req 1.2, 2.1)            #
# --------------------------------------------------------------------------- #


def test_publishes_classification_into_slot() -> None:
    state = _state_with(_full_analysis(), default_profile())
    stage = _bound_stage(state)
    out = _drive(stage, _sample_event())

    assert len(out) == 1
    published = RunContext(state).classification()
    assert isinstance(published, Classification)
    # Equals the deterministic core classify_repo over the same inputs.
    assert published == classify_repo(_full_analysis(), default_profile())


def test_published_classification_written_through_named_slot() -> None:
    state = _state_with(_full_analysis(), default_profile())
    _drive(_bound_stage(state), _sample_event())

    slot = state.get_slot(SLOT_CLASSIFICATION)
    assert slot is not None
    assert isinstance(slot.content, Classification)


def test_event_is_forwarded_unchanged() -> None:
    state = _state_with(_full_analysis(), default_profile())
    stage = _bound_stage(state)
    event = _sample_event()
    out = _drive(stage, event)
    assert len(out) == 1
    assert out[0] is event  # same object, content-neutral pass-through


def test_two_runs_publish_equal_classification() -> None:
    def _publish() -> Classification:
        state = _state_with(_full_analysis(), default_profile())
        _drive(_bound_stage(state), _sample_event())
        return RunContext(state).classification()

    assert _publish() == _publish()


def test_empty_analysis_yields_wellformed_classification() -> None:
    state = _state_with(_empty_analysis(), default_profile())
    _drive(_bound_stage(state), _sample_event())
    published = RunContext(state).classification()
    assert isinstance(published, Classification)
    # No error for "no findings": a well-formed, possibly-empty Classification.
    assert published.cells == ()


# --------------------------------------------------------------------------- #
# Input errors halt the run with an identifiable cause (Req 2.3, 2.4, 2.5)     #
# --------------------------------------------------------------------------- #


def test_missing_analysis_raises_planning_input_error() -> None:
    state = _state_with(None, default_profile())  # analysis slot never set
    stage = _bound_stage(state)
    with pytest.raises(PlanningInputError):
        _drive(stage, _sample_event())


def test_missing_vocabulary_raises_planning_input_error() -> None:
    state = _state_with(_full_analysis(), None)  # vocabulary slot never set
    stage = _bound_stage(state)
    with pytest.raises(PlanningInputError):
        _drive(stage, _sample_event())


def test_unsupported_analysis_schema_version_raises() -> None:
    bad = replace(_full_analysis(), schema_version=999)
    state = _state_with(bad, default_profile())
    stage = _bound_stage(state)
    with pytest.raises(PlanningInputError):
        _drive(stage, _sample_event())


def test_missing_analysis_does_not_publish_partial_classification() -> None:
    state = _state_with(None, default_profile())
    stage = _bound_stage(state)
    with pytest.raises(PlanningInputError):
        _drive(stage, _sample_event())
    assert RunContext(state).classification() is None


def test_input_error_message_names_the_offending_slot() -> None:
    state = _state_with(None, default_profile())
    stage = _bound_stage(state)
    with pytest.raises(PlanningInputError) as excinfo:
        _drive(stage, _sample_event())
    msg = str(excinfo.value)
    assert "analysis" in msg.lower() or SLOT_CLASSIFICATION.rsplit(".", 1)[
        -1
    ] in msg or "repo_analysis" in msg


# --------------------------------------------------------------------------- #
# Driven outside a harness (no runtime/State bound): graceful pass-through     #
# --------------------------------------------------------------------------- #


def test_pass_through_when_no_runtime_bound() -> None:
    # The shared stage suite drives every stage's process() with NO runtime bound
    # and asserts a pure pass-through; the real Classify stage must keep that.
    stage = ClassifyStage()  # never _bind_runtime'd, no task_start
    event = _sample_event()

    async def _collect() -> list[Any]:
        return [out async for out in stage.process(event)]

    out = asyncio.run(_collect())
    assert len(out) == 1
    assert out[0] is event


# --------------------------------------------------------------------------- #
# Journal participation + bounded summary (Req 9.1, 9.3)                       #
# --------------------------------------------------------------------------- #


def test_emits_participation_trigger_with_bounded_summary() -> None:
    state = _state_with(_full_analysis(), default_profile())
    tracer = _CapturingTracer()
    _drive(_bound_stage(state, tracer=tracer), _sample_event())

    triggers = [e for e in tracer.events if isinstance(e, ProcessorTriggerEvent)]
    assert len(triggers) == 1
    trig = triggers[0]
    assert trig.processor == "ClassifyStage"
    assert trig.hook == PIPELINE_HOOK
    assert trig.action == STAGE_PARTICIPATION_ACTION
    detail = trig.detail
    assert detail["stage"] == "classify"
    # Bounded summary: subject counts per prefix + activated-cell count.
    classification = classify_repo(_full_analysis(), default_profile())
    assert detail["activated_cells"] == len(classification.cells)
    # The per-prefix subject counts sum to the total derived subjects.
    counts = detail["subjects_by_prefix"]
    assert isinstance(counts, dict)
    assert sum(counts.values()) == len(classification.subjects)


def test_summary_does_not_embed_full_classification() -> None:
    # The journal must stay bounded: no raw subject/cell objects in the detail.
    state = _state_with(_full_analysis(), default_profile())
    tracer = _CapturingTracer()
    _drive(_bound_stage(state, tracer=tracer), _sample_event())

    detail = [
        e for e in tracer.events if isinstance(e, ProcessorTriggerEvent)
    ][0].detail
    # Every detail value is a small scalar/dict of counts — not a Classification.
    for value in detail.values():
        assert isinstance(value, (str, int, bool, dict))
    # The dict-valued field (subjects_by_prefix) holds only int counts.
    for v in detail["subjects_by_prefix"].values():
        assert isinstance(v, int)


def test_works_without_a_bound_tracer() -> None:
    # When no tracer is reachable the stage still does its work and forwards the
    # event; it just records no trigger.
    state = _state_with(_full_analysis(), default_profile())
    stage = _bound_stage(state, tracer=None)
    out = _drive(stage, _sample_event())
    assert len(out) == 1
    assert isinstance(RunContext(state).classification(), Classification)
