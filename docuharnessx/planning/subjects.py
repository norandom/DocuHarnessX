"""Derive typed ontology :class:`Subject` values from ``RepoAnalysis`` findings.

This is the *subjects* component of the deterministic planning core (task 2.1). It
maps the upstream frozen :class:`~docuharnessx.analysis.model.RepoAnalysis` onto typed
ontology :class:`~docuharnessx.ontology.Subject` values, **filtered by the loaded,
project-configurable** :class:`~docuharnessx.ontology.Vocabulary`'s subject prefixes —
so the subject namespace is project-specific, never hardcoded (design "subjects —
findings to typed Subjects"; Req 3.1-3.5).

Mapping (each only when its prefix is a member of ``vocab.subject_prefixes``, normalized
via :func:`~docuharnessx.ontology.normalize_prefix`):

* ``component:`` — components / structural modules from ``analysis.components``.
* ``tech:`` — detected languages (the FULL ``analysis.languages`` tuple, not solely
  ``primary_languages`` — a doc-heavy repo can report a markup language as primary, so
  programming/tech signals are taken from every detected language plus the test
  frameworks and declared dependencies; design planner-facing note).
* ``artifact:`` — build-file kinds, CI providers, and notable artifact kinds
  (license / dockerfile / schema / generated / ...).
* ``topic:`` — cross-cutting concerns *inferred* from signals (tests present →
  ``testing``; CI present → ``ci``; security/compliance signals → ``security``).

Every emitted subject is built via :meth:`Subject.parse` against the loaded vocabulary's
prefixes (so the local name is normalized/case-folded deterministically, Req 3.4) and is
paired with the :class:`~docuharnessx.planning.model.EvidenceRef` (finding kind + source
path/token) it was derived from (Req 3.5). A would-be subject whose prefix is absent from
the vocabulary is omitted, never emitted with a non-vocabulary prefix (Req 3.3).

Pure and deterministic: identical analysis + vocabulary inputs always yield the identical
ordered ``(Subject, EvidenceRef)`` pairs, sorted by ``Subject.canonical()`` (Req 3.4).
This module is model-free and side-effect-free; it imports only the upstream
``RepoAnalysis`` contract, the ontology ``Subject``/``Vocabulary``/``normalize_prefix``,
and this spec's :class:`EvidenceRef`.
"""

from __future__ import annotations

from docuharnessx.analysis.model import RepoAnalysis
from docuharnessx.ontology import Subject, Vocabulary, normalize_prefix
from docuharnessx.planning.model import EvidenceRef

__all__ = ["derive_subjects"]

# Canonical bare prefixes this component maps findings onto. Each is only ever used
# when it is also a member of the loaded vocabulary (Req 3.3) — this tuple is the set
# of prefixes the *mapping* knows how to populate, NOT a hardcoded vocabulary.
_COMPONENT = "component"
_TECH = "tech"
_ARTIFACT = "artifact"
_TOPIC = "topic"


def derive_subjects(
    analysis: RepoAnalysis, vocab: Vocabulary
) -> tuple[tuple[Subject, EvidenceRef], ...]:
    """Map ``analysis`` findings onto typed ontology subjects, vocab-prefix filtered.

    Returns a deterministically ordered tuple of ``(Subject, EvidenceRef)`` pairs,
    sorted by ``Subject.canonical()``, de-duplicated on the canonical string (the first
    finding contributing a given subject supplies its evidence, in the fixed iteration
    order below). Only prefixes present in ``vocab.subject_prefixes`` are ever emitted
    (Req 3.1-3.5). Never raises for "no findings" — an empty analysis (or a vocabulary
    with no relevant prefix) yields an empty tuple.
    """
    allowed = frozenset(normalize_prefix(p) for p in vocab.subject_prefixes)

    # Collect (prefix, local, evidence) candidates in a fixed, deterministic order.
    # Each candidate is realized into a Subject only when its prefix is in `allowed`.
    candidates: list[tuple[str, str, EvidenceRef]] = []

    # component: components / structural modules.
    for comp in analysis.components:
        candidates.append(
            (_COMPONENT, comp.name, EvidenceRef(kind="component", detail=comp.path))
        )

    # tech: every detected language (full tuple, not just primary), test frameworks,
    # and declared dependencies (a tech signal even when the language is shared).
    for lang in analysis.languages:
        candidates.append(
            (_TECH, lang.language, EvidenceRef(kind="language", detail=lang.language))
        )
    for framework in analysis.tests.frameworks:
        candidates.append(
            (_TECH, framework, EvidenceRef(kind="test", detail=framework))
        )
    for dep in analysis.dependencies:
        candidates.append(
            (_TECH, dep.name, EvidenceRef(kind="dependency", detail=dep.source))
        )

    # artifact: build-file kinds, CI providers, and notable artifact kinds.
    for build in analysis.build_files:
        candidates.append(
            (_ARTIFACT, build.kind, EvidenceRef(kind="build", detail=build.path))
        )
    for ci in analysis.ci_workflows:
        candidates.append(
            (_ARTIFACT, ci.provider, EvidenceRef(kind="ci", detail=ci.path))
        )
    for artifact in analysis.artifacts:
        candidates.append(
            (
                _ARTIFACT,
                artifact.kind,
                EvidenceRef(kind="artifact", detail=artifact.path),
            )
        )

    # topic: cross-cutting concerns inferred from signals.
    if analysis.tests.present:
        detail = analysis.tests.paths[0] if analysis.tests.paths else "tests"
        candidates.append((_TOPIC, "testing", EvidenceRef(kind="test", detail=detail)))
    if analysis.ci_workflows:
        candidates.append(
            (
                _TOPIC,
                "ci",
                EvidenceRef(kind="ci", detail=analysis.ci_workflows[0].path),
            )
        )
    security_evidence = _security_signal(analysis)
    if security_evidence is not None:
        candidates.append((_TOPIC, "security", security_evidence))

    # Realize candidates whose prefix is a vocabulary member, de-duplicate on the
    # canonical subject string (first occurrence wins its evidence), then sort.
    seen: dict[str, tuple[Subject, EvidenceRef]] = {}
    for prefix, local, evidence in candidates:
        if prefix not in allowed:
            continue
        if not local or not local.strip():
            continue
        subject = Subject.parse(f"{prefix}:{local}", allowed)
        canonical = subject.canonical()
        if canonical not in seen:
            seen[canonical] = (subject, evidence)

    return tuple(seen[key] for key in sorted(seen))


def _security_signal(analysis: RepoAnalysis) -> EvidenceRef | None:
    """Return the strongest security/compliance evidence, or ``None`` when absent.

    A ``topic:security`` concern is inferred from a license/compliance artifact (the
    cheapest, most reliable cross-cutting signal). The first matching artifact in the
    analysis's pre-sorted ``artifacts`` tuple supplies a deterministic evidence ref.
    """
    for artifact in analysis.artifacts:
        if artifact.kind == "license":
            return EvidenceRef(kind="artifact", detail=artifact.path)
    return None
