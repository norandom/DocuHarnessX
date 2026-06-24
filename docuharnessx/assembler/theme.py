"""The site theme stylesheet — a deepwiki-open-inspired skin for Material for MkDocs.

The assembled site is **Material for MkDocs**; this module supplies the one extra stylesheet
(:data:`EXTRA_CSS_PATH`, referenced from ``mkdocs.yml`` ``extra_css``) that re-skins Material
to match the look of deepwiki-open: a warm "washi paper" light theme and a charcoal dark
theme, a soft-purple accent, a subtle paper texture, and gently rounded, shadowed content
blocks. It does this purely by overriding Material's documented CSS custom properties per
colour scheme (``[data-md-color-scheme="default"]`` / ``"slate"``), so it layers on top of the
stock theme without forking it.

The palette values are taken from deepwiki-open's own ``globals.css`` (the "Japanese
aesthetic" palette). :func:`render_extra_css` is deterministic and byte-stable; the writer
emits its output verbatim to ``docs/<EXTRA_CSS_PATH>``.
"""

from __future__ import annotations

__all__ = ["EXTRA_CSS_PATH", "render_extra_css"]

#: Docs-relative path of the extra stylesheet (Material's conventional ``stylesheets/`` dir).
#: Referenced from ``mkdocs.yml`` ``extra_css`` and emitted here by the writer.
EXTRA_CSS_PATH: str = "stylesheets/extra.css"

#: The washi-paper texture deepwiki-open uses on its light background (an inline SVG so the
#: site needs no external asset). Kept as a module constant for byte-stability.
_PAPER_TEXTURE_SVG: str = (
    "url(\"data:image/svg+xml,%3Csvg width='80' height='80' viewBox='0 0 80 80' "
    "xmlns='http://www.w3.org/2000/svg'%3E%3Cpath d='M11 18c3.866 0 7-3.134 7-7s-3.134-7-7-7"
    "-7 3.134-7 7 3.134 7 7 7zm48 25c3.866 0 7-3.134 7-7s-3.134-7-7-7-7 3.134-7 7 3.134 7 7 "
    "7zm-43-7c1.657 0 3-1.343 3-3s-1.343-3-3-3-3 1.343-3 3 1.343 3 3 3zm63 31c1.657 0 3-1.343 "
    "3-3s-1.343-3-3-3-3 1.343-3 3 1.343 3 3 3zM34 90c1.657 0 3-1.343 3-3s-1.343-3-3-3-3 "
    "1.343-3 3 1.343 3 3 3zm56-76c1.657 0 3-1.343 3-3s-1.343-3-3-3-3 1.343-3 3 1.343 3 3 3z' "
    "fill='%23e0d8c8' fill-opacity='0.18' fill-rule='evenodd'/%3E%3C/svg%3E\")"
)


def render_extra_css() -> str:
    """Return the deepwiki-inspired Material override stylesheet (deterministic, byte-stable).

    Overrides Material's per-scheme CSS custom properties only — background/foreground,
    primary/accent, link and code colours — for the light (``default``) and dark (``slate``)
    schemes, then adds the paper texture and softly rounded, shadowed content blocks. No
    Material internals are forked; equal calls return an equal string.
    """
    return _CSS


_CSS: str = """\
/* DocuHarnessX site theme — deepwiki-open-inspired skin for Material for MkDocs.
   Washi-paper light + charcoal dark, soft-purple accent. Overrides documented Material
   CSS custom properties per colour scheme; does not fork the stock theme. */

/* ---- Light scheme ("default"): warm washi paper ---- */
[data-md-color-scheme="default"] {
  --md-default-bg-color: #f8f4e6;
  --md-default-fg-color: #333333;
  --md-default-fg-color--light: #5a5446;
  --md-default-fg-color--lighter: #a59e8c;
  --md-default-fg-color--lightest: #e0d8c8;
  --md-primary-fg-color: #9b7cb9;
  --md-primary-fg-color--light: #b19cd9;
  --md-primary-fg-color--dark: #7c5aa0;
  --md-primary-bg-color: #fffaf0;
  --md-primary-bg-color--light: #fffaf0;
  --md-accent-fg-color: #e8927c;
  --md-typeset-a-color: #7c5aa0;
  --md-code-bg-color: #fffaf0;
  --md-code-fg-color: #5a4a6a;
}

/* ---- Dark scheme ("slate"): deep charcoal ---- */
[data-md-color-scheme="slate"] {
  --md-default-bg-color: #1a1a1a;
  --md-default-bg-color--light: #222222;
  --md-default-fg-color: #f0f0f0;
  --md-default-fg-color--light: #c8c8c8;
  --md-default-fg-color--lighter: #8c8c8c;
  --md-default-fg-color--lightest: #2c2c2c;
  --md-primary-fg-color: #9370db;
  --md-primary-fg-color--light: #b19cd9;
  --md-primary-fg-color--dark: #5d4037;
  --md-primary-bg-color: #222222;
  --md-accent-fg-color: #e57373;
  --md-typeset-a-color: #b19cd9;
  --md-code-bg-color: #222222;
  --md-code-fg-color: #d7c4bb;
}

/* Subtle washi paper texture behind the content (light scheme only). */
[data-md-color-scheme="default"] .md-main {
  background-image: %PAPER%;
}

/* Softly rounded, gently shadowed content blocks (the deepwiki "card" feel). */
.md-typeset pre,
.md-typeset .admonition,
.md-typeset details,
.md-typeset .mermaid {
  border-radius: 8px;
  box-shadow: 0 4px 10px -4px rgba(0, 0, 0, 0.12);
}

/* Center rendered Mermaid diagrams with a little breathing room. */
.md-typeset .mermaid {
  text-align: center;
  padding: 0.6rem 0;
}

/* Sidebar: a slightly tighter, wiki-like tree with an accented section title. */
.md-nav {
  font-size: 0.72rem;
}
.md-nav__title {
  color: var(--md-primary-fg-color--dark);
  font-weight: 700;
}
.md-nav__item .md-nav__link--active {
  font-weight: 700;
}
"""


# Inline the paper texture once (kept out of the f-string above for readability).
_CSS = _CSS.replace("%PAPER%", _PAPER_TEXTURE_SVG)
