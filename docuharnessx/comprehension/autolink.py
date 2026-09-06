"""Fence-aware glossary autolink on assembled Markdown."""

from __future__ import annotations

import re

from docuharnessx.comprehension.glossary import Glossary, GlossaryTerm

__all__ = ["appearances_for_pages", "autolink_markdown", "relate_cooccurring"]

_FENCE = re.compile(
    r"(```[\s\S]*?```|`[^`]+`|\[[^\]]*\]\([^)]+\)|"
    r"<script[\s\S]*?</script>|<textarea[\s\S]*?</textarea>|<[^>]+>)"
)
_FRONTMATTER = re.compile(r"\A---\n.*?\n---\n?", re.DOTALL)


def autolink_markdown(text: str, glossary: Glossary) -> str:
    """Link whole-word term/alias hits to glossary.md#id.

    Skips YAML frontmatter, code fences, inline code, existing links, HTML
    tags, and ATX headings so MkDocs metadata and titles stay intact.
    """
    phrases = _phrases(glossary)
    if not phrases:
        return text
    match = _FRONTMATTER.match(text)
    if match:
        return match.group(0) + _autolink_body(text[match.end() :], phrases)
    return _autolink_body(text, phrases)


def appearances_for_pages(
    glossary: Glossary,
    pages: list[tuple[str, str, str]],
) -> dict[str, tuple[tuple[str, str], ...]]:
    """Map term id → ((page title, page href), ...) for whole-word hits in body."""
    phrases = _phrases(glossary)
    found: dict[str, list[tuple[str, str]]] = {term.id: [] for term in glossary.terms}
    for href, title, body in pages:
        blob = _FRONTMATTER.sub("", body)
        blob = re.sub(r"```[\s\S]*?```", " ", blob)
        lowered = blob.casefold()
        for name, term_id in phrases:
            if re.search(
                rf"(?<![A-Za-z0-9_-]){re.escape(name)}(?![A-Za-z0-9_-])",
                lowered,
                re.IGNORECASE,
            ):
                pair = (title, href)
                if pair not in found[term_id]:
                    found[term_id].append(pair)
    return {tid: tuple(hits) for tid, hits in found.items() if hits}


def relate_cooccurring(
    glossary: Glossary,
    appearances: dict[str, tuple[tuple[str, str], ...]],
) -> Glossary:
    """Fill ``related`` from terms that appear on the same page (cap 8)."""
    page_terms: dict[str, set[str]] = {}
    for tid, hits in appearances.items():
        for _title, href in hits:
            page_terms.setdefault(href, set()).add(tid)
    related: dict[str, list[str]] = {term.id: list(term.related) for term in glossary.terms}
    for group in page_terms.values():
        for tid in group:
            for other in sorted(group):
                if other == tid or other in related[tid]:
                    continue
                if len(related[tid]) >= 8:
                    break
                related[tid].append(other)
    terms: list[GlossaryTerm] = []
    for term in glossary.terms:
        terms.append(
            GlossaryTerm(
                id=term.id,
                label=term.label,
                aliases=term.aliases,
                definition=term.definition,
                related=tuple(related[term.id]),
                sources=term.sources,
            )
        )
    return Glossary(terms=tuple(terms))


def _phrases(glossary: Glossary) -> list[tuple[str, str]]:
    phrases: list[tuple[str, str]] = []
    for term in glossary.terms:
        for raw in (term.label, *term.aliases):
            name = raw.strip()
            if len(name) < 3:
                continue
            phrases.append((name, term.id))
    phrases.sort(key=lambda item: len(item[0]), reverse=True)
    return phrases


def _autolink_body(text: str, phrases: list[tuple[str, str]]) -> str:
    parts = _FENCE.split(text)
    out: list[str] = []
    for part in parts:
        if (
            part.startswith("```")
            or part.startswith("`")
            or part.startswith("<")
            or (part.startswith("[") and "](" in part)
        ):
            out.append(part)
            continue
        lines = part.splitlines(keepends=True)
        for line in lines:
            if line.lstrip().startswith("#"):
                out.append(line)
            else:
                out.append(_link_part(line, phrases))
    return "".join(out)


def _link_part(text: str, phrases: list[tuple[str, str]]) -> str:
    parts = _FENCE.split(text)
    rebuilt: list[str] = []
    for part in parts:
        if (
            part.startswith("`")
            or part.startswith("<")
            or (part.startswith("[") and "](" in part)
        ):
            rebuilt.append(part)
            continue
        chunk = part
        for name, term_id in phrases:
            pattern = re.compile(
                rf"(?<![A-Za-z0-9_-])({re.escape(name)})(?![A-Za-z0-9_-])",
                re.IGNORECASE,
            )

            def _sub(match: re.Match[str], tid: str = term_id) -> str:
                return f'<a class="dhx-term" href="glossary.md#{tid}">{match.group(1)}</a>'

            pieces = re.split(r"(\[[^\]]*\]\([^)]+\)|<a\b[^>]*>.*?</a>)", chunk, flags=re.I)
            inner: list[str] = []
            for piece in pieces:
                if piece.startswith("[") or piece.lower().startswith("<a "):
                    inner.append(piece)
                else:
                    inner.append(pattern.sub(_sub, piece))
            chunk = "".join(inner)
        rebuilt.append(chunk)
    return "".join(rebuilt)
