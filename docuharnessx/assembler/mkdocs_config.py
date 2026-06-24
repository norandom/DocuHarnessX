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
  which the writer supplies in vocabulary role order) followed by the tags index (Req 6.1);
* a minimal, idempotent ``markdown_extensions`` block enabling the Material
  ``pymdownx.superfences`` custom fence for ``mermaid`` so the agentic writer's emitted
  diagrams render (Req 10.1, 10.2). The fence ``format`` is a Python function reference, so
  the configuration is serialized with :class:`_MkDocsYamlDumper` (a ``SafeDumper`` that
  emits the ``!!python/name:`` tag MkDocs' full loader recognizes) rather than plain
  ``yaml.safe_dump``; the dumper behaves identically to ``SafeDumper`` for every other value,
  so all previously emitted keys stay byte-stable.

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

import types

import yaml
from pymdownx import superfences

from docuharnessx.assembler.model import SiteIdentity
from docuharnessx.assembler.theme import EXTRA_CSS_PATH
from docuharnessx.ontology import Vocabulary

__all__ = ["build_mkdocs_yaml", "TAGS_INDEX_PATH"]

#: The docs-relative path of the tags index page (owned/emitted by the writer, task 4.1).
#: The writer places the Material ``<!-- material/tags -->`` listing directive in this page;
#: the ``tags`` plugin discovers it and renders the tag listing there, and the nav references
#: it, so the index resolves to a real rendered listing (Req 6.1, 6.2).
TAGS_INDEX_PATH: str = "tags.md"

#: The human-facing nav title for the tags index entry.
_TAGS_NAV_TITLE: str = "Tags"

#: The docs-relative path of the site landing page (emitted by the writer). At the docs root
#: so MkDocs serves it as the site home — ``index.md`` renders at the site's base path, giving
#: the site a real entry point instead of a 404 (Req 6.1).
HOME_PAGE_PATH: str = "index.md"

#: The human-facing nav title for the home entry (first in the nav).
HOME_NAV_TITLE: str = "Home"

#: The Material theme features. Tuned for a deepwiki-open-like experience: a left **sidebar
#: tree** (rather than top tabs) with section index pages and everything expanded, instant
#: SPA-style loading, a "back to top" button, a followed table of contents, and code-copy
#: buttons. ``content.tabs.link`` is kept for the role renderer's role-switch content-tabs
#: (Req 6.3, 6.4); ``navigation.indexes`` makes each role landing page its section's index.
_THEME_FEATURES: tuple[str, ...] = (
    "navigation.instant",
    "navigation.tracking",
    "navigation.indexes",
    "navigation.expand",
    "navigation.top",
    "navigation.footer",
    "toc.follow",
    "content.code.copy",
    "content.tabs.link",
    "search.suggest",
    "search.highlight",
)

#: The colour-scheme palette: a light/dark toggle. The concrete deepwiki-open colours are
#: applied per scheme by the extra stylesheet (:data:`docuharnessx.assembler.theme.EXTRA_CSS_PATH`)
#: overriding Material's CSS custom properties; here we only wire the two schemes + the toggle.
_PALETTE: tuple[dict, ...] = (
    {
        "scheme": "default",
        "toggle": {
            "icon": "material/weather-night",
            "name": "Switch to dark mode",
        },
    },
    {
        "scheme": "slate",
        "toggle": {
            "icon": "material/weather-sunny",
            "name": "Switch to light mode",
        },
    },
)

#: The typeface, matching deepwiki-open's Noto Sans JP body font (a clean monospace for code).
#: Material loads these from Google Fonts automatically.
_FONT: dict = {"text": "Noto Sans JP", "code": "Roboto Mono"}


class _MkDocsYamlDumper(yaml.SafeDumper):
    """A ``SafeDumper`` that additionally emits Python-object references as ``!!python/name:``.

    The Mermaid custom fence's ``format`` value is a Python function reference
    (:func:`pymdownx.superfences.fence_code_format`), which MkDocs' own (full) YAML loader
    constructs back into the function object. PyYAML's plain ``safe_dump`` cannot emit such a
    tag, so this dumper adds a single representer for the function type that emits the
    ``!!python/name:<module>.<qualname>`` tag — exactly the form the full loader recognizes
    (Req 10.1). For every non-function value the dumper behaves identically to ``SafeDumper``,
    so all previously emitted keys stay byte-stable (Req 10.2).
    """


def _represent_python_name(dumper: yaml.Dumper, data: types.FunctionType) -> yaml.Node:
    """Represent a function as the ``!!python/name:<module>.<qualname>`` YAML tag.

    Mirrors PyYAML's full ``Dumper`` representation of a Python name reference (an empty
    scalar carrying the ``python/name`` tag), so MkDocs' full loader resolves it back to the
    function object rather than treating it as a quoted string.
    """
    name = f"{data.__module__}.{data.__qualname__}"
    return dumper.represent_scalar("tag:yaml.org,2002:python/name:" + name, "")


_MkDocsYamlDumper.add_representer(types.FunctionType, _represent_python_name)


def _markdown_extensions() -> list:
    """Return the ``markdown_extensions`` block enabling the Mermaid custom fence (Req 10.1).

    A single, fixed ``pymdownx.superfences`` entry registering a custom fence named
    ``mermaid`` (class ``mermaid``) whose ``format`` is
    :func:`pymdownx.superfences.fence_code_format` — emitted as the ``!!python/name:`` tag by
    :class:`_MkDocsYamlDumper`. This is the minimal, idempotent addition needed for Material
    to render fenced ```` ```mermaid ```` blocks as diagrams; it changes no other behavior
    (Req 10.2). Order and content are fixed for byte-stability.
    """
    return [
        {
            "pymdownx.superfences": {
                "custom_fences": [
                    {
                        "name": "mermaid",
                        "class": "mermaid",
                        "format": superfences.fence_code_format,
                    }
                ]
            }
        }
    ]


def _theme() -> dict:
    """Return the Material theme block (Req 6.4).

    Emitted as a mapping (not the bare ``"material"`` string) so the deepwiki-inspired
    features, the light/dark palette toggle, and the Noto Sans JP font can be attached. The
    concrete colours are applied by the extra stylesheet; this only wires the schemes.
    Deterministic.
    """
    return {
        "name": "material",
        "features": list(_THEME_FEATURES),
        "palette": [dict(entry) for entry in _PALETTE],
        "font": dict(_FONT),
    }


def _plugins() -> list:
    """Return the plugins list: ``search`` then the Material ``tags`` plugin (Req 6.2).

    The ``tags`` plugin is enabled bare (``{}``): it discovers the ``<!-- material/tags -->``
    listing directive the writer places in the tags index page (:data:`TAGS_INDEX_PATH`) and
    renders the tag listing there. The legacy ``tags_file`` option is deprecated in current
    ``mkdocs-material`` and aborts a ``--strict`` build, so it is intentionally not emitted.
    Order is fixed (search first) for byte-stability.
    """
    return ["search", {"tags": {}}]


def _nav(
    role_pages: tuple[tuple[str, str], ...],
    segments_by_role: "dict[str, tuple[tuple[str, str], ...]] | None" = None,
) -> list:
    """Return the deterministic nav: home, each role section (+ its segment pages), then tags.

    ``role_pages`` is ``(label, docs_relative_path)`` per emitted role landing page, in the
    caller's order (vocabulary role order). ``segments_by_role`` optionally maps a role's
    landing path to its ``(segment_title, segment_docs_path)`` entries (the writer assigns
    each accepted segment to one role); when present the role becomes a **section** whose
    index is the landing page (``navigation.indexes``) followed by its segment pages — so the
    left sidebar is a full wiki-style page tree. With no mapping each role is a flat link
    (back-compatible). The home page is first and the tags index last; the order is a total,
    deterministic function of the caller's input.
    """
    mapping = segments_by_role or {}
    nav: list = [{HOME_NAV_TITLE: HOME_PAGE_PATH}]
    for label, path in role_pages:
        children = mapping.get(path)
        if children:
            # navigation.indexes: a list whose first item (the landing path, bare) is the
            # section index, followed by one {title: path} entry per assigned segment.
            section: list = [path]
            section.extend({title: seg_path} for (title, seg_path) in children)
            nav.append({label: section})
        else:
            nav.append({label: path})
    nav.append({_TAGS_NAV_TITLE: TAGS_INDEX_PATH})
    return nav


def build_mkdocs_yaml(
    identity: SiteIdentity,
    role_pages: tuple[tuple[str, str], ...],
    vocab: Vocabulary,
    segments_by_role: "dict[str, tuple[tuple[str, str], ...]] | None" = None,
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
    # The deepwiki-inspired skin: a single extra stylesheet overriding Material's CSS custom
    # properties (the writer emits it at the same docs-relative path).
    config["extra_css"] = [EXTRA_CSS_PATH]
    config["plugins"] = _plugins()
    config["nav"] = _nav(role_pages, segments_by_role)

    # Mermaid rendering: a minimal, idempotent pymdownx.superfences custom fence so emitted
    # fenced `mermaid` blocks render as diagrams in the Material site (Req 10.1, 10.2). The
    # fence `format` is a Python function reference emitted via _MkDocsYamlDumper as the
    # !!python/name: tag MkDocs' full loader recognizes; every other key is unchanged.
    config["markdown_extensions"] = _markdown_extensions()

    body = yaml.dump(
        config,
        Dumper=_MkDocsYamlDumper,
        default_flow_style=False,
        sort_keys=False,
        allow_unicode=True,
    )
    if not body.endswith("\n"):
        body += "\n"
    return body
