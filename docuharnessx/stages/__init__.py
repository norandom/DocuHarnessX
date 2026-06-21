"""Pipeline stage sub-package and the stage-registration contract (task 3.1).

Owned by the harness-bundle-skeleton spec. Beyond the eight no-op stage modules
(ingest … deploy) and the stage base (task 2.5), this package root is the
**StageRegistry** boundary (Req 5.1, 5.2, 5.4, 5.5, 5.6):

* :data:`STAGES` — the ordered ``(StageName, factory)`` list giving the canonical
  pipeline order ingest → analyze → classify → plan → write → review → assemble →
  deploy (Req 5.2, 5.4). It is the single source of truth for stage order; each
  entry references the per-stage module's own factory so a Wave 1+ spec can swap
  exactly one factory without touching this list's ordering or ``make_docgen``
  (Req 5.6).
* :func:`register_stages` — appends every stage processor on
  :data:`docuharnessx.stages.base.PIPELINE_HOOK` using **append-don't-replace**
  semantics: processors already present on that hook are retained ahead of the
  stages (Req 5.1, 5.5).

Append-don't-replace via ``order``: HarnessX's :class:`~harnessx.core.builder.HarnessBuilder`
is immutable and materialises processors within a hook in ascending ``order``
(see :func:`harnessx.core.builder._topological_sort_entries`). Pre-existing
processors added by a baseline bundle carry the default ``order=0``; this registry
assigns each stage a strictly positive, monotonically increasing ``order`` (1, 2,
…, 8) so the eight stages always sort *after* any pre-existing hook processor and
*among themselves* in canonical order. Nothing is removed or replaced — each call
to ``builder.add(...)`` returns a new builder with one more entry — so the
contract is purely additive (Req 5.5).
"""

from __future__ import annotations

from typing import Callable

from harnessx.core.builder import HarnessBuilder
from harnessx.core.processor import Processor

from docuharnessx.stages.analyze import AnalyzeStage, make_analyze_stage
from docuharnessx.stages.assemble import AssembleStage, make_assemble_stage
from docuharnessx.stages.base import NoOpStage, PIPELINE_HOOK
from docuharnessx.stages.classify import ClassifyStage, make_classify_stage
from docuharnessx.stages.deploy import DeployStage, make_deploy_stage
from docuharnessx.stages.ingest import IngestStage, make_ingest_stage
from docuharnessx.stages.plan import PlanStage, make_plan_stage
from docuharnessx.stages.review import ReviewStage, make_review_stage
from docuharnessx.stages.write import WriteStage, make_write_stage
from docuharnessx.types import StageName

__all__ = [
    "STAGES",
    "register_stages",
    "stages_builder",
    "stage_class_for",
    "PIPELINE_HOOK",
]


#: Ordered ``(StageName, factory)`` pairs in canonical pipeline order (Req 5.2,
#: 5.4). Each factory is the per-stage module's own ``make_<stage>_stage`` so a
#: Wave 1+ spec swaps a single module's factory — and only that stage — without
#: editing this list's ordering or the bundle entry point (Req 5.6).
STAGES: list[tuple[StageName, Callable[[], Processor]]] = [
    ("ingest", make_ingest_stage),
    ("analyze", make_analyze_stage),
    ("classify", make_classify_stage),
    ("plan", make_plan_stage),
    ("write", make_write_stage),
    ("review", make_review_stage),
    ("assemble", make_assemble_stage),
    ("deploy", make_deploy_stage),
]


#: Canonical stage name → its real, module-level :class:`NoOpStage` subclass. Each
#: class lives at its own module path so it serializes to an importable ``_target_``
#: and is instantiated (and fired) at run time. Used by
#: :func:`docuharnessx.stages.base.make_noop_stage` to build a stage by name.
_STAGE_CLASSES: dict[str, type[NoOpStage]] = {
    "ingest": IngestStage,
    "analyze": AnalyzeStage,
    "classify": ClassifyStage,
    "plan": PlanStage,
    "write": WriteStage,
    "review": ReviewStage,
    "assemble": AssembleStage,
    "deploy": DeployStage,
}


def stage_class_for(name: str) -> type[NoOpStage]:
    """Return the real, module-level :class:`NoOpStage` subclass for *name*.

    Args:
        name: One of the eight canonical stage names.

    Returns:
        The per-stage class (e.g. ``"ingest"`` → :class:`IngestStage`).

    Raises:
        ValueError: If *name* is not a canonical stage name.
    """
    try:
        return _STAGE_CLASSES[name]
    except KeyError:
        raise ValueError(
            f"unknown stage name {name!r}; valid stages: {sorted(_STAGE_CLASSES)}"
        ) from None


def register_stages(builder: HarnessBuilder) -> HarnessBuilder:
    """Append the eight stage processors to *builder* on :data:`PIPELINE_HOOK`.

    Each stage from :data:`STAGES` is added in canonical order with a strictly
    positive, increasing ``order`` so the stages sort after any processor already
    present on the hook (append-don't-replace, Req 5.5) and among themselves in
    canonical pipeline order (Req 5.4).

    :class:`HarnessBuilder` is immutable: every ``.add(...)`` returns a new
    builder, so the input *builder* is left unmodified and the contract only ever
    adds processors — it never replaces existing ones (Req 5.1, 5.5).

    Args:
        builder: A valid :class:`HarnessBuilder`, possibly already carrying
            baseline-bundle processors on :data:`PIPELINE_HOOK`.

    Returns:
        A new builder with all eight stage processors appended in canonical order
        on :data:`PIPELINE_HOOK`, behind any pre-existing hook processors.
    """
    result = builder
    # order starts at 1 so default-order (0) pre-existing processors stay ahead.
    for index, (_name, factory) in enumerate(STAGES, start=1):
        result = result.add(factory(), hook=PIPELINE_HOOK, order=index)
    return result


def stages_builder() -> HarnessBuilder:
    """Return a fresh builder carrying ONLY the eight stages, for ``|`` composition.

    Equivalent to ``register_stages(HarnessBuilder())`` but expressed as a
    standalone stages-only builder so the bundle can compose it with the baseline
    control builder via the ``|`` operator (``control | stages_builder()``). Using
    ``|`` keeps HarnessX's singleton-conflict detection **in force** during
    composition (Req 2.1, 2.5): a stage whose processor declares a singleton group
    that conflicts with a control capability surfaces
    :class:`~harnessx.core.builder.HarnessConflictError` instead of being silently
    merged. The stages carry strictly positive ``order`` (1…8) so they sort after
    the default-order (0) control processors (append-don't-replace; Req 5.5).
    """
    return register_stages(HarnessBuilder())
