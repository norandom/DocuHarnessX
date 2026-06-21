"""Tests for the no-op stage stubs and the stage base (task 2.5).

These cover the ``stages/base.py`` contract:

* :data:`docuharnessx.stages.base.PIPELINE_HOOK` — the single lifecycle hook the
  eight stages attach to (Req 5.1).
* :func:`docuharnessx.stages.base.make_noop_stage` — a shared factory that builds
  a genuine pass-through processor which yields the lifecycle event unchanged and
  modifies no generated content (Req 5.2, 5.3).

and the eight per-stage modules (ingest, analyze, classify, plan, write, review,
assemble, deploy), each of which exposes a stage factory built from the shared
factory in its own file so a later spec can replace exactly one stub (Req 5.2).

The stage processors are HarnessX ``Processor`` objects whose ``process(event)``
is an async generator. The suite has no pytest-asyncio, so the helper below
drives the generator synchronously via ``asyncio.run``.
"""

from __future__ import annotations

import asyncio
import importlib

import pytest

from harnessx.core.events import StepEndEvent
from harnessx.core.processor import Processor


# The eight canonical pipeline stages, in canonical order, paired with the
# factory callable name each per-stage module is expected to export.
STAGE_SPECS: list[tuple[str, str]] = [
    ("ingest", "make_ingest_stage"),
    ("analyze", "make_analyze_stage"),
    ("classify", "make_classify_stage"),
    ("plan", "make_plan_stage"),
    ("write", "make_write_stage"),
    ("review", "make_review_stage"),
    ("assemble", "make_assemble_stage"),
    ("deploy", "make_deploy_stage"),
]


def _drive(processor: Processor, event: object) -> list[object]:
    """Run a Processor's async ``process`` generator to completion synchronously."""

    async def _collect() -> list[object]:
        return [out async for out in processor.process(event)]

    return asyncio.run(_collect())


def _sample_event() -> StepEndEvent:
    """A representative lifecycle event carrying content the stage must not touch."""
    return StepEndEvent(
        run_id="run-test",
        step_id=3,
        step_summary="some prior summary",
        tool_call_summary="readFile(a)|writeFile(b)",
        cumulative_tokens=1234,
        cumulative_cost_usd=0.5,
    )


def test_pipeline_hook_constant_is_a_known_lifecycle_hook() -> None:
    from docuharnessx.stages.base import PIPELINE_HOOK

    # A non-empty hook string that HarnessX recognises as a lifecycle hook the
    # runloop drives. step_end is read-only (no messages field) so a no-op there
    # participates in the lifecycle without risking any hook-contract violation.
    assert isinstance(PIPELINE_HOOK, str)
    assert PIPELINE_HOOK in {
        "task_start",
        "step_start",
        "before_model",
        "after_model",
        "before_tool",
        "after_tool",
        "step_end",
        "task_end",
    }


def test_factory_returns_a_processor() -> None:
    from docuharnessx.stages.base import make_noop_stage

    proc = make_noop_stage("ingest")
    assert isinstance(proc, Processor)


def test_factory_processor_is_named_after_the_stage() -> None:
    from docuharnessx.stages.base import make_noop_stage

    # The journal records processor participation by class name; the no-op stage
    # must carry the stage name so per-stage participation is distinguishable.
    proc = make_noop_stage("classify")
    assert "classify" in type(proc).__name__.lower()


def test_noop_stage_is_pass_through() -> None:
    from docuharnessx.stages.base import make_noop_stage

    proc = make_noop_stage("ingest")
    event = _sample_event()
    out = _drive(proc, event)

    # Exactly one event out, identical (same object, unmodified) — a true no-op.
    assert len(out) == 1
    assert out[0] is event


def test_each_stage_module_exposes_its_factory_and_is_pass_through() -> None:
    for stage_name, factory_name in STAGE_SPECS:
        module = importlib.import_module(f"docuharnessx.stages.{stage_name}")
        factory = getattr(module, factory_name)
        proc = factory()
        assert isinstance(proc, Processor), f"{stage_name} factory did not return a Processor"
        assert stage_name in type(proc).__name__.lower()

        event = _sample_event()
        out = _drive(proc, event)
        assert len(out) == 1, f"{stage_name} stage yielded {len(out)} events, expected 1"
        assert out[0] is event, f"{stage_name} stage mutated/replaced the lifecycle event"


def test_each_stage_factory_returns_a_fresh_instance() -> None:
    # A later spec replaces exactly one stub; each factory call must build a new
    # processor so swapping one factory does not share state with the others.
    for stage_name, factory_name in STAGE_SPECS:
        module = importlib.import_module(f"docuharnessx.stages.{stage_name}")
        factory = getattr(module, factory_name)
        assert factory() is not factory()


def test_stage_modules_reuse_the_shared_base_factory() -> None:
    # All per-stage modules must build their processor via the shared factory in
    # stages/base.py so a single pattern governs every stub (Req 5.2).
    from docuharnessx.stages import base as base_module

    for stage_name, _ in STAGE_SPECS:
        module = importlib.import_module(f"docuharnessx.stages.{stage_name}")
        assert getattr(module, "make_noop_stage", None) is base_module.make_noop_stage, (
            f"{stage_name} should import the shared make_noop_stage factory"
        )
