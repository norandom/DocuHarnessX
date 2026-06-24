"""The site home landing page (``docs/index.md``) and its place in the nav.

Without a docs-root ``index.md`` the generated site has no entry point — the base path is a
404. These tests pin the home-page renderer (:func:`docuharnessx.assembler.home.render_home_page`),
that the writer emits it, that it is first in the nav, and that it names the *target* project
(never DocuHarnessX) without leaking authoring-methodology terms.
"""

from __future__ import annotations

from pathlib import Path

from docuharnessx.assembler.home import HOME_PAGE_PATH, render_home_page
from docuharnessx.assembler.mkdocs_config import (
    HOME_NAV_TITLE,
    TAGS_INDEX_PATH,
    build_mkdocs_yaml,
)
from docuharnessx.assembler.model import SiteIdentity

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


def test_home_page_has_heading_and_names_target_repo() -> None:
    page = render_home_page(_identity(), _ROLE_PAGES)
    assert page.startswith("# malware_hashes\n")
    assert "github.com/acme/malware_hashes" in page  # links the target repo
    assert "DocuHarnessX" not in page  # never the generator's own identity


def test_home_page_links_each_role_in_order() -> None:
    page = render_home_page(_identity(), _ROLE_PAGES)
    assert "[Developer](developer/index.md)" in page
    assert "[Manager](manager/index.md)" in page
    assert page.index("developer/index.md") < page.index("manager/index.md")
    assert f"[Tags]({TAGS_INDEX_PATH})" in page


def test_home_page_with_no_roles_still_valid() -> None:
    page = render_home_page(_identity(), ())
    assert page.startswith("# malware_hashes\n")
    assert page.endswith("\n")
    assert "No documentation sections" in page


def test_home_page_names_no_authoring_methodology() -> None:
    page = render_home_page(_identity(), _ROLE_PAGES)
    lowered = page.lower()
    for jargon in ("cobesy", "scqa", "minto", "reduce", "working memory", "andragogy"):
        assert jargon not in lowered, jargon


def test_home_page_is_deterministic() -> None:
    assert render_home_page(_identity(), _ROLE_PAGES) == render_home_page(
        _identity(), _ROLE_PAGES
    )


def test_nav_lists_home_first() -> None:
    # String-based: the rendered mkdocs.yml carries a "!!python/name:" tag for the mermaid
    # fence that a plain yaml.safe_load would reject. The Home entry must precede the role
    # entries, and the tags index must remain last.
    raw = build_mkdocs_yaml(_identity(), _ROLE_PAGES, None)
    home_at = raw.find(f"{HOME_NAV_TITLE}: {HOME_PAGE_PATH}")
    dev_at = raw.find("developer/index.md")
    tags_at = raw.rfind(TAGS_INDEX_PATH)
    assert home_at != -1
    assert home_at < dev_at < tags_at


def test_writer_emits_index_md_at_docs_root(tmp_path: Path) -> None:
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
    index = Path(site.docs_dir) / HOME_PAGE_PATH
    assert index.is_file()
    assert index.read_text(encoding="utf-8").startswith("# malware_hashes\n")
