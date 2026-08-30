"""The deterministic substance gate for accepted page bodies.

This module owns the *SubstanceGate* boundary of ``explore-first-simplification``:
:func:`validate_page_body` decides whether a writer body is accepted as a page or
omitted (Req 5.2, 6.3, 7.1–7.5, 10.4). Unlike the mermaid-required structure gate,
acceptance is grounded in *substance*: real ``path:line`` citations, a real
identifier from the question, and the absence of retired outline slogans.

A body is accepted **iff** all of:

1. at least two distinct ``path:line`` citations whose paths exist as files
   under ``repo_path`` (Req 5.2, 7.1, 7.3);
2. at least one identifier from the question's subject or evidence basenames
   appears as a whole token (Req 7.2);
3. the body does not contain retired phrases (case-insensitive):
   ``fastest path for``, ``who this is for:``, ``run the smallest action``,
   ``verify you reached first success``, or ``locate {subject}`` as an empty
   imperative (Req 6.3, 10.4);
4. the body is not merely the question title restated — remaining prose is
   the title plus trivial glue such as ``See``, not merely because the
   subject token already occurs in the title (Req 7.5).

Mermaid fences are ignored for the decision: a diagram is neither required nor
disqualifying (Req 7.4). The gate is model-free. It never invents replacement
prose; ``accepted=False`` means omit.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from docuharnessx.planning.question_model import Question

__all__ = ["GateResult", "validate_page_body"]


#: Distinct existing ``path:line`` files required to accept (Req 7.1).
_MIN_EXISTING_CITED_FILES = 2

#: Retired template slogans; matched as case-insensitive substrings (Req 6.3, 10.4).
_RETIRED_PHRASES: tuple[str, ...] = (
    "fastest path for",
    "who this is for:",
    "run the smallest action",
    "verify you reached first success",
)

#: ``path:line`` citation: a path token with an extension, then ``:`` and digits.
#: Inspired by the structure gate; existence under ``repo_path`` is checked separately.
_CITATION_RE = re.compile(r"(?P<path>[^\s`:]+(?:/[^\s`:]+)*\.[^\s`:]+):\d+")

_MERMAID_OPEN_RE = re.compile(r"^[ \t]*`{3,}[ \t]*mermaid\b[^\n]*$", re.MULTILINE)
_FENCE_CLOSE_RE = re.compile(r"^[ \t]*`{3,}[ \t]*$")
_WORD_RE = re.compile(r"[A-Za-z0-9_]+")

#: Citation/title connectors; leftover prose beyond these is not a restatement.
_TRIVIAL_GLUE = frozenset(
    {
        "a",
        "an",
        "and",
        "also",
        "as",
        "at",
        "by",
        "for",
        "from",
        "in",
        "into",
        "of",
        "on",
        "or",
        "plus",
        "see",
        "the",
        "to",
        "via",
        "with",
    }
)


@dataclass(frozen=True)
class GateResult:
    """The deterministic outcome of validating one page body.

    :param accepted: ``True`` iff every substance condition holds.
    :param cited_files: distinct citation paths that exist under the repo.
    :param reason: a short explanation of the decision (never the body itself).
    """

    accepted: bool
    cited_files: int
    reason: str


def _basename(path: str) -> str:
    return path.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1].strip()


def _stem(name: str) -> str:
    base = _basename(name)
    if not base or "." not in base[1:]:
        return base
    return base.rsplit(".", 1)[0]


def _question_identifiers(question: Question) -> tuple[str, ...]:
    """Subject name plus evidence basenames and stems, de-duplicated."""
    names: list[str] = []
    seen: set[str] = set()

    def add(value: str) -> None:
        text = value.strip()
        if not text:
            return
        key = text.lower()
        if key in seen:
            return
        seen.add(key)
        names.append(text)

    add(question.subject_name)
    add(_basename(question.subject_name))
    add(_stem(question.subject_name))
    for path in question.evidence_paths:
        add(_basename(path))
        add(_stem(path))
    return tuple(names)


def _has_whole_token(text: str, token: str) -> bool:
    if not token:
        return False
    pattern = re.compile(
        r"(?<![A-Za-z0-9_])" + re.escape(token) + r"(?![A-Za-z0-9_])",
        re.IGNORECASE,
    )
    return pattern.search(text) is not None


def _words(text: str) -> list[str]:
    return [match.group(0).lower() for match in _WORD_RE.finditer(text or "")]


def _strip_mermaid_fences(body: str) -> str:
    """Drop fenced mermaid blocks so diagrams are ignored for the decision."""
    lines = body.split("\n")
    kept: list[str] = []
    index = 0
    n = len(lines)
    while index < n:
        if _MERMAID_OPEN_RE.match(lines[index]) is None:
            kept.append(lines[index])
            index += 1
            continue
        index += 1
        while index < n:
            closed = _FENCE_CLOSE_RE.match(lines[index]) is not None
            index += 1
            if closed:
                break
    return "\n".join(kept)


def _existing_cited_files(body: str, repo_path: str) -> tuple[str, ...]:
    """Distinct repo-relative paths cited as ``path:line`` that exist on disk."""
    if not repo_path:
        return ()
    repo = Path(repo_path)
    if not repo.is_dir():
        return ()
    try:
        root = repo.resolve()
    except OSError:
        return ()

    found: list[str] = []
    seen: set[str] = set()
    for match in _CITATION_RE.finditer(body):
        raw = match.group("path").replace("\\", "/").strip()
        rel = raw
        while rel.startswith("./"):
            rel = rel[2:]
        if not rel or rel.startswith("/"):
            continue
        candidate = root / rel
        try:
            resolved = candidate.resolve()
            ident = resolved.relative_to(root).as_posix()
        except (OSError, ValueError):
            continue
        if not resolved.is_file() or ident in seen:
            continue
        seen.add(ident)
        found.append(ident)
    return tuple(found)


def _has_retired_slogans(body: str, subject_name: str) -> bool:
    lowered = body.lower()
    if any(phrase in lowered for phrase in _RETIRED_PHRASES):
        return True
    names = {subject_name.strip().lower(), "subject"}
    names.add(_basename(subject_name).lower())
    names.add(_stem(subject_name).lower())
    names.discard("")
    if not names:
        return False
    alternatives = "|".join(
        re.escape(name) for name in sorted(names, key=len, reverse=True)
    )
    locate = re.compile(
        rf"^\s*(?:\d+[.)]\s*|[-*+]\s*)?locate\s+(?:the\s+)?(?:{alternatives})\s*[.]?\s*$",
        re.IGNORECASE | re.MULTILINE,
    )
    return locate.search(body) is not None


def _is_title_restatement(body: str, title: str) -> bool:
    """True when remaining prose is the question title plus trivial glue."""
    prose = _CITATION_RE.sub(" ", _strip_mermaid_fences(body))
    ignore = set(_words(title)) | _TRIVIAL_GLUE
    leftover = [word for word in _words(prose) if word not in ignore]
    return not leftover


def validate_page_body(
    body: str,
    *,
    repo_path: str,
    question: Question,
) -> GateResult:
    """Deterministically gate a page ``body`` on substance, not diagrams.

    Accepts **iff** the body cites at least two distinct files that exist under
    ``repo_path``, names at least one subject/evidence identifier as a whole
    token, contains no retired slogans, and is not a title-only restatement.
    Mermaid is ignored for the decision (Req 7.4).

    Returns a :class:`GateResult`. Equal inputs yield an equal result.
    """
    text = body if isinstance(body, str) else ""
    repo = repo_path if isinstance(repo_path, str) else ""
    decision_body = _strip_mermaid_fences(text)
    cited = _existing_cited_files(decision_body, repo)
    cited_files = len(cited)
    identifiers = _question_identifiers(question)
    has_identifier = any(
        _has_whole_token(decision_body, ident) for ident in identifiers
    )
    has_slogan = _has_retired_slogans(decision_body, question.subject_name)
    restatement = _is_title_restatement(decision_body, question.title)

    accepted = (
        cited_files >= _MIN_EXISTING_CITED_FILES
        and has_identifier
        and not has_slogan
        and not restatement
    )

    if accepted:
        reason = (
            f"accepted: {cited_files} distinct existing cited file(s) "
            f"(>= {_MIN_EXISTING_CITED_FILES})"
        )
    elif has_slogan:
        reason = "rejected: retired slogan"
    elif cited_files < _MIN_EXISTING_CITED_FILES:
        reason = (
            f"rejected: only {cited_files} distinct existing cited file(s) "
            f"(< {_MIN_EXISTING_CITED_FILES})"
        )
    elif not has_identifier:
        reason = "rejected: no subject or evidence identifier"
    else:
        reason = "rejected: title restatement"

    return GateResult(
        accepted=accepted,
        cited_files=cited_files,
        reason=reason,
    )
