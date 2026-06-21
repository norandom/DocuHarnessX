"""No-op Ingest stage stub (task 2.5 boundary: Stage stubs).

The Ingest stage ingests the target repository's source material. In this skeleton
it ships as a no-op: a pass-through processor that participates in the run lifecycle
without modifying generated content (Req 5.2, 5.3) while recording its participation
in the run journal (Req 8.2). It lives in its own file so a Wave 1+ spec can replace
exactly this stub with real ingest behavior without editing the bundle entry point
or any sibling stage (Req 5.6).

:class:`IngestStage` is a **real module-level class** (subclassing the shared
:class:`docuharnessx.stages.base.NoOpStage`) so it serializes to the importable
``_target_`` ``docuharnessx.stages.ingest.IngestStage`` and is therefore actually
instantiated — and fired — at run time (see ``stages/base.py`` for why module-level
identity is required).
"""

from __future__ import annotations

from harnessx.core.processor import Processor

from docuharnessx.stages.base import NoOpStage, make_noop_stage

#: Canonical stage name, used as the stage-registry key and processor identity.
STAGE_NAME = "ingest"

__all__ = ["STAGE_NAME", "IngestStage", "make_ingest_stage", "make_noop_stage"]


class IngestStage(NoOpStage):
    """No-op Ingest stage: forwards the lifecycle event unchanged (Req 5.2, 5.3)."""

    stage_name = STAGE_NAME


def make_ingest_stage() -> Processor:
    """Return a fresh no-op processor for the ingest stage (Req 5.2, 5.3)."""
    return IngestStage()
