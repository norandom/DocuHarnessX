"""Integration tests for the Classify -> Plan stage pair (task 5.3).

Where the per-stage suites (``test_stage_classify.py`` / ``test_stage_plan.py``;
tasks 4.2 / 4.3) exercise each stage in isolation, this suite drives **both real
stages over one shared harness ``State``** so the inter-stage handoff is the real
seam under test (design "System Flows": Classify writes the ``Classification`` to
the internal handoff slot, Plan reads it and publishes the frozen
:class:`CoveragePlan`). It is the Classify->Plan analogue of the Ingest->Analyze
integration suite (``test_stage_integration.py``), and asserts exactly the
behavior task 5.3 pins:

* driving ``ClassifyStage`` then ``PlanStage`` over a single ``State`` populates the
  ``SLOT_CLASSIFICATION`` handoff slot and then the ``SLOT_COVERAGE_PLAN`` output
  slot (Req 2.3, 7.3), and the handed-off ``Classification`` is exactly the one the
  Plan stage consumes (the slot is the real seam, not a re-classification);
* the input-error paths each halt with :class:`PlanningInputError` and write **no**
  downstream slot — missing analysis (Req 2.4), missing vocabulary (Req 2.4),
  missing classification (Req 2.4), and an analysis declaring an unsupported
  ``schema_version`` (Req 2.5);
* an empty-evidence analysis flows end-to-end into a well-formed, empty-but-valid
  :class:`CoveragePlan` (no fabricated segments) with an explainable empty reason in
  the journal (Req 5.5, 9.4);
* the gated relevance hook is honored from the stage layer end-to-end: disabled (the
  default) publishes the bare deterministic plan even with a model reachable
  (Req 8.3, 8.5); a simulated relevance failure still publishes the deterministic
  plan unchanged (Req 8.4); an enabled, succeeding re-rank model reorders/annotates
  while preserving every segment's required writer fields and the set of segments
  (Req 8.2);
* both stages emit a ``stage_participated`` trigger into one shared run journal
  (Req 9.1, 9.2).

These tests are credential-free and network-free: the relevance hook is exercised
only with local, hand-built model stubs, never a real provider. The stages are
driven the way ``Harness.__init__`` + the run loop drive them — bind a runtime
carrying the run tracer via ``_bind_runtime``, hand the live ``State`` to each
stage through a ``TaskStartEvent`` (``on_task_start``), then drive the content-free
``step_end`` hook (``on_step_end``). The hooks are driven *directly* (not through
``MultiHookProcessor.process``) so a fatal :class:`PlanningInputError` propagates
rather than being swallowed by ``process``.
"""

from __future__ import annotations

import asyncio
import json
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
from docuharnessx.stages.base import STAGE_PARTICIPATION_ACTION
from docuharnessx.stages.classify import ClassifyStage, make_classify_stage
from docuharnessx.stages.plan import PlanStage, make_plan_stage
from docuharnessx.types import (
    SLOT_CLASSIFICATION,
    SLOT_COVERAGE_PLAN,
)


# --------------------------------------------------------------------------- #
# Harness-faithful drivers + a recording run tracer                            #
# --------------------------------------------------------------------------- #


class _RecordingTracer:
    """A stand-in run tracer capturing every event a stage emits to ``on_event``.

    The real run tracer is a HarnessJournal; the stages only ever call its
    ``on_event`` coroutine, so this records each stage's participation across a
    shared run without a live harness.
    """

    def __init__(self) -> None:
        self.events: list[Any] = []

    async def on_event(self, event: Any) -> None:
        self.events.append(event)


class _Runtime:
    """Minimal ``_HarnessRuntime`` stand-in carrying just the run ``tracer``."""

    def __init__(self, tracer: Any | None) -> None:
        self.tracer = tracer


class _ModelConfig:
    """A tiny ``ModelConfig`` stand-in exposing only ``.main`` (the provider).

    ``PlanStage._relevance_model`` reads the bound model from
    ``self._model_config.main``; this mirrors that one attribute so the relevance
    hook can be driven with credential-free local model stubs.
    """

    def __init__(self, provider: Any) -> None:
        self.main = provider


@dataclass
class _Resp:
    """A minimal ``ModelResponseEvent``-shaped object: only ``.content`` is read."""

    content: str


class _RerankProvider:
    """A model stub that re-ranks (reverses) the planned segment keys + annotates.

    Recovers the existing segment keys from the deterministic brief the relevance
    hook builds, returns them reversed (a clean permutation) plus a per-key note —
    so the hook re-orders and annotates without ever inventing/dropping a segment.
    """

    async def complete(
        self, messages: Any, tools: Any, stream_callback: object | None = None
    ) -> Any:
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
        return _Resp(json.dumps({"order": order, "notes": notes}))


class _FailingProvider:
    """A model stub whose ``complete`` always raises (simulated hook failure)."""

    async def complete(
        self, messages: Any, tools: Any, stream_callback: object | None = None
    ) -> Any:
        raise RuntimeError("simulated relevance failure")


def _drive_hook(gen) -> list[Any]:
    """Run an async-generator hook to completion, propagating any raised error.

    Driven directly (not via ``MultiHookProcessor.process``) so a fatal
    :class:`PlanningInputError` raised inside the hook propagates; ``process``
    would otherwise swallow non-control exceptions.
    """

    async def _collect() -> list[Any]:
        return [out async for out in gen]

    return asyncio.run(_collect())


def _step_end_event(run_id: str, step_id: int) -> StepEndEvent:
    return StepEndEvent(run_id=run_id, step_id=step_id)


def _bind_and_start(stage: Processor, state: State, tracer: Any | None) -> None:
    """Bind the run tracer and hand the live ``State`` to *stage* via task_start.

    Reproduces the run lifecycle: ``Harness.__init__`` binds the runtime onto each
    ``MultiHookProcessor`` (``_bind_runtime``), and the run loop drives a
    ``TaskStartEvent`` carrying ``event.state`` once per task (``on_task_start``),
    which is how the stage reaches the run ``State`` (``StepEndEvent`` is
    content-free).
    """
    stage._bind_runtime(_Runtime(tracer))
    _drive_hook(
        stage.on_task_start(
            TaskStartEvent(run_id=state.run_id, step_id=0, state=state)
        )
    )


def _run_classify(
    state: State, tracer: Any | None = None, *, step_id: int = 1
) -> list[Any]:
    """Drive the real Classify stage's ``step_end`` over *state* (shared run)."""
    stage = make_classify_stage()
    _bind_and_start(stage, state, tracer)
    return _drive_hook(stage.on_step_end(_step_end_event(state.run_id, step_id)))


def _run_plan(
    state: State,
    tracer: Any | None = None,
    *,
    relevance_enabled: bool = False,
    model: Any | None = None,
    step_id: int = 2,
) -> list[Any]:
    """Drive the real Plan stage's ``step_end`` over *state* (shared run)."""
    stage = make_plan_stage()
    if relevance_enabled:
        stage.relevance_enabled = True
    if model is not None:
        stage._bind_model_config(_ModelConfig(model))
    _bind_and_start(stage, state, tracer)
    return _drive_hook(stage.on_step_end(_step_end_event(state.run_id, step_id)))


def _participation_triggers(tracer: _RecordingTracer) -> list[ProcessorTriggerEvent]:
    return [
        e
        for e in tracer.events
        if isinstance(e, ProcessorTriggerEvent)
        and e.action == STAGE_PARTICIPATION_ACTION
    ]


# --------------------------------------------------------------------------- #
# Crafted analyses + a state seeded with the analysis + vocabulary slots        #
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


def _seed_state(
    analysis: RepoAnalysis | None,
    vocab: Vocabulary | None,
    *,
    run_id: str = "run-classify-plan",
) -> State:
    """Build a run State pre-loaded with the analysis + vocabulary slots.

    This is exactly the upstream seam the (already-tested) Ingest -> Analyze pair
    leaves behind: a ``RepoAnalysis`` in ``SLOT_REPO_ANALYSIS`` and a loaded
    ``Vocabulary`` in ``SLOT_VOCABULARY``. The Classify and Plan stages drive
    forward from here.
    """
    state = State(run_id=run_id)
    rc = RunContext(state)
    if analysis is not None:
        rc.set_repo_analysis(analysis)
    if vocab is not None:
        rc.set_vocabulary(vocab)
    return state


# --------------------------------------------------------------------------- #
# Happy path: Classify -> Plan over one shared State populates both slots       #
# (Req 2.3, 7.3)                                                               #
# --------------------------------------------------------------------------- #


def test_classify_then_plan_populates_both_slots() -> None:
    vocab = default_profile()
    state = _seed_state(_full_analysis(), vocab)
    rc = RunContext(state)

    # Before either stage runs, both handoff/output slots are explicitly unset.
    assert rc.classification() is None
    assert rc.coverage_plan() is None

    # Stage 1: Classify writes the Classification to the internal handoff slot.
    out_classify = _run_classify(state)
    assert len(out_classify) == 1  # content-free pass-through
    classification = rc.classification()
    assert isinstance(classification, Classification)

    # Stage 2: Plan reads that same Classification from the shared State and
    # publishes the CoveragePlan to its output slot.
    out_plan = _run_plan(state)
    assert len(out_plan) == 1
    published = rc.coverage_plan()
    assert isinstance(published, CoveragePlan)
    assert published.schema_version == 1
    assert published.relevance_applied is False


def test_handoff_classification_is_the_one_plan_consumes() -> None:
    # The Classification Classify publishes is exactly what Plan plans over —
    # proving the inter-stage handoff slot is the real seam (not a re-classify).
    # The published plan equals plan_coverage() over the handed-off classification.
    vocab = default_profile()
    state = _seed_state(_full_analysis(), vocab)
    rc = RunContext(state)

    _run_classify(state)
    handed_off = rc.classification()
    _run_plan(state)

    assert rc.coverage_plan() == plan_coverage(handed_off, vocab)


def test_published_plan_reflects_the_classified_analysis() -> None:
    vocab = default_profile()
    state = _seed_state(_full_analysis(), vocab)
    rc = RunContext(state)

    _run_classify(state)
    _run_plan(state)
    published = rc.coverage_plan()

    # The end-to-end plan equals the deterministic core over the same inputs and
    # carries the analysis provenance verbatim.
    assert published == plan_coverage(classify_repo(_full_analysis(), vocab), vocab)
    assert published.repo_path == "/repo/malware_hashes"
    # The Go CLI surfaces evidence, so the plan is non-empty and priority-ordered.
    assert len(published.segments) > 0
    priorities = [seg.priority for seg in published.segments]
    assert priorities == sorted(priorities, reverse=True)


def test_chain_is_deterministic_across_two_runs() -> None:
    vocab = default_profile()

    def _publish() -> CoveragePlan:
        state = _seed_state(_full_analysis(), vocab)
        _run_classify(state)
        _run_plan(state)
        return RunContext(state).coverage_plan()

    assert _publish() == _publish()


def test_both_stages_emit_participation_into_shared_journal() -> None:
    vocab = default_profile()
    state = _seed_state(_full_analysis(), vocab)
    tracer = _RecordingTracer()  # one tracer shared across the run

    _run_classify(state, tracer)
    _run_plan(state, tracer)

    triggers = _participation_triggers(tracer)
    processors = {t.processor for t in triggers}
    stages = {t.detail["stage"] for t in triggers}
    assert processors == {"ClassifyStage", "PlanStage"}
    assert stages == {"classify", "plan"}


def test_participation_summaries_are_bounded_scalars() -> None:
    # The journal must stay bounded for large repos: each stage's detail carries
    # only summary-level scalars/lists/count-dicts — never the full plan/classification.
    vocab = default_profile()
    state = _seed_state(_full_analysis(), vocab)
    tracer = _RecordingTracer()

    _run_classify(state, tracer)
    _run_plan(state, tracer)

    for trig in _participation_triggers(tracer):
        for value in trig.detail.values():
            assert isinstance(value, (str, int, bool, list, dict))
        # No CoveragePlan / Classification object leaks into the summary detail.
        assert not isinstance(trig.detail.get("plan"), CoveragePlan)
        assert not isinstance(
            trig.detail.get("classification"), Classification
        )


# --------------------------------------------------------------------------- #
# Fatal preconditions halt the run with PlanningInputError, no downstream slot  #
# (Req 2.4, 2.5)                                                               #
# --------------------------------------------------------------------------- #


def test_missing_analysis_halts_at_classify_no_classification() -> None:
    # Analysis slot unset (Analyze did not run): Classify halts before any
    # Classification is produced, so the downstream CoveragePlan is never written.
    state = _seed_state(None, default_profile())  # SLOT_REPO_ANALYSIS never set
    with pytest.raises(PlanningInputError):
        _run_classify(state)
    rc = RunContext(state)
    assert rc.classification() is None
    assert rc.coverage_plan() is None


def test_missing_vocabulary_halts_at_classify_no_classification() -> None:
    # No loaded vocabulary: Classify cannot classify against an ontology, so it
    # halts with PlanningInputError and writes no partial classification.
    state = _seed_state(_full_analysis(), None)  # SLOT_VOCABULARY never set
    with pytest.raises(PlanningInputError):
        _run_classify(state)
    rc = RunContext(state)
    assert rc.classification() is None
    assert rc.coverage_plan() is None


def test_unsupported_analysis_schema_version_halts_at_classify() -> None:
    # An analysis declaring a schema version this build does not understand is a
    # fatal input: Classify halts with an identifiable cause naming the version
    # (Req 2.5) and writes no classification.
    bad = replace(_full_analysis(), schema_version=999)
    state = _seed_state(bad, default_profile())
    with pytest.raises(PlanningInputError) as excinfo:
        _run_classify(state)
    assert "999" in str(excinfo.value)
    rc = RunContext(state)
    assert rc.classification() is None
    assert rc.coverage_plan() is None


def test_missing_classification_halts_at_plan_no_plan() -> None:
    # Classify skipped/failed: the handoff classification slot is unset, so Plan
    # halts with PlanningInputError naming the cause and writes no partial plan.
    state = _seed_state(_full_analysis(), default_profile())  # but Classify skipped
    with pytest.raises(PlanningInputError) as excinfo:
        _run_plan(state)
    assert "classification" in str(excinfo.value).lower()
    assert RunContext(state).coverage_plan() is None


def test_input_error_message_at_classify_names_the_cause() -> None:
    state = _seed_state(None, default_profile())
    with pytest.raises(PlanningInputError) as excinfo:
        _run_classify(state)
    msg = str(excinfo.value).lower()
    assert "analysis" in msg or "repo_analysis" in msg


# --------------------------------------------------------------------------- #
# Empty-evidence analysis flows end-to-end into a well-formed empty plan         #
# (Req 5.5, 9.4)                                                               #
# --------------------------------------------------------------------------- #


def test_empty_analysis_yields_wellformed_empty_plan_end_to_end() -> None:
    vocab = default_profile()
    state = _seed_state(_empty_analysis(), vocab)
    rc = RunContext(state)

    _run_classify(state)
    classification = rc.classification()
    assert isinstance(classification, Classification)
    assert classification.cells == ()  # no findings, no activated cells

    _run_plan(state)
    plan = rc.coverage_plan()
    assert isinstance(plan, CoveragePlan)
    # Well-formed but empty: no fabricated segments, never raised (Req 5.5).
    assert plan.segments == ()
    assert plan.relevance_applied is False


def test_empty_plan_records_explainable_reason_in_journal() -> None:
    vocab = default_profile()
    state = _seed_state(_empty_analysis(), vocab)
    tracer = _RecordingTracer()

    _run_classify(state, tracer)
    _run_plan(state, tracer)

    plan_trig = next(
        t for t in _participation_triggers(tracer) if t.processor == "PlanStage"
    )
    assert plan_trig.detail["total_segments"] == 0
    # An explainable, non-empty reason string for the empty result (Req 9.4).
    assert isinstance(plan_trig.detail["empty_reason"], str)
    assert plan_trig.detail["empty_reason"] != ""


# --------------------------------------------------------------------------- #
# The gated relevance hook end-to-end through the stage layer                   #
# (Req 8.2, 8.3, 8.4, 8.5)                                                     #
# --------------------------------------------------------------------------- #


def test_relevance_disabled_by_default_publishes_deterministic_plan() -> None:
    # Default gate (off) — even with a model reachable, the published plan is the
    # bare deterministic plan with relevance_applied=False (Req 8.3, 8.5).
    vocab = default_profile()
    state = _seed_state(_full_analysis(), vocab)

    _run_classify(state)
    _run_plan(state, model=_RerankProvider(), relevance_enabled=False)

    plan = RunContext(state).coverage_plan()
    assert plan.relevance_applied is False
    assert plan == plan_coverage(classify_repo(_full_analysis(), vocab), vocab)


def test_relevance_failure_falls_back_to_deterministic_plan() -> None:
    # Gate ON and a model bound, but the model raises: the hook absorbs the failure
    # and the deterministic plan is retained unchanged (relevance_applied=False;
    # Req 8.4). The run is NOT halted.
    vocab = default_profile()
    state = _seed_state(_full_analysis(), vocab)

    _run_classify(state)
    out = _run_plan(state, model=_FailingProvider(), relevance_enabled=True)

    assert len(out) == 1  # the run is not halted by a relevance failure
    plan = RunContext(state).coverage_plan()
    deterministic = plan_coverage(classify_repo(_full_analysis(), vocab), vocab)
    assert plan.relevance_applied is False
    assert plan.segments == deterministic.segments


def test_relevance_enabled_success_reorders_and_annotates_only() -> None:
    # Gate ON and a re-ranking model bound: the plan is reordered and annotated, but
    # every segment's required writer fields are preserved and the set of segments
    # is unchanged (Req 8.2).
    vocab = default_profile()
    deterministic = plan_coverage(classify_repo(_full_analysis(), vocab), vocab)
    if len(deterministic.segments) < 2:
        pytest.skip("needs >=2 segments to observe a re-rank")

    state = _seed_state(_full_analysis(), vocab)
    _run_classify(state)
    _run_plan(state, model=_RerankProvider(), relevance_enabled=True)
    plan = RunContext(state).coverage_plan()

    assert plan.relevance_applied is True
    # Same set of segment keys (no add/drop), reordered (reversed) here.
    assert {s.segment_key for s in plan.segments} == {
        s.segment_key for s in deterministic.segments
    }
    # Required writer fields preserved per key; only relevance_note may change.
    det_by_key = {s.segment_key: s for s in deterministic.segments}
    for seg in plan.segments:
        d = det_by_key[seg.segment_key]
        assert seg.roles == d.roles
        assert seg.intent == d.intent
        assert seg.subjects == d.subjects
        assert seg.priority == d.priority
        assert seg.evidence == d.evidence


def test_relevance_applied_flag_in_journal_on_success() -> None:
    vocab = default_profile()
    deterministic = plan_coverage(classify_repo(_full_analysis(), vocab), vocab)
    if len(deterministic.segments) < 2:
        pytest.skip("needs >=2 segments to observe a re-rank")

    state = _seed_state(_full_analysis(), vocab)
    tracer = _RecordingTracer()
    _run_classify(state, tracer)
    _run_plan(
        state, tracer, model=_RerankProvider(), relevance_enabled=True
    )

    plan_trig = next(
        t for t in _participation_triggers(tracer) if t.processor == "PlanStage"
    )
    assert plan_trig.detail["relevance_applied"] is True


def test_relevance_failure_journal_keeps_relevance_applied_false() -> None:
    vocab = default_profile()
    state = _seed_state(_full_analysis(), vocab)
    tracer = _RecordingTracer()

    _run_classify(state, tracer)
    _run_plan(state, tracer, model=_FailingProvider(), relevance_enabled=True)

    plan_trig = next(
        t for t in _participation_triggers(tracer) if t.processor == "PlanStage"
    )
    assert plan_trig.detail["relevance_applied"] is False


# --------------------------------------------------------------------------- #
# Defensive: the stages exposed by the factories are the real adapters          #
# --------------------------------------------------------------------------- #


def test_factories_return_the_real_stage_adapters() -> None:
    assert isinstance(make_classify_stage(), ClassifyStage)
    assert isinstance(make_plan_stage(), PlanStage)
    # The real adapters override on_step_end to do real slot I/O.
    assert "on_step_end" in vars(ClassifyStage)
    assert "on_step_end" in vars(PlanStage)
