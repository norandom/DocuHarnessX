"""Density trim for question summaries (architect-narrative task 4)."""

from __future__ import annotations

from docuharnessx.assembler.pages import render_question_page
from docuharnessx.composition.density import (
    CITATIONS_ONLY_NOTE,
    trim_page,
    trim_summary,
)
from docuharnessx.composition.substance_gate import validate_page_body
from docuharnessx.pages.model import Page
from docuharnessx.planning.question_model import QuestionKind, make_question_id


def _page(
    *,
    summary: str,
    body: str = "Engine drives a bounded work cycle from loaded config.",
    cited: tuple[str, ...] = ("engine.py", "config.py"),
) -> Page:
    return Page(
        id=make_question_id(QuestionKind.COMPONENT, "engine"),
        title="What does Engine do?",
        summary=summary,
        body=body,
        subjects=("engine",),
        related=(),
        cited_files=cited,
    )


def test_trim_is_byte_stable() -> None:
    page = _page(summary="Engine loads config. It then runs a cycle.")
    assert trim_summary(page) == trim_summary(page)
    assert trim_page(page) == trim_page(page)


def test_short_summary_is_unchanged() -> None:
    page = _page(summary="Engine loads config and runs a cycle.")
    assert trim_summary(page) is page or trim_summary(page).summary == page.summary
    assert trim_page(page).note == ""


def test_char_cap_keeps_a_complete_sentence() -> None:
    first = (
        "DocuHarnessX is a Python package — version 2.0.0 — whose own docstring "
        'describes it as a tool to "generate grounded developer documentation '
        'from a software repository".'
    )
    second = (
        "In practice it is a CLI-driven pipeline that scans a target repo, "
        "decides which software questions deserve documentation, runs bounded "
        "model agents to write those pages, and assembles the accepted ones "
        "into an MkDocs site."
    )
    assert len(first) <= 280
    assert len(first) + 1 + len(second) > 280
    page = _page(summary=first + " " + second + " Extra dump continues. " * 10)
    trimmed = trim_summary(page)
    assert trimmed.summary == first
    assert trimmed.summary.endswith(".")
    assert "deserve" not in trimmed.summary
    assert len(trimmed.summary) <= 280


def test_long_cited_summary_trims_to_two_sentences_without_path_line() -> None:
    dump = (
        "Engine loads config and runs a cycle. "
        "It then writes a report for the operator. "
        "This extra dump names `engine.py:16` and `config.py:10` and keeps going. "
        + ("More inspection. " * 40)
    )
    assert len(dump) > 600
    page = _page(summary=dump, body=dump + "\n\nBody stays.")
    trimmed = trim_summary(page)
    assert trimmed.body == page.body
    assert len(trimmed.summary) <= 280
    assert trimmed.summary.count(".") <= 2
    assert "engine.py:16" not in trimmed.summary
    assert "config.py:10" not in trimmed.summary
    assert "path:" not in trimmed.summary
    assert trimmed.summary.startswith("Engine loads config")
    assert "It then writes a report" in trimmed.summary
    assert "More inspection" not in trimmed.summary


def test_empty_after_trim_keeps_body_and_records_a_note() -> None:
    page = _page(
        summary="`engine.py:1` (`config.py:2`)",
        body="Engine drives a bounded work cycle from loaded config.",
    )
    outcome = trim_page(page)
    assert outcome.page.body == page.body
    assert outcome.page.summary == ""
    assert outcome.note == CITATIONS_ONLY_NOTE
    assert trim_summary(page).body == page.body


def test_substance_gate_still_requires_citations_in_the_body(tmp_path) -> None:
    repo = tmp_path
    (repo / "engine.py").write_text("class Engine:\n    pass\n", encoding="utf-8")
    (repo / "config.py").write_text("def load_config():\n    return {}\n", encoding="utf-8")
    from docuharnessx.planning.question_model import Question, QuestionKind, make_question_id

    question = Question(
        id=make_question_id(QuestionKind.COMPONENT, "engine"),
        kind=QuestionKind.COMPONENT,
        title="What does Engine do?",
        subject_name="Engine",
        evidence_paths=("engine.py", "config.py"),
    )
    body = (
        "The Engine class loads run settings through load_config "
        "(`config.py:10`) and then drives a cycle (`engine.py:16`).\n"
    )
    gate = validate_page_body(body, repo_path=str(repo), question=question)
    assert gate.accepted
    page = trim_summary(_page(summary=body, body=body))
    assert "config.py:" not in page.summary
    assert "engine.py:" in page.body


def test_assembled_depth_one_is_trimmed_summary_not_body() -> None:
    dump = (
        "Engine loads config and runs a cycle. "
        "It then writes a report for the operator. "
        "DEPTH_ONE_MUST_NOT_KEEP_THIS dump (`engine.py:16`). "
        + ("Pad. " * 50)
    )
    body = "BODY_MARKER Engine drives a bounded work cycle.\n"
    page = _page(summary=dump, body=body)
    _path, markdown = render_question_page(page, (page,), include_diagrams=False)
    depth_one = markdown.split('data-min="1"', 1)[1].split("</div>", 1)[0]
    assert "Engine loads config" in depth_one
    assert "BODY_MARKER" not in depth_one
    assert "DEPTH_ONE_MUST_NOT_KEEP_THIS" not in depth_one
    assert "engine.py:16" not in depth_one
    assert len(depth_one) < len(dump)
    assert 'data-min="5"' in markdown
    assert "BODY_MARKER" in markdown.split('data-min="5"', 1)[1]


def test_assembled_empty_trim_keeps_body_and_notes() -> None:
    page = _page(summary="`engine.py:1`")
    _path, markdown = render_question_page(page, (page,), include_diagrams=False)
    assert "dhx-density:" in markdown
    assert CITATIONS_ONLY_NOTE in markdown
    assert page.body in markdown
    if 'data-min="1"' in markdown:
        depth_one = markdown.split('data-min="1"', 1)[1].split("</div>", 1)[0]
        assert "engine.py:1" not in depth_one
