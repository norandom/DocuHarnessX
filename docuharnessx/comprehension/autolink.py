"""Fence-aware glossary autolink on assembled Markdown."""

from __future__ import annotations

import re

from docuharnessx.comprehension.glossary import Glossary

__all__ = ["autolink_markdown"]

_FENCE = re.compile(r"(```[\s\S]*?```|`[^`]+`|\[[^\]]*\]\([^)]+\))")


def autolink_markdown(text: str, glossary: Glossary) -> str:
    """Link whole-word term/alias hits to glossary.md#id. Skip code."""
    phrases: list[tuple[str, str]] = []
    for term in glossary.terms:
        for raw in (term.label, *term.aliases):
            name = raw.strip()
            if len(name) < 3:
                continue
            phrases.append((name, term.id))
    phrases.sort(key=lambda item: len(item[0]), reverse=True)
    if not phrases:
        return text
    parts = _FENCE.split(text)
    out: list[str] = []
    for part in parts:
        if part.startswith("`") or (part.startswith("[") and "](" in part):
            out.append(part)
            continue
        out.append(_link_part(part, phrases))
    return "".join(out)


def _link_part(text: str, phrases: list[tuple[str, str]]) -> str:
    result = text
    for name, term_id in phrases:
        pattern = re.compile(
            rf"(?<![A-Za-z0-9_-])({re.escape(name)})(?![A-Za-z0-9_-])",
            re.IGNORECASE,
        )

        def _sub(match: re.Match[str], tid: str = term_id) -> str:
            return f"[{match.group(1)}](glossary.md#{tid})"

        result = pattern.sub(_sub, result)
    return result
