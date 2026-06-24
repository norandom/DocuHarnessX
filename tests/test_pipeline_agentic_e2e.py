"""Credential-free end-to-end pipeline test for the agentic writer (task 5.2).

This is the make-or-break validation of the Wave 2.5 ``agentic-codebase-writer``: it drives
the FULL pipeline (Write -> Review -> Assemble -> build) over the crafted fixture repository
with NO network and NO credentials, and asserts that the agentic writer's bounded run reaches
the review gate's ACCEPT path so the assembled site is NON-EMPTY and carries a rendered
Mermaid diagram (Req 9.2, 9.4, 10.3).

How it is driven (the "write through assemble" portion of the pipeline)
-----------------------------------------------------------------------
The real stages do their work as a side effect of the content-free ``step_end`` event over a
shared run ``State``. This suite seeds the *writer's* inputs (a small, vocabulary-consistent
``CoveragePlan``, the loaded ``Vocabulary``, an empty ``InMemorySegmentStore``), the
``SLOT_TARGET_REPO`` rooted at a throwaway copy of ``tests/fixtures/agentic_repo``, and the
``SLOT_OUTPUT_DIR`` on one ``State``, then fires the three REAL downstream stages
(``WriteStage`` -> ``ReviewStage`` -> ``AssembleStage``) in order against it — each bound to
the one combined offline provider and a shared tracer-bearing runtime, exactly as the live run
loop drives them (each stage captures the ``State`` at ``task_start`` and acts at
``step_end``). Driving Write-through-Assemble directly (rather than via the full
``make_docgen`` chain) keeps the upstream Ingest/Classify/Plan derivation — and its
planner-shaped output, which is a separate spec's concern — out of this writer-boundary test
while keeping every stage under test REAL. The chain fires in order:

* the REAL :class:`~docuharnessx.stages.write.WriteStage` runs the bounded
  :class:`~docuharnessx.composition.AgenticProseRunner` per segment — the combined provider
  drives the REAL HarnessX agentic loop (real read/grep tools over the read-only fixture
  workspace) and returns the grounded, Mermaid-diagrammed, ``file:line``-cited body, which the
  structure gate accepts and the stage stores verbatim (Req 3.x, 4.5, 9.1-9.3);
* the REAL :class:`~docuharnessx.stages.review.ReviewStage` judges that written set — the same
  combined provider returns a passing per-criterion COBESY verdict, so every written segment
  is ACCEPTED (Req 9.4); and
* the REAL :class:`~docuharnessx.stages.assemble.AssembleStage` writes a Material for MkDocs
  source tree under ``<out>/site`` whose per-segment page carries the agent's body verbatim
  (the Mermaid fence + citations), with the Mermaid superfence enabled in ``mkdocs.yml``.

Finally the suite runs a REAL, network-free ``python -m mkdocs build --strict`` over that
assembled site and asserts the built HTML carries the rendered Mermaid diagram (Material wraps
a ``mermaid`` fence in a ``<pre class="mermaid">`` / ``<div class="mermaid">`` block under the
enabled superfence), closing the loop from agentic prose to a rendered page (Req 10.3).

The combined provider ROUTES by prompt content (the same robust signal
:class:`tests._fakes.RoutingFakeProvider` uses): a review/judge prompt carries the distinctive
"COBESY documentation quality evaluator" phrase and the named criteria, so it gets the passing
verdict; every other ``complete`` call is a writer-agentic turn and is answered by the scripted
read/grep tool-call sequence then the grounded body. No live API key is used anywhere.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from harnessx.core.events import StepEndEvent, TaskStartEvent
from harnessx.core.state import State

from docuharnessx.composition import MIN_CITED_FILES, validate_agent_body
from docuharnessx.context import RunContext
from docuharnessx.ontology import InMemorySegmentStore, Subject, default_profile
from docuharnessx.planning import COVERAGE_PLAN_SCHEMA_VERSION, CoveragePlan
from docuharnessx.planning.model import EvidenceRef, PlannedSegment
from docuharnessx.stages.assemble import AssembleStage
from docuharnessx.stages.review import ReviewStage
from docuharnessx.stages.write import WriteStage

from tests._fakes import SCRIPTED_AGENT_BODY, ScriptedReviewAgentProvider

# The doc framework is a declared runtime dependency installed in the project venv; skip
# gracefully if it is somehow absent rather than failing the whole module (mirrors the deploy
# build E2E and the multi-project E2E suites).
pytest.importorskip("mkdocs")
pytest.importorskip("material")

#: The crafted fixture repository the scripted agentic reads/citations target (task 1.3).
_FIXTURE_REPO = Path(__file__).parent / "fixtures" / "agentic_repo"


# --------------------------------------------------------------------------- #
# Fixtures: a small vocabulary-consistent plan naming the fixture evidence      #
# --------------------------------------------------------------------------- #


def _planned(
    *,
    key: str,
    roles: tuple[str, ...],
    intent: str,
    subject_local: str,
    priority: int,
    evidence: tuple[EvidenceRef, ...] = (),
) -> PlannedSegment:
    return PlannedSegment(
        segment_key=key,
        roles=roles,
        intent=intent,
        subjects=(Subject(prefix="component", local=subject_local),),
        priority=priority,
        evidence=evidence,
    )


def _seeded_planned() -> tuple[PlannedSegment, ...]:
    """A small plan whose evidence names the fixture's real files (default profile axes)."""
    return (
        _planned(
            key="developer__extend__component-app",
            roles=("developer",),
            intent="extend",
            subject_local="app",
            priority=20,
            evidence=(EvidenceRef(kind="entrypoint", detail="app.py"),),
        ),
        _planned(
            key="contributor__contribute__component-engine",
            roles=("contributor",),
            intent="contribute",
            subject_local="engine",
            priority=10,
            evidence=(EvidenceRef(kind="module", detail="engine.py"),),
        ),
    )


def _plan(segments: tuple[PlannedSegment, ...]) -> CoveragePlan:
    return CoveragePlan(
        schema_version=COVERAGE_PLAN_SCHEMA_VERSION,
        repo_path="/repo/x",
        vocabulary_fingerprint="fp",
        segments=segments,
    )


def _rooted_copy(tmp_path: Path) -> str:
    """Copy the pristine fixture into *tmp_path* so the run can root there cleanly.

    ``Harness.run`` writes a ``harness_config.yaml`` runtime snapshot into the workspace root,
    so rooting at a throwaway copy keeps the committed fixture clean and deterministic.
    """
    tmp_path.mkdir(parents=True, exist_ok=True)
    dest = tmp_path / "agentic_repo"
    shutil.copytree(_FIXTURE_REPO, dest)
    return str(dest)


# --------------------------------------------------------------------------- #
# Harness-faithful driver: bind the combined provider, seed slots, run once     #
# --------------------------------------------------------------------------- #


class _CapturingTracer:
    """A minimal tracer that records every emitted event (mirrors the stage suites)."""

    def __init__(self) -> None:
        self.events: list[Any] = []

    async def on_event(self, event: Any) -> None:
        self.events.append(event)


class _RuntimeStub:
    def __init__(self, tracer: _CapturingTracer) -> None:
        self.tracer = tracer


class _ModelConfigStub:
    """A ``ModelConfig`` stand-in exposing a ``main`` provider (mirrors PlanStage)."""

    def __init__(self, main: Any) -> None:
        self.main = main


class _RunResult:
    def __init__(
        self,
        *,
        run_context: RunContext,
        store: InMemorySegmentStore,
        out_dir: str,
        provider: ScriptedReviewAgentProvider,
        tracer: _CapturingTracer,
    ) -> None:
        self.run_context = run_context
        self.store = store
        self.out_dir = out_dir
        self.provider = provider
        self.tracer = tracer


def _sample_step_end() -> StepEndEvent:
    """A content-free ``step_end`` event — the hook every real stage acts on."""
    return StepEndEvent(
        run_id="agentic-e2e-run",
        step_id=1,
        step_summary="prior summary",
        tool_call_summary="",
        cumulative_tokens=10,
        cumulative_cost_usd=0.0,
    )


def _bind_stage(stage: Any, *, state: State, runtime: _RuntimeStub, model: Any) -> None:
    """Bind one real stage to the shared runtime + model and capture the run ``State``.

    Mirrors how ``Harness.run`` binds ``_rt`` / ``_model_config`` onto every processor and how
    the run loop delivers ``task_start`` (the stage stashes the ``State``) before ``step_end``.
    """
    stage._bind_runtime(runtime)
    stage._bind_model_config(_ModelConfigStub(model))

    async def _start() -> None:
        async for _ in stage.on_task_start(
            TaskStartEvent(run_id=state.run_id, step_id=0, state=state)
        ):
            pass

    asyncio.run(_start())


def _fire_step_end(stage: Any) -> None:
    """Drive one real stage's ``on_step_end`` to completion (forwarding the event)."""

    async def _collect() -> None:
        async for _ in stage.on_step_end(_sample_step_end()):
            pass

    asyncio.run(_collect())


def _drive_pipeline(*, repo_path: str, out_dir: str) -> _RunResult:
    """Drive the REAL Write -> Review -> Assemble stages once over a shared ``State``.

    Seeds the writer's inputs (``CoveragePlan``/``Vocabulary``/empty store) plus the target-repo
    and output-dir slots, binds the three real stages to one combined offline provider and a
    shared tracer-bearing runtime, then fires each stage's ``step_end`` in pipeline order. The
    Write stage produces the written set agentically (the real run loop over the read-only
    fixture workspace), the Review stage judges it (accept path), and the Assemble stage writes
    the Material site — exactly the production seam, fully offline.
    """
    vocab = default_profile()
    store = InMemorySegmentStore(vocab)
    os.makedirs(out_dir, exist_ok=True)

    provider = ScriptedReviewAgentProvider()
    tracer = _CapturingTracer()
    runtime = _RuntimeStub(tracer)

    state = State(run_id="agentic-e2e-run")
    run_context = RunContext(state)
    # Seed the writer's inputs + the target repo (the agent's read-only workspace root) + the
    # output dir (the assembler's site root). SLOT_REPO_ANALYSIS is intentionally left unset —
    # the writer and the assembler both tolerate ``analysis is None`` (Req 2.5).
    run_context.set_coverage_plan(_plan(_seeded_planned()))
    run_context.set_vocabulary(vocab)
    run_context.set_segment_store(store)
    run_context.set_target_repo(repo_path)
    run_context.set_output_dir(out_dir)

    # Fire the three real stages in pipeline order against the shared State.
    for stage in (WriteStage(), ReviewStage(), AssembleStage()):
        _bind_stage(stage, state=state, runtime=runtime, model=provider)
        _fire_step_end(stage)

    return _RunResult(
        run_context=run_context,
        store=store,
        out_dir=out_dir,
        provider=provider,
        tracer=tracer,
    )


@pytest.fixture(scope="module")
def pipeline_run(tmp_path_factory: pytest.TempPathFactory) -> _RunResult:
    """Drive the full credential-free pipeline once for the module (built once, asserted many)."""
    base = tmp_path_factory.mktemp("agentic_e2e")
    repo_path = _rooted_copy(base / "repo")
    out_dir = str(base / "out")
    return _drive_pipeline(repo_path=repo_path, out_dir=out_dir)


# --------------------------------------------------------------------------- #
# The agentic writer produced an accepted, grounded segment (Req 9.2, 9.4)      #
# --------------------------------------------------------------------------- #


def test_pipeline_drove_both_the_agentic_and_review_paths(pipeline_run: _RunResult) -> None:
    """The one combined offline provider drove the agentic-write loop AND the review judge.

    The scripted read/grep agentic turns executed (the writer ran the real run loop) and the
    review judge path was exercised (the provider routed at least one passing verdict), all
    with no network and no credentials (Req 9.1, 9.2).
    """
    provider = pipeline_run.provider
    # The writer-agentic loop ran the scripted read/grep turns for at least one segment.
    assert provider.read_paths == ["app.py", "engine.py", "config.py"]
    # The review judge path was routed at least once per written segment.
    assert provider.review_calls >= 1


def test_writer_stored_the_grounded_agentic_body(pipeline_run: _RunResult) -> None:
    """The agentic writer stored the agent's grounded body verbatim (Req 3.5, 4.5, 9.2).

    At least one stored segment carries the scripted agent body verbatim — a Mermaid fence
    plus >= MIN_CITED_FILES distinct ``file:line`` citations the structure gate accepted.
    """
    stored = pipeline_run.store.list_segments()
    assert stored, "the writer must store at least one segment"
    agentic_bodies = [s for s in stored if s.body == SCRIPTED_AGENT_BODY]
    assert agentic_bodies, "no stored segment carries the grounded agentic body verbatim"
    body = agentic_bodies[0].body
    gate = validate_agent_body(body)
    assert gate.accepted
    assert gate.mermaid_blocks >= 1
    assert gate.cited_files >= MIN_CITED_FILES


def test_review_gate_accepted_the_agentic_segments(pipeline_run: _RunResult) -> None:
    """The review gate's ACCEPT path is reached: the accepted set is non-empty (Req 9.4).

    The combined provider returns a passing COBESY verdict, so every written segment is
    accepted (no entry fell back to the fail-closed ``unavailable`` default), and the
    accepted ids equal the written ids.
    """
    rc = pipeline_run.run_context
    report = rc.review_report()
    written = rc.written_segments()
    assert report is not None
    assert written is not None

    written_ids = [s.id for s in written.segments]
    assert written_ids, "the writer must have written at least one segment"
    # The accept path was reached for every written segment (Req 9.4).
    assert report.aggregate.accepted == len(written_ids) > 0
    assert [s.id for s in report.accepted] == written_ids
    # No entry used the fail-closed unavailable judge default.
    assert all(
        getattr(e, "judge_source", None) != "unavailable" for e in report.entries
    )


# --------------------------------------------------------------------------- #
# The assembled site is NON-EMPTY and carries the Mermaid diagram (Req 9.4)     #
# --------------------------------------------------------------------------- #


def test_assembled_site_is_non_empty(pipeline_run: _RunResult) -> None:
    """The assembled site carries >= 1 content page and a per-segment page exists (Req 9.4)."""
    site = pipeline_run.run_context.assembled_site()
    assert site is not None
    # At least one per-segment content page was emitted.
    assert site.page_count >= 1

    docs_dir = Path(pipeline_run.out_dir) / "site" / "docs"
    assert docs_dir.is_dir(), "the assembled docs/ tree must exist"
    segment_pages = [
        p
        for p in docs_dir.glob("*.md")
        if p.name not in {"index.md", "tags.md"}
    ]
    assert segment_pages, "no per-segment Markdown page was written"


def test_an_assembled_page_carries_mermaid_and_citations(pipeline_run: _RunResult) -> None:
    """A per-segment page carries the agent's Mermaid fence + ``file:line`` citations (Req 9.4)."""
    docs_dir = Path(pipeline_run.out_dir) / "site" / "docs"
    page_texts = [p.read_text(encoding="utf-8") for p in docs_dir.glob("*.md")]
    mermaid_pages = [t for t in page_texts if "```mermaid" in t]
    assert mermaid_pages, "no assembled page carries a Mermaid fence"
    page = mermaid_pages[0]
    # The agent's body is preserved verbatim on the page (Req 4.5): the citations land too.
    assert "graph TD" in page
    assert "app.py:11" in page
    assert "engine.py:16" in page
    assert "config.py:10" in page


# --------------------------------------------------------------------------- #
# A real, network-free strict build renders the Mermaid diagram (Req 10.3)      #
# --------------------------------------------------------------------------- #


def test_strict_build_renders_the_mermaid_diagram(pipeline_run: _RunResult) -> None:
    """A real ``mkdocs build --strict`` over the assembled site renders the Mermaid block.

    The only subprocess is the local ``python -m mkdocs build --strict`` (no network); under
    the enabled ``pymdownx.superfences`` Mermaid custom fence, Material renders a fenced
    ``mermaid`` block into a ``class="mermaid"`` HTML element rather than a plain code block,
    and the strict build (which would error on any broken reference) succeeds (Req 10.3).
    """
    site_dir = Path(pipeline_run.out_dir) / "site"
    config_file = site_dir / "mkdocs.yml"
    assert config_file.is_file(), "the assembled site must carry a mkdocs.yml"

    built = site_dir / "_built"
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "mkdocs",
            "build",
            "--strict",
            "--config-file",
            str(config_file),
            "--site-dir",
            str(built),
        ],
        cwd=str(site_dir),
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, (
        "mkdocs build --strict failed:\n"
        f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
    )

    # The built site is non-empty: rendered HTML pages exist.
    html_pages = list(built.rglob("*.html"))
    assert html_pages, "the strict build produced no rendered HTML pages"

    # Under the enabled Mermaid superfence, the fenced block renders to a class="mermaid"
    # HTML element (not a plain <code> block), proving the diagram reaches the published page.
    joined_html = "\n".join(p.read_text(encoding="utf-8") for p in html_pages)
    assert 'class="mermaid"' in joined_html, (
        "the rendered site does not carry a class=\"mermaid\" element; the Mermaid superfence "
        "did not render the agent's diagram"
    )
