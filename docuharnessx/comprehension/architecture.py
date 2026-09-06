"""Detect organizational architecture from names, paths, and compose files.

Fail-closed: a style is emitted only when enough bands have members. No model.
"""

from __future__ import annotations

import os
from collections.abc import Sequence

import yaml

from docuharnessx.analysis.model import Component, RepoAnalysis
from docuharnessx.comprehension.signals import ArchitectureBand, ArchitectureStyle

__all__ = ["detect_architectures"]

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
