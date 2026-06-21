"""``make_docgen`` — the harness composition point (task 3.2 boundary: make_docgen).

This module is the skeleton's single composition seam: it assembles a HarnessX
:class:`~harnessx.core.harness.HarnessConfig` from three pieces and nothing more —

1. the **baseline Control** bundle (cost-guard + loop-detection, tuned for the
   25–40k LOC repos DocuHarnessX targets) via :func:`harnessx.bundles.control.make_control`;
2. the **eight pipeline stages** appended through
   :func:`docuharnessx.stages.register_stages` using the ``|`` composition operator
   (append-don't-replace: stages sort after the control processors);
3. **Observe** — a :class:`~harnessx.tracing.journal.HarnessJournal` tracer rooted
   at the resolved output directory so every run emits a JSONL trace recording run
   start/end and each stage's participation (Req 2.6, 8.1).

The returned ``HarnessConfig`` carries **no model binding** (Req 2.1, 2.5):
HarnessX keeps the model out of ``HarnessConfig`` entirely — the CLI binds it
later via ``ModelConfig(main=...).agentic(make_docgen(...))``. Conflicting
singleton control capabilities are never silently merged; HarnessX's own conflict
detection raises :class:`~harnessx.core.builder.HarnessConflictError` (Req 2.5),
which is re-exported here so callers reach it through this one site.

Drift mitigation — single HarnessX import site
----------------------------------------------
Per the design ("Risks: HarnessX API drift — centralize all HarnessX imports
here"), this module is the **only** place in the skeleton's bundle/stage path that
imports the HarnessX composition surface (``HarnessBuilder``, ``make_control``,
``HarnessConfig``, ``HarnessJournal``, ``HarnessConflictError``). If a HarnessX
composition, control, or journal API changes, the blast radius is this file.

Composition mechanics (verified against the installed HarnessX)
--------------------------------------------------------------
* ``make_control(max_cost_usd=...)`` returns a :class:`HarnessBuilder` carrying the
  reliability group (which includes :class:`LoopDetectionProcessor`) plus a
  :class:`CostGuardProcessor` when ``max_cost_usd`` is provided. Loop-detection
  thresholds are raised above the defaults so a long, legitimately repetitive
  documentation run over a 25–40k LOC repo is not mistaken for a stuck loop.
* ``builder | register_stages(...)`` is expressed by composing onto the builder
  with the ``|`` operator (here: ``register_stages`` appends onto the control
  builder), keeping conflict detection in force.
* ``.build(journal_dir=out)`` slots a ``TracerConfig(base_dir=out)`` as the tracer;
  when ``journal_dir`` is omitted the journal directory is resolved at run time by
  HarnessX. ``HarnessConfig.__post_init__`` normalises the journal into a
  ``TracerConfig`` so the wired tracer is always observable on ``config.tracer``.
"""

from __future__ import annotations

# --- The single HarnessX import site for the bundle/stage path (drift note) --- #
from harnessx.bundles.control import make_control
from harnessx.core.builder import HarnessBuilder, HarnessConflictError
from harnessx.core.harness import HarnessConfig

from docuharnessx.stages import stages_builder

__all__ = [
    "make_docgen",
    # Re-exported HarnessX symbols so callers reach them through this one site.
    "HarnessConfig",
    "HarnessConflictError",
    "HarnessBuilder",
]


# Loop-detection tuning for 25–40k LOC repositories. A documentation run over a
# large codebase legitimately revisits similar shapes (per-file ingest, repeated
# classify/write turns), so the halt/warn thresholds are set well above the
# HarnessX defaults (5 / 3) to avoid mis-flagging that volume as a stuck loop
# while still catching a genuinely degenerate cycle (Req 2.2, 2.3).
_LOOP_THRESHOLD: int = 12
_LOOP_WARN_THRESHOLD: int = 8


def make_docgen(
    max_cost_usd: float | None = None,
    max_steps: int | None = None,
    journal_dir: str | None = None,
) -> HarnessConfig:
    """Compose and return a model-free ``HarnessConfig`` for the doc pipeline.

    Builds a :class:`HarnessBuilder` from the baseline Control bundle (cost-guard +
    loop-detection tuned for 25–40k LOC repos), appends the eight pipeline stages
    via the ``|`` composition operator (:func:`register_stages`), and wires Observe
    by rooting a :class:`HarnessJournal` tracer at *journal_dir* (Req 2.1–2.6, 8.1).

    The returned ``HarnessConfig`` has **no model binding** — the CLI binds the
    model separately via ``ModelConfig(main=...).agentic(make_docgen(...))``. Step
    budgeting (*max_steps*) is enforced by the CLI at run invocation, not by a
    Control processor, so it is accepted here for the stable call contract but does
    not alter the composed config.

    Args:
        max_cost_usd: When set, add a cost-guard control capability halting the run
            once the cumulative spend reaches this many US dollars (Req 2.3). When
            ``None``, no cost guard is added (the loop-detection guard still is).
        max_steps: Accepted for the stable CLI call contract; the step budget is
            applied by the CLI at run time (see task 4.x), not composed here.
        journal_dir: Output directory the HarnessJournal trace is rooted at
            (Req 2.6, 8.1). When ``None``, the journal directory is resolved at run
            time by HarnessX.

    Returns:
        A model-free ``HarnessConfig`` carrying baseline Control, the eight ordered
        no-op stages on the pipeline hook, and a journal tracer.

    Raises:
        HarnessConflictError: If composition produces two conflicting singleton
            control capabilities (surfaced by HarnessX, never silently merged;
            Req 2.5). ``ValueError``: if *max_cost_usd*/*max_steps* is negative.
    """
    if max_cost_usd is not None and max_cost_usd < 0:
        raise ValueError(f"max_cost_usd must be non-negative, got {max_cost_usd!r}")
    if max_steps is not None and max_steps < 0:
        raise ValueError(f"max_steps must be non-negative, got {max_steps!r}")

    # 1. Baseline Control: reliability group (incl. loop-detection) tuned for large
    #    repos, plus a cost guard when a budget is configured (Req 2.2, 2.3).
    control: HarnessBuilder = make_control(
        max_cost_usd=max_cost_usd,
        loop_threshold=_LOOP_THRESHOLD,
        loop_warn_threshold=_LOOP_WARN_THRESHOLD,
    )

    # 2. Append the eight pipeline stages via the `|` composition operator (Req
    #    2.1). `stages_builder()` is a stages-only builder (single source of truth
    #    for stage ordering in the StageRegistry); composing it with `control | ...`
    #    keeps HarnessX's singleton-conflict detection IN FORCE, so a conflicting
    #    singleton capability surfaces HarnessConflictError rather than being
    #    silently merged (Req 2.5). Nothing pre-existing on the hook is replaced —
    #    the stages carry order 1…8 so they sort behind the control processors
    #    (append-don't-replace, Req 2.4).
    builder: HarnessBuilder = control | stages_builder()

    # 3. Wire Observe: root the HarnessJournal tracer at the resolved output dir.
    #    `.build(journal_dir=...)` slots a TracerConfig(base_dir=...) taking
    #    precedence over any pre-existing tracer (Req 2.6, 8.1). With None, HarnessX
    #    resolves the journal directory at run time.
    config: HarnessConfig = builder.build(journal_dir=journal_dir)

    # No model binding: HarnessConfig never carries model info (Req 2.1, 2.5).
    return config
