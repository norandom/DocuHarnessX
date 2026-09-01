"""Status and sufficiency CLI (tasks 4.1 / 4.2)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from docuharnessx import cli
from docuharnessx.adoption import declare_sufficient, load_adoption
from docuharnessx.analysis import analyze, scan
from docuharnessx.ontology_setup import run_init
from docuharnessx.pages.model import Page
from docuharnessx.pages.store import FilesystemLivingPageStore
from docuharnessx.planning.questions import plan_questions

_FIXTURE_REPO = Path(__file__).parent / "fixtures" / "agentic_repo"


def test_status_lists_missing_ids_and_not_sufficient(tmp_path: Path, capsys) -> None:
    repo = tmp_path / "repo"
    shutil.copytree(_FIXTURE_REPO, repo)
    run_init(str(repo), use_default=True)
    plan = plan_questions(analyze(scan(str(repo))))
    assert len(plan.questions) >= 2
    store = FilesystemLivingPageStore(str(repo))
    first = plan.questions[0]
    store.put(
        Page(
            id=first.id,
            title=first.title,
            summary="s",
            body="b",
            subjects=(first.subject_name,),
            related=(),
            cited_files=(),
        )
    )
    code = cli.main(["status", str(repo)])
    assert code == 0
    out = capsys.readouterr().out
    assert "sufficient: no" in out
    assert first.id in out
    missing = plan.questions[1].id
    assert missing in out
    assert "missing:" in out


def test_status_reads_omission_reason_from_saved_report(
    tmp_path: Path, capsys
) -> None:
    repo = tmp_path / "repo"
    shutil.copytree(_FIXTURE_REPO, repo)
    run_init(str(repo), use_default=True)
    plan = plan_questions(analyze(scan(str(repo))))
    omitted_id = plan.questions[0].id
    report_dir = repo / ".docuharnessx" / "out"
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "report.json").write_text(
        json.dumps(
            {
                "planned": 1,
                "accepted": 0,
                "omitted": 1,
                "questions": [omitted_id],
                "omissions": [
                    {"question_id": omitted_id, "reason": "no_model"},
                ],
            }
        ),
        encoding="utf-8",
    )
    code = cli.main(["status", str(repo)])
    assert code == 0
    out = capsys.readouterr().out
    assert omitted_id in out
    assert "no_model" in out


def test_sufficient_declaration_and_stale_after_put(tmp_path: Path, capsys) -> None:
    repo = tmp_path / "repo"
    shutil.copytree(_FIXTURE_REPO, repo)
    run_init(str(repo), use_default=True)
    assert cli.main(["sufficient", str(repo)]) == 0
    record = load_adoption(str(repo))
    assert record is not None
    assert record.sufficient is True
    assert record.sufficient_stale is False
    out = capsys.readouterr().out
    assert "sufficient=yes" in out
    assert cli.main(["status", str(repo)]) == 0
    assert "sufficient: yes" in capsys.readouterr().out

    store = FilesystemLivingPageStore(str(repo))
    store.put(
        Page(
            id="startup:app.py",
            title="t",
            summary="s",
            body="b",
            subjects=(),
            related=(),
            cited_files=(),
        )
    )
    record = load_adoption(str(repo))
    assert record is not None
    assert record.sufficient_stale is True
    assert cli.main(["status", str(repo)]) == 0
    assert "sufficient: stale" in capsys.readouterr().out

    assert cli.main(["sufficient", str(repo), "--not"]) == 0
    record = load_adoption(str(repo))
    assert record is not None
    assert record.sufficient is False
