"""Detect organizational architecture and build one fail-closed model.

A style is emitted only when enough bands have members. Views read the
frozen :class:`ArchitectureModel`; they do not invent extra nodes.
"""

from __future__ import annotations

import os
import re
from collections.abc import Sequence

import yaml

from typing import TYPE_CHECKING

from docuharnessx.analysis.model import Component, RepoAnalysis
from docuharnessx.comprehension.signals import (
    AbstractionLevel,
    ArchitectureBand,
    ArchitectureEdge,
    ArchitectureModel,
    ArchitectureNode,
    ArchitectureStyle,
    RequirementHit,
)

if TYPE_CHECKING:
    from docuharnessx.assembler.model import SiteIdentity
    from docuharnessx.pages.model import Page

__all__ = [
    "build_architecture_model",
    "detect_architectures",
    "page_abstraction",
]

_CI_LABELS = {
    "github_actions": "GitHub Actions",
    "gitlab_ci": "GitLab CI",
    "circleci": "CircleCI",
    "dagger": "Dagger",
}

_SKIP = frozenset({"javascripts", "stylesheets", "static", "assets", "css", "js"})

_INTERFACE = frozenset(
    {
        "cli",
        "api",
        "http",
        "rest",
        "graphql",
        "ui",
        "web",
        "frontend",
        "mcp",
        "handler",
        "handlers",
        "view",
        "views",
        "controller",
        "controllers",
        "route",
        "routes",
        "cmd",
        "gateway",
        "server",
        "rpc",
    }
)
_APPLICATION = frozenset(
    {
        "app",
        "application",
        "orchestration",
        "orchestrator",
        "workflow",
        "pipeline",
        "usecase",
        "use_case",
        "usecases",
        "composition",
        "assembler",
        "deployer",
        "writer",
        "planning",
        "review",
        "orchestrate",
    }
)
_DOMAIN = frozenset(
    {
        "domain",
        "core",
        "model",
        "models",
        "ontology",
        "business",
        "entity",
        "entities",
        "analysis",
        "comprehension",
        "logic",
    }
)
_INFRA = frozenset(
    {
        "infra",
        "infrastructure",
        "adapter",
        "adapters",
        "repository",
        "repositories",
        "store",
        "storage",
        "db",
        "database",
        "persist",
        "persistence",
        "deploy",
        "queue",
        "cache",
        "client",
    }
)
_LAYER_ORDER = (
    ("interface", "Interface", _INTERFACE),
    ("application", "Application", _APPLICATION),
    ("domain", "Domain", _DOMAIN),
    ("infrastructure", "Infrastructure", _INFRA),
)
_HEX_PORTS = frozenset({"port", "ports"})
_HEX_ADAPTERS = frozenset({"adapter", "adapters"})
_HEX_DOMAIN = frozenset({"domain", "core"})
_CLIENT = frozenset({"frontend", "web", "ui", "client", "www"})
_SERVER = frozenset({"backend", "api", "server", "service"})
_PIPELINE_DIRS = {
    "raw": "Raw",
    "data": "Data",
    "features": "Features",
    "feature": "Features",
    "signals": "Signals",
    "train": "Training",
    "training": "Training",
    "models": "Models",
    "model": "Models",
    "notebooks": "Research",
}
_COMPOSE_NAMES = frozenset(
    {
        "docker-compose.yml",
        "docker-compose.yaml",
        "compose.yml",
        "compose.yaml",
    }
)


def _all_tokens(component: Component) -> tuple[str, ...]:
    parts = [component.name.casefold()]
    for segment in component.path.replace("\\", "/").casefold().split("/"):
        if segment:
            parts.append(segment)
    return tuple(dict.fromkeys(parts))


def _self_tokens(component: Component) -> tuple[str, ...]:
    name = component.name.casefold()
    last = component.path.replace("\\", "/").casefold().rstrip("/").rsplit("/", 1)[-1]
    return tuple(dict.fromkeys(token for token in (name, last) if token))


def _is_noise(component: Component) -> bool:
    name = component.name.casefold().rsplit("/", 1)[-1]
    path = component.path.replace("\\", "/").casefold()
    if name in _SKIP:
        return True
    if path.startswith("docs/") or "/javascripts" in path or "/stylesheets" in path:
        return True
    return False


def _real(analysis: RepoAnalysis) -> tuple[Component, ...]:
    return tuple(item for item in analysis.components if not _is_noise(item))


def _layer_id(component: Component) -> str | None:
    tokens = _self_tokens(component)
    for layer_id, _label, names in _LAYER_ORDER:
        if any(token in names for token in tokens):
            return layer_id
    return None


def _layered(
    components: Sequence[Component],
    analysis: RepoAnalysis,
) -> ArchitectureStyle | None:
    buckets: dict[str, list[str]] = {layer_id: [] for layer_id, _label, _names in _LAYER_ORDER}
    evidence: list[str] = []
    if any(
        entry.kind in {"cli", "console_script", "main"}
        for entry in analysis.entrypoints
    ):
        buckets["interface"].append("CLI")
        evidence.append("entrypoint:CLI")
    for component in components:
        layer = _layer_id(component)
        if layer is None:
            continue
        if component.name not in buckets[layer]:
            buckets[layer].append(component.name)
            evidence.append(f"{component.name}:{layer}")
    filled = [layer_id for layer_id, members in buckets.items() if members]
    if len(filled) < 3:
        return None
    bands = tuple(
        ArchitectureBand(id=layer_id, label=label, members=tuple(buckets[layer_id]))
        for layer_id, label, _names in _LAYER_ORDER
        if buckets[layer_id]
    )
    return ArchitectureStyle(
        id="layered",
        label="Layered architecture",
        bands=bands,
        evidence=tuple(evidence),
    )


def _under(components: Sequence[Component], folder: str) -> tuple[str, ...]:
    names: list[str] = []
    for component in components:
        parts = component.path.replace("\\", "/").casefold().split("/")
        if folder not in parts:
            continue
        index = parts.index(folder)
        if index + 1 < len(parts):
            child = parts[index + 1]
        elif component.name.casefold() != folder:
            child = component.name.casefold()
        else:
            continue
        if child not in names and child not in _SKIP:
            names.append(child)
    return tuple(names)


def _compose_services(repo: str, analysis: RepoAnalysis) -> tuple[tuple[str, str], ...]:
    paths: list[str] = []
    for item in (*analysis.build_files, *analysis.artifacts):
        base = item.path.replace("\\", "/").rsplit("/", 1)[-1].casefold()
        if base in _COMPOSE_NAMES:
            paths.append(item.path.replace("\\", "/"))
    for name in _COMPOSE_NAMES:
        if os.path.isfile(os.path.join(repo, name)) and name not in paths:
            paths.append(name)
    found: list[tuple[str, str]] = []
    seen: set[str] = set()
    for rel in paths:
        full = os.path.join(repo, rel.replace("/", os.sep))
        try:
            with open(full, "r", encoding="utf-8", errors="replace") as handle:
                data = yaml.safe_load(handle.read(80_000))
        except (OSError, yaml.YAMLError):
            continue
        if not isinstance(data, dict):
            continue
        services = data.get("services")
        if not isinstance(services, dict):
            continue
        for name in services:
            key = str(name)
            if key and key not in seen:
                seen.add(key)
                found.append((key, rel))
    return tuple(found)


def _entrypoint_roots(analysis: RepoAnalysis) -> tuple[str, ...]:
    roots: list[str] = []
    for entry in analysis.entrypoints:
        parent = entry.path.replace("\\", "/").rsplit("/", 1)[0]
        if not parent or parent == entry.path:
            continue
        top = parent.split("/", 1)[0]
        if top not in roots and top not in _SKIP:
            roots.append(top)
    return tuple(roots)


def _services(
    components: Sequence[Component],
    analysis: RepoAnalysis,
    repo: str,
) -> ArchitectureStyle | None:
    compose = _compose_services(repo, analysis)
    cmd = _under(components, "cmd")
    svc_dir = _under(components, "services") or _under(components, "service")
    roots = _entrypoint_roots(analysis)
    members: list[str] = []
    evidence: list[str] = []
    for name, path in compose:
        if name not in members:
            members.append(name)
            evidence.append(path)
    for name in cmd:
        if name not in members:
            members.append(name)
            evidence.append("cmd/" + name)
    for name in svc_dir:
        if name not in members:
            members.append(name)
            evidence.append("services/" + name)
    if len(members) < 2 and len(roots) >= 2:
        members = list(roots)
        evidence.extend("entrypoint:" + name for name in roots)
    if len(members) < 2:
        return None
    bands = tuple(
        ArchitectureBand(id="service-" + name, label=name, members=(name,))
        for name in members[:10]
    )
    return ArchitectureStyle(
        id="services",
        label="Services",
        bands=bands,
        evidence=tuple(dict.fromkeys(evidence)),
    )


def _hexagonal(components: Sequence[Component]) -> ArchitectureStyle | None:
    ports: list[str] = []
    adapters: list[str] = []
    domain: list[str] = []
    for component in components:
        tokens = set(_all_tokens(component))
        if tokens & _HEX_PORTS:
            ports.append(component.name)
        elif tokens & _HEX_ADAPTERS:
            adapters.append(component.name)
        elif tokens & _HEX_DOMAIN:
            domain.append(component.name)
    if not ((ports or adapters) and domain):
        return None
    if not adapters and not ports:
        return None
    bands = []
    if ports:
        bands.append(ArchitectureBand(id="ports", label="Ports", members=tuple(ports)))
    if domain:
        bands.append(ArchitectureBand(id="domain", label="Domain", members=tuple(domain)))
    if adapters:
        bands.append(
            ArchitectureBand(id="adapters", label="Adapters", members=tuple(adapters))
        )
    evidence = tuple(f"{name}:hex" for name in (*ports, *domain, *adapters))
    return ArchitectureStyle(
        id="hexagonal",
        label="Ports and adapters",
        bands=tuple(bands),
        evidence=evidence,
    )


def _client_server(components: Sequence[Component]) -> ArchitectureStyle | None:
    clients: list[str] = []
    servers: list[str] = []
    for component in components:
        tokens = set(_all_tokens(component))
        if tokens & _CLIENT:
            clients.append(component.name)
        elif tokens & _SERVER:
            servers.append(component.name)
    if not clients or not servers:
        return None
    return ArchitectureStyle(
        id="client_server",
        label="Client / server",
        bands=(
            ArchitectureBand(id="client", label="Client", members=tuple(clients)),
            ArchitectureBand(id="server", label="Server", members=tuple(servers)),
        ),
        evidence=tuple(f"{name}:tier" for name in (*clients, *servers)),
    )


def _pipeline(analysis: RepoAnalysis) -> ArchitectureStyle | None:
    segments: set[str] = set()
    for item in (*analysis.components, *analysis.structure):
        for segment in item.path.replace("\\", "/").casefold().split("/"):
            if segment:
                segments.add(segment)
    hits: list[tuple[str, str]] = []
    seen_labels: set[str] = set()
    for token, label in _PIPELINE_DIRS.items():
        if token in segments and label not in seen_labels:
            seen_labels.add(label)
            hits.append((token, label))
    if len(hits) < 3:
        return None
    bands = tuple(
        ArchitectureBand(id=token, label=label, members=(token,))
        for token, label in hits
    )
    return ArchitectureStyle(
        id="pipeline",
        label="Processing pipeline",
        bands=bands,
        evidence=tuple(token for token, _label in hits),
    )


def detect_architectures(
    analysis: RepoAnalysis | None,
    repo_path: str = "",
) -> tuple[ArchitectureStyle, ...]:
    """Return evidenced architecture styles, strongest structural views first."""
    if analysis is None:
        return ()
    components = _real(analysis)
    styles: list[ArchitectureStyle] = []
    for candidate in (
        _services(components, analysis, repo_path),
        _hexagonal(components),
        _client_server(components),
        _layered(components, analysis),
        _pipeline(analysis),
    ):
        if candidate is not None:
            styles.append(candidate)
    return tuple(styles)


def _alnum(value: str) -> str:
    return "".join(ch for ch in value.lower() if ch.isalnum())


def page_abstraction(
    page: "Page",
    identity: "SiteIdentity | None" = None,
) -> AbstractionLevel:
    """Zoom level for a question page: package at container, modules at component."""
    kind = page.id.split(":", 1)[0]
    if kind in {"startup", "public_surface"}:
        return AbstractionLevel.CONTEXT
    if kind in {"build", "tests"}:
        return AbstractionLevel.CONTAINER
    if kind == "component":
        slug = page.id.split(":", 1)[1] if ":" in page.id else ""
        keys: set[str] = set()
        if identity is not None:
            repo = (identity.repo_name or "").rsplit("/", 1)[-1]
            if repo:
                keys.add(_alnum(repo))
            if identity.site_name:
                keys.add(_alnum(identity.site_name))
        tokens = [_alnum(slug), *(_alnum(item) for item in page.subjects)]
        if keys and any(token in keys for token in tokens if token):
            return AbstractionLevel.CONTAINER
        return AbstractionLevel.COMPONENT
    return AbstractionLevel.COMPONENT


def _basename(path: str) -> str:
    return path.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]


def _container_id(member: str) -> str:
    if member == "CLI":
        return "container:CLI"
    return f"container:{member}"


def _cli_name(analysis: RepoAnalysis) -> str:
    for entry in analysis.entrypoints:
        if entry.name:
            return entry.name
    if any(e.kind in {"cli", "console_script", "main"} for e in analysis.entrypoints):
        return "CLI"
    if analysis.entrypoints:
        return _basename(analysis.entrypoints[0].path) or "entrypoint"
    return "CLI"


def _system_name(
    analysis: RepoAnalysis,
    identity: "SiteIdentity | None",
) -> str:
    if identity is not None and identity.site_name:
        return identity.site_name
    if analysis.repo_path:
        return _basename(analysis.repo_path) or "System"
    return "System"


_WORD = re.compile(r"[A-Za-z0-9_]+")


def _hit_key(hit: RequirementHit) -> str:
    return hit.path + "\n" + hit.text


def _tokens(*parts: str) -> frozenset[str]:
    found: set[str] = set()
    for part in parts:
        for token in _WORD.findall(part):
            if len(token) >= 4:
                found.add(token.casefold())
    return frozenset(found)


def _requirement_links(
    nodes: tuple[ArchitectureNode, ...],
    styles: tuple[ArchitectureStyle, ...],
    hits: tuple[RequirementHit, ...],
) -> tuple[tuple[str, str], ...]:
    """Link harvested shall-cards to nodes by whole-word overlap. Never invent hits."""
    if not hits or not nodes:
        return ()
    names: list[tuple[str, str]] = []
    for node in nodes:
        label = (node.label or "").strip()
        if len(label) >= 4:
            names.append((label.casefold(), node.id))
        band = (node.band or "").strip()
        if len(band) >= 4:
            names.append((band.casefold(), node.id))
    for style in styles:
        for band in style.bands:
            members = tuple(node.id for node in nodes if node.band == band.id)
            compact = band.label.strip().casefold()
            for target in members:
                if len(band.id) >= 4:
                    names.append((band.id.casefold(), target))
                if len(compact) >= 4 and " " not in compact and "/" not in compact:
                    names.append((compact, target))
    names = list(dict.fromkeys(names))
    links: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for hit in hits:
        tokens = _tokens(hit.text, *hit.term_ids)
        key = _hit_key(hit)
        for name, target in names:
            if name not in tokens:
                continue
            pair = (key, target)
            if pair in seen:
                continue
            seen.add(pair)
            links.append(pair)
    return tuple(sorted(links))


def build_architecture_model(
    analysis: RepoAnalysis | None,
    identity: "SiteIdentity | None" = None,
    styles: tuple[ArchitectureStyle, ...] = (),
    hits: tuple[RequirementHit, ...] = (),
) -> ArchitectureModel | None:
    """Build one fail-closed model. Views must not invent extra nodes."""
    if analysis is None:
        return None
    if not (analysis.entrypoints or analysis.components):
        return None
    nodes: dict[str, ArchitectureNode] = {}
    edges: list[ArchitectureEdge] = []

    def add_node(node: ArchitectureNode) -> None:
        if node.id not in nodes:
            nodes[node.id] = node

    def add_edge(source: str, target: str, verb: str, evidence: str) -> None:
        if source not in nodes or target not in nodes or source == target:
            return
        pair = (source, target, verb)
        if any((e.source, e.target, e.verb) == pair for e in edges):
            return
        edges.append(ArchitectureEdge(source, target, verb, evidence))

    kinds = {entry.kind for entry in analysis.entrypoints}
    actor = (
        "Operator"
        if kinds & {"cli", "console_script", "main", "script", "package_bin"}
        else "User"
    )
    add_node(
        ArchitectureNode(
            id="actor:operator",
            label=actor,
            level=AbstractionLevel.CONTEXT,
            kind="actor",
        )
    )
    system_name = _system_name(analysis, identity)
    add_node(
        ArchitectureNode(
            id="system",
            label=system_name,
            level=AbstractionLevel.CONTEXT,
            kind="system",
        )
    )
    cli = _cli_name(analysis) if analysis.entrypoints else ""
    add_edge(
        "actor:operator",
        "system",
        f"runs {cli}" if cli else "runs",
        "entrypoint",
    )

    repo = ""
    if identity is not None:
        repo = identity.repo_name or identity.site_name
    if not repo and analysis.repo_path:
        repo = _basename(analysis.repo_path)
    if repo:
        add_node(
            ArchitectureNode(
                id="external:repo",
                label=repo,
                level=AbstractionLevel.CONTEXT,
                kind="store",
            )
        )
        add_edge("system", "external:repo", "reads and cites", "identity.repo")
    if analysis.ci_workflows:
        provider = analysis.ci_workflows[0].provider
        add_node(
            ArchitectureNode(
                id="external:ci",
                label=_CI_LABELS.get(provider, "CI"),
                level=AbstractionLevel.CONTEXT,
                kind="external",
                path=analysis.ci_workflows[0].path,
            )
        )
        add_edge("external:ci", "system", "runs in", "ci_workflows")
    if analysis.docs.doc_dirs or analysis.docs.has_readme:
        add_node(
            ArchitectureNode(
                id="external:docs",
                label="Documentation site",
                level=AbstractionLevel.CONTEXT,
                kind="store",
            )
        )
        add_edge("system", "external:docs", "publishes", "docs")

    if analysis.entrypoints:
        add_node(
            ArchitectureNode(
                id="container:CLI",
                label="CLI",
                level=AbstractionLevel.CONTAINER,
                kind="container",
                path=analysis.entrypoints[0].path,
                band="interface",
            )
        )
        add_edge("actor:operator", "container:CLI", f"runs {cli}", "entrypoint")

    live_styles = styles or detect_architectures(analysis)
    seen_members: set[str] = set()
    if analysis.entrypoints:
        seen_members.add("CLI")
    for style in live_styles:
        for band in style.bands:
            for member in band.members:
                if member in seen_members or member.casefold() in _SKIP:
                    continue
                seen_members.add(member)
                add_node(
                    ArchitectureNode(
                        id=_container_id(member),
                        label=member,
                        level=AbstractionLevel.CONTAINER,
                        kind="container",
                        band=band.id,
                    )
                )
        if style.id == "layered":
            filled = [band for band in style.bands if band.members]
            for left, right in zip(filled, filled[1:]):
                add_edge(
                    _container_id(left.members[0]),
                    _container_id(right.members[0]),
                    "depends on",
                    f"layered:{left.id}->{right.id}",
                )

    leftover = [
        item
        for item in _real(analysis)
        if item.name not in seen_members and item.name.casefold() not in _SKIP
    ]
    has_structural = any(
        style.id in {"layered", "services", "hexagonal", "client_server"}
        and style.bands
        for style in live_styles
    )
    leftover_level = (
        AbstractionLevel.COMPONENT if has_structural else AbstractionLevel.CONTAINER
    )
    leftover_kind = "component" if has_structural else "container"
    leftover_prefix = "component:" if has_structural else "container:"
    for index, item in enumerate(leftover[:8]):
        nid = leftover_prefix + item.name
        add_node(
            ArchitectureNode(
                id=nid,
                label=item.name,
                level=leftover_level,
                kind=leftover_kind,
                path=item.path,
            )
        )
        if (
            not has_structural
            and index < 4
            and "container:CLI" in nodes
            and leftover_kind == "container"
        ):
            add_edge("container:CLI", nid, "uses", "entrypoint")

    ordered = tuple(
        sorted(nodes.values(), key=lambda node: (node.level, node.kind, node.id))
    )
    return ArchitectureModel(
        system_name=system_name,
        nodes=ordered,
        edges=tuple(edges),
        styles=live_styles,
        requirement_links=_requirement_links(ordered, live_styles, hits),
    )
