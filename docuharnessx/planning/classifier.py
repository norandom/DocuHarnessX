"""Compose subjects + matrix into a ``Classification`` (task 2.3, boundary: classifier).

This is the *classifier* component of the deterministic planning core. It is the single
composition step of the Classify stage: it reads the upstream frozen
:class:`~docuharnessx.analysis.model.RepoAnalysis` **verbatim** (consuming its published
fields/shapes exactly, never reimplementing or copying the model, Req 2.2) together with
the loaded, project-configurable :class:`~docuharnessx.ontology.Vocabulary`, and returns
a fully-populated :class:`~docuharnessx.planning.model.Classification` — the derived
subjects, the activated role x intent coverage cells with their evidence, and a
deterministic vocabulary fingerprint the plan inherits (design "classifier — RepoAnalysis
to Classification"; Req 2.1, 2.2, 3.1, 4.1).

It does no derivation of its own: subject derivation lives in
:func:`~docuharnessx.planning.subjects.derive_subjects` and cell activation in
:func:`~docuharnessx.planning.matrix.activate_cells`. The classifier only wires them
together (grouping the derived subjects by their bare prefix into the matrix-input shape),
computes the vocabulary fingerprint, and assembles the frozen handoff value object.

Version gating (Req 2.3)
------------------------
The consumed ``RepoAnalysis`` is contract-pinned to
:data:`~docuharnessx.analysis.model.REPO_ANALYSIS_SCHEMA_VERSION` (``== 1``). An analysis
declaring any other schema version is a fatal, unsupported input:
:func:`classify_repo` raises :class:`~docuharnessx.planning.model.PlanningInputError`
naming the offending version so the run halts with an identifiable cause rather than
classifying against a contract this build does not understand. (The
:class:`~docuharnessx.stages.classify.ClassifyStage` adapter additionally validates that
the analysis/vocabulary are present at all; this core function validates the version it
is handed.) No model, no network, no I/O — pure and deterministic: identical inputs always
yield an equal :class:`Classification` (Req 4.5).
"""

from __future__ import annotations

from docuharnessx.analysis.model import REPO_ANALYSIS_SCHEMA_VERSION, RepoAnalysis
from docuharnessx.ontology import Subject, Vocabulary
from docuharnessx.planning.matrix import activate_cells
from docuharnessx.planning.model import Classification, PlanningInputError
from docuharnessx.planning.subjects import derive_subjects

__all__ = ["classify_repo", "vocabulary_fingerprint"]

#: The single supported ``RepoAnalysis`` contract version (Req 2.3). Pinned to the
#: upstream authority so a contract bump there is a deliberate revalidation trigger here.
_SUPPORTED_ANALYSIS_SCHEMA_VERSION: int = REPO_ANALYSIS_SCHEMA_VERSION


def vocabulary_fingerprint(vocab: Vocabulary) -> str:
    """Return a deterministic, id-keyed digest of the loaded ``vocab``.

    The fingerprint identifies *which* project vocabulary a plan was built against. It is
    keyed on the **ids** of the loaded roles and intents (in their declared order) plus
    the normalized subject prefixes — never on the human-facing labels/descriptions, so a
    label-only edit does not invalidate a plan while a renamed/added/removed/reordered
    role, intent, or prefix does (mirrors the project-specificity contract: a different
    vocabulary yields a different fingerprint). Pure and deterministic: equal
    vocabularies always yield the identical string.

    The form is a plain, stable, human-readable token rather than a hash, so the
    fingerprint is auditable in the journal/serialized plan without a decoder:
    ``"roles=<id>,<id>;intents=<id>,<id>;subjects=<prefix>,<prefix>"``.
    """
    roles = ",".join(role.id for role in vocab.roles)
    intents = ",".join(vocab.intent_order())
    subjects = ",".join(p.strip().rstrip(":").strip().casefold() for p in vocab.subject_prefixes)
    return f"roles={roles};intents={intents};subjects={subjects}"


def _subjects_by_kind(
    derived: tuple[tuple[Subject, object], ...]
) -> dict[str, tuple[Subject, ...]]:
    """Group derived subjects by their bare prefix into the matrix-input shape.

    Each :class:`~docuharnessx.ontology.Subject` already carries its normalized bare
    ``prefix`` (``"component"`` / ``"tech"`` / ``"artifact"`` / ``"topic"`` / ...), which
    is exactly the key :func:`~docuharnessx.planning.matrix.activate_cells` expects in its
    ``subjects_by_kind`` mapping. Insertion order follows the canonical-sorted order of
    ``derived`` (from :func:`~docuharnessx.planning.subjects.derive_subjects`), so the
    grouping is deterministic.
    """
    grouped: dict[str, list[Subject]] = {}
    for subject, _evidence in derived:
        grouped.setdefault(subject.prefix, []).append(subject)
    return {prefix: tuple(subjects) for prefix, subjects in grouped.items()}


def classify_repo(analysis: RepoAnalysis, vocab: Vocabulary) -> Classification:
    """Classify ``analysis`` against ``vocab`` into a fully-populated ``Classification``.

    Pins the consumed ``RepoAnalysis`` to schema version
    :data:`~docuharnessx.analysis.model.REPO_ANALYSIS_SCHEMA_VERSION` (``== 1``); any other
    version raises :class:`~docuharnessx.planning.model.PlanningInputError` naming the
    offending version so the run halts with an identifiable cause rather than producing a
    partial plan (Req 2.3). For a supported analysis it:

    1. derives the typed ontology subjects (vocab-prefix filtered, evidence-attached) via
       :func:`~docuharnessx.planning.subjects.derive_subjects` (Req 3.1);
    2. groups them by bare prefix and activates the vocabulary-valid role x intent cells
       via :func:`~docuharnessx.planning.matrix.activate_cells` (Req 4.1);
    3. assembles a frozen :class:`~docuharnessx.planning.model.Classification` carrying the
       sorted subjects, the ordered activated cells, the ``repo_path`` (read verbatim from
       the analysis), and the deterministic :func:`vocabulary_fingerprint`.

    Consumes the ``RepoAnalysis`` model verbatim and reimplements neither it nor the
    subject/matrix logic (Req 2.2). Never raises for "no findings": an empty analysis (or a
    vocabulary that activates nothing) yields a well-formed ``Classification`` with empty
    ``subjects``/``cells`` (Req 5.5 support). Pure and deterministic: identical inputs always
    yield an equal ``Classification`` (Req 4.5).
    """
    if analysis.schema_version != _SUPPORTED_ANALYSIS_SCHEMA_VERSION:
        raise PlanningInputError(
            "unsupported RepoAnalysis schema_version "
            f"{analysis.schema_version!r}; this build understands version "
            f"{_SUPPORTED_ANALYSIS_SCHEMA_VERSION}"
        )

    derived = derive_subjects(analysis, vocab)
    subjects = tuple(subject for subject, _evidence in derived)
    cells = activate_cells(analysis, vocab, _subjects_by_kind(derived))

    return Classification(
        repo_path=analysis.repo_path,
        vocabulary_fingerprint=vocabulary_fingerprint(vocab),
        subjects=subjects,
        cells=cells,
    )
