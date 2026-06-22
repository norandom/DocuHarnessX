"""Unit tests for the per-segment Markdown page renderer (mkdocs-site-assembler task 3.1).

These tests pin the *Segment page renderer* boundary (design "Segment page renderer";
Req 4.1-4.5) of the Wave 3 ``mkdocs-site-assembler`` core: the stable, deterministic,
filesystem-safe :func:`page_filename` and the pure :func:`render_segment_page`, which turns
one accepted :class:`~docuharnessx.ontology.Segment` (plus the loaded
:class:`~docuharnessx.ontology.Vocabulary` and the set of accepted segment ids) into a
``(relative_docs_path, page_markdown)`` pair:

* frontmatter ``tags:`` equal to ``emit_tags(segment, vocab)`` verbatim (Req 4.3),
* the title rendered as a heading (Req 4.2),
* the body preserved verbatim (Req 4.2),
* a "Related" section of in-page Markdown links built from ``segment.related`` filtered to
  ids present in the accepted set, dangling references dropped (Req 4.4),
* byte-identical output for equal inputs (Req 4.5).

The renderer treats the segment read-only and performs no I/O.
"""

from __future__ import annotations

import pytest

from docuharnessx.ontology import (
    InMemorySegmentStore,
    Segment,
    Subject,
    Vocabulary,
    default_profile,
    emit_tags,
)
from docuharnessx.assembler import pages
from docuharnessx.assembler.pages import page_filename, render_segment_page


# --------------------------------------------------------------------------- #
# Fixtures / builders                                                          #
# --------------------------------------------------------------------------- #


def _vocab() -> Vocabulary:
    return default_profile()


def _segment(
    *,
    seg_id: str = "install-guide",
    title: str = "Install Guide",
    roles: list[str] | None = None,
    subjects: list[Subject] | None = None,
    intent: str = "install",
    summary: str = "How to install.",
    related: list[str] | None = None,
    body: str = "Run the installer.\n\nThen configure it.\n",
) -> Segment:
    return Segment(
        id=seg_id,
        title=title,
        roles=["developer"] if roles is None else roles,
        subjects=(
            [Subject(prefix="component", local="installer")]
            if subjects is None
            else subjects
        ),
        intent=intent,
        summary=summary,
        related=[] if related is None else related,
        body=body,
    )


# --------------------------------------------------------------------------- #
# Package surface                                                              #
# --------------------------------------------------------------------------- #


def test_renderer_symbols_importable_from_submodule() -> None:
    assert callable(page_filename)
    assert callable(render_segment_page)
    assert "page_filename" in pages.__all__
    assert "render_segment_page" in pages.__all__


# --------------------------------------------------------------------------- #
# page_filename: stable, deterministic, filesystem-safe (Req 4.1)             #
# --------------------------------------------------------------------------- #


def test_page_filename_ends_with_md() -> None:
    assert page_filename("install-guide").endswith(".md")


def test_page_filename_is_deterministic() -> None:
    assert page_filename("install-guide") == page_filename("install-guide")


def test_page_filename_is_filesystem_safe() -> None:
    # No path separators or unsafe characters in the emitted filename.
    name = page_filename("Group/Sub Section: Weird*Name?")
    base = name[:-3]  # strip ".md"
    assert "/" not in name
    assert "\\" not in name
    for ch in base:
        assert ch.isalnum() or ch in ("-", "_"), ch


def test_page_filename_distinct_for_distinct_ids() -> None:
    assert page_filename("alpha") != page_filename("beta")


def test_page_filename_nonempty_for_pathological_id() -> None:
    # An id that slugifies to empty must still yield a usable, deterministic name.
    name = page_filename("///")
    assert name.endswith(".md")
    assert len(name) > len(".md")
    assert name == page_filename("///")


def test_page_filename_distinguishes_ids_that_share_a_slug() -> None:
    # Two ids that would collapse to the same slug must not collide.
    assert page_filename("a b") != page_filename("a-b-")


# --------------------------------------------------------------------------- #
# render_segment_page: return shape                                            #
# --------------------------------------------------------------------------- #


def test_render_returns_path_and_content() -> None:
    rel_path, content = render_segment_page(_segment(), _vocab(), frozenset())
    assert isinstance(rel_path, str)
    assert isinstance(content, str)
    assert rel_path == page_filename("install-guide")


# --------------------------------------------------------------------------- #
# Frontmatter tags equal emit_tags (Req 4.3)                                   #
# --------------------------------------------------------------------------- #


def test_frontmatter_tags_equal_emit_tags() -> None:
    seg = _segment(
        roles=["developer", "manager"],
        subjects=[
            Subject(prefix="component", local="installer"),
            Subject(prefix="tech", local="python"),
        ],
        intent="install",
    )
    vocab = _vocab()
    _, content = render_segment_page(seg, vocab, frozenset())

    expected = list(emit_tags(seg, vocab))
    assert expected, "fixture should emit at least one tag"

    # The page begins with a YAML frontmatter fence carrying a tags list.
    assert content.startswith("---\n")
    import yaml

    block = content.split("---\n", 2)[1]
    fm = yaml.safe_load(block)
    assert fm["tags"] == expected


def test_frontmatter_tags_empty_when_no_vocab_match() -> None:
    # A segment whose axis values are not vocabulary members emits no tags;
    # the frontmatter tags list is then empty (still equals emit_tags()).
    seg = _segment(roles=["not-a-role"], subjects=[], intent="not-an-intent")
    vocab = _vocab()
    _, content = render_segment_page(seg, vocab, frozenset())
    import yaml

    block = content.split("---\n", 2)[1]
    fm = yaml.safe_load(block)
    assert fm["tags"] == list(emit_tags(seg, vocab)) == []


# --------------------------------------------------------------------------- #
# Title heading + body preserved verbatim (Req 4.2)                            #
# --------------------------------------------------------------------------- #


def test_title_rendered_as_heading() -> None:
    seg = _segment(title="My Install Guide")
    _, content = render_segment_page(seg, _vocab(), frozenset())
    assert "# My Install Guide" in content


def test_body_preserved_verbatim() -> None:
    body = "Line one.\n\n```python\nprint('x')\n```\n\nLine two.\n"
    seg = _segment(body=body)
    _, content = render_segment_page(seg, _vocab(), frozenset())
    assert body in content


def test_empty_body_does_not_crash() -> None:
    seg = _segment(body="")
    _, content = render_segment_page(seg, _vocab(), frozenset())
    assert "# Install Guide" in content


# --------------------------------------------------------------------------- #
# Related cross-links, dangling dropped (Req 4.4)                              #
# --------------------------------------------------------------------------- #


def test_related_links_render_for_accepted_targets() -> None:
    seg = _segment(seg_id="a", related=["b", "c"])
    accepted = frozenset({"a", "b", "c"})
    _, content = render_segment_page(seg, _vocab(), accepted)
    # Each accepted related id is rendered as a Markdown link to its page file.
    assert f"]({page_filename('b')})" in content
    assert f"]({page_filename('c')})" in content


def test_dangling_related_links_dropped() -> None:
    seg = _segment(seg_id="a", related=["b", "ghost"])
    accepted = frozenset({"a", "b"})  # "ghost" is not accepted
    _, content = render_segment_page(seg, _vocab(), accepted)
    assert f"]({page_filename('b')})" in content
    assert "ghost" not in content
    assert f"({page_filename('ghost')})" not in content


def test_self_reference_in_related_dropped() -> None:
    # A segment must not link to itself even if it is in the accepted set.
    seg = _segment(seg_id="a", related=["a", "b"])
    accepted = frozenset({"a", "b"})
    _, content = render_segment_page(seg, _vocab(), accepted)
    assert f"]({page_filename('b')})" in content
    assert f"]({page_filename('a')})" not in content


def test_no_related_section_when_all_dangling() -> None:
    seg = _segment(seg_id="a", related=["ghost1", "ghost2"])
    accepted = frozenset({"a"})
    _, content = render_segment_page(seg, _vocab(), accepted)
    # No related links rendered at all.
    assert "ghost1" not in content
    assert "ghost2" not in content


def test_no_related_section_when_related_empty() -> None:
    seg = _segment(seg_id="a", related=[])
    _, content = render_segment_page(seg, _vocab(), frozenset({"a"}))
    assert "](" not in content or "# Install Guide" in content


def test_related_links_deterministic_order() -> None:
    # Related links preserve the segment's declared related order.
    seg = _segment(seg_id="a", related=["c", "b"])
    accepted = frozenset({"a", "b", "c"})
    _, content = render_segment_page(seg, _vocab(), accepted)
    assert content.index(page_filename("c")) < content.index(page_filename("b"))


# --------------------------------------------------------------------------- #
# Determinism: byte-identical output for equal inputs (Req 4.5)                #
# --------------------------------------------------------------------------- #


def test_byte_identical_for_equal_inputs() -> None:
    seg1 = _segment(seg_id="a", related=["b"])
    seg2 = _segment(seg_id="a", related=["b"])
    accepted = frozenset({"a", "b"})
    out1 = render_segment_page(seg1, _vocab(), accepted)
    out2 = render_segment_page(seg2, _vocab(), accepted)
    assert out1 == out2


def test_accepted_ids_iteration_order_does_not_change_output() -> None:
    # accepted_ids is a set; membership-only use must keep output stable
    # regardless of any incidental iteration order.
    seg = _segment(seg_id="a", related=["b", "c", "d"])
    a = render_segment_page(seg, _vocab(), frozenset({"a", "b", "c", "d"}))
    b = render_segment_page(seg, _vocab(), frozenset(["d", "c", "b", "a"]))
    assert a == b


# --------------------------------------------------------------------------- #
# Read-only over the segment                                                   #
# --------------------------------------------------------------------------- #


def test_segment_not_mutated() -> None:
    seg = _segment(seg_id="a", roles=["developer"], related=["b"])
    before_roles = list(seg.roles)
    before_related = list(seg.related)
    before_body = seg.body
    render_segment_page(seg, _vocab(), frozenset({"a", "b"}))
    assert seg.roles == before_roles
    assert seg.related == before_related
    assert seg.body == before_body


def test_store_reuse_does_not_affect_rendering() -> None:
    # Sanity: rendering does not depend on or touch a SegmentStore.
    store = InMemorySegmentStore(_vocab())
    seg = _segment()
    store.put(seg)
    rel1, c1 = render_segment_page(seg, _vocab(), frozenset({seg.id}))
    rel2, c2 = render_segment_page(seg, _vocab(), frozenset({seg.id}))
    assert (rel1, c1) == (rel2, c2)


# --------------------------------------------------------------------------- #
# Trailing-newline / well-formed Markdown invariants                           #
# --------------------------------------------------------------------------- #


def test_page_ends_with_single_trailing_newline() -> None:
    _, content = render_segment_page(_segment(), _vocab(), frozenset())
    assert content.endswith("\n")
    assert not content.endswith("\n\n\n")


def test_frontmatter_is_first_thing_in_file() -> None:
    _, content = render_segment_page(_segment(), _vocab(), frozenset())
    assert content.startswith("---\n")
    # The frontmatter block closes before the heading.
    fm_close = content.index("\n---\n")
    heading = content.index("# Install Guide")
    assert fm_close < heading
