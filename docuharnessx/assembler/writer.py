"""The site writer (design "Site writer"; task 4.1).

This module is the orchestration boundary of the Wave 3 ``mkdocs-site-assembler`` core. It
is the single deterministic, model-free, network-free transform that turns the quality-gated
content into a publishable **Material for MkDocs** source tree on disk and the frozen
:class:`~docuharnessx.assembler.model.AssembledSite` seam the
:class:`~docuharnessx.stages.assemble.AssembleStage` adapter publishes.

:func:`assemble_site` consumes:

* the frozen :class:`~docuharnessx.review.model.ReviewReport` — its
  :attr:`~docuharnessx.review.model.ReviewReport.accepted` set is the segments that passed
  the COBESY quality gate, consumed **verbatim, read-only** (Req 2.2);
* the loaded project :class:`~docuharnessx.ontology.Vocabulary` — the single source of the
  role/intent ordering, so a renamed/reordered vocabulary changes the site with no code
  change (Req 5.6);
* the optional :class:`~docuharnessx.analysis.model.RepoAnalysis` — accepted for
  site-identity context but its absence is tolerated (Req 2.5);
* the run's output directory ``out_dir`` — the only write target (Req 8.5);
* the resolved per-target :class:`~docuharnessx.assembler.model.SiteIdentity` (Req 3.x).

and orchestrates the deterministic renderers (the only place that wires them together):

1. builds a **fresh** :class:`~docuharnessx.ontology.InMemorySegmentStore` over the accepted
   segments, so the role-view agendas contain *only* accepted segments (not the full written
   corpus) — the role views are derived against this accepted-only store;
2. renders one ``docs/<segment>.md`` page per accepted segment via
   :func:`~docuharnessx.assembler.pages.render_segment_page`, passing the accepted-id set so
   cross-links resolve only to accepted pages (Req 4.1, 4.4);
3. renders one ``docs/<role>/index.md`` landing page **only** for each vocabulary role that
   has at least one accepted segment, in vocabulary role order, omitting empty roles
   (Req 5.1, 5.5) via :func:`~docuharnessx.assembler.roles.render_role_landing_page`;
4. builds the ``docs/tags.md`` index page carrying the Material ``<!-- material/tags -->``
   listing directive the ``tags`` plugin discovers (Req 6.2);
5. builds the ``mkdocs.yml`` from the identity, the emitted role pages, and the vocabulary
   via :func:`~docuharnessx.assembler.mkdocs_config.build_mkdocs_yaml` (Req 6.1, 6.4);
6. writes the whole tree under ``<out_dir>/site/`` (``mkdocs.yml`` + ``docs/``) and returns a
   frozen :class:`AssembledSite` with the per-segment page count and the per-role landing
   page count (Req 7.1).

Determinism (Req 8.1, 8.2): the writer performs no model call and no network access; it
iterates the accepted set and the vocabulary roles in their declared order, renders through
pure renderers, and writes UTF-8 text with explicit newline content — so identical inputs
yield a byte-identical tree across runs. Isolation (Req 8.5): the single write target is
``<out_dir>/site``; the writer never derives DocuHarnessX's own identity (the identity is the
caller's per-target value). Segments are treated read-only throughout (Req 2.2).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

from docuharnessx.assembler.home import HOME_PAGE_PATH, render_home_page
from docuharnessx.assembler.mkdocs_config import TAGS_INDEX_PATH, build_mkdocs_yaml
from docuharnessx.assembler.model import (
    ASSEMBLED_SITE_SCHEMA_VERSION,
    AssembledSite,
    SiteIdentity,
)
from docuharnessx.assembler.pages import page_filename, render_segment_page
from docuharnessx.assembler.roles import render_role_landing_page, role_page_path
from docuharnessx.assembler.theme import EXTRA_CSS_PATH, render_extra_css
from docuharnessx.ontology import (
    AxisTerm,
    InMemorySegmentStore,
    Vocabulary,
    build_role_view,
)
from docuharnessx.review.model import ReviewReport

if TYPE_CHECKING:  # optional site-identity context, consumed read-only (Req 2.5).
    from docuharnessx.analysis.model import RepoAnalysis

__all__ = ["assemble_site"]

#: The site source root, relative to the run's output directory. The whole Material for
#: MkDocs source tree (``mkdocs.yml`` + ``docs/``) lives under ``<out_dir>/site`` — the single
#: write target for this one target run (Req 8.5).
_SITE_SUBDIR: str = "site"

#: The docs directory name under the site root (the MkDocs ``docs_dir`` default).
_DOCS_SUBDIR: str = "docs"

#: The mkdocs configuration filename under the site root.
_MKDOCS_YML: str = "mkdocs.yml"

#: The heading and Material listing directive written into the tags index page
#: (:data:`~docuharnessx.assembler.mkdocs_config.TAGS_INDEX_PATH`). The ``tags`` plugin
#: discovers the ``<!-- material/tags -->`` directive and renders the namespaced
#: ``role:``/``subject:``/``intent:`` tag listing there (Req 6.2). Byte-stable.
_TAGS_INDEX_CONTENT: str = "# Tags\n\nBrowse the corpus by tag.\n\n<!-- material/tags -->\n"


def _build_accepted_store(
    report: ReviewReport, vocab: Vocabulary
) -> InMemorySegmentStore:
    """Build a fresh accepted-only :class:`InMemorySegmentStore` (design step 1).

    Populates a new store, bound to the loaded ``vocab``, with exactly the accepted segments
    in ``report.accepted`` so the role-view agendas derived via ``build_role_view`` contain
    only accepted segments — not the full written corpus. The accepted segments are the same
    identities the upstream written set holds and are stored read-only (``put`` does not copy
    or mutate them). Deterministic: the store orders by id internally, and the accepted set is
    already validated upstream.
    """
    store = InMemorySegmentStore(vocab)
    for segment in report.accepted:
        store.put(segment)
    return store


def _emitted_roles(
    store: InMemorySegmentStore, vocab: Vocabulary
) -> tuple[AxisTerm, ...]:
    """Return the vocabulary roles that carry at least one accepted segment, in vocab order.

    Walks ``vocab.roles`` in their declared (configurable) order and includes a role only
    when its accepted-store role view is non-empty (Req 5.1, 5.5) — empty roles are omitted
    rather than emitting an empty agenda. The order is a total, deterministic function of the
    vocabulary role order; this single list drives both the nav (``mkdocs.yml``) and the
    role-switch affordance on every landing page, so all landing pages agree on the same set.
    """
    return tuple(
        role for role in vocab.roles if build_role_view(store, role.id, vocab)
    )


def _write_text(path: Path, content: str) -> None:
    """Write ``content`` to ``path`` as UTF-8 with ``\\n`` newlines, creating parents.

    Newlines are written verbatim (``newline=""``) so the on-disk bytes equal the renderer's
    byte-stable output on every platform — the renderers already end every file with a single
    ``\\n`` (Req 8.2). Parent directories are created as needed so a ``<role>/index.md`` page
    lands under its role directory.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as handle:
        handle.write(content)


def assemble_site(
    report: ReviewReport,
    vocab: Vocabulary,
    analysis: "RepoAnalysis | None",
    out_dir: str,
    identity: SiteIdentity,
) -> AssembledSite:
    """Assemble the Material for MkDocs source tree and return the frozen seam (task 4.1).

    Args:
        report: The frozen :class:`~docuharnessx.review.model.ReviewReport`. Only its
            :attr:`~docuharnessx.review.model.ReviewReport.accepted` set is consumed, verbatim
            and read-only (Req 2.2). Its ``schema_version`` is validated by the stage adapter
            before this is called.
        vocab: The loaded :class:`~docuharnessx.ontology.Vocabulary` — the single source of
            the role and intent ordering (Req 5.6). Never hardcoded here.
        analysis: The optional :class:`~docuharnessx.analysis.model.RepoAnalysis` site-identity
            context. Accepted for symmetry; its absence is tolerated (the identity is already
            resolved by the caller), so ``None`` never raises (Req 2.5).
        out_dir: The run's resolved output directory. The whole tree is written under
            ``<out_dir>/site`` — the single write target (Req 8.5). Created if missing.
        identity: The resolved per-target :class:`~docuharnessx.assembler.model.SiteIdentity`
            (Req 3.x). Reflected verbatim into ``mkdocs.yml``; never DocuHarnessX's own
            identity (Req 3.8).

    Returns:
        A frozen :class:`AssembledSite` carrying the absolute site/docs/``mkdocs.yml`` paths,
        the resolved ``identity``, the per-segment ``page_count``, and the per-role
        ``role_page_count`` (Req 7.1).

    The site layout under ``<out_dir>/site``: ``mkdocs.yml``; ``docs/<segment>.md`` (one per
    accepted segment); ``docs/<role>/index.md`` (one per non-empty vocabulary role, in
    vocabulary order); ``docs/tags.md`` (the tags index). Deterministic and byte-stable for
    equal inputs (Req 8.1, 8.2); no model call, no network access.
    """
    # ``analysis`` is accepted for site-identity context; the identity is already resolved by
    # the caller, so an absent analysis is simply tolerated here (Req 2.5).
    del analysis

    site_dir = Path(out_dir) / _SITE_SUBDIR
    docs_dir = site_dir / _DOCS_SUBDIR
    docs_dir.mkdir(parents=True, exist_ok=True)

    # Step 1: a fresh accepted-only store so role views contain only accepted segments.
    store = _build_accepted_store(report, vocab)
    accepted_ids: frozenset[str] = frozenset(seg.id for seg in report.accepted)

    # Step 2: one per-segment page per accepted segment (cross-links filtered to accepted).
    page_count = 0
    for segment in report.accepted:
        rel_path, content = render_segment_page(segment, vocab, accepted_ids)
        _write_text(docs_dir / rel_path, content)
        page_count += 1

    # Step 3: one landing page per non-empty vocabulary role, in vocabulary order. The full
    # emitted set is computed first so every landing page's role-switch affordance and the
    # nav reference the same role pages.
    emitted_roles = _emitted_roles(store, vocab)
    role_pages = tuple(
        (role.label, role_page_path(role.id)) for role in emitted_roles
    )
    for role in emitted_roles:
        landing_rel, content = render_role_landing_page(role, store, vocab, role_pages)
        _write_text(docs_dir / landing_rel, content)
    role_page_count = len(emitted_roles)

    # Assign each accepted segment to exactly ONE role section — its first emitted role in
    # vocabulary order — so the sidebar nav becomes a wiki-style page tree (role section ->
    # its segment pages) with no duplicate entries (a segment may belong to several roles).
    emitted_role_ids = [role.id for role in emitted_roles]
    landing_by_role_id = {role.id: role_page_path(role.id) for role in emitted_roles}
    grouped: dict[str, list[tuple[str, str]]] = {}
    for segment in report.accepted:
        primary = next(
            (rid for rid in emitted_role_ids if rid in segment.roles), None
        )
        if primary is None:
            continue  # every accepted segment has an emitted role; defensive only
        grouped.setdefault(landing_by_role_id[primary], []).append(
            (segment.title, page_filename(segment.id))
        )
    segments_by_role = {landing: tuple(entries) for landing, entries in grouped.items()}

    # Step 4: the tags index page (the listing directive the tags plugin discovers).
    _write_text(docs_dir / TAGS_INDEX_PATH, _TAGS_INDEX_CONTENT)

    # Step 4b: the home landing page at the docs root, so the site has a real entry point
    # (``index.md`` renders at the base path instead of a 404). It indexes the same emitted
    # role pages the nav carries, in the same order.
    _write_text(docs_dir / HOME_PAGE_PATH, render_home_page(identity, role_pages))

    # Step 4c: the deepwiki-inspired theme stylesheet referenced from mkdocs.yml extra_css.
    _write_text(docs_dir / EXTRA_CSS_PATH, render_extra_css())

    # Step 5: the mkdocs.yml (Material theme + tags plugin + per-target identity + nav).
    mkdocs_yml = build_mkdocs_yaml(identity, role_pages, vocab, segments_by_role)
    mkdocs_yml_path = site_dir / _MKDOCS_YML
    _write_text(mkdocs_yml_path, mkdocs_yml)

    return AssembledSite(
        schema_version=ASSEMBLED_SITE_SCHEMA_VERSION,
        site_dir=os.path.abspath(str(site_dir)),
        docs_dir=os.path.abspath(str(docs_dir)),
        mkdocs_yml_path=os.path.abspath(str(mkdocs_yml_path)),
        identity=identity,
        page_count=page_count,
        role_page_count=role_page_count,
    )
