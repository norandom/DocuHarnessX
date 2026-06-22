"""The evidence-gated signal->cell rule table and coverage-matrix construction.

This is the *matrix* component of the deterministic planning core (task 2.2). It
builds the candidate coverage matrix as the set of role x intent cells drawn
**exclusively from the loaded, project-configurable**
:class:`~docuharnessx.ontology.Vocabulary` (never a hardcoded role/intent list,
Req 4.1, 4.2) and *activates* a cell only when an evidence predicate over the
upstream frozen :class:`~docuharnessx.analysis.model.RepoAnalysis` fires **and** both
the cell's role id and intent id are vocabulary members (Req 4.3).

Decision intelligence as data, not branches
--------------------------------------------
The mapping from analysis signals to relevant cells lives in the module-level
:data:`_RULE_TABLE` — a list of :class:`_Rule` records, each pairing one auditable
evidence *predicate* over the analysis with the ``(role id, intent id)`` *hint pairs*
it would activate, the subject-prefix *kinds* whose derived subjects attach to those
cells, and an *evidence builder* yielding the activating
:class:`~docuharnessx.planning.model.EvidenceRef`s. Extending the planner's
"decision intelligence" is editing this data table, not adding archetype-specific code
branches (design "matrix — Implementation Notes").

Vocabulary filtering happens at activation time: a rule's hint pair is realized into a
cell only when ``vocab.has_role(role)`` and ``vocab.has_intent(intent)`` both hold, so a
custom vocabulary (renamed terms, fewer/more intents, an extra subject prefix) yields a
different activated cell set with no code change (Req 4.2, 4.3). Rows whose ids are
absent from the loaded vocabulary are simply skipped.

The rule-table hint ids correspond to the shipped default profile's role/intent ids
(``tech-savvy-user``/``install`` etc.); they are the *signals the mapping knows how to
express*, not a closed vocabulary. A vocabulary that shares none of these ids activates
no cells — proving the matrix never falls back to a hardcoded set.

Output (Req 3.5, 4.4, 4.5, 5.4)
-------------------------------
:func:`activate_cells` returns one :class:`~docuharnessx.planning.model.CandidateCell`
per activated ``(role, intent)`` pair (its ``roles`` tuple holds the single activated
role id), carrying the derived subjects for the rule's subject kinds (sorted by
``Subject.canonical()``) and the merged activating evidence (sorted by ``(kind,
detail)``). Cells are ordered by ``vocab.intent_order()`` as the documented primary key,
then the vocabulary's declared role order, then the role id — a stable, total,
reproducible order (Req 4.4, 4.5). Pure and deterministic: identical analysis +
vocabulary inputs always yield the identical cell tuple. Model-free and
side-effect-free.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping

from docuharnessx.analysis.model import RepoAnalysis
from docuharnessx.ontology import Subject, Vocabulary
from docuharnessx.planning.model import CandidateCell, EvidenceRef

__all__ = ["activate_cells"]


# --------------------------------------------------------------------------- #
# Evidence predicates over the analysis (auditable, pure booleans)             #
# --------------------------------------------------------------------------- #


def _has_cli(analysis: RepoAnalysis) -> bool:
    """A CLI / console entrypoint is present (install/use/troubleshoot signal)."""
    if any(e.kind in {"cli", "console_script", "package_bin"} for e in analysis.entrypoints):
        return True
    if any(e.kind == "main" for e in analysis.entrypoints):
        return True
    return any(
        s.kind in {"cli_flag", "cli_subcommand"} for s in analysis.public_surface
    )


def _has_ci_and_build(analysis: RepoAnalysis) -> bool:
    """Both CI workflows AND build files are present (operate/monitor signal)."""
    return bool(analysis.ci_workflows) and bool(analysis.build_files)


def _has_tests(analysis: RepoAnalysis) -> bool:
    """Tests are present (contribute signal)."""
    return analysis.tests.present


def _has_public_surface(analysis: RepoAnalysis) -> bool:
    """A public/exported surface is present (extend signal)."""
    return bool(analysis.public_surface)


def _has_security_signal(analysis: RepoAnalysis) -> bool:
    """A security/compliance signal is present (assess-quality signal).

    The cheapest, most reliable cross-cutting signal is a license/compliance artifact
    (mirrors ``subjects._security_signal`` so the activated cell carries the matching
    ``topic:security`` subject).
    """
    return any(a.kind == "license" for a in analysis.artifacts)


def _has_integration_surface(analysis: RepoAnalysis) -> bool:
    """An integration surface is present (integrate signal).

    A package binary entrypoint or an exported symbol is a cheap API/integration
    signal.
    """
    if any(e.kind == "package_bin" for e in analysis.entrypoints):
        return True
    return any(s.kind == "exported_symbol" for s in analysis.public_surface)


def _has_docs(analysis: RepoAnalysis) -> bool:
    """Documentation (a README or a doc directory) is present (understand signal)."""
    return analysis.docs.has_readme or bool(analysis.docs.doc_dirs)


# --------------------------------------------------------------------------- #
# Evidence builders (the activating EvidenceRefs for a fired rule)             #
# --------------------------------------------------------------------------- #


def _cli_evidence(analysis: RepoAnalysis) -> tuple[EvidenceRef, ...]:
    refs: list[EvidenceRef] = []
    for entry in analysis.entrypoints:
        if entry.kind in {"cli", "console_script", "package_bin", "main"}:
            refs.append(EvidenceRef(kind="entrypoint", detail=entry.path))
    for symbol in analysis.public_surface:
        if symbol.kind in {"cli_flag", "cli_subcommand"}:
            refs.append(EvidenceRef(kind="cli", detail=symbol.source))
    return tuple(refs)


def _ci_and_build_evidence(analysis: RepoAnalysis) -> tuple[EvidenceRef, ...]:
    refs = [EvidenceRef(kind="ci", detail=ci.path) for ci in analysis.ci_workflows]
    refs += [
        EvidenceRef(kind="build", detail=build.path) for build in analysis.build_files
    ]
    return tuple(refs)


def _tests_evidence(analysis: RepoAnalysis) -> tuple[EvidenceRef, ...]:
    return tuple(
        EvidenceRef(kind="test", detail=path) for path in analysis.tests.paths
    ) or (EvidenceRef(kind="test", detail="tests"),)


def _public_surface_evidence(analysis: RepoAnalysis) -> tuple[EvidenceRef, ...]:
    return tuple(
        EvidenceRef(kind="public_surface", detail=s.source)
        for s in analysis.public_surface
    )


def _security_evidence(analysis: RepoAnalysis) -> tuple[EvidenceRef, ...]:
    return tuple(
        EvidenceRef(kind="artifact", detail=a.path)
        for a in analysis.artifacts
        if a.kind == "license"
    )


def _integration_evidence(analysis: RepoAnalysis) -> tuple[EvidenceRef, ...]:
    refs: list[EvidenceRef] = []
    for entry in analysis.entrypoints:
        if entry.kind == "package_bin":
            refs.append(EvidenceRef(kind="entrypoint", detail=entry.path))
    for symbol in analysis.public_surface:
        if symbol.kind == "exported_symbol":
            refs.append(EvidenceRef(kind="public_surface", detail=symbol.source))
    return tuple(refs)


def _docs_evidence(analysis: RepoAnalysis) -> tuple[EvidenceRef, ...]:
    refs = [EvidenceRef(kind="doc", detail=p) for p in analysis.docs.readme_paths]
    refs += [EvidenceRef(kind="doc", detail=p) for p in analysis.docs.doc_dirs]
    return tuple(refs)


# --------------------------------------------------------------------------- #
# The signal -> cell rule table (decision intelligence as data)               #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class _Rule:
    """One auditable signal->cell mapping row.

    ``predicate`` decides whether the rule's signal is present in the analysis;
    ``hints`` are the ``(role id, intent id)`` pairs the rule would activate (realized
    only for ids present in the loaded vocabulary); ``subject_kinds`` are the bare
    subject prefixes whose derived subjects attach to the activated cells; and
    ``evidence`` builds the activating :class:`EvidenceRef`s.
    """

    name: str
    predicate: Callable[[RepoAnalysis], bool]
    hints: tuple[tuple[str, str], ...]
    subject_kinds: tuple[str, ...]
    evidence: Callable[[RepoAnalysis], tuple[EvidenceRef, ...]]


# Hint ids correspond to the shipped default profile; they are signals the mapping
# expresses, NOT a closed vocabulary. Vocabulary-filtering at activation time means a
# custom vocabulary produces a different cell set with no edit here (Req 4.2, 4.3).
_RULE_TABLE: tuple[_Rule, ...] = (
    _Rule(
        name="cli_surface",
        predicate=_has_cli,
        hints=(
            ("tech-savvy-user", "install"),
            ("tech-savvy-user", "use"),
            ("tech-savvy-user", "troubleshoot"),
            ("possible-adopter", "evaluate"),
            ("manager", "evaluate"),
        ),
        subject_kinds=("component", "tech"),
        evidence=_cli_evidence,
    ),
    _Rule(
        name="ci_and_build",
        predicate=_has_ci_and_build,
        hints=(
            ("devops-admin", "operate"),
            ("devops-admin", "configure"),
            ("support-sre", "monitor"),
        ),
        subject_kinds=("artifact",),
        evidence=_ci_and_build_evidence,
    ),
    _Rule(
        name="tests",
        predicate=_has_tests,
        hints=(("contributor", "contribute"),),
        subject_kinds=("topic",),
        evidence=_tests_evidence,
    ),
    _Rule(
        name="public_surface",
        predicate=_has_public_surface,
        hints=(("developer", "extend"),),
        subject_kinds=("component", "tech"),
        evidence=_public_surface_evidence,
    ),
    _Rule(
        name="security",
        predicate=_has_security_signal,
        hints=(("security-compliance-officer", "assess-quality"),),
        subject_kinds=("topic", "artifact"),
        evidence=_security_evidence,
    ),
    _Rule(
        name="integration",
        predicate=_has_integration_surface,
        hints=(("integrator", "integrate"),),
        subject_kinds=("component", "tech"),
        evidence=_integration_evidence,
    ),
    _Rule(
        name="docs",
        predicate=_has_docs,
        hints=(("possible-adopter", "understand"),),
        subject_kinds=("topic",),
        evidence=_docs_evidence,
    ),
)


# --------------------------------------------------------------------------- #
# Activation                                                                   #
# --------------------------------------------------------------------------- #


def activate_cells(
    analysis: RepoAnalysis,
    vocab: Vocabulary,
    subjects_by_kind: Mapping[str, tuple[Subject, ...]],
) -> tuple[CandidateCell, ...]:
    """Activate vocabulary-valid role x intent cells from analysis evidence.

    Walks the module-level :data:`_RULE_TABLE`: for each rule whose evidence predicate
    fires, each ``(role id, intent id)`` hint is realized into an activation **only**
    when both ``vocab.has_role(role)`` and ``vocab.has_intent(intent)`` hold (Req 4.1,
    4.3) — so the candidate space is exactly ``vocab.roles x vocab.intents`` and rows
    whose ids are absent from the loaded vocabulary are skipped. When several rules
    activate the same ``(role, intent)`` pair, their subjects and evidence are merged.

    ``subjects_by_kind`` maps each bare subject prefix (``"component"`` / ``"tech"`` /
    ``"artifact"`` / ``"topic"`` ...) to the derived subjects of that prefix; the
    subjects a cell carries are those of the activating rule's ``subject_kinds`` (Req
    3.5, 5.4). Returns one :class:`CandidateCell` per activated ``(role, intent)`` pair,
    its ``roles`` tuple holding that single role id, with subjects sorted by
    ``Subject.canonical()`` and evidence sorted by ``(kind, detail)``. Cells are ordered
    by ``vocab.intent_order()``, then the vocabulary's declared role order, then the role
    id — a total, reproducible order (Req 4.4, 4.5). Never raises for "no evidence": an
    analysis matching no rule yields ``()`` (Req 5.5 support).
    """
    intent_rank = {intent: i for i, intent in enumerate(vocab.intent_order())}
    role_rank = {role.id: i for i, role in enumerate(vocab.roles)}

    # Accumulate per (role, intent) pair: deduped subjects (by canonical) and evidence.
    subjects_acc: dict[tuple[str, str], dict[str, Subject]] = {}
    evidence_acc: dict[tuple[str, str], dict[tuple[str, str], EvidenceRef]] = {}

    for rule in _RULE_TABLE:
        if not rule.predicate(analysis):
            continue
        rule_subjects = _subjects_for_kinds(subjects_by_kind, rule.subject_kinds)
        rule_evidence = rule.evidence(analysis)
        for role_id, intent_id in rule.hints:
            if not vocab.has_role(role_id) or not vocab.has_intent(intent_id):
                continue
            key = (role_id, intent_id)
            subj_bucket = subjects_acc.setdefault(key, {})
            for subject in rule_subjects:
                subj_bucket.setdefault(subject.canonical(), subject)
            ev_bucket = evidence_acc.setdefault(key, {})
            for ref in rule_evidence:
                ev_bucket.setdefault((ref.kind, ref.detail), ref)

    cells: list[CandidateCell] = []
    for (role_id, intent_id), subj_bucket in subjects_acc.items():
        subjects = tuple(
            subj_bucket[canon] for canon in sorted(subj_bucket)
        )
        ev_bucket = evidence_acc[(role_id, intent_id)]
        evidence = tuple(ev_bucket[key] for key in sorted(ev_bucket))
        cells.append(
            CandidateCell(
                roles=(role_id,),
                intent=intent_id,
                subjects=subjects,
                evidence=evidence,
            )
        )

    # Ordered by intent_order() (primary), then declared role order, then role id —
    # a stable, total, reproducible order (Req 4.4, 4.5).
    cells.sort(
        key=lambda c: (
            intent_rank[c.intent],
            role_rank.get(c.roles[0], len(role_rank)),
            c.roles[0],
        )
    )
    return tuple(cells)


def _subjects_for_kinds(
    subjects_by_kind: Mapping[str, tuple[Subject, ...]], kinds: tuple[str, ...]
) -> tuple[Subject, ...]:
    """Collect the subjects whose bare prefix is one of ``kinds`` (order-preserving)."""
    collected: list[Subject] = []
    for kind in kinds:
        collected.extend(subjects_by_kind.get(kind, ()))
    return tuple(collected)
