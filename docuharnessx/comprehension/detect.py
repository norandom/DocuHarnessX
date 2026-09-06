"""Detect pipelines, lineage, project kinds, and requirement-shaped sentences."""

from __future__ import annotations

import os
import re
import yaml

from docuharnessx.analysis.model import RepoAnalysis
from docuharnessx.comprehension.architecture import (
    build_architecture_model,
    detect_architectures,
)
from docuharnessx.comprehension.signals import (
    ComprehensionSignals,
    DagNode,
    LineageHop,
    PipelineDag,
    RequirementHit,
)

__all__ = ["detect_comprehension"]

_SHALL = re.compile(
    r"^.+\bshall\b.+$",
    re.IGNORECASE | re.MULTILINE,
)
_DAG_NAME = re.compile(r"""name\s*[:=]\s*['\"]([^'\"]+)['\"]""")
_NEEDS = re.compile(r"^\s+needs:\s*(.+)$", re.MULTILINE)
_MAKE_TARGET = re.compile(r"^([A-Za-z0-9_./-]+)\s*:(.*)$", re.MULTILINE)


def _read(repo: str, rel: str, limit: int = 80_000) -> str:
    path = os.path.join(repo, rel.replace("/", os.sep))
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            return handle.read(limit)
    except OSError:
        return ""


def _rel_paths(analysis: RepoAnalysis) -> tuple[str, ...]:
    paths: list[str] = []
    paths.extend(item.path for item in analysis.ci_workflows)
    paths.extend(item.path for item in analysis.build_files)
    paths.extend(item.path for item in analysis.artifacts)
    paths.extend(analysis.docs.other_docs)
    paths.extend(analysis.docs.readme_paths)
    paths.extend(c.path for c in analysis.components)
    for summary in analysis.structure:
        if summary.path:
            paths.append(summary.path)
    return tuple(dict.fromkeys(paths))


def _github_actions(repo: str, analysis: RepoAnalysis) -> tuple[PipelineDag, ...]:
    dags: list[PipelineDag] = []
    for workflow in analysis.ci_workflows:
        if workflow.provider != "github_actions":
            continue
        text = _read(repo, workflow.path)
        if not text:
            continue
        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError:
            continue
        if not isinstance(data, dict):
            continue
        jobs = data.get("jobs")
        if not isinstance(jobs, dict):
            continue
        nodes = tuple(
            DagNode(id=str(name), label=str(name), path=workflow.path)
            for name in jobs
        )
        edges: list[tuple[str, str]] = []
        for name, job in jobs.items():
            if not isinstance(job, dict):
                continue
            needs = job.get("needs")
            if needs is None:
                continue
            if isinstance(needs, str):
                deps = [needs]
            elif isinstance(needs, list):
                deps = [str(item) for item in needs]
            else:
                continue
            for dep in deps:
                if dep in jobs:
                    edges.append((dep, str(name)))
        dags.append(
            PipelineDag(
                source="github-actions",
                nodes=nodes,
                edges=tuple(dict.fromkeys(edges)),
            )
        )
    return tuple(dags)


def _makefile(repo: str, analysis: RepoAnalysis) -> tuple[PipelineDag, ...]:
    makes = [
        item.path
        for item in analysis.build_files
        if item.kind == "makefile" or item.path.replace("\\", "/").endswith("Makefile")
    ]
    if not makes:
        for candidate in ("Makefile", "makefile"):
            if os.path.isfile(os.path.join(repo, candidate)):
                makes.append(candidate)
    dags: list[PipelineDag] = []
    for rel in makes:
        text = _read(repo, rel)
        nodes: dict[str, DagNode] = {}
        edges: list[tuple[str, str]] = []
        for match in _MAKE_TARGET.finditer(text):
            name = match.group(1)
            if name.startswith(".") or name.startswith("#"):
                continue
            nodes[name] = DagNode(id=name, label=name, path=rel)
            deps = [d.strip() for d in match.group(2).split() if d.strip()]
            for dep in deps:
                if dep.startswith("-") or dep.startswith("$"):
                    continue
                nodes.setdefault(dep, DagNode(id=dep, label=dep, path=rel))
                edges.append((dep, name))
        if nodes:
            dags.append(
                PipelineDag(
                    source="makefile",
                    nodes=tuple(nodes.values()),
                    edges=tuple(dict.fromkeys(edges)),
                )
            )
    return tuple(dags)


def _named_files(repo: str, analysis: RepoAnalysis) -> tuple[PipelineDag, ...]:
    mapping = {
        "snakemake": ("Snakefile", "snakefile"),
        "dbt": ("dbt_project.yml",),
        "kedro": ("catalog.yml", "pipeline.py"),
        "airflow": ("dags",),
        "prefect": (),
        "dagster": (),
    }
    blob = " ".join(_rel_paths(analysis)).replace("\\", "/").casefold()
    dags: list[PipelineDag] = []
    if any(name in blob for name in mapping["snakemake"]):
        dags.append(
            PipelineDag(
                source="snakemake",
                nodes=(DagNode(id="snakemake", label="Snakemake", path="Snakefile"),),
            )
        )
    if "dbt_project.yml" in blob or "/models/" in blob:
        dags.append(
            PipelineDag(
                source="dbt",
                nodes=(DagNode(id="dbt", label="dbt models", path="dbt_project.yml"),),
            )
        )
    if "catalog.yml" in blob or "kedro" in blob:
        dags.append(
            PipelineDag(
                source="kedro",
                nodes=(DagNode(id="kedro", label="Kedro", path="catalog.yml"),),
            )
        )
    if "/dags/" in blob or "airflow" in blob:
        dags.append(
            PipelineDag(
                source="airflow",
                nodes=(DagNode(id="airflow", label="Airflow", path="dags"),),
            )
        )
    if "@flow" in _read(repo, "README.md") or "prefect" in blob:
        dags.append(
            PipelineDag(
                source="prefect",
                nodes=(DagNode(id="prefect", label="Prefect", path=None),),
            )
        )
    if "dagster" in blob:
        dags.append(
            PipelineDag(
                source="dagster",
                nodes=(DagNode(id="dagster", label="Dagster", path=None),),
            )
        )
    return tuple(dags)


def _coarse(analysis: RepoAnalysis) -> tuple[PipelineDag, ...]:
    if not analysis.entrypoints and not analysis.components:
        return ()
    nodes: list[DagNode] = []
    edges: list[tuple[str, str]] = []
    for entry in analysis.entrypoints[:8]:
        nid = f"entry:{entry.path}"
        nodes.append(DagNode(id=nid, label=entry.name or entry.path, path=entry.path))
        for component in analysis.components[:8]:
            cid = f"comp:{component.path}"
            nodes.append(
                DagNode(id=cid, label=component.name, path=component.path)
            )
            edges.append((nid, cid))
            for artifact in analysis.artifacts[:4]:
                aid = f"art:{artifact.path}"
                nodes.append(
                    DagNode(id=aid, label=artifact.path, path=artifact.path)
                )
                edges.append((cid, aid))
    if len(nodes) < 2:
        return ()
    unique_nodes = tuple({n.id: n for n in nodes}.values())
    return (
        PipelineDag(
            source="coarse",
            nodes=unique_nodes,
            edges=tuple(dict.fromkeys(edges)),
        ),
    )


def _lineage(analysis: RepoAnalysis) -> tuple[LineageHop, ...]:
    hops: list[LineageHop] = []
    kinds = _project_kinds(analysis)
    if "ml" in kinds or "quant" in kinds:
        stages = ("raw", "features", "model", "output")
        for left, right in zip(stages, stages[1:]):
            hops.append(LineageHop(left, right, 1, "transform"))
        if analysis.entrypoints:
            hops.append(
                LineageHop(
                    "entrypoint",
                    stages[0],
                    1,
                    "input",
                )
            )
        return tuple(hops)
    if not analysis.entrypoints:
        return ()
    entry = analysis.entrypoints[0].name or analysis.entrypoints[0].path
    hops.append(LineageHop("input", entry, 1, "input"))
    for component in analysis.components[:6]:
        hops.append(LineageHop(entry, component.name, 1, "transform"))
        hops.append(LineageHop(component.name, "output", 1, "output"))
    if len(hops) == 1 and analysis.artifacts:
        hops.append(LineageHop(entry, analysis.artifacts[0].path, 1, "output"))
    return tuple(hops)


def _project_kinds(analysis: RepoAnalysis) -> tuple[str, ...]:
    blob = " ".join(_rel_paths(analysis)).casefold()
    kinds: list[str] = ["software"]
    if any(
        token in blob
        for token in ("notebook", ".ipynb", "train", "mlflow", ".pt", "sklearn")
    ):
        kinds.append("ml")
    if any(
        token in blob
        for token in ("signal", "portfolio", "quant", "feature", "alpha")
    ):
        kinds.append("quant")
    return tuple(kinds)


def _requirements(repo: str, analysis: RepoAnalysis) -> tuple[RequirementHit, ...]:
    candidates: list[str] = []
    for path in _rel_paths(analysis):
        low = path.replace("\\", "/").casefold()
        if low.endswith("requirements.md") or low.endswith(".adr.md") or "/adr/" in low:
            candidates.append(path)
    extra = (
        "requirements.md",
        os.path.join(".kiro", "specs"),
    )
    hits: list[RequirementHit] = []
    seen: set[str] = set()
    for rel in candidates:
        if rel in seen:
            continue
        seen.add(rel)
        text = _read(repo, rel)
        for match in _SHALL.finditer(text):
            line = " ".join(match.group(0).split())
            if len(line) < 12:
                continue
            hits.append(RequirementHit(text=line[:240], path=rel))
            if len(hits) >= 24:
                return tuple(hits)
    specs = os.path.join(repo, ".kiro", "specs")
    if os.path.isdir(specs):
        spec_files: list[str] = []
        for root, _dirs, files in os.walk(specs):
            for name in files:
                if name != "requirements.md":
                    continue
                full = os.path.join(root, name)
                rel = os.path.relpath(full, repo).replace("\\", "/")
                if rel not in seen:
                    spec_files.append(rel)
        for rel in sorted(spec_files):
            seen.add(rel)
            text = _read(repo, rel)
            for match in _SHALL.finditer(text):
                line = " ".join(match.group(0).split())
                hits.append(RequirementHit(text=line[:240], path=rel))
                if len(hits) >= 24:
                    return tuple(hits)
    _ = extra
    return tuple(hits)


def detect_comprehension(
    analysis: RepoAnalysis | None,
    repo_path: str,
) -> ComprehensionSignals:
    if analysis is None:
        return ComprehensionSignals()
    pipelines: list[PipelineDag] = []
    pipelines.extend(_github_actions(repo_path, analysis))
    pipelines.extend(_makefile(repo_path, analysis))
    pipelines.extend(_named_files(repo_path, analysis))
    if not pipelines:
        pipelines.extend(_coarse(analysis))
    styles = detect_architectures(analysis, repo_path)
    hits = _requirements(repo_path, analysis)
    return ComprehensionSignals(
        pipelines=tuple(pipelines),
        lineage=_lineage(analysis),
        project_kinds=_project_kinds(analysis),
        requirement_sentences=hits,
        architectures=styles,
        model=build_architecture_model(analysis, styles=styles, hits=hits),
    )
