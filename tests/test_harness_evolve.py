"""Harness evolution comparison gate (task 7.2)."""

from __future__ import annotations

from pathlib import Path

from docuharnessx.adoption import AdoptionRecord, load_adoption, save_adoption
from docuharnessx.blueprint import BLUEPRINT_NAME, BLUEPRINT_VERSION
from docuharnessx.evolve import evolve_project
from docuharnessx.pages.model import Page
from docuharnessx.pages.store import FilesystemLivingPageStore


def _adopt(project: Path) -> None:
    save_adoption(
        str(project),
        AdoptionRecord(
            blueprint_name=BLUEPRINT_NAME,
            blueprint_version=BLUEPRINT_VERSION,
            adopted_at="2026-09-01T12:00:00+00:00",
            sufficient=False,
            sufficient_at=None,
            sufficient_stale=False,
            harness_snapshot=None,
        ),
    )


def test_evolve_insufficient_traces_leaves_snapshot(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    _adopt(project)
    message = evolve_project(str(project))
    assert "no evolution was applied" in message
    assert "insufficient" in message
    record = load_adoption(str(project))
    assert record is not None
    assert record.harness_snapshot is None


def test_evolve_rejects_candidate_that_drops_the_gate(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    _adopt(project)
    journals = project / ".docuharnessx" / "journals"
    journals.mkdir(parents=True)
    (journals / "a.json").write_text("{}", encoding="utf-8")
    (journals / "b.json").write_text("{}", encoding="utf-8")
    message = evolve_project(
        str(project),
        candidate_processors=("not-the-gate",),
    )
    assert "no evolution was applied" in message
    record = load_adoption(str(project))
    assert record is not None
    assert record.harness_snapshot is None


def test_evolve_saves_snapshot_without_rewriting_pages(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    _adopt(project)
    store = FilesystemLivingPageStore(str(project))
    store.put(
        Page(
            id="startup:app.py",
            title="t",
            summary="s",
            body="KEEP",
            subjects=(),
            related=(),
            cited_files=(),
        )
    )
    journals = project / ".docuharnessx" / "journals"
    journals.mkdir(parents=True, exist_ok=True)
    (journals / "a.json").write_text('{"cycles": 4}', encoding="utf-8")
    (journals / "b.json").write_text('{"cycles": 2}', encoding="utf-8")
    message = evolve_project(
        str(project),
        candidate_processors=("validate_page_body",),
        improved=True,
    )
    assert "applied" in message.lower() or "snapshot" in message.lower()
    record = load_adoption(str(project))
    assert record is not None
    assert record.harness_snapshot is not None
    assert store.get("startup:app.py") is not None
    assert store.get("startup:app.py").body == "KEEP"
