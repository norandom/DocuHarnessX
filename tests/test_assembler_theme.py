"""The deepwiki-open-inspired theme: palette/font wiring, the extra stylesheet, and the
wiki-style nested sidebar nav.

The assembled site is Material for MkDocs re-skinned to resemble deepwiki-open: a washi-paper
light theme + charcoal dark theme with a soft-purple accent (applied by an extra stylesheet
overriding Material's CSS custom properties), the Noto Sans JP font, a light/dark toggle, and
a left sidebar that is a full page tree (each role section followed by its segment pages).
"""

from __future__ import annotations

from pathlib import Path

from docuharnessx.assembler.mkdocs_config import build_mkdocs_yaml
from docuharnessx.assembler.model import SiteIdentity
from docuharnessx.assembler.theme import EXTRA_CSS_PATH, render_extra_css

_ROLE_PAGES = (("Developer", "developer/index.md"), ("Manager", "manager/index.md"))


def _identity() -> SiteIdentity:
    return SiteIdentity(
        site_name="malware_hashes",
        repo_name="malware_hashes",
        repo_url="https://github.com/acme/malware_hashes",
        site_url="https://acme.github.io/malware_hashes/",
        base_path="/malware_hashes/",
        edit_uri="edit/main/docs/",
    )


# --------------------------------------------------------------------------- #
# Extra stylesheet — deepwiki palette overrides                                #
# --------------------------------------------------------------------------- #


def test_extra_css_carries_both_scheme_palettes() -> None:
    css = render_extra_css()
    # Light "default" scheme overrides + dark "slate" scheme overrides are both present.
    assert '[data-md-color-scheme="default"]' in css
    assert '[data-md-color-scheme="slate"]' in css
    # deepwiki-open's signature colours.
    assert "#f8f4e6" in css  # washi-paper light background
    assert "#1a1a1a" in css  # charcoal dark background
    assert "#9b7cb9" in css or "#9370db" in css  # soft-purple accent
    # It overrides documented Material custom properties (does not fork the theme).
    assert "--md-default-bg-color" in css and "--md-primary-fg-color" in css


def test_extra_css_is_deterministic() -> None:
    assert render_extra_css() == render_extra_css()


def test_extra_css_path_is_under_stylesheets() -> None:
    assert EXTRA_CSS_PATH == "stylesheets/extra.css"


# --------------------------------------------------------------------------- #
# mkdocs.yml — palette toggle, font, extra_css wiring                          #
# --------------------------------------------------------------------------- #


def test_mkdocs_yaml_wires_palette_font_and_extra_css() -> None:
    raw = build_mkdocs_yaml(_identity(), _ROLE_PAGES, None)
    # Light + dark palette with a toggle.
    assert "scheme: default" in raw and "scheme: slate" in raw
    assert "Switch to dark mode" in raw and "Switch to light mode" in raw
    # deepwiki body font + the extra stylesheet reference.
    assert "Noto Sans JP" in raw
    assert EXTRA_CSS_PATH in raw
    # A left-sidebar (not top-tabs) experience.
    assert "navigation.tabs" not in raw
    assert "navigation.indexes" in raw and "navigation.expand" in raw


# --------------------------------------------------------------------------- #
# Nested sidebar nav — role sections with their segment pages                  #
# --------------------------------------------------------------------------- #


def test_nav_nests_segments_under_their_role_section() -> None:
    segments_by_role = {
        "developer/index.md": (
            ("Extend the engine", "dev-extend-1.md"),
            ("Build internals", "dev-build-2.md"),
        ),
        "manager/index.md": (("Evaluate fit", "mgr-eval-3.md"),),
    }
    raw = build_mkdocs_yaml(_identity(), _ROLE_PAGES, None, segments_by_role)
    # The role landing page is the section index; its segments are listed under it.
    assert "developer/index.md" in raw and "dev-extend-1.md" in raw
    assert "Extend the engine: dev-extend-1.md" in raw
    # Each segment's title labels its nav entry.
    assert "Evaluate fit: mgr-eval-3.md" in raw
    # Ordering: Home first, the developer section's segments before the manager section.
    assert raw.find("dev-extend-1.md") < raw.find("mgr-eval-3.md")


def test_nav_flat_when_no_segments_given() -> None:
    # Back-compatible: with no mapping each role is a flat link (no nested section).
    raw = build_mkdocs_yaml(_identity(), _ROLE_PAGES, None)
    assert "Developer: developer/index.md" in raw
    assert "Manager: manager/index.md" in raw


def test_writer_emits_extra_css(tmp_path: Path) -> None:
    from docuharnessx.assembler.writer import assemble_site
    from docuharnessx.ontology import default_profile
    from docuharnessx.review.model import ReviewAggregate, ReviewReport

    report = ReviewReport(
        schema_version=1,
        entries=(),
        accepted=(),
        aggregate=ReviewAggregate(
            judged=0, accepted=0, rejected=0, unavailable=0, criterion_tally=()
        ),
    )
    site = assemble_site(report, default_profile(), None, str(tmp_path), _identity())
    css = Path(site.docs_dir) / EXTRA_CSS_PATH
    assert css.is_file()
    assert "#f8f4e6" in css.read_text(encoding="utf-8")
