"""Comprehension signals, glossary, compliance matrix, autolink."""

from __future__ import annotations

from pathlib import Path

import pytest

from docuharnessx.comprehension.autolink import autolink_markdown
from docuharnessx.comprehension.compliance import (
    ComplianceSelection,
    load_compliance,
    parse_frameworks,
    save_compliance,
    score_matrix,
)
from docuharnessx.comprehension.glossary import (
    Glossary,
    GlossaryTerm,
    load_glossary,
    merge_glossary,
    save_glossary,
)
from docuharnessx.comprehension.signals import ComprehensionSignals, PipelineDag
from docuharnessx.errors import OntologyConfigError


def test_empty_signals_equal() -> None:
    assert ComprehensionSignals() == ComprehensionSignals()
    assert PipelineDag(source="coarse").edges == ()


def test_glossary_operator_wins(tmp_path: Path) -> None:
    seed = Glossary(
        terms=(
            GlossaryTerm(id="signal", label="Signal", definition="seed"),
        )
    )
    save_glossary(
        str(tmp_path),
        Glossary(
            terms=(
                GlossaryTerm(
                    id="signal",
                    label="Signal",
                    aliases=("alpha",),
                    definition="operator",
                ),
            )
        ),
    )
    merged = merge_glossary(seed, load_glossary(str(tmp_path)))
    term = merged.by_id()["signal"]
    assert term.definition == "operator"
    assert "alpha" in term.aliases


def test_invalid_glossary_raises(tmp_path: Path) -> None:
    path = tmp_path / ".docuharnessx"
    path.mkdir()
    (path / "glossary.yaml").write_text("terms: not-a-list\n", encoding="utf-8")
    with pytest.raises(OntologyConfigError):
        load_glossary(str(tmp_path))


def test_autolink_skips_code() -> None:
    glossary = Glossary(
        terms=(GlossaryTerm(id="signal", label="Signal"),)
    )
    text = "A Signal in prose and `Signal` in code and\n```\nSignal\n```\n"
    out = autolink_markdown(text, glossary)
    assert "[Signal](glossary.md#signal)" in out
    assert "`Signal`" in out
    assert "```\nSignal\n```" in out
    linked = autolink_markdown("[go](component-root-551790a4.md)", glossary)
    assert linked == "[go](component-root-551790a4.md)"


def test_parse_frameworks() -> None:
    assert parse_frameworks("none") == ()
    assert parse_frameworks("gdpr, ISO-27001") == ("gdpr", "iso27001")


def test_score_matrix_grays_unselected_pci(tmp_path: Path) -> None:
    selection = ComplianceSelection(frameworks=("gdpr",))
    cells = score_matrix(selection, None)
    pci = [c for c in cells if c.framework == "pci-dss"]
    assert pci
    assert all(c.status == "na" for c in pci)
    privacy = [
        c for c in cells if c.framework == "gdpr" and c.pillar == "privacy"
    ]
    assert privacy[0].status == "fail"


def test_override_wins_and_keeps_evidence(tmp_path: Path) -> None:
    save_compliance(
        str(tmp_path),
        ComplianceSelection(
            frameworks=("iso27001",),
            overrides=(("iso27001", "incident", "partial"),),
        ),
    )
    loaded = load_compliance(str(tmp_path))
    cells = score_matrix(loaded, None)
    incident = [
        c
        for c in cells
        if c.framework == "iso27001" and c.pillar == "incident"
    ][0]
    assert incident.status == "partial"
    assert incident.overridden is True


def test_none_in_scope_has_only_na() -> None:
    cells = score_matrix(ComplianceSelection(), None)
    assert cells
    assert all(c.status == "na" for c in cells)
