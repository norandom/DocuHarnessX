"""Shared types and slot-key constants for the DocuHarnessX skeleton.

This module holds the two pieces of vocabulary the rest of the skeleton agrees
on (task 1.2 boundary: types, errors):

* :data:`StageName` — a ``Literal`` constraining stage identifiers to the eight
  canonical pipeline stages, plus :data:`STAGE_NAMES`, the same names as an
  ordered tuple for the stage registry to iterate (Req 5.4: canonical order
  ingest → analyze → classify → plan → write → review → assemble → deploy).
* The harness state/slot keys used to pass run data between stages:
  :data:`SLOT_TARGET_REPO`, :data:`SLOT_OUTPUT_DIR`, :data:`SLOT_SEGMENT_STORE`,
  and :data:`SLOT_VOCABULARY` (Req 6.2, 10.2; design "RunContext"/state model).

Deliberately absent: there is **no** ``RoleId`` alias and **no** fixed role
list. Roles, intents, and subjects come from the loaded ``Vocabulary`` owned by
``ontology-engine`` (Req 6.2; design "NO RoleId alias — roles come from the
loaded Vocabulary"). Keeping roles out of this module is what lets the
``make_docgen`` harness stay reusable across projects.
"""

from __future__ import annotations

from typing import Literal

__all__ = [
    "StageName",
    "STAGE_NAMES",
    "SLOT_TARGET_REPO",
    "SLOT_OUTPUT_DIR",
    "SLOT_SEGMENT_STORE",
    "SLOT_VOCABULARY",
]

# The eight canonical pipeline stages, constrained at the type level. The order
# of the Literal arguments mirrors the canonical pipeline order (Req 5.4); the
# stage registry (task 3.1) derives execution order from STAGE_NAMES below.
StageName = Literal[
    "ingest",
    "analyze",
    "classify",
    "plan",
    "write",
    "review",
    "assemble",
    "deploy",
]

#: The canonical stage names as an ordered tuple — the single source of truth for
#: pipeline ordering that the stage registry and tests iterate (Req 5.4).
STAGE_NAMES: tuple[StageName, ...] = (
    "ingest",
    "analyze",
    "classify",
    "plan",
    "write",
    "review",
    "assemble",
    "deploy",
)

# --- Harness state/slot keys -------------------------------------------------- #
# Stages exchange run data exclusively through harness state/slots keyed by these
# constants (Req 6.1). The CLI populates the target-repo, output-dir, and
# vocabulary slots before the run (Req 6.2, 10.2); the segment-store handle slot
# carries the ontology-engine SegmentStore for stages to read (Req 6.4).
# Namespaced to avoid collision with any processor-internal slot keys.

#: Slot key for the validated target-repository path (Req 4.2, 6.2).
SLOT_TARGET_REPO: str = "docuharnessx.target_repo"

#: Slot key for the resolved output directory (Req 6.2).
SLOT_OUTPUT_DIR: str = "docuharnessx.output_dir"

#: Slot key for the segment-store handle conforming to the ontology-engine
#: ``SegmentStore`` interface (Req 6.4).
SLOT_SEGMENT_STORE: str = "docuharnessx.segment_store"

#: Slot key for the loaded ``Vocabulary`` placed into the run context at run
#: start so stages can read the active roles/intents/subjects (Req 10.2).
SLOT_VOCABULARY: str = "docuharnessx.vocabulary"
