"""Unit tests for the deterministic agent-body structure gate (task 2.2).

Task 2.2 (agentic-codebase-writer, boundary: *structure_gate*) adds
:func:`docuharnessx.composition.structure_gate.validate_agent_body`, the deterministic
gate that decides whether an agent-produced body is accepted verbatim or the deterministic
fallback is used (Req 4.4, 9.5). A body is accepted **iff** it carries:

* at least one fenced ```` ```mermaid ```` block whose first content line names a supported
  diagram type (``graph``/``flowchart``/``sequenceDiagram``/``classDiagram``/``erDiagram``/
  ``stateDiagram``); and
* at least ``min_citations`` *distinct* ``file:line`` citations (a path token followed by
  ``:<digits>``).

It reports the counts and a reason on a :class:`GateResult`, is pure/deterministic, and
never raises (design "validate_agent_body", lines 433-461). These tests pin that contract:
a ``graph TD`` body with enough citations is accepted, a body with no Mermaid is rejected,
a body with too few citations is rejected, distinct cited files are counted correctly, and
the function is deterministic and total over arbitrary input.
"""

from __future__ import annotations

import importlib

from docuharnessx.composition.budgets import MIN_CITED_FILES
from docuharnessx.composition.structure_gate import GateResult, validate_agent_body


# --------------------------------------------------------------------------- #
# Body fixtures                                                                #
# --------------------------------------------------------------------------- #


def _body_with(mermaid: str, citation_lines: list[str]) -> str:
    """Assemble a Markdown body with one mermaid fence + the given citation lines."""
    parts = ["# Title", "", "Lead conclusion first.", ""]
    parts.append("```mermaid")
    parts.append(mermaid)
    parts.append("  A[Start] --> B[End]")
    parts.append("```")
    parts.append("")
    parts.extend(citation_lines)
    return "\n".join(parts) + "\n"


_THREE_CITATIONS = [
    "See `src/app.py:12` for the entry point.",
    "The loader lives in `src/loader.py:88`.",
    "Config is parsed in `src/config.py:5`.",
]


# --------------------------------------------------------------------------- #
# Accept path                                                                  #
# --------------------------------------------------------------------------- #


def test_accepts_graph_td_with_enough_citations() -> None:
    body = _body_with("graph TD", _THREE_CITATIONS)
    result = validate_agent_body(body)
    assert isinstance(result, GateResult)
    assert result.accepted is True
    assert result.mermaid_blocks >= 1
    assert result.cited_files >= MIN_CITED_FILES
    assert result.reason  # a non-empty human-readable reason


def test_accepts_each_supported_diagram_type() -> None:
    for first_line in (
        "graph TD",
        "flowchart TD",
        "sequenceDiagram",
        "classDiagram",
        "erDiagram",
        "stateDiagram-v2",
    ):
        body = _body_with(first_line, _THREE_CITATIONS)
        result = validate_agent_body(body)
        assert result.accepted is True, first_line


def test_accepts_exactly_min_citations() -> None:
    body = _body_with("graph TD", _THREE_CITATIONS[:MIN_CITED_FILES])
    result = validate_agent_body(body)
    assert result.accepted is True
    assert result.cited_files == MIN_CITED_FILES


def test_accepts_diagram_after_init_directive() -> None:
    # Mermaid allows a ``%%{ init: ... }%%`` directive before the diagram type.
    body = _body_with("%%{ init: { 'theme': 'dark' } }%%\ngraph TD", _THREE_CITATIONS)
    assert validate_agent_body(body).accepted is True


def test_accepts_diagram_after_comment_line() -> None:
    body = _body_with("%% flow of the startup path\nflowchart TD", _THREE_CITATIONS)
    assert validate_agent_body(body).accepted is True


def test_accepts_diagram_after_yaml_frontmatter() -> None:
    # Mermaid allows a ``---`` YAML frontmatter block (e.g. a title) before the type.
    body = _body_with("---\ntitle: Startup Flow\n---\ngraph TD", _THREE_CITATIONS)
    assert validate_agent_body(body).accepted is True


def test_accepts_broadened_diagram_types() -> None:
    for first_line in ("mindmap", "gitGraph", "journey", "timeline"):
        body = _body_with(first_line, _THREE_CITATIONS)
        assert validate_agent_body(body).accepted is True, first_line


def test_still_rejects_mermaid_fence_whose_first_line_is_prose() -> None:
    # A ```mermaid fence opened but filled with prose (no diagram-type line) must still be
    # rejected — the preamble tolerance must not become a blanket accept-any-fence.
    body = _body_with("This diagram shows how the modules connect.", _THREE_CITATIONS)
    assert validate_agent_body(body).accepted is False


# --------------------------------------------------------------------------- #
# Reject: no Mermaid                                                           #
# --------------------------------------------------------------------------- #


def test_rejects_body_with_no_mermaid_fence() -> None:
    body = "\n".join(["# Title", "", *_THREE_CITATIONS]) + "\n"
    result = validate_agent_body(body)
    assert result.accepted is False
    assert result.mermaid_blocks == 0
    assert result.reason


def test_rejects_fenced_block_with_unsupported_diagram_type() -> None:
    # A fenced mermaid block but the first content line is not a supported type.
    body = _body_with("piechart title Foo", _THREE_CITATIONS)
    result = validate_agent_body(body)
    assert result.accepted is False
    assert result.mermaid_blocks == 0


def test_rejects_non_mermaid_code_fence() -> None:
    # A python code fence whose body says "graph TD" must NOT count as a mermaid block.
    body = "\n".join(
        [
            "# Title",
            "",
            "```python",
            "graph TD",
            "x = 1",
            "```",
            "",
            *_THREE_CITATIONS,
        ]
    ) + "\n"
    result = validate_agent_body(body)
    assert result.accepted is False
    assert result.mermaid_blocks == 0


# --------------------------------------------------------------------------- #
# Reject: too few citations                                                    #
# --------------------------------------------------------------------------- #


def test_rejects_body_with_too_few_citations() -> None:
    body = _body_with("graph TD", _THREE_CITATIONS[: MIN_CITED_FILES - 1])
    result = validate_agent_body(body)
    assert result.accepted is False
    assert result.cited_files == MIN_CITED_FILES - 1
    assert result.reason


def test_distinct_files_counted_not_raw_occurrences() -> None:
    # The same file cited on three different lines is still ONE distinct cited file.
    body = _body_with(
        "graph TD",
        [
            "Loader at `src/loader.py:10`.",
            "Also `src/loader.py:20`.",
            "And `src/loader.py:30`.",
        ],
    )
    result = validate_agent_body(body)
    assert result.cited_files == 1
    assert result.accepted is False


def test_distinct_files_counts_unique_paths() -> None:
    body = _body_with(
        "graph TD",
        [
            "`a/one.py:1`",
            "`a/one.py:2`",  # duplicate path, distinct line
            "`b/two.py:3`",
            "`c/three.py:4`",
        ],
    )
    result = validate_agent_body(body)
    assert result.cited_files == 3
    assert result.accepted is True


# --------------------------------------------------------------------------- #
# min_citations override                                                       #
# --------------------------------------------------------------------------- #


def test_min_citations_override_raises_the_bar() -> None:
    body = _body_with("graph TD", _THREE_CITATIONS)  # exactly 3 distinct
    assert validate_agent_body(body, min_citations=3).accepted is True
    assert validate_agent_body(body, min_citations=4).accepted is False


def test_default_min_citations_is_the_shared_threshold() -> None:
    # A body with exactly MIN_CITED_FILES - 1 distinct files is rejected by default.
    body = _body_with("graph TD", _THREE_CITATIONS[: MIN_CITED_FILES - 1])
    assert validate_agent_body(body).accepted is False


# --------------------------------------------------------------------------- #
# Determinism, totality, purity                                               #
# --------------------------------------------------------------------------- #


def test_deterministic_for_equal_input() -> None:
    body = _body_with("graph TD", _THREE_CITATIONS)
    first = validate_agent_body(body)
    second = validate_agent_body(body)
    assert first == second


def test_never_raises_on_pathological_input() -> None:
    for body in (
        "",
        "```mermaid",  # unterminated fence
        "```mermaid\n```",  # empty fence (no content line)
        "no fences, no citations at all",
        "```mermaid\ngraph TD\n```\n`only:1` and `:notdigits`",
        ":1234 bare colon-number with no path",
        "```",
        "`file.py:` colon but no digits",
    ):
        result = validate_agent_body(body)
        assert isinstance(result, GateResult)
        assert isinstance(result.accepted, bool)


def test_gate_result_is_frozen() -> None:
    result = validate_agent_body(_body_with("graph TD", _THREE_CITATIONS))
    import dataclasses

    assert dataclasses.is_dataclass(result)
    try:
        result.accepted = False  # type: ignore[misc]
    except dataclasses.FrozenInstanceError:
        pass
    else:  # pragma: no cover - guard
        raise AssertionError("GateResult must be frozen")


# --------------------------------------------------------------------------- #
# Module surface                                                              #
# --------------------------------------------------------------------------- #


def test_module_all_lists_public_names() -> None:
    mod = importlib.import_module("docuharnessx.composition.structure_gate")
    assert set(mod.__all__) == {"GateResult", "validate_agent_body"}
    for name in mod.__all__:
        assert hasattr(mod, name)
