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

from typing import TYPE_CHECKING

from docuharnessx.assembler.mkdocs_config import HOME_PAGE_PATH, TAGS_INDEX_PATH

if TYPE_CHECKING:  # consumed read-only; typing-only import.
    from docuharnessx.assembler.model import SiteIdentity

__all__ = ["HOME_PAGE_PATH", "render_home_page"]


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
