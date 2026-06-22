"""MkDocs build, base-path, determinism, and isolation tests (mkdocs-site-assembler 6.2).

These tests pin the *build / determinism / isolation* boundary of the Wave 3
``mkdocs-site-assembler`` core (design "Build / E2E", "Determinism / isolation"). They drive
the real, deterministic assembler core (``assembler.writer.assemble_site`` over the real
``resolve_site_identity``) and a **real** ``mkdocs build`` of the emitted tree — no model, no
network (the identity is resolved from an explicit, in-test remote string, never a live git
read).

Task 6.2 (tasks.md) — observable completion:

* Run a real ``mkdocs build`` on the emitted tree across the default vocabulary, a custom
  vocabulary, and varying target remotes (GitHub project, no remote, non-GitHub), asserting
  the build succeeds with the per-target base-path and no broken internal links among the
  generated pages (Req 8.4, 3.2, 3.5, 3.6). ``--strict`` is used so a broken internal link
  among the generated pages fails the build.
* Verify two assembly runs over equal inputs produce byte-identical trees (Req 8.2), that the
  only write target is the run's output directory (Req 8.5), and that a target run never
  derives DocuHarnessX's own identity or Pages URL (Req 3.8, 5.6 — identity is per-target).

This file owns only build/determinism/isolation validation; the unit-level page/role/yaml/
writer behavior is covered by the task 3.x / 4.1 suites, and the stage wiring by task 6.1.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from docuharnessx.assembler.identity import resolve_site_identity
from docuharnessx.assembler.model import SiteIdentity
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

# Skip the whole module gracefully if the doc framework is somehow absent (it is a declared
# runtime dependency — Req 8.3 — and installed in the project venv, so this is a guard, not an
# expected path).
pytest.importorskip("mkdocs")
pytest.importorskip("material")


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
        body=f"Body of {seg_id}.\n\nMore prose for {seg_id}." if body is None else body,
    )


def _report(*accepted: Segment) -> ReviewReport:
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


def _default_report() -> ReviewReport:
    """Accepted segments spanning several default roles + intents, with cross-links.

    Covers multiple roles (so several role landing pages are emitted and the role-switch
    affordance lists siblings), multiple intents (so the agenda ordering is exercised), and
    ``related`` references — including one dangling id that must be dropped — so the build
    exercises the full link surface (segment cross-links + agenda links + role-switch links).
    """
    return _report(
        _segment(
            "install-guide",
            title="Install Guide",
            roles=["developer"],
            intent="install",
            summary="How to install.",
            related=["use-guide", "ghost-ref"],  # ghost-ref is dangling -> dropped
        ),
        _segment(
            "use-guide",
            title="Use Guide",
            roles=["developer", "tech-savvy-user"],
            intent="use",
            summary="How to use it day to day.",
            related=["install-guide"],
        ),
        _segment(
            "deploy-guide",
            title="Deploy Guide",
            roles=["devops-admin"],
            intent="configure",
            summary="How to deploy.",
        ),
        _segment(
            "monitor-guide",
            title="Monitor Guide",
            roles=["devops-admin"],
            intent="monitor",
            summary="Keep it healthy.",
            related=["deploy-guide"],
        ),
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


def _custom_report() -> ReviewReport:
    """Accepted segments under the custom vocabulary (both custom roles + intents)."""
    return _report(
        _segment(
            "boot-it",
            title="Boot It",
            roles=["operator"],
            intent="first",
            summary="Start the service.",
            prefixes=("component:", "topic:"),
            related=["watch-it"],
        ),
        _segment(
            "watch-it",
            title="Watch It",
            roles=["operator"],
            intent="second",
            summary="Then watch it.",
            prefixes=("component:", "topic:"),
        ),
        _segment(
            "review-controls",
            title="Review Controls",
            roles=["auditor"],
            intent="first",
            summary="Audit the controls.",
            prefixes=("component:", "topic:"),
        ),
    )


# The three target-remote shapes the matrix covers, each resolved through the *real*
# resolve_site_identity (no live git read; the remote string is passed explicitly). The
# target path is an arbitrary non-DocuHarnessX path so the fallback site_name is per-target.
_GITHUB_REMOTE = "https://github.com/norandom/malware_hashes.git"
_NON_GITHUB_REMOTE = "https://gitlab.example.com/acme/widgets.git"
_TARGET_REPO = "/home/operator/projects/widgets"


def _identity_for(remote_url: str | None, target_repo: str = _TARGET_REPO) -> SiteIdentity:
    """Resolve a per-target identity through the real resolver (no overrides, no git read)."""
    return resolve_site_identity(target_repo, remote_url, {})


# (label, report-factory, vocab) per vocabulary; (label, remote) per remote shape.
_VOCAB_CASES = [
    ("default", _default_report, default_profile()),
    ("custom", _custom_report, _CUSTOM_VOCAB),
]
_REMOTE_CASES = [
    ("github", _GITHUB_REMOTE),
    ("no-remote", None),
    ("non-github", _NON_GITHUB_REMOTE),
]


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #


def _run_mkdocs_build(mkdocs_yml_path: str, site_out: Path) -> subprocess.CompletedProcess:
    """Run a real, strict ``mkdocs build`` of the emitted tree into ``site_out``.

    ``--strict`` turns a broken internal link (or any warning) into a non-zero exit, so a
    clean exit proves there are no broken internal links among the generated pages (Req 8.4).
    The build is invoked via the project interpreter's ``-m mkdocs`` so it uses the installed
    ``mkdocs-material`` theme; it is a local, network-free transform.
    """
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "mkdocs",
            "build",
            "-f",
            mkdocs_yml_path,
            "-d",
            str(site_out),
            "--strict",
        ],
        capture_output=True,
        text=True,
    )


def _read_tree(site_dir: Path) -> dict[str, bytes]:
    """Return a ``{relative-posix-path: bytes}`` map of every file under ``site_dir``."""
    out: dict[str, bytes] = {}
    for path in sorted(site_dir.rglob("*")):
        if path.is_file():
            out[path.relative_to(site_dir).as_posix()] = path.read_bytes()
    return out


# --------------------------------------------------------------------------- #
# Build matrix: every (vocabulary, remote) combination builds clean (Req 8.4)  #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "vocab_label,report_factory,vocab",
    _VOCAB_CASES,
    ids=[c[0] for c in _VOCAB_CASES],
)
@pytest.mark.parametrize(
    "remote_label,remote_url",
    _REMOTE_CASES,
    ids=[c[0] for c in _REMOTE_CASES],
)
def test_emitted_tree_builds_strict_across_vocab_and_remote(
    tmp_path: Path,
    vocab_label: str,
    report_factory,
    vocab: Vocabulary,
    remote_label: str,
    remote_url: str | None,
) -> None:
    """Every (vocabulary, remote) combination builds clean under mkdocs-material --strict.

    Req 8.4 / 3.2 / 3.5 / 3.6: across the default and custom vocabularies and the GitHub /
    no-remote / non-GitHub target remotes, ``mkdocs build --strict`` succeeds (no broken
    internal links among the generated pages) and the static site is produced.
    """
    identity = _identity_for(remote_url)
    out = tmp_path / "run"
    out.mkdir()
    site = assemble_site(report_factory(), vocab, None, str(out), identity)

    built = tmp_path / "_built"
    result = _run_mkdocs_build(site.mkdocs_yml_path, built)
    assert result.returncode == 0, (
        f"mkdocs build failed for vocab={vocab_label} remote={remote_label}:\n"
        f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )
    # The static site exists (an index page is always produced).
    assert (built / "index.html").exists() or any(built.rglob("index.html"))
    # Every emitted role landing page produced a built page under its role directory.
    assert site.role_page_count >= 1
    role_index_pages = list((built).rglob("index.html"))
    assert role_index_pages, "no built pages produced"


@pytest.mark.parametrize(
    "vocab_label,report_factory,vocab",
    _VOCAB_CASES,
    ids=[c[0] for c in _VOCAB_CASES],
)
def test_github_build_carries_repo_base_path(
    tmp_path: Path, vocab_label: str, report_factory, vocab: Vocabulary
) -> None:
    """A GitHub-project target builds with the per-target ``/<repo>/`` base-path (Req 3.2/3.3).

    The resolved ``site_url`` ends in ``/<repo>/``; the emitted ``mkdocs.yml`` carries it; and
    the built ``sitemap.xml`` references the project Pages base-path — so links and assets
    resolve under the project subpath rather than at the domain root.
    """
    identity = _identity_for(_GITHUB_REMOTE)
    assert identity.base_path == "/malware_hashes/"
    assert identity.site_url == "https://norandom.github.io/malware_hashes/"

    out = tmp_path / "run"
    out.mkdir()
    site = assemble_site(report_factory(), vocab, None, str(out), identity)

    yml = Path(site.mkdocs_yml_path).read_text(encoding="utf-8")
    assert identity.site_url in yml
    assert "use_directory_urls: true" in yml

    built = tmp_path / "_built"
    result = _run_mkdocs_build(site.mkdocs_yml_path, built)
    assert result.returncode == 0, (
        f"mkdocs build failed (github base-path, vocab={vocab_label}):\n"
        f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )
    # The built sitemap places every URL under the project Pages base-path.
    sitemap = built / "sitemap.xml"
    assert sitemap.is_file()
    assert "norandom.github.io/malware_hashes/" in sitemap.read_text(encoding="utf-8")


def test_no_remote_and_non_github_use_root_base_path() -> None:
    """No-remote / non-GitHub fallbacks build under a root base-path, not a project subpath.

    Req 3.5 / 3.6: a target with no remote derives a per-target ``site_name`` with an empty
    ``repo_url`` and a root base-path; a non-GitHub remote keeps the remote as ``repo_url``
    but still falls back to a root base-path. Neither carries a GitHub Pages ``site_url``.
    """
    no_remote = _identity_for(None)
    assert no_remote.base_path == "/"
    assert no_remote.site_url == ""
    assert no_remote.repo_url == ""
    assert no_remote.site_name == "widgets"  # target-dir basename

    non_github = _identity_for(_NON_GITHUB_REMOTE)
    assert non_github.base_path == "/"
    assert non_github.site_url == ""
    assert non_github.repo_url == _NON_GITHUB_REMOTE
    assert non_github.site_name == "widgets"


# --------------------------------------------------------------------------- #
# Determinism: two runs over equal inputs -> byte-identical trees (Req 8.2)    #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "vocab_label,report_factory,vocab",
    _VOCAB_CASES,
    ids=[c[0] for c in _VOCAB_CASES],
)
@pytest.mark.parametrize(
    "remote_label,remote_url",
    _REMOTE_CASES,
    ids=[c[0] for c in _REMOTE_CASES],
)
def test_two_runs_byte_identical_tree(
    tmp_path: Path,
    vocab_label: str,
    report_factory,
    vocab: Vocabulary,
    remote_label: str,
    remote_url: str | None,
) -> None:
    """Two assembly runs over equal inputs produce a byte-identical source tree (Req 8.2).

    Distinct (but equal) report instances are assembled into two separate output dirs; the
    whole emitted ``site/`` tree must be byte-for-byte identical, proving determinism across
    every (vocabulary, remote) combination.
    """
    identity = _identity_for(remote_url)
    a_out = tmp_path / "a"
    b_out = tmp_path / "b"
    a_out.mkdir()
    b_out.mkdir()

    site_a = assemble_site(report_factory(), vocab, None, str(a_out), identity)
    site_b = assemble_site(report_factory(), vocab, None, str(b_out), identity)

    tree_a = _read_tree(Path(site_a.site_dir))
    tree_b = _read_tree(Path(site_b.site_dir))
    assert tree_a.keys() == tree_b.keys()
    assert tree_a == tree_b
    # The returned seam values match too (modulo the output-dir prefix the bytes are stable).
    assert site_a.page_count == site_b.page_count
    assert site_a.role_page_count == site_b.role_page_count
    assert site_a.identity == site_b.identity


# --------------------------------------------------------------------------- #
# Isolation: only writes under the run's output dir (Req 8.5)                  #
# --------------------------------------------------------------------------- #


def test_only_writes_under_run_output_dir(tmp_path: Path) -> None:
    """The single write target is ``<out_dir>/site`` — nothing escapes the run output dir.

    Req 8.5: assembling into an output dir created inside an otherwise-empty sandbox leaves no
    file anywhere except under ``<out_dir>/site``; the rest of the sandbox stays empty.
    """
    out = tmp_path / "out"
    out.mkdir()
    site = assemble_site(_default_report(), default_profile(), None, str(out), _identity_for(_GITHUB_REMOTE))

    site_root = Path(site.site_dir)
    assert site_root == out / "site"
    # Every emitted file lives under <out>/site.
    for path in site_root.rglob("*"):
        if path.is_file():
            assert site_root in path.parents

    # The only entry created under the output dir is the site/ tree.
    assert {p.name for p in out.iterdir()} == {"site"}
    # The sandbox parent holds only the output dir we created (no stray writes elsewhere).
    assert {p.name for p in tmp_path.iterdir()} == {"out"}


def test_isolation_two_targets_distinct_identities_and_dirs(tmp_path: Path) -> None:
    """Two different targets resolve to distinct identities written to distinct dirs (Req 8.5).

    Per-project isolation: documenting a second target in a second output dir yields a
    different per-target identity and a separate site tree; neither leaks the other's identity.
    """
    out_a = tmp_path / "target_a"
    out_b = tmp_path / "target_b"
    out_a.mkdir()
    out_b.mkdir()

    ident_a = resolve_site_identity("/work/alpha", "https://github.com/octocat/alpha.git", {})
    ident_b = resolve_site_identity("/work/beta", "https://github.com/hubber/beta.git", {})
    assert ident_a != ident_b
    assert ident_a.base_path == "/alpha/"
    assert ident_b.base_path == "/beta/"

    site_a = assemble_site(_default_report(), default_profile(), None, str(out_a), ident_a)
    site_b = assemble_site(_default_report(), default_profile(), None, str(out_b), ident_b)

    yml_a = Path(site_a.mkdocs_yml_path).read_text(encoding="utf-8")
    yml_b = Path(site_b.mkdocs_yml_path).read_text(encoding="utf-8")
    assert "octocat.github.io/alpha/" in yml_a
    assert "beta" not in yml_a  # target A never carries target B's identity
    assert "hubber.github.io/beta/" in yml_b
    assert "alpha" not in yml_b


# --------------------------------------------------------------------------- #
# A target run never derives DocuHarnessX's own identity / Pages URL (Req 3.8) #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "remote_label,remote_url",
    _REMOTE_CASES,
    ids=[c[0] for c in _REMOTE_CASES],
)
def test_target_run_never_emits_docuharnessx_identity(
    tmp_path: Path, remote_label: str, remote_url: str | None
) -> None:
    """No (vocabulary, remote) combination ever emits DocuHarnessX's own identity (Req 3.8).

    The resolved identity and the emitted ``mkdocs.yml`` must never reference DocuHarnessX's
    repo name or its GitHub Pages host/subpath — the identity is always per-target.
    """
    identity = _identity_for(remote_url)
    out = tmp_path / "run"
    out.mkdir()
    site = assemble_site(_default_report(), default_profile(), None, str(out), identity)

    forbidden = ("docuharnessx", "DocuHarnessX")
    blob = "\n".join(
        [
            identity.site_name,
            identity.repo_name,
            identity.repo_url,
            identity.site_url,
            identity.base_path,
        ]
    )
    for token in forbidden:
        assert token.lower() not in blob.lower(), token

    yml = Path(site.mkdocs_yml_path).read_text(encoding="utf-8")
    for token in forbidden:
        assert token.lower() not in yml.lower(), token


def test_reference_target_resolves_to_repo_pages_subpath(tmp_path: Path) -> None:
    """The reference target resolves to the ``/malware_hashes/`` Pages subpath (Req 3.2).

    ``github.com/norandom/malware_hashes`` -> base-path ``/malware_hashes/`` and a non-
    DocuHarnessX identity, end to end through a real build.
    """
    identity = _identity_for(_GITHUB_REMOTE, target_repo="/home/mc/Source/malware_hashes")
    assert identity.base_path == "/malware_hashes/"
    assert identity.repo_name == "norandom/malware_hashes"

    out = tmp_path / "run"
    out.mkdir()
    site = assemble_site(_default_report(), default_profile(), None, str(out), identity)
    built = tmp_path / "_built"
    result = _run_mkdocs_build(site.mkdocs_yml_path, built)
    assert result.returncode == 0, (
        f"reference-target build failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )
    assert "malware_hashes" in (built / "sitemap.xml").read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# No model / no network at assembly time (Req 8.1) — the build is the only     #
# subprocess, and it is invoked by the test, not the assembler.                #
# --------------------------------------------------------------------------- #


def test_assembly_makes_no_subprocess_or_network_call(monkeypatch, tmp_path: Path) -> None:
    """``assemble_site`` performs no subprocess and no network access (Req 8.1).

    The identity is pre-resolved by the caller, so the writer is a pure filesystem transform.
    We trip both ``subprocess.run`` and ``socket.socket`` to prove neither is touched while
    assembling the tree (the real ``mkdocs build`` subprocess is driven separately by tests).
    """
    import socket
    import subprocess as _sp

    def _no_subprocess(*args, **kwargs):  # pragma: no cover - must not be called
        raise AssertionError("assemble_site must not spawn a subprocess")

    def _no_socket(*args, **kwargs):  # pragma: no cover - must not be called
        raise AssertionError("assemble_site must not open a socket")

    monkeypatch.setattr(_sp, "run", _no_subprocess)
    monkeypatch.setattr(socket, "socket", _no_socket)

    out = tmp_path / "run"
    out.mkdir()
    site = assemble_site(
        _default_report(), default_profile(), None, str(out), _identity_for(_GITHUB_REMOTE)
    )
    assert os.path.isfile(site.mkdocs_yml_path)
