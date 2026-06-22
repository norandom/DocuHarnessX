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
    "SLOT_FILE_INVENTORY",
    "SLOT_REPO_ANALYSIS",
    "SLOT_CLASSIFICATION",
    "SLOT_COVERAGE_PLAN",
    "SLOT_WRITTEN_SEGMENTS",
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

# --- repo-ingestion-analysis seam extension (task 1.3, append-only) ----------- #
# Added by the ``repo-ingestion-analysis`` spec as an append-only extension of this
# ``harness-bundle-skeleton``-owned module (Req 7.1). No existing slot key,
# ``StageName``, or ``STAGE_NAMES`` entry is modified.

#: Slot key for the inter-stage file inventory handoff (Ingest -> Analyze). The
#: Ingest stage writes the classified ``FileInventory`` here; the Analyze stage
#: reads it instead of re-walking the filesystem (Req 1.7).
SLOT_FILE_INVENTORY: str = "docuharnessx.file_inventory"

#: Slot key for the frozen ``RepoAnalysis`` produced by the Analyze stage — the
#: output seam the downstream ``classification-coverage-planner`` consumes
#: (Req 7.1, 7.2).
SLOT_REPO_ANALYSIS: str = "docuharnessx.repo_analysis"

# --- classification-coverage-planner seam extension (task 4.1, append-only) --- #
# Added by the ``classification-coverage-planner`` spec as an append-only extension
# of this ``harness-bundle-skeleton``-owned module (Req 7.1, 7.5). No existing slot
# key, ``StageName``, or ``STAGE_NAMES`` entry is modified.

#: Slot key for the internal Classify -> Plan handoff (the ``Classification`` value
#: object). The Classify stage writes it; the Plan stage reads it to materialize the
#: ``CoveragePlan`` (design "types.py additions"; Req 7.1).
SLOT_CLASSIFICATION: str = "docuharnessx.classification"

#: Slot key for the frozen ``CoveragePlan`` the Plan stage produces — the output seam
#: the downstream Wave 2 ``cobesy-writer`` consumes verbatim (Req 7.1, 7.2, 7.3).
SLOT_COVERAGE_PLAN: str = "docuharnessx.coverage_plan"

# --- cobesy-writer seam extension (task 1.2, append-only) --------------------- #
# Added by the Wave 2 ``cobesy-writer`` spec as an append-only extension of this
# ``harness-bundle-skeleton``-owned module (cobesy-writer Req 7.2). No existing slot
# key, ``StageName``, or ``STAGE_NAMES`` entry is modified.

#: Slot key for the frozen ``WrittenSegments`` the Write stage publishes — the output
#: seam the downstream Wave 2 ``quality-review-gate`` consumes verbatim so it judges
#: exactly the segments the writer produced (cobesy-writer Req 7.1, 7.4, 7.5).
SLOT_WRITTEN_SEGMENTS: str = "docuharnessx.written_segments"
