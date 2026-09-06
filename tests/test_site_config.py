"""Site presentation: theme + engineering depth."""

from __future__ import annotations

from pathlib import Path

from docuharnessx.assembler.depth import wrap_layer
from docuharnessx.site_config import (
    DEFAULT_DEPTH,
    DEFAULT_THEME,
    SitePresentation,
    load_site_presentation,
    parse_depth,
    parse_theme,
    prompt_site_presentation,
    save_site_presentation,
)


def test_parse_theme_and_depth_defaults() -> None:
    assert parse_theme("") == DEFAULT_THEME
    assert parse_theme("deepwiki") == "deepwiki"
    assert parse_theme("violet") == DEFAULT_THEME
    assert parse_depth("") == DEFAULT_DEPTH
    assert parse_depth("1") == 1
    assert parse_depth("99") == 7
    assert parse_depth("nope") == DEFAULT_DEPTH


def test_save_and_load_round_trip(tmp_path: Path) -> None:
    path = save_site_presentation(
        str(tmp_path), SitePresentation(theme="deepwiki", depth=3)
    )
    assert path.endswith("site.yaml")
    loaded = load_site_presentation(str(tmp_path))
    assert loaded == SitePresentation(theme="deepwiki", depth=3)


def test_missing_site_yaml_is_black_programmer(tmp_path: Path) -> None:
    assert load_site_presentation(str(tmp_path)) == SitePresentation()


def test_prompt_keeps_enter_defaults() -> None:
    answers = iter(["", ""])
    result = prompt_site_presentation(
        input_fn=lambda _p: next(answers),
        out=__import__("io").StringIO(),
    )
    assert result.theme == "black"
    assert result.depth == 5


def test_wrap_layer_skips_blank() -> None:
    assert wrap_layer(5, "  \n") == ""
    text = wrap_layer(1, "Hello")
    assert 'data-min="1"' in text
    assert "Hello" in text
    assert "markdown=\"1\"" in text
