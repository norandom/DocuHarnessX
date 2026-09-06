"""Feature validation for architect-narrative (tasks 6.1–6.2)."""

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
from docuharnessx.assembler.methodology import suppress_methodology_labels
from docuharnessx.assembler.model import SiteIdentity
from docuharnessx.assembler.pages import page_filename, render_question_page
from docuharnessx.assembler.question_site import assemble_question_site
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
    *,
    summary: str = "Engine loads config and runs a cycle.",
    body: str = "Engine drives a bounded work cycle.\n",
    cited: tuple[str, ...] = ("engine.py",),
) -> Page:
    return Page(
        id=make_question_id(kind, slug),
        title=title,
        summary=summary,
        body=body,
        subjects=(slug,),
        related=(),
        cited_files=cited,
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
            Component(name="cli", path="app/cli", representative_files=()),
            Component(name="assembler", path="app/assembler", representative_files=()),
            Component(name="ontology", path="app/ontology", representative_files=()),
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


def _depth_one_chunks(markdown: str) -> list[str]:
    parts = markdown.split('class="dhx-layer"')
    chunks: list[str] = []
    for part in parts[1:]:
        header, _, rest = part.partition(">")
        if 'data-min="1"' not in header:
            continue
        chunks.append(rest.split("</div>", 1)[0])
    return chunks


def test_suppress_methodology_labels_is_byte_stable() -> None:
    text = "A COBESY-structured SCQA opener with a Minto lead and andragogy (`_build_scqa`)."
    assert suppress_methodology_labels(text) == suppress_methodology_labels(text)
    cleaned = suppress_methodology_labels(text)
    lowered = cleaned.lower()
    for word in ("scqa", "minto", "cobesy", "andragogy"):
        assert word not in lowered
    assert "structured" in cleaned
    assert "opener" in cleaned


def test_home_depth_one_is_a_story_not_a_file_star(tmp_path: Path) -> None:
    pages = (
        _page(QuestionKind.STARTUP, "cli.py", "How does this program start?"),
        _page(QuestionKind.COMPONENT, "agentic_repo", "What does agentic_repo do?"),
    )
    site = assemble_question_site(
        pages, _identity(), str(tmp_path), analysis=_analysis()
    )
    assert site is not None
    home = Path(site.docs_dir, "index.md").read_text(encoding="utf-8")
    depth_one = "\n".join(_depth_one_chunks(home))
    assert "Read in this order" in depth_one
    assert "How does this program start?" in depth_one
    assert "dhx-jit" in depth_one
    assert "```mermaid" not in depth_one
    assert 'n0["' not in depth_one


def test_package_page_depth_one_has_model_view_not_file_star(tmp_path: Path) -> None:
    pages = (
        _page(QuestionKind.STARTUP, "cli.py", "How does this program start?"),
        _page(QuestionKind.COMPONENT, "agentic_repo", "What does agentic_repo do?"),
    )
    site = assemble_question_site(
        pages, _identity(), str(tmp_path), analysis=_analysis()
    )
    assert site is not None
    package = Path(
        site.docs_dir, page_filename(pages[1].id)
    ).read_text(encoding="utf-8")
    depth_one = "\n".join(_depth_one_chunks(package))
    assert "dhx-jit" in depth_one
    assert "Operator" in depth_one
    assert "agentic_repo" in depth_one
    assert "This system" in package
    assert "Engine loads config" in depth_one
    assert 'n0["' not in depth_one
    assert "engine.py" not in depth_one
    assert 'data-min="5"' in package
    assert "Engine drives a bounded work cycle." in package


def test_published_pages_omit_methodology_names(tmp_path: Path) -> None:
    living = _page(
        QuestionKind.COMPONENT,
        "composition",
        "What does composition do?",
        summary="Composition writes grounded pages.",
        body=(
            "The package is a COBESY composition core with an SCQA opener, "
            "a Minto lead, and andragogy (`composition/blueprint.py:1`).\n"
        ),
        cited=("composition/blueprint.py",),
    )
    site = assemble_question_site(
        (living,), _identity(), str(tmp_path), analysis=_analysis()
    )
    assert site is not None
    published = Path(
        site.docs_dir, page_filename(living.id)
    ).read_text(encoding="utf-8")
    lowered = published.lower()
    for word in ("scqa", "minto", "cobesy", "andragogy"):
        assert word not in lowered
    assert living.body != published
    assert "composition core" in published
    _path, raw = render_question_page(living, (living,), include_diagrams=False)
    assert "COBESY" in raw
