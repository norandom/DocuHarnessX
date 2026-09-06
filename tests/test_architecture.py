"""Architecture-style autodetection and organizational diagrams."""

from __future__ import annotations

from pathlib import Path

from docuharnessx.analysis.model import (
    REPO_ANALYSIS_SCHEMA_VERSION,
    Artifact,
    CIWorkflow,
    Component,
    DirectorySummary,
    DocPresence,
    Entrypoint,
    PublicSymbol,
    RepoAnalysis,
    ScanStats,
)
from docuharnessx.analysis.model import TestLayout as AnalysisTestLayout
from docuharnessx.assembler.model import SiteIdentity
from docuharnessx.comprehension.architecture import (
    build_architecture_model,
    detect_architectures,
    page_abstraction,
)
from docuharnessx.comprehension.graphs import (
    collect_diagram_figures,
    render_architecture,
    render_diagrams_index,
    view_container,
    view_context,
    view_deployment,
    view_erd,
    view_sequence,
    view_style,
    view_use_case,
)
from docuharnessx.comprehension.signals import (
    ArchitectureBand,
    ArchitectureStyle,
    CoverageCounts,
)
from docuharnessx.pages.model import Page
from docuharnessx.planning.question_model import QuestionKind, make_question_id


def _analysis(*components: Component, extra: dict[str, object] | None = None) -> RepoAnalysis:
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
        "components": components,
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
    if extra:
        values.update(extra)
    return RepoAnalysis(**values)  # type: ignore[arg-type]


def _comp(name: str, path: str) -> Component:
    return Component(name=name, path=path, representative_files=())


def test_layered_needs_three_bands() -> None:
    thin = detect_architectures(
        _analysis(_comp("cli", "cli"), _comp("core", "core"))
    )
    assert all(item.id != "layered" for item in thin)
    styles = detect_architectures(
        _analysis(
            _comp("cli", "app/cli"),
            _comp("assembler", "app/assembler"),
            _comp("ontology", "app/ontology"),
            _comp("javascripts", "docs/javascripts"),
        )
    )
    layered = next(item for item in styles if item.id == "layered")
    labels = {band.id: band.members for band in layered.bands}
    assert "cli" in labels["interface"]
    assert "assembler" in labels["application"]
    assert "ontology" in labels["domain"]
    assert "javascripts" not in str(layered.bands)


def test_services_from_compose(tmp_path: Path) -> None:
    (tmp_path / "compose.yaml").write_text(
        "services:\n  api:\n    image: api\n  worker:\n    image: worker\n",
        encoding="utf-8",
    )
    styles = detect_architectures(_analysis(), str(tmp_path))
    services = next(item for item in styles if item.id == "services")
    names = [band.label for band in services.bands]
    assert names == ["api", "worker"]


def test_services_from_cmd_packages() -> None:
    styles = detect_architectures(
        _analysis(
            _comp("ingest", "cmd/ingest"),
            _comp("serve", "cmd/serve"),
        )
    )
    services = next(item for item in styles if item.id == "services")
    assert {band.label for band in services.bands} == {"ingest", "serve"}


def test_hexagonal_and_client_server() -> None:
    hexed = detect_architectures(
        _analysis(
            _comp("domain", "internal/domain"),
            _comp("http", "internal/adapters/http"),
            _comp("ports", "internal/ports"),
        )
    )
    assert any(item.id == "hexagonal" for item in hexed)
    tiers = detect_architectures(
        _analysis(_comp("web", "frontend"), _comp("api", "backend/api"))
    )
    assert any(item.id == "client_server" for item in tiers)


def test_pipeline_from_stage_directories() -> None:
    styles = detect_architectures(
        _analysis(
            extra={
                "structure": (
                    DirectorySummary(
                        path="data", file_count=1, dominant_language="Other", role="other"
                    ),
                    DirectorySummary(
                        path="features",
                        file_count=1,
                        dominant_language="Python",
                        role="source",
                    ),
                    DirectorySummary(
                        path="models",
                        file_count=1,
                        dominant_language="Python",
                        role="source",
                    ),
                )
            }
        )
    )
    pipe = next(item for item in styles if item.id == "pipeline")
    assert {band.label for band in pipe.bands} >= {"Data", "Features", "Models"}


def test_render_layered_stacks_bands() -> None:
    style = ArchitectureStyle(
        id="layered",
        label="Layered architecture",
        bands=(
            ArchitectureBand(id="interface", label="Interface", members=("cli", "mcp")),
            ArchitectureBand(
                id="application", label="Application", members=("assembler",)
            ),
            ArchitectureBand(id="domain", label="Domain", members=("analysis",)),
        ),
        evidence=("cli:interface",),
    )
    text = render_architecture(style)
    assert 'subgraph b0["Interface"]' in text
    assert "depends on" in text
    assert "javascripts" not in text


def test_empty_analysis_has_no_architecture() -> None:
    assert detect_architectures(None) == ()
    assert build_architecture_model(None) is None


def _identity() -> SiteIdentity:
    return SiteIdentity(
        site_name="agentic_repo",
        repo_name="acme/agentic_repo",
        repo_url="https://github.com/acme/agentic_repo",
        site_url="https://acme.github.io/agentic_repo/",
        base_path="/agentic_repo/",
        edit_uri="edit/main/docs/",
    )


def test_architecture_model_is_byte_stable() -> None:
    analysis = _analysis(
        _comp("cli", "app/cli"),
        _comp("assembler", "app/assembler"),
        _comp("ontology", "app/ontology"),
        extra={
            "entrypoints": (
                Entrypoint(path="app.py", kind="cli", name="app"),
            )
        },
    )
    styles = detect_architectures(analysis)
    first = build_architecture_model(analysis, _identity(), styles)
    second = build_architecture_model(analysis, _identity(), styles)
    assert first is not None
    assert first == second
    ids = {node.id for node in first.nodes}
    assert "actor:operator" in ids
    assert "system" in ids
    assert first.system_name == "agentic_repo"
    labels = {node.label for node in first.nodes}
    context = view_context(first)
    container = view_container(first)
    assert "agentic_repo" in context
    assert "Operator" in context
    assert "Operator" in container
    for label in labels:
        if label in {"Operator", "agentic_repo", "CLI"}:
            assert label in context or label in container


def _page(
    kind: QuestionKind,
    slug: str,
    title: str,
    cited: tuple[str, ...] = ("app.py",),
) -> Page:
    return Page(
        id=make_question_id(kind, slug),
        title=title,
        summary="s",
        body="b",
        subjects=(slug,),
        related=(),
        cited_files=cited,
    )


def test_page_abstraction_from_kind() -> None:
    page = _page(QuestionKind.STARTUP, "cli.py", "How does this program start?")
    assert str(page_abstraction(page)) == "context"
    module = _page(QuestionKind.COMPONENT, "engine", "What does Engine do?")
    assert str(page_abstraction(module)) == "component"
    package = _page(QuestionKind.COMPONENT, "agentic_repo", "What is agentic_repo?")
    assert str(page_abstraction(package, _identity())) == "container"


def test_model_edges_are_grounded() -> None:
    analysis = _analysis(
        _comp("cli", "app/cli"),
        _comp("assembler", "app/assembler"),
        _comp("ontology", "app/ontology"),
        extra={
            "entrypoints": (Entrypoint(path="app.py", kind="cli", name="app"),)
        },
    )
    styles = detect_architectures(analysis)
    model = build_architecture_model(analysis, _identity(), styles)
    assert model is not None
    ids = {node.id for node in model.nodes}
    for edge in model.edges:
        assert edge.source in ids
        assert edge.target in ids
        assert edge.evidence
        assert edge.source != edge.target
    verbs = {edge.verb for edge in model.edges}
    assert any(verb.startswith("runs") for verb in verbs)
    assert "depends on" in verbs


def test_views_share_node_labels() -> None:
    analysis = _analysis(
        _comp("cli", "app/cli"),
        _comp("assembler", "app/assembler"),
        _comp("ontology", "app/ontology"),
        extra={
            "entrypoints": (Entrypoint(path="app.py", kind="cli", name="app"),)
        },
    )
    model = build_architecture_model(
        analysis, _identity(), detect_architectures(analysis)
    )
    context = view_context(model)
    container = view_container(model)
    layered = view_style(model, "layered")
    sequence = view_sequence(model)
    assert "Operator" in context
    assert "Operator" in container
    assert "agentic_repo" in context
    assert "assembler" in container
    assert 'subgraph b0["Interface"]' in layered
    assert "sequenceDiagram" in sequence
    assert "Operator" in sequence
    assert "javascripts" not in container


def test_optional_views_omit_when_empty() -> None:
    thin = _analysis(_comp("core", "core"))
    assert view_use_case(thin) == ""
    assert view_erd(thin) == ""
    assert view_deployment(thin) == ""


def test_optional_views_emit_when_evidenced() -> None:
    analysis = _analysis(
        extra={
            "entrypoints": (Entrypoint(path="app.py", kind="cli", name="app"),),
            "public_surface": (
                PublicSymbol(name="run", kind="cli_subcommand", source="app.py"),
                PublicSymbol(name="init", kind="cli_subcommand", source="app.py"),
            ),
            "ci_workflows": (
                CIWorkflow(path=".github/workflows/ci.yml", provider="github_actions"),
            ),
            "artifacts": (
                Artifact(path="schema.sql", kind="schema"),
                Artifact(path="prisma/schema.prisma", kind="schema"),
                Artifact(path="Dockerfile", kind="dockerfile"),
            ),
            "docs": DocPresence(
                has_readme=True, readme_paths=("README.md",), doc_dirs=(), other_docs=()
            ),
        }
    )
    use_case = view_use_case(analysis)
    erd = view_erd(analysis)
    deploy = view_deployment(analysis)
    assert "Operator" in use_case
    assert "init" in use_case
    assert "schema" in erd
    assert "GitHub Actions" in deploy
    assert "Dockerfile" in deploy
    for jargon in ("ArchiMate", "SysML", "BPMN", "TOGAF"):
        assert jargon not in use_case
        assert jargon not in erd
        assert jargon not in deploy


def test_catalog_groups_architecture_first() -> None:
    analysis = _analysis(
        _comp("cli", "app/cli"),
        _comp("assembler", "app/assembler"),
        _comp("ontology", "app/ontology"),
        extra={
            "entrypoints": (Entrypoint(path="app.py", kind="cli", name="app"),)
        },
    )
    from docuharnessx.comprehension.detect import detect_comprehension

    pages = (
        _page(QuestionKind.STARTUP, "cli.py", "How does this program start?"),
        _page(QuestionKind.COMPONENT, "engine", "What does Engine do?", ("engine.py",)),
    )
    signals = detect_comprehension(analysis, "/tmp/repo")
    figures = collect_diagram_figures(
        pages,
        analysis,
        signals,
        CoverageCounts(planned=2, accepted=2, omitted=0),
        _identity(),
    )
    html = render_diagrams_index(figures)
    architecture = html.find("## Architecture")
    reading = html.find("## Reading path")
    coverage = html.find("## Coverage")
    per_question = html.find("## Per question")
    assert architecture != -1
    assert reading != -1
    assert coverage != -1
    assert architecture < reading < coverage
    if per_question != -1:
        assert coverage < per_question
    headings = [item.heading for item in figures if item.section == "Architecture"]
    assert "System context" in headings
    assert "Layered architecture" in headings
    assert headings.count("System context") == 1
    assert "Containers" in headings
    architecture = html.find("## Architecture")
    context_h3 = html.find('<h3 id="system-context">')
    containers_h3 = html.find('<h3 id="containers">')
    assert architecture != -1
    assert architecture < context_h3 < containers_h3
