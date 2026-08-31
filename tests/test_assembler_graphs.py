"""Deterministic Mermaid companions for question pages."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from docuharnessx.analysis.model import (
    REPO_ANALYSIS_SCHEMA_VERSION,
    Component,
    DocPresence,
    Entrypoint,
    PublicSymbol,
    RepoAnalysis,
    ScanStats,
)
from docuharnessx.analysis.model import TestLayout as AnalysisTestLayout
from docuharnessx.assembler.graphs import render_home_diagrams, render_page_diagrams
from docuharnessx.assembler.home import render_question_home
from docuharnessx.assembler.model import SiteIdentity
from docuharnessx.assembler.pages import render_question_page
from docuharnessx.assembler.question_site import assemble_question_site
from docuharnessx.pages.model import Page
from docuharnessx.planning.question_model import QuestionKind, make_question_id


def _page(
    *,
    kind: QuestionKind = QuestionKind.STARTUP,
    slug: str = "cli.py",
    title: str = "How does this program start?",
    related: tuple[str, ...] = (),
    cited: tuple[str, ...] = ("docuharnessx/cli.py", "pyproject.toml"),
) -> Page:
    return Page(
        id=make_question_id(kind, slug),
        title=title,
        summary="summary",
        body="The CLI starts in `docuharnessx/cli.py:1`.\n",
        subjects=(slug,),
        related=related,
        cited_files=cited,
    )


def _identity() -> SiteIdentity:
    return SiteIdentity(
        site_name="agentic_repo",
        repo_name="acme/agentic_repo",
        repo_url="https://github.com/acme/agentic_repo",
        site_url="https://acme.github.io/agentic_repo/",
        base_path="/agentic_repo/",
        edit_uri="edit/main/docs/",
    )


def _empty_analysis(**overrides: object) -> RepoAnalysis:
    values: dict[str, object] = {
        "schema_version": REPO_ANALYSIS_SCHEMA_VERSION,
        "repo_path": "/tmp/repo",
        "languages": (),
        "primary_languages": (),
        "total_loc": 0,
        "total_files": 0,
        "structure": (),
        "entrypoints": (),
        "build_files": (),
        "ci_workflows": (),
        "tests": AnalysisTestLayout(present=False, frameworks=(), paths=()),
        "dependencies": (),
        "components": (),
        "public_surface": (),
        "docs": DocPresence(
            has_readme=False, readme_paths=(), doc_dirs=(), other_docs=()
        ),
        "artifacts": (),
        "scan_stats": ScanStats(
            files_scanned=0,
            files_skipped=0,
            bytes_scanned=0,
            limit_reached=False,
            notes=(),
        ),
    }
    values.update(overrides)
    return RepoAnalysis(**values)  # type: ignore[arg-type]


def test_page_diagrams_are_mermaid_flowcharts() -> None:
    page = _page()
    text = render_page_diagrams(page, (page,))
    assert text.startswith("```mermaid\nflowchart ")
    assert "```\n" in text
    assert "cli.py" in text
    assert "How does this program start?" in text


def test_page_diagrams_are_deterministic() -> None:
    page = _page()
    accepted = (page,)
    assert render_page_diagrams(page, accepted) == render_page_diagrams(page, accepted)


def test_related_pages_appear_on_glance_graph() -> None:
    other = _page(
        kind=QuestionKind.COMPONENT,
        slug="engine",
        title="What does Engine do?",
        cited=("engine.py",),
    )
    page = _page(related=(other.id,))
    text = render_page_diagrams(page, (page, other))
    assert "What does Engine do?" in text


def test_quotes_and_brackets_are_stripped_from_labels() -> None:
    page = _page(title='How does "this" [start]?')
    text = render_page_diagrams(page, (page,))
    assert "[start]" not in text
    assert "How does 'this' (start)?" in text


def test_startup_uses_entrypoints_when_analysis_present() -> None:
    page = _page()
    analysis = _empty_analysis(
        entrypoints=(
            Entrypoint(path="docuharnessx/cli.py", kind="cli", name="dhx"),
        )
    )
    text = render_page_diagrams(page, (page,), analysis)
    assert "dhx" in text


def test_component_uses_representative_files() -> None:
    page = _page(
        kind=QuestionKind.COMPONENT,
        slug="assembler",
        title="What does assembler do?",
        cited=("docuharnessx/assembler/pages.py",),
    )
    analysis = _empty_analysis(
        components=(
            Component(
                name="assembler",
                path="docuharnessx/assembler",
                representative_files=("docuharnessx/assembler/pages.py",),
            ),
        )
    )
    text = render_page_diagrams(page, (page,), analysis)
    assert "assembler" in text
    assert "pages.py" in text


def test_public_surface_lists_symbols() -> None:
    page = _page(
        kind=QuestionKind.PUBLIC_SURFACE,
        slug="init.py",
        title="How is the public surface used or extended?",
        cited=("docuharnessx/__init__.py",),
    )
    analysis = _empty_analysis(
        public_surface=(
            PublicSymbol(
                name="dhx",
                kind="cli_subcommand",
                source="docuharnessx/__init__.py",
            ),
        )
    )
    text = render_page_diagrams(page, (page,), analysis)
    assert "dhx" in text


def test_evidence_groups_files_by_directory() -> None:
    page = _page(
        cited=("docuharnessx/cli.py", "tests/test_cli.py"),
    )
    text = render_page_diagrams(page, (page,))
    assert "subgraph" in text
    assert "docuharnessx" in text
    assert "tests" in text


def test_empty_page_emits_no_diagrams() -> None:
    page = _page(cited=(), related=())
    assert render_page_diagrams(page, (page,)) == ""


def test_published_page_puts_mermaid_before_prose() -> None:
    page = _page()
    _path, markdown = render_question_page(page, (page,))
    heading_at = markdown.find(f"# {page.title}")
    mermaid_at = markdown.find("```mermaid")
    body_at = markdown.find(page.body.strip())
    assert heading_at != -1
    assert mermaid_at != -1
    assert body_at != -1
    assert heading_at < mermaid_at < body_at


def test_persisted_page_can_omit_diagrams() -> None:
    page = _page()
    _path, markdown = render_question_page(page, (page,), include_diagrams=False)
    assert "```mermaid" not in markdown
    assert page.body in markdown


def test_home_diagram_lists_questions_before_index() -> None:
    pages = (
        _page(),
        _page(
            kind=QuestionKind.COMPONENT,
            slug="engine",
            title="What does Engine do?",
            cited=("engine.py",),
        ),
    )
    home = render_question_home(_identity(), pages)
    assert home.startswith("# agentic_repo\n")
    assert home.index("```mermaid") < home.index("## Questions")
    assert "How does this program start?" in home
    assert "What does Engine do?" in home


def test_home_diagrams_helper_is_deterministic() -> None:
    pages = (_page(),)
    assert render_home_diagrams(pages) == render_home_diagrams(pages)


def test_question_site_with_graphs_builds_strict(tmp_path: Path) -> None:
    pytest.importorskip("mkdocs")
    pytest.importorskip("material")
    pages = (
        _page(),
        _page(
            kind=QuestionKind.COMPONENT,
            slug="engine",
            title="What does Engine do?",
            related=(),
            cited=("engine.py", "config.py"),
        ),
    )
    site = assemble_question_site(pages, _identity(), str(tmp_path))
    assert site is not None
    built = tmp_path / "_built"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "mkdocs",
            "build",
            "-f",
            site.mkdocs_yml_path,
            "-d",
            str(built),
            "--strict",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    html = (built / "index.html").read_text(encoding="utf-8")
    assert "mermaid" in html
