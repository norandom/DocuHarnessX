"""Default black/white Material theme, optional deepwiki skin, depth slider."""

from __future__ import annotations

from pathlib import Path

from docuharnessx.assembler.mkdocs_config import build_mkdocs_yaml
from docuharnessx.assembler.model import SiteIdentity
from docuharnessx.assembler.theme import (
    EXTRA_CSS_PATH,
    EXTRA_JS_PATH,
    render_depth_js,
    render_extra_css,
)
from docuharnessx.site_config import SitePresentation

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


def test_default_extra_css_is_black_not_violet() -> None:
    css = render_extra_css()
    assert "#9b7cb9" not in css
    assert "#9370db" not in css
    assert ".dhx-depth" in css
    assert "#E8B923" in css
    assert ".node.person" in css


def test_deepwiki_extra_css_keeps_violet_palette() -> None:
    css = render_extra_css("deepwiki")
    assert '[data-md-color-scheme="default"]' in css
    assert "#f8f4e6" in css
    assert "#9b7cb9" in css or "#9370db" in css


def test_extra_css_is_deterministic() -> None:
    assert render_extra_css() == render_extra_css()


def test_extra_css_path_is_under_stylesheets() -> None:
    assert EXTRA_CSS_PATH == "stylesheets/extra.css"


# --------------------------------------------------------------------------- #
# mkdocs.yml — palette toggle, font, extra_css wiring                          #
# --------------------------------------------------------------------------- #


def test_mkdocs_yaml_wires_palette_font_and_extra_css() -> None:
    raw = build_mkdocs_yaml(_identity(), _ROLE_PAGES, None)
    assert "scheme: default" in raw and "scheme: slate" in raw
    assert "primary: black" in raw
    assert "Switch to dark mode" in raw and "Switch to light mode" in raw
    assert "Roboto" in raw
    assert "Noto Sans JP" not in raw
    assert EXTRA_CSS_PATH in raw
    assert EXTRA_JS_PATH in raw
    assert "md_in_html" in raw
    # A left-sidebar (not top-tabs) experience.
    assert "navigation.tabs" not in raw
    assert "navigation.indexes" in raw and "navigation.expand" in raw


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
    assert ".dhx-depth" in css.read_text(encoding="utf-8")
    js = Path(site.docs_dir) / EXTRA_JS_PATH
    assert js.is_file()
    assert "dhx-depth" in js.read_text(encoding="utf-8")


def test_deepwiki_mkdocs_omits_black_primary() -> None:
    raw = build_mkdocs_yaml(
        _identity(),
        _ROLE_PAGES,
        None,
        presentation=SitePresentation(theme="deepwiki", depth=5),
    )
    assert "Noto Sans JP" in raw
    assert "primary: black" not in raw


def test_depth_js_bakes_default() -> None:
    js = render_depth_js(3)
    assert "var DEFAULT_DEPTH = 3;" in js
