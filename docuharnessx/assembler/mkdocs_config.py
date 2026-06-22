"""The ``mkdocs.yml`` builder (design "mkdocs.yml builder"; task 3.3).

This module is the deterministic, model-free ``mkdocs.yml`` builder of the Wave 3
``mkdocs-site-assembler`` core. From the resolved per-target
:class:`~docuharnessx.assembler.model.SiteIdentity`, the emitted per-role landing pages, and
the loaded project :class:`~docuharnessx.ontology.Vocabulary`, it emits the ``mkdocs.yml``
configuration string the writer writes under ``<out>/site/`` and the deploy stage builds
with ``mkdocs build`` (Req 3.3, 6.1, 6.2, 6.4):

* ``site_name`` from the identity;
* the per-target ``site_url`` (the GitHub project-Pages URL carrying the ``/<repo>/``
  base-path) and ``use_directory_urls: true`` so internal links and static assets resolve
  under the project's Pages subpath (Req 3.3);
* ``repo_url`` / ``edit_uri`` only when the identity carries them (an empty value is
  omitted, never emitted as an empty key, so a no-remote / non-GitHub fallback still builds
  cleanly — Req 3.5, 3.6);
* ``theme: {name: material, ...}`` — the Material theme with the content-tabs feature the
  role renderer's role-switch affordance relies on (Req 6.4);
* ``plugins: [search, {tags: {}}]`` — the Material ``tags`` plugin enabled; the plugin
  discovers the ``<!-- material/tags -->`` listing directive the writer places in the tags
  index page, so the namespaced ``role:``/``subject:``/``intent:`` tags produce a browsable
  index (Req 6.2). (The legacy ``tags_file`` option is deprecated in current
  ``mkdocs-material`` and aborts a ``--strict`` build, so it is intentionally not emitted.)
* a deterministic ``nav`` — one entry per emitted role landing page (in the caller's order,
  which the writer supplies in vocabulary role order) followed by the tags index (Req 6.1).

The builder is **pure**: it derives the configuration only from its three arguments,
performs no I/O, and emits byte-identical YAML for equal inputs (Req 8.2). It never injects
DocuHarnessX's own identity — every per-target value comes from the passed
:class:`SiteIdentity` (Req 3.8). The tags index *page content* (``tags.md``) is owned by the
writer (task 4.1); this builder only references it by :data:`TAGS_INDEX_PATH`.

Determinism note: the configuration is assembled as an ordered ``dict`` and serialized with
``yaml.safe_dump(..., sort_keys=False)`` so key order is preserved and the output is
byte-stable, mirroring the YAML emission already used in
:mod:`docuharnessx.assembler.pages` and :mod:`docuharnessx.ontology.serializer`.
"""

from __future__ import annotations

import yaml

from docuharnessx.assembler.model import SiteIdentity
from docuharnessx.ontology import Vocabulary

__all__ = ["build_mkdocs_yaml", "TAGS_INDEX_PATH"]

#: The docs-relative path of the tags index page (owned/emitted by the writer, task 4.1).
#: The writer places the Material ``<!-- material/tags -->`` listing directive in this page;
#: the ``tags`` plugin discovers it and renders the tag listing there, and the nav references
#: it, so the index resolves to a real rendered listing (Req 6.1, 6.2).
TAGS_INDEX_PATH: str = "tags.md"

#: The human-facing nav title for the tags index entry.
_TAGS_NAV_TITLE: str = "Tags"

#: The Material theme features. ``navigation.tabs`` surfaces the top-level nav as tabs and
#: ``content.tabs.link`` enables the linked content-tabs the role renderer can use for the
#: role-switching affordance (design "mkdocs.yml builder"; Req 6.3, 6.4).
_THEME_FEATURES: tuple[str, ...] = ("navigation.tabs", "content.tabs.link")


def _theme() -> dict:
    """Return the Material theme block (Req 6.4).

    Emitted as a mapping (not the bare ``"material"`` string) so the Material features the
    role-switch content-tabs rely on can be attached. Deterministic.
    """
    return {"name": "material", "features": list(_THEME_FEATURES)}


def _plugins() -> list:
    """Return the plugins list: ``search`` then the Material ``tags`` plugin (Req 6.2).

    The ``tags`` plugin is enabled bare (``{}``): it discovers the ``<!-- material/tags -->``
    listing directive the writer places in the tags index page (:data:`TAGS_INDEX_PATH`) and
    renders the tag listing there. The legacy ``tags_file`` option is deprecated in current
    ``mkdocs-material`` and aborts a ``--strict`` build, so it is intentionally not emitted.
    Order is fixed (search first) for byte-stability.
    """
    return ["search", {"tags": {}}]


def _nav(role_pages: tuple[tuple[str, str], ...]) -> list:
    """Return the deterministic nav: each role landing page then the tags index (Req 6.1).

    ``role_pages`` is ``(label, docs_relative_path)`` per emitted role landing page, in the
    caller's order (the writer supplies them in vocabulary role order). Each becomes a
    ``{label: path}`` nav entry, in that exact order; the tags index is appended last. The
    nav order is therefore a total, deterministic function of the caller's input.
    """
    nav: list = [{label: path} for (label, path) in role_pages]
    nav.append({_TAGS_NAV_TITLE: TAGS_INDEX_PATH})
    return nav


def build_mkdocs_yaml(
    identity: SiteIdentity,
    role_pages: tuple[tuple[str, str], ...],
    vocab: Vocabulary,
) -> str:
    """Build the ``mkdocs.yml`` string for the assembled site (Req 3.3, 6.1, 6.2, 6.4).

    Args:
        identity: The resolved per-target :class:`SiteIdentity`. Supplies ``site_name``, the
            per-target ``site_url`` (with the ``/<repo>/`` base-path), and the optional
            ``repo_url``/``edit_uri``. Never DocuHarnessX's own identity (Req 3.8).
        role_pages: ``(label, docs_relative_path)`` for every emitted per-role landing page,
            in the order they should appear in the nav (the writer passes vocabulary role
            order). May be empty (a site with no role pages still gets a valid tags-index
            nav).
        vocab: The loaded :class:`~docuharnessx.ontology.vocabulary.Vocabulary`. Accepted for
            symmetry with the other renderers and future config-derived nav; the role order
            is carried by ``role_pages`` (already vocabulary-ordered by the writer), so no
            vocabulary field is hardcoded here.

    Returns:
        The ``mkdocs.yml`` content as a single YAML string ending in exactly one trailing
        newline. Byte-stable for equal inputs (Req 8.2).

    The emitted configuration sets the Material theme (Req 6.4), the ``tags`` plugin
    (enabled bare; it discovers the listing directive in the tags index page — Req 6.2), the
    per-target ``site_url`` + ``use_directory_urls`` so
    links/assets resolve under the project base-path (Req 3.3), ``repo_url``/``edit_uri``
    only when present (omitted on a no-remote/non-GitHub fallback so the build stays clean —
    Req 3.5, 3.6), and a deterministic nav over the role pages plus the tags index (Req 6.1).
    """
    # Ordered configuration mapping; key order is preserved by sort_keys=False below.
    config: dict = {"site_name": identity.site_name}

    # Per-target site_url only when present (a GitHub project-Pages site). An empty site_url
    # would break MkDocs' base-path resolution, so it is omitted on the root-base-path
    # fallbacks (no remote / non-GitHub) rather than emitted empty (Req 3.3, 3.5, 3.6).
    if identity.site_url:
        config["site_url"] = identity.site_url

    # Repo button + edit link only when the identity carries them (Req 3.3); empty values
    # (no-remote / non-GitHub-without-edit) are omitted so no broken affordance is rendered.
    if identity.repo_url:
        config["repo_url"] = identity.repo_url
    if identity.edit_uri:
        config["edit_uri"] = identity.edit_uri

    # Directory-URL handling so internal links and static assets resolve under the project's
    # /<repo>/ Pages subpath (Req 3.3). Always set, deterministically.
    config["use_directory_urls"] = True

    config["theme"] = _theme()
    config["plugins"] = _plugins()
    config["nav"] = _nav(role_pages)

    body = yaml.safe_dump(
        config,
        default_flow_style=False,
        sort_keys=False,
        allow_unicode=True,
    )
    if not body.endswith("\n"):
        body += "\n"
    return body
