"""Tests for the ``dhx mcp`` subcommand (mcp-refine task 5.2; boundary: dhx mcp subcommand).

Task 5.2 extends the existing ``dhx`` parser with an ``mcp`` subparser (``target_repo``,
``--out``, ``--config``, ``-v``) mirroring ``run``, adds ``"mcp"`` to the subcommand set so the
bare form still works, adds a ``_mcp_command(args)`` that validates the target, resolves the
per-target session, and launches the stdio server via ``run_stdio``, and routes ``mcp`` in
``main`` — sending all human/log output to **stderr** so stdout stays the MCP protocol channel
(Req 1.1, 1.3, 2.1, 2.2, 2.5, 2.6).

These tests are credential-free: ``resolve_session`` and ``run_stdio`` are stubbed so the
command is exercised without a real model, no stdio subprocess, and no network. The existing
``run`` / ``init`` / bare-``dhx <repo>`` forms must keep parsing unchanged.
"""

from __future__ import annotations

import io
import sys

import pytest

from docuharnessx import cli
from docuharnessx.errors import TargetRepoError


# --------------------------------------------------------------------------- #
# Parser surface: the mcp subparser mirrors run (Req 2.1).                     #
# --------------------------------------------------------------------------- #


def test_parser_exposes_mcp_subcommand() -> None:
    parser = cli.build_parser()
    ns = parser.parse_args(
        ["mcp", "/some/path", "--out", "/o", "--config", "c.yaml", "-v"]
    )
    assert ns.command == "mcp"
    assert ns.target_repo == "/some/path"
    assert ns.out == "/o"
    assert ns.config == "c.yaml"
    assert ns.verbose is True


def test_mcp_target_repo_is_optional_positional() -> None:
    # Mirrors run: target_repo is an optional positional so a missing target is
    # validated (and reported) by the command rather than argparse.
    parser = cli.build_parser()
    ns = parser.parse_args(["mcp"])
    assert ns.command == "mcp"
    assert ns.target_repo is None


def test_mcp_is_a_recognised_subcommand() -> None:
    # "mcp" must be in the subcommand set so the bare-form normaliser does NOT
    # prepend "run" in front of it (Req 1.3 — bare form left intact).
    assert "mcp" in cli._SUBCOMMANDS


# --------------------------------------------------------------------------- #
# Target validation BEFORE launching the server (Req 2.2).                     #
# --------------------------------------------------------------------------- #


def test_mcp_bad_target_exits_nonzero_without_launching(tmp_path, capsys, monkeypatch) -> None:
    missing = str(tmp_path / "does-not-exist")

    launched = {"count": 0}

    def _never_launch(*_args, **_kwargs):  # pragma: no cover - must not run
        launched["count"] += 1

    # If the target were not validated first, this stub would be reached.
    monkeypatch.setattr(cli, "_run_stdio_blocking", _never_launch, raising=False)

    code = cli.main(["mcp", missing])
    assert code != 0
    err = capsys.readouterr().err
    assert "TargetRepoError" in err
    assert missing in err
    assert launched["count"] == 0, "the server must not launch for an invalid target"


def test_mcp_missing_target_exits_nonzero(capsys) -> None:
    code = cli.main(["mcp"])
    assert code != 0
    assert "TargetRepoError" in capsys.readouterr().err


def test_mcp_command_validates_before_session(tmp_path, monkeypatch) -> None:
    # _mcp_command must validate the target before resolving the session, so a bad
    # target raises TargetRepoError without ever calling resolve_session (Req 2.2).
    resolved = {"count": 0}

    def _spy_resolve(*_args, **_kwargs):  # pragma: no cover - must not run
        resolved["count"] += 1
        raise AssertionError("resolve_session reached for an invalid target")

    monkeypatch.setattr(cli, "resolve_session", _spy_resolve, raising=False)
    args = cli.build_parser().parse_args(["mcp", str(tmp_path / "nope")])
    with pytest.raises(TargetRepoError):
        cli._mcp_command(args)
    assert resolved["count"] == 0


# --------------------------------------------------------------------------- #
# The command resolves the session and launches the stdio server (Req 2.5).    #
# --------------------------------------------------------------------------- #


def test_mcp_command_resolves_session_and_launches(tmp_path, monkeypatch) -> None:
    target = tmp_path / "repo"
    target.mkdir()
    out = tmp_path / "out"

    sentinel_session = object()
    calls: dict[str, object] = {}

    def _fake_resolve(target_repo, out_dir, **kwargs):
        calls["resolve"] = (target_repo, out_dir, kwargs)
        return sentinel_session

    def _fake_launch(session):
        calls["launch"] = session

    monkeypatch.setattr(cli, "resolve_session", _fake_resolve, raising=False)
    monkeypatch.setattr(cli, "_run_stdio_blocking", _fake_launch, raising=False)

    args = cli.build_parser().parse_args(["mcp", str(target), "--out", str(out)])
    code = cli._mcp_command(args)
    assert code == cli.EXIT_OK
    # The validated absolute target + resolved out dir were handed to resolve_session.
    resolved_target, resolved_out, _kwargs = calls["resolve"]
    assert resolved_target == str(target.resolve()) or resolved_target == str(target)
    assert resolved_out == str(out.resolve()) or resolved_out == str(out)
    # The resolved session was launched over stdio.
    assert calls["launch"] is sentinel_session


def test_mcp_command_defaults_out_when_omitted(tmp_path, monkeypatch) -> None:
    target = tmp_path / "repo"
    target.mkdir()

    captured: dict[str, object] = {}

    def _fake_resolve(target_repo, out_dir, **kwargs):
        captured["out"] = out_dir
        return object()

    monkeypatch.setattr(cli, "resolve_session", _fake_resolve, raising=False)
    monkeypatch.setattr(cli, "_run_stdio_blocking", lambda _s: None, raising=False)

    args = cli.build_parser().parse_args(["mcp", str(target)])
    cli._mcp_command(args)
    # --out omitted: the documented per-target default is passed through (None lets
    # resolve_session apply its own default), or the resolved default path.
    assert captured["out"] is None or ".docuharnessx" in str(captured["out"])


# --------------------------------------------------------------------------- #
# main routes mcp and keeps stdout clean (Req 2.5, 1.1).                        #
# --------------------------------------------------------------------------- #


def test_main_routes_mcp_and_writes_nothing_to_stdout(tmp_path, monkeypatch) -> None:
    target = tmp_path / "repo"
    target.mkdir()

    monkeypatch.setattr(cli, "resolve_session", lambda *a, **k: object(), raising=False)

    def _launch(_session):
        # A real launcher writes only the protocol stream (an in-memory/stdio pair).
        # Emit human/log output to stderr to prove stdout stays clean.
        print("dhx mcp: serving", file=sys.stderr)

    monkeypatch.setattr(cli, "_run_stdio_blocking", _launch, raising=False)

    captured = io.StringIO()
    real_stdout = sys.stdout
    sys.stdout = captured
    try:
        code = cli.main(["mcp", str(target)])
    finally:
        sys.stdout = real_stdout
    assert code == cli.EXIT_OK
    assert captured.getvalue() == "", f"dhx mcp wrote to stdout: {captured.getvalue()!r}"


# --------------------------------------------------------------------------- #
# Existing forms still parse unchanged (Req 1.3).                              #
# --------------------------------------------------------------------------- #


def test_run_init_and_bare_forms_unchanged() -> None:
    parser = cli.build_parser()

    run_ns = parser.parse_args(["run", "/some/path", "--out", "/o"])
    assert run_ns.command == "run"
    assert run_ns.target_repo == "/some/path"

    init_ns = parser.parse_args(["init", "/proj", "--default"])
    assert init_ns.command == "init"
    assert init_ns.project_dir == "/proj"

    # Bare form: a leading path is normalised to `run <path>`, NOT `mcp <path>`.
    bare = cli._normalize_argv(["/some/repo", "--out", "/o"])
    assert bare == ["run", "/some/repo", "--out", "/o"]

    # `dhx mcp <path>` is left intact by the normaliser (mcp is a known subcommand).
    mcp_argv = cli._normalize_argv(["mcp", "/some/repo"])
    assert mcp_argv == ["mcp", "/some/repo"]
