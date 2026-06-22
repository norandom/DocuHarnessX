"""The per-role landing-page renderer (the ``roles`` component of the assembler core).

This module is the **Role landing page renderer** boundary (design "Role landing page
renderer") of the Wave 3 ``mkdocs-site-assembler`` (task 3.2). For one role term, an
accepted-segment store, the loaded :class:`~docuharnessx.ontology.vocabulary.Vocabulary`,
and the list of all emitted role pages, it renders the role's ``docs/<role>/index.md``
landing page — a deterministic, model-free, network-free pure transform.

A landing page has three parts:

* a **COBESY SCQA opener** (Situation / Complication / Question / Answer) framed entirely
  from the role's vocabulary ``label`` and ``description`` — never a hardcoded role name
  (Req 5.3, 5.6). The Answer hands the reader to the agenda below;
* the **guided agenda**: the role's segment view derived through the ontology
  :func:`~docuharnessx.ontology.views.build_role_view` (already intent-ordered by
  ``vocab.intent_order()`` with an id tie-break), rendered as ordered Markdown links to the
  per-segment pages — no segment body is duplicated onto the landing page (Req 5.2, 5.4);
* a **role-switching affordance** (a Material admonition) listing the *other* available
  role landing pages, so a reader can move between role views (Req 6.3).

Determinism (Req 8.2): the agenda order comes only from ``build_role_view`` (a total,
deterministic order), and the role-switch list preserves the caller's ``all_role_pages``
order, so equal inputs always yield byte-identical output. The renderer is a *consumer* of
the ontology APIs and owns no storage and performs no I/O; segments are read-only.

Boundary note (design "File Structure Plan"): the agenda links to the per-segment pages by
reusing the per-segment page renderer's own filename authority,
:func:`docuharnessx.assembler.pages.page_filename` (task 3.1) — so the agenda links resolve
to exactly the page files that renderer emits, with no parallel slug rule to drift. This
module owns only the *role-directory* path rule (``<role>/index.md``); the segment filename
rule stays solely in ``pages.py``.
"""

from __future__ import annotations

import re

from docuharnessx.assembler.pages import page_filename
from docuharnessx.ontology import (
    AxisTerm,
    SegmentStore,
    Vocabulary,
    build_role_view,
)

__all__ = [
    "render_role_landing_page",
    "role_page_path",
    "role_dir_name",
]


# --------------------------------------------------------------------------- #
# Filesystem-safe role-directory slug (deterministic)                          #
# --------------------------------------------------------------------------- #

#: Characters allowed verbatim in a role-directory slug; everything else collapses to a
#: single hyphen so an arbitrary vocabulary role id maps to one safe path segment.
_UNSAFE = re.compile(r"[^a-z0-9._-]+")
_DASHES = re.compile(r"-{2,}")


def _slug(value: str) -> str:
    """Map an arbitrary role id to one deterministic, filesystem-safe path segment.

    Lower-cases, replaces any run of unsafe characters (including path separators) with a
    single hyphen, strips a leading/trailing hyphen or dot, and collapses repeated hyphens.
    The result never contains ``/``, ``\\``, ``.``, or ``..`` as a whole segment, so it can
    never escape the docs tree. Deterministic and idempotent for equal inputs. Falls back
    to ``"untitled"`` for a role id that slugifies to empty.
    """
    text = _UNSAFE.sub("-", value.strip().casefold())
    text = _DASHES.sub("-", text).strip("-.")
    return text or "untitled"


def role_dir_name(role_id: str) -> str:
    """Return the deterministic, filesystem-safe directory name for a role landing page."""
    return _slug(role_id)


def role_page_path(role_id: str) -> str:
    """Return the role landing page's docs-relative path: ``<role>/index.md`` (design)."""
    return f"{role_dir_name(role_id)}/index.md"


# --------------------------------------------------------------------------- #
# Role landing page renderer                                                   #
# --------------------------------------------------------------------------- #


def render_role_landing_page(
    role: AxisTerm,
    accepted_store: SegmentStore,
    vocab: Vocabulary,
    all_role_pages: tuple[tuple[str, str], ...],
) -> tuple[str, str]:
    """Render one role's ``docs/<role>/index.md`` landing page (Req 5.2-5.4, 5.6, 6.3).

    Args:
        role: The role :class:`~docuharnessx.ontology.model.AxisTerm` from the loaded
            vocabulary; its ``label`` and ``description`` frame the SCQA opener (never a
            hardcoded name). Read-only.
        accepted_store: A :class:`~docuharnessx.ontology.store.SegmentStore` populated with
            the accepted segments. The role view is derived from it via
            :func:`~docuharnessx.ontology.views.build_role_view`. Read-only.
        vocab: The loaded :class:`~docuharnessx.ontology.vocabulary.Vocabulary`. Supplies
            the intent ordering the agenda follows. Read-only.
        all_role_pages: ``(label, docs_relative_path)`` for every emitted role landing page
            (including this role's own). The role-switch affordance lists every *other*
            entry, preserving this order. The current role's own entry is excluded.

    Returns:
        ``(relative_docs_path, page_markdown)`` where ``relative_docs_path`` is
        ``<role>/index.md`` and ``page_markdown`` is the byte-stable landing-page Markdown.

    The agenda is exactly the intent-ordered ``build_role_view`` result rendered as ordered
    links to the per-segment pages (``../<segment>.md`` — one directory up from
    ``<role>/index.md``), with each segment's summary as link context; no segment body is
    duplicated. Deterministic: equal inputs yield equal output. Never mutates a segment.
    """
    rel_path = role_page_path(role.id)
    view = build_role_view(accepted_store, role.id, vocab)

    sections: list[str] = []
    sections.append(_render_opener(role))
    sections.append(_render_agenda(view))
    switch = _render_role_switch(role, all_role_pages)
    if switch is not None:
        sections.append(switch)

    # One trailing newline; sections joined by a blank line. Byte-stable.
    content = "\n\n".join(sections).rstrip("\n") + "\n"
    return rel_path, content


# --------------------------------------------------------------------------- #
# COBESY SCQA opener (framed from the vocabulary label/description only)        #
# --------------------------------------------------------------------------- #


def _render_opener(role: AxisTerm) -> str:
    """Render the COBESY SCQA opener from the role's vocabulary label + description.

    The opener leads with the role's display ``label`` as the page H1 and frames the four
    SCQA beats — Situation, Complication, Question, Answer — around the role's
    ``description`` (Req 5.3). Nothing here is hardcoded to a particular role: a project that
    renames or re-describes a role changes this opener with no code change (Req 5.6). The
    Answer beat hands the reader to the agenda that follows.
    """
    label = role.label
    description = role.description.strip()
    # The role's own framing sentence; falls back to the label when no description is set,
    # so the opener stays well-formed for a description-less custom role.
    framing = description if description else f"the {label} role"

    lines = [
        f"# {label}",
        "",
        f"**Situation.** You are reading as a **{label}** — {framing}",
        "",
        (
            "**Complication.** The project's documentation is one shared corpus written "
            f"for many roles at once, so not all of it is framed for a {label}."
        ),
        "",
        (
            f"**Question.** As a {label}, where do you start, and in what order should you "
            "work through the material to reach first success on the shortest path?"
        ),
        "",
        (
            "**Answer.** Follow the guided agenda below. It is ordered for this role, so "
            "working through it top to bottom takes you from first step to outcome without "
            "reading the whole corpus."
        ),
    ]
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Intent-ordered guided agenda (links only — no body duplication)              #
# --------------------------------------------------------------------------- #


def _render_agenda(view: tuple) -> str:
    """Render the role view as an ordered, intent-ordered agenda of links (Req 5.2, 5.4).

    ``view`` is the already-intent-ordered tuple from
    :func:`~docuharnessx.ontology.views.build_role_view`. Each entry becomes a numbered
    Markdown list item linking to the segment's per-segment page (``../<segment>.md``),
    annotated with the segment's summary when present. The segment body is never duplicated
    here — the link carries the reader to the full page (Req 5.4). An empty view (no
    accepted segment for the role) renders an explicit "no content yet" line rather than an
    empty list; in practice the writer only renders a landing page for a non-empty role
    (Req 5.1, 5.5), but this keeps the renderer total.
    """
    lines = ["## Your guided agenda", ""]
    if not view:
        lines.append("_No content is available for this role yet._")
        return "\n".join(lines)

    for position, segment in enumerate(view, start=1):
        target = page_filename(segment.id)
        item = f"{position}. [{segment.title}](../{target})"
        summary = segment.summary.strip()
        if summary:
            item = f"{item} — {summary}"
        lines.append(item)
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Role-switching affordance (Material admonition listing the other roles)      #
# --------------------------------------------------------------------------- #


def _render_role_switch(
    role: AxisTerm, all_role_pages: tuple[tuple[str, str], ...]
) -> str | None:
    """Render the role-switch affordance listing the *other* role landing pages (Req 6.3).

    Uses a Material ``!!! info`` admonition holding a bullet list of links to every emitted
    role landing page except this role's own, preserving the caller's ``all_role_pages``
    order. Links are relative to ``<role>/index.md`` — ``../<other-role>/index.md`` reaches
    a sibling role directory. Returns ``None`` when there is no other role to switch to (a
    single-role site), so the affordance is omitted rather than rendered empty.
    """
    own_path = role_page_path(role.id)
    others = [
        (label, path)
        for (label, path) in all_role_pages
        if path != own_path
    ]
    if not others:
        return None

    lines = ['!!! info "Reading in a different role?"', ""]
    lines.append("    This corpus is organized by reader role. Switch to another view:")
    lines.append("")
    for label, path in others:
        lines.append(f"    - [{label}](../{path})")
    return "\n".join(lines)
