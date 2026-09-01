"""Living page store protocol and filesystem adapter (task 1.3).

This is the **LivingPageStore** boundary: accepted :class:`Page` values persist
under ``<project>/.docuharnessx/pages/`` as Markdown with question-page
frontmatter. The retired ``<out>/segments`` tree is not consulted.

Operations are credential-free and model-free: ``list``, ``get``, ``has``,
``put``. ``get`` of a missing id returns ``None`` rather than raising. Filenames
reuse :func:`docuharnessx.assembler.pages.page_filename`. Serialize/parse live
here so a stored file round-trips the :class:`Page` value (including
``cited_files``) rather than assembled site markdown.
"""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Protocol, runtime_checkable

import yaml

from docuharnessx.assembler.pages import page_filename
from docuharnessx.pages.model import Page

__all__ = [
    "PAGES_RELPATH",
    "FilesystemLivingPageStore",
    "LivingPageStore",
]

#: Canonical living-page directory, relative to a project dir (Req 5.1).
PAGES_RELPATH = os.path.join(".docuharnessx", "pages")

_FENCE = "---"


@runtime_checkable
class LivingPageStore(Protocol):
    """Port for the project's living page store (design LivingPageStore)."""

    def list(self) -> tuple[Page, ...]:
        """Return stored pages in deterministic (filename-sorted) order."""
        ...

    def get(self, page_id: str) -> Page | None:
        """Return the page for ``page_id``, or ``None`` when it is not stored."""
        ...

    def has(self, page_id: str) -> bool:
        """Return whether ``page_id`` is stored."""
        ...

    def put(self, page: Page) -> None:
        """Persist ``page``, replacing any existing page with the same id."""
        ...


class FilesystemLivingPageStore:
    """Filesystem :class:`LivingPageStore` rooted at ``<project>/.docuharnessx/pages/``.

    One Markdown file per page, named by :func:`page_filename`. Missing ids
    yield ``None`` / ``False``; a missing pages directory is an empty store.
    """

    def __init__(self, project_dir: str | Path) -> None:
        self._root = Path(project_dir) / PAGES_RELPATH

    def list(self) -> tuple[Page, ...]:
        """Return stored pages, ordered by filename for determinism."""
        if not self._root.is_dir():
            return ()
        pages: list[Page] = []
        for path in sorted(self._root.glob("*.md")):
            if path.is_file():
                pages.append(_parse_page(path.read_text(encoding="utf-8")))
        return tuple(pages)

    def get(self, page_id: str) -> Page | None:
        """Return the stored page, or ``None`` if ``page_id`` is missing."""
        path = self._path_for(page_id)
        if not path.is_file():
            return None
        return _parse_page(path.read_text(encoding="utf-8"))

    def has(self, page_id: str) -> bool:
        return self._path_for(page_id).is_file()

    def put(self, page: Page) -> None:
        self._root.mkdir(parents=True, exist_ok=True)
        self._path_for(page.id).write_text(_serialize_page(page), encoding="utf-8")
        from docuharnessx.adoption import mark_stale

        mark_stale(str(self._root.parent.parent))

    def _path_for(self, page_id: str) -> Path:
        return self._root / page_filename(page_id)


def _str_tuple(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        return tuple(str(item) for item in value)
    raise ValueError(f"expected a list of strings, got {value!r}")


def _find_closing_fence(text: str) -> tuple[str, str] | None:
    """Return ``(block, body)`` split at the first line equal to ``---``."""
    lines = text.split("\n")
    for index, line in enumerate(lines):
        if line.strip() == _FENCE:
            block = "\n".join(lines[:index])
            body = "\n".join(lines[index + 1 :])
            return block, body
    return None


def _serialize_page(page: Page) -> str:
    payload = {
        "id": page.id,
        "title": page.title,
        "subjects": list(page.subjects),
        "summary": page.summary,
        "related": list(page.related),
        "cited_files": list(page.cited_files),
    }
    front = yaml.safe_dump(
        payload,
        default_flow_style=False,
        sort_keys=False,
        allow_unicode=True,
    )
    return f"{_FENCE}\n{front}{_FENCE}\n{page.body}"


def _parse_page(text: str) -> Page:
    if not text.startswith(_FENCE):
        raise ValueError("missing leading '---' front-matter fence")
    after_open = text[len(_FENCE) :]
    if after_open[:1] not in ("\n", ""):
        raise ValueError("malformed opening '---' front-matter fence")
    after_open = after_open[1:] if after_open[:1] == "\n" else after_open
    closing = _find_closing_fence(after_open)
    if closing is None:
        raise ValueError("missing closing '---' front-matter fence")
    block, body = closing
    try:
        data = yaml.safe_load(block)
    except yaml.YAMLError as exc:
        raise ValueError(f"unparseable YAML: {exc}") from exc
    if not isinstance(data, Mapping):
        raise ValueError("front-matter block is not a YAML mapping")
    return Page(
        id=str(data["id"]),
        title=str(data.get("title", "")),
        summary=str(data.get("summary", "")),
        body=body,
        subjects=_str_tuple(data.get("subjects")),
        related=_str_tuple(data.get("related")),
        cited_files=_str_tuple(data.get("cited_files")),
    )
