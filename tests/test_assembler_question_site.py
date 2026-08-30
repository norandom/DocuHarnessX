"""Unit tests for question-organised site assembly (task 2.4).

Task 2.4 (explore-first-simplification, boundary: *SiteAssembler*) adds
:func:`docuharnessx.assembler.assemble_question_site` and
:func:`docuharnessx.assembler.home.render_question_home`. The new entry point
emits a Material site from accepted :class:`~docuharnessx.pages.model.Page`
values only — home lists question titles as links; nav is home + pages; there
are no per-role landing pages. Zero accepted pages writes nothing under
``site/`` so callers skip deploy.

The old :func:`~docuharnessx.assembler.assemble_site` / :func:`render_home_page`
path is unchanged.

Observable completion (tasks.md 2.4 / Req 2.3, 8.1–8.5, 10.1): two accepted
pages → home lists both titles and has no “pick your role” / role-directory
index; zero pages → no role landing files.
"""

from __future__ import annotations

import os
from pathlib import Path

from docuharnessx.assembler.home import HOME_PAGE_PATH, render_question_home
from docuharnessx.assembler.mkdocs_config import HOME_NAV_TITLE, TAGS_INDEX_PATH
from docuharnessx.assembler.model import (
    ASSEMBLED_SITE_SCHEMA_VERSION,
    AssembledSite,
    SiteIdentity,
)
from docuharnessx.assembler.pages import page_filename
from docuharnessx.assembler.question_site import assemble_question_site
from docuharnessx.pages.model import Page
from docuharnessx.planning.question_model import QuestionKind, make_question_id

# Role-landing / persona-index copy that must not appear on the question site.
_ROLE_INDEX_PHRASES: tuple[str, ...] = (
    "pick your role",
    "pick the path that matches your role",
    "choose your path",
    "choose your role",
    "role-based documentation",
    "coming soon",
)

_ROLE_LANDING_RELPATHS: tuple[str, ...] = (
    "developer/index.md",
    "devops-admin/index.md",
    "operator/index.md",
    "manager/index.md",
    "auditor/index.md",
)


def _identity() -> SiteIdentity:
    return SiteIdentity(
        site_name="agentic_repo",
        repo_name="acme/agentic_repo",
        repo_url="https://github.com/acme/agentic_repo",
        site_url="https://acme.github.io/agentic_repo/",
        base_path="/agentic_repo/",
        edit_uri="edit/main/docs/",
    )


def _startup_page() -> Page:
    return Page(
        id=make_question_id(QuestionKind.STARTUP, "app.py"),
        title="How does this program start?",
        summary="The CLI starts in app.py by loading config and constructing Engine.",
        body=(
            "The program starts in `app.py:12` by calling `load_config` "
            "(`config.py:8`) and constructing `Engine` (`engine.py:15`)."
        ),
        subjects=("app.py",),
        related=("component:engine",),
        cited_files=("app.py", "config.py", "engine.py"),
    )


def _engine_page() -> Page:
    return Page(
        id=make_question_id(QuestionKind.COMPONENT, "engine"),
        title="What does Engine do?",
        summary="Engine drives a bounded work cycle from loaded config.",
        body=(
            "The `Engine` class loads run settings through `load_config` "
            "(`config.py:10`) and then drives a bounded work cycle (`engine.py:16`)."
        ),
        subjects=("Engine",),
        related=("startup:app.py",),
        cited_files=("config.py", "engine.py"),
    )


def _two_pages() -> tuple[Page, Page]:
    return (_startup_page(), _engine_page())


def _lowered_tree_text(root: Path) -> str:
    chunks: list[str] = []
    if not root.exists():
        return ""
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.suffix in {".md", ".yml", ".yaml"}:
            chunks.append(path.read_text(encoding="utf-8"))
    return "\n".join(chunks).lower()


# --------------------------------------------------------------------------- #
# Module / package surface                                                     #
# --------------------------------------------------------------------------- #


def test_assemble_question_site_exported_from_package() -> None:
    import docuharnessx.assembler as pkg
    from docuharnessx.assembler.question_site import assemble_question_site as impl

    assert "assemble_question_site" in pkg.__all__
    assert pkg.assemble_question_site is impl


def test_render_question_home_exported_from_package() -> None:
    import docuharnessx.assembler as pkg

    assert "render_question_home" in pkg.__all__
    assert pkg.render_question_home is render_question_home


def test_old_home_and_assemble_entry_points_remain() -> None:
    import docuharnessx.assembler as pkg
    from docuharnessx.assembler.home import render_home_page
    from docuharnessx.assembler.writer import assemble_site

    assert pkg.render_home_page is render_home_page
    assert pkg.assemble_site is assemble_site


# --------------------------------------------------------------------------- #
# render_question_home (Req 2.3, 8.1, 8.2)                                     #
# --------------------------------------------------------------------------- #


def test_question_home_heading_is_site_name() -> None:
    page = render_question_home(_identity(), _two_pages())
    assert page.startswith("# agentic_repo\n")
    assert "github.com/acme/agentic_repo" in page
    assert "DocuHarnessX" not in page


def test_question_home_lists_accepted_titles_as_links_in_order() -> None:
    pages = _two_pages()
    home = render_question_home(_identity(), pages)
    first = f"[{pages[0].title}]({page_filename(pages[0].id)})"
    second = f"[{pages[1].title}]({page_filename(pages[1].id)})"
    assert first in home
    assert second in home
    assert home.index(first) < home.index(second)


def test_question_home_has_no_role_index_copy() -> None:
    home = render_question_home(_identity(), _two_pages()).lower()
    for phrase in _ROLE_INDEX_PHRASES:
        assert phrase not in home, phrase
    for rel in _ROLE_LANDING_RELPATHS:
        assert rel not in home, rel


def test_question_home_is_deterministic() -> None:
    pages = _two_pages()
    assert render_question_home(_identity(), pages) == render_question_home(
        _identity(), pages
    )


# --------------------------------------------------------------------------- #
# Two accepted pages → question site (Req 8.1, 8.2, 8.3, 10.1)                 #
# --------------------------------------------------------------------------- #


def test_two_pages_returns_assembled_site_with_absolute_paths(
    tmp_path: Path,
) -> None:
    site = assemble_question_site(_two_pages(), _identity(), str(tmp_path))
    assert isinstance(site, AssembledSite)
    assert site.schema_version == ASSEMBLED_SITE_SCHEMA_VERSION
    assert os.path.isabs(site.site_dir)
    assert os.path.isabs(site.docs_dir)
    assert os.path.isabs(site.mkdocs_yml_path)
    assert site.identity == _identity()
    assert site.page_count == 2
    assert site.role_page_count == 0
    assert Path(site.site_dir) == tmp_path / "site"
    assert Path(site.docs_dir) == tmp_path / "site" / "docs"
    assert Path(site.mkdocs_yml_path) == tmp_path / "site" / "mkdocs.yml"


def test_two_pages_home_lists_both_titles(tmp_path: Path) -> None:
    pages = _two_pages()
    site = assemble_question_site(pages, _identity(), str(tmp_path))
    assert site is not None
    home = (Path(site.docs_dir) / HOME_PAGE_PATH).read_text(encoding="utf-8")
    assert pages[0].title in home
    assert pages[1].title in home
    assert f"]({page_filename(pages[0].id)})" in home
    assert f"]({page_filename(pages[1].id)})" in home


def test_two_pages_emits_one_markdown_file_per_page(tmp_path: Path) -> None:
    pages = _two_pages()
    site = assemble_question_site(pages, _identity(), str(tmp_path))
    assert site is not None
    docs = Path(site.docs_dir)
    for page in pages:
        path = docs / page_filename(page.id)
        assert path.is_file(), path
        text = path.read_text(encoding="utf-8")
        assert f"# {page.title}" in text
        assert page.body in text


def test_two_pages_home_and_nav_have_no_role_directory_index(
    tmp_path: Path,
) -> None:
    site = assemble_question_site(_two_pages(), _identity(), str(tmp_path))
    assert site is not None
    docs = Path(site.docs_dir)
    yml = Path(site.mkdocs_yml_path).read_text(encoding="utf-8")
    home = (docs / HOME_PAGE_PATH).read_text(encoding="utf-8")
    tree = _lowered_tree_text(Path(site.site_dir))

    for phrase in _ROLE_INDEX_PHRASES:
        assert phrase not in home.lower(), phrase
        assert phrase not in tree, phrase

    for rel in _ROLE_LANDING_RELPATHS:
        assert rel not in yml, rel
        assert rel not in home, rel
        assert not (docs / rel).exists(), rel

    assert list(docs.glob("*/index.md")) == []


def test_two_pages_nav_is_home_plus_pages_only(tmp_path: Path) -> None:
    pages = _two_pages()
    site = assemble_question_site(pages, _identity(), str(tmp_path))
    assert site is not None
    yml = Path(site.mkdocs_yml_path).read_text(encoding="utf-8")
    home_at = yml.find(f"{HOME_NAV_TITLE}: {HOME_PAGE_PATH}")
    first_at = yml.find(page_filename(pages[0].id))
    second_at = yml.find(page_filename(pages[1].id))
    assert home_at != -1
    assert first_at != -1
    assert second_at != -1
    assert home_at < first_at < second_at
    assert pages[0].title in yml
    assert pages[1].title in yml
    assert TAGS_INDEX_PATH not in yml
    assert "tags.md" not in yml


def test_two_pages_mkdocs_carries_identity(tmp_path: Path) -> None:
    ident = _identity()
    site = assemble_question_site(_two_pages(), ident, str(tmp_path))
    assert site is not None
    yml = Path(site.mkdocs_yml_path).read_text(encoding="utf-8")
    assert f"site_name: {ident.site_name}" in yml
    assert ident.site_url in yml
    assert ident.repo_url in yml
    assert "name: material" in yml


def test_omitted_question_leaves_no_stub_page(tmp_path: Path) -> None:
    pages = _two_pages()
    omitted_id = make_question_id(QuestionKind.BUILD, "pyproject.toml")
    site = assemble_question_site(pages, _identity(), str(tmp_path))
    assert site is not None
    docs = Path(site.docs_dir)
    assert not (docs / page_filename(omitted_id)).exists()
    tree = _lowered_tree_text(Path(site.site_dir))
    assert omitted_id not in tree
    assert "coming soon" not in tree
    written = {path.name for path in docs.glob("*.md")}
    expected = {HOME_PAGE_PATH, *(page_filename(page.id) for page in pages)}
    assert written == expected


def test_assembled_site_is_deployable_shape(tmp_path: Path) -> None:
    # Optional publish modes consume AssembledSite; this path must remain callable
    # after a non-empty assemble without reimplementing the deployer.
    from docuharnessx.deployer.deploy import deploy_site

    site = assemble_question_site(_two_pages(), _identity(), str(tmp_path))
    assert site is not None
    assert callable(deploy_site)
    assert Path(site.mkdocs_yml_path).is_file()
    assert Path(site.docs_dir).is_dir()


def test_two_runs_are_byte_identical(tmp_path: Path) -> None:
    ident = _identity()
    pages = _two_pages()
    a_out = tmp_path / "a"
    b_out = tmp_path / "b"
    site_a = assemble_question_site(pages, ident, str(a_out))
    site_b = assemble_question_site(pages, ident, str(b_out))
    assert site_a is not None and site_b is not None

    def snapshot(root: Path) -> dict[str, bytes]:
        return {
            path.relative_to(root).as_posix(): path.read_bytes()
            for path in sorted(root.rglob("*"))
            if path.is_file()
        }

    assert snapshot(Path(site_a.site_dir)) == snapshot(Path(site_b.site_dir))


# --------------------------------------------------------------------------- #
# Zero accepted pages → no site tree (Req 8.4)                                 #
# --------------------------------------------------------------------------- #


def test_zero_pages_returns_none_and_writes_nothing(tmp_path: Path) -> None:
    out = tmp_path / "out"
    out.mkdir()
    result = assemble_question_site((), _identity(), str(out))
    assert result is None
    assert not (out / "site").exists()
    assert list(out.iterdir()) == []


def test_zero_pages_writes_no_role_landing_files(tmp_path: Path) -> None:
    result = assemble_question_site((), _identity(), str(tmp_path))
    assert result is None
    assert list(tmp_path.rglob("**/index.md")) == []
    for rel in _ROLE_LANDING_RELPATHS:
        assert not (tmp_path / "site" / "docs" / rel).exists()
    assert not (tmp_path / "site" / "mkdocs.yml").exists()
