"""Tests for the ``dhx run`` explore-first orchestration (task 4.2 / 5.1).

``orchestrate_run`` drives :func:`docuharnessx.pipeline.run.run_pipeline`.
Completed runs including honest-empty exit 0 and write a run report. The dummy
outer harness is not the documentation run.
"""

from __future__ import annotations

import os

from harnessx.core.model_config import ModelConfig

from docuharnessx import cli

from _fakes import FakeProvider


def _fake_model() -> ModelConfig:
    """A ModelConfig bound to the no-network fake provider."""
    return ModelConfig(main=FakeProvider())


def test_orchestrate_run_clean_run_exits_zero_with_report(tmp_path) -> None:
    target = tmp_path / "repo"
    target.mkdir()
    out = tmp_path / "out"
    args = cli.build_parser().parse_args(["run", str(target), "--out", str(out)])
    prepared = cli.prepare_run(args, model_config=_fake_model())

    outcome = cli.orchestrate_run(prepared)

    assert outcome.exit_reason == "done"
    assert outcome.exit_code == 0
    assert os.path.isfile(os.path.join(str(out), "report.json"))


def test_main_run_exits_zero_and_reports_report_path(tmp_path, capsys) -> None:
    target = tmp_path / "repo"
    target.mkdir()
    out = tmp_path / "out"
    code = cli.main(
        ["run", str(target), "--out", str(out)],
        model_config=_fake_model(),
    )
    assert code == 0
    stdout = capsys.readouterr().out
    report = os.path.join(str(out), "report.json")
    assert os.path.isfile(report), "a run report must be written under the output directory"
    assert report in stdout or "Report:" in stdout, stdout


def test_main_run_uses_default_out_dir_when_omitted(tmp_path, capsys) -> None:
    target = tmp_path / "repo"
    target.mkdir()
    code = cli.main(["run", str(target)], model_config=_fake_model())
    assert code == 0
    default_out = os.path.join(str(target), ".docuharnessx", "out")
    assert os.path.isfile(os.path.join(default_out, "report.json")), (
        "report must land under the default out dir"
    )


def test_exit_code_for_reason_maps_done_to_zero_and_others_nonzero() -> None:
    assert cli.exit_code_for_reason("done") == 0
    for reason in ("budget_exceeded", "loop_detected", "error", "interrupted"):
        assert cli.exit_code_for_reason(reason) != 0
    assert cli.exit_code_for_reason("some-unexpected-reason") != 0
