"""Reading-order helpers for the question site home and nav."""

from __future__ import annotations

from docuharnessx.assembler.home import render_question_home
from docuharnessx.assembler.model import SiteIdentity
from docuharnessx.assembler.pages import page_filename
from docuharnessx.assembler.story import (
    first_sentence,
    primary_component,
    story_order,
    story_spine,
)
from docuharnessx.pages.model import Page
from docuharnessx.planning.question_model import QuestionKind, make_question_id


def _identity() -> SiteIdentity:
    return SiteIdentity(
        site_name="DocuHarnessX",
        repo_name="norandom/DocuHarnessX",
        repo_url="https://github.com/norandom/DocuHarnessX",
        site_url="https://norandom.github.io/DocuHarnessX/",
        base_path="/DocuHarnessX/",
        edit_uri="edit/main/docs/",
    )


def _page(
    kind: QuestionKind,
    slug: str,
    title: str,
    summary: str = "summary",
) -> Page:
    return Page(
        id=make_question_id(kind, slug),
        title=title,
        summary=summary,
        body="body",
        subjects=(slug,),
        related=(),
        cited_files=(),
    )


def _corpus() -> tuple[Page, ...]:
    return (
        _page(QuestionKind.COMPONENT, "analysis", "What does analysis do?"),
        _page(QuestionKind.BUILD, "pyproject.toml", "How is this project built?"),
        _page(QuestionKind.STARTUP, "cli.py", "How does this program start?"),
        _page(QuestionKind.COMPONENT, "docuharnessx", "What does docuharnessx do?"),
        _page(QuestionKind.TESTS, "tests", "How are tests organized?"),
        _page(QuestionKind.PUBLIC_SURFACE, "init.py", "How is the public surface used?"),
        _page(QuestionKind.COMPONENT, "mcp", "What does mcp do?"),
    )


def test_story_order_starts_with_startup_then_the_system() -> None:
    ordered = story_order(_corpus(), _identity())
    titles = [page.title for page in ordered]
    assert titles[0] == "How does this program start?"
    assert titles[1] == "What does docuharnessx do?"
    assert titles[2] == "How is this project built?"
    assert titles[3] == "How are tests organized?"
    assert titles[4] == "How is the public surface used?"
    assert "What does analysis do?" in titles[5:]
    assert "What does mcp do?" in titles[5:]


def test_primary_component_matches_repo_name() -> None:
    page = primary_component(_corpus(), _identity())
    assert page is not None
    assert page.id.endswith(":docuharnessx")


def test_primary_component_does_not_guess_among_many() -> None:
    pages = (
        _page(QuestionKind.COMPONENT, "analysis", "What does analysis do?"),
        _page(QuestionKind.COMPONENT, "mcp", "What does mcp do?"),
    )
    other = SiteIdentity(
        site_name="other",
        repo_name="acme/other",
        repo_url="https://github.com/acme/other",
        site_url="https://acme.github.io/other/",
        base_path="/other/",
        edit_uri="edit/main/docs/",
    )
    assert primary_component(pages, other) is None
    alone = (_page(QuestionKind.COMPONENT, "engine", "What does Engine do?"),)
    assert primary_component(alone, other) is not None


def test_spine_caps_at_five() -> None:
    spine = story_spine(_corpus(), _identity())
    assert len(spine) == 5
    assert spine[0].title == "How does this program start?"
    assert all(
        not page.id.startswith("component:") or page.id.endswith(":docuharnessx")
        for page in spine
    )


def test_first_sentence_stops_at_period_not_versions() -> None:
    text = "Package version 2.0.0 ships a CLI. The rest is internals."
    assert first_sentence(text) == "Package version 2.0.0 ships a CLI."


def test_question_home_is_a_numbered_path() -> None:
    home = render_question_home(_identity(), _corpus())
    start = "[How does this program start?](" + page_filename(
        make_question_id(QuestionKind.STARTUP, "cli.py")
    ) + ")"
    system = "[What does docuharnessx do?](" + page_filename(
        make_question_id(QuestionKind.COMPONENT, "docuharnessx")
    ) + ")"
    extra = "[What does mcp do?](" + page_filename(
        make_question_id(QuestionKind.COMPONENT, "mcp")
    ) + ")"
    assert "## Read in this order" in home
    assert "## More questions" in home
    assert "1. " + start in home
    assert home.index(start) < home.index(system)
    assert home.index("## More questions") < home.index(extra)
    lowered = home.lower()
    for jargon in ("cobesy", "scqa", "minto", "reduce", "andragogy"):
        assert jargon not in lowered, jargon


def test_story_order_is_deterministic() -> None:
    pages = _corpus()
    identity = _identity()
    assert story_order(pages, identity) == story_order(pages, identity)
    assert story_order(tuple(reversed(pages)), identity) == story_order(
        pages, identity
    )
