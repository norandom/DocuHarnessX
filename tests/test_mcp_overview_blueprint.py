"""Unit tests for the deterministic overview blueprint builder (mcp-refine task 2.2).

Task 2.2 owns one pure, model-free boundary:

    build_overview_blueprint(identity, vocab, analysis, *, guidance="") -> CompositionBlueprint

It mirrors ``build_blueprint`` but produces the **overview-shaped** plan: a single
project-wide ``CompositionBlueprint`` whose four ordered chunk headings are
Purpose / Use cases / Features / Design choices, whose ``title`` is the project overview
title (from ``identity.site_name``), whose ``subjects`` are the project's salient subjects
(derived from the optional analysis, vocab-prefix filtered), and whose ``evidence_anchors``
are derived from the analysis's salient entrypoints/components (empty tuple when absent).

The load-bearing constraints these tests pin:

* (a) the blueprint is **byte-deterministic** for equal inputs — and identical regardless of
  the ``guidance`` value (guidance never enters the frozen blueprint; it reaches the agent
  only through the writer's ``guidance`` keyword, never as a doc heading);
* (b) the four overview chunks appear in order with the exact headings;
* (c) labels derive only from the loaded vocabulary / identity (no hardcoded role/intent
  literals): re-describing the vocabulary changes the derived intent label, and the title
  follows ``identity.site_name``;
* (d) a ``None`` analysis is tolerated (empty subjects + empty evidence anchors), and a present
  analysis contributes salient subjects + entrypoint/component evidence anchors;
* (e) purity — model-free, never mutates its inputs.
"""

from __future__ import annotations

import copy

from docuharnessx.assembler import SiteIdentity
from docuharnessx.composition.model import Chunk, CompositionBlueprint, EvidenceAnchor
from docuharnessx.mcp.overview import (
    OVERVIEW_SECTION_HEADINGS,
    build_overview_blueprint,
)
from docuharnessx.ontology import AxisTerm, Vocabulary
from docuharnessx.analysis.model import (
    REPO_ANALYSIS_SCHEMA_VERSION,
    Component,
    DocPresence,
    Entrypoint,
    LanguageStat,
    RepoAnalysis,
    ScanStats,
)
# Aliased on import so pytest does not try to collect the ``Test*``-named value object as a
# test class (it is a frozen dataclass, not a test case).
from docuharnessx.analysis.model import TestLayout as _TestLayout

_EXPECTED_HEADINGS = ("Purpose", "Use cases", "Features", "Design choices")


def _identity(site_name: str = "acme-widget") -> SiteIdentity:
    return SiteIdentity(
        site_name=site_name,
        repo_name="acme/widget",
        repo_url="https://github.com/acme/widget",
        site_url="https://acme.github.io/widget/",
        base_path="/widget/",
        edit_uri="edit/main/docs/",
    )


def _vocab(understand_label: str = "Understand") -> Vocabulary:
    return Vocabulary(
        roles=(
            AxisTerm("possible-adopter", "Possible Adopter", "Evaluates the project."),
            AxisTerm("developer", "Developer", "Builds on the project."),
        ),
        intents=(
            AxisTerm("install", "Install", "Get it installed."),
            AxisTerm(
                "understand",
                understand_label,
                "Build a mental model of the project.",
            ),
            AxisTerm("use", "Use", "Use the project."),
        ),
        subject_prefixes=("component:", "tech:", "artifact:", "topic:"),
    )


def _analysis() -> RepoAnalysis:
    return RepoAnalysis(
        schema_version=REPO_ANALYSIS_SCHEMA_VERSION,
        repo_path="/tmp/widget",
        languages=(LanguageStat("Python", 12, 3400),),
        primary_languages=("Python",),
        total_loc=3400,
        total_files=12,
        structure=(),
        entrypoints=(
            Entrypoint(path="src/widget/cli.py", kind="cli", name="widget"),
            Entrypoint(path="src/widget/__main__.py", kind="main", name=""),
        ),
        build_files=(),
        ci_workflows=(),
        tests=_TestLayout(present=False, frameworks=(), paths=()),
        dependencies=(),
        components=(
            Component(
                name="core",
                path="src/widget/core",
                representative_files=("src/widget/core/engine.py",),
            ),
        ),
        public_surface=(),
        docs=DocPresence(
            has_readme=True, readme_paths=("README.md",), doc_dirs=(), other_docs=()
        ),
        artifacts=(),
        scan_stats=ScanStats(
            files_scanned=12,
            files_skipped=0,
            bytes_scanned=4096,
            limit_reached=False,
            notes=(),
        ),
    )


# --------------------------------------------------------------------------- #
# (a) Determinism + guidance independence                                      #
# --------------------------------------------------------------------------- #


def test_blueprint_is_byte_deterministic_for_equal_inputs() -> None:
    a = build_overview_blueprint(_identity(), _vocab(), _analysis())
    b = build_overview_blueprint(_identity(), _vocab(), _analysis())
    assert a == b


def test_blueprint_independent_of_guidance_value() -> None:
    # The guidance NEVER enters the frozen blueprint (it reaches the agent only through the
    # writer's guidance keyword, never as a doc heading). So varying guidance yields an
    # identical blueprint.
    base = build_overview_blueprint(_identity(), _vocab(), _analysis(), guidance="")
    g1 = build_overview_blueprint(
        _identity(), _vocab(), _analysis(), guidance="emphasise the security posture"
    )
    g2 = build_overview_blueprint(
        _identity(), _vocab(), _analysis(), guidance="focus on the CLI surface"
    )
    assert base == g1 == g2


def test_guidance_text_never_appears_in_the_blueprint() -> None:
    # Applied-not-echoed at the blueprint layer: the verbatim guidance must not leak into any
    # blueprint field (title / headings / points / key_message / scqa / fast_path).
    needle = "ZZ_UNIQUE_GUIDANCE_TOKEN_ZZ"
    bp = build_overview_blueprint(_identity(), _vocab(), _analysis(), guidance=needle)
    haystack = repr(bp)
    assert needle not in haystack


# --------------------------------------------------------------------------- #
# (b) The four overview chunks, in order                                       #
# --------------------------------------------------------------------------- #


def test_four_overview_chunks_in_order() -> None:
    bp = build_overview_blueprint(_identity(), _vocab(), _analysis())
    assert isinstance(bp, CompositionBlueprint)
    headings = tuple(chunk.heading for chunk in bp.chunks)
    assert headings == _EXPECTED_HEADINGS


def test_exported_section_headings_match_chunks() -> None:
    # The public heading tuple is the single source of truth for the overview shape.
    assert OVERVIEW_SECTION_HEADINGS == _EXPECTED_HEADINGS
    bp = build_overview_blueprint(_identity(), _vocab(), None)
    assert tuple(c.heading for c in bp.chunks) == OVERVIEW_SECTION_HEADINGS


def test_every_chunk_is_a_well_formed_chunk_with_points() -> None:
    bp = build_overview_blueprint(_identity(), _vocab(), _analysis())
    for chunk in bp.chunks:
        assert isinstance(chunk, Chunk)
        assert chunk.points  # each section carries deterministic support points


# --------------------------------------------------------------------------- #
# (c) Vocabulary / identity-derived labels — no hardcoded role/intent literals #
# --------------------------------------------------------------------------- #


def test_title_follows_identity_site_name() -> None:
    bp = build_overview_blueprint(_identity("my-cool-project"), _vocab(), None)
    assert "my-cool-project" in bp.title


def test_intent_label_follows_loaded_vocabulary() -> None:
    # Re-describing the "understand" intent's label changes the derived intent_label without
    # a code edit — proving the label is read from the loaded vocabulary, not hardcoded.
    bp_default = build_overview_blueprint(_identity(), _vocab(), None)
    bp_renamed = build_overview_blueprint(
        _identity(), _vocab(understand_label="Get Oriented"), None
    )
    assert bp_default.intent_label == "Understand"
    assert bp_renamed.intent_label == "Get Oriented"
    # The chosen intent id is a real vocabulary member, not an invented literal.
    assert bp_default.intent in {i.id for i in _vocab().intents}


def test_overview_is_project_wide_not_role_targeted() -> None:
    # The overview addresses every reader (a project front door), so it carries no role
    # targeting — roles/role_labels are empty rather than a hardcoded role literal.
    bp = build_overview_blueprint(_identity(), _vocab(), None)
    assert bp.roles == ()
    assert bp.role_labels == ()


def test_falls_back_to_first_intent_when_no_understand_signal() -> None:
    # A vocabulary with no understand/overview-signalling intent still derives a real member
    # (the first intent), never a hardcoded literal.
    vocab = Vocabulary(
        roles=(AxisTerm("dev", "Dev", "Builds."),),
        intents=(
            AxisTerm("ship", "Ship", "Ship outcomes."),
            AxisTerm("install", "Install", "Install it."),
        ),
        subject_prefixes=("component:",),
    )
    bp = build_overview_blueprint(_identity(), vocab, None)
    assert bp.intent == "ship"
    assert bp.intent_label == "Ship"


def test_tolerates_empty_vocabulary_intents() -> None:
    # A vocabulary with no intents at all degrades deterministically (empty intent) rather
    # than raising.
    vocab = Vocabulary(roles=(), intents=(), subject_prefixes=())
    bp = build_overview_blueprint(_identity(), vocab, None)
    assert bp.intent == ""
    assert bp.intent_label == ""
    assert tuple(c.heading for c in bp.chunks) == _EXPECTED_HEADINGS


# --------------------------------------------------------------------------- #
# (d) Salient subjects + evidence anchors from the optional analysis           #
# --------------------------------------------------------------------------- #


def test_none_analysis_yields_empty_subjects_and_anchors() -> None:
    bp = build_overview_blueprint(_identity(), _vocab(), None)
    assert bp.subjects == ()
    assert bp.evidence_anchors == ()
    # Still a complete, well-formed blueprint.
    assert tuple(c.heading for c in bp.chunks) == _EXPECTED_HEADINGS


def test_present_analysis_contributes_salient_subjects() -> None:
    bp = build_overview_blueprint(_identity(), _vocab(), _analysis())
    # The analysis carries a component + a python language signal, both vocab-prefixed.
    canon = {s.canonical() for s in bp.subjects}
    assert "component:core" in canon
    assert "tech:python" in canon
    # Subjects are vocab-prefix filtered: every emitted prefix is a vocabulary member.
    allowed = {p.rstrip(":") for p in _vocab().subject_prefixes}
    assert {s.prefix for s in bp.subjects} <= allowed


def test_present_analysis_contributes_entrypoint_and_component_anchors() -> None:
    bp = build_overview_blueprint(_identity(), _vocab(), _analysis())
    assert bp.evidence_anchors  # non-empty for a populated analysis
    for anchor in bp.evidence_anchors:
        assert isinstance(anchor, EvidenceAnchor)
    details = {a.detail for a in bp.evidence_anchors}
    # Salient entrypoints + components are surfaced as anchors.
    assert "src/widget/cli.py" in details
    assert "src/widget/core" in details
    kinds = {a.kind for a in bp.evidence_anchors}
    assert "entrypoint" in kinds
    assert "component" in kinds


def test_evidence_anchors_are_deterministically_ordered() -> None:
    a = build_overview_blueprint(_identity(), _vocab(), _analysis()).evidence_anchors
    b = build_overview_blueprint(_identity(), _vocab(), _analysis()).evidence_anchors
    assert a == b
    # Anchor order is sorted by (kind, detail) so it is independent of analysis tuple order.
    assert list(a) == sorted(a, key=lambda x: (x.kind, x.detail))


# --------------------------------------------------------------------------- #
# (e) Purity                                                                    #
# --------------------------------------------------------------------------- #


def test_does_not_mutate_inputs() -> None:
    identity = _identity()
    vocab = _vocab()
    analysis = _analysis()
    before_identity = copy.deepcopy(identity)
    before_vocab = copy.deepcopy(vocab)
    before_analysis = copy.deepcopy(analysis)
    build_overview_blueprint(identity, vocab, analysis, guidance="some guidance")
    assert identity == before_identity
    assert vocab == before_vocab
    assert analysis == before_analysis


def test_returns_frozen_blueprint() -> None:
    bp = build_overview_blueprint(_identity(), _vocab(), _analysis())
    assert isinstance(bp, CompositionBlueprint)
    # CompositionBlueprint is frozen: equal inputs hash equal.
    assert hash(bp) == hash(build_overview_blueprint(_identity(), _vocab(), _analysis()))
