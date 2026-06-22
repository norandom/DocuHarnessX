"""The per-segment Markdown page renderer (design "Segment page renderer"; task 3.1).

This module is one of the deterministic, model-free renderers of the Wave 3
``mkdocs-site-assembler`` core. It turns a single accepted ontology
:class:`~docuharnessx.ontology.Segment` — together with the loaded project
:class:`~docuharnessx.ontology.Vocabulary` and the set of accepted segment ids — into the
Material for MkDocs page the writer emits under ``<out>/site/docs/`` (Req 4.1-4.5):

* :func:`page_filename` derives a **stable, deterministic, filesystem-safe** page filename
  from the segment id (Req 4.1). Distinct ids never collide: a slug is computed for
  readability, and a short, deterministic digest of the *raw* id is appended so two ids that
  slugify to the same token (or to an empty token) still map to distinct, valid filenames.
* :func:`render_segment_page` produces the ``(relative_docs_path, page_markdown)`` pair: a
  YAML frontmatter block whose ``tags:`` is exactly ``emit_tags(segment, vocab)`` so the
  Material tags plugin indexes the page (Req 4.3); the title as an H1 heading (Req 4.2); the
  segment body preserved verbatim (Req 4.2); and a "Related" section of in-page Markdown
  links built from ``segment.related`` filtered to ids present in the accepted set, dropping
  any dangling reference and any self-reference (Req 4.4).

The renderer is **pure**: it treats the segment read-only, performs no I/O, and emits
byte-identical output for equal inputs (Req 4.5) — its only inputs are the segment, the
vocabulary, and the accepted-id set, and the accepted-id set is consulted by membership only
(never iterated), so its incidental order can never perturb the output. ``emit_tags`` is the
single source of the page's tags, so a project that renames/reorders its vocabulary changes
the emitted tags with no code change here.
"""

from __future__ import annotations

import hashlib

import yaml

from docuharnessx.ontology import Segment, Vocabulary, emit_tags

__all__ = ["page_filename", "render_segment_page"]

#: The fence delimiter for a YAML frontmatter block (matches the ontology serializer).
_FENCE = "---"

#: Length of the deterministic id-digest suffix appended to every page slug. A short hex
#: digest is enough to keep distinct ids distinct while keeping filenames readable.
_DIGEST_LEN = 8


def _slugify(segment_id: str) -> str:
    """Return a filesystem-safe slug derived from ``segment_id``.

    Lower-cases the id, maps every run of non-``[a-z0-9]`` characters to a single ``-``, and
    trims leading/trailing ``-``. The result contains only ``[a-z0-9-]`` (so it is safe on
    every filesystem and inside a URL) and may be empty for a pathological id — the empty
    case is handled by :func:`page_filename`, which always also appends a digest. Pure and
    deterministic.
    """
    out: list[str] = []
    prev_dash = False
    for ch in segment_id.casefold():
        if ch.isalnum() and ch.isascii():
            out.append(ch)
            prev_dash = False
        else:
            if not prev_dash:
                out.append("-")
            prev_dash = True
    return "".join(out).strip("-")


def page_filename(segment_id: str) -> str:
    """Return the stable, deterministic, filesystem-safe page filename for ``segment_id``.

    The filename is ``<slug>-<digest>.md`` (or ``<digest>.md`` when the slug is empty),
    where ``digest`` is the first :data:`_DIGEST_LEN` hex characters of the SHA-256 of the
    *raw* id. Appending the digest guarantees that distinct ids yield distinct filenames
    even when their slugs collide (e.g. ``"a b"`` and ``"a-b-"``) or are empty (Req 4.1),
    while the leading slug keeps the name human-readable. Pure and deterministic: identical
    ids always yield the identical name.
    """
    slug = _slugify(segment_id)
    digest = hashlib.sha256(segment_id.encode("utf-8")).hexdigest()[:_DIGEST_LEN]
    stem = f"{slug}-{digest}" if slug else digest
    return f"{stem}.md"


def _frontmatter(segment: Segment, vocab: Vocabulary) -> str:
    """Return the YAML frontmatter block (fenced) carrying the segment's tags.

    The ``tags:`` value is exactly ``emit_tags(segment, vocab)`` (Req 4.3), serialized as a
    list (an empty list when the segment carries no vocabulary-valid axis value).
    ``yaml.safe_dump`` with ``sort_keys=False`` keeps emission deterministic.
    """
    tags = list(emit_tags(segment, vocab))
    body = yaml.safe_dump(
        {"tags": tags},
        default_flow_style=False,
        sort_keys=False,
        allow_unicode=True,
    )
    return f"{_FENCE}\n{body}{_FENCE}\n"


def _related_links(segment: Segment, accepted_ids: "frozenset[str]") -> list[str]:
    """Return the Markdown "Related" link lines, in the segment's declared order.

    Each ``segment.related`` reference is rendered as a Markdown link to the referenced
    segment's page file, in declared order, filtered to ids present in ``accepted_ids`` and
    excluding any self-reference (Req 4.4). Dangling references (not accepted) and a
    self-reference are dropped. Duplicate references are emitted once, preserving first
    occurrence. Returns an empty list when nothing survives the filter.
    """
    lines: list[str] = []
    seen: set[str] = set()
    for target in segment.related:
        if target == segment.id:
            continue
        if target not in accepted_ids:
            continue
        if target in seen:
            continue
        seen.add(target)
        lines.append(f"- [{target}]({page_filename(target)})")
    return lines


def render_segment_page(
    segment: Segment, vocab: Vocabulary, accepted_ids: "frozenset[str]"
) -> tuple[str, str]:
    """Render one accepted ``segment`` to ``(relative_docs_path, page_markdown)``.

    Produces (Req 4.1-4.5):

    * the relative docs path :func:`page_filename(segment.id) <page_filename>`;
    * a leading YAML frontmatter block whose ``tags:`` equals ``emit_tags(segment, vocab)``
      verbatim (Req 4.3);
    * the title as an H1 heading (Req 4.2);
    * the segment body preserved verbatim (Req 4.2) — when non-empty;
    * a "Related" section of in-page Markdown links from ``segment.related`` filtered to the
      accepted set, dangling references and self-references dropped (Req 4.4) — emitted only
      when at least one link survives.

    Pure and read-only over the segment; ``accepted_ids`` is consulted by membership only, so
    its iteration order never affects the output. Equal inputs yield byte-identical output
    (Req 4.5). The page always ends with a single trailing newline.
    """
    parts: list[str] = [_frontmatter(segment, vocab), f"# {segment.title}\n"]

    body = segment.body
    if body:
        # Separate the heading from the body with a blank line; preserve the body verbatim.
        parts.append("\n" + body if not body.startswith("\n") else body)

    related = _related_links(segment, accepted_ids)
    if related:
        parts.append("\n## Related\n\n" + "\n".join(related) + "\n")

    content = "".join(parts)
    if not content.endswith("\n"):
        content += "\n"
    return page_filename(segment.id), content
