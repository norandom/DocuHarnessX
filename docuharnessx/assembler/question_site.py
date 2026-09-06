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
from typing import TYPE_CHECKING

from docuharnessx.assembler.home import HOME_PAGE_PATH, render_question_home
from docuharnessx.assembler.mkdocs_config import build_question_mkdocs_yaml
from docuharnessx.assembler.model import (
    ASSEMBLED_SITE_SCHEMA_VERSION,
    AssembledSite,
    SiteIdentity,
)
from docuharnessx.assembler.pages import page_filename, render_question_page
from docuharnessx.assembler.theme import (
    EXTRA_CSS_PATH,
    EXTRA_JS_PATH,
    render_depth_js,
    render_extra_css,
)
from docuharnessx.comprehension.autolink import autolink_markdown
from docuharnessx.comprehension.compliance import load_compliance, score_matrix
from docuharnessx.comprehension.detect import detect_comprehension
from docuharnessx.comprehension.glossary import load_glossary, merge_glossary, seed_glossary
from docuharnessx.comprehension.graphs import render_compliance_page, render_glossary_page
from docuharnessx.comprehension.signals import ComprehensionSignals, CoverageCounts
from docuharnessx.pages.model import Page
from docuharnessx.site_config import SitePresentation

if TYPE_CHECKING:  # pragma: no cover - typing only
    from docuharnessx.analysis.model import RepoAnalysis
    from docuharnessx.ontology import Vocabulary

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
    analysis: "RepoAnalysis | None" = None,
    presentation: SitePresentation | None = None,
    *,
    project_dir: str | None = None,
    vocab: "Vocabulary | None" = None,
    signals: ComprehensionSignals | None = None,
    counts: CoverageCounts | None = None,
) -> AssembledSite | None:
    """Assemble a question-organised site from accepted pages, or skip.

    Args:
        pages: Accepted question pages in nav/home order. Omitted questions are
            not passed in and leave no stub (Req 8.3).
        identity: Resolved per-target :class:`SiteIdentity`.
        out_dir: Run output directory. The tree is written under ``<out_dir>/site``.
        analysis: Optional frozen ``RepoAnalysis`` used to enrich per-page
            Mermaid companions (entrypoints, components, public surface). The
            site still builds when this is ``None``.
        presentation: Theme and default engineering depth. ``None`` uses black / 5.

    Returns:
        A frozen :class:`AssembledSite` with ``role_page_count == 0`` when at
        least one page is accepted, else ``None`` and no files under ``site/``
        (Req 8.4). The returned seam is the existing deployer input (Req 8.5).
    """
    if not pages:
        return None

    look = presentation or SitePresentation()
    accepted = tuple(pages)
    root = project_dir or (analysis.repo_path if analysis is not None else ".")
    live_signals = signals if signals is not None else detect_comprehension(
        analysis, root
    )
    site_dir = Path(out_dir) / _SITE_SUBDIR
    docs_dir = site_dir / _DOCS_SUBDIR
    docs_dir.mkdir(parents=True, exist_ok=True)

    glossary = merge_glossary(
        seed_glossary(vocab, analysis),
        load_glossary(root),
    )

    for page in accepted:
        rel_path, content = render_question_page(
            page,
            accepted,
            analysis=analysis,
            signals=live_signals,
        )
        _write_text(docs_dir / rel_path, autolink_markdown(content, glossary))

    home = render_question_home(
        identity,
        accepted,
        analysis=analysis,
        signals=live_signals,
        counts=counts,
    )
    _write_text(docs_dir / HOME_PAGE_PATH, autolink_markdown(home, glossary))
    _write_text(docs_dir / EXTRA_CSS_PATH, render_extra_css(look.theme))
    _write_text(docs_dir / EXTRA_JS_PATH, render_depth_js(look.depth))

    extra_nav: list[tuple[str, str]] = []
    if glossary.terms:
        _write_text(docs_dir / "glossary.md", render_glossary_page(glossary))
        extra_nav.append(("Glossary", "glossary.md"))
    selection = load_compliance(root)
    if selection.frameworks:
        cells = score_matrix(selection, analysis)
        _write_text(
            docs_dir / "compliance.md",
            render_compliance_page(selection, cells),
        )
        extra_nav.append(("Compliance", "compliance.md"))

    nav_pages = tuple((page.title, page_filename(page.id)) for page in accepted)
    mkdocs_yml_path = site_dir / _MKDOCS_YML
    _write_text(
        mkdocs_yml_path,
        build_question_mkdocs_yaml(
            identity,
            nav_pages,
            presentation=look,
            extra_nav=tuple(extra_nav),
        ),
    )

    return AssembledSite(
        schema_version=ASSEMBLED_SITE_SCHEMA_VERSION,
        site_dir=os.path.abspath(str(site_dir)),
        docs_dir=os.path.abspath(str(docs_dir)),
        mkdocs_yml_path=os.path.abspath(str(mkdocs_yml_path)),
        identity=identity,
        page_count=len(accepted),
        role_page_count=0,
    )
