"""Integration tests for the explore-first writer adapter (task 3.1).

Task 3.1 (explore-first-simplification, boundary: *ExploreWriter*) adds
:func:`docuharnessx.composition.explore_writer.write_questions`. For each planned
question it runs one bounded writer over a read-only target repo using
:func:`~docuharnessx.composition.question_task.build_question_task` and
:func:`~docuharnessx.composition.substance_gate.validate_page_body`. Failures
omit the question; they never substitute an outline body.

Observable completion (tasks.md 3.1 / Req 5.2, 5.3, 6.1, 6.3, 6.4, 11.1, 11.2):

* shipped sample + scripted writer that reads files then returns a grounded
  body → accepted page;
* scripted writer that answers immediately with outline text → zero pages and
  ``not_inspected`` or ``gate_rejected``;
* missing repo path → ``inspection_impossible`` and zero pages.
"""

from __future__ import annotations

import inspect
import shutil
from collections.abc import Sequence
from pathlib import Path

import pytest

from docuharnessx.pages.model import Omission, OmissionReason, Page
from docuharnessx.planning.question_model import Question, QuestionKind, make_question_id

from tests._fakes import FakeProvider, ScriptedAgentProvider

_FIXTURE_REPO = Path(__file__).parent / "fixtures" / "agentic_repo"

# Substance-gate-passing body: two real fixture files + Engine / load_config.
_GROUNDED_BODY = (
    "The `Engine` class loads run settings through `load_config` (`config.py:10`)\n"
    "and then drives a bounded work cycle (`engine.py:16`).\n"
)

_OUTLINE_BODY = "Locate the CLI. Run the smallest action."


def _engine_question() -> Question:
    return Question(
        id=make_question_id(QuestionKind.COMPONENT, "engine"),
        kind=QuestionKind.COMPONENT,
        title="What does Engine do?",
        subject_name="Engine",
        evidence_paths=("engine.py", "config.py"),
    )


def _build_question() -> Question:
    return Question(
        id=make_question_id(QuestionKind.BUILD, "pyproject.toml"),
        kind=QuestionKind.BUILD,
        title="How is this project built and verified?",
        subject_name="pyproject.toml",
        evidence_paths=("pyproject.toml",),
    )


def _rooted_copy(tmp_path: Path) -> str:
    dest = tmp_path / "agentic_repo"
    shutil.copytree(_FIXTURE_REPO, dest)
    return str(dest)


def _write(questions: tuple[Question, ...], *, repo_path: str, model: object | None):
    from docuharnessx.composition.explore_writer import write_questions

    return write_questions(questions, repo_path=repo_path, model=model)


# --------------------------------------------------------------------------- #
# Inspecting scripted writer → accepted grounded page (Req 5.2, 11.1)          #
# --------------------------------------------------------------------------- #


def test_inspecting_scripted_writer_accepts_grounded_page(tmp_path: Path) -> None:
    provider = ScriptedAgentProvider(body=_GROUNDED_BODY)
    pages, omissions = _write(
        (_engine_question(),),
        repo_path=_rooted_copy(tmp_path),
        model=provider,
    )

    assert omissions == ()
    assert len(pages) == 1
    page = pages[0]
    assert isinstance(page, Page)
    assert page.id == "component:engine"
    assert page.title == "What does Engine do?"
    assert page.body == _GROUNDED_BODY
    assert "Engine" in page.body or "load_config" in page.body
    assert "config.py:" in page.body
    assert "engine.py:" in page.body
    assert "config.py" in page.cited_files
    assert "engine.py" in page.cited_files
    assert "Engine" in page.subjects
    # Real tool loop: scripted Read/Grep turns actually ran (Req 5.3 inverse).
    assert provider.complete_calls > 1
    assert "engine.py" in provider.read_paths
    assert "config.py" in provider.read_paths


def test_inspecting_writer_uses_default_scripted_body_when_it_passes_gate(
    tmp_path: Path,
) -> None:
    from tests._fakes import SCRIPTED_AGENT_BODY

    provider = ScriptedAgentProvider()
    pages, omissions = _write(
        (_engine_question(),),
        repo_path=_rooted_copy(tmp_path),
        model=provider,
    )
    assert omissions == ()
    assert len(pages) == 1
    assert pages[0].body == SCRIPTED_AGENT_BODY
    assert "Engine" in pages[0].body or "load_config" in pages[0].body
    assert provider.complete_calls > 1


# --------------------------------------------------------------------------- #
# No tool loop → omit, never publish outline (Req 5.3, 6.1, 6.3, 11.2)         #
# --------------------------------------------------------------------------- #


def test_immediate_outline_writer_omits_with_not_inspected_or_gate_rejected(
    tmp_path: Path,
) -> None:
    pages, omissions = _write(
        (_engine_question(),),
        repo_path=_rooted_copy(tmp_path),
        model=FakeProvider(content=_OUTLINE_BODY),
    )
    assert pages == ()
    assert len(omissions) == 1
    assert omissions[0].question_id == "component:engine"
    assert omissions[0].reason in {
        OmissionReason.NOT_INSPECTED,
        OmissionReason.GATE_REJECTED,
    }


def test_immediate_grounded_body_is_omitted_as_not_inspected(tmp_path: Path) -> None:
    """A passing body with no tool loop is still omitted (Req 5.3)."""
    pages, omissions = _write(
        (_engine_question(),),
        repo_path=_rooted_copy(tmp_path),
        model=FakeProvider(content=_GROUNDED_BODY),
    )
    assert pages == ()
    assert omissions == (
        Omission(
            question_id="component:engine",
            reason=OmissionReason.NOT_INSPECTED,
        ),
    )


def test_empty_body_after_inspection_is_omitted_as_empty(tmp_path: Path) -> None:
    pages, omissions = _write(
        (_engine_question(),),
        repo_path=_rooted_copy(tmp_path),
        model=ScriptedAgentProvider(body=""),
    )
    assert pages == ()
    assert omissions == (
        Omission(question_id="component:engine", reason=OmissionReason.EMPTY),
    )


def test_gate_reject_after_inspection_is_omitted_as_gate_rejected(
    tmp_path: Path,
) -> None:
    pages, omissions = _write(
        (_engine_question(),),
        repo_path=_rooted_copy(tmp_path),
        model=ScriptedAgentProvider(
            body="The Engine is documented without any source citations.\n"
        ),
    )
    assert pages == ()
    assert omissions == (
        Omission(
            question_id="component:engine",
            reason=OmissionReason.GATE_REJECTED,
        ),
    )


# --------------------------------------------------------------------------- #
# Missing / non-directory repo → inspection_impossible (Req 6.4)               #
# --------------------------------------------------------------------------- #


def test_missing_repo_path_omits_all_as_inspection_impossible(tmp_path: Path) -> None:
    questions = (_engine_question(), _build_question())
    pages, omissions = _write(
        questions,
        repo_path=str(tmp_path / "does-not-exist"),
        model=ScriptedAgentProvider(body=_GROUNDED_BODY),
    )
    assert pages == ()
    assert omissions == tuple(
        Omission(question_id=question.id, reason=OmissionReason.INSPECTION_IMPOSSIBLE)
        for question in questions
    )


def test_repo_path_that_is_a_file_omits_all_as_inspection_impossible(
    tmp_path: Path,
) -> None:
    a_file = tmp_path / "not-a-repo"
    a_file.write_text("not a directory\n", encoding="utf-8")
    pages, omissions = _write(
        (_engine_question(),),
        repo_path=str(a_file),
        model=ScriptedAgentProvider(body=_GROUNDED_BODY),
    )
    assert pages == ()
    assert omissions == (
        Omission(
            question_id="component:engine",
            reason=OmissionReason.INSPECTION_IMPOSSIBLE,
        ),
    )


# --------------------------------------------------------------------------- #
# no_model / continue after omission / never fallback                          #
# --------------------------------------------------------------------------- #


def test_none_model_omits_all_as_no_model(tmp_path: Path) -> None:
    questions = (_engine_question(), _build_question())
    pages, omissions = _write(
        questions,
        repo_path=_rooted_copy(tmp_path),
        model=None,
    )
    assert pages == ()
    assert omissions == tuple(
        Omission(question_id=question.id, reason=OmissionReason.NO_MODEL)
        for question in questions
    )


class _MixedQuestionProvider(ScriptedAgentProvider):
    """Inspect+ground Engine; answer the other question immediately with outline."""

    def __init__(self) -> None:
        super().__init__(body=_GROUNDED_BODY)
        self._outline = FakeProvider(content=_OUTLINE_BODY)

    async def complete(
        self,
        messages: Sequence[object],
        tools: Sequence[object],
        stream_callback: object | None = None,
    ):
        text = "\n".join(str(getattr(message, "content", "") or "") for message in messages)
        if "What does Engine do?" in text:
            return await super().complete(messages, tools, stream_callback)
        return await self._outline.complete(messages, tools, stream_callback)


def test_continues_remaining_questions_after_an_omission(tmp_path: Path) -> None:
    provider = _MixedQuestionProvider()
    pages, omissions = _write(
        (_build_question(), _engine_question()),
        repo_path=_rooted_copy(tmp_path),
        model=provider,
    )
    assert [page.id for page in pages] == ["component:engine"]
    assert pages[0].body == _GROUNDED_BODY
    assert len(omissions) == 1
    assert omissions[0].question_id == "build:pyproject.toml"
    assert omissions[0].reason in {
        OmissionReason.NOT_INSPECTED,
        OmissionReason.GATE_REJECTED,
        OmissionReason.EMPTY,
    }


def test_module_never_references_fallback_renderer() -> None:
    from docuharnessx.composition import explore_writer

    source = inspect.getsource(explore_writer)
    assert "render_fallback_body" not in source
    assert "render_fallback_summary" not in source


def test_write_questions_never_calls_fallback_renderer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from docuharnessx.composition import fallback

    def _boom(*_args: object, **_kwargs: object) -> str:
        raise AssertionError("explore writer must not call the fallback renderer")

    monkeypatch.setattr(fallback, "render_fallback_body", _boom)
    monkeypatch.setattr(fallback, "render_fallback_summary", _boom)

    pages, omissions = _write(
        (_engine_question(),),
        repo_path=_rooted_copy(tmp_path),
        model=FakeProvider(content=_OUTLINE_BODY),
    )
    assert pages == ()
    assert omissions


def test_uses_build_question_task_not_cobesy_agent_task(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from docuharnessx.composition import question_task

    seen: list[Question] = []
    real = question_task.build_question_task

    def _spy(question: Question, **kwargs: object):
        seen.append(question)
        return real(question, **kwargs)

    monkeypatch.setattr(
        "docuharnessx.composition.explore_writer.build_question_task", _spy
    )

    def _cobesy(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("must not call build_agent_task")

    monkeypatch.setattr(
        "docuharnessx.composition.task_prompt.build_agent_task", _cobesy
    )

    question = _engine_question()
    pages, omissions = _write(
        (question,),
        repo_path=_rooted_copy(tmp_path),
        model=ScriptedAgentProvider(body=_GROUNDED_BODY),
    )
    assert seen == [question]
    assert pages and not omissions


def test_empty_question_tuple_returns_empty_results(tmp_path: Path) -> None:
    pages, omissions = _write(
        (),
        repo_path=_rooted_copy(tmp_path),
        model=ScriptedAgentProvider(body=_GROUNDED_BODY),
    )
    assert pages == ()
    assert omissions == ()

