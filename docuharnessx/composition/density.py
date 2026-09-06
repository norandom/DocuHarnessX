"""Density trim for question-page summaries.

Fail-open: a summary that is too long is cut; a page is never omitted for
density. Substance stays on the body. Assemble applies the same trim so
older living pages still get a short depth-1 layer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace

from docuharnessx.composition.blueprint_question import DensityBudget
from docuharnessx.pages.model import Page

__all__ = [
    "CITATIONS_ONLY_NOTE",
    "DensityTrim",
    "trim_page",
    "trim_summary",
]

CITATIONS_ONLY_NOTE = "summary was only citations; body kept"

# Same grain as the substance-gate citation matcher, plus optional wraps.
_CITATION = re.compile(
    r"\(?`?(?:[^\s`():]+/)*[^\s`():]+\.[A-Za-z0-9]+:\d+`?\)?"
)
_EMPTY_PARENS = re.compile(r"\(\s*\)")
_SPACE_BEFORE_PUNCT = re.compile(r"\s+([,.;:])")
_CLOSING_QUOTE = frozenset("\"'”’)")


@dataclass(frozen=True)
class DensityTrim:
    """A page after density trim, plus an empty-after-trim note when needed."""

    page: Page
    note: str = ""


def trim_summary(page: Page, budget: DensityBudget | None = None) -> Page:
    """Return ``page`` with summary capped to the density budget."""
    return trim_page(page, budget).page


def trim_page(page: Page, budget: DensityBudget | None = None) -> DensityTrim:
    """Trim summary; never drop the body. Equal inputs yield an equal result."""
    caps = budget or DensityBudget()
    raw = page.summary or ""
    stripped = _strip_citations(raw)
    clipped = _cap(_first_sentences(stripped, caps.summary_sentences), caps.summary_chars)
    if clipped == raw:
        return DensityTrim(page=page)
    if not clipped:
        if not raw.strip():
            return DensityTrim(page=page)
        return DensityTrim(
            page=replace(page, summary=""),
            note=CITATIONS_ONLY_NOTE,
        )
    return DensityTrim(page=replace(page, summary=clipped))


def _strip_citations(text: str) -> str:
    cleaned = _CITATION.sub("", text)
    cleaned = _EMPTY_PARENS.sub("", cleaned)
    cleaned = _SPACE_BEFORE_PUNCT.sub(r"\1", cleaned)
    return " ".join(cleaned.split()).strip(" ,;:-")


def _is_sentence_end(text: str, index: int) -> bool:
    if text[index] not in ".!?":
        return False
    rest = text[index + 1 :]
    if not rest:
        return True
    offset = 0
    while offset < len(rest) and rest[offset] in _CLOSING_QUOTE:
        offset += 1
    if offset == len(rest):
        return True
    return rest[offset] == " "


def _first_sentences(text: str, limit: int) -> str:
    cleaned = " ".join(text.split())
    if not cleaned or limit < 1:
        return ""
    found: list[str] = []
    start = 0
    for index, char in enumerate(cleaned):
        if not _is_sentence_end(cleaned, index):
            continue
        piece = cleaned[start : index + 1].strip()
        if piece:
            found.append(piece)
        start = index + 1
        if len(found) >= limit:
            break
    if len(found) < limit:
        tail = cleaned[start:].strip()
        if tail:
            found.append(tail)
    return " ".join(found[:limit])


def _cap(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    cut = text[:limit].rstrip()
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return cut.rstrip(" ,;:-")
