"""Deterministic Mermaid companions rendered above question-page prose.

The explore-first writer is not a reliable diagram source: the substance gate
ignores Mermaid, so accepted pages can be walls of text. These helpers derive
small flowcharts from the frozen page record (and optional ``RepoAnalysis``)
so every published page opens with pictures. Pure, model-free, byte-stable.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from docuharnessx.pages.model import Page
from docuharnessx.planning.question_model import QuestionKind

if TYPE_CHECKING:
    from docuharnessx.analysis.model import RepoAnalysis

__all__ = ["render_home_diagrams", "render_page_diagrams"]

_MAX_FILES = 8
_MAX_RELATED = 6
_MAX_SYMBOLS = 8


def _label(text: str, limit: int = 40) -> str:
    """Single-line Mermaid node label, quoted-safe."""
    cleaned = " ".join(text.split()).replace('"', "'")
    for src, dst in (("[", "("), ("]", ")"), ("{", "("), ("}", ")")):
        cleaned = cleaned.replace(src, dst)
    if len(cleaned) > limit:
        cleaned = cleaned[: limit - 1] + "…"
    return cleaned or "?"


def _basename(path: str) -> str:
    return path.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]


def _dir_of(path: str) -> str:
    norm = path.replace("\\", "/").rstrip("/")
    if "/" not in norm:
        return "."
    return norm.rsplit("/", 1)[0]


def _kind_of(page: Page) -> str:
    return page.id.split(":", 1)[0]


def _fence(kind_line: str, lines: Sequence[str]) -> str:
    body = "\n".join(lines)
    return f"```mermaid\n{kind_line}\n{body}\n```\n"


class _Graph:
    """Tiny deterministic flowchart builder with stable node ids."""

    def __init__(self) -> None:
        self._ids: dict[str, str] = {}
        self._nodes: list[tuple[str, str]] = []
        self._edges: list[tuple[str, str]] = []
        self._edge_seen: set[tuple[str, str]] = set()

    def node(self, key: str, label: str) -> str:
        existing = self._ids.get(key)
        if existing is not None:
            return existing
        nid = f"n{len(self._ids)}"
        self._ids[key] = nid
        self._nodes.append((nid, _label(label)))
        return nid

    def edge(self, src: str, dst: str) -> None:
        pair = (src, dst)
        if src == dst or pair in self._edge_seen:
            return
        self._edge_seen.add(pair)
        self._edges.append(pair)

    def render(self, direction: str = "TB") -> str:
        if not self._nodes:
            return ""
        lines = [f"  {nid}[\"{label}\"]" for nid, label in self._nodes]
        lines.extend(f"  {src} --> {dst}" for src, dst in self._edges)
        return _fence(f"flowchart {direction}", lines)


def _glance_flowchart(page: Page, accepted: Sequence[Page]) -> str:
    """This question, its related pages, and the files it cites."""
    graph = _Graph()
    here = graph.node(f"page:{page.id}", page.title)
    by_id = {item.id: item for item in accepted}
    related = 0
    for target in page.related:
        other = by_id.get(target)
        if other is None or other.id == page.id:
            continue
        graph.edge(here, graph.node(f"page:{other.id}", other.title))
        related += 1
        if related >= _MAX_RELATED:
            break
    for path in page.cited_files[:_MAX_FILES]:
        graph.edge(here, graph.node(f"file:{path}", _basename(path)))
    if len(graph._nodes) < 2:
        return ""
    return graph.render("TB")


def _file_pipeline(page: Page) -> str:
    """Left-to-right chain of cited files when analysis is absent."""
    files = list(page.cited_files[:_MAX_FILES])
    if len(files) < 2:
        return ""
    graph = _Graph()
    prev = None
    for path in files:
        nid = graph.node(f"file:{path}", _basename(path))
        if prev is not None:
            graph.edge(prev, nid)
        prev = nid
    return graph.render("LR")


def _startup_flowchart(page: Page, analysis: "RepoAnalysis | None") -> str:
    graph = _Graph()
    prev = None
    if analysis is not None:
        for entry in analysis.entrypoints[:_MAX_FILES]:
            label = entry.name or _basename(entry.path) or entry.kind
            nid = graph.node(f"file:{entry.path}", label)
            if prev is not None:
                graph.edge(prev, nid)
            prev = nid
    files = page.cited_files[:_MAX_FILES] or (
        tuple(e.path for e in analysis.entrypoints[:_MAX_FILES]) if analysis else ()
    )
    for path in files:
        nid = graph.node(f"file:{path}", _basename(path))
        if prev is not None:
            graph.edge(prev, nid)
        prev = nid
    if len(graph._nodes) < 2:
        return _file_pipeline(page)
    return graph.render("LR")


def _component_flowchart(page: Page, analysis: "RepoAnalysis | None") -> str:
    graph = _Graph()
    here = graph.node(f"page:{page.id}", page.title)
    if analysis is not None:
        slug = page.id.split(":", 1)[-1].casefold()
        for component in analysis.components:
            name = component.name.casefold()
            path = component.path.casefold()
            if slug not in name and slug not in path and name not in slug:
                continue
            parent = graph.node(f"comp:{component.path}", component.name)
            graph.edge(here, parent)
            for path in component.representative_files[:_MAX_FILES]:
                graph.edge(parent, graph.node(f"file:{path}", _basename(path)))
            break
    for path in page.cited_files[:_MAX_FILES]:
        graph.edge(here, graph.node(f"file:{path}", _basename(path)))
    if len(graph._nodes) < 2:
        return _file_pipeline(page)
    return graph.render("TB")


def _public_surface_flowchart(page: Page, analysis: "RepoAnalysis | None") -> str:
    graph = _Graph()
    here = graph.node(f"page:{page.id}", page.title)
    added = 0
    if analysis is not None:
        cited = set(page.cited_files)
        symbols = analysis.public_surface
        if cited:
            filtered = tuple(s for s in symbols if s.source in cited)
            if filtered:
                symbols = filtered
        for symbol in symbols[:_MAX_SYMBOLS]:
            graph.edge(
                here,
                graph.node(
                    f"sym:{symbol.kind}:{symbol.source}:{symbol.name}",
                    symbol.name,
                ),
            )
            added += 1
    if added == 0:
        return _file_pipeline(page)
    return graph.render("TB")


def _build_flowchart(page: Page, analysis: "RepoAnalysis | None") -> str:
    graph = _Graph()
    here = graph.node(f"page:{page.id}", page.title)
    if analysis is not None:
        prev = here
        for item in analysis.build_files[:_MAX_FILES]:
            nid = graph.node(f"build:{item.path}", _basename(item.path))
            graph.edge(prev, nid)
            prev = nid
        for item in analysis.ci_workflows[:4]:
            graph.edge(here, graph.node(f"ci:{item.path}", _basename(item.path)))
    for path in page.cited_files[:_MAX_FILES]:
        graph.edge(here, graph.node(f"file:{path}", _basename(path)))
    if len(graph._nodes) < 2:
        return _file_pipeline(page)
    return graph.render("LR")


def _tests_flowchart(page: Page, analysis: "RepoAnalysis | None") -> str:
    graph = _Graph()
    here = graph.node(f"page:{page.id}", page.title)
    if analysis is not None:
        for path in analysis.tests.paths[:_MAX_FILES]:
            graph.edge(here, graph.node(f"test:{path}", path))
        for name in analysis.tests.frameworks[:4]:
            graph.edge(here, graph.node(f"fw:{name}", name))
    for path in page.cited_files[:_MAX_FILES]:
        graph.edge(here, graph.node(f"file:{path}", _basename(path)))
    if len(graph._nodes) < 2:
        return _file_pipeline(page)
    return graph.render("TB")


def _kind_flowchart(page: Page, analysis: "RepoAnalysis | None") -> str:
    kind = _kind_of(page)
    if kind == QuestionKind.STARTUP:
        return _startup_flowchart(page, analysis)
    if kind == QuestionKind.COMPONENT:
        return _component_flowchart(page, analysis)
    if kind == QuestionKind.PUBLIC_SURFACE:
        return _public_surface_flowchart(page, analysis)
    if kind == QuestionKind.BUILD:
        return _build_flowchart(page, analysis)
    if kind == QuestionKind.TESTS:
        return _tests_flowchart(page, analysis)
    return _file_pipeline(page)


def _evidence_flowchart(page: Page) -> str:
    """Cited files grouped by parent directory — skipped when all share one dir."""
    files = list(page.cited_files[:_MAX_FILES])
    if len(files) < 2:
        return ""
    groups: dict[str, list[str]] = {}
    for path in files:
        groups.setdefault(_dir_of(path), []).append(path)
    if len(groups) < 2:
        return ""
    here_key = "page"
    lines: list[str] = [f'  {here_key}["{_label(page.title)}"]']
    edges: list[str] = []
    node_i = 0
    dir_i = 0
    for directory, paths in groups.items():
        dir_id = f"d{dir_i}"
        dir_i += 1
        dir_label = "repo root" if directory in {"", "."} else directory
        lines.append(f'  subgraph {dir_id}["{_label(dir_label, 28)}"]')
        for path in paths:
            nid = f"e{node_i}"
            node_i += 1
            lines.append(f'    {nid}["{_label(_basename(path))}"]')
            edges.append(f"  {here_key} --> {nid}")
        lines.append("  end")
    lines.extend(edges)
    return _fence("flowchart TB", lines)


def render_page_diagrams(
    page: Page,
    accepted: Sequence[Page],
    analysis: "RepoAnalysis | None" = None,
) -> str:
    """Return Mermaid markdown to place immediately under the page H1.

    Always pictures-first: no heading before the first fence. Empty string only
    when the page has no related questions and no cited files.
    """
    blocks: list[str] = []
    glance = _glance_flowchart(page, accepted)
    if glance:
        blocks.append(glance)
    kind_block = _kind_flowchart(page, analysis)
    if kind_block and kind_block != glance:
        blocks.append(kind_block)
    evidence = _evidence_flowchart(page)
    if evidence:
        blocks.append(evidence)
    if not blocks:
        return ""
    return "\n".join(blocks) + "\n"


def render_home_diagrams(pages: Sequence[Page]) -> str:
    """Site-wide map of accepted questions, for ``docs/index.md``."""
    if not pages:
        return ""
    graph = _Graph()
    home = graph.node("home", "Home")
    for page in pages:
        graph.edge(home, graph.node(f"page:{page.id}", page.title))
    by_id = {page.id: page for page in pages}
    for page in pages:
        src = graph.node(f"page:{page.id}", page.title)
        for target in page.related:
            if target not in by_id or target == page.id:
                continue
            graph.edge(src, graph.node(f"page:{target}", by_id[target].title))
    rendered = graph.render("TB")
    if not rendered:
        return ""
    return rendered + "\n"
