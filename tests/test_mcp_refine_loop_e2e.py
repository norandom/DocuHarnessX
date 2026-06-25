"""Credential-free END-TO-END refine loop -> non-empty themed site (mcp-refine task 6.1).

This is the feature-level integration test for the ``docuharnessx-mcp-refine`` server: it
drives the WHOLE interactive refine loop a human runs through an MCP client — rewrite a
segment, draft and refine the project overview, then reassemble the themed Material site —
end to end with the offline :class:`tests._fakes.ScriptedAgentProvider` over a throwaway copy
of the crafted fixture repo (``tests/fixtures/agentic_repo``), so the REAL
:class:`~docuharnessx.composition.AgenticProseRunner` run loop (its bounded read/grep
exploration + the deterministic structure gate) executes with **no network and no credentials**
(Req 10.1, 10.2, 10.4).

It composes only the public handler surface over a real
:class:`~docuharnessx.ontology.FilesystemSegmentStore` (the on-disk single source of truth the
batch run produces), proving the anti-slop contract holds across the seams the individual
task-3 tests check in isolation:

* an accepted ``rewrite_segment`` re-grounds through the writer, clears the gate, and
  **replaces the stored segment in place** (same id, grounded body) so the edit persists into
  the later reassemble (Req 5.1-5.4);
* ``draft_overview`` then ``refine_overview`` produce a grounded, gate-passing overview
  structured around Purpose / Use cases / Features / Design choices, persisted as the reserved
  first-class entry (Req 7.1-7.4);
* the human ``guidance`` reaches the rendered agent task (applied near the mission) yet is
  **never echoed** as a heading/section in the persisted body (Req 5.9, 7.2, 9.7);
* a forced gate-reject surfaces the verdict + the deterministic fallback and **persists
  nothing** (anti-slop, never a silent pass; Req 5.5, 7.6, 9.3); and
* ``reassemble_site`` rebuilds a **non-empty** themed Material site from the live store +
  overview, whose pages carry the gate-passing body's Mermaid fence and ``file:line`` citations
  and the per-target identity (Req 8.1-8.3, 8.6, 10.4).

The store, the repo, and the run loop are all real; only the model is the offline scripted
fake (no second engine, no RAG).
"""

from __future__ import annotations

import asyncio
import hashlib
import shutil
from pathlib import Path

from docuharnessx.composition import MIN_CITED_FILES, validate_agent_body
from docuharnessx.composition.blueprint import build_blueprint
from docuharnessx.composition.model import ProseResult
from docuharnessx.composition.wiring import segment_id, wire_segment
from docuharnessx.mcp import handlers
from docuharnessx.mcp.overview import OVERVIEW_SEGMENT_ID
from docuharnessx.mcp.session import RefineSession
from docuharnessx.ontology import (
    AxisTerm,
    FilesystemSegmentStore,
    Segment,
    Subject,
    Vocabulary,
)
from docuharnessx.planning.model import PlannedSegment
from tests._fakes import SCRIPTED_AGENT_BODY, ScriptedAgentProvider

_FIXTURE_REPO = Path(__file__).parent / "fixtures" / "agentic_repo"
_PREFIXES = frozenset({"component", "tech", "artifact", "topic"})


# --------------------------------------------------------------------------- #
# Fixtures: a real per-target session over a real store + the fixture repo      #
# --------------------------------------------------------------------------- #


def _subject(raw: str) -> Subject:
    return Subject.parse(raw, _PREFIXES)


def _vocab() -> Vocabulary:
    return Vocabulary(
        roles=(
            AxisTerm("platform-dev", "Platform Developer", "Builds on the platform."),
            AxisTerm("adopter", "Adopter", "Adopts the project."),
        ),
        intents=(
            AxisTerm("understand", "Understand", "Build a mental model and orient."),
            AxisTerm("extend", "Extend", "Add capabilities."),
        ),
        subject_prefixes=("component:", "tech:", "artifact:", "topic:"),
    )


class _Identity:
    """A distinctive per-target SiteIdentity stand-in (never DocuHarnessX's own).

    The reassemble path must reuse exactly this identity through ``assemble_site``; the test
    asserts the distinctive ``site_name`` lands in the emitted site, proving the per-target
    identity is reused and DocuHarnessX's own identity is never derived (Req 2.4, 8.5).
    """

    site_name = "RefineLoopDemoService"
    repo_name = "demo/refine-loop"
    repo_url = "https://example.com/demo/refine-loop"
    site_url = ""
    base_path = "/"
    edit_uri = ""


def _planner_segment_key(
    roles: tuple[str, ...], intent: str, subjects: tuple[Subject, ...]
) -> str:
    sorted_subjects = tuple(sorted(subjects, key=lambda s: s.canonical()))
    payload = "\n".join(s.canonical() for s in sorted_subjects)
    digest = hashlib.blake2b(payload.encode("utf-8"), digest_size=6).hexdigest()
    return f"{','.join(roles)}__{intent}__{digest}"


# An initial stored body (a deterministic, ungrounded placeholder) the rewrite REPLACES, so the
# test can prove the persisted body really changed to the re-grounded agentic output.
_INITIAL_BODY = (
    "# How the application starts\n\n"
    "Understand: the fastest path is the short sequence below.\n\n"
    "This page documents app.\n"
)


def _stored_segment(
    vocab: Vocabulary,
    *,
    roles: tuple[str, ...],
    intent: str,
    subjects: tuple[Subject, ...],
    body: str,
    summary: str,
) -> Segment:
    """A Segment as the real pipeline persists it: planner key -> build_blueprint -> wire."""
    sorted_subjects = tuple(sorted(subjects, key=lambda s: s.canonical()))
    planned = PlannedSegment(
        segment_key=_planner_segment_key(roles, intent, sorted_subjects),
        roles=roles,
        intent=intent,
        subjects=sorted_subjects,
        priority=0,
        evidence=(),
    )
    blueprint = build_blueprint(planned, None, vocab)
    return wire_segment(
        planned, blueprint, ProseResult(body=body, summary=summary, source="fake")
    )


def _rooted_copy(tmp_path: Path) -> str:
    """Copy the pristine fixture repo into ``tmp_path`` so the run roots there cleanly.

    ``Harness.run`` writes a runtime snapshot into the workspace root, so rooting at a throwaway
    copy keeps the committed fixture clean (mirrors the task-3 suites).
    """
    dest = tmp_path / "agentic_repo"
    shutil.copytree(_FIXTURE_REPO, dest)
    return str(dest)


class _FakeModelConfig:
    """A ModelConfig-shaped object whose ``.main`` is the scripted provider."""

    def __init__(self, provider: object) -> None:
        self.main = provider


def _session(
    tmp_path: Path,
    *,
    provider: object | None,
    segments: tuple[Segment, ...] = (),
) -> RefineSession:
    """A RefineSession over a real FilesystemSegmentStore, rooted at a fixture-repo copy.

    The store is the same on-disk truth a batch run produces; ``target_repo`` is a throwaway
    copy of the crafted fixture repo so the REAL run loop reads real files offline. When
    ``provider`` is ``None`` the session has no model (the model-free paths still work).
    """
    vocab = _vocab()
    out_dir = tmp_path / "out"
    store = FilesystemSegmentStore(str(out_dir / "segments"), vocab)
    for seg in segments:
        store.put(seg)
    return RefineSession(
        out_dir=str(out_dir),
        target_repo=_rooted_copy(tmp_path),
        vocab=vocab,
        store=store,
        model_config=_FakeModelConfig(provider) if provider is not None else None,
        identity=_Identity(),
        analysis=None,
    )


def _the_segment(vocab: Vocabulary) -> Segment:
    return _stored_segment(
        vocab,
        roles=("platform-dev",),
        intent="understand",
        subjects=(_subject("component:app"),),
        body=_INITIAL_BODY,
        summary="The initial, to-be-replaced summary.",
    )


def _all_pages(site_dir: Path) -> str:
    """Concatenate every emitted docs page so assertions can search the whole site corpus."""
    docs_dir = site_dir / "docs"
    return "\n".join(p.read_text(encoding="utf-8") for p in docs_dir.rglob("*.md"))


# --------------------------------------------------------------------------- #
# The full credential-free refine loop: rewrite + overview -> non-empty site    #
# --------------------------------------------------------------------------- #


def test_credential_free_refine_loop_produces_non_empty_site(tmp_path: Path) -> None:
    """rewrite + draft/refine_overview -> reassemble: a non-empty site with the gated bodies.

    Drives the whole loop through the public handlers over one real session: an accepted
    rewrite (re-grounded + gated + replace-in-place) and a drafted+refined overview both persist
    into the store, and ``reassemble_site`` rebuilds a NON-EMPTY themed site whose pages carry
    the gate-passing body's Mermaid fence + ``file:line`` citations (Req 10.4).
    """
    vocab = _vocab()
    seg = _the_segment(vocab)
    session = _session(
        tmp_path, provider=ScriptedAgentProvider(), segments=(seg,)
    )
    original_id = seg.id

    # 1) Rewrite the segment: re-grounded through the REAL run loop, gated, replace-in-place.
    rewrite = asyncio.run(handlers.rewrite_segment(session, original_id, ""))
    assert not rewrite.get("error")
    assert rewrite["accepted"] is True
    assert rewrite["id"] == original_id
    # The persisted body changed to the grounded agentic body and clears the gate.
    stored = next(s for s in session.store.list_segments() if s.id == original_id)
    assert stored.body == SCRIPTED_AGENT_BODY
    assert stored.body != _INITIAL_BODY
    assert validate_agent_body(stored.body, min_citations=session.min_citations).accepted
    # No second id was created — the rewrite replaced in place (Req 5.4, 5.8).
    assert len(session.store.list_segments()) == 1

    # 2) Draft then refine the project overview: grounded, gated, persisted as the reserved entry.
    draft = asyncio.run(handlers.draft_overview(session))
    assert draft.get("accepted") is True
    assert draft["id"] == OVERVIEW_SEGMENT_ID
    refine = asyncio.run(
        handlers.refine_overview(session, "emphasise the bounded work cycle")
    )
    assert refine.get("accepted") is True
    got_overview = handlers.get_overview(session)
    assert got_overview.get("exists") is True
    assert got_overview["body"] == SCRIPTED_AGENT_BODY

    # 3) Reassemble the themed Material site from the live store + overview (model-free).
    result = handlers.reassemble_site(session)
    assert not result.get("error")
    site_dir = Path(result["site_dir"])
    assert site_dir.is_dir()
    # The site is NON-EMPTY: the rewritten segment page + the overview front-door page.
    assert result["page_count"] >= 1
    assert result["page_count"] == 2  # one store segment + the overview
    assert result["overview_included"] is True
    assert result["role_page_count"] >= 1

    # A well-formed Material site: mkdocs.yml + a home page.
    assert (site_dir / "mkdocs.yml").is_file()
    assert (site_dir / "docs" / "index.md").is_file()

    # The rebuilt pages carry the gate-passing body's Mermaid fence + file:line citations.
    corpus = _all_pages(site_dir)
    assert "```mermaid" in corpus
    assert "app.py:11" in corpus  # a real fixture citation from SCRIPTED_AGENT_BODY
    assert "engine.py:16" in corpus
    assert "config.py:10" in corpus

    # The per-target identity is reused (never DocuHarnessX's; Req 2.4, 8.5).
    mkdocs_yml = (site_dir / "mkdocs.yml").read_text(encoding="utf-8")
    assert "RefineLoopDemoService" in mkdocs_yml
    assert "DocuHarnessX" not in mkdocs_yml


# --------------------------------------------------------------------------- #
# A draft-overview-only loop also yields a non-empty site (Req 10.4 variant).   #
# --------------------------------------------------------------------------- #


def test_overview_only_refine_loop_yields_non_empty_site(tmp_path: Path) -> None:
    """draft_overview over an otherwise-empty store -> reassemble -> a non-empty front door.

    The minimal loop the design's E2E names ("rewrite (or draft_overview) -> reassemble"): with
    no stored role segments, a drafted overview alone still produces a non-empty site whose
    single page is the grounded, gate-passing front door (Req 10.4, 8.6 boundary).
    """
    session = _session(tmp_path, provider=ScriptedAgentProvider())

    draft = asyncio.run(handlers.draft_overview(session))
    assert draft.get("accepted") is True

    result = handlers.reassemble_site(session)
    assert not result.get("error")
    site_dir = Path(result["site_dir"])
    # Exactly the overview is a per-segment page (Req 8.6 boundary: overview-only store).
    assert result["page_count"] == 1
    assert result["overview_included"] is True
    corpus = _all_pages(site_dir)
    assert "```mermaid" in corpus
    assert "app.py:11" in corpus


# --------------------------------------------------------------------------- #
# Guidance reaches the rendered task but is NOT echoed as a heading (Req 5.9).   #
# --------------------------------------------------------------------------- #


def test_loop_guidance_reaches_task_but_is_not_echoed_in_persisted_bodies(
    tmp_path: Path,
) -> None:
    """Across the loop the human guidance is APPLIED (reaches the task) yet never echoed.

    A recording provider captures the rendered agent task so the test can prove the guidance
    reached ``BaseTask.description`` (the applied author-guidance instruction near the mission);
    the persisted rewrite + overview bodies must NOT echo the verbatim guidance as a
    heading/section (applied, not echoed; Req 5.9, 7.2, 9.7).
    """
    rewrite_guidance = "ZZZ_REWRITE_TOKEN emphasise the configuration defaults"
    overview_guidance = "QQQ_OVERVIEW_TOKEN emphasise the deployment story"

    class _RecordingProvider(ScriptedAgentProvider):
        def __init__(self) -> None:
            super().__init__()
            self.seen_text = ""

        async def complete(self, messages, tools, stream_callback=None):
            for m in messages:
                content = getattr(m, "content", None)
                if content:
                    self.seen_text += str(content) + "\n"
            return await super().complete(messages, tools, stream_callback)

    provider = _RecordingProvider()
    vocab = _vocab()
    seg = _the_segment(vocab)
    session = _session(tmp_path, provider=provider, segments=(seg,))

    # Rewrite with guidance, then refine the overview with different guidance.
    rewrite = asyncio.run(handlers.rewrite_segment(session, seg.id, rewrite_guidance))
    assert rewrite["accepted"] is True
    asyncio.run(handlers.draft_overview(session))
    refine = asyncio.run(handlers.refine_overview(session, overview_guidance))
    assert refine["accepted"] is True

    # (a) Each guidance reached the agent's task via the applied author-guidance instruction.
    assert rewrite_guidance in provider.seen_text
    assert overview_guidance in provider.seen_text
    assert "Apply this refinement guidance" in provider.seen_text

    # (b) Neither verbatim guidance is echoed as a heading in any persisted body, nor appears
    #     verbatim anywhere in the persisted bodies (the scripted body is fixed + grounded).
    rewritten = next(s for s in session.store.list_segments() if s.id == seg.id)
    overview_body = handlers.get_overview(session)["body"]
    for body in (rewritten.body, overview_body):
        assert "ZZZ_REWRITE_TOKEN" not in body
        assert "QQQ_OVERVIEW_TOKEN" not in body
        for line in body.splitlines():
            if line.strip().startswith("#"):
                assert "ZZZ_REWRITE_TOKEN" not in line
                assert "QQQ_OVERVIEW_TOKEN" not in line


# --------------------------------------------------------------------------- #
# A forced gate-reject surfaces the verdict + fallback and PERSISTS NOTHING.     #
# --------------------------------------------------------------------------- #


class _RejectedBodyProvider:
    """A provider whose end-turn body fails the structure gate (no mermaid / citations)."""

    async def complete(self, messages, tools, stream_callback=None):
        from harnessx.core.events import ModelResponseEvent

        return ModelResponseEvent(
            run_id="rejected-run",
            step_id=0,
            content="Just some prose with no mermaid and no citations.",
            finish_reason="end_turn",
        )

    def count_tokens(self, messages) -> int:
        return 1


def test_loop_forced_gate_reject_surfaces_verdict_and_persists_nothing(
    tmp_path: Path,
) -> None:
    """A rejected rewrite + a rejected overview both surface the verdict and persist nothing.

    Anti-slop: on a gate-reject the handler returns the gate verdict + the deterministic
    fallback and the store is left untouched (the stored segment unchanged, no overview written),
    so a later reassemble still reflects only the gate-passing bodies — never a silent pass
    (Req 5.5, 7.6, 9.3). Asserted across the loop: the prior accepted overview survives a failed
    refine.
    """
    vocab = _vocab()
    seg = _the_segment(vocab)

    # First, an accepted draft so there is a prior overview a failed refine must not clobber.
    session = _session(
        tmp_path, provider=ScriptedAgentProvider(), segments=(seg,)
    )
    asyncio.run(handlers.draft_overview(session))
    prior_overview = handlers.get_overview(session)["body"]
    assert prior_overview == SCRIPTED_AGENT_BODY

    # Now swap in the rejecting provider and attempt a rewrite + a refine.
    session.model_config = _FakeModelConfig(_RejectedBodyProvider())

    rewrite = asyncio.run(handlers.rewrite_segment(session, seg.id, ""))
    # The reject is a verdict, not a tool error; a deterministic fallback is surfaced.
    assert rewrite["accepted"] is False
    assert rewrite.get("error") is not True
    assert "reason" in rewrite
    assert rewrite.get("fallback_body")
    # Nothing persisted: the stored segment is unchanged (still the initial body).
    stored = next(s for s in session.store.list_segments() if s.id == seg.id)
    assert stored.body == _INITIAL_BODY

    refine = asyncio.run(handlers.refine_overview(session, "make it worse"))
    assert refine["accepted"] is False
    assert refine.get("fallback_body")
    # The prior accepted overview survives the failed refine (Req 7.6).
    assert handlers.get_overview(session)["body"] == prior_overview

    # A reassemble after the rejected runs still reflects only the gate-passing bodies.
    result = handlers.reassemble_site(session)
    assert not result.get("error")
    corpus = _all_pages(Path(result["site_dir"]))
    # The rejected, ungrounded prose never reaches the site.
    assert "no mermaid and no citations" not in corpus
    # The surviving overview's grounded citations still appear.
    assert "app.py:11" in corpus


# --------------------------------------------------------------------------- #
# The loop is bounded + never free-writes (the real run loop drove the tools).  #
# --------------------------------------------------------------------------- #


def test_loop_runs_the_real_bounded_writer_never_freewrites(tmp_path: Path) -> None:
    """The persisted bodies come ONLY from the real run loop's gated output (no free-write).

    The scripted provider records its ``complete`` calls; an accepted rewrite drives the real
    exploration turns (>= the scripted read/grep turns + the final body turn), proving the body
    is the agent's gated output rather than handler-authored prose (Req 9.1, 9.6, 5.7).
    """
    provider = ScriptedAgentProvider()
    vocab = _vocab()
    seg = _the_segment(vocab)
    session = _session(tmp_path, provider=provider, segments=(seg,))

    asyncio.run(handlers.rewrite_segment(session, seg.id, ""))

    # The real run loop executed the scripted exploration turns + the final body turn.
    assert provider.complete_calls >= 2
    assert session.min_citations == MIN_CITED_FILES
    stored = next(s for s in session.store.list_segments() if s.id == seg.id)
    assert stored.body == SCRIPTED_AGENT_BODY
