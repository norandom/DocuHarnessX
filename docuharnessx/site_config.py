"""Project site presentation: theme and engineering-depth default.

Persisted at ``.docuharnessx/site.yaml``. Distinct from the ontology and the
adoption record. ``dhx init`` writes this; assemble reads it.
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from typing import Any, Mapping, TextIO

import yaml

__all__ = [
    "DEFAULT_DEPTH",
    "DEFAULT_THEME",
    "DEPTH_LABELS",
    "MAX_DEPTH",
    "MIN_DEPTH",
    "SITE_CONFIG_RELPATH",
    "THEMES",
    "SitePresentation",
    "load_site_presentation",
    "parse_depth",
    "parse_theme",
    "prompt_site_presentation",
    "save_site_presentation",
]

SITE_CONFIG_RELPATH = os.path.join(".docuharnessx", "site.yaml")
THEMES: tuple[str, ...] = ("black", "deepwiki")
DEFAULT_THEME = "black"
MIN_DEPTH = 1
MAX_DEPTH = 7
DEFAULT_DEPTH = 1

DEPTH_LABELS: dict[int, str] = {
    1: "Adopter",
    2: "Evaluator",
    3: "Operator",
    4: "Integrator",
    5: "Programmer",
    6: "Maintainer",
    7: "Internals",
}


@dataclass(frozen=True)
class SitePresentation:
    """How the published MkDocs site looks and how deep it starts."""

    theme: str = DEFAULT_THEME
    depth: int = DEFAULT_DEPTH


def parse_theme(raw: str | None) -> str:
    value = (raw or "").strip().lower()
    if value in THEMES:
        return value
    return DEFAULT_THEME


def parse_depth(raw: str | int | None) -> int:
    if raw is None or raw == "":
        return DEFAULT_DEPTH
    try:
        number = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_DEPTH
    return max(MIN_DEPTH, min(MAX_DEPTH, number))


def load_site_presentation(project_dir: str) -> SitePresentation:
    """Load ``.docuharnessx/site.yaml``, or the black/programmer defaults."""
    path = os.path.join(project_dir, SITE_CONFIG_RELPATH)
    if not os.path.isfile(path):
        return SitePresentation()
    with open(path, "r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, Mapping):
        return SitePresentation()
    return SitePresentation(
        theme=parse_theme(str(data.get("theme", DEFAULT_THEME))),
        depth=parse_depth(data.get("depth")),
    )


def save_site_presentation(project_dir: str, presentation: SitePresentation) -> str:
    """Write ``.docuharnessx/site.yaml``. Returns the path."""
    path = os.path.join(project_dir, SITE_CONFIG_RELPATH)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    payload: dict[str, Any] = asdict(presentation)
    with open(path, "w", encoding="utf-8") as handle:
        yaml.safe_dump(payload, handle, sort_keys=False, allow_unicode=True)
    return path


def prompt_site_presentation(
    *,
    input_fn: Any,
    out: TextIO,
    existing: SitePresentation | None = None,
) -> SitePresentation:
    """Ask for theme and depth. Enter keeps the default (or existing values)."""
    current = existing or SitePresentation()
    print(
        "Site theme: black = Material black/white (default); "
        "deepwiki = washi paper + violet.",
        file=out,
    )
    raw_theme = input_fn(f"Site theme [{current.theme}]: ").strip()
    theme = parse_theme(raw_theme or current.theme)
    print(
        "Engineering depth 1-7: 1 Adopter … 5 Programmer … 7 Internals.",
        file=out,
    )
    raw_depth = input_fn(f"Engineering depth 1-7 [{current.depth}]: ").strip()
    depth = parse_depth(raw_depth) if raw_depth else current.depth
    return SitePresentation(theme=theme, depth=depth)
