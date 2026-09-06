"""The site home page (the docs-root landing page).

This module is the deterministic, model-free renderer for the site's landing page,
``docs/index.md`` (:data:`~docuharnessx.assembler.mkdocs_config.HOME_PAGE_PATH`). MkDocs serves
``index.md`` at the site's base path, so emitting it gives the generated site a real entry
point — without it the site root is a 404 and the reader has nowhere to start.

:func:`render_home_page` produces a short, reader-facing landing page from the resolved
per-target :class:`~docuharnessx.assembler.model.SiteIdentity` and the emitted role landing
pages: a heading and one-line description naming the *target* project (never DocuHarnessX), a
"choose your path" index linking to each role's section in the caller's (vocabulary) order,
and a pointer to the tags index. It names no authoring methodology (the COBESY scaffolding is
an internal authoring guide, not reader-facing content). Deterministic and byte-stable: equal
inputs yield equal output, no I/O, no model call.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from docuharnessx.assembler.depth import wrap_layer
from docuharnessx.assembler.mkdocs_config import HOME_PAGE_PATH, TAGS_INDEX_PATH
from docuharnessx.assembler.pages import page_filename
from docuharnessx.assembler.story import story_order, story_spine
from docuharnessx.comprehension.signals import ComprehensionSignals, CoverageCounts
from docuharnessx.pages.model import Page

if TYPE_CHECKING:  # consumed read-only; typing-only import.
    from docuharnessx.analysis.model import RepoAnalysis
    from docuharnessx.assembler.model import SiteIdentity

__all__ = ["HOME_PAGE_PATH", "render_home_page", "render_question_home"]


def render_home_page(
    identity: "SiteIdentity",
    role_pages: tuple[tuple[str, str], ...],
) -> str:
    """Render the ``docs/index.md`` landing page (design "Site writer").

    Args:
        identity: The resolved per-target :class:`~docuharnessx.assembler.model.SiteIdentity`.
            Its ``site_name``/``repo_name``/``repo_url`` name the *target* project; never
            DocuHarnessX's own identity (Req 3.8).
        role_pages: ``(label, docs_relative_path)`` for every emitted per-role landing page, in
            nav (vocabulary role) order — the same tuple the nav and role-switch affordance
            use, so the home index agrees with them. May be empty (a site with no role pages
            still gets a valid landing page).

    Returns:
        The Markdown body of the landing page, ending in a single ``\\n``. Deterministic and
        byte-stable for equal inputs.
    """
    repo = identity.repo_name or identity.site_name
    target = f"[`{repo}`]({identity.repo_url})" if identity.repo_url else f"`{repo}`"

    lines: list[str] = [
        f"# {identity.site_name}",
        "",
        f"Role-based documentation for {target}, organised by what you are here to do.",
        "",
        "## Start here",
        "",
    ]

    if role_pages:
        lines.append("Pick the path that matches your role:")
        lines.append("")
        for label, path in role_pages:
            lines.append(f"- [{label}]({path})")
    else:
        lines.append("_No documentation sections were generated for this run yet._")

    lines.append("")
    lines.append(f"You can also browse the whole corpus by tag in [Tags]({TAGS_INDEX_PATH}).")
    return "\n".join(lines) + "\n"


def _lede(identity: "SiteIdentity", pages: Sequence[Page]) -> str:
    """Short opening for the numbered path. Does not advertise the planner cap."""
    repo = identity.repo_name or identity.site_name
    target = f"[`{repo}`]({identity.repo_url})" if identity.repo_url else f"`{repo}`"
    if not pages:
        return f"Documentation for {target}."
    spine = story_spine(pages, identity)
    parts = [
        f"A short path through {target}, in the order you would actually "
        "learn the project."
    ]
    if len(pages) > len(spine):
        parts.append(
            "Read the numbered list first. Later questions cover individual modules."
        )
    else:
        parts.append("Read the numbered list in order.")
    return "\n\n".join(parts)


def _numbered_links(pages: Sequence[Page]) -> str:
    lines = ["## Read in this order", ""]
    for index, page in enumerate(pages, 1):
        lines.append(f"{index}. [{page.title}]({page_filename(page.id)})")
    return "\n".join(lines)


def _bullet_links(pages: Sequence[Page]) -> str:
    lines = ["## More questions", ""]
    for page in pages:
        lines.append(f"- [{page.title}]({page_filename(page.id)})")
    return "\n".join(lines)


def render_question_home(
    identity: "SiteIdentity",
    pages: Sequence[Page],
    *,
    analysis: "RepoAnalysis | None" = None,
    signals: ComprehensionSignals | None = None,
    counts: CoverageCounts | None = None,
) -> str:
    """Render the question-organised ``docs/index.md`` (Req 8.1, 8.2).

    Heading is the target ``site_name``. Depth 1 is a short reading path, not a
    system map. Titles are Markdown links; the page does not index reader roles.
    Ends in a single ``\\n``.
    """
    ordered = story_order(pages, identity)
    spine = story_spine(ordered, identity)
    spine_ids = {page.id for page in spine}
    rest = [page for page in ordered if page.id not in spine_ids]

    lines: list[str] = [
        f"# {identity.site_name}",
        "",
        wrap_layer(1, _lede(identity, ordered)).rstrip("\n"),
        "",
    ]
    if spine:
        lines.append(wrap_layer(1, _numbered_links(spine)).rstrip("\n"))
        lines.append("")
    if rest:
        lines.append(wrap_layer(1, _bullet_links(rest)).rstrip("\n"))
        lines.append("")

    from docuharnessx.comprehension.graphs import render_home_extras

    extras = render_home_extras(
        ordered, analysis, signals, counts, identity=identity
    )
    for depth, block in extras:
        lines.append(wrap_layer(max(depth, 2), block).rstrip("\n"))
        lines.append("")
    return "\n".join(lines) + "\n"
