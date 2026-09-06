"""Reading order for the question site: a short path, then the rest.

Used by the home page and the MkDocs nav so the sidebar matches the story.
Deterministic and model-free: equal pages and identity yield equal order.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from docuharnessx.pages.model import Page

if TYPE_CHECKING:
    from docuharnessx.assembler.model import SiteIdentity

__all__ = [
    "first_sentence",
    "is_system_overview",
    "primary_component",
    "story_order",
    "story_spine",
]

_SPINE_KINDS = ("startup", "build", "tests", "public_surface")
_SPINE_KIND_SET = frozenset(_SPINE_KINDS)
_SPINE_CAP = 5


def _kind(page: Page) -> str:
    return page.id.split(":", 1)[0]


def _slug(page: Page) -> str:
    return page.id.split(":", 1)[1] if ":" in page.id else page.id


def _alnum(value: str) -> str:
    return "".join(ch for ch in value.lower() if ch.isalnum())


def first_sentence(text: str, limit: int = 220) -> str:
    """First sentence of ``text``, truncated for a home-page lede."""
    cleaned = " ".join(text.split())
    if not cleaned:
        return ""
    end = 0
    for index, char in enumerate(cleaned):
        if char not in ".!?":
            continue
        if index + 1 == len(cleaned) or cleaned[index + 1] == " ":
            end = index + 1
            break
    sentence = cleaned[:end] if end else cleaned
    if len(sentence) > limit:
        return sentence[: limit - 3].rstrip() + "..."
    return sentence


def primary_component(
    pages: Sequence[Page],
    identity: "SiteIdentity | None" = None,
) -> Page | None:
    """The page that answers 'what is this system?', or ``None``."""
    components = [page for page in pages if _kind(page) == "component"]
    if not components:
        return None
    keys: list[str] = []
    if identity is not None:
        repo = (identity.repo_name or "").rsplit("/", 1)[-1]
        if repo:
            keys.append(_alnum(repo))
        if identity.site_name:
            keys.append(_alnum(identity.site_name))
    for key in keys:
        if not key:
            continue
        for page in components:
            if _alnum(_slug(page)) == key:
                return page
            if any(_alnum(subject) == key for subject in page.subjects):
                return page
    ranked: list[tuple[int, str, Page]] = []
    norms = [(page, _alnum(_slug(page))) for page in components]
    for page, norm in norms:
        if not norm:
            continue
        covers = sum(
            1 for _, other in norms if other != norm and other.startswith(norm)
        )
        if covers:
            ranked.append((len(norm), page.id, page))
    if ranked:
        ranked.sort()
        return ranked[0][2]
    if len(components) == 1:
        return components[0]
    return None


def is_system_overview(
    page: Page,
    accepted: Sequence[Page],
    identity: "SiteIdentity | None" = None,
) -> bool:
    """True when ``page`` is the right place for a system-context picture."""
    primary = primary_component(accepted, identity)
    if primary is not None:
        return page.id == primary.id
    return _kind(page) == "startup"


def story_order(
    pages: Sequence[Page],
    identity: "SiteIdentity | None" = None,
) -> tuple[Page, ...]:
    """Pages in reading order: start, what it is, build, tests, API, then rest."""
    by_kind: dict[str, list[Page]] = {}
    for page in pages:
        by_kind.setdefault(_kind(page), []).append(page)
    for group in by_kind.values():
        group.sort(key=lambda page: page.id)

    seen: set[str] = set()
    ordered: list[Page] = []

    def add(page: Page | None) -> None:
        if page is None or page.id in seen:
            return
        seen.add(page.id)
        ordered.append(page)

    for page in by_kind.get("startup", ()):
        add(page)
    add(primary_component(pages, identity))
    for kind in ("build", "tests", "public_surface"):
        for page in by_kind.get(kind, ()):
            add(page)
    for page in sorted(pages, key=lambda item: item.id):
        add(page)
    return tuple(ordered)


def story_spine(
    pages: Sequence[Page],
    identity: "SiteIdentity | None" = None,
    *,
    cap: int = _SPINE_CAP,
) -> tuple[Page, ...]:
    """The short path shown first on home (at most ``cap`` questions)."""
    ordered = story_order(pages, identity)
    primary = primary_component(pages, identity)
    primary_id = None if primary is None else primary.id
    spine: list[Page] = []
    for page in ordered:
        if _kind(page) in _SPINE_KIND_SET or page.id == primary_id:
            spine.append(page)
        if len(spine) >= cap:
            break
    if not spine:
        return tuple(ordered[:cap])
    return tuple(spine)
