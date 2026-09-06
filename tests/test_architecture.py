"""Architecture-style autodetection and organizational diagrams."""

from __future__ import annotations

from pathlib import Path

from docuharnessx.analysis.model import (
    REPO_ANALYSIS_SCHEMA_VERSION,
    Component,
    DirectorySummary,
    DocPresence,
    Entrypoint,
    RepoAnalysis,
    ScanStats,
)
from docuharnessx.analysis.model import TestLayout as AnalysisTestLayout
from docuharnessx.comprehension.architecture import detect_architectures
from docuharnessx.comprehension.graphs import render_architecture
from docuharnessx.comprehension.signals import ArchitectureBand, ArchitectureStyle


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
