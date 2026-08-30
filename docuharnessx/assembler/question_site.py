"""Question-organised MkDocs assembly from accepted pages.

:func:`assemble_question_site` is the explore-first site entry point. It writes
a Material source tree from accepted :class:`~docuharnessx.pages.model.Page`
values only: home lists question titles, nav is home + pages, and there are no
per-role landings. Zero accepted pages writes nothing under ``site/`` and
returns ``None`` so callers skip deploy (Req 8.1–8.5).

The ReviewReport / Vocabulary :func:`~docuharnessx.assembler.writer.assemble_site`
path is unchanged.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from pathlib import Path

from docuharnessx.assembler.home import HOME_PAGE_PATH, render_question_home
from docuharnessx.assembler.mkdocs_config import build_question_mkdocs_yaml
from docuharnessx.assembler.model import (
    ASSEMBLED_SITE_SCHEMA_VERSION,
    AssembledSite,
    SiteIdentity,
)
from docuharnessx.assembler.pages import page_filename, render_question_page
from docuharnessx.assembler.theme import EXTRA_CSS_PATH, render_extra_css
from docuharnessx.pages.model import Page

__all__ = ["assemble_question_site"]

_SITE_SUBDIR: str = "site"
_DOCS_SUBDIR: str = "docs"
_MKDOCS_YML: str = "mkdocs.yml"


def _write_text(path: Path, content: str) -> None:
    """Write UTF-8 text with verbatim newlines, creating parent directories."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as handle:
        handle.write(content)


def assemble_question_site(
    pages: Sequence[Page],
    identity: SiteIdentity,
    out_dir: str,
) -> AssembledSite | None:
    """Assemble a question-organised site from accepted pages, or skip.

    Args:
        pages: Accepted question pages in nav/home order. Omitted questions are
            not passed in and leave no stub (Req 8.3).
        identity: Resolved per-target :class:`SiteIdentity`.
        out_dir: Run output directory. The tree is written under ``<out_dir>/site``.

    Returns:
        A frozen :class:`AssembledSite` with ``role_page_count == 0`` when at
        least one page is accepted, else ``None`` and no files under ``site/``
        (Req 8.4). The returned seam is the existing deployer input (Req 8.5).
    """
    if not pages:
        return None

    accepted = tuple(pages)
    site_dir = Path(out_dir) / _SITE_SUBDIR
    docs_dir = site_dir / _DOCS_SUBDIR
    docs_dir.mkdir(parents=True, exist_ok=True)

    for page in accepted:
        rel_path, content = render_question_page(page, accepted)
        _write_text(docs_dir / rel_path, content)

    _write_text(docs_dir / HOME_PAGE_PATH, render_question_home(identity, accepted))
    _write_text(docs_dir / EXTRA_CSS_PATH, render_extra_css())

    nav_pages = tuple((page.title, page_filename(page.id)) for page in accepted)
    mkdocs_yml_path = site_dir / _MKDOCS_YML
    _write_text(mkdocs_yml_path, build_question_mkdocs_yaml(identity, nav_pages))

    return AssembledSite(
        schema_version=ASSEMBLED_SITE_SCHEMA_VERSION,
        site_dir=os.path.abspath(str(site_dir)),
        docs_dir=os.path.abspath(str(docs_dir)),
        mkdocs_yml_path=os.path.abspath(str(mkdocs_yml_path)),
        identity=identity,
        page_count=len(accepted),
        role_page_count=0,
    )
