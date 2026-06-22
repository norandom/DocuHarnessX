"""Unit tests for the evidence-gated coverage matrix (task 2.2).

These tests pin the *matrix* boundary of the classification-coverage-planner:
``docuharnessx.planning.matrix.activate_cells`` builds the candidate role x intent
coverage matrix over the LOADED, project-configurable
:class:`~docuharnessx.ontology.Vocabulary` and activates a cell only when an evidence
predicate over the upstream frozen
:class:`~docuharnessx.analysis.model.RepoAnalysis` fires *and* both the cell's role
id and intent id are vocabulary members.

Observable completion (tasks.md 2.2):

* a ``RepoAnalysis`` with a CLI entrypoint activates install/use/troubleshoot cells
  for the matching user role;
* a vocabulary lacking those intents produces no such cells;
* repeated runs over equal inputs return identical cells.

Requirements: 4.1, 4.2, 4.3, 4.4, 4.5.
"""

from __future__ import annotations

from dataclasses import replace

from docuharnessx.analysis.model import (
    Artifact,
    BuildFile,
    CIWorkflow,
    Component,
    Dependency,
    DirectorySummary,
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
from docuharnessx.planning.model import CandidateCell, EvidenceRef
from docuharnessx.planning.matrix import activate_cells
from docuharnessx.planning.subjects import derive_subjects


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #


def _subjects_by_kind(
    analysis: RepoAnalysis, vocab: Vocabulary
) -> dict[str, tuple[Subject, ...]]:
    """Group the derived subjects by their (bare) prefix, matrix-input shape."""
    grouped: dict[str, list[Subject]] = {}
    for subject, _evidence in derive_subjects(analysis, vocab):
        grouped.setdefault(subject.prefix, []).append(subject)
    return {prefix: tuple(subjects) for prefix, subjects in grouped.items()}


def _activate(analysis: RepoAnalysis, vocab: Vocabulary) -> tuple[CandidateCell, ...]:
    return activate_cells(analysis, vocab, _subjects_by_kind(analysis, vocab))


def _pairs(cells: tuple[CandidateCell, ...]) -> set[tuple[str, str]]:
    """Flatten cells into the set of (role id, intent id) pairs they cover."""
    return {(role, cell.intent) for cell in cells for role in cell.roles}


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


def _cli_analysis() -> RepoAnalysis:
    """An analysis with a CLI entrypoint + public CLI surface (and nothing else)."""
    return replace(
        _empty_analysis(),
        repo_path="/repo/cli",
        languages=(LanguageStat(language="Go", files=4, loc=900),),
        primary_languages=("Go",),
        total_loc=900,
        total_files=4,
        entrypoints=(Entrypoint(path="cmd/mh/main.go", kind="cli", name="mh"),),
        public_surface=(
            PublicSymbol(name="scan", kind="cli_subcommand", source="cmd/mh/main.go"),
        ),
    )


def _full_analysis() -> RepoAnalysis:
    """A polyglot Go CLI shaped analysis exercising every rule-table predicate."""
    return RepoAnalysis(
        schema_version=1,
        repo_path="/repo/malware_hashes",
        languages=(
            LanguageStat(language="Go", files=12, loc=3400),
            LanguageStat(language="Markdown", files=8, loc=1200),
            LanguageStat(language="YAML", files=3, loc=140),
        ),
        primary_languages=("Go",),
        total_loc=4740,
        total_files=23,
        structure=(
            DirectorySummary(path="", file_count=23, dominant_language="Go", role="source"),
        ),
        entrypoints=(Entrypoint(path="cmd/mh/main.go", kind="main", name=""),),
        build_files=(BuildFile(path="go.mod", kind="go_mod"),),
        ci_workflows=(
            CIWorkflow(path=".github/workflows/ci.yml", provider="github_actions"),
        ),
        tests=_TestLayout(
            present=True,
            frameworks=("go_testing",),
            paths=("internal/hashing/hash_test.go",),
        ),
        dependencies=(
            Dependency(
                name="github.com/spf13/cobra",
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
            doc_dirs=("docs",),
            other_docs=(),
        ),
        artifacts=(
            Artifact(path="LICENSE", kind="license"),
            Artifact(path="Dockerfile", kind="dockerfile"),
        ),
        scan_stats=ScanStats(
            files_scanned=23,
            files_skipped=0,
            bytes_scanned=100_000,
            limit_reached=False,
            notes=(),
        ),
    )


# --------------------------------------------------------------------------- #
# Return shape (Req 4.1)                                                        #
# --------------------------------------------------------------------------- #


def test_returns_tuple_of_candidate_cells() -> None:
    cells = _activate(_full_analysis(), default_profile())
    assert isinstance(cells, tuple)
    assert cells
    for cell in cells:
        assert isinstance(cell, CandidateCell)
        assert isinstance(cell.roles, tuple) and cell.roles
        assert isinstance(cell.intent, str) and cell.intent
        assert isinstance(cell.subjects, tuple)
        assert isinstance(cell.evidence, tuple)


def test_every_cell_role_and_intent_are_vocabulary_members() -> None:
    vocab = default_profile()
    for cell in _activate(_full_analysis(), vocab):
        assert vocab.has_intent(cell.intent)
        for role in cell.roles:
            assert vocab.has_role(role)


# --------------------------------------------------------------------------- #
# CLI entrypoint -> install/use/troubleshoot for the user role (tasks.md 2.2)  #
# --------------------------------------------------------------------------- #


def test_cli_entrypoint_activates_install_use_troubleshoot_for_user_role() -> None:
    cells = _activate(_cli_analysis(), default_profile())
    pairs = _pairs(cells)
    for intent in ("install", "use", "troubleshoot"):
        assert ("tech-savvy-user", intent) in pairs


def test_cli_entrypoint_also_activates_adopter_and_manager_evaluate() -> None:
    cells = _activate(_cli_analysis(), default_profile())
    pairs = _pairs(cells)
    assert ("possible-adopter", "evaluate") in pairs
    assert ("manager", "evaluate") in pairs


# --------------------------------------------------------------------------- #
# Vocabulary lacking the intents produces no such cells (tasks.md 2.2, Req 4.3) #
# --------------------------------------------------------------------------- #


def test_vocabulary_lacking_intents_produces_no_such_cells() -> None:
    base = default_profile()
    kept = tuple(
        i for i in base.intents if i.id not in {"install", "use", "troubleshoot"}
    )
    vocab = replace(base, intents=kept)
    cells = _activate(_cli_analysis(), vocab)
    pairs = _pairs(cells)
    for intent in ("install", "use", "troubleshoot"):
        assert all(p[1] != intent for p in pairs)
    # No cell ever carries an intent absent from the vocabulary.
    for cell in cells:
        assert vocab.has_intent(cell.intent)


def test_vocabulary_lacking_a_role_skips_that_rows_cells() -> None:
    base = default_profile()
    kept = tuple(r for r in base.roles if r.id != "tech-savvy-user")
    vocab = replace(base, roles=kept)
    cells = _activate(_cli_analysis(), vocab)
    pairs = _pairs(cells)
    assert all(p[0] != "tech-savvy-user" for p in pairs)
    for cell in cells:
        for role in cell.roles:
            assert vocab.has_role(role)


# --------------------------------------------------------------------------- #
# Other rule-table predicates (Req 4.3)                                        #
# --------------------------------------------------------------------------- #


def test_ci_and_build_activate_operate_and_monitor_cells() -> None:
    pairs = _pairs(_activate(_full_analysis(), default_profile()))
    assert ("devops-admin", "operate") in pairs
    assert ("support-sre", "monitor") in pairs
    assert ("devops-admin", "configure") in pairs


def test_tests_and_public_surface_activate_contribute_and_extend() -> None:
    pairs = _pairs(_activate(_full_analysis(), default_profile()))
    assert ("contributor", "contribute") in pairs
    assert ("developer", "extend") in pairs


def test_security_signal_activates_assess_quality() -> None:
    pairs = _pairs(_activate(_full_analysis(), default_profile()))
    assert ("security-compliance-officer", "assess-quality") in pairs


def test_integration_surface_activates_integrate() -> None:
    pairs = _pairs(_activate(_full_analysis(), default_profile()))
    assert ("integrator", "integrate") in pairs


def test_docs_activate_understand_for_adopter() -> None:
    pairs = _pairs(_activate(_full_analysis(), default_profile()))
    assert ("possible-adopter", "understand") in pairs


# --------------------------------------------------------------------------- #
# Empty analysis -> no cells, never raises (Req 5.5 boundary support)           #
# --------------------------------------------------------------------------- #


def test_empty_analysis_yields_no_cells() -> None:
    assert _activate(_empty_analysis(), default_profile()) == ()


def test_build_files_alone_without_ci_do_not_activate_operate() -> None:
    # The CI+build rule requires BOTH CI workflows and build files (design).
    analysis = replace(
        _empty_analysis(),
        build_files=(BuildFile(path="go.mod", kind="go_mod"),),
    )
    pairs = _pairs(_activate(analysis, default_profile()))
    assert ("devops-admin", "operate") not in pairs


# --------------------------------------------------------------------------- #
# Evidence + subjects attached to activated cells (Req 3.5, 5.4)                #
# --------------------------------------------------------------------------- #


def test_activated_cells_carry_evidence() -> None:
    for cell in _activate(_full_analysis(), default_profile()):
        assert cell.evidence
        for ref in cell.evidence:
            assert isinstance(ref, EvidenceRef)
            assert ref.kind and ref.detail


def test_evidence_is_sorted_by_kind_then_detail() -> None:
    for cell in _activate(_full_analysis(), default_profile()):
        keys = [(e.kind, e.detail) for e in cell.evidence]
        assert keys == sorted(keys)


def test_security_cell_carries_security_topic_subject() -> None:
    cells = _activate(_full_analysis(), default_profile())
    sec = [
        c
        for c in cells
        if c.intent == "assess-quality"
        and "security-compliance-officer" in c.roles
    ]
    assert sec
    canon = {s.canonical() for c in sec for s in c.subjects}
    assert "topic:security" in canon


# --------------------------------------------------------------------------- #
# Ordering: vocab.intent_order() as a stable secondary key (Req 4.4)            #
# --------------------------------------------------------------------------- #


def test_cells_ordered_by_intent_order() -> None:
    vocab = default_profile()
    cells = _activate(_full_analysis(), vocab)
    order = vocab.intent_order()
    rank = {intent: i for i, intent in enumerate(order)}
    intent_ranks = [rank[c.intent] for c in cells]
    assert intent_ranks == sorted(intent_ranks)


# --------------------------------------------------------------------------- #
# Determinism (tasks.md 2.2, Req 4.5)                                          #
# --------------------------------------------------------------------------- #


def test_deterministic_across_repeated_runs() -> None:
    a = _activate(_full_analysis(), default_profile())
    b = _activate(_full_analysis(), default_profile())
    assert a == b


def test_subjects_within_cell_sorted_by_canonical() -> None:
    for cell in _activate(_full_analysis(), default_profile()):
        canon = [s.canonical() for s in cell.subjects]
        assert canon == sorted(canon)


# --------------------------------------------------------------------------- #
# Project-configurability: custom vocabulary terms drive the matrix (Req 4.2)   #
# --------------------------------------------------------------------------- #


def test_custom_vocabulary_with_no_matching_ids_yields_no_cells() -> None:
    # A vocabulary whose role/intent ids share none of the rule-table hint ids
    # activates nothing, proving the matrix never falls back to hardcoded ids.
    vocab = Vocabulary(
        roles=(AxisTerm("reader", "Reader", ""),),
        intents=(AxisTerm("skim", "Skim", ""),),
        subject_prefixes=("component:", "tech:", "artifact:", "topic:"),
    )
    cells = activate_cells(_full_analysis(), vocab, {})
    assert cells == ()


def test_custom_vocabulary_only_emits_custom_ids() -> None:
    # Rename the user role + install intent to custom ids matching the rule hints
    # would NOT fire (hints are fixed ids); instead prove the emitted ids are
    # strictly drawn from the loaded vocabulary by intersecting with a renamed set.
    base = default_profile()
    # Drop everything except a single role+intent that the rule table references.
    roles = tuple(r for r in base.roles if r.id == "tech-savvy-user")
    intents = tuple(i for i in base.intents if i.id == "install")
    vocab = replace(base, roles=roles, intents=intents)
    cells = _activate(_cli_analysis(), vocab)
    pairs = _pairs(cells)
    assert pairs == {("tech-savvy-user", "install")}
