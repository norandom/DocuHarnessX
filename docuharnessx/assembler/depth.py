"""Wrap assembled Markdown in engineering-depth layers (1 adopter … 7 internals)."""

from __future__ import annotations

__all__ = ["wrap_layer"]


def wrap_layer(min_depth: int, markdown: str) -> str:
    """Return a ``dhx-layer`` div, or empty string when ``markdown`` is blank."""
    body = markdown.strip("\n")
    if not body.strip():
        return ""
    return (
        f'<div class="dhx-layer" data-min="{min_depth}" markdown="1">\n\n'
        f"{body}\n\n"
        "</div>\n"
    )
