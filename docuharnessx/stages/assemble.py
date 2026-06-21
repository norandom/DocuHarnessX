"""No-op Assemble stage stub (task 2.5 boundary: Stage stubs).

The Assemble stage assembles the reviewed drafts into the doc site. In this skeleton it ships as a no-op: a pass-through
processor that participates in the run lifecycle without modifying generated
content (Req 5.2, 5.3) while recording its participation in the run journal
(Req 8.2). It lives in its own file so a Wave 1+ spec can replace exactly this stub
with real assemble behavior without editing the bundle entry point or any sibling
stage (Req 5.6).

:class:`AssembleStage` is a **real module-level class** (subclassing the shared
:class:`docuharnessx.stages.base.NoOpStage`) so it serializes to the importable
``_target_`` ``docuharnessx.stages.assemble.AssembleStage`` and is therefore actually
instantiated — and fired — at run time (see ``stages/base.py`` for why module-level
identity is required).
"""

from __future__ import annotations

from harnessx.core.processor import Processor

from docuharnessx.stages.base import NoOpStage, make_noop_stage

#: Canonical stage name, used as the stage-registry key and processor identity.
STAGE_NAME = "assemble"

__all__ = ["STAGE_NAME", "AssembleStage", "make_assemble_stage", "make_noop_stage"]


class AssembleStage(NoOpStage):
    """No-op Assemble stage: forwards the lifecycle event unchanged (Req 5.2, 5.3)."""

    stage_name = STAGE_NAME


def make_assemble_stage() -> Processor:
    """Return a fresh no-op processor for the assemble stage (Req 5.2, 5.3)."""
    return AssembleStage()
