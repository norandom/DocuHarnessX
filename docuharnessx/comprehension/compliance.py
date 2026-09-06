"""Compliance self-assessment selection, scoring, and interview."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Mapping, Sequence, TextIO

import yaml

from docuharnessx.analysis.model import RepoAnalysis
from docuharnessx.errors import OntologyConfigError

__all__ = [
    "COMPLIANCE_RELPATH",
    "FRAMEWORKS",
    "PILLARS",
    "ComplianceCell",
    "ComplianceSelection",
    "load_compliance",
    "parse_frameworks",
    "prompt_compliance_topics",
    "save_compliance",
    "score_matrix",
]

COMPLIANCE_RELPATH = os.path.join(".docuharnessx", "compliance.yaml")

FRAMEWORKS: tuple[str, ...] = (
    "iso27001",
    "pci-dss",
    "nis2",
    "cra",
    "gdpr",
)

# pillar_id -> (label, frozenset of frameworks it applies to)
PILLARS: tuple[tuple[str, str, frozenset[str]], ...] = (
    ("inventory", "Asset & data inventory", frozenset(FRAMEWORKS)),
    ("access", "Access control", frozenset({"iso27001", "pci-dss", "nis2", "gdpr"})),
    ("crypto", "Cryptography", frozenset({"iso27001", "pci-dss", "gdpr"})),
    ("logging", "Logging & monitoring", frozenset({"iso27001", "pci-dss", "gdpr"})),
    ("vuln", "Vulnerability management", frozenset({"iso27001", "pci-dss", "cra"})),
    ("ssdlc", "Secure development", frozenset({"iso27001", "pci-dss", "cra", "gdpr"})),
    ("supply", "Supply chain / SBOM", frozenset(FRAMEWORKS)),
    ("incident", "Incident response", frozenset(FRAMEWORKS)),
    ("continuity", "Backup & continuity", frozenset({"iso27001"})),
    ("privacy", "Privacy & data-subject rights", frozenset({"gdpr"})),
    ("cde", "Cardholder data environment", frozenset({"pci-dss"})),
    ("governance", "Policies & governance docs", frozenset({"iso27001", "pci-dss", "gdpr"})),
    ("training", "Awareness / training", frozenset({"iso27001", "pci-dss"})),
)

_ALIASES = {
    "iso": "iso27001",
    "iso-27001": "iso27001",
    "iso27001": "iso27001",
    "pci": "pci-dss",
    "pci-dss": "pci-dss",
    "pcidss": "pci-dss",
    "nis2": "nis2",
    "cra": "cra",
    "gdpr": "gdpr",
}


@dataclass(frozen=True)
class ComplianceSelection:
    frameworks: tuple[str, ...] = ()
    overrides: tuple[tuple[str, str, str], ...] = ()  # framework, pillar, status
    notes: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class ComplianceCell:
    framework: str
    pillar: str
    status: str  # na | fail | partial | pass
    evidence: tuple[str, ...] = ()
    overridden: bool = False


def parse_frameworks(raw: str | Sequence[str] | None) -> tuple[str, ...]:
    if raw is None or raw == "":
        return ()
    if isinstance(raw, str):
        parts = [p.strip().casefold() for p in raw.replace(";", ",").split(",")]
    else:
        parts = [str(p).strip().casefold() for p in raw]
    found: list[str] = []
    for part in parts:
        if part in {"", "none", "no", "n"}:
            continue
        name = _ALIASES.get(part)
        if name and name not in found:
            found.append(name)
    return tuple(found)


def load_compliance(project_dir: str) -> ComplianceSelection:
    path = os.path.join(project_dir, COMPLIANCE_RELPATH)
    if not os.path.isfile(path):
        return ComplianceSelection()
    with open(path, "r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if data is None:
        return ComplianceSelection()
    if not isinstance(data, Mapping):
        raise OntologyConfigError(
            f"invalid compliance config '{path}': mapping required"
        )
    frameworks = parse_frameworks(data.get("frameworks"))
    overrides: list[tuple[str, str, str]] = []
    raw_over = data.get("overrides") or {}
    if isinstance(raw_over, Mapping):
        for key, status in raw_over.items():
            text = str(key)
            if "." not in text:
                continue
            fw, pillar = text.split(".", 1)
            overrides.append((str(fw), str(pillar), str(status)))
    notes: list[tuple[str, str]] = []
    raw_notes = data.get("notes") or {}
    if isinstance(raw_notes, Mapping):
        notes.extend((str(k), str(v)) for k, v in raw_notes.items())
    return ComplianceSelection(
        frameworks=frameworks,
        overrides=tuple(overrides),
        notes=tuple(notes),
    )


def save_compliance(project_dir: str, selection: ComplianceSelection) -> str:
    path = os.path.join(project_dir, COMPLIANCE_RELPATH)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    overrides = {
        f"{fw}.{pillar}": status for fw, pillar, status in selection.overrides
    }
    payload: dict[str, Any] = {
        "frameworks": list(selection.frameworks),
        "disclaimer": "self-assessment",
        "overrides": overrides,
        "notes": {k: v for k, v in selection.notes},
    }
    with open(path, "w", encoding="utf-8") as handle:
        yaml.safe_dump(payload, handle, sort_keys=False, allow_unicode=True)
    return path


def prompt_compliance_topics(
    *,
    input_fn: Any,
    out: TextIO,
    existing: ComplianceSelection | None = None,
) -> ComplianceSelection:
    current = existing or ComplianceSelection()
    default = ",".join(current.frameworks) if current.frameworks else "none"
    print(
        "Compliance topics (self-assessment, not a certification): "
        "iso27001, pci-dss, nis2, cra, gdpr — or none.",
        file=out,
    )
    raw = input_fn(f"Compliance topics [{default}]: ").strip()
    if raw == "":
        frameworks = current.frameworks
    else:
        frameworks = parse_frameworks(raw)
    return ComplianceSelection(
        frameworks=frameworks,
        overrides=current.overrides,
        notes=current.notes,
    )


def _paths_from_analysis(analysis: RepoAnalysis | None) -> tuple[str, ...]:
    if analysis is None:
        return ()
    found: list[str] = []
    found.extend(analysis.docs.readme_paths)
    found.extend(analysis.docs.other_docs)
    found.extend(analysis.docs.doc_dirs)
    found.extend(item.path for item in analysis.artifacts)
    found.extend(item.path for item in analysis.ci_workflows)
    found.extend(analysis.tests.paths)
    found.extend(item.path for item in analysis.build_files)
    found.extend(item.path for item in analysis.components)
    return tuple(dict.fromkeys(found))


def _match(paths: Sequence[str], *needles: str) -> tuple[str, ...]:
    hits: list[str] = []
    lowered = [(p, p.replace("\\", "/").casefold()) for p in paths]
    for needle in needles:
        n = needle.casefold()
        for original, low in lowered:
            if n in low and original not in hits:
                hits.append(original)
    return tuple(hits)


def _grade(hits: Sequence[str], *, strong: bool) -> str:
    if not hits:
        return "fail"
    if strong:
        return "pass"
    return "partial"


def _pillar_evidence(pillar: str, paths: Sequence[str], analysis: RepoAnalysis | None) -> tuple[str, tuple[str, ...]]:
    if pillar == "inventory":
        hits = _match(paths, "codeowners", "sbom", "architecture", "inventory")
        return _grade(hits, strong=any("codeowners" in p.casefold() for p in hits)), hits
    if pillar == "access":
        hits = _match(paths, "codeowners", "oauth", "oidc", "gitleaks", "trufflehog", "secret")
        return _grade(hits, strong=len(hits) >= 2), hits
    if pillar == "crypto":
        hits = _match(paths, "tls", "crypto", "kms", "vault")
        return _grade(hits, strong=bool(hits)), hits
    if pillar == "logging":
        hits = _match(paths, "log", "observab", "sentry", "opentelemetry")
        return _grade(hits, strong=len(hits) >= 2), hits
    if pillar == "vuln":
        hits = _match(
            paths,
            "dependabot",
            "renovate",
            "osv-scanner",
            "pip-audit",
            "govulncheck",
            "codeql",
            "snyk",
        )
        return _grade(hits, strong=bool(hits)), hits
    if pillar == "ssdlc":
        ci = bool(analysis and analysis.ci_workflows)
        tests = bool(analysis and analysis.tests.present)
        hits = _match(paths, ".github/workflows", "pytest", "test")
        if ci and tests:
            return "pass", hits or (".github/workflows",)
        if ci or tests:
            return "partial", hits
        return "fail", ()
    if pillar == "supply":
        hits = _match(paths, "sbom", "cyclonedx", "spdx", "syft")
        return _grade(hits, strong=bool(hits)), hits
    if pillar == "incident":
        hits = _match(paths, "security.md", "security/", "incident")
        strong = any(p.replace("\\", "/").casefold().endswith("security.md") for p in hits)
        return _grade(hits, strong=strong), hits
    if pillar == "continuity":
        hits = _match(paths, "backup", "restore", "disaster", "runbook")
        return _grade(hits, strong=len(hits) >= 2), hits
    if pillar == "privacy":
        hits = _match(paths, "privacy", "gdpr", "dpa", "ropa", "data-protection")
        return _grade(hits, strong=any("privacy" in p.casefold() for p in hits)), hits
    if pillar == "cde":
        hits = _match(paths, "pci", "cardholder", "cde", "pan")
        return _grade(hits, strong=len(hits) >= 2), hits
    if pillar == "governance":
        hits = _match(paths, "security.md", "policy", "governance", "contributing")
        strong = any("policy" in p.casefold() or "security.md" in p.casefold() for p in hits)
        return _grade(hits, strong=strong), hits
    if pillar == "training":
        hits = _match(paths, "training", "awareness", "security-guidelines")
        return _grade(hits, strong=bool(hits)), hits
    return "fail", ()


def score_matrix(
    selection: ComplianceSelection,
    analysis: RepoAnalysis | None,
) -> tuple[ComplianceCell, ...]:
    paths = _paths_from_analysis(analysis)
    override_map = {
        (fw, pillar): status for fw, pillar, status in selection.overrides
    }
    cells: list[ComplianceCell] = []
    in_scope = set(selection.frameworks)
    for pillar_id, _label, applies in PILLARS:
        auto_status, evidence = _pillar_evidence(pillar_id, paths, analysis)
        for framework in FRAMEWORKS:
            if framework not in in_scope or framework not in applies:
                cells.append(
                    ComplianceCell(
                        framework=framework,
                        pillar=pillar_id,
                        status="na",
                    )
                )
                continue
            status = auto_status
            overridden = False
            key = (framework, pillar_id)
            if key in override_map:
                status = override_map[key]
                overridden = True
            cells.append(
                ComplianceCell(
                    framework=framework,
                    pillar=pillar_id,
                    status=status,
                    evidence=evidence,
                    overridden=overridden,
                )
            )
    return tuple(cells)
