"""Smoke test: pipeline composition + reference-repo-shaped planning (task 5.4).

This is the classification-coverage-planner's pipeline-integration *smoke* suite
(tasks.md 5.4; boundary: ClassifyStage, PlanStage, planning package). Where the
per-stage suites (``test_stage_classify``/``test_stage_plan``, tasks 4.2/4.3) drive a
single stage and the core suites (``test_planning_*``, task 5.1) exercise the pure
transforms, this suite proves the *whole seam* the two real stages form composes and
plans correctly:

* **Bundle composition is undisturbed (Req 1.4, 1.5).** ``make_docgen()`` still
  composes; the eight-stage ``STAGES`` ordering is intact (ingest → analyze →
  classify → plan → write → review → assemble → deploy); and the stages no spec yet
  owns (write/review/assemble/deploy) remain genuine pass-through no-ops. The
  classify/plan stages — made real by tasks 4.2/4.3 — drop into exactly the slots
  the stubs occupied with no edit to the registry or the bundle entry point.
* **A malware_hashes-shaped analysis plans the expected role × intent cells (Req 4.3,
  5.2).** Over a ``RepoAnalysis`` shaped like the reference Go CLI at
  ``/home/mc/Source/malware_hashes`` (``go.mod`` build file, GitHub Actions CI,
  ``*_test.go`` tests, a CLI entrypoint + subcommand, a README, an exported symbol,
  and a license/forensic-topic artifact), the classify→plan core activates the cells
  the design pins: install/use/troubleshoot for the technical *user* role, evaluate
  for *adopter*/*manager*, and assess-quality for *security/compliance* — driven
  through the real ``ClassifyStage`` and ``PlanStage`` over one shared harness
  ``State`` so the inter-stage handoff slot is the seam under test.
* **The plan is non-empty, ordered, vocabulary-consistent, and deterministic (Req
  5.2, 5.3).** The published ``CoveragePlan`` carries segments ordered by descending
  priority, every role/intent/subject is a member of the loaded vocabulary, and two
  runs over equal inputs yield equal plans.

The crafted-shape variant is repo-independent so it runs everywhere; a second,
``skipif``-guarded test drives the *real* Ingest → Analyze → Classify → Plan pipeline
over the actual reference repo (credential-free, ``FakeProvider``) to prove a real
``RepoAnalysis`` from ``/home/mc/Source/malware_hashes`` flows end-to-end to a
``CoveragePlan``.

These tests are credential-free and network-free: no model is consulted on the
deterministic path (the relevance gate is off by default), and the only provider ever
bound is the local :class:`tests._fakes.FakeProvider`. The stages are driven the way
``Harness.__init__`` + the run loop drive them — bind a runtime carrying the run
tracer via ``_bind_runtime``, hand the live ``State`` to each stage through a
``TaskStartEvent`` (``on_task_start``), then drive the content-free ``step_end`` hook
(``on_step_end``) directly so a fatal stage error propagates rather than being
swallowed by ``MultiHookProcessor.process``.

Requirements: 1.4, 1.5, 4.3, 5.2, 5.3.
"""

from __future__ import annotations

import asyncio
import importlib
import os
from dataclasses import replace
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
from docuharnessx.planning import CoveragePlan
from docuharnessx.stages.base import STAGE_PARTICIPATION_ACTION
from docuharnessx.stages.classify import ClassifyStage, make_classify_stage
from docuharnessx.stages.plan import PlanStage, make_plan_stage
from docuharnessx.types import STAGE_NAMES

from tests._fakes import FakeProvider

REFERENCE_REPO = "/home/mc/Source/malware_hashes"


# --------------------------------------------------------------------------- #
# Harness-faithful drivers + a recording run tracer                            #
# --------------------------------------------------------------------------- #


class _RecordingTracer:
    """A stand-in run tracer capturing every event a stage emits to ``on_event``."""

    def __init__(self) -> None:
        self.events: list[Any] = []

    async def on_event(self, event: Any) -> None:
        self.events.append(event)


class _Runtime:
    """Minimal ``_HarnessRuntime`` stand-in carrying just the run ``tracer``."""

    def __init__(self, tracer: Any | None) -> None:
        self.tracer = tracer


def _drive_hook(gen) -> list[Any]:
    """Run an async-generator hook to completion, propagating any raised error.

    Driven directly (not via ``MultiHookProcessor.process``) so a fatal
    :class:`PlanningInputError` raised inside the hook propagates; ``process`` would
    otherwise swallow non-control exceptions.
    """

    async def _collect() -> list[Any]:
        return [out async for out in gen]

    return asyncio.run(_collect())


def _step_end_event(run_id: str, step_id: int) -> StepEndEvent:
    return StepEndEvent(run_id=run_id, step_id=step_id)


def _bind_and_start(stage: Processor, state: State, tracer: Any | None) -> None:
    """Bind the run tracer and hand the live ``State`` to *stage* via task_start."""
    stage._bind_runtime(_Runtime(tracer))
    _drive_hook(
        stage.on_task_start(
            TaskStartEvent(run_id=state.run_id, step_id=0, state=state)
        )
    )


def _run_classify(
    state: State, tracer: Any | None = None, *, step_id: int = 3
) -> list[Any]:
    """Drive the real Classify stage's ``step_end`` over *state* (shared run)."""
    stage = make_classify_stage()
    _bind_and_start(stage, state, tracer)
    return _drive_hook(stage.on_step_end(_step_end_event(state.run_id, step_id)))


def _run_plan(
    state: State, tracer: Any | None = None, *, step_id: int = 4
) -> list[Any]:
    """Drive the real Plan stage's ``step_end`` over *state* (shared run)."""
    stage = make_plan_stage()
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
# A malware_hashes-shaped RepoAnalysis (Go CLI, repo-independent)              #
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


def _malware_hashes_shaped_analysis() -> RepoAnalysis:
    """A ``RepoAnalysis`` shaped like the reference Go CLI ``malware_hashes``.

    Carries the design-pinned reference-repo signals: a CLI entrypoint + subcommand
    (install/use/troubleshoot + evaluate), a ``go.mod`` build file + GitHub Actions CI
    (operate/configure/monitor), ``*_test.go`` tests (contribute), an exported symbol
    (extend + integrate), a README (understand), a forensic-hashing component/topic, and
    a license/compliance artifact (assess-quality).
    """
    return replace(
        _empty_analysis(),
        repo_path="/home/mc/Source/malware_hashes",
        languages=(
            LanguageStat(language="Go", files=14, loc=3800),
            LanguageStat(language="Markdown", files=9, loc=1500),
        ),
        primary_languages=("Go",),
        total_loc=5300,
        total_files=23,
        entrypoints=(
            Entrypoint(path="main.go", kind="main", name="mh"),
            Entrypoint(path="cmd/mh", kind="package_bin", name="mh"),
        ),
        build_files=(BuildFile(path="go.mod", kind="go_mod"),),
        ci_workflows=(
            CIWorkflow(
                path=".github/workflows/ci.yml", provider="github_actions"
            ),
        ),
        tests=_TestLayout(
            present=True, frameworks=("go_testing",), paths=("main_test.go",)
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
                name="hash",
                path="internal/hash",
                representative_files=("internal/hash/hash.go",),
            ),
        ),
        public_surface=(
            PublicSymbol(name="scan", kind="cli_subcommand", source="main.go"),
            PublicSymbol(
                name="Hash", kind="exported_symbol", source="internal/hash/hash.go"
            ),
        ),
        docs=DocPresence(
            has_readme=True, readme_paths=("README.md",), doc_dirs=(), other_docs=()
        ),
        artifacts=(Artifact(path="LICENSE", kind="license"),),
    )


def _state_with_analysis(
    analysis: RepoAnalysis, vocab: Vocabulary, *, run_id: str = "run-smoke"
) -> State:
    """A run State carrying the RepoAnalysis + Vocabulary the ClassifyStage reads."""
    state = State(run_id=run_id)
    rc = RunContext(state)
    rc.set_repo_analysis(analysis)
    rc.set_vocabulary(vocab)
    return state


# Convenience: a (roles, intent) cell tuple as the segments expose it.
def _cells_of(plan: CoveragePlan) -> set[tuple[tuple[str, ...], str]]:
    return {(seg.roles, seg.intent) for seg in plan.segments}


# --------------------------------------------------------------------------- #
# make_docgen still composes; canonical order intact; stub stages stay no-ops   #
# (Req 1.4, 1.5)                                                               #
# --------------------------------------------------------------------------- #


# The canonical stage class names in pipeline order. The real ClassifyStage and
# PlanStage occupy the same slots the no-op stubs did (tasks 4.2/4.3).
_CANONICAL_STAGE_CLASSES: tuple[str, ...] = (
    "IngestStage",
    "AnalyzeStage",
    "ClassifyStage",
    "PlanStage",
    "WriteStage",
    "ReviewStage",
    "AssembleStage",
    "DeployStage",
)

# The stages no spec yet owns must still be genuine no-op stubs. ingest/analyze were
# made real by repo-ingestion-analysis and classify/plan by this spec, so they are not
# in this set.
_NOOP_STAGE_NAMES: tuple[str, ...] = (
    "write",
    "review",
    "assemble",
    "deploy",
)


def _is_stage_target(target: str) -> bool:
    if not target.startswith("docuharnessx.stages."):
        return False
    module_path, _, class_name = target.rpartition(".")
    return module_path != "docuharnessx.stages.base" and class_name.endswith("Stage")


def test_make_docgen_still_composes_with_canonical_order_unchanged() -> None:
    # The real Classify/Plan stages drop in without disturbing composition: the bundle
    # still builds and the eight stages keep the canonical pipeline order
    # (single-stage replaceability; Req 1.4).
    from docuharnessx.bundle import make_docgen

    config = make_docgen(journal_dir="/tmp/dhx-planner-smoke-out")
    stage_classes = [
        p["_target_"].rsplit(".", 1)[1]
        for p in config.processors
        if isinstance(p, dict) and _is_stage_target(p.get("_target_", ""))
    ]
    assert stage_classes == list(_CANONICAL_STAGE_CLASSES)
    # STAGE_NAMES (the canonical-order source of truth) is unchanged by the append-only
    # seam extension this spec made (Req 1.4).
    assert STAGE_NAMES == (
        "ingest",
        "analyze",
        "classify",
        "plan",
        "write",
        "review",
        "assemble",
        "deploy",
    )


def test_classify_and_plan_are_in_the_registry_in_canonical_slots() -> None:
    # The STAGES registry references the real stage factories at the canonical
    # positions, so the spec swapped the bodies without touching the registry (Req 1.4).
    from docuharnessx.stages import STAGES

    names = [name for name, _ in STAGES]
    assert names == list(STAGE_NAMES)
    by_name = dict(STAGES)
    assert by_name["classify"] is make_classify_stage
    assert by_name["plan"] is make_plan_stage


def test_remaining_stub_stages_remain_pass_through_noops() -> None:
    # The stages no spec yet owns must still be genuine pass-throughs: driving each
    # yields the same content-free event unchanged (Req 1.5).
    event = _step_end_event("run-noop", 1)

    async def _collect(proc: Processor) -> list[Any]:
        return [out async for out in proc.process(event)]

    for stage_name in _NOOP_STAGE_NAMES:
        module = importlib.import_module(f"docuharnessx.stages.{stage_name}")
        factory = getattr(module, f"make_{stage_name}_stage")
        proc = factory()
        out = asyncio.run(_collect(proc))
        assert len(out) == 1, f"{stage_name} yielded {len(out)} events, expected 1"
        assert out[0] is event, f"{stage_name} mutated/replaced the lifecycle event"


def test_make_docgen_composes_with_a_cost_guard_too() -> None:
    # The bundle composes the same way with a control cost guard configured — the
    # planner stages never conflict with the baseline control capabilities (Req 1.5).
    from docuharnessx.bundle import make_docgen

    config = make_docgen(max_cost_usd=5.0, journal_dir="/tmp/dhx-planner-smoke-cost")
    stage_classes = [
        p["_target_"].rsplit(".", 1)[1]
        for p in config.processors
        if isinstance(p, dict) and _is_stage_target(p.get("_target_", ""))
    ]
    assert stage_classes == list(_CANONICAL_STAGE_CLASSES)


# --------------------------------------------------------------------------- #
# Reference-repo-shaped planning: Classify -> Plan over one shared State        #
# activates the design-pinned cells (Req 4.3, 5.2)                             #
# --------------------------------------------------------------------------- #


def test_reference_shaped_classify_then_plan_populates_both_slots() -> None:
    vocab = default_profile()
    state = _state_with_analysis(_malware_hashes_shaped_analysis(), vocab)
    rc = RunContext(state)

    # Before either stage runs, the internal handoff and the output slots are unset.
    assert rc.classification() is None
    assert rc.coverage_plan() is None

    # Classify writes the intermediate Classification to the handoff slot ...
    out_classify = _run_classify(state)
    assert len(out_classify) == 1  # content-free pass-through
    assert rc.classification() is not None
    # ... and Plan reads that same Classification and publishes the CoveragePlan.
    out_plan = _run_plan(state)
    assert len(out_plan) == 1
    plan = rc.coverage_plan()
    assert isinstance(plan, CoveragePlan)
    assert plan.schema_version == 1
    assert plan.repo_path == "/home/mc/Source/malware_hashes"


def test_reference_shaped_plan_is_nonempty_and_ordered() -> None:
    vocab = default_profile()
    state = _state_with_analysis(_malware_hashes_shaped_analysis(), vocab)
    _run_classify(state)
    _run_plan(state)
    plan = RunContext(state).coverage_plan()

    # Non-empty: a rich Go-CLI shape must yield real segments (not a generic dump).
    assert len(plan.segments) > 0
    # Ordered by descending priority (Req 5.2).
    priorities = [seg.priority for seg in plan.segments]
    assert priorities == sorted(priorities, reverse=True)
    # Every segment carries the writer-facing axis values + auditable evidence.
    for seg in plan.segments:
        assert seg.roles  # at least one role id
        assert seg.intent  # an intent id
        assert seg.segment_key
        assert seg.evidence  # auditable: why this segment is planned


def test_reference_shaped_plan_activates_design_pinned_cells() -> None:
    # The design pins the malware_hashes-shaped reference cells (design "Reference-Repo
    # -Shaped Tests", Req 4.3): install/use/troubleshoot for the user role, evaluate for
    # adopter/manager, and assess-quality for security/compliance.
    vocab = default_profile()
    state = _state_with_analysis(_malware_hashes_shaped_analysis(), vocab)
    _run_classify(state)
    _run_plan(state)
    cells = _cells_of(RunContext(state).coverage_plan())

    # install/use/troubleshoot for the technical user role.
    assert (("tech-savvy-user",), "install") in cells
    assert (("tech-savvy-user",), "use") in cells
    assert (("tech-savvy-user",), "troubleshoot") in cells
    # evaluate for adopter and manager.
    assert (("possible-adopter",), "evaluate") in cells
    assert (("manager",), "evaluate") in cells
    # assess-quality for security/compliance (the license artifact signal).
    assert (("security-compliance-officer",), "assess-quality") in cells


def test_reference_shaped_plan_is_vocabulary_consistent() -> None:
    # Every role/intent/subject in the published plan is a member of the loaded
    # vocabulary — the plan never invents an id outside the configured ontology.
    vocab = default_profile()
    allowed_prefixes = {p.rstrip(":") for p in vocab.subject_prefixes}
    state = _state_with_analysis(_malware_hashes_shaped_analysis(), vocab)
    _run_classify(state)
    _run_plan(state)
    plan = RunContext(state).coverage_plan()

    for seg in plan.segments:
        for role_id in seg.roles:
            assert vocab.has_role(role_id), role_id
        assert vocab.has_intent(seg.intent), seg.intent
        for subject in seg.subjects:
            assert subject.prefix in allowed_prefixes, subject.canonical()


def test_reference_shaped_plan_is_deterministic_across_two_runs() -> None:
    # The whole classify->plan stage seam is reproducible: two independent runs over an
    # equal RepoAnalysis publish equal CoveragePlans (Req 5.3).
    vocab = default_profile()

    def _publish() -> CoveragePlan:
        state = _state_with_analysis(
            _malware_hashes_shaped_analysis(), vocab, run_id="run-det"
        )
        _run_classify(state)
        _run_plan(state)
        return RunContext(state).coverage_plan()

    assert _publish() == _publish()


def test_both_stages_emit_participation_into_shared_journal() -> None:
    vocab = default_profile()
    state = _state_with_analysis(_malware_hashes_shaped_analysis(), vocab)
    tracer = _RecordingTracer()  # one tracer shared across the run

    _run_classify(state, tracer)
    _run_plan(state, tracer)

    triggers = _participation_triggers(tracer)
    processors = {t.processor for t in triggers}
    stages = {t.detail["stage"] for t in triggers}
    assert processors == {"ClassifyStage", "PlanStage"}
    assert stages == {"classify", "plan"}
    # The plan summary names a non-empty result with no empty_reason.
    plan_trig = next(t for t in triggers if t.processor == "PlanStage")
    assert plan_trig.detail["total_segments"] > 0
    assert plan_trig.detail["empty_reason"] == ""


def test_empty_shaped_analysis_yields_wellformed_empty_plan() -> None:
    # A repo with no actionable evidence flows through both real stages to a
    # well-formed, empty-but-valid plan (never raises, never fabricates; Req 5.5).
    vocab = default_profile()
    state = _state_with_analysis(_empty_analysis(), vocab)
    _run_classify(state)
    _run_plan(state)
    plan = RunContext(state).coverage_plan()
    assert isinstance(plan, CoveragePlan)
    assert plan.segments == ()


# --------------------------------------------------------------------------- #
# Real reference repo: Ingest -> Analyze -> Classify -> Plan end-to-end         #
# (credential-free; a real RepoAnalysis flows to a CoveragePlan)               #
# --------------------------------------------------------------------------- #


class _ModelConfig:
    """A tiny ``ModelConfig`` stand-in exposing only ``.main`` (the provider).

    The Analyze stage's enrichment hook reads its model from ``self._model_config.main``;
    binding a :class:`FakeProvider` here keeps the end-to-end run credential-free even if
    a later analyzer build were to consult a model (enrichment is off by default, so no
    network call happens regardless).
    """

    def __init__(self, provider: Any) -> None:
        self._provider = provider

    @property
    def main(self) -> Any:
        return self._provider


@pytest.mark.skipif(
    not os.path.isdir(REFERENCE_REPO),
    reason="reference repo not present in this environment",
)
def test_real_reference_repo_flows_end_to_end_to_a_coverage_plan() -> None:
    # Drive the full real pipeline over the actual reference Go CLI: Ingest scans it,
    # Analyze publishes the RepoAnalysis, Classify derives the Classification, and Plan
    # materializes the CoveragePlan — proving a real malware_hashes analysis flows
    # end-to-end to a non-empty, vocabulary-consistent plan. Credential-free: the only
    # provider ever bound is FakeProvider, and the deterministic path consults no model.
    from docuharnessx.stages.analyze import make_analyze_stage
    from docuharnessx.stages.ingest import make_ingest_stage

    vocab = default_profile()
    state = State(run_id="run-real-ref")
    rc = RunContext(state)
    rc.set_target_repo(REFERENCE_REPO)
    rc.set_vocabulary(vocab)

    # Ingest: scan the real repo into the file-inventory handoff slot.
    ingest = make_ingest_stage()
    _bind_and_start(ingest, state, None)
    _drive_hook(ingest.on_step_end(_step_end_event(state.run_id, 1)))
    assert rc.file_inventory() is not None

    # Analyze: publish the RepoAnalysis (enrichment off by default — no network even
    # with a provider bound).
    analyze_stage = make_analyze_stage()
    analyze_stage._model_config = _ModelConfig(FakeProvider("ignored summary"))
    _bind_and_start(analyze_stage, state, None)
    _drive_hook(analyze_stage.on_step_end(_step_end_event(state.run_id, 2)))
    analysis = rc.repo_analysis()
    assert analysis is not None

    # Classify -> Plan (the real stages this spec owns).
    _run_classify(state)
    _run_plan(state)

    plan = rc.coverage_plan()
    assert isinstance(plan, CoveragePlan)
    assert plan.repo_path == analysis.repo_path
    # The real Go CLI yields a non-empty, ordered, vocabulary-consistent plan.
    assert len(plan.segments) > 0
    priorities = [seg.priority for seg in plan.segments]
    assert priorities == sorted(priorities, reverse=True)
    cells = _cells_of(plan)
    # The reference repo is a Go CLI with a main.go entrypoint, so the user-role
    # install/use cells must be present.
    assert (("tech-savvy-user",), "install") in cells
    assert (("tech-savvy-user",), "use") in cells
    for seg in plan.segments:
        for role_id in seg.roles:
            assert vocab.has_role(role_id)
        assert vocab.has_intent(seg.intent)
