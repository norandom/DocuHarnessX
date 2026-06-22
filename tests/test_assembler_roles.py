"""Unit tests for the per-role landing-page renderer (mkdocs-site-assembler task 3.2).

These tests pin the *Role landing page renderer* boundary (design "Role landing page
renderer", ``assembler/roles.py``). The renderer, for one role term, an accepted-segment
store, the loaded vocabulary, and the list of all emitted role pages, derives the role's
segment view through the ontology ``build_role_view`` API (intent-ordered) and renders a
landing page:

* a COBESY SCQA-style opener using the role's display ``label`` and ``description`` from
  the loaded vocabulary (never a hardcoded role name) (Req 5.3, 5.6);
* the agenda as ordered links to the per-segment pages — intent order via
  ``build_role_view`` — with no body duplication (Req 5.2, 5.4);
* a role-switching affordance (Material content-tabs or an admonition) listing the other
  available role landing pages (Req 6.3).

Observable completion (tasks.md 3.2): the agenda order equals the role-view (intent)
order; the opener uses the vocabulary label/description; a renamed/reordered custom
vocabulary changes the rendered page with no code change; the role-switch affordance
lists the other roles.

Task 3.2 owns only the role landing-page renderer — not the segment page renderer (3.1),
the mkdocs.yml builder (3.3), the writer (4.1), or the stage adapter (5.x).
"""

from __future__ import annotations

import pytest

from docuharnessx.assembler import roles as roles_mod
from docuharnessx.assembler.pages import page_filename
from docuharnessx.assembler.roles import render_role_landing_page, role_page_path
from docuharnessx.ontology import (
    AxisTerm,
    InMemorySegmentStore,
    Segment,
    Subject,
    Vocabulary,
    build_role_view,
    default_profile,
)


# --------------------------------------------------------------------------- #
# Builders                                                                     #
# --------------------------------------------------------------------------- #


def _segment(
    seg_id: str,
    *,
    title: str,
    roles: list[str],
    intent: str,
    summary: str = "",
    prefixes: tuple[str, ...] = ("component:", "tech:", "artifact:", "topic:"),
    subject_local: str = "core",
) -> Segment:
    return Segment(
        id=seg_id,
        title=title,
        roles=roles,
        subjects=[Subject.parse(f"topic:{subject_local}", frozenset(prefixes))],
        intent=intent,
        summary=summary,
        body=f"Body of {seg_id}.",
    )


def _store(vocab: Vocabulary, *segments: Segment) -> InMemorySegmentStore:
    store = InMemorySegmentStore(vocab)
    for seg in segments:
        store.put(seg)
    return store


def _role(vocab: Vocabulary, role_id: str) -> AxisTerm:
    for term in vocab.roles:
        if term.id == role_id:
            return term
    raise AssertionError(f"role {role_id!r} not in vocabulary")


# A small custom vocabulary to prove configurability (no hardcoded roles/intents).
_CUSTOM_VOCAB = Vocabulary(
    roles=(
        AxisTerm("operator", "Site Operator", "Runs the thing in production."),
        AxisTerm("auditor", "Compliance Auditor", "Checks the controls."),
    ),
    intents=(
        AxisTerm("first", "First Step", "Do this first."),
        AxisTerm("second", "Second Step", "Then this."),
        AxisTerm("third", "Third Step", "Finally this."),
    ),
    subject_prefixes=("component:", "topic:"),
)


# --------------------------------------------------------------------------- #
# Module surface                                                               #
# --------------------------------------------------------------------------- #


def test_module_exports_contract() -> None:
    assert "render_role_landing_page" in roles_mod.__all__
    assert "role_page_path" in roles_mod.__all__
    for name in roles_mod.__all__:
        assert hasattr(roles_mod, name), name
    assert len(roles_mod.__all__) == len(set(roles_mod.__all__))


def test_role_page_path_is_role_index_under_role_dir() -> None:
    # Per design: docs/<role>/index.md ; filesystem-safe, deterministic.
    assert role_page_path("developer") == "developer/index.md"
    assert role_page_path("security-compliance-officer") == (
        "security-compliance-officer/index.md"
    )


def test_role_page_path_is_filesystem_safe() -> None:
    # An id with unsafe characters is slugified to a single safe path segment.
    path = role_page_path("Weird/Role Id..")
    assert ".." not in path.split("/")
    assert path.endswith("/index.md")
    # exactly one directory segment + index.md
    assert path.count("/") == 1


def test_role_page_path_is_deterministic() -> None:
    assert role_page_path("developer") == role_page_path("developer")


# --------------------------------------------------------------------------- #
# Return shape                                                                 #
# --------------------------------------------------------------------------- #


def test_returns_relative_path_and_markdown() -> None:
    vocab = default_profile()
    seg = _segment("s1", title="Install Guide", roles=["developer"], intent="install")
    store = _store(vocab, seg)
    rel_path, content = render_role_landing_page(
        _role(vocab, "developer"), store, vocab, (("Developer", "developer/index.md"),)
    )
    assert rel_path == "developer/index.md"
    assert isinstance(content, str)
    assert content


# --------------------------------------------------------------------------- #
# SCQA opener uses the vocabulary label + description (Req 5.3, 5.6)           #
# --------------------------------------------------------------------------- #


def test_opener_uses_vocabulary_label_and_description() -> None:
    vocab = default_profile()
    role = _role(vocab, "developer")
    seg = _segment("s1", title="Install", roles=["developer"], intent="install")
    store = _store(vocab, seg)
    _, content = render_role_landing_page(
        role, store, vocab, (("Developer", "developer/index.md"),)
    )
    assert role.label in content
    assert role.description in content
    # The H1 is the role label, not the machine id.
    assert content.lstrip().startswith(f"# {role.label}")
    assert role.id not in content.splitlines()[0]


def test_opener_does_not_hardcode_role_name() -> None:
    # The custom role label/description appear verbatim; no hardcoded default label leaks.
    role = _role(_CUSTOM_VOCAB, "operator")
    seg = _segment(
        "x1",
        title="Boot It",
        roles=["operator"],
        intent="first",
        prefixes=("component:", "topic:"),
    )
    store = _store(_CUSTOM_VOCAB, seg)
    _, content = render_role_landing_page(
        role,
        store,
        _CUSTOM_VOCAB,
        (("Site Operator", "operator/index.md"),),
    )
    assert "Site Operator" in content
    assert "Runs the thing in production." in content
    # No leakage of unrelated default-profile role labels.
    assert "Possible Adopter" not in content


def test_opener_has_scqa_structure() -> None:
    vocab = default_profile()
    role = _role(vocab, "developer")
    seg = _segment("s1", title="Install", roles=["developer"], intent="install")
    store = _store(vocab, seg)
    _, content = render_role_landing_page(
        role, store, vocab, (("Developer", "developer/index.md"),)
    )
    lower = content.lower()
    # The four SCQA beats are present as an opener structure.
    for beat in ("situation", "complication", "question", "answer"):
        assert beat in lower, beat


# --------------------------------------------------------------------------- #
# Agenda order == build_role_view (intent) order (Req 5.2, 5.4)               #
# --------------------------------------------------------------------------- #


def test_agenda_order_equals_role_view_intent_order() -> None:
    vocab = default_profile()
    role = _role(vocab, "developer")
    # Insert segments out of intent order; build_role_view must reorder by intent.
    seg_use = _segment("b-use", title="Use It", roles=["developer"], intent="use")
    seg_install = _segment(
        "a-install", title="Install It", roles=["developer"], intent="install"
    )
    seg_extend = _segment(
        "c-extend", title="Extend It", roles=["developer"], intent="extend"
    )
    store = _store(vocab, seg_use, seg_install, seg_extend)

    view = build_role_view(store, role.id, vocab)
    expected_titles = [s.title for s in view]
    # install < use < extend in the default intent order.
    assert expected_titles == ["Install It", "Use It", "Extend It"]

    _, content = render_role_landing_page(
        role, store, vocab, (("Developer", "developer/index.md"),)
    )

    # The order titles appear in agenda order matches the role view order.
    positions = [content.index(t) for t in expected_titles]
    assert positions == sorted(positions), (
        f"agenda not in role-view order: {expected_titles} -> {positions}"
    )


def test_agenda_links_to_per_segment_pages_without_body_duplication() -> None:
    vocab = default_profile()
    role = _role(vocab, "developer")
    seg = _segment(
        "install-guide",
        title="Install Guide",
        roles=["developer"],
        intent="install",
        summary="How to install.",
    )
    store = _store(vocab, seg)
    _, content = render_role_landing_page(
        role, store, vocab, (("Developer", "developer/index.md"),)
    )
    # A Markdown link to the per-segment page (one dir up from <role>/index.md),
    # using the per-segment renderer's own filename authority (pages.page_filename).
    expected_link = f"../{page_filename('install-guide')}"
    assert expected_link in content
    assert f"[Install Guide]({expected_link})" in content
    # The body is NOT duplicated onto the landing page.
    assert "Body of install-guide." not in content


def test_agenda_uses_segment_summary_when_present() -> None:
    vocab = default_profile()
    role = _role(vocab, "developer")
    seg = _segment(
        "s1",
        title="Title One",
        roles=["developer"],
        intent="install",
        summary="A crisp one-line summary.",
    )
    store = _store(vocab, seg)
    _, content = render_role_landing_page(
        role, store, vocab, (("Developer", "developer/index.md"),)
    )
    assert "A crisp one-line summary." in content


# --------------------------------------------------------------------------- #
# Configurable vocabulary: rename/reorder changes the page, no code change     #
# --------------------------------------------------------------------------- #


def test_reordered_custom_vocabulary_changes_agenda_order() -> None:
    role = _role(_CUSTOM_VOCAB, "operator")
    s_first = _segment(
        "p1", title="Page First", roles=["operator"], intent="first",
        prefixes=("component:", "topic:"),
    )
    s_third = _segment(
        "p3", title="Page Third", roles=["operator"], intent="third",
        prefixes=("component:", "topic:"),
    )
    store = _store(_CUSTOM_VOCAB, s_first, s_third)
    _, content = render_role_landing_page(
        role, store, _CUSTOM_VOCAB, (("Site Operator", "operator/index.md"),)
    )
    assert content.index("Page First") < content.index("Page Third")

    # Reverse the intent order in a new vocabulary: same code, different output.
    reversed_vocab = Vocabulary(
        roles=_CUSTOM_VOCAB.roles,
        intents=tuple(reversed(_CUSTOM_VOCAB.intents)),
        subject_prefixes=_CUSTOM_VOCAB.subject_prefixes,
    )
    role2 = _role(reversed_vocab, "operator")
    store2 = _store(reversed_vocab, s_first, s_third)
    _, content2 = render_role_landing_page(
        role2, store2, reversed_vocab, (("Site Operator", "operator/index.md"),)
    )
    assert content2.index("Page Third") < content2.index("Page First")


def test_renamed_role_label_changes_opener() -> None:
    base_vocab = _CUSTOM_VOCAB
    seg = _segment(
        "p1", title="Page", roles=["operator"], intent="first",
        prefixes=("component:", "topic:"),
    )
    _, content_a = render_role_landing_page(
        _role(base_vocab, "operator"),
        _store(base_vocab, seg),
        base_vocab,
        (("Site Operator", "operator/index.md"),),
    )
    renamed = Vocabulary(
        roles=(
            AxisTerm("operator", "Platform Operator", "Operates the platform."),
            base_vocab.roles[1],
        ),
        intents=base_vocab.intents,
        subject_prefixes=base_vocab.subject_prefixes,
    )
    _, content_b = render_role_landing_page(
        _role(renamed, "operator"),
        _store(renamed, seg),
        renamed,
        (("Platform Operator", "operator/index.md"),),
    )
    assert "Site Operator" in content_a
    assert "Platform Operator" in content_b
    assert content_a != content_b


# --------------------------------------------------------------------------- #
# Role-switching affordance lists the OTHER role pages (Req 6.3)               #
# --------------------------------------------------------------------------- #


def test_role_switch_affordance_lists_other_roles() -> None:
    vocab = default_profile()
    role = _role(vocab, "developer")
    seg = _segment("s1", title="Install", roles=["developer"], intent="install")
    store = _store(vocab, seg)
    all_role_pages = (
        ("Developer", "developer/index.md"),
        ("Manager", "manager/index.md"),
        ("DevOps/Admin", "devops-admin/index.md"),
    )
    _, content = render_role_landing_page(role, store, vocab, all_role_pages)
    # Other role labels are present as switch targets...
    assert "Manager" in content
    assert "DevOps/Admin" in content
    # ...and link to their landing pages (one dir up, then into the role dir).
    assert "../manager/index.md" in content
    assert "../devops-admin/index.md" in content


def test_role_switch_excludes_the_current_role_link() -> None:
    vocab = default_profile()
    role = _role(vocab, "developer")
    seg = _segment("s1", title="Install", roles=["developer"], intent="install")
    store = _store(vocab, seg)
    all_role_pages = (
        ("Developer", "developer/index.md"),
        ("Manager", "manager/index.md"),
    )
    _, content = render_role_landing_page(role, store, vocab, all_role_pages)
    # The current role's own landing page is not offered as a switch link.
    assert "../developer/index.md" not in content
    assert "../manager/index.md" in content


def test_role_switch_uses_material_affordance() -> None:
    vocab = default_profile()
    role = _role(vocab, "developer")
    seg = _segment("s1", title="Install", roles=["developer"], intent="install")
    store = _store(vocab, seg)
    _, content = render_role_landing_page(
        role,
        store,
        vocab,
        (("Developer", "developer/index.md"), ("Manager", "manager/index.md")),
    )
    # Material content-tabs ("===") or an admonition ("!!!"/"???") affordance.
    assert ('=== "' in content) or ("!!!" in content) or ("???" in content)


def test_single_role_site_still_renders_without_switch_targets() -> None:
    vocab = default_profile()
    role = _role(vocab, "developer")
    seg = _segment("s1", title="Install", roles=["developer"], intent="install")
    store = _store(vocab, seg)
    # Only this role page exists -> no other roles to switch to; must not raise.
    rel, content = render_role_landing_page(
        role, store, vocab, (("Developer", "developer/index.md"),)
    )
    assert rel == "developer/index.md"
    assert "../developer/index.md" not in content


# --------------------------------------------------------------------------- #
# Determinism (Req 8.2-style byte stability for equal inputs)                  #
# --------------------------------------------------------------------------- #


def test_byte_stable_for_equal_inputs() -> None:
    vocab = default_profile()
    role = _role(vocab, "developer")
    segs = [
        _segment("a", title="A", roles=["developer"], intent="install"),
        _segment("b", title="B", roles=["developer"], intent="use"),
    ]
    all_role_pages = (
        ("Developer", "developer/index.md"),
        ("Manager", "manager/index.md"),
    )
    _, c1 = render_role_landing_page(role, _store(vocab, *segs), vocab, all_role_pages)
    _, c2 = render_role_landing_page(role, _store(vocab, *segs), vocab, all_role_pages)
    assert c1 == c2


def test_does_not_mutate_segments() -> None:
    vocab = default_profile()
    role = _role(vocab, "developer")
    seg = _segment("s1", title="Install", roles=["developer"], intent="install")
    before = (seg.id, seg.title, tuple(seg.roles), seg.intent, seg.body, seg.summary)
    store = _store(vocab, seg)
    render_role_landing_page(role, store, vocab, (("Developer", "developer/index.md"),))
    after = (seg.id, seg.title, tuple(seg.roles), seg.intent, seg.body, seg.summary)
    assert before == after
