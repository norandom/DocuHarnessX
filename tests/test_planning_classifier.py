"""Unit tests for the classifier (task 2.3, boundary: classifier).

These tests pin ``docuharnessx.planning.classifier.classify_repo``: the composition
step that consumes the upstream frozen
:class:`~docuharnessx.analysis.model.RepoAnalysis` **verbatim** (schema_version == 1)
plus the loaded, project-configurable :class:`~docuharnessx.ontology.Vocabulary`, and
returns a fully-populated :class:`~docuharnessx.planning.model.Classification` — the
subjects + activated coverage cells + evidence + a deterministic vocabulary
fingerprint — by delegating to the ``subjects`` and ``matrix`` components without
reimplementing either model.

Observable completion (tasks.md 2.3):

* ``classify_repo`` over a crafted analysis returns a ``Classification`` whose
  subjects and cells match the component outputs;
* it is identical across two runs over equal inputs;
* it references only ``RepoAnalysis`` fields defined by the upstream contract;
* an unsupported ``RepoAnalysis.schema_version`` raises ``PlanningInputError``.

Requirements: 2.1, 2.2, 3.1, 4.1.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from docuharnessx.analysis.model import (
    Artifact,
    BuildFile,
    CIWorkflow,
    Component,
    Dependency,
    DocPresence,
    Entrypoint,
    LanguageStat,
    PublicSymbol,
    RepoAnalysis,
    ScanStats,
)
from docuharnessx.analysis.model import TestLayout as _TestLayout  # noqa: N813
from docuharnessx.ontology import (
    AxisTerm,
    Subject,
    Vocabulary,
    default_profile,
    normalize_prefix,
)
from docuharnessx.planning.classifier import classify_repo
from docuharnessx.planning.matrix import activate_cells
from docuharnessx.planning.model import (
    CandidateCell,
    Classification,
    PlanningError,
    PlanningInputError,
)
from docuharnessx.planning.subjects import derive_subjects


# --------------------------------------------------------------------------- #
# Fixtures                                                                     #
# --------------------------------------------------------------------------- #


def _empty_analysis() -> RepoAnalysis:
    return RepoAnalysis(
        schema_version=1,
        repo_path="/repo/empty",
        languages=(),
        primary_languages=(),
        total_loc=0,
        total_files=0,
        structure=(),
        entrypoints=(),
        build_files=(),
        ci_workflows=(),
        tests=_TestLayout(present=False, frameworks=(), paths=()),
        dependencies=(),
        components=(),
        public_surface=(),
        docs=DocPresence(
            has_readme=False, readme_paths=(), doc_dirs=(), other_docs=()
        ),
        artifacts=(),
        scan_stats=ScanStats(
            files_scanned=0,
            files_skipped=0,
            bytes_scanned=0,
            limit_reached=False,
            notes=(),
        ),
    )


def _full_analysis() -> RepoAnalysis:
    """A Go-CLI-shaped analysis exercising several rule-table predicates."""
    return replace(
        _empty_analysis(),
        repo_path="/repo/malware_hashes",
        languages=(
            LanguageStat(language="Go", files=12, loc=3400),
            LanguageStat(language="Markdown", files=8, loc=1200),
        ),
        primary_languages=("Go",),
        total_loc=4600,
        total_files=20,
        entrypoints=(Entrypoint(path="cmd/mh/main.go", kind="cli", name="mh"),),
        build_files=(BuildFile(path="go.mod", kind="go_mod"),),
        ci_workflows=(
            CIWorkflow(path=".github/workflows/ci.yml", provider="github_actions"),
        ),
        tests=_TestLayout(
            present=True, frameworks=("go_testing",), paths=("hash_test.go",)
        ),
        dependencies=(
            Dependency(
                name="cobra",
                version_spec="v1.8.0",
                source="go.mod",
                scope="runtime",
            ),
        ),
        components=(
            Component(
                name="hashing",
                path="internal/hashing",
                representative_files=("internal/hashing/hash.go",),
            ),
        ),
        public_surface=(
            PublicSymbol(name="scan", kind="cli_subcommand", source="cmd/mh/main.go"),
            PublicSymbol(name="Hash", kind="exported_symbol", source="internal/hashing/hash.go"),
        ),
        docs=DocPresence(
            has_readme=True,
            readme_paths=("README.md",),
            doc_dirs=(),
            other_docs=(),
        ),
        artifacts=(Artifact(path="LICENSE", kind="license"),),
    )


def _subjects_by_kind(
    analysis: RepoAnalysis, vocab: Vocabulary
) -> dict[str, tuple[Subject, ...]]:
    """Independent reimplementation of the matrix-input grouping (test oracle)."""
    grouped: dict[str, list[Subject]] = {}
    for subject, _evidence in derive_subjects(analysis, vocab):
        grouped.setdefault(subject.prefix, []).append(subject)
    return {prefix: tuple(subjects) for prefix, subjects in grouped.items()}


def _custom_vocab() -> Vocabulary:
    """A renamed-term vocabulary that shares no ids with the default profile."""
    return Vocabulary(
        roles=(
            AxisTerm("operator", "Operator", "Runs the thing."),
            AxisTerm("buyer", "Buyer", "Decides to adopt."),
        ),
        intents=(
            AxisTerm("setup", "Set Up", "Get it running."),
            AxisTerm("review", "Review", "Judge it."),
        ),
        subject_prefixes=("component:", "tech:"),
    )


# --------------------------------------------------------------------------- #
# Shape: returns a fully-populated Classification                              #
# --------------------------------------------------------------------------- #


def test_returns_classification() -> None:
    result = classify_repo(_full_analysis(), default_profile())
    assert isinstance(result, Classification)


def test_classification_carries_repo_path_verbatim() -> None:
    analysis = _full_analysis()
    result = classify_repo(analysis, default_profile())
    assert result.repo_path == analysis.repo_path


def test_subjects_match_subjects_component_output() -> None:
    analysis = _full_analysis()
    vocab = default_profile()
    result = classify_repo(analysis, vocab)
    expected = tuple(subject for subject, _ev in derive_subjects(analysis, vocab))
    assert result.subjects == expected


def test_subjects_sorted_by_canonical() -> None:
    result = classify_repo(_full_analysis(), default_profile())
    canon = [s.canonical() for s in result.subjects]
    assert canon == sorted(canon)


def test_cells_match_matrix_component_output() -> None:
    analysis = _full_analysis()
    vocab = default_profile()
    result = classify_repo(analysis, vocab)
    expected = activate_cells(analysis, vocab, _subjects_by_kind(analysis, vocab))
    assert result.cells == expected


def test_cells_are_candidate_cells() -> None:
    result = classify_repo(_full_analysis(), default_profile())
    assert all(isinstance(cell, CandidateCell) for cell in result.cells)
    assert len(result.cells) > 0


def test_fingerprint_is_non_empty_string() -> None:
    result = classify_repo(_full_analysis(), default_profile())
    assert isinstance(result.vocabulary_fingerprint, str)
    assert result.vocabulary_fingerprint != ""


# --------------------------------------------------------------------------- #
# Determinism                                                                  #
# --------------------------------------------------------------------------- #


def test_identical_across_two_runs() -> None:
    analysis = _full_analysis()
    vocab = default_profile()
    assert classify_repo(analysis, vocab) == classify_repo(analysis, vocab)


def test_identical_for_freshly_built_equal_inputs() -> None:
    first = classify_repo(_full_analysis(), default_profile())
    second = classify_repo(_full_analysis(), default_profile())
    assert first == second
    assert first.vocabulary_fingerprint == second.vocabulary_fingerprint


# --------------------------------------------------------------------------- #
# Empty analysis -> well-formed empty Classification (no raise)               #
# --------------------------------------------------------------------------- #


def test_empty_analysis_yields_empty_subjects_and_cells() -> None:
    result = classify_repo(_empty_analysis(), default_profile())
    assert result.subjects == ()
    assert result.cells == ()
    assert result.repo_path == "/repo/empty"
    assert result.vocabulary_fingerprint != ""


# --------------------------------------------------------------------------- #
# Configurability: a custom vocabulary changes the output                      #
# --------------------------------------------------------------------------- #


def test_custom_vocab_produces_no_default_ids() -> None:
    analysis = _full_analysis()
    result = classify_repo(analysis, _custom_vocab())
    # Custom vocab shares no role/intent ids with the default profile, so no cell
    # activates -> empty cells; and only component:/tech: subjects are derivable.
    assert result.cells == ()
    for subject in result.subjects:
        assert subject.prefix in {"component", "tech"}


def test_custom_vocab_fingerprint_differs_from_default() -> None:
    analysis = _full_analysis()
    default_fp = classify_repo(analysis, default_profile()).vocabulary_fingerprint
    custom_fp = classify_repo(analysis, _custom_vocab()).vocabulary_fingerprint
    assert default_fp != custom_fp


def test_fingerprint_changes_when_roles_renamed() -> None:
    analysis = _full_analysis()
    base = default_profile()
    renamed = replace(
        base,
        roles=base.roles[:-1]
        + (AxisTerm("renamed-role", "Renamed", "x"),),
    )
    assert (
        classify_repo(analysis, base).vocabulary_fingerprint
        != classify_repo(analysis, renamed).vocabulary_fingerprint
    )


def test_fingerprint_stable_for_label_only_change() -> None:
    """The fingerprint is keyed on ids (+ prefixes), not human labels."""
    analysis = _full_analysis()
    base = default_profile()
    relabeled_roles = tuple(
        replace(r, label=r.label + " (relabeled)") for r in base.roles
    )
    relabeled = replace(base, roles=relabeled_roles)
    assert (
        classify_repo(analysis, base).vocabulary_fingerprint
        == classify_repo(analysis, relabeled).vocabulary_fingerprint
    )


# --------------------------------------------------------------------------- #
# Version gating: unsupported RepoAnalysis schema version -> PlanningInputError #
# --------------------------------------------------------------------------- #


def test_unsupported_schema_version_raises_planning_input_error() -> None:
    analysis = replace(_full_analysis(), schema_version=2)
    with pytest.raises(PlanningInputError):
        classify_repo(analysis, default_profile())


def test_unsupported_schema_version_error_names_version() -> None:
    analysis = replace(_full_analysis(), schema_version=99)
    with pytest.raises(PlanningInputError) as excinfo:
        classify_repo(analysis, default_profile())
    assert "99" in str(excinfo.value)


def test_planning_input_error_is_planning_error() -> None:
    analysis = replace(_full_analysis(), schema_version=0)
    with pytest.raises(PlanningError):
        classify_repo(analysis, default_profile())


def test_supported_version_one_does_not_raise() -> None:
    # schema_version == 1 is accepted (the supported version pin).
    result = classify_repo(_full_analysis(), default_profile())
    assert isinstance(result, Classification)


# --------------------------------------------------------------------------- #
# Verbatim consumption: cells carry the same subjects the matrix attaches       #
# --------------------------------------------------------------------------- #


def test_cells_carry_evidence_and_subjects() -> None:
    result = classify_repo(_full_analysis(), default_profile())
    # At least one activated cell, and every cell carries activating evidence.
    assert result.cells
    assert all(cell.evidence for cell in result.cells)


def test_classifier_uses_full_language_tuple_for_tech_subjects() -> None:
    """tech: subjects come from the FULL languages tuple, not solely primary."""
    analysis = _full_analysis()  # primary is Go; Markdown is also present
    result = classify_repo(analysis, default_profile())
    tech_locals = {s.local for s in result.subjects if s.prefix == "tech"}
    assert normalize_prefix("tech")  # sanity
    assert "go" in tech_locals
    assert "markdown" in tech_locals
