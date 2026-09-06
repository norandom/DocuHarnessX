"""Deterministic extra diagrams. Flowchart fallbacks stay MkDocs-safe."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from docuharnessx.analysis.model import RepoAnalysis
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

if TYPE_CHECKING:
    from docuharnessx.assembler.model import SiteIdentity

__all__ = [
    "DIAGRAMS_PAGE_PATH",
    "DiagramFigure",
    "collect_diagram_figures",
    "render_compliance_page",
    "render_diagrams_index",
    "render_glossary_page",
    "render_home_extras",
    "render_page_extras",
]

DIAGRAMS_PAGE_PATH = "diagrams.md"

_SLUG = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class DiagramFigure:
    """One picture in the global diagrams catalog."""

    slug: str
    heading: str
    section: str
    source_title: str
    source_href: str
    min_depth: int
    mermaid: str


def _wrap(min_depth: int, markdown: str) -> str:
    from docuharnessx.assembler.depth import wrap_layer

    return wrap_layer(min_depth, markdown)


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


def render_story_path(pages: Sequence[Page]) -> str:
    """Small left-to-right path of the home reading list. Empty if under two pages."""
    if len(pages) < 2:
        return ""
    lines = [f'  p{index}["{_label(page.title)}"]' for index, page in enumerate(pages)]
    for index in range(len(pages) - 1):
        lines.append(f"  p{index} --> p{index + 1}")
    return _fence_flow("LR", lines)


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
    identity: "SiteIdentity | None" = None,
) -> list[tuple[int, str]]:
    blocks: list[tuple[int, str]] = []
    from docuharnessx.assembler.story import is_system_overview

    if is_system_overview(page, accepted, identity):
        context = render_c4_context(analysis)
        if context:
            blocks.append((1, context))
        else:
            mind = render_mindmap(analysis)
            if mind:
                blocks.append((1, mind))
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
    from docuharnessx.assembler.graphs import render_page_diagrams

    diagrams = render_page_diagrams(page, accepted, analysis)
    if diagrams:
        blocks.append((5, diagrams))
    return blocks


def render_home_extras(
    pages: Sequence[Page],
    analysis: RepoAnalysis | None,
    signals: ComprehensionSignals | None,
    counts: CoverageCounts | None,
    identity: "SiteIdentity | None" = None,
) -> list[tuple[int, str]]:
    """Home pictures. Depth 1 is prose (the reading path); maps start at 2."""
    blocks: list[tuple[int, str]] = []
    from docuharnessx.assembler.story import story_spine

    path = render_story_path(story_spine(pages, identity))
    if path:
        blocks.append((3, path))
    pie = render_coverage_pie(counts)
    if pie:
        blocks.append((2, pie))
    context = render_c4_context(analysis)
    if context:
        blocks.append((5, context))
    else:
        mind = render_mindmap(analysis)
        if mind:
            blocks.append((5, mind))
    from docuharnessx.assembler.graphs import render_home_diagrams

    home_map = render_home_diagrams(pages)
    if home_map:
        blocks.append((5, home_map))
    if signals and signals.lineage:
        blocks.append((5, render_sankey(signals)))
        blocks.append((7, render_sankey(signals)))
    if signals and signals.pipelines:
        blocks.append((5, render_dag(signals.pipelines[0], detailed=False)))
        blocks.append((7, render_dag(signals.pipelines[0], detailed=True)))
    return [(d, b) for d, b in blocks if b]


def _figure_slug(heading: str, used: set[str]) -> str:
    base = _SLUG.sub("-", heading.strip().casefold()).strip("-") or "diagram"
    slug = base
    index = 2
    while slug in used:
        slug = f"{base}-{index}"
        index += 1
    used.add(slug)
    return slug


def collect_diagram_figures(
    pages: Sequence[Page],
    analysis: RepoAnalysis | None,
    signals: ComprehensionSignals | None,
    counts: CoverageCounts | None,
    identity: "SiteIdentity | None" = None,
) -> tuple[DiagramFigure, ...]:
    """Unique assembled pictures for ``diagrams.md``, overview first."""
    from docuharnessx.assembler.graphs import iter_page_diagrams, render_home_diagrams
    from docuharnessx.assembler.mkdocs_config import HOME_PAGE_PATH
    from docuharnessx.assembler.pages import page_filename
    from docuharnessx.assembler.story import primary_component, story_spine

    used: set[str] = set()
    seen_bodies: set[str] = set()
    figures: list[DiagramFigure] = []

    def add(
        heading: str,
        section: str,
        source_title: str,
        source_href: str,
        min_depth: int,
        mermaid: str,
    ) -> None:
        body = mermaid.strip()
        if not body or body in seen_bodies:
            return
        seen_bodies.add(body)
        figures.append(
            DiagramFigure(
                slug=_figure_slug(heading, used),
                heading=heading,
                section=section,
                source_title=source_title,
                source_href=source_href,
                min_depth=min_depth,
                mermaid=body + "\n",
            )
        )

    primary = primary_component(pages, identity)
    context = render_c4_context(analysis) or render_mindmap(analysis)
    if context:
        if primary is not None:
            add(
                "System context",
                "System",
                primary.title,
                page_filename(primary.id),
                1,
                context,
            )
        else:
            add("System context", "System", "Home", HOME_PAGE_PATH, 5, context)

    spine = story_spine(pages, identity)
    path = render_story_path(spine)
    if path:
        add("Start-here path", "Reading path", "Home", HOME_PAGE_PATH, 3, path)

    pie = render_coverage_pie(counts)
    if pie:
        add("Coverage", "Coverage", "Home", HOME_PAGE_PATH, 2, pie)

    home_map = render_home_diagrams(pages)
    if home_map:
        add("Question map", "Reading path", "Home", HOME_PAGE_PATH, 5, home_map)

    live = signals or ComprehensionSignals()
    lineage = render_sankey(live)
    if lineage:
        add("Lineage", "Lineage", "Home", HOME_PAGE_PATH, 5, lineage)

    if live.pipelines:
        collapsed = render_dag(live.pipelines[0], detailed=False)
        if collapsed:
            add("Pipeline", "Pipeline", "Home", HOME_PAGE_PATH, 5, collapsed)
        detailed = render_dag(live.pipelines[0], detailed=True)
        if detailed:
            add("Pipeline (detailed)", "Pipeline", "Home", HOME_PAGE_PATH, 7, detailed)

    surface = render_public_surface(analysis)
    if surface:
        surface_page = next(
            (page for page in pages if page.id.startswith("public_surface:")),
            None,
        )
        if surface_page is None:
            surface_page = next(
                (page for page in pages if page.id.startswith("component:")),
                None,
            )
        if surface_page is not None:
            add(
                "Public surface",
                "Public surface",
                surface_page.title,
                page_filename(surface_page.id),
                4,
                surface,
            )
        else:
            add("Public surface", "Public surface", "Home", HOME_PAGE_PATH, 4, surface)

    for page in pages:
        href = page_filename(page.id)
        for label, fence in iter_page_diagrams(page, pages, analysis):
            add(f"{page.title} · {label}", "Per question", page.title, href, 5, fence)

    return tuple(figures)


def render_diagrams_index(
    figures: Sequence[DiagramFigure],
    glossary_links: Sequence[tuple[str, str]] = (),
) -> str:
    """Render ``diagrams.md``. Pictures are not depth-wrapped so they stay visible."""
    if not figures and not glossary_links:
        return ""
    lines = [
        "# Diagrams",
        "",
        "Every picture this site assembled, in one catalog. Each also lives on "
        "the linked page, often behind the depth slider.",
        "",
    ]
    if figures:
        lines.append("## Contents")
        lines.append("")
        for figure in figures:
            lines.append(f"- [{figure.heading}](#{figure.slug})")
        if glossary_links:
            lines.append("- [Glossary related-term graphs](#glossary-related-term-graphs)")
        lines.append("")
        current_section = ""
        for figure in figures:
            if figure.section != current_section:
                current_section = figure.section
                lines.append(f"## {figure.section}")
                lines.append("")
            lines.append(f'<h3 id="{figure.slug}">{figure.heading}</h3>')
            lines.append("")
            lines.append(
                f"On [{figure.source_title}]({figure.source_href}) "
                f"at depth {figure.min_depth}."
            )
            lines.append("")
            lines.append(figure.mermaid.rstrip("\n"))
            lines.append("")
    if glossary_links:
        lines.append('<h2 id="glossary-related-term-graphs">Glossary related-term graphs</h2>')
        lines.append("")
        lines.append("Small related-term pictures live on the glossary entries:")
        lines.append("")
        for label, href in glossary_links:
            lines.append(f"- [{label}]({href})")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_glossary_page(
    glossary: Glossary,
    appearances: dict[str, tuple[tuple[str, str], ...]] | None = None,
) -> str:
    seen = appearances or {}
    by_id = glossary.by_id()
    lines = [
        "# Glossary",
        "",
        "Highlighted words in the docs link here. Related terms are other "
        "glossary entries that appear on the same page.",
        "",
    ]
    for term in glossary.terms:
        lines.append(f'<h2 id="{term.id}">{term.label}</h2>')
        lines.append("")
        lines.append(term.definition or "_No definition in the repository yet._")
        lines.append("")
        if term.aliases:
            lines.append("Aliases: " + ", ".join(f"`{a}`" for a in term.aliases))
            lines.append("")
        related = [by_id[rid] for rid in term.related if rid in by_id]
        if related:
            lines.append(
                "Related: "
                + ", ".join(f"[{item.label}](#{item.id})" for item in related)
            )
            lines.append("")
            node_lines = [f'  here["{_label(term.label)}"]']
            for index, item in enumerate(related[:8]):
                nid = f"r{index}"
                node_lines.append(f'  {nid}["{_label(item.label)}"]')
                node_lines.append(f"  here --> {nid}")
            lines.append("```mermaid")
            lines.append("flowchart LR")
            lines.extend(node_lines)
            lines.append("```")
            lines.append("")
        hits = seen.get(term.id, ())
        if hits:
            lines.append("Appears on:")
            lines.append("")
            for title, href in hits[:12]:
                lines.append(f"- [{title}]({href})")
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
        _wrap(
            1,
            _matrix_markdown(in_scope, cells, labels, css, mark),
        ),
        "",
        _wrap(5, _evidence_markdown(in_scope, cells, labels)),
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
