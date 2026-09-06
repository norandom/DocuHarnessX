"""Strip reader-facing methodology labels from published Markdown.

Living pages stay verbatim. Assemble applies this so published docs do not
print SCQA, Minto, COBESY, or andragogy (architect-narrative Req 5.3).
"""

from __future__ import annotations

import re

__all__ = ["suppress_methodology_labels"]

_LABELS = re.compile(r"(SCQA|Minto|COBESY|andragogy)-?", re.IGNORECASE)
_MULTI_SPACE = re.compile(r"[ \t]{2,}")
_EMPTY_IDENT = re.compile(r"`_+`")


def suppress_methodology_labels(text: str) -> str:
    """Return ``text`` with methodology names removed. Byte-stable."""
    if not text:
        return text
    cleaned = _LABELS.sub("", text)
    cleaned = _EMPTY_IDENT.sub("", cleaned)
    cleaned = _MULTI_SPACE.sub(" ", cleaned)
    return cleaned
