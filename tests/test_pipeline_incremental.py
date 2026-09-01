"""Incremental generation against the living page store (task 3.1)."""

from __future__ import annotations

import shutil
from pathlib import Path

from docuharnessx.analysis import analyze, scan
from docuharnessx.pages.model import Page
from docuharnessx.pages.store import FilesystemLivingPageStore
from docuharnessx.pipeline import run_pipeline
from docuharnessx.planning.questions import plan_questions
from _fakes import FakeProvider, ScriptedAgentProvider

_FIXTURE_REPO = Path(__file__).parent / "fixtures" / "agentic_repo"

_GROUNDED_BODY = (
    "The `Engine` class loads run settings through `load_config` (`config.py:10`)\n"
    "and then drives a bounded work cycle (`engine.py:16`).\n"
)

_KEPT_BODY = "KEEPME original living page body that must not be rewritten.\n"


def test_run_skips_existing_living_page_and_fills_missing(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    shutil.copytree(_FIXTURE_REPO, repo)
    plan = plan_questions(analyze(scan(str(repo))))
    assert len(plan.questions) >= 2
    first, second = plan.questions[0], plan.questions[1]
    store = FilesystemLivingPageStore(str(repo))
    store.put(
        Page(
            id=first.id,
            title=first.title,
            summary="kept",
            body=_KEPT_BODY,
            subjects=(first.subject_name,),
            related=(),
            cited_files=("config.py", "engine.py"),
        )
    )
    original = store.get(first.id)
    assert original is not None
    original_body = original.body

    outcome = run_pipeline(
        repo_path=str(repo),
        out_dir=str(tmp_path / "out"),
        model=ScriptedAgentProvider(body=_GROUNDED_BODY),
        deploy_mode="build-only",
    )

    kept = store.get(first.id)
    assert kept is not None
    assert kept.body == original_body
    living_ids = {page.id for page in store.list()}
    assert first.id in living_ids
    assert outcome.report.planned == len(plan.questions)
    assert first.id not in {item.question_id for item in outcome.report.omissions}


def test_regenerate_id_keeps_previous_page_when_gate_rejects(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    shutil.copytree(_FIXTURE_REPO, repo)
    plan = plan_questions(analyze(scan(str(repo))))
    first = plan.questions[0]
    store = FilesystemLivingPageStore(str(repo))
    store.put(
        Page(
            id=first.id,
            title=first.title,
            summary="kept",
            body=_KEPT_BODY,
            subjects=(first.subject_name,),
            related=(),
            cited_files=("config.py", "engine.py"),
        )
    )
    run_pipeline(
        repo_path=str(repo),
        out_dir=str(tmp_path / "out"),
        model=FakeProvider(content="Locate the CLI. Run the smallest action."),
        deploy_mode="build-only",
        regenerate_ids=(first.id,),
    )
    kept = store.get(first.id)
    assert kept is not None
    assert kept.body == _KEPT_BODY


def test_regenerate_id_replaces_page_when_gate_accepts(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    shutil.copytree(_FIXTURE_REPO, repo)
    plan = plan_questions(analyze(scan(str(repo))))
    first = plan.questions[0]
    store = FilesystemLivingPageStore(str(repo))
    store.put(
        Page(
            id=first.id,
            title=first.title,
            summary="kept",
            body=_KEPT_BODY,
            subjects=(first.subject_name,),
            related=(),
            cited_files=("config.py", "engine.py"),
        )
    )
    run_pipeline(
        repo_path=str(repo),
        out_dir=str(tmp_path / "out"),
        model=ScriptedAgentProvider(body=_GROUNDED_BODY),
        deploy_mode="build-only",
        regenerate_ids=(first.id,),
    )
    updated = store.get(first.id)
    assert updated is not None
    assert updated.body != _KEPT_BODY
    assert "Engine" in updated.body


def test_empty_living_store_writes_report_without_site_shell(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    shutil.copytree(_FIXTURE_REPO, repo)
    out = tmp_path / "out"
    outcome = run_pipeline(
        repo_path=str(repo),
        out_dir=str(out),
        model=None,
        deploy_mode="build-only",
    )
    assert outcome.pages == ()
    assert (out / "report.json").is_file()
    assert not (out / "site").exists()
    assert not (repo / "docs").exists()
