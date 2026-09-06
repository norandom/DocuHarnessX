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


_SKIP_COMPONENT_NAMES = frozenset(
    {"javascripts", "stylesheets", "static", "assets", "css", "js"}
)
_CI_LABELS = {
    "github_actions": "GitHub Actions",
    "gitlab_ci": "GitLab CI",
    "circleci": "CircleCI",
    "dagger": "Dagger",
}
_STYLE_LINES = (
    "  classDef actor fill:#0F172A,stroke:#020617,color:#FFFFFF",
    "  classDef system fill:#1E3A8A,stroke:#1E3A8A,color:#FFFFFF",
    "  classDef container fill:#EEF2FF,stroke:#1E3A8A,color:#0F172A",
    "  classDef external fill:#F8FAFC,stroke:#64748B,color:#0F172A",
    "  classDef store fill:#E2E8F0,stroke:#334155,color:#0F172A",
)


def _fence(header: str, lines: Sequence[str]) -> str:
    body = "\n".join(line for line in lines if line is not None)
    return f"```mermaid\n{header}\n{body}\n```\n"


def _fence_flow(direction: str, lines: Sequence[str], *, styled: bool = False) -> str:
    body = list(lines)
    if styled:
        body.extend(_STYLE_LINES)
    return _fence(f"flowchart {direction}", body)


def _label(text: str, limit: int = 42) -> str:
    cleaned = " ".join(text.split()).replace('"', "'")
    for src, dst in (("[", "("), ("]", ")"), ("{", "("), ("}", ")")):
        cleaned = cleaned.replace(src, dst)
    if len(cleaned) > limit:
        cleaned = cleaned[: limit - 1] + "…"
    return cleaned or "?"


def _basename(path: str) -> str:
    return path.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]


def _ident(prefix: str, raw: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]", "", raw)[:18] or "x"
    if slug[0].isdigit():
        slug = "n" + slug
    return f"{prefix}{slug}"


def _is_noise_component(name: str, path: str = "") -> bool:
    token = name.casefold().rsplit("/", 1)[-1]
    rel = path.replace("\\", "/").casefold()
    if token in _SKIP_COMPONENT_NAMES:
        return True
    if rel.startswith("docs/") or "/javascripts" in rel or "/stylesheets" in rel:
        return True
    return False


def _real_components(analysis: RepoAnalysis):
    return [
        item
        for item in analysis.components
        if not _is_noise_component(item.name, item.path)
    ]


def _system_name(
    analysis: RepoAnalysis | None,
    identity: "SiteIdentity | None",
) -> str:
    if identity is not None and identity.site_name:
        return identity.site_name
    if analysis is not None and analysis.components:
        real = _real_components(analysis)
        if real:
            return real[0].name
    return "System"


def _cli_name(analysis: RepoAnalysis) -> str:
    for entry in analysis.entrypoints:
        if entry.name:
            return entry.name
    commands = [
        symbol.name
        for symbol in analysis.public_surface
        if symbol.kind == "cli_subcommand" and symbol.name and symbol.name != "run"
    ]
    for entry in analysis.entrypoints:
        if entry.kind in {"cli", "console_script", "main"}:
            base = _basename(entry.path)
            if base in {"cli.py", "cli", "__main__.py", "main.py"}:
                return "CLI"
            return base or "CLI"
    if commands:
        return "CLI"
    if analysis.entrypoints:
        return _basename(analysis.entrypoints[0].path) or "entrypoint"
    return "CLI"


def _system_blurb(analysis: RepoAnalysis) -> str:
    cli = _cli_name(analysis) if analysis.entrypoints else ""
    if any(e.kind in {"cli", "console_script", "main"} for e in analysis.entrypoints):
        return f"Command-line program ({cli})"
    if analysis.entrypoints:
        return "Runnable program"
    return "Software system"


def _actor_label(analysis: RepoAnalysis) -> str:
    kinds = {entry.kind for entry in analysis.entrypoints}
    if kinds & {"cli", "console_script", "main", "script", "package_bin"}:
        return "Operator"
    return "User"


def render_c4_context(
    analysis: RepoAnalysis | None,
    identity: "SiteIdentity | None" = None,
) -> str:
    """System-context view: people, this system, evidenced externals."""
    if analysis is None or not (analysis.entrypoints or analysis.components):
        return ""
    name = _system_name(analysis, identity)
    blurb = _system_blurb(analysis)
    actor = _actor_label(analysis)
    cli = _cli_name(analysis) if analysis.entrypoints else ""
    lines = [
        '  subgraph people["People"]',
        f'    actor(["{_label(actor)}"])',
        "  end",
        f'  subgraph enterprise["This system"]',
        f'    sys["{_label(name)}<br/>{_label(blurb, 40)}"]',
        "  end",
    ]
    externals: list[tuple[str, str, str]] = []
    ext_nodes: list[str] = []
    repo = ""
    if identity is not None:
        repo = identity.repo_name or identity.site_name
    if not repo and analysis.repo_path:
        repo = _basename(analysis.repo_path)
    if repo:
        ext_nodes.append(f'    repo[("{_label(repo)}")]')
        externals.append(("repo", "store", "reads and cites"))
    if analysis.ci_workflows:
        provider = analysis.ci_workflows[0].provider
        ci_label = _CI_LABELS.get(provider, "CI")
        ext_nodes.append(f'    ci["{_label(ci_label)}"]')
        externals.append(("ci", "external", "runs in"))
    if analysis.docs.doc_dirs or analysis.docs.has_readme:
        ext_nodes.append('    docs[("Documentation site")]')
        externals.append(("docs", "store", "publishes"))
    if ext_nodes:
        lines.append('  subgraph external["External"]')
        lines.extend(ext_nodes)
        lines.append("  end")
    run_label = f"runs {cli}" if cli else "runs"
    lines.append(f'  actor -->|"{_label(run_label, 24)}"| sys')
    for nid, _kind, verb in externals:
        if nid == "ci":
            lines.append(f'  ci -->|"{_label(verb, 24)}"| sys')
        else:
            lines.append(f'  sys -->|"{_label(verb, 24)}"| {nid}')
    lines.append("  class actor actor")
    lines.append("  class sys system")
    classed = [nid for nid, kind, _verb in externals if kind == "store"]
    if classed:
        lines.append("  class " + ",".join(classed) + " store")
    ext_ids = [nid for nid, kind, _verb in externals if kind == "external"]
    if ext_ids:
        lines.append("  class " + ",".join(ext_ids) + " external")
    return _fence_flow("TB", lines, styled=True)


def render_c4_container(
    analysis: RepoAnalysis | None,
    identity: "SiteIdentity | None" = None,
    signals: ComprehensionSignals | None = None,
) -> str:
    """Container view: CLI and modules inside the system boundary."""
    if analysis is None:
        return ""
    components = _real_components(analysis)[:8]
    if not (analysis.entrypoints or components):
        return ""
    name = _system_name(analysis, identity)
    lines = [f'  subgraph sys["{_label(name)}"]']
    classed = ["sysbox"]
    if analysis.entrypoints:
        cli_name = _cli_name(analysis)
        cli_label = "CLI" if cli_name == "CLI" else f"CLI · {_label(cli_name, 20)}"
        lines.append(f'    cli["{cli_label}"]')
        classed.append("cli")
    for index, component in enumerate(components):
        nid = f"c{index}"
        lines.append(f'    {nid}["{_label(component.name, 24)}"]')
        classed.append(nid)
    lines.append("  end")
    if analysis.entrypoints:
        lines.append(f'  actor(["{_label(_actor_label(analysis))}"])')
        lines.append(f'  actor -->|"{_label("runs " + _cli_name(analysis), 24)}"| cli')
        lines.append("  class actor actor")
    dag_edges: list[tuple[str, str]] = []
    if signals and signals.pipelines:
        label_to_id = {component.name: f"c{index}" for index, component in enumerate(components)}
        if analysis.entrypoints:
            label_to_id[_cli_name(analysis)] = "cli"
            for entry in analysis.entrypoints:
                if entry.name:
                    label_to_id[entry.name] = "cli"
                label_to_id[entry.path] = "cli"
                label_to_id[_basename(entry.path)] = "cli"
        for src, dst in signals.pipelines[0].edges:
            left = label_to_id.get(src)
            right = label_to_id.get(dst)
            if left and right and left != right:
                dag_edges.append((left, right))
    if dag_edges:
        for src, dst in dict.fromkeys(dag_edges):
            lines.append(f"  {src} --> {dst}")
    elif analysis.entrypoints:
        for index, _component in enumerate(components):
            lines.append(f'  cli -->|uses| c{index}')
    elif len(components) > 1:
        for index in range(len(components) - 1):
            lines.append(f"  c{index} --> c{index + 1}")
    styled_ids = [item for item in classed if item != "sysbox"]
    if styled_ids:
        lines.append("  class " + ",".join(styled_ids) + " container")
    return _fence_flow("TB", lines, styled=True)


def render_mindmap(analysis: RepoAnalysis | None) -> str:
    if analysis is None:
        return ""
    components = _real_components(analysis)[:8]
    if not components:
        return ""
    lines = ["  root((System))"]
    for component in components:
        lines.append(f"    {_label(component.name, 24)}")
    return _fence("mindmap", lines)


def render_sequence(
    analysis: RepoAnalysis | None,
    identity: "SiteIdentity | None" = None,
) -> str:
    """Typical run: operator through the CLI into the main modules."""
    if analysis is None or not analysis.entrypoints:
        return ""
    cli = _cli_name(analysis)
    actor = _actor_label(analysis)
    root = _system_name(analysis, identity).casefold()
    components = [
        item
        for item in _real_components(analysis)
        if item.name.casefold() not in {root, cli.casefold(), "cli"}
    ][:4]
    participants = ["  autonumber", f"  actor {actor}"]
    cli_id = _ident("p", cli)
    participants.append(f"  participant {cli_id} as {_label(cli, 20)}")
    comp_ids: list[str] = []
    for component in components:
        cid = _ident("p", component.name)
        if cid == cli_id:
            continue
        participants.append(f"  participant {cid} as {_label(component.name, 20)}")
        comp_ids.append(cid)
    messages = [f"  {actor}->>{cli_id}: run"]
    for cid in comp_ids:
        messages.append(f"  {cli_id}->>{cid}: uses")
    messages.append(f"  {cli_id}-->>{actor}: result")
    return _fence("sequenceDiagram", participants + messages)


def render_sankey(signals: ComprehensionSignals) -> str:
    """Merged data-flow, not one disconnected hop per edge."""
    if not signals.lineage:
        return ""
    hops = [
        hop
        for hop in signals.lineage[:24]
        if not _is_noise_component(hop.source) and not _is_noise_component(hop.target)
    ]
    if not hops:
        return ""
    ids: dict[str, str] = {}
    kinds: dict[str, str] = {}

    def node_id(name: str, kind: str) -> str:
        if name not in ids:
            ids[name] = f"n{len(ids)}"
            kinds[name] = kind
        return ids[name]

    for hop in hops:
        node_id(hop.source, hop.kind if hop.kind == "input" else "transform")
        node_id(hop.target, hop.kind if hop.kind == "output" else "transform")
        if hop.kind == "input":
            kinds[hop.source] = "input"
        if hop.kind == "output":
            kinds[hop.target] = "output"

    def display(name: str) -> str:
        if name.casefold() == "input":
            return "Inputs"
        if name.casefold() == "output":
            return "Outputs"
        return _label(_basename(name), 28)

    groups = (
        ("input", "Inputs"),
        ("transform", "This system"),
        ("output", "Outputs"),
    )
    lines: list[str] = []
    for kind, title in groups:
        members = [name for name, node_kind in kinds.items() if node_kind == kind]
        if not members:
            continue
        lines.append(f'  subgraph g{kind}["{title}"]')
        for name in members:
            shape_l, shape_r = ("([", "])") if kind != "transform" else ("[", "]")
            if kind == "output":
                shape_l, shape_r = '[(', ")]"
            lines.append(
                f"    {ids[name]}{shape_l}\"{display(name)}\"{shape_r}"
            )
        lines.append("  end")
    seen_edges: set[tuple[str, str]] = set()
    for hop in hops:
        pair = (ids[hop.source], ids[hop.target])
        if pair in seen_edges or pair[0] == pair[1]:
            continue
        seen_edges.add(pair)
        if hop.weight > 1:
            lines.append(f"  {pair[0]} -->|{hop.weight}| {pair[1]}")
        else:
            lines.append(f"  {pair[0]} --> {pair[1]}")
    if len(seen_edges) < 1:
        return ""
    return _fence_flow("LR", lines, styled=True)


def render_dag(dag: PipelineDag, *, detailed: bool) -> str:
    nodes = dag.nodes if detailed else dag.nodes[:12]
    allowed = {
        node.id: node
        for node in nodes
        if not _is_noise_component(node.label, node.path or "")
    }
    if len(allowed) < 2:
        return ""
    lines = ['  subgraph pipe["Pipeline"]']
    for node in allowed.values():
        lines.append(f'    {node.id}["{_label(node.label)}"]')
    lines.append("  end")
    any_edge = False
    for src, dst in dag.edges:
        if src in allowed and dst in allowed:
            lines.append(f"  {src} --> {dst}")
            any_edge = True
    if not any_edge:
        return ""
    lines.append("  class " + ",".join(allowed) + " container")
    return _fence_flow("LR", lines, styled=True)


def render_public_surface(analysis: RepoAnalysis | None) -> str:
    if analysis is None or not analysis.public_surface:
        return ""
    commands: list[str] = []
    modules: dict[str, list[str]] = {}
    for symbol in analysis.public_surface:
        name = symbol.name.strip()
        if not name or name.startswith("_"):
            continue
        if symbol.kind == "cli_flag":
            continue
        if symbol.kind == "cli_subcommand":
            if name not in commands:
                commands.append(name)
            continue
        if name.endswith("Error") or name.endswith("Exception"):
            continue
        if name.isupper():
            continue
        source = _basename(symbol.source).replace(".py", "") or "api"
        if source in {"__init__", "init"}:
            continue
        bucket = modules.setdefault(source, [])
        if name not in bucket:
            bucket.append(name)
    if not commands and not modules:
        return ""
    lines = ["  direction LR"]
    if commands:
        lines.append("  class CLI {")
        lines.append("    <<command>>")
        for item in commands[:10]:
            safe = re.sub(r"[^A-Za-z0-9_]", "_", item) or "cmd"
            lines.append(f"    {safe}()")
        lines.append("  }")
    for source, names in list(modules.items())[:4]:
        class_name = _ident("C", source)
        lines.append(f"  class {class_name} {{")
        lines.append("    <<module>>")
        for item in names[:6]:
            safe = re.sub(r"[^A-Za-z0-9_]", "_", item) or "item"
            lines.append(f"    {safe}()")
        lines.append("  }")
    return _fence("classDiagram", lines)


def render_story_path(pages: Sequence[Page]) -> str:
    """Numbered reading path for an enterprise landing page."""
    if len(pages) < 2:
        return ""
    lines = ['  subgraph path["Read in this order"]', "    direction LR"]
    for index, page in enumerate(pages):
        lines.append(f'    p{index}["{index + 1}. {_label(page.title, 36)}"]')
    lines.append("  end")
    for index in range(len(pages) - 1):
        lines.append(f'  p{index} -->|"then"| p{index + 1}')
    return _fence_flow("LR", lines, styled=True)


def render_question_map(
    pages: Sequence[Page],
    identity: "SiteIdentity | None" = None,
) -> str:
    """Questions clustered by reading path, not a star from Home."""
    if not pages:
        return ""
    from docuharnessx.assembler.story import story_spine

    spine = story_spine(pages, identity)
    spine_ids = {page.id for page in spine}
    rest = [page for page in pages if page.id not in spine_ids]
    lines: list[str] = []
    if spine:
        lines.append('  subgraph start["Start here"]')
        for index, page in enumerate(spine):
            lines.append(f'    s{index}["{_label(page.title, 36)}"]')
        lines.append("  end")
        for index in range(len(spine) - 1):
            lines.append(f"  s{index} --> s{index + 1}")
    if rest:
        lines.append('  subgraph more["Further questions"]')
        for index, page in enumerate(rest):
            lines.append(f'    m{index}["{_label(page.title, 36)}"]')
        lines.append("  end")
        if spine:
            lines.append("  s" + str(len(spine) - 1) + " -.-> m0")
    if len(lines) < 2:
        return ""
    return _fence_flow("TB", lines, styled=True)


def render_coverage_pie(counts: CoverageCounts | None) -> str:
    if counts is None or counts.planned == 0:
        return ""
    slices: list[str] = []
    if counts.accepted:
        slices.append(f'  "Accepted pages" : {counts.accepted}')
    if counts.omitted:
        slices.append(f'  "Omitted pages" : {counts.omitted}')
    leftover = counts.planned - counts.accepted - counts.omitted
    if leftover > 0:
        slices.append(f'  "Not yet written" : {leftover}')
    if not slices:
        return ""
    return _fence("pie showData\n  title Documentation coverage", slices)


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
        context = render_c4_context(analysis, identity)
        if context:
            blocks.append((1, context))
        else:
            mind = render_mindmap(analysis)
            if mind:
                blocks.append((1, mind))
        container = render_c4_container(analysis, identity, signals)
        if container:
            blocks.append((2, container))
    if analysis is not None and page.id.startswith("startup:"):
        seq = render_sequence(analysis, identity)
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
    container = render_c4_container(analysis, identity, signals)
    if container:
        blocks.append((2, container))
    context = render_c4_context(analysis, identity)
    if context:
        blocks.append((5, context))
    else:
        mind = render_mindmap(analysis)
        if mind:
            blocks.append((5, mind))
    home_map = render_question_map(pages, identity)
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
    from docuharnessx.assembler.graphs import iter_page_diagrams
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
    context = render_c4_context(analysis, identity) or render_mindmap(analysis)
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
    container = render_c4_container(analysis, identity, signals)
    if container:
        add(
            "Containers",
            "System",
            primary.title if primary is not None else "Home",
            page_filename(primary.id) if primary is not None else HOME_PAGE_PATH,
            2,
            container,
        )
    sequence = render_sequence(analysis, identity)
    if sequence:
        startup = next((page for page in pages if page.id.startswith("startup:")), None)
        add(
            "Typical run",
            "System",
            startup.title if startup is not None else "Home",
            page_filename(startup.id) if startup is not None else HOME_PAGE_PATH,
            3,
            sequence,
        )

    spine = story_spine(pages, identity)
    path = render_story_path(spine)
    if path:
        add("Start-here path", "Reading path", "Home", HOME_PAGE_PATH, 3, path)

    pie = render_coverage_pie(counts)
    if pie:
        add("Coverage", "Coverage", "Home", HOME_PAGE_PATH, 2, pie)

    home_map = render_question_map(pages, identity)
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
