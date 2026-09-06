"""JIT Hypertree JSON from the architecture model."""

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
from docuharnessx.assembler.jit import load_jit_javascript, render_conceptual_js
from docuharnessx.assembler.model import SiteIdentity
from docuharnessx.assembler.question_site import assemble_question_site
from docuharnessx.comprehension.architecture import (
    build_architecture_model,
    detect_architectures,
)
from docuharnessx.comprehension.jit import conceptual_tree, render_conceptual_hypertree
from docuharnessx.pages.model import Page
from docuharnessx.planning.question_model import QuestionKind, make_question_id


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


def _identity() -> SiteIdentity:
    return SiteIdentity(
        site_name="agentic_repo",
        repo_name="acme/agentic_repo",
        repo_url="https://github.com/acme/agentic_repo",
        site_url="https://acme.github.io/agentic_repo/",
        base_path="/agentic_repo/",
        edit_uri="edit/main/docs/",
    )


def test_conceptual_tree_is_byte_stable_and_system_rooted() -> None:
    analysis = _analysis()
    model = build_architecture_model(
        analysis, _identity(), detect_architectures(analysis)
    )
    first = conceptual_tree(model)
    second = conceptual_tree(model)
    assert first == second
    assert first is not None
    assert first["id"] == "system"
    assert first["name"] == "agentic_repo"
    names = {child["name"] for child in first["children"]}
    assert "People" in names
    assert "Interface" in names or "CLI" in names
    html = render_conceptual_hypertree(model)
    assert "dhx-jit-conceptual" in html
    assert "dhx-jit__data" in html
    assert "agentic_repo" in html
    assert render_conceptual_hypertree(None) == ""


def test_empty_model_has_no_hypertree() -> None:
    assert conceptual_tree(None) is None


def test_assemble_ships_jit_and_hypertree(tmp_path: Path) -> None:
    pages = (
        Page(
            id=make_question_id(QuestionKind.STARTUP, "cli.py"),
            title="How does this program start?",
            summary="s",
            body="b",
            subjects=("cli.py",),
            related=(),
            cited_files=("app.py",),
        ),
        Page(
            id=make_question_id(QuestionKind.COMPONENT, "agentic_repo"),
            title="What does agentic_repo do?",
            summary="s",
            body="b",
            subjects=("agentic_repo",),
            related=(),
            cited_files=("app.py",),
        ),
    )
    site = assemble_question_site(
        pages, _identity(), str(tmp_path), analysis=_analysis()
    )
    assert site is not None
    docs = Path(site.docs_dir)
    jit = docs / "javascripts" / "jit.js"
    assert jit.is_file()
    text = jit.read_text(encoding="utf-8")
    assert "Nicolas Garcia Belmonte" in text
    assert "$jit" in text
    assert (docs / "javascripts" / "conceptual.js").is_file()
    yml = Path(site.mkdocs_yml_path).read_text(encoding="utf-8")
    assert "javascripts/jit.js" in yml
    assert "javascripts/conceptual.js" in yml
    matches = list(docs.glob("component-agentic-repo-*.md"))
    assert matches
    body = matches[0].read_text(encoding="utf-8")
    assert "dhx-jit-conceptual" in body
    assert "$jit.Hypertree" in render_conceptual_js()
    assert load_jit_javascript().startswith("/*")
