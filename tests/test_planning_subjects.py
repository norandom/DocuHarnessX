"""Unit tests for typed-Subject derivation from ``RepoAnalysis`` (task 2.1).

These tests pin the *subjects* boundary of the classification-coverage-planner:
``docuharnessx.planning.subjects.derive_subjects`` maps the upstream frozen
:class:`~docuharnessx.analysis.model.RepoAnalysis` findings onto typed ontology
:class:`~docuharnessx.ontology.Subject` values, prefix-filtered against the loaded,
project-configurable :class:`~docuharnessx.ontology.Vocabulary`.

Observable completion (tasks.md 2.1):

* given a crafted ``RepoAnalysis`` and the default vocabulary, the function returns
  deterministically ordered ``(Subject, EvidenceRef)`` pairs;
* given a vocabulary missing the ``topic:`` prefix, no ``topic:`` subjects are
  returned.

Requirements: 3.1, 3.2, 3.3, 3.4, 3.5.
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
    Subject,
    Vocabulary,
    default_profile,
    normalize_prefix,
)
from docuharnessx.planning.model import EvidenceRef
from docuharnessx.planning.subjects import derive_subjects


# --------------------------------------------------------------------------- #
# Crafted RepoAnalysis fixtures                                                #
# --------------------------------------------------------------------------- #


def _full_analysis() -> RepoAnalysis:
    """A polyglot Go CLI shaped analysis exercising every subject mapping path."""
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
            DirectorySummary(
                path="internal/hashing",
                file_count=4,
                dominant_language="Go",
                role="source",
            ),
        ),
        entrypoints=(
            Entrypoint(path="cmd/mh/main.go", kind="main", name=""),
        ),
        build_files=(
            BuildFile(path="go.mod", kind="go_mod"),
            BuildFile(path=".dagger/go.mod", kind="go_mod"),
        ),
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
            Component(
                name="scanner",
                path="internal/scanner",
                representative_files=("internal/scanner/scan.go",),
            ),
        ),
        public_surface=(
            PublicSymbol(name="scan", kind="cli_subcommand", source="cmd/mh/main.go"),
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
            Artifact(path="schema/event.json", kind="schema"),
            Artifact(path="internal/hashing/zz_generated.go", kind="generated"),
        ),
        scan_stats=ScanStats(
            files_scanned=23,
            files_skipped=0,
            bytes_scanned=100_000,
            limit_reached=False,
            notes=(),
        ),
    )


def _empty_analysis() -> RepoAnalysis:
    """An analysis with no actionable findings (every detection category empty)."""
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


def _prefixes_of(pairs: tuple[tuple[Subject, EvidenceRef], ...]) -> set[str]:
    return {subj.prefix for subj, _ in pairs}


def _canonicals(pairs: tuple[tuple[Subject, EvidenceRef], ...]) -> list[str]:
    return [subj.canonical() for subj, _ in pairs]


# --------------------------------------------------------------------------- #
# Return shape and types                                                       #
# --------------------------------------------------------------------------- #


def test_returns_tuple_of_subject_evidence_pairs() -> None:
    pairs = derive_subjects(_full_analysis(), default_profile())
    assert isinstance(pairs, tuple)
    assert pairs  # non-empty for the full analysis
    for item in pairs:
        assert isinstance(item, tuple) and len(item) == 2
        subj, ev = item
        assert isinstance(subj, Subject)
        assert isinstance(ev, EvidenceRef)


def test_subjects_are_well_formed_ontology_subjects() -> None:
    # Every emitted subject is parseable back from its canonical form against the
    # loaded vocabulary's prefixes (Req 3.1) — i.e. it is genuinely well-formed.
    vocab = default_profile()
    allowed = frozenset(normalize_prefix(p) for p in vocab.subject_prefixes)
    for subj, _ in derive_subjects(_full_analysis(), vocab):
        assert Subject.parse(subj.canonical(), allowed) == subj


# --------------------------------------------------------------------------- #
# Mapping: each finding category to its prefix (Req 3.2)                        #
# --------------------------------------------------------------------------- #


def test_components_map_to_component_prefix() -> None:
    pairs = derive_subjects(_full_analysis(), default_profile())
    canon = _canonicals(pairs)
    assert "component:hashing" in canon
    assert "component:scanner" in canon


def test_languages_map_to_tech_prefix() -> None:
    pairs = derive_subjects(_full_analysis(), default_profile())
    canon = _canonicals(pairs)
    # Derived from the FULL languages tuple, not solely primary_languages.
    assert "tech:go" in canon


def test_frameworks_map_to_tech_prefix() -> None:
    pairs = derive_subjects(_full_analysis(), default_profile())
    canon = _canonicals(pairs)
    assert "tech:go_testing" in canon


def test_dependencies_inform_tech_subjects() -> None:
    pairs = derive_subjects(_full_analysis(), default_profile())
    canon = _canonicals(pairs)
    # Cobra is a declared dependency -> tech subject keyed off its name.
    assert any(c.startswith("tech:") and "cobra" in c for c in canon)


def test_build_files_map_to_artifact_prefix() -> None:
    pairs = derive_subjects(_full_analysis(), default_profile())
    canon = _canonicals(pairs)
    assert "artifact:go_mod" in canon


def test_ci_maps_to_artifact_prefix() -> None:
    pairs = derive_subjects(_full_analysis(), default_profile())
    canon = _canonicals(pairs)
    assert any(c.startswith("artifact:") and "github_actions" in c for c in canon)


def test_notable_artifacts_map_to_artifact_prefix() -> None:
    pairs = derive_subjects(_full_analysis(), default_profile())
    canon = _canonicals(pairs)
    assert "artifact:license" in canon
    assert "artifact:dockerfile" in canon
    assert "artifact:schema" in canon
    assert "artifact:generated" in canon


def test_cross_cutting_concerns_map_to_topic_prefix() -> None:
    pairs = derive_subjects(_full_analysis(), default_profile())
    canon = _canonicals(pairs)
    # Tests present -> topic:testing ; CI present -> topic:ci .
    assert "topic:testing" in canon
    assert "topic:ci" in canon


# --------------------------------------------------------------------------- #
# Evidence attached to every subject (Req 3.5)                                 #
# --------------------------------------------------------------------------- #


def test_every_subject_carries_evidence() -> None:
    for subj, ev in derive_subjects(_full_analysis(), default_profile()):
        assert isinstance(ev, EvidenceRef)
        assert ev.kind
        assert ev.detail


def test_component_evidence_points_at_source_path() -> None:
    pairs = derive_subjects(_full_analysis(), default_profile())
    ev = next(ev for subj, ev in pairs if subj.canonical() == "component:hashing")
    assert ev.kind == "component"
    assert ev.detail == "internal/hashing"


# --------------------------------------------------------------------------- #
# Normalization (Req 3.4)                                                       #
# --------------------------------------------------------------------------- #


def test_local_names_are_normalized_lowercase() -> None:
    analysis = _full_analysis()
    analysis = replace(
        analysis,
        components=(
            Component(
                name="HashingEngine",
                path="internal/HashingEngine",
                representative_files=(),
            ),
        ),
    )
    pairs = derive_subjects(analysis, default_profile())
    canon = _canonicals(pairs)
    assert "component:hashingengine" in canon
    assert "component:HashingEngine" not in canon


# --------------------------------------------------------------------------- #
# Deterministic ordering (Req 3.4)                                             #
# --------------------------------------------------------------------------- #


def test_pairs_sorted_by_subject_canonical() -> None:
    pairs = derive_subjects(_full_analysis(), default_profile())
    canon = _canonicals(pairs)
    assert canon == sorted(canon)


def test_deterministic_across_repeated_runs() -> None:
    a = derive_subjects(_full_analysis(), default_profile())
    b = derive_subjects(_full_analysis(), default_profile())
    assert a == b


def test_no_duplicate_subjects() -> None:
    pairs = derive_subjects(_full_analysis(), default_profile())
    canon = _canonicals(pairs)
    assert len(canon) == len(set(canon))


# --------------------------------------------------------------------------- #
# Prefix filtering against the loaded vocabulary (Req 3.3)                      #
# --------------------------------------------------------------------------- #


def _vocab_without_prefix(missing: str) -> Vocabulary:
    base = default_profile()
    kept = tuple(
        p for p in base.subject_prefixes if normalize_prefix(p) != normalize_prefix(missing)
    )
    return replace(base, subject_prefixes=kept)


def test_missing_topic_prefix_omits_all_topic_subjects() -> None:
    vocab = _vocab_without_prefix("topic:")
    pairs = derive_subjects(_full_analysis(), vocab)
    assert "topic" not in _prefixes_of(pairs)
    # The other prefixes are still produced.
    assert {"component", "tech", "artifact"} <= _prefixes_of(pairs)


def test_missing_component_prefix_omits_all_component_subjects() -> None:
    vocab = _vocab_without_prefix("component:")
    pairs = derive_subjects(_full_analysis(), vocab)
    assert "component" not in _prefixes_of(pairs)


def test_only_vocabulary_prefixes_are_ever_emitted() -> None:
    vocab = _vocab_without_prefix("artifact:")
    allowed = {normalize_prefix(p) for p in vocab.subject_prefixes}
    pairs = derive_subjects(_full_analysis(), vocab)
    assert _prefixes_of(pairs) <= allowed
    assert "artifact" not in _prefixes_of(pairs)


def test_custom_extra_prefix_is_honored_when_present() -> None:
    # A custom vocabulary that adds a non-default prefix still maps the standard
    # categories; the extra prefix simply has no findings mapped to it here.
    base = default_profile()
    vocab = replace(
        base, subject_prefixes=base.subject_prefixes + ("concept:",)
    )
    pairs = derive_subjects(_full_analysis(), vocab)
    # No "concept:" subjects are fabricated (nothing maps to it).
    assert "concept" not in _prefixes_of(pairs)
    # But the standard prefixes are all present.
    assert {"component", "tech", "artifact", "topic"} <= _prefixes_of(pairs)


# --------------------------------------------------------------------------- #
# Empty analysis (Req 3.x: no findings -> no subjects, never raises)            #
# --------------------------------------------------------------------------- #


def test_empty_analysis_yields_no_subjects() -> None:
    assert derive_subjects(_empty_analysis(), default_profile()) == ()


def test_empty_vocabulary_prefixes_yields_no_subjects() -> None:
    vocab = replace(default_profile(), subject_prefixes=())
    assert derive_subjects(_full_analysis(), vocab) == ()
