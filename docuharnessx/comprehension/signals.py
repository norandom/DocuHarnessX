"""Frozen comprehension signals (design: do not reshape RepoAnalysis)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

__all__ = [
    "AbstractionLevel",
    "ArchitectureBand",
    "ArchitectureEdge",
    "ArchitectureModel",
    "ArchitectureNode",
    "ArchitectureStyle",
    "ComprehensionSignals",
    "CoverageCounts",
    "DagNode",
    "LineageHop",
    "PipelineDag",
    "RequirementHit",
]


class AbstractionLevel(StrEnum):
    CONTEXT = "context"
    CONTAINER = "container"
    COMPONENT = "component"
    CODE = "code"


@dataclass(frozen=True)
class DagNode:
    id: str
    label: str
    path: str | None = None


@dataclass(frozen=True)
class PipelineDag:
    source: str
    nodes: tuple[DagNode, ...] = ()
    edges: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class LineageHop:
    source: str
    target: str
    weight: int
    kind: str


@dataclass(frozen=True)
class RequirementHit:
    text: str
    path: str
    term_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class CoverageCounts:
    planned: int = 0
    accepted: int = 0
    omitted: int = 0


@dataclass(frozen=True)
class ArchitectureBand:
    """One band in a detected architecture (a layer, a service, a side)."""

    id: str
    label: str
    members: tuple[str, ...] = ()


@dataclass(frozen=True)
class ArchitectureStyle:
    """A grounded architecture shape, or omitted when evidence is thin."""

    id: str
    label: str
    bands: tuple[ArchitectureBand, ...] = ()
    evidence: tuple[str, ...] = ()


@dataclass(frozen=True)
class ArchitectureNode:
    id: str
    label: str
    level: AbstractionLevel
    kind: str
    path: str | None = None
    band: str | None = None


@dataclass(frozen=True)
class ArchitectureEdge:
    source: str
    target: str
    verb: str
    evidence: str


@dataclass(frozen=True)
class ArchitectureModel:
    """One system model; views are projections of these nodes and edges."""

    system_name: str
    nodes: tuple[ArchitectureNode, ...] = ()
    edges: tuple[ArchitectureEdge, ...] = ()
    styles: tuple[ArchitectureStyle, ...] = ()
    requirement_links: tuple[tuple[str, str], ...] = ()

    def by_id(self) -> dict[str, ArchitectureNode]:
        return {node.id: node for node in self.nodes}


@dataclass(frozen=True)
class ComprehensionSignals:
    pipelines: tuple[PipelineDag, ...] = ()
    lineage: tuple[LineageHop, ...] = ()
    project_kinds: tuple[str, ...] = ()
    requirement_sentences: tuple[RequirementHit, ...] = ()
    architectures: tuple[ArchitectureStyle, ...] = ()
    model: ArchitectureModel | None = None
