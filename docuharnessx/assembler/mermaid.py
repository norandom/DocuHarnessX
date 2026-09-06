"""Copy the vendored Mermaid runtime into an assembled site.

Material 9.7.7 otherwise injects ``https://unpkg.com/mermaid@11/dist/mermaid.min.js``
when it finds a diagram and ``window.mermaid`` is missing. The assembler ships the
same UMD build as a local extra script so the published site never fetches it.
"""

from __future__ import annotations

from importlib.resources import files
from pathlib import Path

__all__ = [
    "MERMAID_BOOT_PATH",
    "MERMAID_JS_PATH",
    "MERMAID_SCRIPTS",
    "load_mermaid_javascript",
    "render_mermaid_boot_js",
    "write_mermaid_javascript",
]

MERMAID_JS_PATH = "javascripts/mermaid.min.js"
MERMAID_BOOT_PATH = "javascripts/mermaid-boot.js"
MERMAID_SCRIPTS: tuple[str, str] = (MERMAID_JS_PATH, MERMAID_BOOT_PATH)

#: Disable Mermaid's own auto-render so Material can theme and mount diagrams.
_MERMAID_BOOT = """(function () {
  if (typeof mermaid === "undefined" || !mermaid.initialize) return;
  mermaid.initialize({ startOnLoad: false });
})();
"""


def load_mermaid_javascript() -> bytes:
    """Return the vendored Mermaid 11.17.2 UMD build (MIT, mermaid-js)."""
    return files("docuharnessx.assembler.vendor").joinpath("mermaid.min.js").read_bytes()


def render_mermaid_boot_js() -> str:
    """Return the boot script that keeps Mermaid from racing Material."""
    return _MERMAID_BOOT


def write_mermaid_javascript(docs_dir: Path) -> None:
    """Write the local Mermaid copies under ``docs/javascripts/``."""
    dest = docs_dir / MERMAID_JS_PATH
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(load_mermaid_javascript())
    boot = docs_dir / MERMAID_BOOT_PATH
    with open(boot, "w", encoding="utf-8", newline="") as handle:
        handle.write(render_mermaid_boot_js())
