"""Tests for the ``dhx run`` end-to-end orchestration (task 4.2 boundary: dhx CLI).

Task 4.2 takes the :class:`~docuharnessx.cli.PreparedRun` produced by task 4.1 and
drives the run to completion:

* populate the run-context slots (target-repo path, output dir, loaded
  ``Vocabulary`` at ``SLOT_VOCABULARY``) **before** the run (Req 6.2, 10.2);
* execute the composed pipeline **once** with a minimal skeleton ``BaseTask``;
* write the HarnessJournal trace under the resolved output directory and report
  the journal path on success (Req 4.4, 8.1);
* map exit reasons to process exit codes: ``done`` → 0; ``budget_exceeded`` and
  every error path → non-zero, with the budget-exceeded outcome recorded in the
  journal (Req 4.5, 4.6, 8.3, 8.4, 8.5).

Every test injects the test-scoped :class:`tests._fakes.FakeProvider`, so the
empty pipeline reaches ``exit_reason='done'`` with no network call and no real
credentials. The production model resolver is never exercised here.
"""

from __future__ import annotations

import json
import os

from harnessx.core.model_config import ModelConfig

from docuharnessx import cli
from docuharnessx.types import (
    SLOT_OUTPUT_DIR,
    SLOT_TARGET_REPO,
    SLOT_VOCABULARY,
)

from _fakes import FakeProvider


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #


def _fake_model() -> ModelConfig:
    """A ModelConfig bound to the no-network fake provider."""
    return ModelConfig(main=FakeProvider())


def _find_journal_jsonl(out_dir: str) -> list[str]:
    """Return every conversation ``.jsonl`` trace written under *out_dir*."""
    found: list[str] = []
    for root, _dirs, files in os.walk(out_dir):
        for name in files:
            if name.endswith(".jsonl") and not name.endswith("_trace.jsonl"):
                found.append(os.path.join(root, name))
    return found


# --------------------------------------------------------------------------- #
# orchestrate_run: slots populated before the run (Req 6.2, 10.2)             #
# --------------------------------------------------------------------------- #


def test_orchestrate_run_populates_all_slots_including_vocabulary(tmp_path) -> None:
    target = tmp_path / "repo"
    target.mkdir()
    out = tmp_path / "out"
    args = cli.build_parser().parse_args(["run", str(target), "--out", str(out)])
    prepared = cli.prepare_run(args, model_config=_fake_model())

    outcome = cli.orchestrate_run(prepared)

    state = outcome.run_context.state
    # All three run-data slots are populated before the run and survive it.
    assert state.get_slot(SLOT_TARGET_REPO) is not None
    assert state.get_slot(SLOT_OUTPUT_DIR) is not None
    assert state.get_slot(SLOT_VOCABULARY) is not None
    # The vocabulary slot carries the loaded Vocabulary (Req 10.2).
    assert outcome.run_context.vocabulary() is prepared.vocabulary
    assert outcome.run_context.target_repo() == prepared.target_repo
    assert outcome.run_context.output_dir() == prepared.out_dir


# --------------------------------------------------------------------------- #
# orchestrate_run: clean run → exit 0, journal written + reported (Req 4.4)   #
# --------------------------------------------------------------------------- #


def test_orchestrate_run_clean_run_exits_zero_with_journal_path(tmp_path) -> None:
    target = tmp_path / "repo"
    target.mkdir()
    out = tmp_path / "out"
    args = cli.build_parser().parse_args(["run", str(target), "--out", str(out)])
    prepared = cli.prepare_run(args, model_config=_fake_model())

    outcome = cli.orchestrate_run(prepared)

    assert outcome.exit_reason == "done"
    assert outcome.exit_code == 0
    # A journal trace was written under the resolved output directory.
    assert outcome.journal_path is not None
    assert os.path.isfile(outcome.journal_path)
    assert os.path.abspath(outcome.journal_path).startswith(os.path.abspath(str(out)))
    # It is one of the JSONL files HarnessJournal produced under out.
    assert outcome.journal_path in _find_journal_jsonl(str(out))


def test_orchestrate_run_journal_records_run_start_and_end(tmp_path) -> None:
    target = tmp_path / "repo"
    target.mkdir()
    out = tmp_path / "out"
    args = cli.build_parser().parse_args(["run", str(target), "--out", str(out)])
    prepared = cli.prepare_run(args, model_config=_fake_model())

    outcome = cli.orchestrate_run(prepared)

    # The conversation JSONL records the run boundaries and the turns. Record kinds
    # are carried in the ``type`` field (session_start … episode_end), with the
    # user/assistant turns recorded as ``raw_user`` / ``raw_assistant``.
    with open(outcome.journal_path, "r", encoding="utf-8") as handle:
        records = [json.loads(line) for line in handle if line.strip()]
    types = [r.get("type") for r in records]
    # Run start and run end are both recorded (Req 8.1).
    assert "session_start" in types, types
    assert "episode_end" in types, types
    # The single user turn and the assistant's end-turn response are recorded.
    assert "raw_user" in types, types
    assert "raw_assistant" in types, types


# --------------------------------------------------------------------------- #
# main(): full run path through the CLI exits 0 and reports the journal        #
# --------------------------------------------------------------------------- #


def test_main_run_exits_zero_and_reports_journal_path(tmp_path, capsys) -> None:
    target = tmp_path / "repo"
    target.mkdir()
    out = tmp_path / "out"
    code = cli.main(
        ["run", str(target), "--out", str(out)],
        model_config=_fake_model(),
    )
    assert code == 0
    stdout = capsys.readouterr().out
    journals = _find_journal_jsonl(str(out))
    assert journals, "a journal trace must be written under the output directory"
    # The journal path (or its session directory) is reported on success.
    assert any(os.path.dirname(j) in stdout or j in stdout for j in journals), stdout


def test_main_run_uses_default_out_dir_when_omitted(tmp_path, capsys) -> None:
    # When --out is omitted the run journal lands under the documented default
    # (<target>/.docuharnessx/out), so a run is self-contained in the target.
    target = tmp_path / "repo"
    target.mkdir()
    code = cli.main(["run", str(target)], model_config=_fake_model())
    assert code == 0
    default_out = os.path.join(str(target), ".docuharnessx", "out")
    assert _find_journal_jsonl(default_out), "journal must land under the default out dir"


# --------------------------------------------------------------------------- #
# Budget-exceeded simulation → non-zero exit, recorded in the journal          #
# (Req 4.5, 8.4)                                                               #
# --------------------------------------------------------------------------- #


def test_orchestrate_run_budget_exceeded_exits_nonzero(tmp_path) -> None:
    target = tmp_path / "repo"
    target.mkdir()
    out = tmp_path / "out"
    args = cli.build_parser().parse_args(["run", str(target), "--out", str(out)])
    prepared = cli.prepare_run(args, model_config=_fake_model())

    # max_steps=0 makes State.budget_exceeded() true before the first step, so the
    # run loop exits with exit_reason='budget_exceeded' with NO model call/network.
    outcome = cli.orchestrate_run(prepared, max_steps=0)

    assert outcome.exit_reason == "budget_exceeded"
    assert outcome.exit_code != 0


def test_budget_exceeded_recorded_in_journal(tmp_path) -> None:
    target = tmp_path / "repo"
    target.mkdir()
    out = tmp_path / "out"
    args = cli.build_parser().parse_args(["run", str(target), "--out", str(out)])
    prepared = cli.prepare_run(args, model_config=_fake_model())

    outcome = cli.orchestrate_run(prepared, max_steps=0)

    # The budget-exceeded outcome is recorded in the run journal (Req 8.4): the
    # trace file carries a task_end record with exit_reason 'budget_exceeded'.
    assert outcome.journal_path is not None
    trace_path = outcome.journal_path.replace(".jsonl", "_trace.jsonl")
    assert os.path.isfile(trace_path)
    blob = open(trace_path, "r", encoding="utf-8").read()
    assert "budget_exceeded" in blob


def test_main_budget_exceeded_exits_nonzero(tmp_path, capsys) -> None:
    target = tmp_path / "repo"
    target.mkdir()
    out = tmp_path / "out"
    code = cli.main(
        ["run", str(target), "--out", str(out)],
        model_config=_fake_model(),
        max_steps=0,
    )
    assert code != 0


# --------------------------------------------------------------------------- #
# Exit-reason → exit-code mapping is total (Req 4.6, 8.5)                       #
# --------------------------------------------------------------------------- #


def test_exit_code_for_reason_maps_done_to_zero_and_others_nonzero() -> None:
    assert cli.exit_code_for_reason("done") == 0
    for reason in ("budget_exceeded", "loop_detected", "error", "interrupted"):
        assert cli.exit_code_for_reason(reason) != 0
    # An unrecognised reason is conservatively non-zero (never silently 0).
    assert cli.exit_code_for_reason("some-unexpected-reason") != 0
