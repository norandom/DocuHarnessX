"""Unit tests for ``reassemble_site`` — ReviewReport-from-store, model-free (mcp task 3.4).

``reassemble_site(session)`` is the **model-free** assembly handler. It NEVER consults a model
and NEVER free-writes: it builds a :class:`~docuharnessx.review.model.ReviewReport` whose
``accepted`` set is the current segments in the session's
:class:`~docuharnessx.ontology.FilesystemSegmentStore` (the on-disk **single source of truth**)
plus the persisted reserved overview entry when present, and calls the **reused**
:func:`~docuharnessx.assembler.assemble_site` with the session's loaded ``Vocabulary``, optional
``RepoAnalysis``, output dir, and per-target ``SiteIdentity``. It returns the produced site
directory and the per-segment / per-role page counts, writes only under the output dir, and
reuses the per-target identity (never DocuHarnessX's). An empty store (and no overview) yields a
well-formed empty site with a zero page count (Req 8.1-8.6, 9.4).

These tests build a real :class:`FilesystemSegmentStore` over a tmp directory (the same on-disk
truth a batch run produces) seeded with realistic wired segments, optionally a persisted reserved
overview entry, and a :class:`RefineSession` carrying them. They run the **real**
:func:`assemble_site` (no model, no network) and pin: a populated store yields a non-empty site
reflecting the current bodies (+ overview), an empty store yields a well-formed empty site with
zero pages, the per-target identity is reused, and nothing is written into the target repo.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from docuharnessx import mcp
from docuharnessx.composition import MIN_CITED_FILES
from docuharnessx.composition.blueprint import build_blueprint
from docuharnessx.composition.model import ProseResult
from docuharnessx.composition.wiring import wire_segment
from docuharnessx.mcp import handlers
from docuharnessx.mcp.overview import (
    OVERVIEW_SEGMENT_ID,
    build_overview_blueprint,
    persist_overview,
    wire_overview_segment,
)
from docuharnessx.mcp.session import RefineSession
from docuharnessx.ontology import (
    AxisTerm,
    FilesystemSegmentStore,
    Segment,
    Subject,
    Vocabulary,
)
from docuharnessx.planning.model import PlannedSegment

_PREFIXES = frozenset({"component", "tech", "artifact", "topic"})


def _subject(raw: str) -> Subject:
    return Subject.parse(raw, _PREFIXES)


def _vocab() -> Vocabulary:
    return Vocabulary(
        roles=(
            AxisTerm("platform-dev", "Platform Developer", "Builds on the platform."),
            AxisTerm("adopter", "Adopter", "Adopts the project."),
        ),
        intents=(
            AxisTerm("extend", "Extend", "Add capabilities."),
            AxisTerm("understand", "Understand", "Build a mental model and orient."),
        ),
        subject_prefixes=("component:", "tech:", "artifact:", "topic:"),
    )


class _Identity:
    """A per-target SiteIdentity stand-in — a DISTINCTIVE site_name (never DocuHarnessX's).

    The reassemble handler must reuse exactly this identity through ``assemble_site``; the
    tests assert the distinctive ``site_name`` lands in the emitted ``mkdocs.yml`` and the home
    page, proving the per-target identity is reused and DocuHarnessX's own identity is never
    derived (Req 8.5, 2.4).
    """

    site_name = "AcmeWidgetService"
    repo_name = "acme/widget-service"
    repo_url = "https://example.com/acme/widget-service"
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


# A grounded body that PASSES the structure gate (one mermaid + >= the minimum citations).
_GROUNDED_BODY = (
    "## Overview\n\n"
    "```mermaid\n"
    "graph TD\n"
    "  A --> B\n"
    "```\n\n"
    "The CLI entrypoint lives in cli.py:10 and dispatches to the runner in "
    "agent.py:42, validated by gate.py:7.\n"
)

# A distinctive sentinel only in the overview body, so the test can find the overview page.
_OVERVIEW_BODY = (
    "## Purpose\n\n"
    "OVERVIEW_FRONT_DOOR_SENTINEL — what AcmeWidgetService is and why it exists.\n\n"
    "```mermaid\n"
    "graph TD\n"
    "  P --> Q\n"
    "```\n\n"
    "Grounded in cli.py:10, agent.py:42, and gate.py:7.\n"
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


def _session(
    tmp_path: Path,
    *,
    segments: tuple[Segment, ...] = (),
) -> RefineSession:
    """A model-free RefineSession over a real FilesystemSegmentStore seeded with ``segments``.

    ``model_config`` is None throughout — ``reassemble_site`` is model-free, so nothing here
    requires a provider or network. ``target_repo`` is an empty tmp dir (the handler writes
    only under ``out_dir`` and never into the target repo).
    """
    vocab = _vocab()
    out_dir = tmp_path / "out"
    store = FilesystemSegmentStore(str(out_dir / "segments"), vocab)
    for seg in segments:
        store.put(seg)
    target = tmp_path / "repo"
    target.mkdir(parents=True, exist_ok=True)
    return RefineSession(
        out_dir=str(out_dir),
        target_repo=str(target),
        vocab=vocab,
        store=store,
        model_config=None,
        identity=_Identity(),
        analysis=None,
    )


def _two_segments(vocab: Vocabulary) -> tuple[Segment, ...]:
    return (
        _stored_segment(
            vocab,
            roles=("platform-dev",),
            intent="understand",
            subjects=(_subject("component:app"),),
            body=_GROUNDED_BODY,
            summary="How the platform developer gets oriented.",
        ),
        _stored_segment(
            vocab,
            roles=("adopter",),
            intent="extend",
            subjects=(_subject("component:engine"),),
            body=_GROUNDED_BODY,
            summary="How an adopter extends the engine.",
        ),
    )


def _persist_overview(session: RefineSession) -> Segment:
    """Persist a reserved, gate-passing overview entry under <out>/segments/overview.md."""
    blueprint = build_overview_blueprint(
        session.identity, session.vocab, session.analysis, guidance=""
    )
    seg = wire_overview_segment(
        blueprint,
        ProseResult(body=_OVERVIEW_BODY, summary="The project front door.", source="fake"),
    )
    persist_overview(str(Path(session.out_dir) / "segments"), seg)
    return seg


def _read_all_pages(docs_dir: Path) -> str:
    """Concatenate every emitted docs page so assertions can search the whole site corpus."""
    return "\n".join(p.read_text(encoding="utf-8") for p in docs_dir.rglob("*.md"))


# --------------------------------------------------------------------------- #
# Package surface: reassemble_site is exposed from the handlers + the package.   #
# --------------------------------------------------------------------------- #


def test_handlers_expose_reassemble_site() -> None:
    assert hasattr(handlers, "reassemble_site")
    assert hasattr(mcp, "reassemble_site")
    assert mcp.reassemble_site is handlers.reassemble_site


# --------------------------------------------------------------------------- #
# Populated store -> non-empty site reflecting the current bodies (Req 8.1-8.3) #
# --------------------------------------------------------------------------- #


def test_populated_store_yields_non_empty_site_reflecting_bodies(tmp_path: Path) -> None:
    vocab = _vocab()
    session = _session(tmp_path, segments=_two_segments(vocab))

    result = handlers.reassemble_site(session)

    # Not an error envelope; reports the site dir + counts (Req 8.2).
    assert not result.get("error")
    site_dir = Path(result["site_dir"])
    assert site_dir.is_dir()
    # One per-segment page per stored segment (Req 8.2). No overview here, so page_count == 2.
    assert result["page_count"] == 2
    assert result["role_page_count"] >= 1

    # The rebuilt site reflects the CURRENT persisted bodies (Req 8.3): the grounded body's
    # mermaid + a citation appear in the emitted docs.
    docs_dir = site_dir / "docs"
    corpus = _read_all_pages(docs_dir)
    assert "```mermaid" in corpus
    assert "cli.py:10" in corpus
    # mkdocs.yml exists (a well-formed Material site).
    assert (site_dir / "mkdocs.yml").is_file()


# --------------------------------------------------------------------------- #
# Overview present -> surfaced as an extra first-class page (Req 8.1, 8.3)       #
# --------------------------------------------------------------------------- #


def test_persisted_overview_is_surfaced_in_the_reassembled_site(tmp_path: Path) -> None:
    vocab = _vocab()
    session = _session(tmp_path, segments=_two_segments(vocab))
    _persist_overview(session)

    result = handlers.reassemble_site(session)

    assert not result.get("error")
    site_dir = Path(result["site_dir"])
    docs_dir = site_dir / "docs"
    corpus = _read_all_pages(docs_dir)

    # The overview body is surfaced as a first-class page (Req 8.1, 8.3).
    assert "OVERVIEW_FRONT_DOOR_SENTINEL" in corpus
    # The overview adds one page on top of the two store segments (Req 8.2).
    assert result["page_count"] == 3


# --------------------------------------------------------------------------- #
# Empty store -> well-formed empty site, zero pages (Req 8.6)                    #
# --------------------------------------------------------------------------- #


def test_empty_store_yields_well_formed_empty_site_zero_pages(tmp_path: Path) -> None:
    session = _session(tmp_path)  # no segments, no overview

    result = handlers.reassemble_site(session)

    assert not result.get("error")
    site_dir = Path(result["site_dir"])
    # A well-formed (empty) site: it still has mkdocs.yml + a home page, but zero per-segment
    # pages and zero per-role landing pages (Req 8.6).
    assert site_dir.is_dir()
    assert (site_dir / "mkdocs.yml").is_file()
    assert (site_dir / "docs" / "index.md").is_file()
    assert result["page_count"] == 0
    assert result["role_page_count"] == 0


# --------------------------------------------------------------------------- #
# Per-target identity reused; never DocuHarnessX's (Req 8.5, 2.4)               #
# --------------------------------------------------------------------------- #


def test_reassemble_reuses_the_per_target_identity(tmp_path: Path) -> None:
    vocab = _vocab()
    session = _session(tmp_path, segments=_two_segments(vocab))

    result = handlers.reassemble_site(session)
    site_dir = Path(result["site_dir"])

    mkdocs_yml = (site_dir / "mkdocs.yml").read_text(encoding="utf-8")
    # The session's distinctive per-target site_name lands in mkdocs.yml (Req 8.5).
    assert "AcmeWidgetService" in mkdocs_yml
    # DocuHarnessX's own identity is never derived for the target site.
    assert "DocuHarnessX" not in mkdocs_yml
    home = (site_dir / "docs" / "index.md").read_text(encoding="utf-8")
    assert "AcmeWidgetService" in home


# --------------------------------------------------------------------------- #
# Writes only under out_dir; never into the target repo (Req 8.5)               #
# --------------------------------------------------------------------------- #


def test_reassemble_writes_only_under_out_dir_not_the_target_repo(tmp_path: Path) -> None:
    vocab = _vocab()
    session = _session(tmp_path, segments=_two_segments(vocab))
    target = Path(session.target_repo)
    before = sorted(p.name for p in target.iterdir())

    result = handlers.reassemble_site(session)

    # The site is written UNDER the session output dir (Req 8.5).
    site_dir = Path(result["site_dir"])
    assert str(site_dir).startswith(str(Path(session.out_dir).resolve())) or str(
        site_dir
    ).startswith(session.out_dir)
    # The target repo is untouched (read-only target invariant; Req 8.5).
    after = sorted(p.name for p in target.iterdir())
    assert after == before


# --------------------------------------------------------------------------- #
# Model-free: reassemble never reads session.model() (Req 8.4)                  #
# --------------------------------------------------------------------------- #


def test_reassemble_is_model_free(tmp_path: Path) -> None:
    vocab = _vocab()
    session = _session(tmp_path, segments=_two_segments(vocab))

    # Make any model access blow up: reassemble must never touch the model (Req 8.4).
    def _boom() -> object:  # pragma: no cover - must never be called
        raise AssertionError("reassemble_site must be model-free")

    session.model = _boom  # type: ignore[assignment]

    result = handlers.reassemble_site(session)
    assert not result.get("error")
    assert result["page_count"] == 2


# --------------------------------------------------------------------------- #
# An empty store but a persisted overview: the overview still surfaces.          #
# --------------------------------------------------------------------------- #


def test_overview_only_store_surfaces_the_overview(tmp_path: Path) -> None:
    session = _session(tmp_path)  # empty store
    _persist_overview(session)

    result = handlers.reassemble_site(session)

    assert not result.get("error")
    site_dir = Path(result["site_dir"])
    corpus = _read_all_pages(site_dir / "docs")
    assert "OVERVIEW_FRONT_DOOR_SENTINEL" in corpus
    # Only the overview is a per-segment page.
    assert result["page_count"] == 1
