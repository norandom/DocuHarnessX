"""Deterministic extra diagrams. Flowchart fallbacks stay MkDocs-safe."""

from __future__ import annotations

from collections.abc import Sequence

from docuharnessx.analysis.model import RepoAnalysis
from docuharnessx.assembler.depth import wrap_layer
from docuharnessx.assembler.graphs import render_home_diagrams, render_page_diagrams
from docuharnessx.comprehension.compliance import (
    PILLARS,
    ComplianceCell,
    ComplianceSelection,
)
from docuharnessx.comprehension.glossary import Glossary
from docuharnessx.comprehension.signals import (
    ComprehensionSignals,
    CoverageCounts,
    PipelineDag,
)
from docuharnessx.pages.model import Page

__all__ = [
    "render_compliance_page",
    "render_glossary_page",
    "render_home_extras",
    "render_page_extras",
]


def _fence_flow(direction: str, lines: Sequence[str]) -> str:
    body = "\n".join(lines)
    return f"```mermaid\nflowchart {direction}\n{body}\n```\n"


def _label(text: str, limit: int = 36) -> str:
    cleaned = " ".join(text.split()).replace('"', "'")[:limit]
    return cleaned or "?"


def render_c4_context(analysis: RepoAnalysis | None) -> str:
    if analysis is None or not (analysis.entrypoints or analysis.components):
        return ""
    lines = ['  system["System"]']
    for index, entry in enumerate(analysis.entrypoints[:6]):
        nid = f"e{index}"
        lines.append(f'  {nid}["{_label(entry.name or entry.path)}"]')
        lines.append(f"  {nid} --> system")
    for index, component in enumerate(analysis.components[:6]):
        nid = f"c{index}"
        lines.append(f'  {nid}["{_label(component.name)}"]')
        lines.append(f"  system --> {nid}")
    return _fence_flow("TB", lines)


def render_mindmap(analysis: RepoAnalysis | None) -> str:
    if analysis is None or not analysis.components:
        return ""
    lines = ["  root((System))"]
    for component in analysis.components[:8]:
        lines.append(f"    { _label(component.name, 24) }")
    return "```mermaid\nmindmap\n" + "\n".join(lines) + "\n```\n"


def render_sequence(analysis: RepoAnalysis | None) -> str:
    if analysis is None or not analysis.entrypoints:
        return ""
    actors = ["User"] + [
        _label(e.name or e.path, 20).replace(" ", "_")
        for e in analysis.entrypoints[:4]
    ]
    lines = [f"  participant {name}" for name in actors]
    prev = actors[0]
    for name in actors[1:]:
        lines.append(f"  {prev}->>{name}: invoke")
        prev = name
    if analysis.components:
        last = _label(analysis.components[0].name, 20).replace(" ", "_")
        lines.append(f"  participant {last}")
        lines.append(f"  {prev}->>{last}: work")
    return "```mermaid\nsequenceDiagram\n" + "\n".join(lines) + "\n```\n"


def render_sankey(signals: ComprehensionSignals) -> str:
    if not signals.lineage:
        return ""
    lines = ["%% structural counts, not measured volume"]
    for hop in signals.lineage[:24]:
        src = hop.source.replace(",", " ")
        dst = hop.target.replace(",", " ")
        lines.append(f"{src},{dst},{max(1, hop.weight)}")
    # Flowchart fallback (Material mermaid may not ship sankey-beta).
    flow = []
    for index, hop in enumerate(signals.lineage[:24]):
        a = f"s{index}"
        b = f"t{index}"
        flow.append(f'  {a}["{_label(hop.source)}"]')
        flow.append(f'  {b}["{_label(hop.target)}"]')
        flow.append(f"  {a} -->|{hop.weight}| {b}")
    return _fence_flow("LR", flow)


def render_dag(dag: PipelineDag, *, detailed: bool) -> str:
    nodes = dag.nodes if detailed else dag.nodes[:12]
    allowed = {node.id for node in nodes}
    lines = [f'  {node.id}["{_label(node.label)}"]' for node in nodes]
    for src, dst in dag.edges:
        if src in allowed and dst in allowed:
            lines.append(f"  {src} --> {dst}")
    if len(lines) < 2:
        return ""
    return _fence_flow("LR", lines)


def render_public_surface(analysis: RepoAnalysis | None) -> str:
    if analysis is None or not analysis.public_surface:
        return ""
    lines = ['  api["Public surface"]']
    for index, symbol in enumerate(analysis.public_surface[:12]):
        nid = f"p{index}"
        lines.append(f'  {nid}["{_label(symbol.name)}"]')
        lines.append(f"  api --> {nid}")
    return _fence_flow("TB", lines)


def render_coverage_pie(counts: CoverageCounts | None) -> str:
    if counts is None or counts.planned == 0:
        return ""
    lines = [
        f'  accepted["accepted {counts.accepted}"]',
        f'  omitted["omitted {counts.omitted}"]',
        f'  planned["planned {counts.planned}"]',
        "  planned --> accepted",
        "  planned --> omitted",
    ]
    return _fence_flow("TB", lines)


def render_page_extras(
    page: Page,
    accepted: Sequence[Page],
    analysis: RepoAnalysis | None,
    signals: ComprehensionSignals | None,
) -> list[tuple[int, str]]:
    blocks: list[tuple[int, str]] = []
    if analysis is not None and page.id.startswith("how:"):
        seq = render_sequence(analysis)
        if seq:
            blocks.append((3, seq))
        sankey = render_sankey(signals or ComprehensionSignals())
        if sankey:
            blocks.append((3, sankey))
        if signals and signals.pipelines:
            collapsed = render_dag(signals.pipelines[0], detailed=False)
            if collapsed:
                blocks.append((3, collapsed))
            detailed = render_dag(signals.pipelines[0], detailed=True)
            if detailed:
                blocks.append((4, detailed))
    if analysis is not None and (
        page.id.startswith("component:") or page.id.startswith("how:") is False
    ):
        surface = render_public_surface(analysis)
        if surface and (
            "surface" in page.id or page.id.startswith("component:")
        ):
            blocks.append((4, surface))
    diagrams = render_page_diagrams(page, accepted, analysis)
    if diagrams:
        blocks.append((5, diagrams))
    return blocks


def render_home_extras(
    pages: Sequence[Page],
    analysis: RepoAnalysis | None,
    signals: ComprehensionSignals | None,
    counts: CoverageCounts | None,
) -> list[tuple[int, str]]:
    blocks: list[tuple[int, str]] = []
    context = render_c4_context(analysis)
    if context:
        blocks.append((1, context))
    else:
        mind = render_mindmap(analysis)
        if mind:
            blocks.append((1, mind))
    pie = render_coverage_pie(counts)
    if pie:
        blocks.append((2, pie))
    home_map = render_home_diagrams(pages)
    if home_map:
        blocks.append((3, home_map))
    if signals and signals.lineage:
        blocks.append((3, render_sankey(signals)))
        blocks.append((7, render_sankey(signals)))
    if signals and signals.pipelines:
        blocks.append((3, render_dag(signals.pipelines[0], detailed=False)))
        blocks.append((5, render_dag(signals.pipelines[0], detailed=True)))
    return [(d, b) for d, b in blocks if b]


def render_glossary_page(glossary: Glossary) -> str:
    lines = [
        "# Glossary",
        "",
        "Project terms. Highlighted words in the docs link here.",
        "",
    ]
    for term in glossary.terms:
        lines.append(f'<h2 id="{term.id}">{term.label}</h2>')
        lines.append("")
        lines.append(term.definition or "_undefined_")
        lines.append("")
        if term.aliases:
            lines.append("Aliases: " + ", ".join(term.aliases))
            lines.append("")
        if term.related:
            lines.append(
                "Related: "
                + ", ".join(f"[{rid}](#{rid})" for rid in term.related)
            )
            lines.append("")
        if term.sources:
            lines.append("Sources: " + ", ".join(f"`{s}`" for s in term.sources[:8]))
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_compliance_page(
    selection: ComplianceSelection,
    cells: Sequence[ComplianceCell],
) -> str:
    labels = {pid: label for pid, label, _applies in PILLARS}
    css = {
        "na": "dhx-na",
        "fail": "dhx-fail",
        "partial": "dhx-partial",
        "pass": "dhx-pass",
    }
    mark = {"na": "n/a", "fail": "red", "partial": "yellow", "pass": "green"}
    in_scope = list(selection.frameworks)
    lines = [
        "# Compliance self-assessment",
        "",
        "This matrix is a **self-assessment reference**, not a certification "
        "or auditor opinion.",
        "",
        wrap_layer(
            1,
            _matrix_markdown(in_scope, cells, labels, css, mark),
        ),
        "",
        wrap_layer(5, _evidence_markdown(in_scope, cells, labels)),
        "",
    ]
    return "\n".join(part for part in lines if part is not None).replace("\n\n\n", "\n\n")


def _matrix_markdown(
    frameworks: Sequence[str],
    cells: Sequence[ComplianceCell],
    labels: dict[str, str],
    css: dict[str, str],
    mark: dict[str, str],
) -> str:
    if not frameworks:
        return ""
    header = "| Pillar | " + " | ".join(frameworks) + " |"
    sep = "|---|" + "|".join("---" for _ in frameworks) + "|"
    rows = [header, sep]
    by = {(c.framework, c.pillar): c for c in cells}
    for pillar_id, label, _applies in PILLARS:
        cols = []
        for fw in frameworks:
            cell = by.get((fw, pillar_id))
            status = cell.status if cell else "na"
            cols.append(f'<span class="{css[status]}">{mark[status]}</span>')
        rows.append("| " + label + " | " + " | ".join(cols) + " |")
    return "\n".join(rows)


def _evidence_markdown(
    frameworks: Sequence[str],
    cells: Sequence[ComplianceCell],
    labels: dict[str, str],
) -> str:
    lines = ["## Evidence", ""]
    any_hit = False
    for cell in cells:
        if cell.framework not in frameworks or cell.status == "na":
            continue
        if not cell.evidence:
            continue
        any_hit = True
        note = " (override)" if cell.overridden else ""
        lines.append(
            f"- **{cell.framework} / {labels.get(cell.pillar, cell.pillar)}** "
            f"{cell.status}{note}: "
            + ", ".join(f"`{p}`" for p in cell.evidence[:6])
        )
    if not any_hit:
        return "_No automated evidence paths recorded._"
    return "\n".join(lines)
