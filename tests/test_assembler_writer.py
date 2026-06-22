"""Unit tests for the site writer (mkdocs-site-assembler task 4.1).

These tests pin the *Site writer* boundary (design "Site writer", ``assembler/writer.py``).
The writer, from the review report, the loaded vocabulary, the optional analysis, the output
directory, and the resolved identity:

* builds a fresh in-memory store from the accepted segments (so role-view agendas contain
  only accepted segments);
* renders one ``docs/*.md`` page per accepted segment (Req 4.1);
* renders a per-role landing page only for each vocabulary role that has at least one
  accepted segment, omitting empty roles, in vocabulary role order (Req 5.1, 5.5);
* builds a tags index page carrying the Material listing directive (Req 6.2);
* builds the ``mkdocs.yml`` (Req 6.1, 6.4);
* writes the whole tree under ``<out_dir>/site/`` (Req 8.5);
* returns the frozen :class:`AssembledSite` with the correct page and role-page counts
  (Req 7.1);
* performs no model call and no network access; tolerates an absent analysis (Req 2.5, 8.1).

Observable completion (tasks.md 4.1): a unit test over a seeded accepted set produces one
page per accepted segment, one landing page per role that has content (and none for empty
roles), a tags index, and a ``mkdocs.yml`` under the output dir, returning an AssembledSite
with matching counts; an absent analysis still produces a site; two runs over equal inputs
produce byte-identical trees.

Task 4.1 owns only the site writer — not the renderers (3.x), the identity resolver (2.x),
or the stage adapter (5.x).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from docuharnessx.assembler import writer as writer_mod
from docuharnessx.assembler.mkdocs_config import TAGS_INDEX_PATH
from docuharnessx.assembler.model import (
    ASSEMBLED_SITE_SCHEMA_VERSION,
    AssembledSite,
    SiteIdentity,
)
from docuharnessx.assembler.pages import page_filename
from docuharnessx.assembler.roles import role_page_path
from docuharnessx.assembler.writer import assemble_site
from docuharnessx.ontology import (
    AxisTerm,
    Segment,
    Subject,
    Vocabulary,
    default_profile,
)
from docuharnessx.review.model import (
    REVIEW_REPORT_SCHEMA_VERSION,
    ReviewAggregate,
    ReviewReport,
)


# --------------------------------------------------------------------------- #
# Builders / fixtures                                                          #
# --------------------------------------------------------------------------- #


def _segment(
    seg_id: str,
    *,
    title: str,
    roles: list[str],
    intent: str,
    summary: str = "",
    related: list[str] | None = None,
    prefixes: tuple[str, ...] = ("component:", "tech:", "artifact:", "topic:"),
    body: str | None = None,
) -> Segment:
    return Segment(
        id=seg_id,
        title=title,
        roles=roles,
        subjects=[Subject.parse(f"topic:{seg_id}", frozenset(prefixes))],
        intent=intent,
        summary=summary,
        related=list(related or []),
        body=f"Body of {seg_id}." if body is None else body,
    )


def _report(*accepted: Segment) -> ReviewReport:
    """A ReviewReport carrying only the accepted set the writer consumes (verbatim)."""
    return ReviewReport(
        schema_version=REVIEW_REPORT_SCHEMA_VERSION,
        entries=(),
        accepted=tuple(accepted),
        aggregate=ReviewAggregate(
            judged=len(accepted),
            accepted=len(accepted),
            rejected=0,
            unavailable=0,
            criterion_tally=(),
        ),
    )


def _identity() -> SiteIdentity:
    return SiteIdentity(
        site_name="malware_hashes",
        repo_name="norandom/malware_hashes",
        repo_url="https://github.com/norandom/malware_hashes",
        site_url="https://norandom.github.io/malware_hashes/",
        base_path="/malware_hashes/",
        edit_uri="edit/main/docs/",
    )


_CUSTOM_VOCAB = Vocabulary(
    roles=(
        AxisTerm("operator", "Site Operator", "Runs the thing in production."),
        AxisTerm("auditor", "Compliance Auditor", "Checks the controls."),
    ),
    intents=(
        AxisTerm("first", "First Step", "Do this first."),
        AxisTerm("second", "Second Step", "Then this."),
    ),
    subject_prefixes=("component:", "topic:"),
)


def _seeded_report() -> ReviewReport:
    """Three accepted segments across two of the default roles; one role left empty."""
    return _report(
        _segment(
            "install-guide",
            title="Install Guide",
            roles=["developer"],
            intent="install",
            summary="How to install.",
        ),
        _segment(
            "deploy-guide",
            title="Deploy Guide",
            roles=["devops-admin"],
            intent="configure",
            summary="How to deploy.",
        ),
        _segment(
            "use-guide",
            title="Use Guide",
            roles=["developer"],
            intent="use",
            summary="How to use.",
        ),
    )


# --------------------------------------------------------------------------- #
# Module surface                                                              #
# --------------------------------------------------------------------------- #


def test_module_exports_contract() -> None:
    assert "assemble_site" in writer_mod.__all__
    for name in writer_mod.__all__:
        assert hasattr(writer_mod, name), name
    assert len(writer_mod.__all__) == len(set(writer_mod.__all__))


def test_assemble_site_exported_from_package() -> None:
    import docuharnessx.assembler as pkg

    assert "assemble_site" in pkg.__all__
    assert pkg.assemble_site is assemble_site


# --------------------------------------------------------------------------- #
# Returns a well-formed AssembledSite (Req 7.1)                                #
# --------------------------------------------------------------------------- #


def test_returns_assembled_site_with_absolute_paths(tmp_path: Path) -> None:
    site = assemble_site(
        _seeded_report(), default_profile(), None, str(tmp_path), _identity()
    )
    assert isinstance(site, AssembledSite)
    assert site.schema_version == ASSEMBLED_SITE_SCHEMA_VERSION
    assert os.path.isabs(site.site_dir)
    assert os.path.isabs(site.docs_dir)
    assert os.path.isabs(site.mkdocs_yml_path)
    assert site.identity == _identity()


def test_site_layout_under_output_dir(tmp_path: Path) -> None:
    site = assemble_site(
        _seeded_report(), default_profile(), None, str(tmp_path), _identity()
    )
    site_root = tmp_path / "site"
    assert Path(site.site_dir) == site_root
    assert Path(site.docs_dir) == site_root / "docs"
    assert Path(site.mkdocs_yml_path) == site_root / "mkdocs.yml"
    assert Path(site.mkdocs_yml_path).is_file()
    assert Path(site.docs_dir).is_dir()


# --------------------------------------------------------------------------- #
# One page per accepted segment (Req 4.1)                                      #
# --------------------------------------------------------------------------- #


def test_one_page_per_accepted_segment(tmp_path: Path) -> None:
    report = _seeded_report()
    site = assemble_site(report, default_profile(), None, str(tmp_path), _identity())
    docs = Path(site.docs_dir)
    assert site.page_count == len(report.accepted)
    for seg in report.accepted:
        page = docs / page_filename(seg.id)
        assert page.is_file(), page
        text = page.read_text(encoding="utf-8")
        assert f"# {seg.title}" in text


def test_page_count_matches_accepted_count(tmp_path: Path) -> None:
    report = _seeded_report()
    site = assemble_site(report, default_profile(), None, str(tmp_path), _identity())
    # Count only the per-segment pages (exclude role index pages + tags index).
    docs = Path(site.docs_dir)
    top_level_md = [
        p for p in docs.glob("*.md") if p.name != TAGS_INDEX_PATH
    ]
    assert len(top_level_md) == len(report.accepted) == site.page_count


# --------------------------------------------------------------------------- #
# One landing page per non-empty role; none for empty roles (Req 5.1, 5.5)     #
# --------------------------------------------------------------------------- #


def test_landing_page_per_non_empty_role_only(tmp_path: Path) -> None:
    report = _seeded_report()
    vocab = default_profile()
    site = assemble_site(report, vocab, None, str(tmp_path), _identity())
    docs = Path(site.docs_dir)

    # developer + devops-admin have accepted segments -> landing pages exist.
    assert (docs / role_page_path("developer")).is_file()
    assert (docs / role_page_path("devops-admin")).is_file()
    # A role with no accepted segment (e.g. manager) -> no landing page.
    assert not (docs / role_page_path("manager")).exists()

    # Exactly two roles carry content here.
    assert site.role_page_count == 2


def test_role_pages_in_vocabulary_order(tmp_path: Path) -> None:
    report = _seeded_report()
    vocab = default_profile()
    site = assemble_site(report, vocab, None, str(tmp_path), _identity())
    mkdocs_yml = Path(site.mkdocs_yml_path).read_text(encoding="utf-8")
    # developer precedes devops-admin in the default vocabulary role order, so its nav
    # entry must precede devops-admin's.
    assert mkdocs_yml.index("developer/index.md") < mkdocs_yml.index(
        "devops-admin/index.md"
    )


def test_no_role_pages_when_no_accepted_segments(tmp_path: Path) -> None:
    site = assemble_site(_report(), default_profile(), None, str(tmp_path), _identity())
    assert site.page_count == 0
    assert site.role_page_count == 0
    # Still a buildable site: mkdocs.yml + tags index exist.
    assert Path(site.mkdocs_yml_path).is_file()
    assert (Path(site.docs_dir) / TAGS_INDEX_PATH).is_file()


# --------------------------------------------------------------------------- #
# Tags index page (Req 6.2)                                                    #
# --------------------------------------------------------------------------- #


def test_tags_index_page_with_listing_directive(tmp_path: Path) -> None:
    site = assemble_site(
        _seeded_report(), default_profile(), None, str(tmp_path), _identity()
    )
    tags_page = Path(site.docs_dir) / TAGS_INDEX_PATH
    assert tags_page.is_file()
    content = tags_page.read_text(encoding="utf-8")
    # The Material tags plugin discovers this listing directive.
    assert "<!-- material/tags -->" in content


# --------------------------------------------------------------------------- #
# mkdocs.yml is built and carries the per-target identity (Req 6.1, 6.4)       #
# --------------------------------------------------------------------------- #


def test_mkdocs_yml_carries_identity_and_theme(tmp_path: Path) -> None:
    ident = _identity()
    site = assemble_site(_seeded_report(), default_profile(), None, str(tmp_path), ident)
    yml = Path(site.mkdocs_yml_path).read_text(encoding="utf-8")
    assert ident.site_name in yml
    assert ident.site_url in yml
    assert "material" in yml
    assert TAGS_INDEX_PATH in yml


# --------------------------------------------------------------------------- #
# Absent analysis still produces a site (Req 2.5)                              #
# --------------------------------------------------------------------------- #


def test_absent_analysis_still_produces_site(tmp_path: Path) -> None:
    # analysis=None must not raise; the writer is the deterministic transform.
    site = assemble_site(
        _seeded_report(), default_profile(), None, str(tmp_path), _identity()
    )
    assert isinstance(site, AssembledSite)
    assert site.page_count == 3


# --------------------------------------------------------------------------- #
# Configurable vocabulary: custom roles flow through, no code change (Req 5.6) #
# --------------------------------------------------------------------------- #


def test_custom_vocabulary_role_pages(tmp_path: Path) -> None:
    report = _report(
        _segment(
            "boot-it",
            title="Boot It",
            roles=["operator"],
            intent="first",
            prefixes=("component:", "topic:"),
        ),
    )
    site = assemble_site(report, _CUSTOM_VOCAB, None, str(tmp_path), _identity())
    docs = Path(site.docs_dir)
    assert (docs / role_page_path("operator")).is_file()
    # The auditor role carries no accepted segment -> no landing page.
    assert not (docs / role_page_path("auditor")).exists()
    assert site.role_page_count == 1
    content = (docs / role_page_path("operator")).read_text(encoding="utf-8")
    assert "Site Operator" in content


# --------------------------------------------------------------------------- #
# Determinism / byte-stability (Req 8.2)                                       #
# --------------------------------------------------------------------------- #


def _read_tree(site_dir: Path) -> dict[str, bytes]:
    """Return a {relative-posix-path: bytes} map of every file under ``site_dir``."""
    out: dict[str, bytes] = {}
    for path in sorted(site_dir.rglob("*")):
        if path.is_file():
            rel = path.relative_to(site_dir).as_posix()
            out[rel] = path.read_bytes()
    return out


def test_two_runs_produce_byte_identical_trees(tmp_path: Path) -> None:
    report = _seeded_report()
    vocab = default_profile()
    ident = _identity()

    a_out = tmp_path / "a"
    b_out = tmp_path / "b"
    a_out.mkdir()
    b_out.mkdir()

    site_a = assemble_site(report, vocab, None, str(a_out), ident)
    # A distinct, equal report instance to prove order/identity independence.
    site_b = assemble_site(_seeded_report(), vocab, None, str(b_out), ident)

    tree_a = _read_tree(Path(site_a.site_dir))
    tree_b = _read_tree(Path(site_b.site_dir))
    assert tree_a.keys() == tree_b.keys()
    assert tree_a == tree_b


def test_returns_equal_assembled_site_for_equal_inputs(tmp_path: Path) -> None:
    out = tmp_path / "site_in"
    out.mkdir()
    ident = _identity()
    site_a = assemble_site(_seeded_report(), default_profile(), None, str(out), ident)
    # Re-running into the SAME dir must yield an equal AssembledSite (idempotent layout).
    # (Pages overwrite deterministically; the writer must tolerate a pre-existing tree.)
    site_b = assemble_site(_seeded_report(), default_profile(), None, str(out), ident)
    assert site_a == site_b


# --------------------------------------------------------------------------- #
# Isolation: only writes under the output dir (Req 8.5)                        #
# --------------------------------------------------------------------------- #


def test_only_writes_under_output_dir(tmp_path: Path) -> None:
    out = tmp_path / "out"
    out.mkdir()
    site = assemble_site(_seeded_report(), default_profile(), None, str(out), _identity())
    # Every emitted path is under <out>/site.
    site_root = Path(site.site_dir)
    assert site_root == out / "site"
    for path in site_root.rglob("*"):
        assert out in path.parents or path == site_root


def test_creates_output_dir_when_missing(tmp_path: Path) -> None:
    # The writer creates <out>/site (and docs/) even when <out> does not yet exist.
    out = tmp_path / "does-not-exist-yet"
    site = assemble_site(_seeded_report(), default_profile(), None, str(out), _identity())
    assert Path(site.site_dir).is_dir()
    assert Path(site.docs_dir).is_dir()


# --------------------------------------------------------------------------- #
# Read-only over the accepted segments (Req 2.2)                               #
# --------------------------------------------------------------------------- #


def test_does_not_mutate_accepted_segments(tmp_path: Path) -> None:
    report = _seeded_report()
    before = [
        (s.id, s.title, tuple(s.roles), s.intent, s.body, s.summary, tuple(s.related))
        for s in report.accepted
    ]
    assemble_site(report, default_profile(), None, str(tmp_path), _identity())
    after = [
        (s.id, s.title, tuple(s.roles), s.intent, s.body, s.summary, tuple(s.related))
        for s in report.accepted
    ]
    assert before == after


# --------------------------------------------------------------------------- #
# Related cross-links resolve only to accepted pages (Req 4.4 via the writer)  #
# --------------------------------------------------------------------------- #


def test_related_links_filtered_to_accepted_set(tmp_path: Path) -> None:
    # seg-a relates to seg-b (accepted) and to a dangling id (not accepted).
    seg_a = _segment(
        "seg-a",
        title="A",
        roles=["developer"],
        intent="install",
        related=["seg-b", "ghost"],
    )
    seg_b = _segment("seg-b", title="B", roles=["developer"], intent="use")
    report = _report(seg_a, seg_b)
    site = assemble_site(report, default_profile(), None, str(tmp_path), _identity())
    page_a = (Path(site.docs_dir) / page_filename("seg-a")).read_text(encoding="utf-8")
    assert page_filename("seg-b") in page_a
    # The dangling reference produces no link.
    assert page_filename("ghost") not in page_a


# --------------------------------------------------------------------------- #
# The emitted tree builds cleanly under mkdocs-material (Req 8.4 smoke test)    #
# --------------------------------------------------------------------------- #


def test_emitted_tree_builds_under_mkdocs_material_strict(tmp_path: Path) -> None:
    # Req 8.4: the full writer-emitted tree (segment pages, role landing pages with
    # role-switch links + agenda links, tags index, mkdocs.yml) builds cleanly under
    # mkdocs-material in --strict mode with the per-target base-path. (The full
    # vocabulary/remote build matrix is task 6.2; this is a focused smoke test of the
    # writer's own output.)
    pytest.importorskip("mkdocs")
    pytest.importorskip("material")

    out = tmp_path / "run"
    out.mkdir()
    site = assemble_site(_seeded_report(), default_profile(), None, str(out), _identity())

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "mkdocs",
            "build",
            "-f",
            site.mkdocs_yml_path,
            "-d",
            str(tmp_path / "_built"),
            "--strict",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"mkdocs build failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )
    # The per-target base-path is honored: a role landing page is emitted under its dir.
    assert (tmp_path / "_built" / "developer" / "index.html").exists()
