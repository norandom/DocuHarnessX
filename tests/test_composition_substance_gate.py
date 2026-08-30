"""Unit tests for the deterministic page-body substance gate (task 2.2).

Task 2.2 (explore-first-simplification, boundary: *SubstanceGate*) adds
:func:`docuharnessx.composition.substance_gate.validate_page_body`. A body is
accepted **iff** all of:

* at least two distinct ``path:line`` citations whose paths exist under the
  target repository (Req 5.2, 7.1, 7.3);
* at least one identifier from the question's subject or evidence basenames
  as a whole token (Req 7.2);
* no retired template slogans (Req 6.3, 10.4);
* the body is not merely the question title restated (Req 7.5).

A Mermaid diagram is optional and is not the accept condition (Req 7.4).
"""

from __future__ import annotations

import dataclasses
import importlib
from pathlib import Path

import pytest

from docuharnessx.composition.substance_gate import GateResult, validate_page_body
from docuharnessx.planning.question_model import Question, QuestionKind, make_question_id

_FIXTURE_REPO = Path(__file__).parent / "fixtures" / "agentic_repo"

# Grounded sample: two real fixture files + load_config / Engine (task 2.2 observable).
_GROUNDED_BODY = (
    "The `Engine` class loads run settings through `load_config` (`config.py:10`)\n"
    "and then drives a bounded work cycle (`engine.py:16`).\n"
)


def _engine_question() -> Question:
    return Question(
        id=make_question_id(QuestionKind.COMPONENT, "engine"),
        kind=QuestionKind.COMPONENT,
        title="What does Engine do?",
        subject_name="Engine",
        evidence_paths=("engine.py", "config.py"),
    )


def _gate(
    body: str,
    *,
    question: Question | None = None,
    repo_path: Path | str | None = None,
) -> GateResult:
    return validate_page_body(
        body,
        repo_path=str(repo_path if repo_path is not None else _FIXTURE_REPO),
        question=question if question is not None else _engine_question(),
    )


# --------------------------------------------------------------------------- #
# Accept: grounded fixture body                                                #
# --------------------------------------------------------------------------- #


def test_accepts_grounded_body_citing_two_real_files_and_identifier() -> None:
    result = _gate(_GROUNDED_BODY)
    assert isinstance(result, GateResult)
    assert result.accepted is True
    assert result.cited_files >= 2
    assert result.reason


def test_accepts_engine_only_grounded_body_citing_two_real_files() -> None:
    # Observable: Engine (title already contains that token) plus two real files.
    body = (
        "The `Engine` class loads run settings (`config.py:10`)\n"
        "and then drives a bounded work cycle (`engine.py:16`).\n"
    )
    assert "load_config" not in body
    result = _gate(body)
    assert result.accepted is True
    assert result.cited_files >= 2


def test_accepts_grounded_body_without_mermaid() -> None:
    assert "```mermaid" not in _GROUNDED_BODY
    assert _gate(_GROUNDED_BODY).accepted is True


def test_accepts_mermaid_plus_valid_citations() -> None:
    body = (
        _GROUNDED_BODY
        + "\n```mermaid\n"
        + "graph TD\n"
        + "  Engine --> Config[load_config]\n"
        + "```\n"
    )
    assert _gate(body).accepted is True


# --------------------------------------------------------------------------- #
# Reject: mermaid is not the accept condition (Req 7.4)                        #
# --------------------------------------------------------------------------- #


def test_rejects_mermaid_without_citations() -> None:
    body = (
        "```mermaid\n"
        "graph TD\n"
        "  Engine --> Config[load_config]\n"
        "```\n"
        "\n"
        "The Engine uses load_config to start.\n"
    )
    result = _gate(body)
    assert result.accepted is False
    assert result.cited_files == 0


# --------------------------------------------------------------------------- #
# Reject: retired slogans (Req 6.3, 10.4)                                      #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "slogan",
    [
        "the fastest path for developers to work with Engine",
        "Who this is for: developers.",
        "Run the smallest action that makes progress toward understand.",
        "Verify you reached first success, then stop.",
        "Locate the Engine.",
        "1. Locate the Engine.",
        "Locate the subject.",
    ],
)
def test_rejects_retired_slogan_bodies(slogan: str) -> None:
    body = _GROUNDED_BODY + "\n" + slogan + "\n"
    assert _gate(body).accepted is False


def test_rejects_retired_slogans_case_insensitively() -> None:
    body = _GROUNDED_BODY + "\nFASTEST PATH FOR operators.\n"
    assert _gate(body).accepted is False


# --------------------------------------------------------------------------- #
# Reject: missing or insufficient real path:line citations (Req 7.1, 7.3)      #
# --------------------------------------------------------------------------- #


def test_rejects_citations_whose_paths_do_not_exist() -> None:
    body = (
        "The Engine loads via load_config (`no_such_module.py:1`) "
        "and (`also_missing.py:2`).\n"
    )
    result = _gate(body)
    assert result.accepted is False
    assert result.cited_files == 0


def test_rejects_when_only_one_cited_path_exists() -> None:
    body = (
        "The Engine loads via load_config (`config.py:10`) "
        "and (`ghost.py:1`).\n"
    )
    result = _gate(body)
    assert result.accepted is False
    assert result.cited_files == 1


def test_rejects_two_line_citations_of_the_same_file() -> None:
    body = (
        "The Engine loads via load_config (`config.py:10`) "
        "and again (`config.py:12`).\n"
    )
    result = _gate(body)
    assert result.accepted is False
    assert result.cited_files == 1


def test_rejects_body_with_no_citations() -> None:
    result = _gate("The Engine uses load_config to start the work cycle.\n")
    assert result.accepted is False
    assert result.cited_files == 0


# --------------------------------------------------------------------------- #
# Reject: no subject/evidence identifier (Req 7.2)                             #
# --------------------------------------------------------------------------- #


def test_rejects_generic_words_without_subject_or_evidence_identifier() -> None:
    # README.md and pyproject.toml exist under the fixture but are not this
    # question's evidence; "component" / "the project" are not identifiers.
    body = (
        "The component of the project is described in `README.md:1` "
        "and `pyproject.toml:7`.\n"
    )
    result = _gate(body)
    assert result.accepted is False


# --------------------------------------------------------------------------- #
# Reject: title-only restatement (Req 7.5)                                     #
# --------------------------------------------------------------------------- #


def test_rejects_title_only_restatement() -> None:
    question = _engine_question()
    body = (
        f"{question.title}\n\n"
        "See `engine.py:16` and `config.py:10`.\n"
    )
    result = _gate(body, question=question)
    assert result.accepted is False


def test_rejects_title_echo_with_no_extra_identifiers() -> None:
    question = _engine_question()
    body = f"{question.title} `engine.py:10` `config.py:10`\n"
    assert _gate(body, question=question).accepted is False


# --------------------------------------------------------------------------- #
# Determinism, totality, frozen result                                         #
# --------------------------------------------------------------------------- #


def test_deterministic_for_equal_input() -> None:
    first = _gate(_GROUNDED_BODY)
    second = _gate(_GROUNDED_BODY)
    assert first == second


def test_never_raises_on_pathological_input() -> None:
    question = _engine_question()
    for body in (
        "",
        "```mermaid",
        "```mermaid\n```",
        "no fences, no citations at all",
        ":1234 bare colon-number with no path",
        "`file.py:` colon but no digits",
        "Locate the Engine.",
    ):
        result = validate_page_body(
            body, repo_path=str(_FIXTURE_REPO), question=question
        )
        assert isinstance(result, GateResult)
        assert isinstance(result.accepted, bool)
        assert result.accepted is False


def test_gate_result_is_frozen() -> None:
    result = _gate(_GROUNDED_BODY)
    assert dataclasses.is_dataclass(result)
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.accepted = False  # type: ignore[misc]


# --------------------------------------------------------------------------- #
# Module surface                                                               #
# --------------------------------------------------------------------------- #


def test_module_all_lists_public_names() -> None:
    mod = importlib.import_module("docuharnessx.composition.substance_gate")
    assert set(mod.__all__) == {"GateResult", "validate_page_body"}
    for name in mod.__all__:
        assert hasattr(mod, name)
