"""The deterministic structure gate for agent bodies (agentic-codebase-writer task 2.2).

This module owns the *structure_gate* boundary of the Wave 2.5 ``agentic-codebase-writer``:
:func:`validate_agent_body` is the deterministic check that decides whether a body produced
by the per-segment HarnessX agent is accepted *verbatim* as the segment body, or whether the
caller renders the deterministic fallback instead (Req 4.4, 9.5; design "validate_agent_body",
lines 433-461).

The agentic writer asks the agent for a COBESY-structured body that is grounded in real
source: at least one Mermaid diagram and ``file:line`` citations to real files (Req 4.2,
4.3). Because the agent's prose is non-deterministic, the *orchestration* keeps the run
deterministic by gating the body with this pure structural check before
:func:`~docuharnessx.composition.wiring.wire_segment` carries it into a ``Segment``. A body is
accepted **iff** both structural conditions hold:

1. it contains at least one fenced ```` ```mermaid ```` block whose first content line names a
   supported diagram type — ``graph``, ``flowchart``, ``sequenceDiagram``, ``classDiagram``,
   ``erDiagram``, or ``stateDiagram`` (the deepwiki-open quality bar; Req 4.2); and
2. it contains at least :data:`~docuharnessx.composition.budgets.MIN_CITED_FILES` *distinct*
   ``file:line`` citations — a path token followed by ``:<digits>`` (Req 4.3, 4.4) — so the
   prose is grounded in more than a single file.

The gate is **pure and total**: it reads only the ``body`` string, performs no I/O, never
consults a model, never raises (every malformed input yields a rejecting
:class:`GateResult`), and is deterministic — an equal body always yields an equal result
(Req 9.5). It is the deterministic backbone the runner uses to accept a model body or fall
back, so the credential-free scripted run reaches the review accept path with a real diagram.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from docuharnessx.composition.budgets import MIN_CITED_FILES

__all__ = ["GateResult", "validate_agent_body"]


# --------------------------------------------------------------------------- #
# Supported Mermaid diagram types (deepwiki-open quality bar; Req 4.2)         #
# --------------------------------------------------------------------------- #

#: The Mermaid diagram keywords a fence's first content line may open with for the fence to
#: count as a valid diagram. Matched against the first *word* of the first non-blank content
#: line, case-sensitively (Mermaid keywords are case-sensitive), so ``graph TD``,
#: ``flowchart TD``, ``sequenceDiagram``, ``classDiagram``, ``erDiagram``, and
#: ``stateDiagram``/``stateDiagram-v2`` are all recognised while a ``piechart`` or a stray
#: ``python`` fence body is not.
_SUPPORTED_DIAGRAM_KEYWORDS: frozenset[str] = frozenset(
    {
        # Architecture/flow diagrams (the deepwiki bar) ...
        "graph",
        "flowchart",
        "sequenceDiagram",
        "classDiagram",
        "erDiagram",
        "stateDiagram",
        "stateDiagram-v2",
        # ... plus the other well-established Mermaid diagram types, so a valid diagram
        # of any supported kind counts rather than being rejected on type alone.
        "journey",
        "gantt",
        "pie",
        "mindmap",
        "gitGraph",
        "timeline",
        "requirementDiagram",
        "quadrantChart",
        "C4Context",
    }
)

#: Matches the opening of a fenced ``mermaid`` code block at the start of a line: three or
#: more backticks immediately followed by the ``mermaid`` info string (optionally with
#: trailing attributes), so a plain ```` ``` ```` fence or a ```` ```python ```` fence does
#: not open a mermaid block. Anchored with :data:`re.MULTILINE` so every line is a candidate.
_MERMAID_OPEN_RE = re.compile(r"^[ \t]*`{3,}[ \t]*mermaid\b[^\n]*$", re.MULTILINE)

#: Matches a fence terminator line (three or more backticks, nothing else of substance).
_FENCE_CLOSE_RE = re.compile(r"^[ \t]*`{3,}[ \t]*$")

#: Matches a ``path:line`` citation: a path token (no whitespace, no backticks, containing at
#: least one path-ish character) followed by ``:`` and one or more digits, with the line
#: number not itself glued to more digits via another colon. The leading ``path`` group is
#: kept so distinct *files* (not raw occurrences) can be counted (Req 4.4). A bare ``:1234``
#: with no path, or ``file.py:`` with no digits, does not match.
_CITATION_RE = re.compile(r"(?P<path>[^\s`:]+(?:/[^\s`:]+)*\.[^\s`:]+):\d+")


# --------------------------------------------------------------------------- #
# Result value object                                                         #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class GateResult:
    """The deterministic outcome of validating one agent body.

    :param accepted: ``True`` iff the body carries at least one valid Mermaid fence *and* at
        least the required number of distinct ``file:line`` citations.
    :param mermaid_blocks: the number of fenced ``mermaid`` blocks whose first content line
        names a supported diagram type.
    :param cited_files: the number of *distinct* file paths cited as ``path:line``.
    :param reason: a short, human-readable explanation of the decision, for the bounded
        journal/telemetry (it never carries the body itself).
    """

    accepted: bool
    mermaid_blocks: int
    cited_files: int
    reason: str


# --------------------------------------------------------------------------- #
# Internal scanners (pure helpers)                                            #
# --------------------------------------------------------------------------- #


def _opens_supported_diagram(content: list[str]) -> bool:
    """True when a mermaid fence's body declares a supported diagram type.

    Tolerates the optional preamble Mermaid permits *before* the diagram declaration, so a
    valid diagram is not rejected on formatting alone: leading blank lines, a ``---`` YAML
    frontmatter block (e.g. a ``title:``), ``%%`` comments, and ``%%{ init: ... }%%``
    directives are skipped; the first substantive line after them must open with a token in
    :data:`_SUPPORTED_DIAGRAM_KEYWORDS`. Pure and total.
    """
    i = 0
    n = len(content)
    while i < n and not content[i].strip():
        i += 1
    # Optional YAML frontmatter block: a leading ``---`` runs to the next ``---``.
    if i < n and content[i].strip() == "---":
        i += 1
        while i < n and content[i].strip() != "---":
            i += 1
        i += 1  # consume the closing ``---``
    # Skip blank lines, ``%%`` comments, and ``%%{ ... }%%`` init directives.
    while i < n:
        stripped = content[i].strip()
        if not stripped or stripped.startswith("%%"):
            i += 1
            continue
        return stripped.split()[0] in _SUPPORTED_DIAGRAM_KEYWORDS
    return False


def _count_valid_mermaid_blocks(body: str) -> int:
    """Count fenced ``mermaid`` blocks that declare a supported diagram type.

    Walks the body line by line. On a ```` ```mermaid ```` opener it scans forward to the
    matching closing fence and counts the block when :func:`_opens_supported_diagram` accepts
    its content (a supported diagram keyword after any valid frontmatter/comment/directive
    preamble). An unterminated opener (no closing fence before end-of-text) does not count, so
    a truncated body cannot smuggle a half-diagram past the gate. Pure and total.
    """
    lines = body.split("\n")
    count = 0
    index = 0
    n = len(lines)
    while index < n:
        if _MERMAID_OPEN_RE.match(lines[index]) is None:
            index += 1
            continue
        # Found a ```mermaid opener; collect its content up to the terminator.
        index += 1
        content: list[str] = []
        closed = False
        while index < n:
            line = lines[index]
            if _FENCE_CLOSE_RE.match(line) is not None:
                closed = True
                index += 1
                break
            content.append(line)
            index += 1
        if closed and _opens_supported_diagram(content):
            count += 1
    return count


def _count_distinct_cited_files(body: str) -> int:
    """Count the distinct file paths cited as ``path:line`` anywhere in the body.

    Distinct *files*, not raw citation occurrences: ``loader.py:10`` and ``loader.py:20`` are
    one cited file (Req 4.4). Pure and total over arbitrary text.
    """
    paths = {match.group("path") for match in _CITATION_RE.finditer(body)}
    return len(paths)


# --------------------------------------------------------------------------- #
# Public entry point                                                          #
# --------------------------------------------------------------------------- #


def validate_agent_body(body: str, *, min_citations: int = MIN_CITED_FILES) -> GateResult:
    """Deterministically gate an agent ``body`` for Mermaid + ``file:line`` citations.

    Accepts the body **iff** it contains at least one fenced ``mermaid`` block whose first
    content line names a supported diagram type *and* at least ``min_citations`` distinct
    ``file:line`` citations (Req 4.4). Returns a :class:`GateResult` carrying the decision,
    the two counts, and a short reason for the bounded journal.

    Pure, total, and deterministic: it reads only ``body``, performs no I/O, consults no
    model, and never raises — a malformed, empty, or non-string-shaped body simply yields a
    rejecting result (Req 9.5). Equal input always yields an equal result.
    """
    text = body if isinstance(body, str) else ""
    mermaid_blocks = _count_valid_mermaid_blocks(text)
    cited_files = _count_distinct_cited_files(text)

    has_mermaid = mermaid_blocks >= 1
    has_citations = cited_files >= min_citations
    accepted = has_mermaid and has_citations

    if accepted:
        reason = (
            f"accepted: {mermaid_blocks} mermaid block(s), "
            f"{cited_files} distinct cited file(s) (>= {min_citations})"
        )
    elif not has_mermaid and not has_citations:
        reason = (
            f"rejected: no valid mermaid diagram and only {cited_files} distinct cited "
            f"file(s) (< {min_citations})"
        )
    elif not has_mermaid:
        reason = "rejected: no valid mermaid diagram block"
    else:
        reason = (
            f"rejected: only {cited_files} distinct cited file(s) (< {min_citations})"
        )

    return GateResult(
        accepted=accepted,
        mermaid_blocks=mermaid_blocks,
        cited_files=cited_files,
        reason=reason,
    )
