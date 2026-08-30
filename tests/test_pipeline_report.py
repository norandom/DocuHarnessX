"""Unit tests for the frozen run-report types and serialize helpers (task 1.2).

Pins the RunReport boundary: planned / accepted / omitted counts, question ids,
and closed-set omissions — never page bodies (Req 9.1, 9.2, 9.3). Observable
completion: serializing a report with one ``no_model`` omission yields counts
and no body text.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any

import pytest

from docuharnessx.pages.model import Omission, OmissionReason, Page
from docuharnessx.pipeline.report import RunReport, to_dict, to_json, write_run_report
from docuharnessx.planning.question_model import QuestionKind, make_question_id

_SECRET_BODY = (
    "SECRET_PAGE_BODY_TEXT: the program starts in app.py:12 by calling "
    "load_config and constructing Engine."
)


def _question_id() -> str:
    return make_question_id(QuestionKind.STARTUP, "app.py")


def _page() -> Page:
    return Page(
        id=_question_id(),
        title="How does this program start?",
        summary="A one-liner that must not appear in the report.",
        body=_SECRET_BODY,
        subjects=("app.py",),
        related=(),
        cited_files=("app.py", "engine.py"),
    )


def _no_model_omission() -> Omission:
    return Omission(question_id=_question_id(), reason=OmissionReason.NO_MODEL)


def _no_model_report() -> RunReport:
    question_id = _question_id()
    return RunReport(
        planned=1,
        accepted=0,
        omitted=1,
        questions=(question_id,),
        omissions=(_no_model_omission(),),
    )


def _payload_keys(value: object) -> set[str]:
    keys: set[str] = set()
    if isinstance(value, dict):
        keys.update(value)
        for item in value.values():
            keys.update(_payload_keys(item))
    elif isinstance(value, list):
        for item in value:
            keys.update(_payload_keys(item))
    return keys


# --------------------------------------------------------------------------- #
# Field set and invariant (planned = accepted + omitted)                       #
# --------------------------------------------------------------------------- #


def test_run_report_field_set_has_counts_questions_omissions_and_no_body() -> None:
    fields = {field.name for field in dataclasses.fields(RunReport)}
    assert fields == {
        "planned",
        "accepted",
        "omitted",
        "questions",
        "omissions",
    }
    assert "body" not in fields
    assert "bodies" not in fields
    assert "pages" not in fields
    assert "roles" not in fields
    assert "intent" not in fields


def test_run_report_counts_add_up() -> None:
    report = _no_model_report()
    assert report.planned == report.accepted + report.omitted
    assert report.planned == 1
    assert report.accepted == 0
    assert report.omitted == 1


def test_run_report_rejects_count_mismatch() -> None:
    with pytest.raises(ValueError, match="accepted"):
        RunReport(
            planned=2,
            accepted=0,
            omitted=0,
            questions=(_question_id(),),
            omissions=(),
        )


def test_run_report_rejects_planned_not_matching_questions() -> None:
    with pytest.raises(ValueError, match="questions"):
        RunReport(
            planned=1,
            accepted=1,
            omitted=0,
            questions=(),
            omissions=(),
        )


def test_run_report_rejects_omitted_not_matching_omissions() -> None:
    question_id = _question_id()
    with pytest.raises(ValueError, match="omissions"):
        RunReport(
            planned=1,
            accepted=0,
            omitted=1,
            questions=(question_id,),
            omissions=(),
        )


def test_empty_run_report_is_valid() -> None:
    report = RunReport(
        planned=0,
        accepted=0,
        omitted=0,
        questions=(),
        omissions=(),
    )
    assert report.planned == report.accepted + report.omitted
    assert report.questions == ()
    assert report.omissions == ()


def test_run_reports_from_equal_inputs_are_equal() -> None:
    assert _no_model_report() == _no_model_report()


def test_run_report_is_hashable() -> None:
    assert hash(_no_model_report()) == hash(_no_model_report())


def test_run_report_fields_are_immutable() -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(_no_model_report(), "accepted", 1)


def test_run_report_collections_are_tuples() -> None:
    report = _no_model_report()
    assert isinstance(report.questions, tuple)
    assert isinstance(report.omissions, tuple)


# --------------------------------------------------------------------------- #
# Serialize: no_model omission, counts present, no body text (Req 9.1–9.3)     #
# --------------------------------------------------------------------------- #


def test_serialize_no_model_report_has_counts_and_no_body_text() -> None:
    """Observable completion for task 1.2 (Req 9.1, 9.2, 9.3)."""
    page = _page()
    report = _no_model_report()
    payload: dict[str, Any] = to_dict(report)
    rendered = to_json(report)

    assert payload["planned"] == 1
    assert payload["accepted"] == 0
    assert payload["omitted"] == 1
    assert payload["questions"] == [_question_id()]
    assert payload["omissions"] == [
        {"question_id": _question_id(), "reason": "no_model"}
    ]

    keys = _payload_keys(payload)
    assert "body" not in keys
    assert "bodies" not in keys
    assert page.body not in rendered
    assert _SECRET_BODY not in rendered
    assert page.summary not in rendered
    assert "body" not in rendered

    loaded = json.loads(rendered)
    assert loaded["planned"] == 1
    assert loaded["accepted"] == 0
    assert loaded["omitted"] == 1
    assert loaded["omissions"][0]["reason"] == "no_model"


def test_to_json_is_byte_stable_for_equal_reports() -> None:
    assert to_json(_no_model_report()) == to_json(_no_model_report())


@pytest.mark.parametrize("reason", list(OmissionReason))
def test_every_omission_reason_serializes_as_its_token(reason: OmissionReason) -> None:
    question_id = _question_id()
    report = RunReport(
        planned=1,
        accepted=0,
        omitted=1,
        questions=(question_id,),
        omissions=(Omission(question_id=question_id, reason=reason),),
    )
    payload = to_dict(report)
    assert payload["omissions"][0]["reason"] == reason.value
    assert "body" not in _payload_keys(payload)


def test_write_run_report_emits_json_and_markdown_without_bodies(tmp_path: Path) -> None:
    page = _page()
    write_run_report(_no_model_report(), tmp_path)

    json_text = (tmp_path / "report.json").read_text(encoding="utf-8")
    markdown = (tmp_path / "report.md").read_text(encoding="utf-8")

    json_payload = json.loads(json_text)
    assert json_payload["planned"] == 1
    assert json_payload["accepted"] == 0
    assert json_payload["omitted"] == 1
    assert json_payload["omissions"][0]["reason"] == "no_model"

    assert "planned" in markdown
    assert "accepted" in markdown
    assert "omitted" in markdown
    assert "no_model" in markdown
    assert _question_id() in markdown

    for blob in (json_text, markdown):
        assert page.body not in blob
        assert _SECRET_BODY not in blob
        assert page.summary not in blob
