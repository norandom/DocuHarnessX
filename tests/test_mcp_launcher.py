"""The stdio launcher + public-surface re-export (mcp-refine task 4.2).

Task 4.2 owns two observable contracts:

* :func:`docuharnessx.mcp.server.run_stdio` opens the stdio transport, builds the server via
  :func:`build_refine_server`, and drives :meth:`mcp.server.Server.run` over the inherited
  read/write streams with :meth:`Server.create_initialization_options`. The launcher writes
  **nothing** to stdout except the MCP protocol stream (logs go to stderr; the stdio transport
  owns stdout) (Req 2.5, 3.6).
* The package ``docuharnessx.mcp`` re-exports the public surface — ``build_refine_server`` and
  ``run_stdio`` alongside ``RefineSession`` / ``resolve_session`` / the eight handlers — from
  one namespace, so the ``dhx mcp`` launcher and the tests import the MCP surface from a single
  place and no second generation engine is introduced (Req 1.5).

These tests are credential-free: the launcher is driven against **in-memory** streams (the
same memory-object-stream pair the SDK's ``stdio_server`` yields) so a real initialize ->
shutdown exchange terminates ``Server.run`` without a stdio subprocess and without a model.
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import sys

import anyio
import mcp.types as mt
import pytest
from mcp.shared.message import SessionMessage

from docuharnessx.mcp.server import build_refine_server, run_stdio
from docuharnessx.mcp.session import RefineSession
from docuharnessx.ontology import AxisTerm, FilesystemSegmentStore, Vocabulary

_PUBLIC_SURFACE = {
    "RefineSession",
    "resolve_session",
    "planned_from_segment",
    "build_overview_blueprint",
    "list_segments",
    "get_segment",
    "validate_segment",
    "rewrite_segment",
    "draft_overview",
    "refine_overview",
    "get_overview",
    "reassemble_site",
    "build_refine_server",
    "run_stdio",
}


def _vocab() -> Vocabulary:
    return Vocabulary(
        roles=(AxisTerm("platform-dev", "Platform Developer", "Builds on the platform."),),
        intents=(AxisTerm("extend", "Extend", "Add capabilities."),),
        subject_prefixes=("component:", "tech:", "artifact:", "topic:"),
    )


def _session(tmp_path) -> RefineSession:
    """A model-free RefineSession over a real (empty) store — no model, no network."""
    vocab = _vocab()
    store = FilesystemSegmentStore(str(tmp_path / "segments"), vocab)
    return RefineSession(
        out_dir=str(tmp_path / "out"),
        target_repo=str(tmp_path),
        vocab=vocab,
        store=store,
        model_config=None,
        identity=object(),
        analysis=None,
    )


# --------------------------------------------------------------------------- #
# Public-surface re-export (Req 1.5).                                          #
# --------------------------------------------------------------------------- #


def test_package_reexports_the_public_surface() -> None:
    import docuharnessx.mcp as pkg

    # Req 1.5: build_refine_server + run_stdio join the session/handlers in __all__.
    assert "build_refine_server" in pkg.__all__
    assert "run_stdio" in pkg.__all__
    assert _PUBLIC_SURFACE.issubset(set(pkg.__all__))
    # No duplicates; every advertised name resolves on the package.
    assert len(pkg.__all__) == len(set(pkg.__all__))
    for name in pkg.__all__:
        assert hasattr(pkg, name), f"__all__ advertises {name!r} but it is absent"


def test_run_stdio_reexport_is_identity_equal_to_the_submodule() -> None:
    import docuharnessx.mcp as pkg
    from docuharnessx.mcp import server

    # The re-exports are identity-equal to their submodule definitions (no shadow copies).
    assert pkg.run_stdio is server.run_stdio
    assert pkg.build_refine_server is server.build_refine_server


# --------------------------------------------------------------------------- #
# In-memory launcher helpers (no stdio subprocess, no model).                  #
# --------------------------------------------------------------------------- #


def _jsonrpc(message: dict) -> SessionMessage:
    return SessionMessage(mt.JSONRPCMessage.model_validate(message))


async def _drive_launcher_in_memory(session: RefineSession) -> list[SessionMessage]:
    """Drive ``run_stdio`` against in-memory streams that terminate the server.

    Builds the same memory-object-stream pair ``stdio_server`` yields, feeds a real
    ``initialize`` request + ``notifications/initialized``, then closes the inbound stream so
    ``Server.run`` exits cleanly. Returns the protocol messages the server wrote.
    """
    # client -> server (the server's read side)
    read_writer, read_stream = anyio.create_memory_object_stream(100)
    # server -> client (the server's write side)
    write_stream, write_reader = anyio.create_memory_object_stream(100)

    @contextlib.asynccontextmanager
    async def _fake_transport():
        yield read_stream, write_stream

    # Seed a minimal valid initialize handshake, then close the inbound stream so the
    # server's read loop ends and Server.run returns.
    await read_writer.send(
        _jsonrpc(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": mt.LATEST_PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "test-client", "version": "0.0.0"},
                },
            }
        )
    )
    await read_writer.aclose()

    written: list[SessionMessage] = []

    async def _collect() -> None:
        async with write_reader:
            async for msg in write_reader:
                written.append(msg)

    async with anyio.create_task_group() as tg:
        tg.start_soon(_collect)
        await run_stdio(session, transport=_fake_transport)

    return written


# --------------------------------------------------------------------------- #
# run_stdio wires the built server to the (in-memory) stdio streams (Req 2.5). #
# --------------------------------------------------------------------------- #


def test_run_stdio_drives_the_server_over_the_transport_streams(tmp_path) -> None:
    session = _session(tmp_path)
    written = asyncio.run(_drive_launcher_in_memory(session))

    # The server answered the initialize handshake over the write stream — i.e. run_stdio
    # actually wired build_refine_server's server to the transport's read/write streams.
    assert written, "run_stdio wrote no protocol messages to the write stream"
    payloads = [m.message.model_dump(by_alias=True, exclude_none=True) for m in written]
    init_results = [p for p in payloads if p.get("id") == 1 and "result" in p]
    assert init_results, f"no initialize result among {payloads!r}"
    server_info = init_results[0]["result"]["serverInfo"]
    assert server_info["name"] == "docuharnessx-refine"


def test_run_stdio_writes_nothing_to_real_stdout(tmp_path) -> None:
    # The launcher must keep the real process stdout clean (only the transport's stream is
    # the MCP channel; here that is an in-memory pair). Req 2.5 / 3.6.
    session = _session(tmp_path)
    captured = io.StringIO()
    real_stdout = sys.stdout
    sys.stdout = captured
    try:
        asyncio.run(_drive_launcher_in_memory(session))
    finally:
        sys.stdout = real_stdout
    assert captured.getvalue() == "", f"run_stdio wrote to stdout: {captured.getvalue()!r}"


def test_run_stdio_default_transport_is_stdio_server() -> None:
    # By default run_stdio uses the SDK's stdio_server transport (the inherited streams);
    # the injectable transport is only for the in-memory drive above.
    import inspect

    from mcp.server.stdio import stdio_server

    sig = inspect.signature(run_stdio)
    assert "transport" in sig.parameters
    assert sig.parameters["transport"].default is stdio_server
