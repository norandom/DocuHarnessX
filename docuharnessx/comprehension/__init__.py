"""Depth-assigned visuals, glossary, and compliance self-assessment."""

from __future__ import annotations

from docuharnessx.comprehension.compliance import (
    COMPLIANCE_RELPATH,
    FRAMEWORKS,
    ComplianceCell,
    ComplianceSelection,
    load_compliance,
    prompt_compliance_topics,
    save_compliance,
    score_matrix,
)
from docuharnessx.comprehension.detect import detect_comprehension
from docuharnessx.comprehension.glossary import (
    GLOSSARY_RELPATH,
    Glossary,
    GlossaryTerm,
    load_glossary,
    merge_glossary,
    save_glossary,
    seed_glossary,
)
from docuharnessx.comprehension.architecture import (
    build_architecture_model,
    detect_architectures,
    page_abstraction,
)
from docuharnessx.comprehension.signals import (
    AbstractionLevel,
    ArchitectureBand,
    ArchitectureEdge,
    ArchitectureModel,
    ArchitectureNode,
    ArchitectureStyle,
    ComprehensionSignals,
    DagNode,
    LineageHop,
    PipelineDag,
    RequirementHit,
)

__all__ = [
    "COMPLIANCE_RELPATH",
    "FRAMEWORKS",
    "GLOSSARY_RELPATH",
    "ComplianceCell",
    "ComplianceSelection",
    "AbstractionLevel",
    "ArchitectureBand",
    "ArchitectureEdge",
    "ArchitectureModel",
    "ArchitectureNode",
    "ArchitectureStyle",
    "ComprehensionSignals",
    "DagNode",
    "Glossary",
    "GlossaryTerm",
    "LineageHop",
    "PipelineDag",
    "RequirementHit",
    "build_architecture_model",
    "detect_architectures",
    "detect_comprehension",
    "page_abstraction",
    "load_compliance",
    "load_glossary",
    "merge_glossary",
    "prompt_compliance_topics",
    "save_compliance",
    "save_glossary",
    "score_matrix",
    "seed_glossary",
]
