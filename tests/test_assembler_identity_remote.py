"""Unit tests for the isolated, mockable origin-remote read helper (mkdocs-site-assembler task 2.2).

These tests pin the *SiteIdentity resolver* boundary's only process-touching surface
(design "SiteIdentity resolver", Req 3.1, 3.5, 2.5): the thin, mockable
:func:`docuharnessx.assembler.identity.read_origin_remote`. It runs a **read-only**
``git -C <target> remote get-url origin`` and returns the remote URL or ``None`` — swallowing
a missing remote (non-zero exit), a missing git executable, and any failed invocation so a
git-less environment degrades to the no-remote fallback rather than aborting the run (Req 2.5).

The git invocation is stubbed (the helper is isolated behind ``subprocess.run`` precisely so
tests need neither a real repo nor a git binary):

* a present remote returns its URL (Req 3.1);
* an absent remote (non-zero exit) returns ``None`` (Req 3.5);
* a missing git executable (``FileNotFoundError``) returns ``None`` (Req 2.5);
* a generic ``OSError`` / ``subprocess`` failure returns ``None`` (Req 2.5);
* a timeout returns ``None`` (Req 2.5);
* none of the failure paths raise.
"""

from __future__ import annotations

import subprocess
from types import SimpleNamespace

import pytest

import docuharnessx.assembler as assembler
from docuharnessx.assembler import identity as identity_mod
from docuharnessx.assembler.identity import read_origin_remote

_TARGET = "/home/mc/Source/malware_hashes"


def _completed(stdout: str, returncode: int = 0) -> SimpleNamespace:
    """A minimal stand-in for :class:`subprocess.CompletedProcess`.

    The helper reads only ``returncode`` and ``stdout``; we model just those so the test does
    not depend on how the helper constructs the ``subprocess.run`` call.
    """
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr="")


# --------------------------------------------------------------------------- #
# Public surface                                                               #
# --------------------------------------------------------------------------- #


def test_read_origin_remote_is_exported_from_package_surface() -> None:
    """``read_origin_remote`` is re-exported from the package, identity-equal (task 2.2)."""
    assert hasattr(assembler, "read_origin_remote")
    assert assembler.read_origin_remote is read_origin_remote
    assert "read_origin_remote" in assembler.__all__


def test_module_exposes_read_origin_remote_in_all() -> None:
    """``identity.__all__`` now carries the git read helper (task 2.2)."""
    assert "read_origin_remote" in identity_mod.__all__


# --------------------------------------------------------------------------- #
# Present remote → returns the URL (Req 3.1)                                   #
# --------------------------------------------------------------------------- #


def test_present_remote_returns_its_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """A successful ``git remote get-url origin`` returns the remote URL (Req 3.1)."""
    captured: dict[str, object] = {}

    def fake_run(cmd, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return _completed("https://github.com/norandom/malware_hashes.git\n")

    monkeypatch.setattr(identity_mod.subprocess, "run", fake_run)
    result = read_origin_remote(_TARGET)
    assert result == "https://github.com/norandom/malware_hashes.git"


def test_present_remote_url_is_stripped(monkeypatch: pytest.MonkeyPatch) -> None:
    """Trailing whitespace/newline from git stdout is stripped (Req 3.1)."""

    def fake_run(cmd, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        return _completed("  https://github.com/norandom/malware_hashes.git  \n")

    monkeypatch.setattr(identity_mod.subprocess, "run", fake_run)
    assert read_origin_remote(_TARGET) == "https://github.com/norandom/malware_hashes.git"


def test_invocation_is_read_only_and_scoped_to_target(monkeypatch: pytest.MonkeyPatch) -> None:
    """The helper runs a read-only ``git ... remote get-url origin`` scoped to the target.

    Pins the design contract (design "SiteIdentity resolver"): the only subprocess is the
    read-only ``git remote get-url origin`` for the target directory — no write subcommand, no
    network, no shell.
    """
    captured: dict[str, object] = {}

    def fake_run(cmd, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        captured["cmd"] = list(cmd)
        captured["kwargs"] = kwargs
        return _completed("https://github.com/norandom/malware_hashes.git")

    monkeypatch.setattr(identity_mod.subprocess, "run", fake_run)
    read_origin_remote(_TARGET)

    cmd = captured["cmd"]
    assert cmd[0] == "git"
    # Read-only remote read, scoped to the target dir.
    assert "remote" in cmd
    assert "get-url" in cmd
    assert "origin" in cmd
    assert _TARGET in cmd
    # Never via a shell (argument-vector invocation only).
    assert captured["kwargs"].get("shell", False) is False


def test_empty_stdout_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """A zero exit with empty stdout yields ``None`` (no usable URL → no-remote fallback)."""

    def fake_run(cmd, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        return _completed("   \n")

    monkeypatch.setattr(identity_mod.subprocess, "run", fake_run)
    assert read_origin_remote(_TARGET) is None


# --------------------------------------------------------------------------- #
# Failure paths all swallow and return None (Req 3.5, 2.5)                     #
# --------------------------------------------------------------------------- #


def test_absent_remote_nonzero_exit_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """A non-zero git exit (no ``origin`` remote) returns ``None`` without raising (Req 3.5)."""

    def fake_run(cmd, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        return _completed("", returncode=2)

    monkeypatch.setattr(identity_mod.subprocess, "run", fake_run)
    assert read_origin_remote(_TARGET) is None


def test_missing_git_executable_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """A missing ``git`` binary (``FileNotFoundError``) degrades to ``None`` (Req 2.5)."""

    def fake_run(cmd, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        raise FileNotFoundError("git")

    monkeypatch.setattr(identity_mod.subprocess, "run", fake_run)
    assert read_origin_remote(_TARGET) is None


def test_called_process_error_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """A raised ``CalledProcessError`` (if check is used) degrades to ``None`` (Req 2.5)."""

    def fake_run(cmd, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        raise subprocess.CalledProcessError(1, cmd)

    monkeypatch.setattr(identity_mod.subprocess, "run", fake_run)
    assert read_origin_remote(_TARGET) is None


def test_generic_oserror_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """Any ``OSError`` from the invocation degrades to ``None`` (Req 2.5)."""

    def fake_run(cmd, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        raise OSError("permission denied")

    monkeypatch.setattr(identity_mod.subprocess, "run", fake_run)
    assert read_origin_remote(_TARGET) is None


def test_timeout_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """A ``TimeoutExpired`` degrades to ``None`` rather than aborting the run (Req 2.5)."""

    def fake_run(cmd, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        raise subprocess.TimeoutExpired(cmd, 5)

    monkeypatch.setattr(identity_mod.subprocess, "run", fake_run)
    assert read_origin_remote(_TARGET) is None


# --------------------------------------------------------------------------- #
# Composition with the pure resolver (Req 3.5 end-to-end fallback)             #
# --------------------------------------------------------------------------- #


def test_none_remote_feeds_resolver_no_remote_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """A ``None`` from the helper drives the resolver's no-remote fallback (Req 3.5).

    Confirms the helper's absent-value contract composes with :func:`resolve_site_identity`:
    a git-less environment yields a buildable, target-derived identity at root base-path.
    """

    def fake_run(cmd, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        raise FileNotFoundError("git")

    monkeypatch.setattr(identity_mod.subprocess, "run", fake_run)
    remote = read_origin_remote(_TARGET)
    assert remote is None
    ident = identity_mod.resolve_site_identity(_TARGET, remote, {})
    assert ident.base_path == "/"
    assert ident.site_name == "malware_hashes"
