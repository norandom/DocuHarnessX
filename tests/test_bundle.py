"""Tests for ``make_docgen`` bundle composition (task 3.2 boundary: make_docgen).

These cover :mod:`docuharnessx.bundle` (Req 2.1–2.6, 8.1):

* ``make_docgen(...)`` composes a ``HarnessBuilder()`` with the baseline Control
  bundle (cost-guard + loop-detection tuned for 25–40k LOC repos) and the stage
  registry via the ``|`` operator, and returns a model-free ``HarnessConfig``.
* Observe is wired by setting the config tracer to a ``HarnessJournal`` rooted at
  the resolved output directory (``journal_dir``).
* HarnessX conflict detection surfaces ``HarnessConflictError`` when two
  conflicting singleton control capabilities are composed.

Composition facts the assertions rely on (verified against the installed
HarnessX):

* ``HarnessConfig`` carries **no** model field — the model is bound separately via
  ``ModelConfig.agentic(config)`` — so "no model binding" is asserted by the
  absence of any ``model``/``model_config`` attribute.
* The eight no-op stage processors serialize to ``_target_`` dicts in
  ``config.processors`` whose class names are ``IngestStage`` … ``DeployStage``
  (the per-stage class names set by the no-op factory), in canonical pipeline
  order. The stage hook is ``step_end`` (the natural hook), so the dicts carry no
  ``_hook_`` override.
* ``HarnessConfig.__post_init__`` converts a ``HarnessJournal`` instance into a
  ``TracerConfig`` carrying ``base_dir=journal_dir``, so a wired journal tracer is
  asserted via ``isinstance(config.tracer, TracerConfig)`` plus ``base_dir``.
"""

from __future__ import annotations

import pytest

from harnessx.core.builder import HarnessBuilder, HarnessConflictError
from harnessx.core.config_schema import TracerConfig
from harnessx.core.harness import HarnessConfig
from harnessx.processors.control.cost_guard import CostGuardProcessor
from harnessx.processors.control.loop_detection import LoopDetectionProcessor

from docuharnessx.bundle import make_docgen


# Canonical stage class names produced by the no-op stage factory, in pipeline
# order ingest → analyze → classify → plan → write → review → assemble → deploy.
CANONICAL_STAGE_CLASSES: tuple[str, ...] = (
    "IngestStage",
    "AnalyzeStage",
    "ClassifyStage",
    "PlanStage",
    "WriteStage",
    "ReviewStage",
    "AssembleStage",
    "DeployStage",
)


def _is_stage_target(target: str) -> bool:
    """True for a per-stage processor ``_target_`` (its own importable module path).

    Each stage is a real module-level class at ``docuharnessx.stages.<name>.<X>Stage``
    (NOT ``stages.base.*`` — that path was unimportable and silently dropped every
    stage at run time). A stage target therefore lives directly under
    ``docuharnessx.stages.`` (not the ``stages.base`` module) and its class name
    ends with ``Stage``.
    """
    if not target.startswith("docuharnessx.stages."):
        return False
    module_path, _, class_name = target.rpartition(".")
    return module_path != "docuharnessx.stages.base" and class_name.endswith("Stage")


def _stage_targets(config: HarnessConfig) -> list[str]:
    """Return the stage processor ``_target_`` class names in resolved order."""
    return [
        p["_target_"].rsplit(".", 1)[1]
        for p in config.processors
        if isinstance(p, dict) and _is_stage_target(p.get("_target_", ""))
    ]


def _control_targets(config: HarnessConfig) -> list[str]:
    """Return the control-bundle processor ``_target_`` strings."""
    return [
        p["_target_"]
        for p in config.processors
        if isinstance(p, dict)
        and p.get("_target_", "").startswith("harnessx.processors.control.")
    ]


# --------------------------------------------------------------------------- #
# Return type & no model binding (Req 2.1, 2.5)                                #
# --------------------------------------------------------------------------- #


def test_make_docgen_returns_harness_config() -> None:
    config = make_docgen(journal_dir="/tmp/dhx-test-out")
    assert isinstance(config, HarnessConfig)


def test_make_docgen_has_no_model_binding() -> None:
    config = make_docgen(journal_dir="/tmp/dhx-test-out")
    # HarnessConfig is the pure behaviour pipeline: it never carries model info.
    # The model is bound separately via ModelConfig.agentic(config).
    assert not hasattr(config, "model")
    assert not hasattr(config, "model_config")


# --------------------------------------------------------------------------- #
# Pipeline hook carries the 8 stages in canonical order (Req 2.4, 8.1)        #
# --------------------------------------------------------------------------- #


def test_make_docgen_exposes_eight_stages_in_canonical_order() -> None:
    config = make_docgen(journal_dir="/tmp/dhx-test-out")
    assert _stage_targets(config) == list(CANONICAL_STAGE_CLASSES)


def test_make_docgen_stages_are_appended_behind_control_processors() -> None:
    # Append-don't-replace: control processors (added first via `|`) precede the
    # eight stages in the resolved processor list (Req 2.4; StageRegistry 5.5).
    config = make_docgen(journal_dir="/tmp/dhx-test-out")
    targets = [p["_target_"] for p in config.processors if isinstance(p, dict)]
    first_stage_idx = next(i for i, t in enumerate(targets) if _is_stage_target(t))
    # Every control processor appears before the first stage.
    assert _control_targets(config)
    for i, t in enumerate(targets):
        if t.startswith("harnessx.processors.control."):
            assert i < first_stage_idx


# --------------------------------------------------------------------------- #
# Baseline control tuned for 25–40k LOC (Req 2.2, 2.3)                         #
# --------------------------------------------------------------------------- #


def test_make_docgen_includes_cost_guard_and_loop_detection() -> None:
    config = make_docgen(max_cost_usd=12.5, journal_dir="/tmp/dhx-test-out")
    controls = _control_targets(config)
    assert any(t.endswith("CostGuardProcessor") for t in controls), (
        "cost-guard control must be present when max_cost_usd is set"
    )
    assert any(t.endswith("LoopDetectionProcessor") for t in controls), (
        "loop-detection control must always be present"
    )


def test_make_docgen_loop_detection_present_without_cost_guard() -> None:
    # Loop-detection is part of the baseline reliability group regardless of the
    # cost budget; the cost guard is only added when max_cost_usd is provided.
    config = make_docgen(journal_dir="/tmp/dhx-test-out")
    controls = _control_targets(config)
    assert any(t.endswith("LoopDetectionProcessor") for t in controls)


# --------------------------------------------------------------------------- #
# Observe wiring: journal tracer rooted at the output dir (Req 2.6, 8.1)       #
# --------------------------------------------------------------------------- #


def test_make_docgen_wires_journal_tracer_at_output_dir(tmp_path) -> None:
    out = str(tmp_path / "out")
    config = make_docgen(journal_dir=out)
    # __post_init__ normalises a HarnessJournal into a TracerConfig (base_dir set).
    assert isinstance(config.tracer, TracerConfig)
    assert config.tracer.base_dir == out


def test_make_docgen_without_journal_dir_defers_tracer_to_run_time() -> None:
    # With no journal_dir HarnessX resolves the journal directory at run time
    # (Harness.__init__ derives it from the workspace/agent home), so the config
    # carries no explicit tracer slot. The CLI always passes the resolved output
    # dir, so the journal is rooted there in practice (design integration note).
    config = make_docgen()
    assert config.tracer is None


# --------------------------------------------------------------------------- #
# Conflict detection: conflicting singleton control capabilities (Req 2.5)    #
# --------------------------------------------------------------------------- #


def test_conflicting_cost_guards_raise_harness_conflict_error() -> None:
    # Two CostGuardProcessor entries share singleton_group 'cost_guard'; composing
    # them with `|` must surface a HarnessConflictError rather than silently
    # overwriting the capability (Req 2.5).
    left = HarnessBuilder().add(CostGuardProcessor(max_usd=5.0))
    right = HarnessBuilder().add(CostGuardProcessor(max_usd=9.0))
    with pytest.raises(HarnessConflictError):
        _ = left | right


def test_conflicting_loop_detectors_raise_harness_conflict_error() -> None:
    left = HarnessBuilder().add(LoopDetectionProcessor())
    right = HarnessBuilder().add(LoopDetectionProcessor())
    with pytest.raises(HarnessConflictError):
        _ = left | right


def test_harness_conflict_error_is_importable_from_bundle_module() -> None:
    # All HarnessX imports are centralised in the bundle module (drift mitigation);
    # HarnessConflictError is re-exported so callers reach it through one site.
    from docuharnessx import bundle

    assert bundle.HarnessConflictError is HarnessConflictError


def test_make_docgen_itself_surfaces_conflict_error(monkeypatch) -> None:
    """``make_docgen`` composes stages with ``|``, so a conflicting singleton stage
    surfaces ``HarnessConflictError`` through ``make_docgen`` itself (Req 2.1, 2.5).

    A genuine conflict is only caught by the ``|`` composition operator (not by
    ``.add``/``.build``). This proves ``make_docgen`` uses ``|`` composition by
    injecting a rogue stage whose processor declares the ``cost_guard`` singleton
    group that already exists on the baseline control capability: composing it must
    raise rather than silently merge two cost guards.
    """
    from docuharnessx import stages as stages_pkg

    original = list(stages_pkg.STAGES)
    # A rogue stage carrying a second CostGuardProcessor — conflicts with the
    # control cost guard added when max_cost_usd is set.
    rogue = ("rogue", lambda: CostGuardProcessor(max_usd=3.0))
    monkeypatch.setattr(stages_pkg, "STAGES", original + [rogue], raising=True)

    with pytest.raises(HarnessConflictError):
        make_docgen(max_cost_usd=10.0, journal_dir="/tmp/dhx-conflict-probe")
