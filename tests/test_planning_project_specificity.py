"""Acceptance: planning is project-specific, not templated (task 5.2).

This is the project-specificity *acceptance signal* of the classification-coverage
planner (tasks.md 5.2, boundary: classifier + planner). It runs the full
classify-then-plan deterministic core over *one* crafted
:class:`~docuharnessx.analysis.model.RepoAnalysis` twice — once under the shipped
:func:`~docuharnessx.ontology.default_profile` and once under a *custom*
:class:`~docuharnessx.ontology.Vocabulary` (renamed/omitted roles + intents and an
extra subject prefix) — and proves the two resulting
:class:`~docuharnessx.planning.model.CoveragePlan` outputs **diverge appropriately**
and each **reflects only the vocabulary it was planned against**.

That is the whole point of the planner: the coverage matrix is drawn from the *loaded*
vocabulary's roles x intents and the subjects from its prefixes (never a hardcoded
default 10-role / 13-intent / 4-prefix table), so a project that configures different
roles/intents/subjects gets a measurably different plan with no code change.

Observable completion (tasks.md 5.2):

* the default-profile plan and the custom-vocabulary plan **differ** (segments,
  role/intent ids, and subjects), and
* the custom-vocabulary plan contains **only** custom role / intent / subject ids —
  no id that exists solely in the default profile leaks into it.

The crafted analysis is deliberately rich (a Go CLI with CI+build, tests, a public
surface, an exported integration symbol, docs, and a license/compliance artifact) so
that *under the default profile* many distinct rule rows fire — install/use/
troubleshoot, evaluate, extend, integrate, contribute, operate/monitor/configure, and
assess-quality. The custom vocabulary then keeps only a subset of those role/intent ids
(plus its own renamed ids and an extra ``concept:`` prefix), so the divergence is large
and unambiguous: the custom plan necessarily loses the cells whose role *or* intent id
it does not declare, and the subjects whose prefix it drops.

Requirements: 4.1, 4.2.
"""

from __future__ import annotations

from dataclasses import replace

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
    Vocabulary,
    default_profile,
    normalize_prefix,
)
from docuharnessx.planning.classifier import classify_repo
from docuharnessx.planning.model import CoveragePlan
from docuharnessx.planning.planner import plan_coverage


# --------------------------------------------------------------------------- #
# Crafted inputs                                                               #
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


def _rich_analysis() -> RepoAnalysis:
    """A rich Go-CLI-shaped analysis exercising many rule-table predicates.

    Activates (under the default profile) install/use/troubleshoot + evaluate
    (CLI surface), operate/configure/monitor (CI+build), contribute (tests), extend
    (public surface), integrate (exported symbol + package bin), understand (docs), and
    assess-quality (license artifact). Subjects span component/tech/artifact/topic.
    """
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
        entrypoints=(
            Entrypoint(path="cmd/mh/main.go", kind="cli", name="mh"),
            Entrypoint(path="cmd/mh", kind="package_bin", name="mh"),
        ),
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
            PublicSymbol(
                name="Hash", kind="exported_symbol", source="internal/hashing/hash.go"
            ),
        ),
        docs=DocPresence(
            has_readme=True,
            readme_paths=("README.md",),
            doc_dirs=(),
            other_docs=(),
        ),
        artifacts=(Artifact(path="LICENSE", kind="license"),),
    )


def _custom_vocab() -> Vocabulary:
    """A project-specific vocabulary: subset + renamed ids + an extra prefix.

    It deliberately *overlaps* the rule-table hint ids on a few roles/intents
    (``tech-savvy-user``/``developer`` x ``install``/``use``/``extend``/``evaluate``) so
    cells genuinely activate — proving the matrix is vocabulary-driven, not that a custom
    vocab simply silences everything. But it:

    * introduces its own ``analyst`` role and ``appraise`` intent (ids that exist *only*
      here, never in the default profile);
    * omits roles the default profile defines and the analysis would otherwise activate
      (``possible-adopter``, ``manager``, ``contributor``, ``integrator``, ``devops-admin``,
      ``support-sre``, ``security-compliance-officer``);
    * omits intents the default profile defines and the analysis would otherwise activate
      (``troubleshoot``, ``configure``, ``operate``, ``monitor``, ``integrate``,
      ``contribute``, ``assess-quality``, ``understand``);
    * keeps the ``component:``/``tech:`` subject prefixes, **adds** an extra ``concept:``
      prefix, and **drops** ``artifact:`` and ``topic:`` — so artifact/topic subjects the
      default profile derives cannot appear here.
    """
    return Vocabulary(
        roles=(
            AxisTerm("tech-savvy-user", "Power User", "Runs the CLI."),
            AxisTerm("developer", "Engineer", "Extends the code."),
            AxisTerm("analyst", "Analyst", "A role only this project defines."),
        ),
        intents=(
            AxisTerm("install", "Install", "Get it running."),
            AxisTerm("use", "Use", "Operate it day to day."),
            AxisTerm("extend", "Extend", "Build on the public surface."),
            AxisTerm("evaluate", "Evaluate", "Decide whether to adopt."),
            AxisTerm("appraise", "Appraise", "An intent only this project defines."),
        ),
        subject_prefixes=("component:", "tech:", "concept:"),
    )


# Ids that exist in the default profile. Used to assert no default-only id leaks into
# the custom plan (computed from the live profile, never a frozen literal list).
def _default_role_ids() -> frozenset[str]:
    return frozenset(role.id for role in default_profile().roles)


def _default_intent_ids() -> frozenset[str]:
    return frozenset(default_profile().intent_order())


def _custom_role_ids() -> frozenset[str]:
    return frozenset(role.id for role in _custom_vocab().roles)


def _custom_intent_ids() -> frozenset[str]:
    return frozenset(_custom_vocab().intent_order())


def _custom_prefixes() -> frozenset[str]:
    return frozenset(normalize_prefix(p) for p in _custom_vocab().subject_prefixes)


def _plan(vocab: Vocabulary, analysis: RepoAnalysis | None = None) -> CoveragePlan:
    analysis = analysis if analysis is not None else _rich_analysis()
    return plan_coverage(classify_repo(analysis, vocab), vocab)


# --------------------------------------------------------------------------- #
# Both plans are well-formed and non-trivially populated                       #
# --------------------------------------------------------------------------- #


def test_both_plans_are_populated_coverage_plans() -> None:
    """Both vocabularies must actually produce segments (so the comparison is real)."""
    default_plan = _plan(default_profile())
    custom_plan = _plan(_custom_vocab())
    assert isinstance(default_plan, CoveragePlan)
    assert isinstance(custom_plan, CoveragePlan)
    assert len(default_plan.segments) > 0
    assert len(custom_plan.segments) > 0


# --------------------------------------------------------------------------- #
# The two plans DIVERGE (project-specific, not templated)                      #
# --------------------------------------------------------------------------- #


def test_default_and_custom_plans_differ() -> None:
    default_plan = _plan(default_profile())
    custom_plan = _plan(_custom_vocab())
    assert default_plan != custom_plan


def test_plans_have_different_vocabulary_fingerprints() -> None:
    default_plan = _plan(default_profile())
    custom_plan = _plan(_custom_vocab())
    assert (
        default_plan.vocabulary_fingerprint != custom_plan.vocabulary_fingerprint
    )


def test_segment_sets_differ() -> None:
    """The set of planned (roles, intent) cells differs between the two vocabularies."""
    default_cells = {
        (seg.roles, seg.intent) for seg in _plan(default_profile()).segments
    }
    custom_cells = {(seg.roles, seg.intent) for seg in _plan(_custom_vocab()).segments}
    assert default_cells != custom_cells
    # The default profile activates strictly more role x intent cells here (it declares
    # every rule-table id; the custom vocab declares only a subset).
    assert len(default_cells) > len(custom_cells)


def test_segment_keys_differ() -> None:
    default_keys = {seg.segment_key for seg in _plan(default_profile()).segments}
    custom_keys = {seg.segment_key for seg in _plan(_custom_vocab()).segments}
    assert default_keys != custom_keys


def test_default_plan_has_cells_the_custom_plan_drops() -> None:
    """Cells whose role OR intent the custom vocab omits must vanish from the custom plan.

    Concretely: the security/compliance assess-quality cell, the contributor/contribute
    cell, and the devops operate/monitor cells exist under the default profile but cannot
    exist under the custom vocabulary (it declares neither those roles nor those intents).
    """
    custom_cells = {(seg.roles, seg.intent) for seg in _plan(_custom_vocab()).segments}
    default_cells = {
        (seg.roles, seg.intent) for seg in _plan(default_profile()).segments
    }
    dropped = {
        (("security-compliance-officer",), "assess-quality"),
        (("contributor",), "contribute"),
        (("devops-admin",), "operate"),
        (("support-sre",), "monitor"),
    }
    # These cells are present under the default profile ...
    assert dropped & default_cells == dropped
    # ... and absent under the custom vocabulary.
    assert dropped & custom_cells == set()


# --------------------------------------------------------------------------- #
# The custom plan reflects ONLY the custom vocabulary (no default-only leak)    #
# --------------------------------------------------------------------------- #


def test_custom_plan_roles_are_all_custom_vocabulary_members() -> None:
    custom = _custom_vocab()
    plan = _plan(custom)
    for seg in plan.segments:
        for role_id in seg.roles:
            assert custom.has_role(role_id), role_id


def test_custom_plan_intents_are_all_custom_vocabulary_members() -> None:
    custom = _custom_vocab()
    plan = _plan(custom)
    for seg in plan.segments:
        assert custom.has_intent(seg.intent), seg.intent


def test_custom_plan_subject_prefixes_are_all_custom_vocabulary_members() -> None:
    """Every subject in the custom plan uses a prefix the custom vocabulary declares."""
    allowed = _custom_prefixes()
    plan = _plan(_custom_vocab())
    for seg in plan.segments:
        for subject in seg.subjects:
            assert subject.prefix in allowed, subject.canonical()


def test_no_default_only_role_id_appears_in_custom_plan() -> None:
    """No role id that exists *only* in the default profile leaks into the custom plan."""
    default_only_roles = _default_role_ids() - _custom_role_ids()
    assert default_only_roles  # the default profile has roles the custom vocab omits
    plan = _plan(_custom_vocab())
    seen_roles = {role_id for seg in plan.segments for role_id in seg.roles}
    assert seen_roles & default_only_roles == set()


def test_no_default_only_intent_id_appears_in_custom_plan() -> None:
    """No intent id that exists *only* in the default profile leaks into the custom plan."""
    default_only_intents = _default_intent_ids() - _custom_intent_ids()
    assert default_only_intents  # the default profile has intents the custom vocab omits
    plan = _plan(_custom_vocab())
    seen_intents = {seg.intent for seg in plan.segments}
    assert seen_intents & default_only_intents == set()


def test_no_dropped_prefix_subject_appears_in_custom_plan() -> None:
    """artifact:/topic: subjects (dropped by the custom vocab) never appear in its plan."""
    dropped_prefixes = {"artifact", "topic"}
    plan = _plan(_custom_vocab())
    seen_prefixes = {
        subject.prefix for seg in plan.segments for subject in seg.subjects
    }
    assert seen_prefixes & dropped_prefixes == set()


def test_custom_vocab_specific_ids_can_appear_but_only_via_evidence() -> None:
    """The custom-only ids are *available* to the planner (declared, vocab-driven).

    ``analyst``/``appraise`` are not wired to any rule-table predicate, so they do not
    activate for this analysis — which is correct (the planner never fabricates cells).
    The contract proven here is the inverse of the leak test: the custom plan's ids are a
    *subset* of the custom vocabulary's declared ids, confirming it is built from that
    vocabulary and nothing else.
    """
    custom = _custom_vocab()
    plan = _plan(custom)
    seen_roles = {role_id for seg in plan.segments for role_id in seg.roles}
    seen_intents = {seg.intent for seg in plan.segments}
    assert seen_roles <= _custom_role_ids()
    assert seen_intents <= _custom_intent_ids()


# --------------------------------------------------------------------------- #
# Determinism: each vocabulary's plan is reproducible across runs               #
# --------------------------------------------------------------------------- #


def test_each_vocabulary_plan_is_deterministic_across_two_runs() -> None:
    assert _plan(default_profile()) == _plan(default_profile())
    assert _plan(_custom_vocab()) == _plan(_custom_vocab())
