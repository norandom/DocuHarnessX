"""Conceptual tree for the JavaScript InfoVis Toolkit Hypertree.

JSON shape is JIT's tree: ``id``, ``name``, ``data``, ``children``.
Built only from the architecture model. Empty model → no tree.
"""

from __future__ import annotations

import html
import json
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING

from docuharnessx.comprehension.signals import (
    AbstractionLevel,
    ArchitectureModel,
    ArchitectureNode,
)

if TYPE_CHECKING:
    from docuharnessx.assembler.model import SiteIdentity
    from docuharnessx.pages.model import Page

__all__ = ["conceptual_tree", "hrefs_from_pages", "render_conceptual_hypertree"]


def _alnum(value: str) -> str:
    return "".join(ch for ch in value.lower() if ch.isalnum())


def _page_href(page_id: str) -> str:
    from docuharnessx.assembler.pages import page_filename

    name = page_filename(page_id)
    if name.endswith(".md"):
        name = name[:-3]
    return name + "/"


def hrefs_from_pages(
    pages: Sequence["Page"] | None,
    identity: "SiteIdentity | None" = None,
) -> dict[str, str]:
    """Map architecture node ids to in-site directory URLs (TOC targets)."""
    if not pages:
        return {}
    from docuharnessx.assembler.story import primary_component

    hrefs: dict[str, str] = {}
    primary = primary_component(pages, identity)
    if primary is not None:
        hrefs["system"] = _page_href(primary.id)
    for page in pages:
        kind, _, slug = page.id.partition(":")
        href = _page_href(page.id)
        if kind == "component" and slug:
            hrefs["container:" + slug] = href
            hrefs["component:" + slug] = href
            if _alnum(slug) == "cli":
                hrefs.setdefault("container:CLI", href)
        elif kind == "startup":
            hrefs.setdefault("container:CLI", href)
    return hrefs


def _data(kind: str, level: object, href: str | None) -> dict[str, object]:
    payload: dict[str, object] = {"kind": kind, "level": str(level)}
    if href:
        payload["href"] = href
    return payload


def _leaf(
    node: ArchitectureNode, hrefs: Mapping[str, str]
) -> dict[str, object]:
    return {
        "id": node.id,
        "name": node.label,
        "data": _data(node.kind, node.level, hrefs.get(node.id)),
        "children": [],
    }


def conceptual_tree(
    model: ArchitectureModel | None,
    hrefs: Mapping[str, str] | None = None,
) -> dict[str, object] | None:
    """Hypertree JSON with the system at the origin. Fail-closed."""
    if model is None:
        return None
    links = dict(hrefs or {})
    system = next((node for node in model.nodes if node.kind == "system"), None)
    if system is None:
        return None
    children: list[dict[str, object]] = []
    actors = [node for node in model.nodes if node.kind == "actor"]
    if actors:
        children.append(
            {
                "id": "group:people",
                "name": "People",
                "data": _data("group", "context", None),
                "children": [_leaf(node, links) for node in actors],
            }
        )
    containers = [
        node
        for node in model.nodes
        if node.kind == "container" or node.level == AbstractionLevel.CONTAINER
    ]
    used: set[str] = set()
    seen_bands: set[str] = set()
    for style in model.styles:
        for band in style.bands:
            if band.id in seen_bands:
                continue
            seen_bands.add(band.id)
            members = [node for node in containers if node.band == band.id]
            if not members:
                continue
            for node in members:
                used.add(node.id)
            children.append(
                {
                    "id": "band:" + band.id,
                    "name": band.label,
                    "data": _data("band", "container", None),
                    "children": [_leaf(node, links) for node in members],
                }
            )
    for node in containers:
        if node.id in used:
            continue
        children.append(_leaf(node, links))
    externals = [
        node
        for node in model.nodes
        if node.kind in {"external", "store"}
        and (node.level == AbstractionLevel.CONTEXT or node.level == "context")
    ]
    if externals:
        children.append(
            {
                "id": "group:external",
                "name": "External",
                "data": _data("group", "context", None),
                "children": [_leaf(node, links) for node in externals],
            }
        )
    if not children:
        return None
    return {
        "id": system.id,
        "name": system.label,
        "data": _data("system", "context", links.get(system.id)),
        "children": children,
    }


def render_conceptual_hypertree(
    model: ArchitectureModel | None,
    hrefs: Mapping[str, str] | None = None,
) -> str:
    """HTML widget + JSON payload for the vendored JIT Hypertree."""
    tree = conceptual_tree(model, hrefs)
    if tree is None:
        return ""
    payload = html.escape(
        json.dumps(tree, sort_keys=True, ensure_ascii=True), quote=False
    )
    return (
        '<div class="dhx-jit" markdown="0">\n'
        '<textarea class="dhx-jit__data" hidden readonly>'
        f"{payload}</textarea>\n"
        '<div class="dhx-jit__bar">\n'
        '<p class="dhx-jit__hint">Click a name to open its page. '
        "Click a dot to recenter.</p>\n"
        '<button type="button" class="dhx-jit__reset">Center</button>\n'
        "</div>\n"
        '<div id="dhx-jit-conceptual" class="dhx-jit__stage"></div>\n'
        "</div>\n"
    )
