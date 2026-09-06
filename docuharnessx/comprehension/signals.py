"""Frozen comprehension signals (design: do not reshape RepoAnalysis)."""

from __future__ import annotations

from dataclasses import dataclass

__all__ = [
    "ComprehensionSignals",
    "CoverageCounts",
    "DagNode",
    "LineageHop",
    "PipelineDag",
    "RequirementHit",
]


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
class ComprehensionSignals:
    pipelines: tuple[PipelineDag, ...] = ()
    lineage: tuple[LineageHop, ...] = ()
    project_kinds: tuple[str, ...] = ()
    requirement_sentences: tuple[RequirementHit, ...] = ()
