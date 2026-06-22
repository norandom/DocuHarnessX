"""Task 5.1 — cross-cutting validation of the deterministic planning core.

This suite is the dedicated **validation** task (tasks.md 5.1) over the four
deterministic-core boundaries — *subjects*, *matrix*, *scorer*, *serde* — built by
tasks 2.1, 2.2, 3.1, and 1.2. Where the per-module suites pin each component in
isolation, this file proves the *integrated* properties task 5.1 names as its
observable completion, chaining the components over one crafted ``RepoAnalysis`` and
the loaded, project-configurable :class:`~docuharnessx.ontology.Vocabulary`:

* **Subject derivation per prefix and prefix omission** — every finding category maps
  onto its typed prefix, and dropping a prefix from the vocabulary drops exactly those
  subjects (Req 3.1, 3.2, 3.3, 3.4, 3.5).
* **Evidence-gated cell activation with vocabulary filtering and ``intent_order()``
  ordering** — a CLI signal activates install/use/troubleshoot for the matching user
  role only when those ids are vocabulary members, and cells come out in
  ``vocab.intent_order()`` (Req 4.3, 4.4, 4.5).
* **Monotonic evidence-driven scoring with total tie-breaking** — more evidence scores
  strictly higher and the ``order_key`` is a total, reproducible order with no unbroken
  ties (Req 5.1, 5.2, 5.3).
* **Serde round-trip + byte-stability + the version error** — ``from_dict(to_dict(p))
  == p``, ``to_json`` is byte-identical for equal inputs, and an unknown
  ``schema_version`` raises :class:`CoveragePlanVersionError` (Req 6.4, 6.5, 6.6).

The unifying gate (tasks.md 5.1 observable completion): **byte-identical serialization
and identical scores/cells across two runs over equal inputs**. Every fixture here is
hand-crafted (no scanner/harness), so the suite runs without credentials or a model and
is deterministic by construction (Req 8.1).

Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 4.3, 4.4, 4.5, 5.1, 5.2, 5.3, 6.4, 6.5, 6.6, 8.1.
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
from docuharnessx.planning.matrix import activate_cells
from docuharnessx.planning.model import (
    COVERAGE_PLAN_SCHEMA_VERSION,
    CandidateCell,
    CoveragePlan,
    CoveragePlanVersionError,
    EvidenceRef,
    PlannedSegment,
)
from docuharnessx.planning.scorer import order_key, score_cell
from docuharnessx.planning.serde import from_dict, to_dict, to_json
from docuharnessx.planning.subjects import derive_subjects


# --------------------------------------------------------------------------- #
# Crafted fixtures (no scanner, no harness, no model)                          #
# --------------------------------------------------------------------------- #


def _reference_analysis() -> RepoAnalysis:
    """A Go-CLI-shaped analysis exercising every subject category and rule predicate.

    Modeled on the reference ``malware_hashes`` repo (Go CLI, ``go.mod``, GitHub
    Actions, ``*_test.go``, README, LICENSE) so the chained core sees each finding
    category: components, languages, frameworks, dependencies, build files, CI,
    notable artifacts, tests, public surface, docs.
    """
    return RepoAnalysis(
        schema_version=1,
        repo_path="/repo/malware_hashes",
        languages=(
            LanguageStat(language="Go", files=12, loc=3400),
            LanguageStat(language="Markdown", files=8, loc=1200),
            LanguageStat(language="YAML", files=3, loc=140),
        ),
        # Note the planner-facing caveat: primary_languages reflects RAW LOC, so a
        # markup language can lead; tech signals are taken from the FULL languages
        # tuple + components/build/entrypoints, never solely primary_languages.
        primary_languages=("Go",),
        total_loc=4740,
        total_files=23,
        structure=(
            DirectorySummary(
                path="", file_count=23, dominant_language="Go", role="source"
            ),
            DirectorySummary(
                path="internal/hashing",
                file_count=4,
                dominant_language="Go",
                role="source",
            ),
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
            Component(
                name="scanner",
                path="internal/scanner",
                representative_files=("internal/scanner/scan.go",),
            ),
        ),
        public_surface=(
            PublicSymbol(name="scan", kind="cli_subcommand", source="cmd/mh/main.go"),
            PublicSymbol(
                name="Hash", kind="exported_symbol", source="internal/hashing/hash.go"
            ),
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
        docs=DocPresence(has_readme=False, readme_paths=(), doc_dirs=(), other_docs=()),
        artifacts=(),
        scan_stats=ScanStats(
            files_scanned=0,
            files_skipped=0,
            bytes_scanned=0,
            limit_reached=False,
            notes=(),
        ),
    )


def _subjects_by_kind(
    analysis: RepoAnalysis, vocab: Vocabulary
) -> dict[str, tuple[Subject, ...]]:
    """Group derived subjects by bare prefix — the shape ``activate_cells`` expects."""
    grouped: dict[str, list[Subject]] = {}
    for subject, _evidence in derive_subjects(analysis, vocab):
        grouped.setdefault(subject.prefix, []).append(subject)
    return {prefix: tuple(subjects) for prefix, subjects in grouped.items()}


def _activate(
    analysis: RepoAnalysis, vocab: Vocabulary
) -> tuple[CandidateCell, ...]:
    """Chain subjects -> matrix exactly as the classifier composes them."""
    return activate_cells(analysis, vocab, _subjects_by_kind(analysis, vocab))


def _materialize_plan(
    analysis: RepoAnalysis, vocab: Vocabulary
) -> CoveragePlan:
    """Chain the full deterministic core (subjects -> matrix -> scorer -> model).

    A self-contained, planner-shaped materialization used only to drive the *serde*
    boundary end-to-end with realistic content; it mirrors the documented ordering
    (priority desc, then role/intent order, then segment_key) without importing the
    planner module (whose boundary is owned by task 3.2).
    """
    cells = _activate(analysis, vocab)
    segments: list[PlannedSegment] = []
    for cell in cells:
        priority = score_cell(cell, vocab)
        subjects = tuple(sorted(cell.subjects, key=lambda s: s.canonical()))
        digest = "-".join(s.canonical() for s in subjects)
        segment_key = f"{'+'.join(cell.roles)}__{cell.intent}__{digest}"
        segments.append(
            PlannedSegment(
                segment_key=segment_key,
                roles=cell.roles,
                intent=cell.intent,
                subjects=subjects,
                priority=priority,
                evidence=cell.evidence,
            )
        )
    segments.sort(key=lambda s: order_key(s, vocab))
    return CoveragePlan(
        schema_version=COVERAGE_PLAN_SCHEMA_VERSION,
        repo_path=analysis.repo_path,
        vocabulary_fingerprint="vocab-fp-reference",
        segments=tuple(segments),
    )


# --------------------------------------------------------------------------- #
# subjects — derivation per prefix and prefix omission (Req 3.1-3.5)            #
# --------------------------------------------------------------------------- #


def test_subjects_cover_every_prefix_category() -> None:
    """Each finding category maps onto its documented typed prefix (Req 3.1, 3.2)."""
    canon = {s.canonical() for s, _ in derive_subjects(_reference_analysis(), default_profile())}
    assert "component:hashing" in canon  # components -> component:
    assert "component:scanner" in canon
    assert "tech:go" in canon  # full languages tuple -> tech:
    assert "tech:go_testing" in canon  # test frameworks -> tech:
    assert any(c.startswith("tech:") and "cobra" in c for c in canon)  # deps -> tech:
    assert "artifact:go_mod" in canon  # build files -> artifact:
    assert any("github_actions" in c for c in canon if c.startswith("artifact:"))
    assert "artifact:license" in canon  # notable artifacts -> artifact:
    assert "topic:testing" in canon  # tests present -> topic:testing
    assert "topic:ci" in canon  # CI present -> topic:ci
    assert "topic:security" in canon  # license -> topic:security


def test_subjects_every_pair_carries_evidence(  # noqa: D103 (Req 3.5)
) -> None:
    for subject, evidence in derive_subjects(_reference_analysis(), default_profile()):
        assert isinstance(subject, Subject)
        assert isinstance(evidence, EvidenceRef)
        assert evidence.kind and evidence.detail


def test_subjects_sorted_by_canonical(  # Req 3.4
) -> None:
    canon = [s.canonical() for s, _ in derive_subjects(_reference_analysis(), default_profile())]
    assert canon == sorted(canon)


@pytest.mark.parametrize("dropped", ["topic:", "component:", "artifact:", "tech:"])
def test_dropping_a_prefix_omits_exactly_those_subjects(dropped: str) -> None:
    """Prefix omission: a vocabulary missing a prefix yields none of those subjects (Req 3.3)."""
    base = default_profile()
    kept = tuple(
        p
        for p in base.subject_prefixes
        if normalize_prefix(p) != normalize_prefix(dropped)
    )
    vocab = replace(base, subject_prefixes=kept)
    pairs = derive_subjects(_reference_analysis(), vocab)
    prefixes = {s.prefix for s, _ in pairs}
    bare = normalize_prefix(dropped)
    assert bare not in prefixes
    # And only vocabulary prefixes are ever emitted (no fallback to a hardcoded set).
    allowed = {normalize_prefix(p) for p in kept}
    assert prefixes <= allowed


def test_subjects_identical_across_two_runs() -> None:
    """Determinism gate: subjects are identical across two runs (Req 3.4)."""
    a = derive_subjects(_reference_analysis(), default_profile())
    b = derive_subjects(_reference_analysis(), default_profile())
    assert a == b


# --------------------------------------------------------------------------- #
# matrix — evidence-gated activation, vocab filtering, intent_order (Req 4.3-5) #
# --------------------------------------------------------------------------- #


def _pairs(cells: tuple[CandidateCell, ...]) -> set[tuple[str, str]]:
    return {(role, cell.intent) for cell in cells for role in cell.roles}


def test_cli_signal_activates_install_use_troubleshoot_for_user_role() -> None:
    """CLI evidence activates install/use/troubleshoot for the matching role (Req 4.3)."""
    pairs = _pairs(_activate(_reference_analysis(), default_profile()))
    for intent in ("install", "use", "troubleshoot"):
        assert ("tech-savvy-user", intent) in pairs


def test_vocabulary_filtering_drops_cells_whose_intents_are_absent() -> None:
    """A vocabulary lacking the intents produces no such cells (Req 4.3)."""
    base = default_profile()
    kept = tuple(
        i for i in base.intents if i.id not in {"install", "use", "troubleshoot"}
    )
    vocab = replace(base, intents=kept)
    cells = _activate(_reference_analysis(), vocab)
    pairs = _pairs(cells)
    for intent in ("install", "use", "troubleshoot"):
        assert all(p[1] != intent for p in pairs)
    # Never emits an id absent from the loaded vocabulary.
    for cell in cells:
        assert vocab.has_intent(cell.intent)
        for role in cell.roles:
            assert vocab.has_role(role)


def test_cells_ordered_by_vocab_intent_order() -> None:
    """Cells come out in ``vocab.intent_order()`` as the documented primary key (Req 4.4)."""
    vocab = default_profile()
    cells = _activate(_reference_analysis(), vocab)
    rank = {intent: i for i, intent in enumerate(vocab.intent_order())}
    intent_ranks = [rank[c.intent] for c in cells]
    assert intent_ranks == sorted(intent_ranks)


def test_custom_intent_order_reorders_cells() -> None:
    """The matrix follows whatever intent order the loaded vocabulary declares (Req 4.4).

    Reversing the default intent declaration order reverses the cells' intent-rank
    sequence — proving ordering is vocabulary-driven, not hardcoded.
    """
    base = default_profile()
    reversed_intents = tuple(reversed(base.intents))
    vocab = replace(base, intents=reversed_intents)
    cells = _activate(_reference_analysis(), vocab)
    rank = {intent: i for i, intent in enumerate(vocab.intent_order())}
    intent_ranks = [rank[c.intent] for c in cells]
    assert intent_ranks == sorted(intent_ranks)
    # The activated (role, intent) *pairs* are unchanged; only their order differs.
    assert _pairs(cells) == _pairs(_activate(_reference_analysis(), base))


def test_cells_identical_across_two_runs() -> None:
    """Determinism gate: identical cells across two runs over equal inputs (Req 4.5)."""
    a = _activate(_reference_analysis(), default_profile())
    b = _activate(_reference_analysis(), default_profile())
    assert a == b


def test_empty_analysis_yields_no_cells_and_never_raises() -> None:
    assert _activate(_empty_analysis(), default_profile()) == ()


# --------------------------------------------------------------------------- #
# scorer — monotonic evidence scoring + total tie-breaking (Req 5.1-5.3)        #
# --------------------------------------------------------------------------- #


def _cell(
    *,
    roles: tuple[str, ...],
    intent: str,
    evidence: tuple[EvidenceRef, ...] = (),
) -> CandidateCell:
    return CandidateCell(roles=roles, intent=intent, subjects=(), evidence=evidence)


def test_more_evidence_scores_strictly_higher() -> None:
    """More supporting evidence => strictly higher priority (Req 5.1)."""
    vocab = default_profile()
    lean = _cell(
        roles=("developer",),
        intent="extend",
        evidence=(EvidenceRef(kind="public_surface", detail="a.go"),),
    )
    rich = _cell(
        roles=("developer",),
        intent="extend",
        evidence=(
            EvidenceRef(kind="public_surface", detail="a.go"),
            EvidenceRef(kind="public_surface", detail="b.go"),
        ),
    )
    assert score_cell(rich, vocab) > score_cell(lean, vocab)


def test_scores_are_plain_ints_and_identical_across_two_runs() -> None:
    """Determinism gate: integer scores, identical across two runs (Req 5.1, 5.3)."""
    cell = _cell(
        roles=("tech-savvy-user",),
        intent="install",
        evidence=(
            EvidenceRef(kind="entrypoint", detail="main.go"),
            EvidenceRef(kind="ci", detail=".github/workflows/ci.yml"),
        ),
    )
    first = score_cell(cell, default_profile())
    second = score_cell(cell, default_profile())
    assert type(first) is int
    assert first == second


def test_order_key_is_total_with_no_unbroken_ties() -> None:
    """``order_key`` yields a total order even under deliberate priority collisions (Req 5.2, 5.3)."""
    vocab = default_profile()
    role_ids = [r.id for r in vocab.roles]
    intent_ids = vocab.intent_order()
    segments: list[PlannedSegment] = []
    for ri, role in enumerate(role_ids[:3]):
        for ii, intent in enumerate(intent_ids[:3]):
            segments.append(
                PlannedSegment(
                    segment_key=f"{role}__{intent}__{ri}{ii}",
                    roles=(role,),
                    intent=intent,
                    subjects=(),
                    priority=(ri + ii) % 2,  # force priority ties
                    evidence=(),
                )
            )
    keys = [order_key(s, vocab) for s in segments]
    assert len(set(keys)) == len(keys)  # every key distinct => total order


def test_order_key_priority_dominates_then_role_then_intent_then_key() -> None:
    """The ordering precedence is priority desc, role, intent, then segment_key (Req 5.2)."""
    vocab = default_profile()
    role_ids = [r.id for r in vocab.roles]
    intent_ids = vocab.intent_order()
    early_role, late_role = role_ids[0], role_ids[1]
    early_intent, late_intent = intent_ids[0], intent_ids[1]

    def seg(key: str, roles: tuple[str, ...], intent: str, priority: int) -> PlannedSegment:
        return PlannedSegment(
            segment_key=key,
            roles=roles,
            intent=intent,
            subjects=(),
            priority=priority,
            evidence=(),
        )

    # Priority dominates everything.
    hi = seg("z", (late_role,), late_intent, 99)
    lo = seg("a", (early_role,), early_intent, 1)
    assert sorted([lo, hi], key=lambda s: order_key(s, vocab))[0] is hi

    # Equal priority -> role order wins over intent + key.
    a = seg("z", (early_role,), late_intent, 7)
    b = seg("a", (late_role,), early_intent, 7)
    assert sorted([b, a], key=lambda s: order_key(s, vocab))[0] is a

    # Equal priority + role -> intent order wins over key.
    c = seg("z", (early_role,), early_intent, 7)
    d = seg("a", (early_role,), late_intent, 7)
    assert sorted([d, c], key=lambda s: order_key(s, vocab))[0] is c

    # Equal priority + role + intent -> the stable segment_key breaks the tie.
    e = seg("m", (early_role,), early_intent, 7)
    f = seg("a", (early_role,), early_intent, 7)
    assert [s.segment_key for s in sorted([e, f], key=lambda s: order_key(s, vocab))] == ["a", "m"]


def test_order_key_reproducible_across_two_runs() -> None:
    seg = PlannedSegment(
        segment_key="tech-savvy-user__install__x",
        roles=("tech-savvy-user",),
        intent="install",
        subjects=(),
        priority=42,
        evidence=(),
    )
    assert order_key(seg, default_profile()) == order_key(seg, default_profile())


# --------------------------------------------------------------------------- #
# serde — round-trip + byte-stability + version error (Req 6.4, 6.5, 6.6)       #
# --------------------------------------------------------------------------- #


def test_round_trip_equality_over_chained_plan() -> None:
    """``from_dict(to_dict(p)) == p`` for a plan built from the chained core (Req 6.5)."""
    plan = _materialize_plan(_reference_analysis(), default_profile())
    assert plan.segments  # the reference analysis produces a non-empty plan
    assert from_dict(to_dict(plan)) == plan


def test_round_trip_equality_over_empty_plan() -> None:
    plan = _materialize_plan(_empty_analysis(), default_profile())
    assert plan.segments == ()
    assert from_dict(to_dict(plan)) == plan


def test_round_trip_preserves_typed_subjects() -> None:
    plan = _materialize_plan(_reference_analysis(), default_profile())
    rebuilt = from_dict(to_dict(plan))
    for original, restored in zip(plan.segments, rebuilt.segments, strict=True):
        assert restored.subjects == original.subjects
        assert all(isinstance(s, Subject) for s in restored.subjects)


def test_to_json_byte_identical_across_two_runs() -> None:
    """Determinism gate: byte-identical serialization across two runs (Req 6.4)."""
    first = to_json(_materialize_plan(_reference_analysis(), default_profile()))
    second = to_json(_materialize_plan(_reference_analysis(), default_profile()))
    assert first == second


def test_to_json_byte_identical_for_independently_built_equal_plans() -> None:
    """Two independently-materialized equal plans serialize byte-identically (Req 6.4)."""
    plan_a = _materialize_plan(_reference_analysis(), default_profile())
    plan_b = _materialize_plan(_reference_analysis(), default_profile())
    assert plan_a == plan_b
    assert to_json(plan_a) == to_json(plan_b)


def test_from_dict_unknown_schema_version_raises() -> None:
    """An unknown ``schema_version`` raises ``CoveragePlanVersionError`` (Req 6.5, 6.6)."""
    data = to_dict(_materialize_plan(_reference_analysis(), default_profile()))
    data["schema_version"] = COVERAGE_PLAN_SCHEMA_VERSION + 1
    with pytest.raises(CoveragePlanVersionError, match=str(COVERAGE_PLAN_SCHEMA_VERSION + 1)):
        from_dict(data)


def test_from_dict_missing_schema_version_raises() -> None:
    data = to_dict(_materialize_plan(_reference_analysis(), default_profile()))
    del data["schema_version"]
    with pytest.raises(CoveragePlanVersionError):
        from_dict(data)


# --------------------------------------------------------------------------- #
# Whole-core determinism: identical scores AND cells across two runs (5.1 gate) #
# --------------------------------------------------------------------------- #


def test_chained_core_is_byte_and_value_identical_across_two_runs() -> None:
    """The unifying task-5.1 gate over the *whole* chained core.

    Over equal inputs, two independent runs of subjects -> matrix -> scorer produce
    identical cells AND identical scores, and the materialized plan serializes
    byte-identically (Req 4.5, 5.3, 6.4, 8.1).
    """
    analysis, vocab = _reference_analysis(), default_profile()

    cells_a = _activate(analysis, vocab)
    cells_b = _activate(analysis, vocab)
    assert cells_a == cells_b

    scores_a = [score_cell(c, vocab) for c in cells_a]
    scores_b = [score_cell(c, vocab) for c in cells_b]
    assert scores_a == scores_b

    assert to_json(_materialize_plan(analysis, vocab)) == to_json(
        _materialize_plan(analysis, vocab)
    )


def test_custom_vocabulary_changes_scores_and_cells_but_stays_deterministic() -> None:
    """A custom vocabulary yields a different, still-deterministic core (Req 4.x, 5.1, 8.1).

    Renaming/reducing the vocabulary changes the activated cells and their scores
    (project-specific, not templated), yet each custom run is still byte-identical
    to a repeat of itself.
    """
    base = default_profile()
    custom = Vocabulary(
        roles=(
            AxisTerm("operator", "Operator", ""),
            AxisTerm("auditor", "Auditor", ""),
        ),
        intents=(
            AxisTerm("ship", "Ship", ""),
            AxisTerm("review", "Review", ""),
        ),
        subject_prefixes=base.subject_prefixes,
    )
    # The custom vocabulary shares no rule-table hint ids, so it activates nothing —
    # proving the matrix never falls back to the default ids.
    assert _activate(_reference_analysis(), custom) == ()
    assert _materialize_plan(_reference_analysis(), custom).segments == ()

    # The default run, by contrast, is non-empty — the two are not templated copies.
    assert _materialize_plan(_reference_analysis(), base).segments

    # Each run is still self-identical (determinism preserved under a custom vocab).
    assert to_json(_materialize_plan(_reference_analysis(), custom)) == to_json(
        _materialize_plan(_reference_analysis(), custom)
    )
