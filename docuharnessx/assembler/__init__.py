"""The pure, model-free MkDocs site-assembly core (Wave 3, spec #1: ``mkdocs-site-assembler``).

``docuharnessx.assembler`` is the deterministic, harness-free assembly core behind the
thin :class:`~docuharnessx.stages.assemble.AssembleStage` adapter. It consumes the
accepted ontology :class:`~docuharnessx.ontology.Segment` set (verbatim, read-only) from
the frozen :class:`~docuharnessx.review.model.ReviewReport`, the loaded project
:class:`~docuharnessx.ontology.Vocabulary`, and the optional
:class:`~docuharnessx.analysis.model.RepoAnalysis`, and emits a **Material for MkDocs**
source tree under the run's output directory: one ``docs/*.md`` page per accepted segment,
per-role landing pages with COBESY-structured intent-ordered agendas, a tags index, and a
``mkdocs.yml`` configuring the Material theme and the tags plugin. All work is
deterministic and unit-testable without a model or network (the only subprocess is the
read-only, mockable origin-remote read in :mod:`docuharnessx.assembler.identity`).

This module is the **single public namespace** for the assembler core (mirroring
:mod:`docuharnessx.planning`, :mod:`docuharnessx.composition`, and
:mod:`docuharnessx.review`). Downstream consumers — the ``AssembleStage`` adapter and the
tests — import from ``docuharnessx.assembler`` rather than reaching into submodules.

Each re-export is identity-equal to its submodule definition (no shadow copies). Later
tasks populate the namespace further:

* task 1.2 (this task) — the frozen output seam from :mod:`docuharnessx.assembler.model`
  (:class:`AssembledSite`, :class:`SiteIdentity`, the single
  :data:`ASSEMBLED_SITE_SCHEMA_VERSION` authority, and the
  :class:`AssemblerError` / :class:`AssemblerInputError` family);
* task 2.1 — the pure per-target site-identity resolver
  (:func:`resolve_site_identity`) from :mod:`docuharnessx.assembler.identity`; task 2.2 adds
  the mockable, read-only origin-remote read (:func:`read_origin_remote`) to the same module;
* task 3.1/3.2/3.3 — the per-segment page renderer, the per-role landing-page renderer,
  and the ``mkdocs.yml`` builder;
* task 4.1 — the site writer that orchestrates the renderers and emits the tree.

:data:`__all__` is the authoritative, self-consistent contract for the package (mirroring
the sibling pure-core packages).
"""

from __future__ import annotations

from docuharnessx.assembler.model import (
    ASSEMBLED_SITE_SCHEMA_VERSION,
    AssembledSite,
    AssemblerError,
    AssemblerInputError,
    SiteIdentity,
)
from docuharnessx.assembler.home import HOME_PAGE_PATH, render_home_page
from docuharnessx.assembler.identity import read_origin_remote, resolve_site_identity
from docuharnessx.assembler.mkdocs_config import TAGS_INDEX_PATH, build_mkdocs_yaml
from docuharnessx.assembler.pages import page_filename, render_segment_page
from docuharnessx.assembler.roles import render_role_landing_page, role_page_path
from docuharnessx.assembler.theme import EXTRA_CSS_PATH, render_extra_css
from docuharnessx.assembler.writer import assemble_site

__all__ = [
    # frozen assembled-site data model (task 1.2)
    "ASSEMBLED_SITE_SCHEMA_VERSION",
    "SiteIdentity",
    "AssembledSite",
    "AssemblerError",
    "AssemblerInputError",
    # per-target site-identity resolver (task 2.1) + mockable origin-remote read (task 2.2)
    "resolve_site_identity",
    "read_origin_remote",
    # per-segment page renderer (task 3.1)
    "page_filename",
    "render_segment_page",
    # per-role landing-page renderer (task 3.2)
    "render_role_landing_page",
    "role_page_path",
    # mkdocs.yml builder (task 3.3)
    "build_mkdocs_yaml",
    "TAGS_INDEX_PATH",
    # site home landing page
    "render_home_page",
    "HOME_PAGE_PATH",
    # deepwiki-inspired theme stylesheet
    "render_extra_css",
    "EXTRA_CSS_PATH",
    # site writer (task 4.1)
    "assemble_site",
]
