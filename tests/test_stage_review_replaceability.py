"""Stable-replaceability + reproducibility tests for the Review stage (quality-review-gate task 5.2).

Task 5.2 pins the two halves of the Review stage's *stability* contract — the same real
:class:`~docuharnessx.stages.review.ReviewStage` task 4.1 wired, exercised here for the
properties a downstream consumer and a maintainer rely on (Req 1.1, 1.3, 8.3, 10.3, 6.6):

Stable replaceability (Req 1.1, 1.3)
------------------------------------
The real stage drops into the exact slot the no-op ``review`` stub occupied, so the stage
registry and ``make_docgen`` need **zero edits**:

* the public surface is unchanged — the ``STAGE_NAME`` constant (``"review"``), the
  :class:`ReviewStage` class name, the :func:`make_review_stage` factory name, and the
  ``docuharnessx/stages/review.py`` module path are all stable, and ``make_noop_stage`` is
  still re-exported (Req 1.1);
* the canonical eight-stage registry (:data:`docuharnessx.stages.STAGES`) and
  :func:`~docuharnessx.stages.register_stages` still bind ``review`` to
  :func:`make_review_stage` at its canonical position with **no edit to the list**, and
  ``make_docgen`` still composes the canonical pipeline order with ``ReviewStage`` in the
  review slot (Req 1.1);
* a Wave 1+ spec can swap a *single* stage factory in :data:`STAGES` — proven with the
  importable :class:`tests._fakes.ReplacementStage` — without disturbing the other seven
  entries, confirming the registry is a single-stage-replaceable list (Req 1.1, the
  single-stage replaceability contract the skeleton established);
* driven **outside a harness** (no run ``State`` bound — no ``task_start`` to capture one)
  an :meth:`ReviewStage.on_step_end` direct drive forwards the lifecycle event *unchanged*
  and produces **no report**, exactly like the no-op base it replaced (Req 1.3).

Reproducibility (Req 8.3, 10.3, 6.6)
------------------------------------
Two review runs over an **equal** written set with an **equal** judge source produce an
**equal** :class:`~docuharnessx.review.ReviewReport`. Because :class:`ReviewReport` and its
nested records are frozen dataclasses and ``Segment`` compares by value, the whole report
compares structurally — equal entries, per-criterion scores, verdicts, accepted set,
aggregate (counts + per-criterion tally), and order — across:

* the **default / fail-closed** judge source (no model bound -> every segment is the
  deterministic ``judge_source="unavailable"`` default-reject), proving a credential-free
  default-verdict run is fully reproducible (Req 10.3, 8.3); and
* a **recorded** judge source (a deterministic per-segment verdict replayed identically on
  both runs), proving a recorded-judge run is reproducible too (Req 10.3).

The written set's existing order is the determinism authority: the report entries and the
accepted set come out in written order on every run (Req 6.6).

These tests are credential-free and harness-free (except the bundle-composition assertions,
which only *compose* ``make_docgen`` — they never run it): ``on_step_end`` is driven directly
over a seeded run ``State`` with a duck-typed per-segment judge stub bound via
``_bind_runtime`` / ``_bind_model_config`` (mirroring ``tests/test_stage_review_gating.py``
and ``tests/test_stage_review_journal.py``). No network, no real model resolver.
"""

from __future__ import annotations

import asyncio
import importlib
import json
from dataclasses import dataclass
from typing import Any

from harnessx.core.events import StepEndEvent, TaskStartEvent
from harnessx.core.state import State

from docuharnessx.composition import segment_id
from docuharnessx.composition.model import WrittenSegments
from docuharnessx.context import RunContext
from docuharnessx.ontology import (
    InMemorySegmentStore,
    Segment,
    Subject,
    default_profile,
)
from docuharnessx.planning import COVERAGE_PLAN_SCHEMA_VERSION, CoveragePlan
from docuharnessx.planning.model import PlannedSegment
from docuharnessx.review import COBESY_CRITERIA
import docuharnessx.stages.review as review_module
from docuharnessx.stages.review import STAGE_NAME, ReviewStage, make_review_stage


# --------------------------------------------------------------------------- #
# Harness-free drivers + minimal runtime / model-config stubs                   #
# (mirrors tests/test_stage_review_gating.py + tests/test_stage_review_journal.py)
# --------------------------------------------------------------------------- #


class _RuntimeStub:
    def __init__(self, tracer: Any | None = None) -> None:
        self.tracer = tracer


class _ModelConfigStub:
    def __init__(self, main: Any) -> None:
        self.main = main


def _passing_verdict_json() -> str:
    """A clean, all-pass per-criterion JSON verdict the deterministic parser accepts."""
    return json.dumps(
        {
            "criteria": {
                name: {"score": 1.0, "passed": True, "reason": "ok"}
                for name in COBESY_CRITERIA
            },
            "passed": True,
            "reason": "all criteria met",
        }
    )


@dataclass
class _Resp:
    content: Any


class _RecordedJudge:
    """A duck-typed per-segment judge that replays a *recorded* verdict deterministically.

    Returns the same recorded verdict JSON as ``.content`` for every ``complete`` call, so two
    runs over an equal written set produce an identical (recorded) judge source — the recorded
    reproducibility case (Req 10.3). Mirrors the duck-typed provider stubs the gating/journal
    suites bind via ``_bind_model_config``.
    """

    def __init__(self, content: str) -> None:
        self._content = content

    async def complete(
        self, messages: Any, tools: Any, stream_callback: Any = None
    ) -> Any:
        return _Resp(content=self._content)

    def count_tokens(self, messages: Any) -> int:
        return 1


def _start_task(stage: ReviewStage, state: State) -> None:
    async def _collect() -> None:
        async for _ in stage.on_task_start(
            TaskStartEvent(run_id=state.run_id, step_id=0, state=state)
        ):
            pass

    asyncio.run(_collect())


def _bound_stage(
    state: State,
    *,
    model: Any | None = None,
) -> ReviewStage:
    stage = ReviewStage()
    stage._bind_runtime(_RuntimeStub())
    if model is not None:
        stage._bind_model_config(_ModelConfigStub(model))
    _start_task(stage, state)
    return stage


def _sample_event() -> StepEndEvent:
    return StepEndEvent(
        run_id="run-review-repro",
        step_id=11,
        step_summary="prior summary",
        tool_call_summary="readFile(a)",
        cumulative_tokens=10,
        cumulative_cost_usd=0.1,
    )


def _drive(stage: ReviewStage, event: StepEndEvent) -> list[Any]:
    async def _collect() -> list[Any]:
        return [out async for out in stage.on_step_end(event)]

    return asyncio.run(_collect())


# --------------------------------------------------------------------------- #
# Fixtures: wired written segments + matching plan + store                      #
# --------------------------------------------------------------------------- #


def _planned(
    *, key: str, roles: tuple[str, ...], intent: str, subject_local: str, priority: int
) -> PlannedSegment:
    return PlannedSegment(
        segment_key=key,
        roles=roles,
        intent=intent,
        subjects=(Subject(prefix="component", local=subject_local),),
        priority=priority,
        evidence=(),
    )


def _three_planned() -> tuple[PlannedSegment, ...]:
    """Three default-profile-consistent planned segments (priority-desc order)."""
    return (
        _planned(
            key="developer__extend__component-scanner",
            roles=("developer",),
            intent="extend",
            subject_local="scanner",
            priority=30,
        ),
        _planned(
            key="contributor__contribute__component-core",
            roles=("contributor",),
            intent="contribute",
            subject_local="core",
            priority=20,
        ),
        _planned(
            key="devops-admin__operate__component-runner",
            roles=("devops-admin",),
            intent="operate",
            subject_local="runner",
            priority=10,
        ),
    )


def _segment_for(planned: PlannedSegment) -> Segment:
    """A wired ontology Segment matching a planned segment (same id the writer derives)."""
    return Segment(
        id=segment_id(planned),
        title=f"{planned.intent} {planned.subjects[0].local}",
        roles=list(planned.roles),
        subjects=list(planned.subjects),
        intent=planned.intent,
        summary=f"Summary for {planned.subjects[0].local}.",
        related=[],
        body=f"# Body for {planned.subjects[0].local}\n\nDetailed prose grounding.",
    )


def _seed_state(
    planned: tuple[PlannedSegment, ...],
    *,
    run_id: str,
) -> tuple[State, InMemorySegmentStore]:
    """Seed a fresh run State with the written set + plan + vocab + store the stage reads.

    A *fresh* ``State`` / store / segment instances per call so two seeded runs are
    independent — the report equality across them is genuine reproducibility over equal
    *content*, not a shared mutable object.
    """
    vocab = default_profile()
    store = InMemorySegmentStore(vocab)
    segments = [_segment_for(p) for p in planned]
    for seg in segments:
        store.put(seg)

    state = State(run_id=run_id)
    rc = RunContext(state)
    rc.set_coverage_plan(
        CoveragePlan(
            schema_version=COVERAGE_PLAN_SCHEMA_VERSION,
            repo_path="/repo/x",
            vocabulary_fingerprint="fp",
            segments=planned,
        )
    )
    rc.set_vocabulary(vocab)
    rc.set_segment_store(store)
    rc.set_written_segments(
        WrittenSegments(
            segments=tuple(segments),
            flags=(),
            total_planned=len(planned),
        )
    )
    return state, store


def _run_review(
    planned: tuple[PlannedSegment, ...],
    *,
    run_id: str,
    model: Any | None = None,
):
    """Drive one full Review-stage ``on_step_end`` over a freshly seeded State; return report."""
    state, _store = _seed_state(planned, run_id=run_id)
    stage = _bound_stage(state, model=model)
    out = _drive(stage, _sample_event())
    assert len(out) == 1  # event forwarded unchanged
    report = RunContext(state).review_report()
    assert report is not None
    return report


# =========================================================================== #
# Stable replaceability: unchanged public surface (Req 1.1)                      #
# =========================================================================== #


def test_public_surface_names_are_stable() -> None:
    # The stage-name constant, the class name, the factory name, and the module path are all
    # unchanged from the no-op stub, so the registry/bundle bind it identically (Req 1.1).
    assert STAGE_NAME == "review"
    assert ReviewStage.__name__ == "ReviewStage"
    assert ReviewStage.stage_name == "review"
    assert make_review_stage.__name__ == "make_review_stage"
    assert review_module.__name__ == "docuharnessx.stages.review"
    # The factory returns a real ReviewStage instance (the slot the stub occupied).
    instance = make_review_stage()
    assert isinstance(instance, ReviewStage)
    assert type(instance).__name__ == "ReviewStage"


def test_module_re_exports_make_noop_stage() -> None:
    # The no-op re-export is retained in __all__ so the registry/bundle's import surface is
    # untouched (design "Modified Files": __all__ retains make_noop_stage) (Req 1.1).
    assert "make_noop_stage" in review_module.__all__
    assert hasattr(review_module, "make_noop_stage")
    # The canonical names are exported too.
    for name in ("STAGE_NAME", "ReviewStage", "make_review_stage"):
        assert name in review_module.__all__


def test_review_stage_subclasses_the_shared_noop_base() -> None:
    # Subclassing the shared no-op base is what lets the registry bind it identically to the
    # other stages (Req 1.2); confirmed here so the replaceability contract is structural.
    from docuharnessx.stages.base import NoOpStage

    assert issubclass(ReviewStage, NoOpStage)


# =========================================================================== #
# Stable replaceability: registry + bundle need no edits (Req 1.1)              #
# =========================================================================== #


def test_registry_binds_review_to_its_factory_at_canonical_position() -> None:
    # The canonical eight-stage STAGES list still binds "review" to make_review_stage at its
    # canonical (6th) position with no edit to the list (Req 1.1).
    from docuharnessx.stages import STAGES

    names = [name for name, _factory in STAGES]
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
    review_entry = dict(STAGES)["review"]
    assert review_entry is make_review_stage
    assert review_entry() .__class__ is ReviewStage


def test_stage_class_for_review_is_review_stage() -> None:
    # The registry's name->class map resolves "review" to the real ReviewStage (the module-
    # level class HarnessX serializes to an importable _target_) (Req 1.1).
    from docuharnessx.stages import stage_class_for

    assert stage_class_for("review") is ReviewStage


def test_make_docgen_composes_with_review_stage_in_canonical_order() -> None:
    # make_docgen still composes the canonical eight-stage pipeline with ReviewStage in the
    # review slot — no bundle edit needed for the real stage to drop in (Req 1.1).
    from docuharnessx.bundle import make_docgen

    config = make_docgen(journal_dir="/tmp/dhx-review-repro-out")

    def _is_stage_target(target: str) -> bool:
        if not target.startswith("docuharnessx.stages."):
            return False
        module_path, _, class_name = target.rpartition(".")
        return module_path != "docuharnessx.stages.base" and class_name.endswith(
            "Stage"
        )

    stage_classes = [
        p["_target_"].rsplit(".", 1)[1]
        for p in config.processors
        if isinstance(p, dict) and _is_stage_target(p.get("_target_", ""))
    ]
    assert stage_classes == [
        "IngestStage",
        "AnalyzeStage",
        "ClassifyStage",
        "PlanStage",
        "WriteStage",
        "ReviewStage",
        "AssembleStage",
        "DeployStage",
    ]
    # ReviewStage's _target_ resolves to this stable module path.
    review_targets = [
        p["_target_"]
        for p in config.processors
        if isinstance(p, dict) and p.get("_target_", "").endswith(".ReviewStage")
    ]
    assert review_targets == ["docuharnessx.stages.review.ReviewStage"]


def test_a_single_stage_factory_swap_flows_through_unchanged() -> None:
    # Single-stage replaceability: swapping ONE entry's factory in STAGES (here the review
    # slot, with the importable _fakes.ReplacementStage) leaves the other seven entries
    # untouched and the list a single-stage-replaceable surface (Req 1.1). We swap on a COPY
    # so the global registry is not mutated.
    from docuharnessx.stages import STAGES
    from tests._fakes import ReplacementStage, make_replacement_stage

    swapped = [
        (name, make_replacement_stage if name == "review" else factory)
        for name, factory in STAGES
    ]
    # Exactly one factory changed; the names/order are identical.
    assert [n for n, _ in swapped] == [n for n, _ in STAGES]
    assert dict(swapped)["review"] is make_replacement_stage
    assert isinstance(dict(swapped)["review"](), ReplacementStage)
    # Every other stage still resolves to its original factory (only review was swapped).
    for (name, orig), (sname, new) in zip(STAGES, swapped):
        assert name == sname
        if name != "review":
            assert orig is new
    # The real global registry was not mutated by the local swap.
    assert dict(STAGES)["review"] is make_review_stage


# =========================================================================== #
# Stable replaceability: out-of-harness pass-through (Req 1.3)                   #
# =========================================================================== #


def test_out_of_harness_drive_forwards_event_and_produces_nothing() -> None:
    # Driven outside a harness (no task_start -> no run State captured) the stage forwards the
    # lifecycle event UNCHANGED and writes no report, exactly like the no-op base (Req 1.3).
    stage = make_review_stage()  # never task_start'd, no runtime bound
    event = _sample_event()
    out = _drive(stage, event)
    assert len(out) == 1
    assert out[0] is event  # the same event object, unmodified


def test_out_of_harness_drive_does_not_raise_even_with_runtime_bound() -> None:
    # Even with a runtime bound (but still no task_start to capture a run State) the stage is a
    # graceful pass-through: it never raises a ReviewInputError off-harness (Req 1.3).
    stage = ReviewStage()
    stage._bind_runtime(_RuntimeStub())
    event = _sample_event()
    out = _drive(stage, event)
    assert len(out) == 1
    assert out[0] is event


def test_process_entrypoint_is_a_passthrough_off_harness() -> None:
    # The base `process` dispatcher (the way the run loop actually invokes the stage) is also a
    # pure pass-through off-harness — no report, same event (Req 1.3).
    stage = make_review_stage()
    event = _sample_event()

    async def _collect() -> list[Any]:
        return [out async for out in stage.process(event)]

    out = asyncio.run(_collect())
    assert len(out) == 1
    assert out[0] is event


# =========================================================================== #
# Reproducibility: equal inputs + equal judge source -> equal report (Req 8.3, 10.3, 6.6)
# =========================================================================== #


def test_default_verdict_run_is_reproducible() -> None:
    # No model bound -> every segment is the deterministic fail-closed default-reject
    # (judge_source="unavailable"). Two runs over an equal written set produce an EQUAL report
    # (frozen value object: equal entries, scores, verdicts, accepted, aggregate, order) — a
    # credential-free default-verdict run is fully reproducible (Req 10.3, 8.3).
    planned = _three_planned()
    r1 = _run_review(planned, run_id="run-default-a")
    r2 = _run_review(planned, run_id="run-default-b")

    assert r1 == r2  # whole frozen report compares structurally

    # Spell out the seam the assembler reads, so a future shape change is caught here too.
    assert r1.schema_version == r2.schema_version
    assert r1.entries == r2.entries
    assert r1.accepted == r2.accepted
    assert r1.aggregate == r2.aggregate
    # The default path: nothing accepted, all unavailable, in written order.
    assert r1.accepted == ()
    assert all(e.verdict == "fail" for e in r1.entries)
    assert all(e.judge_source == "unavailable" for e in r1.entries)
    assert [e.segment_id for e in r1.entries] == [segment_id(p) for p in planned]


def test_recorded_judge_run_is_reproducible() -> None:
    # A recorded judge source: the same recorded verdict JSON replayed on both runs. Two runs
    # over an equal written set produce an EQUAL report — a recorded-judge run is reproducible
    # (Req 10.3, 8.3). A fresh judge per run (with identical recorded content) proves the
    # equality is over content, not a shared stub.
    planned = _three_planned()
    recorded = _passing_verdict_json()
    r1 = _run_review(planned, run_id="run-rec-a", model=_RecordedJudge(recorded))
    r2 = _run_review(planned, run_id="run-rec-b", model=_RecordedJudge(recorded))

    assert r1 == r2

    # The recorded judge accepts every segment; the accepted set is equal and in written order.
    assert all(e.verdict == "pass" for e in r1.entries)
    assert all(e.judge_source == "model" for e in r1.entries)
    assert [s.id for s in r1.accepted] == [segment_id(p) for p in planned]
    assert r1.accepted == r2.accepted
    assert r1.aggregate == r2.aggregate
    assert r1.aggregate.accepted == len(planned)


def test_reproducible_report_preserves_written_order(tmp_path) -> None:
    # The written set's existing order is the determinism authority: report entries and the
    # accepted set come out in written order on both runs (Req 6.6). Asserted independently of
    # the whole-report equality so an order regression is pinpointed.
    planned = _three_planned()
    expected_order = [segment_id(p) for p in planned]
    recorded = _passing_verdict_json()

    r1 = _run_review(planned, run_id="run-order-a", model=_RecordedJudge(recorded))
    r2 = _run_review(planned, run_id="run-order-b", model=_RecordedJudge(recorded))

    assert [e.segment_id for e in r1.entries] == expected_order
    assert [e.segment_id for e in r2.entries] == expected_order
    assert [s.id for s in r1.accepted] == expected_order
    assert [s.id for s in r2.accepted] == expected_order


def test_aggregate_is_reproducible_including_criterion_tally() -> None:
    # The aggregate summary (counts + the per-criterion pass/fail tally) is equal on repeated
    # runs for an equal input + equal judge source (Req 8.3). Pins the tally explicitly so an
    # aggregation regression surfaces independently of the whole-report equality.
    planned = _three_planned()
    recorded = _passing_verdict_json()
    r1 = _run_review(planned, run_id="run-agg-a", model=_RecordedJudge(recorded))
    r2 = _run_review(planned, run_id="run-agg-b", model=_RecordedJudge(recorded))

    assert r1.aggregate == r2.aggregate
    # The per-criterion tally is itself an ordered, equal sequence of named tallies.
    assert r1.aggregate.criterion_tally == r2.aggregate.criterion_tally
    tally_names_1 = [t.name for t in r1.aggregate.criterion_tally]
    tally_names_2 = [t.name for t in r2.aggregate.criterion_tally]
    assert tally_names_1 == tally_names_2
    # Every COBESY criterion is represented in the tally (all passed under the recorded judge).
    assert set(tally_names_1) == set(COBESY_CRITERIA)
    for tally in r1.aggregate.criterion_tally:
        assert tally.passed == len(planned)
        assert tally.failed == 0


def test_distinct_runs_use_distinct_segment_identities_yet_report_is_equal() -> None:
    # Reproducibility is genuine: two independent runs build DISTINCT Segment object
    # identities (fresh State/store/segments each), yet the frozen ReviewReport compares EQUAL
    # because Segment compares by value — so the equality above is real reproducibility, not a
    # shared mutable object (Req 10.3).
    planned = _three_planned()
    recorded = _passing_verdict_json()
    r1 = _run_review(planned, run_id="run-id-a", model=_RecordedJudge(recorded))
    r2 = _run_review(planned, run_id="run-id-b", model=_RecordedJudge(recorded))

    # Distinct identities in the accepted tuples...
    for s1, s2 in zip(r1.accepted, r2.accepted):
        assert s1 is not s2
        assert s1 == s2  # ...but value-equal
    # ...and the whole report still compares equal.
    assert r1 == r2


def test_empty_written_set_is_reproducible() -> None:
    # An empty written set yields the well-formed empty report on every run, and two such runs
    # are equal (Req 6.5, 10.3) — the degenerate reproducibility case.
    r1 = _run_review((), run_id="run-empty-a")
    r2 = _run_review((), run_id="run-empty-b")

    assert r1 == r2
    assert r1.entries == ()
    assert r1.accepted == ()
    assert r1.aggregate.judged == 0


# --------------------------------------------------------------------------- #
# Cross-check: the importable replacement stage is a real, single-hook stub     #
# (the registry-swap test above relies on it being importable + pass-through)   #
# --------------------------------------------------------------------------- #


def test_replacement_stage_is_importable_and_pass_through() -> None:
    # The single-stage-swap test relies on _fakes.ReplacementStage being a real, importable,
    # module-level pass-through stage (so HarnessX can serialize it to a _target_). Confirm the
    # contract here so the swap test's premise is pinned.
    module = importlib.import_module("tests._fakes")
    assert hasattr(module, "ReplacementStage")
    assert hasattr(module, "make_replacement_stage")
    stage = module.make_replacement_stage()
    event = _sample_event()

    async def _collect() -> list[Any]:
        return [out async for out in stage.process(event)]

    out = asyncio.run(_collect())
    assert len(out) == 1
    assert out[0] is event
