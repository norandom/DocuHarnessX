"""Unit tests for the pure per-target site-identity resolver (mkdocs-site-assembler task 2.1).

These tests pin the *SiteIdentity resolver* boundary (design "SiteIdentity resolver"):
the pure :func:`docuharnessx.assembler.identity.resolve_site_identity`. The resolver takes
the target path, an optional ``origin`` remote URL string, and an overrides mapping, and
returns a frozen :class:`~docuharnessx.assembler.model.SiteIdentity` — deterministically and
without any process/network access (the mockable git read is task 2.2, not exercised here).

Observable completion (tasks.md 2.1):

* the GitHub HTTPS and SSH forms yield the same ``owner/repo`` with ``site_url`` ending in
  ``/<repo>/`` and ``base_path`` ``/<repo>/`` (Req 3.1, 3.2, 3.4);
* the no-remote and non-GitHub fallbacks produce a root base-path and a target-derived name
  without raising (Req 3.5, 3.6);
* each override field wins (Req 3.7);
* the reference target ``github.com/norandom/malware_hashes`` resolves to base-path
  ``/malware_hashes/`` and a non-DocuHarnessX identity (Req 3.2, 3.8).
"""

from __future__ import annotations

import pytest

import docuharnessx.assembler as assembler
from docuharnessx.assembler import SiteIdentity
from docuharnessx.assembler import identity as identity_mod
from docuharnessx.assembler.identity import resolve_site_identity

# A target dir basename used across the fallback tests. The resolver never touches the
# filesystem (it derives the name from the path basename only), so the path need not exist.
_TARGET = "/home/mc/Source/malware_hashes"


# --------------------------------------------------------------------------- #
# Public surface                                                               #
# --------------------------------------------------------------------------- #


def test_resolver_is_exported_from_package_surface() -> None:
    """``resolve_site_identity`` is re-exported from the package, identity-equal (Req 2.1)."""
    assert hasattr(assembler, "resolve_site_identity")
    assert assembler.resolve_site_identity is resolve_site_identity
    assert "resolve_site_identity" in assembler.__all__


def test_resolver_returns_a_frozen_site_identity() -> None:
    """The resolver returns a frozen :class:`SiteIdentity` value object."""
    ident = resolve_site_identity(_TARGET, None, {})
    assert isinstance(ident, SiteIdentity)
    with pytest.raises(Exception):
        ident.site_name = "x"  # type: ignore[misc]


# --------------------------------------------------------------------------- #
# GitHub project Pages: HTTPS and SSH parse to the same identity (Req 3.1/3.2/3.4)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "remote",
    [
        "https://github.com/norandom/malware_hashes.git",
        "https://github.com/norandom/malware_hashes",
        "git@github.com:norandom/malware_hashes.git",
        "git@github.com:norandom/malware_hashes",
        "ssh://git@github.com/norandom/malware_hashes.git",
    ],
)
def test_github_forms_yield_same_owner_repo_identity(remote: str) -> None:
    """HTTPS, SSH, and ssh:// GitHub forms all parse to the same ``owner/repo`` (Req 3.4).

    Trailing ``.git`` is stripped (Req 3.4); ``site_url`` is the project Pages URL ending in
    ``/<repo>/`` and ``base_path`` is ``/<repo>/`` (Req 3.2).
    """
    ident = resolve_site_identity(_TARGET, remote, {})
    assert ident.repo_name == "norandom/malware_hashes"
    assert ident.site_url == "https://norandom.github.io/malware_hashes/"
    assert ident.site_url.endswith("/malware_hashes/")
    assert ident.base_path == "/malware_hashes/"
    assert ident.site_name == "malware_hashes"
    # repo_url is the canonical HTTPS browse URL (no .git suffix).
    assert ident.repo_url == "https://github.com/norandom/malware_hashes"
    # An edit_uri is provided for GitHub so Material renders an edit link.
    assert ident.edit_uri
    assert ident.edit_uri.endswith("docs/")


def test_reference_target_resolves_to_repo_subpath_and_not_docuharnessx() -> None:
    """The reference target resolves to ``/malware_hashes/`` and never DocuHarnessX (Req 3.2, 3.8)."""
    ident = resolve_site_identity(
        _TARGET, "https://github.com/norandom/malware_hashes.git", {}
    )
    assert ident.base_path == "/malware_hashes/"
    assert ident.site_url == "https://norandom.github.io/malware_hashes/"
    # Never DocuHarnessX's own identity, name, repo, or Pages URL (Req 3.8).
    blob = " ".join(
        (
            ident.site_name,
            ident.repo_name,
            ident.repo_url,
            ident.site_url,
            ident.base_path,
            ident.edit_uri,
        )
    ).casefold()
    assert "docuharnessx" not in blob


def test_https_form_with_trailing_slash_is_tolerated() -> None:
    """A trailing slash on the HTTPS remote does not leak into the parsed repo (Req 3.4)."""
    ident = resolve_site_identity(_TARGET, "https://github.com/norandom/malware_hashes/", {})
    assert ident.repo_name == "norandom/malware_hashes"
    assert ident.base_path == "/malware_hashes/"


# --------------------------------------------------------------------------- #
# No remote → target-derived name + root base-path (Req 3.5)                   #
# --------------------------------------------------------------------------- #


def test_no_remote_falls_back_to_target_basename_and_root_base_path() -> None:
    """``remote_url=None`` → target-basename name, empty repo_url/edit_uri, root base-path (Req 3.5)."""
    ident = resolve_site_identity(_TARGET, None, {})
    assert ident.site_name == "malware_hashes"
    assert ident.repo_url == ""
    assert ident.repo_name == ""
    assert ident.site_url == ""
    assert ident.edit_uri == ""
    assert ident.base_path == "/"


def test_empty_remote_string_is_treated_as_no_remote() -> None:
    """An empty/whitespace remote string degrades to the no-remote fallback (Req 3.5)."""
    ident = resolve_site_identity(_TARGET, "   ", {})
    assert ident.base_path == "/"
    assert ident.repo_url == ""
    assert ident.site_name == "malware_hashes"


def test_target_basename_strips_trailing_separator() -> None:
    """A trailing path separator does not yield an empty site_name (Req 3.5)."""
    ident = resolve_site_identity("/home/mc/Source/malware_hashes/", None, {})
    assert ident.site_name == "malware_hashes"


# --------------------------------------------------------------------------- #
# Non-GitHub remote → keep repo_url, root base-path, target name (Req 3.6)     #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "remote",
    [
        "https://gitlab.com/acme/widgets.git",
        "git@bitbucket.org:acme/widgets.git",
        "https://example.com/git/widgets.git",
    ],
)
def test_non_github_remote_keeps_repo_url_with_root_base_path(remote: str) -> None:
    """A non-GitHub remote keeps ``repo_url`` but falls back to root base-path (Req 3.6)."""
    ident = resolve_site_identity(_TARGET, remote, {})
    assert ident.repo_url == remote
    assert ident.base_path == "/"
    assert ident.site_url == ""
    # site_name is target-derived, not GitHub-Pages-derived.
    assert ident.site_name == "malware_hashes"


# --------------------------------------------------------------------------- #
# Per-field overrides win (Req 3.7)                                            #
# --------------------------------------------------------------------------- #


def test_override_site_name_wins() -> None:
    ident = resolve_site_identity(
        _TARGET, "https://github.com/norandom/malware_hashes.git", {"site_name": "Custom Name"}
    )
    assert ident.site_name == "Custom Name"
    # Non-overridden fields keep their derived values.
    assert ident.base_path == "/malware_hashes/"


def test_override_site_url_wins() -> None:
    ident = resolve_site_identity(
        _TARGET, None, {"site_url": "https://docs.example.com/"}
    )
    assert ident.site_url == "https://docs.example.com/"


def test_override_repo_url_wins() -> None:
    ident = resolve_site_identity(
        _TARGET, None, {"repo_url": "https://github.com/acme/forked"}
    )
    assert ident.repo_url == "https://github.com/acme/forked"


def test_override_edit_uri_wins() -> None:
    ident = resolve_site_identity(
        _TARGET, None, {"edit_uri": "edit/trunk/site/"}
    )
    assert ident.edit_uri == "edit/trunk/site/"


def test_all_overrides_win_together() -> None:
    """Every overridable field is honored simultaneously (Req 3.7)."""
    overrides = {
        "site_name": "N",
        "site_url": "https://u/",
        "repo_url": "https://r",
        "edit_uri": "e/",
    }
    ident = resolve_site_identity(_TARGET, "git@github.com:o/r.git", overrides)
    assert ident.site_name == "N"
    assert ident.site_url == "https://u/"
    assert ident.repo_url == "https://r"
    assert ident.edit_uri == "e/"


def test_unknown_override_keys_are_ignored() -> None:
    """Keys outside the overridable set do not perturb the derived identity (Req 3.7)."""
    ident = resolve_site_identity(
        _TARGET, "https://github.com/norandom/malware_hashes.git", {"unknown": "x"}
    )
    assert ident.repo_name == "norandom/malware_hashes"
    assert ident.base_path == "/malware_hashes/"


# --------------------------------------------------------------------------- #
# Determinism (Req 8.2 spirit at the resolver level)                           #
# --------------------------------------------------------------------------- #


def test_resolution_is_deterministic_and_compares_by_value() -> None:
    """Equal inputs yield equal :class:`SiteIdentity` instances (frozen, by-value)."""
    a = resolve_site_identity(_TARGET, "https://github.com/norandom/malware_hashes.git", {})
    b = resolve_site_identity(_TARGET, "https://github.com/norandom/malware_hashes.git", {})
    assert a == b
    assert hash(a) == hash(b)


def test_module_exposes_only_its_documented_surface() -> None:
    """``identity.__all__`` carries the resolver (the git read is task 2.2)."""
    assert "resolve_site_identity" in identity_mod.__all__
