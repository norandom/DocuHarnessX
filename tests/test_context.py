"""Tests for the RunContext data-passing seam (task 2.3).

RunContext is the skeleton's single auditable data seam over the harness
``State`` slots. It provides typed setters/getters for the target-repository
path and the output directory keyed by the ``types.py`` slot constants, returns
an explicit ``None`` for an absent slot, and exposes the two ontology handles the
later stages read: ``segment_store()`` (typed by the ``ontology-engine``
``SegmentStore`` port at ``SLOT_SEGMENT_STORE``) and ``vocabulary()`` (the loaded
``Vocabulary`` at ``SLOT_VOCABULARY``).

Both ontology types are consumed through the skeleton's single re-export site
(``docuharnessx._ontology``); the data-passing contract reads/writes exclusively
through harness state/slots, never globals (Req 6.1, 6.2, 6.4, 6.5, 10.2).
"""

from __future__ import annotations

from harnessx.core.state import State

from docuharnessx._ontology import (
    SegmentStore,
    Vocabulary,
    default_profile,
)
from docuharnessx.context import RunContext
# InMemorySegmentStore is a concrete ontology-engine adapter (not part of the
# skeleton's pinned re-export surface); import it directly to exercise the
# SegmentStore-typed handle.
from docuharnessx.ontology import InMemorySegmentStore
from docuharnessx.types import (
    SLOT_FILE_INVENTORY,
    SLOT_OUTPUT_DIR,
    SLOT_REPO_ANALYSIS,
    SLOT_SEGMENT_STORE,
    SLOT_TARGET_REPO,
    SLOT_VOCABULARY,
)


def _state() -> State:
    return State(run_id="test-run")


# --------------------------------------------------------------------------- #
# Construction + state access                                                  #
# --------------------------------------------------------------------------- #


def test_run_context_wraps_a_state() -> None:
    state = _state()
    ctx = RunContext(state)
    assert ctx.state is state


# --------------------------------------------------------------------------- #
# Target-repo + output-dir slot round-trip (Req 6.2)                           #
# --------------------------------------------------------------------------- #


def test_target_repo_round_trip() -> None:
    ctx = RunContext(_state())
    assert ctx.target_repo() is None  # absent before set
    ctx.set_target_repo("/home/mc/Source/malware_hashes")
    assert ctx.target_repo() == "/home/mc/Source/malware_hashes"


def test_output_dir_round_trip() -> None:
    ctx = RunContext(_state())
    assert ctx.output_dir() is None  # absent before set
    ctx.set_output_dir("/tmp/out")
    assert ctx.output_dir() == "/tmp/out"


def test_setters_write_through_the_named_slot_keys() -> None:
    """Slots are keyed by the shared constants, not ad-hoc strings (Req 6.1)."""
    state = _state()
    ctx = RunContext(state)
    ctx.set_target_repo("/repo")
    ctx.set_output_dir("/out")
    assert state.get_slot(SLOT_TARGET_REPO) is not None
    assert state.get_slot(SLOT_TARGET_REPO).content == "/repo"
    assert state.get_slot(SLOT_OUTPUT_DIR) is not None
    assert state.get_slot(SLOT_OUTPUT_DIR).content == "/out"


# --------------------------------------------------------------------------- #
# Absent slots return an explicit None, never an undefined value (Req 6.5)     #
# --------------------------------------------------------------------------- #


def test_absent_target_repo_returns_none() -> None:
    assert RunContext(_state()).target_repo() is None


def test_absent_output_dir_returns_none() -> None:
    assert RunContext(_state()).output_dir() is None


def test_absent_segment_store_returns_none() -> None:
    assert RunContext(_state()).segment_store() is None


def test_absent_vocabulary_returns_none() -> None:
    assert RunContext(_state()).vocabulary() is None


# --------------------------------------------------------------------------- #
# Segment-store handle accessor (Req 6.3, 6.4)                                 #
# --------------------------------------------------------------------------- #


def test_segment_store_handle_round_trip() -> None:
    store = InMemorySegmentStore(default_profile())
    ctx = RunContext(_state())
    ctx.set_segment_store(store)
    handle = ctx.segment_store()
    assert handle is store


def test_segment_store_handle_is_segment_store_typed() -> None:
    """The returned handle conforms to the consumed SegmentStore port."""
    store = InMemorySegmentStore(default_profile())
    ctx = RunContext(_state())
    ctx.set_segment_store(store)
    handle = ctx.segment_store()
    # SegmentStore is a runtime_checkable Protocol with the four pinned methods.
    assert isinstance(handle, SegmentStore)
    for method in ("put", "query", "list_segments", "resolve_cross_links"):
        assert callable(getattr(handle, method))


def test_segment_store_written_through_named_slot() -> None:
    store = InMemorySegmentStore(default_profile())
    state = _state()
    RunContext(state).set_segment_store(store)
    assert state.get_slot(SLOT_SEGMENT_STORE).content is store


# --------------------------------------------------------------------------- #
# Vocabulary accessor (Req 10.2)                                               #
# --------------------------------------------------------------------------- #


def test_vocabulary_round_trip() -> None:
    vocab = default_profile()
    ctx = RunContext(_state())
    ctx.set_vocabulary(vocab)
    retrieved = ctx.vocabulary()
    assert retrieved is vocab
    assert isinstance(retrieved, Vocabulary)


def test_vocabulary_written_through_named_slot() -> None:
    vocab = default_profile()
    state = _state()
    RunContext(state).set_vocabulary(vocab)
    assert state.get_slot(SLOT_VOCABULARY).content is vocab


def test_vocabulary_roles_readable_by_stages() -> None:
    """Stages read the active roles from the slotted Vocabulary (Req 10.2)."""
    vocab = default_profile()
    ctx = RunContext(_state())
    ctx.set_vocabulary(vocab)
    retrieved = ctx.vocabulary()
    assert retrieved.roles == vocab.roles


# --------------------------------------------------------------------------- #
# repo-ingestion-analysis seam accessors (task 1.4, append-only)              #
# --------------------------------------------------------------------------- #
# Two new accessor pairs mirror the existing style: the Ingest->Analyze file
# inventory handoff (SLOT_FILE_INVENTORY) and the frozen RepoAnalysis output
# (SLOT_REPO_ANALYSIS). Each returns an explicit None when unset (Req 7.3, 7.4,
# 7.5). The slot is content-agnostic, so opaque sentinels exercise round-trip
# fidelity without coupling these tests to the analysis model's shape.


def test_absent_file_inventory_returns_none() -> None:
    """Reading the inventory slot before Ingest runs returns None (Req 7.4)."""
    assert RunContext(_state()).file_inventory() is None


def test_file_inventory_round_trip() -> None:
    ctx = RunContext(_state())
    assert ctx.file_inventory() is None  # absent before set
    inventory = object()  # opaque inventory handle; slot is content-agnostic
    ctx.set_file_inventory(inventory)
    assert ctx.file_inventory() is inventory


def test_file_inventory_written_through_named_slot() -> None:
    state = _state()
    inventory = object()
    RunContext(state).set_file_inventory(inventory)
    assert state.get_slot(SLOT_FILE_INVENTORY) is not None
    assert state.get_slot(SLOT_FILE_INVENTORY).content is inventory


def test_absent_repo_analysis_returns_none() -> None:
    """Reading the analysis slot before Analyze runs returns None (Req 7.4)."""
    assert RunContext(_state()).repo_analysis() is None


def test_repo_analysis_round_trip() -> None:
    ctx = RunContext(_state())
    assert ctx.repo_analysis() is None  # explicit unset before set (Req 7.4)
    analysis = object()  # opaque RepoAnalysis stand-in; slot is content-agnostic
    ctx.set_repo_analysis(analysis)
    assert ctx.repo_analysis() is analysis


def test_repo_analysis_round_trip_with_real_model() -> None:
    """A frozen RepoAnalysis stored then read back is the same instance."""
    from docuharnessx.analysis.model import (
        REPO_ANALYSIS_SCHEMA_VERSION,
        DocPresence,
        RepoAnalysis,
        ScanStats,
        TestLayout,
    )

    analysis = RepoAnalysis(
        schema_version=REPO_ANALYSIS_SCHEMA_VERSION,
        repo_path="/home/mc/Source/malware_hashes",
        languages=(),
        primary_languages=(),
        total_loc=0,
        total_files=0,
        structure=(),
        entrypoints=(),
        build_files=(),
        ci_workflows=(),
        tests=TestLayout(present=False, frameworks=(), paths=()),
        dependencies=(),
        components=(),
        public_surface=(),
        docs=DocPresence(
            has_readme=False, readme_paths=(), doc_dirs=(), other_docs=()
        ),
        artifacts=(),
        scan_stats=ScanStats(
            files_scanned=0,
            files_skipped=0,
            bytes_scanned=0,
            limit_reached=False,
            notes=(),
        ),
    )
    ctx = RunContext(_state())
    ctx.set_repo_analysis(analysis)
    assert ctx.repo_analysis() is analysis


def test_repo_analysis_written_through_named_slot() -> None:
    state = _state()
    analysis = object()
    RunContext(state).set_repo_analysis(analysis)
    assert state.get_slot(SLOT_REPO_ANALYSIS) is not None
    assert state.get_slot(SLOT_REPO_ANALYSIS).content is analysis
