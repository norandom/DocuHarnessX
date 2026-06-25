"""The stdio MCP refine server factory + dispatch (mcp-refine task 4.1).

:func:`build_refine_server` constructs a low-level :class:`mcp.server.Server` bound to a
per-target :class:`~docuharnessx.mcp.session.RefineSession` and registers the **eight**
refine/overview tools (Req 3.1):

* read-only / model-free: ``list_segments``, ``get_segment``, ``validate_segment``,
  ``reassemble_site``, ``get_overview``;
* model-touching (bounded agentic writer + structure gate): ``rewrite_segment``,
  ``draft_overview``, ``refine_overview``.

A ``@server.list_tools()`` handler advertises the typed :class:`mcp.types.Tool` descriptors
from :mod:`docuharnessx.mcp.schemas` (Req 3.2). A ``@server.call_tool()`` handler is the
single **dispatch layer**: it validates arguments, dispatches to the matching handler over the
bound session, **offloads the synchronous, model-touching handlers off the async loop** via
:func:`asyncio.to_thread` (so the runner's private event loop never nests in the server's
loop; design "Server"), wraps a handler's structured result as MCP content, and returns a
**structured tool error** for a missing/malformed argument (Req 3.4) or an unknown tool
(Req 3.5) — it **never raises out of the dispatch loop** (a handler exception is caught and
turned into a structured error too).

The factory and the registered handlers are exercisable **in-process** — no stdio subprocess,
no model — by invoking the handlers the decorators register into ``server.request_handlers``
with the matching MCP request objects (Req 3.6, 10.3). Argument validation is owned here
(``validate_input=False``) so a malformed call yields a clear, argument-naming structured
error rather than the framework's generic JSON-Schema message. The server logs to **stderr**
so stdout stays the MCP protocol channel (the stdio launcher is task 4.2).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, AsyncContextManager, Awaitable, Callable

import mcp.types as mt
from mcp.server import Server
from mcp.server.stdio import stdio_server

from docuharnessx.mcp import handlers, schemas

if TYPE_CHECKING:  # pragma: no cover - typing only
    from docuharnessx.mcp.session import RefineSession

__all__ = ["build_refine_server", "run_stdio"]

#: The server logs to stderr (the stdio transport owns stdout; design "Monitoring").
_LOGGER = logging.getLogger("docuharnessx.mcp.server")

#: The MCP server name advertised in the initialization handshake.
_SERVER_NAME = "docuharnessx-refine"


def _str_argument(
    arguments: dict[str, Any], tool: str, argument: str
) -> tuple[str | None, mt.CallToolResult | None]:
    """Extract a required **string** ``argument``, or a structured error (Req 3.4).

    Returns ``(value, None)`` when ``argument`` is present and a string; otherwise
    ``(None, error)`` where ``error`` is the structured missing-argument tool error naming the
    offending argument, so a malformed call never reaches a handler or crashes dispatch.
    """
    value = arguments.get(argument)
    if not isinstance(value, str):
        return None, schemas.missing_argument_error(tool, argument)
    return value, None


def build_refine_server(session: "RefineSession") -> Server:
    """Build the low-level MCP :class:`Server` bound to ``session`` (Req 3.1-3.6).

    Registers the ``list_tools`` advertiser and the ``call_tool`` dispatcher; the returned
    server is ready for the stdio launcher (task 4.2) and is fully exercisable in-process for
    the dispatch tests (no stdio subprocess, no model required).
    """
    server: Server = Server(_SERVER_NAME)

    @server.list_tools()
    async def _list_tools() -> list[mt.Tool]:
        """Advertise the eight typed tool descriptors (Req 3.1, 3.2)."""
        return schemas.tool_descriptors()

    # The synchronous, read-only / model-free handlers — dispatched directly (no offload).
    _sync_dispatch: dict[str, Callable[[], dict[str, Any]]] = {
        "list_segments": lambda: {"segments": handlers.list_segments(session)},
        "reassemble_site": lambda: handlers.reassemble_site(session),
        "get_overview": lambda: handlers.get_overview(session),
    }

    # The model-touching, async handlers — already coroutine functions that offload the
    # synchronous bounded writer off the event loop via asyncio.to_thread internally
    # (handlers.py), so dispatch simply awaits them.
    _async_dispatch: dict[str, Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]] = {
        "draft_overview": lambda _args: handlers.draft_overview(session),
    }

    @server.call_tool(validate_input=False)
    async def _call_tool(name: str, arguments: dict[str, Any]) -> Any:
        """Validate, dispatch, and wrap — never raising out of the dispatch loop.

        Returns either a JSON-serialisable ``dict`` (the framework wraps it as
        ``structuredContent`` + a JSON text block, ``isError=False``) or an
        :class:`mcp.types.CallToolResult` with ``isError=True`` for an unknown tool / missing
        argument (the framework passes a returned ``CallToolResult`` straight through). Any
        unexpected handler exception is caught and surfaced as a structured error so the loop
        survives (Req 3.3, 3.4, 3.5).
        """
        arguments = arguments or {}

        # Unknown tool -> structured error, never a raise (Req 3.5).
        if name not in schemas.TOOL_NAMES:
            _LOGGER.warning("call_tool: unknown tool %r", name)
            return schemas.unknown_tool_error(name)

        try:
            # No-argument, model-free synchronous tools.
            if name in _sync_dispatch:
                return _sync_dispatch[name]()

            # ``get_segment`` / ``validate_segment`` — a required ``id`` string.
            if name in ("get_segment", "validate_segment"):
                segment_id, err = _str_argument(arguments, name, "id")
                if err is not None:
                    return err
                if name == "get_segment":
                    return handlers.get_segment(session, segment_id)
                return handlers.validate_segment(session, segment_id)

            # ``rewrite_segment`` — required ``id`` + ``guidance`` (model-touching; awaited).
            if name == "rewrite_segment":
                segment_id, err = _str_argument(arguments, name, "id")
                if err is not None:
                    return err
                guidance, err = _str_argument(arguments, name, "guidance")
                if err is not None:
                    return err
                return await handlers.rewrite_segment(session, segment_id, guidance)

            # ``refine_overview`` — a required ``guidance`` (model-touching; awaited).
            if name == "refine_overview":
                guidance, err = _str_argument(arguments, name, "guidance")
                if err is not None:
                    return err
                return await handlers.refine_overview(session, guidance)

            # ``draft_overview`` — no arguments (model-touching; awaited).
            return await _async_dispatch[name](arguments)
        except Exception as exc:  # pragma: no cover - defensive: the loop must never crash
            # A handler should not raise for a domain condition (it returns a structured
            # result), but any unexpected error is contained here so the dispatch loop stays
            # alive (Req 3.4-3.5). Logged to stderr; surfaced as a structured tool error.
            _LOGGER.exception("call_tool: handler for %r raised", name)
            return schemas.make_tool_error(
                f"tool {name!r} failed unexpectedly: {exc}",
                structured={"error": True, "code": "handler_error", "tool": name},
            )

    return server


async def run_stdio(
    session: "RefineSession",
    *,
    transport: Callable[[], AsyncContextManager[Any]] = stdio_server,
) -> None:
    """Drive the refine :class:`Server` over the stdio transport (task 4.2; Req 2.5, 3.6).

    Opens the stdio ``transport`` (the SDK's :func:`mcp.server.stdio.stdio_server` by default,
    which re-wraps the **inherited** process ``stdin``/``stdout`` as the MCP read/write
    streams), builds the server via :func:`build_refine_server`, and awaits
    :meth:`Server.run` over those streams with :meth:`Server.create_initialization_options`.
    The server loop runs until the read stream closes (the client disconnects), then returns.

    The launcher writes **nothing** to stdout except the MCP protocol stream — the transport
    owns stdout and the server logs to stderr (design "Monitoring") — so the ``dhx mcp``
    command's stdout stays a clean protocol channel. The ``dhx mcp`` launcher calls this via
    :func:`asyncio.run`.

    The ``transport`` factory is injectable so the launcher is exercisable against in-memory
    streams (a memory-object-stream pair mirroring ``stdio_server``'s yield), letting a test
    drive a real initialize -> disconnect exchange to termination without a stdio subprocess
    and without a model.
    """
    server = build_refine_server(session)
    init_options = server.create_initialization_options()
    _LOGGER.info("docuharnessx-refine MCP server starting over stdio")
    async with transport() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, init_options)
    _LOGGER.info("docuharnessx-refine MCP server stopped")
