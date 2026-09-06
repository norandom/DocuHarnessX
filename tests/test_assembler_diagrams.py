"""Global diagrams catalog assembled next to the glossary."""

from __future__ import annotations

from pathlib import Path

from docuharnessx.analysis.model import (
    REPO_ANALYSIS_SCHEMA_VERSION,
    Component,
    DocPresence,
    Entrypoint,
    RepoAnalysis,
    ScanStats,
)
from docuharnessx.analysis.model import TestLayout as AnalysisTestLayout
from docuharnessx.assembler.model import SiteIdentity
from docuharnessx.assembler.pages import page_filename
from docuharnessx.assembler.question_site import assemble_question_site
from docuharnessx.comprehension.graphs import (
    DIAGRAMS_PAGE_PATH,
    collect_diagram_figures,
    render_diagrams_index,
)
from docuharnessx.comprehension.signals import CoverageCounts
from docuharnessx.pages.model import Page
from docuharnessx.planning.question_model import QuestionKind, make_question_id


def _identity() -> SiteIdentity:
    return SiteIdentity(
        site_name="agentic_repo",
        repo_name="acme/agentic_repo",
        repo_url="https://github.com/acme/agentic_repo",
        site_url="https://acme.github.io/agentic_repo/",
        base_path="/agentic_repo/",
        edit_uri="edit/main/docs/",
    )


def _page(
    kind: QuestionKind,
    slug: str,
    title: str,
    cited: tuple[str, ...] = ("app.py",),
) -> Page:
    return Page(
        id=make_question_id(kind, slug),
        title=title,
        summary="summary",
        body="body",
        subjects=(slug,),
        related=(),
        cited_files=cited,
    )


def _two() -> tuple[Page, Page]:
    return (
        _page(QuestionKind.STARTUP, "cli.py", "How does this program start?"),
        _page(
            QuestionKind.COMPONENT,
            "engine",
            "What does Engine do?",
            cited=("engine.py",),
        ),
    )


def _analysis() -> RepoAnalysis:
    return RepoAnalysis(
        schema_version=REPO_ANALYSIS_SCHEMA_VERSION,
        repo_path="/tmp/repo",
        languages=(),
        primary_languages=(),
        total_loc=0,
        total_files=0,
        structure=(),
        entrypoints=(Entrypoint(path="app.py", kind="cli", name="app"),),
        build_files=(),
        ci_workflows=(),
        tests=AnalysisTestLayout(present=False, frameworks=(), paths=()),
        dependencies=(),
        components=(
            Component(
                name="engine",
                path="engine",
                representative_files=("engine.py",),
            ),
        ),
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


def test_collect_is_deterministic() -> None:
    pages = _two()
    identity = _identity()
    assert collect_diagram_figures(
        pages, None, None, None, identity
    ) == collect_diagram_figures(pages, None, None, None, identity)


def test_index_embeds_mermaid_without_depth_wrap() -> None:
    pages = _two()
    figures = collect_diagram_figures(pages, None, None, None, _identity())
    assert figures
    html = render_diagrams_index(figures)
    assert html.startswith("# Diagrams\n")
    assert "```mermaid" in html
    assert "dhx-layer" not in html
    assert "data-min=" not in html
    assert "## Contents" in html
    assert f"[{pages[0].title}]({page_filename(pages[0].id)})" in html


def test_index_dedupes_identical_bodies() -> None:
    pages = _two()
    analysis = _analysis()
    figures = collect_diagram_figures(pages, analysis, None, None, _identity())
    bodies = [item.mermaid for item in figures]
    assert len(bodies) == len(set(bodies))
    headings = [item.heading for item in figures]
    assert "System context" in headings


def test_index_points_glossary_graphs_at_glossary() -> None:
    html = render_diagrams_index(
        (),
        (("Signal", "glossary.md#signal"),),
    )
    assert "glossary.md#signal" in html
    assert "## Contents" not in html or "Glossary related-term graphs" in html


def test_assemble_emits_diagrams_nav_next_to_glossary(tmp_path: Path) -> None:
    site = assemble_question_site(
        _two(),
        _identity(),
        str(tmp_path),
        analysis=_analysis(),
        counts=CoverageCounts(planned=2, accepted=2, omitted=0),
    )
    assert site is not None
    docs = Path(site.docs_dir)
    catalog = docs / DIAGRAMS_PAGE_PATH
    assert catalog.is_file()
    text = catalog.read_text(encoding="utf-8")
    assert "# Diagrams" in text
    assert "```mermaid" in text
    assert "System context" in text
    assert "Start-here path" in text
    assert "Coverage" in text
    yml = Path(site.mkdocs_yml_path).read_text(encoding="utf-8")
    diagrams_at = yml.find("Diagrams: diagrams.md")
    assert diagrams_at != -1
    glossary_at = yml.find("Glossary: glossary.md")
    if glossary_at != -1:
        assert glossary_at < diagrams_at
    compliance_at = yml.find("Compliance: compliance.md")
    if compliance_at != -1:
        assert diagrams_at < compliance_at
    for jargon in ("cobesy", "scqa", "minto"):
        assert jargon not in text.lower()


def test_empty_index_is_empty_string() -> None:
    assert render_diagrams_index(()) == ""
