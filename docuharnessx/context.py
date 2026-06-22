"""The :class:`RunContext` data-passing seam (task 2.3 boundary: RunContext).

``RunContext`` is the skeleton's single, auditable data seam between the CLI and
the pipeline stages. Stages exchange run data *exclusively* through harness
``State`` slots and the segment-store handle — never globals (Req 6.1) — and this
module is the one typed surface over those slots.

What it provides
----------------
* Typed setters/getters for the **target-repository path** and the **output
  directory**, keyed by the slot constants in :mod:`docuharnessx.types`
  (``SLOT_TARGET_REPO`` / ``SLOT_OUTPUT_DIR``; Req 6.2). The CLI populates these
  before ``harness.run(...)`` so registered stages can read them.
* :meth:`RunContext.segment_store` — returns the handle conforming to the
  ``ontology-engine`` :class:`SegmentStore` port (``put`` / ``query`` /
  ``list_segments`` / ``resolve_cross_links``), stored at ``SLOT_SEGMENT_STORE``
  (Req 6.3, 6.4). The skeleton consumes this port at the contract level only and
  never owns a storage implementation.
* :meth:`RunContext.vocabulary` — returns the loaded :class:`Vocabulary` placed
  at ``SLOT_VOCABULARY`` at run start, from which stages read the project's valid
  roles/intents/subjects (Req 10.2).

Absent slots return an explicit ``None`` rather than an undefined value (Req
6.5), so a stage can branch on "not set yet" without catching exceptions.

The two ontology types (:class:`SegmentStore`, :class:`Vocabulary`) are imported
from the skeleton's single ontology re-export site (:mod:`docuharnessx._ontology`),
keeping the downstream blast radius of any ``ontology-engine`` contract drift to
one module (design "ontology re-export"; revalidation trigger recorded there).

State-slot mechanics
--------------------
HarnessX :class:`~harnessx.core.state.State` stores each slot as a
:class:`~harnessx.core.state.StateSlot` value object holding ``slot_type`` +
``content``. The setters call ``state.set_slot(key, slot_type, content)`` and the
getters read ``state.get_slot(key)`` and return its ``.content`` (or ``None`` when
the slot is absent). ``slot_type`` is a short tag used by the journal/snapshot
machinery; it does not affect retrieval here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from harnessx.core.state import State

from docuharnessx.types import (
    SLOT_FILE_INVENTORY,
    SLOT_OUTPUT_DIR,
    SLOT_REPO_ANALYSIS,
    SLOT_SEGMENT_STORE,
    SLOT_TARGET_REPO,
    SLOT_VOCABULARY,
)

if TYPE_CHECKING:  # contract-level types — single re-export site (Req 6.3, 10.5)
    from docuharnessx._ontology import SegmentStore, Vocabulary
    # The frozen output seam consumed by the downstream planner (Req 7.2, 7.3).
    from docuharnessx.analysis.model import RepoAnalysis

__all__ = ["RunContext"]

# Slot-type tags recorded on each StateSlot for journal/snapshot readability.
# These are descriptive labels only; retrieval is purely by slot key.
_SLOT_TYPE_PATH = "path"
_SLOT_TYPE_SEGMENT_STORE = "segment_store"
_SLOT_TYPE_VOCABULARY = "vocabulary"
# repo-ingestion-analysis seam extension (task 1.4, append-only).
_SLOT_TYPE_FILE_INVENTORY = "file_inventory"
_SLOT_TYPE_REPO_ANALYSIS = "repo_analysis"


class RunContext:
    """Typed accessors over a harness :class:`State`'s run-data slots.

    A thin, single-run wrapper: it owns no data itself, only the typed read/write
    surface over the wrapped ``State``'s slots. Construct it around the run's
    ``State`` (the CLI does this before the run; stages receive it to read).
    """

    def __init__(self, state: State) -> None:
        self._state = state

    @property
    def state(self) -> State:
        """The wrapped harness :class:`State` (the slot backing store)."""
        return self._state

    # ----------------------------------------------------------------- #
    # Internal slot helper                                              #
    # ----------------------------------------------------------------- #

    def _get_content(self, key: str):
        """Return a slot's ``content``, or ``None`` when the slot is absent.

        Never raises for a missing slot — an unset slot is an explicit ``None``
        (Req 6.5), distinct from a slot that was set to ``None``.
        """
        slot = self._state.get_slot(key)
        return slot.content if slot is not None else None

    # ----------------------------------------------------------------- #
    # Target-repository path (Req 6.2)                                  #
    # ----------------------------------------------------------------- #

    def set_target_repo(self, path: str) -> None:
        """Record the validated target-repository path for stages to read."""
        self._state.set_slot(SLOT_TARGET_REPO, _SLOT_TYPE_PATH, path)

    def target_repo(self) -> str | None:
        """The target-repository path, or ``None`` when the slot is unset."""
        return self._get_content(SLOT_TARGET_REPO)

    # ----------------------------------------------------------------- #
    # Output directory (Req 6.2)                                        #
    # ----------------------------------------------------------------- #

    def set_output_dir(self, path: str) -> None:
        """Record the resolved output directory for stages to read."""
        self._state.set_slot(SLOT_OUTPUT_DIR, _SLOT_TYPE_PATH, path)

    def output_dir(self) -> str | None:
        """The resolved output directory, or ``None`` when the slot is unset."""
        return self._get_content(SLOT_OUTPUT_DIR)

    # ----------------------------------------------------------------- #
    # Segment-store handle (Req 6.3, 6.4)                               #
    # ----------------------------------------------------------------- #

    def set_segment_store(self, store: "SegmentStore") -> None:
        """Record the segment-store handle (the ``ontology-engine`` port)."""
        self._state.set_slot(SLOT_SEGMENT_STORE, _SLOT_TYPE_SEGMENT_STORE, store)

    def segment_store(self) -> "SegmentStore | None":
        """The segment-store handle typed by the consumed ``SegmentStore`` port.

        Returns the handle conforming to the pinned ``put`` / ``query`` /
        ``list_segments`` / ``resolve_cross_links`` signatures, or ``None`` when
        no handle has been placed in the run context (Req 6.4, 6.5).
        """
        return self._get_content(SLOT_SEGMENT_STORE)

    # ----------------------------------------------------------------- #
    # Loaded vocabulary (Req 10.2)                                      #
    # ----------------------------------------------------------------- #

    def set_vocabulary(self, vocabulary: "Vocabulary") -> None:
        """Record the loaded project ``Vocabulary`` at ``SLOT_VOCABULARY``."""
        self._state.set_slot(SLOT_VOCABULARY, _SLOT_TYPE_VOCABULARY, vocabulary)

    def vocabulary(self) -> "Vocabulary | None":
        """The loaded :class:`Vocabulary`, or ``None`` when the slot is unset.

        Stages read the project's valid roles/intents/subjects from this
        ``Vocabulary`` (Req 10.2); it is placed into the run context at run start
        by the CLI's ontology-loading step.
        """
        return self._get_content(SLOT_VOCABULARY)

    # ----------------------------------------------------------------- #
    # File-inventory handoff: Ingest -> Analyze (Req 1.7, 7.3)          #
    # ----------------------------------------------------------------- #
    # repo-ingestion-analysis seam extension (task 1.4, append-only). Carries the
    # classified file inventory the Ingest stage publishes for the Analyze stage
    # to read instead of re-walking the filesystem (design "context.py
    # additions"). The slot content is treated opaquely here — the inventory is an
    # internal analysis type, so this accessor pair stays loosely typed.

    def set_file_inventory(self, inventory: object) -> None:
        """Record the classified file inventory for the Analyze stage to read."""
        self._state.set_slot(
            SLOT_FILE_INVENTORY, _SLOT_TYPE_FILE_INVENTORY, inventory
        )

    def file_inventory(self) -> object | None:
        """The file inventory handoff, or ``None`` when the slot is unset.

        Returns an explicit ``None`` before the Ingest stage has published an
        inventory (Req 6.5 absent-slot semantics), so the Analyze stage can branch
        on "not set yet" without catching exceptions.
        """
        return self._get_content(SLOT_FILE_INVENTORY)

    # ----------------------------------------------------------------- #
    # RepoAnalysis output seam (Req 7.2, 7.3, 7.4, 7.5)                 #
    # ----------------------------------------------------------------- #
    # repo-ingestion-analysis seam extension (task 1.4, append-only). The frozen
    # RepoAnalysis the Analyze stage writes is the output seam the downstream
    # classification-coverage-planner consumes verbatim (design "context.py
    # additions"). Typed by the model under TYPE_CHECKING only, keeping the
    # runtime import surface unchanged.

    def set_repo_analysis(self, analysis: "RepoAnalysis") -> None:
        """Record the produced :class:`RepoAnalysis` at ``SLOT_REPO_ANALYSIS``."""
        self._state.set_slot(
            SLOT_REPO_ANALYSIS, _SLOT_TYPE_REPO_ANALYSIS, analysis
        )

    def repo_analysis(self) -> "RepoAnalysis | None":
        """The produced :class:`RepoAnalysis`, or ``None`` when the slot is unset.

        Returns an explicit ``None`` when read before the Analyze stage has run
        (Req 7.4) rather than raising, matching the other accessors' absent-slot
        semantics (Req 6.5).
        """
        return self._get_content(SLOT_REPO_ANALYSIS)
