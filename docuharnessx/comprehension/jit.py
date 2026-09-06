"""Conceptual tree for the JavaScript InfoVis Toolkit Hypertree.

JSON shape is JIT's tree: ``id``, ``name``, ``data``, ``children``.
Built only from the architecture model. Empty model → no tree.
"""

from __future__ import annotations

import html
import json

from docuharnessx.comprehension.signals import (
    AbstractionLevel,
    ArchitectureModel,
    ArchitectureNode,
)

__all__ = ["conceptual_tree", "render_conceptual_hypertree"]


def _leaf(node: ArchitectureNode) -> dict[str, object]:
    return {
        "id": node.id,
        "name": node.label,
        "data": {"kind": node.kind, "level": str(node.level)},
        "children": [],
    }


def conceptual_tree(model: ArchitectureModel | None) -> dict[str, object] | None:
    """Hypertree JSON with the system at the origin. Fail-closed."""
    if model is None:
        return None
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
                "data": {"kind": "group"},
                "children": [_leaf(node) for node in actors],
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
                    "data": {"kind": "band"},
                    "children": [_leaf(node) for node in members],
                }
            )
    for node in containers:
        if node.id in used:
            continue
        children.append(_leaf(node))
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
                "data": {"kind": "group"},
                "children": [_leaf(node) for node in externals],
            }
        )
    if not children:
        return None
    return {
        "id": system.id,
        "name": system.label,
        "data": {"kind": "system"},
        "children": children,
    }


def render_conceptual_hypertree(model: ArchitectureModel | None) -> str:
    """HTML widget + JSON payload for the vendored JIT Hypertree."""
    tree = conceptual_tree(model)
    if tree is None:
        return ""
    payload = html.escape(
        json.dumps(tree, sort_keys=True, ensure_ascii=True), quote=False
    )
    return (
        '<div class="dhx-jit" markdown="0">\n'
        '<p class="dhx-jit__hint">Click a node to recenter the map.</p>\n'
        '<textarea class="dhx-jit__data" hidden readonly>'
        f"{payload}</textarea>\n"
        '<div id="dhx-jit-conceptual" class="dhx-jit__stage"></div>\n'
        "</div>\n"
    )
