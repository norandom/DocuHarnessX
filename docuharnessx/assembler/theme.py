"""Site theme stylesheet and engineering-depth slider script.

Default look is Material for MkDocs **black/white** (``primary: black``). The
optional ``deepwiki`` theme keeps the older washi-paper + violet skin.
Both themes ship the depth-slider CSS; :data:`EXTRA_JS_PATH` is the slider.
"""

from __future__ import annotations

from docuharnessx.site_config import DEFAULT_DEPTH, DEFAULT_THEME, parse_depth, parse_theme

__all__ = [
    "EXTRA_CSS_PATH",
    "EXTRA_JS_PATH",
    "render_depth_js",
    "render_extra_css",
]

EXTRA_CSS_PATH: str = "stylesheets/extra.css"
EXTRA_JS_PATH: str = "javascripts/depth.js"

_PAPER_TEXTURE_SVG: str = (
    "url(\"data:image/svg+xml,%3Csvg width='80' height='80' viewBox='0 0 80 80' "
    "xmlns='http://www.w3.org/2000/svg'%3E%3Cpath d='M11 18c3.866 0 7-3.134 7-7s-3.134-7-7-7"
    "-7 3.134-7 7 3.134 7 7 7zm48 25c3.866 0 7-3.134 7-7s-3.134-7-7-7-7 3.134-7 7 3.134 7 7 "
    "7zm-43-7c1.657 0 3-1.343 3-3s-1.343-3-3-3-3 1.343-3 3 1.343 3 3 3zm63 31c1.657 0 3-1.343 "
    "3-3s-1.343-3-3-3-3 1.343-3 3 1.343 3 3 3zM34 90c1.657 0 3-1.343 3-3s-1.343-3-3-3-3 "
    "1.343-3 3 1.343 3 3 3zm56-76c1.657 0 3-1.343 3-3s-1.343-3-3-3-3 1.343-3 3 1.343 3 3 3z' "
    "fill='%23e0d8c8' fill-opacity='0.18' fill-rule='evenodd'/%3E%3C/svg%3E\")"
)

_SLIDER_CSS: str = """
/* Engineering-depth slider in the header. */
.dhx-depth {
  display: flex;
  align-items: center;
  gap: 0.45rem;
  margin-left: 0.75rem;
  color: var(--md-primary-bg-color);
  font-size: 0.65rem;
  white-space: nowrap;
}
.dhx-depth__range {
  width: 7rem;
  accent-color: var(--md-primary-bg-color);
}
.dhx-depth__value {
  min-width: 7.5rem;
}
.dhx-layer[hidden] {
  display: none !important;
}
a.dhx-term, a[href*="glossary.md"] {
  text-decoration: underline dotted;
}
.dhx-na { background: #9e9e9e; color: #fff; padding: 0.05em 0.4em; }
.dhx-fail { background: #c62828; color: #fff; padding: 0.05em 0.4em; }
.dhx-partial { background: #f9a825; color: #111; padding: 0.05em 0.4em; }
.dhx-pass { background: #2e7d32; color: #fff; padding: 0.05em 0.4em; }

.md-typeset pre,
.md-typeset .admonition,
.md-typeset details,
.md-typeset .mermaid {
  border-radius: 8px;
}
.md-typeset .mermaid {
  text-align: center;
  padding: 0.6rem 0;
}
"""

_BLACK_CSS: str = """\
/* DocuHarnessX default theme — Material black/white. */

""" + _SLIDER_CSS

_DEEPWIKI_CSS: str = """\
/* DocuHarnessX optional theme — deepwiki-open washi paper + violet. */

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

[data-md-color-scheme="default"] .md-main {
  background-image: %PAPER%;
}

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
""" + _SLIDER_CSS

_DEEPWIKI_CSS = _DEEPWIKI_CSS.replace("%PAPER%", _PAPER_TEXTURE_SVG)

_DEPTH_JS: str = """\
(function () {
  var DEFAULT_DEPTH = %DEPTH%;
  var STORAGE_KEY = "dhx-depth";
  var LABELS = {
    1: "Adopter",
    2: "Evaluator",
    3: "Operator",
    4: "Integrator",
    5: "Programmer",
    6: "Maintainer",
    7: "Internals"
  };

  function apply(depth) {
    var n = Math.min(7, Math.max(1, depth));
    document.documentElement.setAttribute("data-dhx-depth", String(n));
    document.querySelectorAll(".dhx-layer").forEach(function (el) {
      var min = Number(el.getAttribute("data-min") || "1");
      el.hidden = min > n;
    });
    var out = document.getElementById("dhx-depth-label");
    if (out) out.textContent = n + "/7 " + (LABELS[n] || "");
    try { localStorage.setItem(STORAGE_KEY, String(n)); } catch (err) {}
  }

  function mount() {
    var header = document.querySelector(".md-header__inner");
    if (!header || document.getElementById("dhx-depth")) return;
    var wrap = document.createElement("div");
    wrap.id = "dhx-depth";
    wrap.className = "dhx-depth";
    wrap.innerHTML =
      '<label class="dhx-depth__label" for="dhx-depth-range">Depth</label>' +
      '<input id="dhx-depth-range" class="dhx-depth__range" type="range" min="1" max="7" step="1">' +
      '<span id="dhx-depth-label" class="dhx-depth__value"></span>';
    header.appendChild(wrap);
    var input = wrap.querySelector("input");
    var start = DEFAULT_DEPTH;
    try {
      var saved = localStorage.getItem(STORAGE_KEY);
      if (saved) start = Number(saved);
    } catch (err) {}
    input.value = String(start);
    input.addEventListener("input", function () { apply(Number(input.value)); });
    apply(start);
  }

  document.addEventListener("DOMContentLoaded", mount);
  if (typeof document$ !== "undefined" && document$.subscribe) {
    document$.subscribe(mount);
  }
})();
"""


def render_extra_css(theme: str = DEFAULT_THEME) -> str:
    """Return the extra stylesheet for ``theme`` (deterministic)."""
    if parse_theme(theme) == "deepwiki":
        return _DEEPWIKI_CSS
    return _BLACK_CSS


def render_depth_js(depth: int = DEFAULT_DEPTH) -> str:
    """Return the header depth-slider script with the project default baked in."""
    return _DEPTH_JS.replace("%DEPTH%", str(parse_depth(depth)))
