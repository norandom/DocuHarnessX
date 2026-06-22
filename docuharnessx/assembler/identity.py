"""The per-target site-identity resolver (design "SiteIdentity resolver"; task 2.1).

This module isolates the per-target site-identity computation of the Wave 3
``mkdocs-site-assembler`` core. DocuHarnessX documents *arbitrary* target projects, so the
published site's identity — its display ``site_name``, the ``owner/repo`` ``repo_name``, the
remote ``repo_url``, the GitHub project-Pages ``site_url``, the ``/<repo>/`` Pages
``base_path``, and the Material ``edit_uri`` — is derived **per-target** from the target
repository's ``origin`` git remote, never hardcoded to DocuHarnessX's own identity (Req 3.8).

* :func:`resolve_site_identity` is **pure** (Req 3.1-3.8, 2.5): given the target path, an
  optional ``origin`` remote URL string, and an overrides mapping, it returns a frozen
  :class:`~docuharnessx.assembler.model.SiteIdentity`. It parses the GitHub HTTPS and SSH
  remote forms into ``owner/repo`` (stripping any trailing ``.git``), computes the project
  GitHub Pages ``site_url`` ``https://<owner>.github.io/<repo>/`` and the ``/<repo>/``
  base-path and an ``edit_uri``; for a non-GitHub remote it keeps the remote URL as
  ``repo_url`` with a root base-path and a target-directory-derived ``site_name``; for no
  remote it derives ``site_name`` from the target directory with an empty ``repo_url`` and a
  root base-path; and it applies per-field overrides (``site_name``, ``site_url``,
  ``repo_url``, ``edit_uri``) over the derived value (Req 3.7). It performs no I/O and never
  raises on a missing / non-GitHub remote — every input combination yields a total,
  deterministic, buildable identity (Req 3.5, 3.6, 2.5).

The only process-touching surface in this spec — the read-only, mockable ``origin`` remote
read — also lives in this module (:func:`read_origin_remote`, task 2.2). It is deliberately
isolated behind a single :mod:`subprocess` call so tests stub it without a real repo or git
binary, and so every failure mode (no remote, no git executable, a failed/timed-out
invocation) degrades to ``None`` — the resolver above then takes the no-remote fallback rather
than the run aborting (Req 2.5). The resolver itself stays pure: it takes the URL this helper
returns as a plain string argument and never invokes git.
"""

from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Mapping

from docuharnessx.assembler.model import SiteIdentity

__all__ = ["read_origin_remote", "resolve_site_identity"]

#: Wall-clock ceiling (seconds) for the read-only origin-remote read. A hung git invocation
#: degrades to the no-remote fallback rather than stalling the run (Req 2.5); the read is a
#: trivial local config lookup so a few seconds is generous.
_GIT_REMOTE_READ_TIMEOUT_SECONDS: float = 5.0


def read_origin_remote(target_repo: str) -> str | None:
    """Return the target's ``origin`` remote URL, or ``None`` (task 2.2; Req 3.1, 3.5, 2.5).

    Runs a single **read-only** ``git -C <target_repo> remote get-url origin`` (the only
    subprocess in this spec) and returns the remote URL string on success. Every failure mode
    is swallowed to ``None`` so a git-less / remote-less environment degrades to the no-remote
    site-identity fallback (:func:`resolve_site_identity`) rather than aborting the run:

    * no ``origin`` remote (git exits non-zero) → ``None`` (Req 3.5);
    * no ``git`` executable on ``PATH`` (:class:`FileNotFoundError`) → ``None`` (Req 2.5);
    * any other failed / timed-out / errored invocation (:class:`OSError`,
      :class:`subprocess.SubprocessError`) → ``None`` (Req 2.5);
    * a zero exit with empty / whitespace-only stdout → ``None`` (no usable URL).

    Args:
        target_repo: The target repository's directory path. Passed to git via ``-C`` so the
            read is scoped to the target rather than the process's working directory.

    Returns:
        The trimmed ``origin`` remote URL, or ``None`` when no usable remote can be read.

    The invocation is read-only, argument-vector (no shell), text-mode, and time-bounded; it
    performs no writes to the target's git, no network access, and uses no credentials.
    """
    try:
        completed = subprocess.run(
            ["git", "-C", target_repo, "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            shell=False,
            check=False,
            timeout=_GIT_REMOTE_READ_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError):
        # FileNotFoundError (no git), TimeoutExpired, CalledProcessError, and any other
        # OSError/SubprocessError all degrade to the no-remote fallback (Req 2.5).
        return None

    if completed.returncode != 0:
        return None

    url = (completed.stdout or "").strip()
    return url or None

#: The Material ``edit_uri`` emitted for a GitHub project remote. ``mkdocs-material`` resolves
#: it against ``repo_url`` to render the per-page "edit" affordance; ``edit/main/docs/`` is the
#: conventional default for a docs tree under ``docs/`` on the ``main`` branch. Emitted only
#: for GitHub remotes (a non-GitHub / no-remote fallback carries an empty ``edit_uri`` so no
#: broken affordance is rendered — Req 3.5, 3.6).
_GITHUB_EDIT_URI: str = "edit/main/docs/"

#: The override keys the resolver honors (Req 3.7). Keys outside this set are ignored so an
#: unrelated config value can never perturb the derived identity. ``repo_name``/``base_path``
#: are intentionally *not* overridable — they are derived invariants of the resolved remote.
_OVERRIDABLE: frozenset[str] = frozenset({"site_name", "site_url", "repo_url", "edit_uri"})

#: Matches a GitHub HTTPS remote: ``https://github.com/<owner>/<repo>`` with an optional
#: ``www.`` host prefix, an optional trailing ``.git``, and an optional trailing ``/``. The
#: ``owner``/``repo`` groups stop at ``/`` so a trailing slash or ``.git`` never leaks in.
_GITHUB_HTTPS = re.compile(
    r"^https?://(?:www\.)?github\.com/(?P<owner>[^/]+?)/(?P<repo>[^/]+?)(?:\.git)?/?$",
    re.IGNORECASE,
)

#: Matches a GitHub SSH remote in the scp-like form ``git@github.com:<owner>/<repo>`` with an
#: optional trailing ``.git``/``/``.
_GITHUB_SSH = re.compile(
    r"^git@github\.com:(?P<owner>[^/]+?)/(?P<repo>[^/]+?)(?:\.git)?/?$",
    re.IGNORECASE,
)

#: Matches a GitHub ``ssh://`` remote ``ssh://git@github.com/<owner>/<repo>``.
_GITHUB_SSH_URL = re.compile(
    r"^ssh://git@github\.com/(?P<owner>[^/]+?)/(?P<repo>[^/]+?)(?:\.git)?/?$",
    re.IGNORECASE,
)


def _target_basename(target_repo: str) -> str:
    """Return the target directory's basename, the fallback ``site_name`` (Req 3.5, 3.6).

    Trailing path separators are stripped before taking the basename so a path written with a
    trailing ``/`` (e.g. ``/a/b/``) still yields ``b`` rather than an empty string. Pure: it
    parses the path string only and never touches the filesystem.
    """
    normalized = target_repo.rstrip("/" + os.sep)
    base = os.path.basename(normalized)
    return base or target_repo


def _parse_github(remote_url: str) -> tuple[str, str] | None:
    """Return ``(owner, repo)`` for a GitHub HTTPS/SSH remote, else ``None`` (Req 3.4).

    Recognizes the HTTPS, scp-like SSH (``git@github.com:owner/repo``), and ``ssh://`` forms,
    each with an optional trailing ``.git`` and/or ``/`` (stripped by the patterns). Returns
    ``None`` for any non-GitHub remote so the caller takes the non-GitHub fallback (Req 3.6).
    Pure and deterministic.
    """
    for pattern in (_GITHUB_HTTPS, _GITHUB_SSH, _GITHUB_SSH_URL):
        match = pattern.match(remote_url)
        if match:
            return match.group("owner"), match.group("repo")
    return None


def _github_identity(owner: str, repo: str, target_repo: str) -> SiteIdentity:
    """Build the GitHub project-Pages identity for ``owner/repo`` (Req 3.1, 3.2, 3.4).

    Computes the project Pages ``site_url`` ``https://<owner>.github.io/<repo>/`` and the
    ``/<repo>/`` base-path so internal links and assets resolve under the project's Pages
    subpath; ``site_name`` defaults to the repo name; ``repo_url`` is the canonical HTTPS
    browse URL (no ``.git``); ``edit_uri`` is the conventional GitHub docs edit path. Never
    DocuHarnessX's own identity — every value is derived from the passed ``owner``/``repo``
    (Req 3.8). The ``target_repo`` is accepted for symmetry with the fallbacks but the
    GitHub identity is fully remote-derived.
    """
    return SiteIdentity(
        site_name=repo,
        repo_name=f"{owner}/{repo}",
        repo_url=f"https://github.com/{owner}/{repo}",
        site_url=f"https://{owner}.github.io/{repo}/",
        base_path=f"/{repo}/",
        edit_uri=_GITHUB_EDIT_URI,
    )


def _non_github_identity(remote_url: str, target_repo: str) -> SiteIdentity:
    """Build the non-GitHub fallback identity (Req 3.6).

    Keeps the detected remote URL as ``repo_url`` (so a repo button can still be rendered) but
    falls back to a root base-path and an empty ``site_url``/``edit_uri`` — the project's Pages
    subpath is unknown for a non-GitHub host — with a target-directory-derived ``site_name``.
    Never raises; never DocuHarnessX's identity (Req 3.8).
    """
    return SiteIdentity(
        site_name=_target_basename(target_repo),
        repo_name="",
        repo_url=remote_url,
        site_url="",
        base_path="/",
        edit_uri="",
    )


def _no_remote_identity(target_repo: str) -> SiteIdentity:
    """Build the no-remote fallback identity (Req 3.5).

    Derives ``site_name`` from the target directory, leaves ``repo_url``/``repo_name``/
    ``site_url``/``edit_uri`` empty, and uses a root base-path. The result is a buildable
    identity (the mkdocs builder omits the empty ``site_url``/``repo_url``/``edit_uri`` keys).
    Never raises; never DocuHarnessX's identity (Req 3.8).
    """
    return SiteIdentity(
        site_name=_target_basename(target_repo),
        repo_name="",
        repo_url="",
        site_url="",
        base_path="/",
        edit_uri="",
    )


def _apply_overrides(
    identity: SiteIdentity, overrides: Mapping[str, str]
) -> SiteIdentity:
    """Return ``identity`` with each overridable field replaced by its override (Req 3.7).

    Only the keys in :data:`_OVERRIDABLE` (``site_name``, ``site_url``, ``repo_url``,
    ``edit_uri``) are honored; any other key is ignored so an unrelated config value can never
    perturb the derived identity. ``repo_name``/``base_path`` are never overridden — they are
    derived invariants of the resolved remote. Returns a new frozen value object (the input is
    immutable). Pure and deterministic.
    """
    selected = {
        key: value for key, value in overrides.items() if key in _OVERRIDABLE
    }
    if not selected:
        return identity
    return SiteIdentity(
        site_name=selected.get("site_name", identity.site_name),
        repo_name=identity.repo_name,
        repo_url=selected.get("repo_url", identity.repo_url),
        site_url=selected.get("site_url", identity.site_url),
        base_path=identity.base_path,
        edit_uri=selected.get("edit_uri", identity.edit_uri),
    )


def resolve_site_identity(
    target_repo: str,
    remote_url: str | None,
    overrides: Mapping[str, str],
) -> SiteIdentity:
    """Resolve the per-target :class:`SiteIdentity` (Req 3.1-3.8, 2.5).

    Args:
        target_repo: The target repository's directory path. Only its basename is read (for
            the fallback ``site_name``); the resolver never touches the filesystem.
        remote_url: The target's ``origin`` remote URL, or ``None`` when the target has no
            remote (the value :func:`read_origin_remote`, task 2.2, returns). An empty /
            whitespace-only string is treated as no remote.
        overrides: A per-field override mapping. Only the keys ``site_name``, ``site_url``,
            ``repo_url``, ``edit_uri`` are honored (Req 3.7); other keys are ignored. May be
            empty.

    Returns:
        A frozen :class:`SiteIdentity`. Resolution order (design "Site-identity resolution"):

        1. **GitHub remote** (HTTPS / SSH / ``ssh://``, ``.git`` stripped) → the project
           Pages identity: ``site_url`` ``https://<owner>.github.io/<repo>/`` and base-path
           ``/<repo>/`` (Req 3.1, 3.2, 3.4).
        2. **Non-GitHub remote** → keep the remote URL as ``repo_url`` with a root base-path
           and a target-derived ``site_name`` (Req 3.6).
        3. **No remote** → a target-derived ``site_name`` with an empty ``repo_url`` and a root
           base-path (Req 3.5).

        Per-field overrides are then applied over the derived value (Req 3.7).

    The resolver is **pure, total, and deterministic** — it performs no I/O, never raises on a
    missing / non-GitHub remote (Req 2.5, 3.5, 3.6), and never derives DocuHarnessX's own
    identity: every value comes from the passed ``target_repo`` / ``remote_url`` / ``overrides``
    (Req 3.8).
    """
    normalized_remote = remote_url.strip() if remote_url is not None else ""

    if not normalized_remote:
        identity = _no_remote_identity(target_repo)
    else:
        parsed = _parse_github(normalized_remote)
        if parsed is not None:
            owner, repo = parsed
            identity = _github_identity(owner, repo, target_repo)
        else:
            identity = _non_github_identity(normalized_remote, target_repo)

    return _apply_overrides(identity, overrides)
