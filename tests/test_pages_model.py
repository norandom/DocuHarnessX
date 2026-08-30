"""Unit tests for the frozen page and omission types (task 1.2).

Pins the Page / Omission model boundary: a slim accepted document with no reader
roles or intent, plus an omission that is only a question id and a closed-set
reason. RunReport serialize lives in ``tests/test_pipeline_report.py``.
"""

from __future__ import annotations

import dataclasses

import pytest

from docuharnessx.pages.model import Omission, OmissionReason, Page
from docuharnessx.planning.question_model import QuestionKind, make_question_id


def _page() -> Page:
    return Page(
        id=make_question_id(QuestionKind.STARTUP, "app.py"),
        title="How does this program start?",
        summary="The CLI starts in app.py by loading config and constructing Engine.",
        body=(
            "The program starts in app.py:12 by calling load_config "
            "(config.py:8) and constructing Engine (engine.py:15)."
        ),
        subjects=("app.py",),
        related=("component:engine",),
        cited_files=("app.py", "config.py", "engine.py"),
    )


def _omission() -> Omission:
    return Omission(
        question_id=make_question_id(QuestionKind.STARTUP, "app.py"),
        reason=OmissionReason.NO_MODEL,
    )


# --------------------------------------------------------------------------- #
# Page field set — no roles or intent (Req 1.4, 10.3)                          #
# --------------------------------------------------------------------------- #


def test_page_field_set_has_no_role_or_intent() -> None:
    fields = {field.name for field in dataclasses.fields(Page)}
    assert fields == {
        "id",
        "title",
        "summary",
        "body",
        "subjects",
        "related",
        "cited_files",
    }
    assert "roles" not in fields
    assert "role" not in fields
    assert "intent" not in fields


def test_page_round_trips() -> None:
    original = _page()
    assert original.id == "startup:app.py"
    assert original.title == "How does this program start?"
    assert original.summary.startswith("The CLI starts")
    assert "engine.py:15" in original.body
    assert original.subjects == ("app.py",)
    assert original.related == ("component:engine",)
    assert original.cited_files == ("app.py", "config.py", "engine.py")

    rebuilt = Page(**dataclasses.asdict(original))
    assert rebuilt == original


def test_page_collections_are_tuples() -> None:
    page = _page()
    assert isinstance(page.subjects, tuple)
    assert isinstance(page.related, tuple)
    assert isinstance(page.cited_files, tuple)


def test_pages_from_equal_inputs_are_equal() -> None:
    assert _page() == _page()


def test_page_is_hashable() -> None:
    assert hash(_page()) == hash(_page())


@pytest.mark.parametrize(
    "field, value",
    [
        ("title", "other"),
        ("id", "startup:other"),
        ("body", ""),
        ("subjects", ()),
        ("related", ()),
        ("cited_files", ()),
    ],
)
def test_page_fields_are_immutable(field: str, value: object) -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(_page(), field, value)


# --------------------------------------------------------------------------- #
# Omission + closed-set reasons (Req 9.2)                                      #
# --------------------------------------------------------------------------- #


def test_omission_reason_closed_set() -> None:
    assert {reason.value for reason in OmissionReason} == {
        "not_inspected",
        "empty",
        "gate_rejected",
        "no_model",
        "inspection_impossible",
    }


def test_omission_field_set() -> None:
    fields = {field.name for field in dataclasses.fields(Omission)}
    assert fields == {"question_id", "reason"}


def test_omission_round_trips() -> None:
    original = _omission()
    assert original.question_id == "startup:app.py"
    assert original.reason is OmissionReason.NO_MODEL
    rebuilt = Omission(**dataclasses.asdict(original))
    assert rebuilt == original


def test_omission_rejects_unknown_reason() -> None:
    with pytest.raises(ValueError):
        OmissionReason("fallback_outline")


def test_omissions_from_equal_inputs_are_equal() -> None:
    assert _omission() == _omission()


def test_omission_is_hashable() -> None:
    assert hash(_omission()) == hash(_omission())


def test_omission_fields_are_immutable() -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(_omission(), "reason", OmissionReason.EMPTY)
