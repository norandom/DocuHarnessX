"""Typed MCP input schemas + the structured error envelope (mcp-refine task 4.1).

This module is the **pure, SDK-light** half of the server factory: it owns the eight
:class:`mcp.types.Tool` descriptors (name + human description + JSON-Schema ``inputSchema``)
the server advertises (Req 3.1, 3.2), and the structured tool-error envelope the dispatch
layer returns for a missing/malformed argument or an unknown tool (Req 3.4, 3.5). It binds
**no** session and touches **no** model — the descriptors are static metadata, so the
protocol contract is enumerable and testable in-process without a model (Req 3.6, 10.3).

The descriptors are the single source of truth the dispatch layer (``mcp.server``) iterates:
:func:`tool_descriptors` returns them in a stable order, and :data:`TOOL_NAMES` is the matching
name set the dispatcher checks an incoming tool name against. The schemas mirror the handler
signatures in :mod:`docuharnessx.mcp.handlers` exactly:

* ``list_segments`` / ``reassemble_site`` / ``get_overview`` / ``draft_overview`` — no
  arguments (an empty object);
* ``get_segment`` / ``validate_segment`` — a required ``id`` string;
* ``rewrite_segment`` — a required ``id`` string + a required ``guidance`` string (the human
  refinement guidance, applied through the writer's additive ``guidance`` keyword, never
  echoed);
* ``refine_overview`` — a required ``guidance`` string.

The arguments are declared ``required`` so the low-level ``call_tool`` framework's
JSON-Schema validation rejects a missing argument **before** dispatch, and the dispatcher
also enforces them defensively (a structured tool error naming the offending argument), so a
malformed call never crashes the dispatch loop (Req 3.4).
"""

from __future__ import annotations

from typing import Any

import mcp.types as mt

__all__ = [
    "TOOL_NAMES",
    "tool_descriptors",
    "make_tool_error",
    "unknown_tool_error",
    "missing_argument_error",
]


# --------------------------------------------------------------------------- #
# Reusable JSON-Schema fragments                                              #
# --------------------------------------------------------------------------- #


def _object_schema(
    properties: dict[str, Any], required: list[str]
) -> dict[str, Any]:
    """A closed JSON-Schema object with the given properties and required keys.

    ``additionalProperties`` is ``False`` so an unexpected key is a validation error rather
    than silently ignored — the typed input contract is strict (Req 3.1, 3.4).
    """
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


_NO_ARGS = _object_schema({}, [])

_ID_PROPERTY = {
    "id": {
        "type": "string",
        "description": "The stored segment id (as returned by list_segments).",
    }
}

_GUIDANCE_PROPERTY = {
    "guidance": {
        "type": "string",
        "description": (
            "Human refinement guidance shaping WHAT the agent writes and emphasises. "
            "It is applied to the content, never quoted, named, or rendered as a "
            "heading/section in the result."
        ),
    }
}

_REPO_PROPERTY = {
    "repo": {
        "type": "string",
        "description": "Path to the target repository whose generated docs to refine.",
    }
}

_OUT_PROPERTY = {
    "out": {
        "type": "string",
        "description": (
            "The output directory a prior `dhx run` wrote (segments + site). Omit to use the "
            "documented per-target default (<repo>/.docuharnessx/out)."
        ),
    }
}

_CONFIG_PROPERTY = {
    "config": {
        "type": "string",
        "description": (
            "Optional path to a --config YAML selecting the model (config-then-env, like "
            "`dhx run`)."
        ),
    }
}


# --------------------------------------------------------------------------- #
# The eight tool descriptors                                                  #
# --------------------------------------------------------------------------- #
#
# Ordered: the read-only/model-free refine tools, then the model-touching rewrite, then the
# reassembly, then the overview tools. The order is stable for deterministic tool listing.

_TOOLS: tuple[mt.Tool, ...] = (
    mt.Tool(
        name="open_workspace",
        description=(
            "Open (or switch to) the documentation workspace the refine tools operate on: a "
            "target repository and the output directory a prior `dhx run` wrote. CALL THIS "
            "FIRST — the other tools act on the open workspace and return a structured error "
            "until one is open. `repo` is required; `out` defaults to the per-target path; "
            "`config` optionally selects the model. Returns the resolved repo/out, the segment "
            "count, the site name, and whether a model is configured."
        ),
        inputSchema=_object_schema(
            {**_REPO_PROPERTY, **_OUT_PROPERTY, **_CONFIG_PROPERTY}, ["repo"]
        ),
    ),
    mt.Tool(
        name="list_segments",
        description=(
            "List the drafted segments in the store's deterministic by-id order, each with "
            "its id, title, roles, intent, and subjects. Read-only and model-free."
        ),
        inputSchema=_NO_ARGS,
    ),
    mt.Tool(
        name="get_segment",
        description=(
            "Return one stored segment in full (id, title, roles, intent, subjects, summary, "
            "and Markdown body) by id. Read-only and model-free; a missing id yields a "
            "structured result naming the id."
        ),
        inputSchema=_object_schema(dict(_ID_PROPERTY), ["id"]),
    ),
    mt.Tool(
        name="rewrite_segment",
        description=(
            "Rewrite one stored segment to the supplied guidance: the bounded agentic writer "
            "re-explores the read-only target repository and regenerates the body, which is "
            "persisted in place only when it passes the structure gate (>=1 Mermaid diagram + "
            ">= the minimum distinct file:line citations). On reject the gate verdict and the "
            "deterministic fallback are surfaced and nothing is persisted. Requires a "
            "configured model."
        ),
        inputSchema=_object_schema(
            {**_ID_PROPERTY, **_GUIDANCE_PROPERTY}, ["id", "guidance"]
        ),
    ),
    mt.Tool(
        name="validate_segment",
        description=(
            "Run the deterministic structure gate over a stored segment's body and return the "
            "verdict (accepted, mermaid_blocks, cited_files, reason) at the same threshold the "
            "rewrite path enforces. Read-only and model-free; a missing id yields a structured "
            "result naming the id."
        ),
        inputSchema=_object_schema(dict(_ID_PROPERTY), ["id"]),
    ),
    mt.Tool(
        name="reassemble_site",
        description=(
            "Rebuild the themed Material site from the current store segments plus the "
            "persisted overview, returning the site directory and the per-segment / per-role "
            "page counts. Deterministic and model-free; writes only under the output dir."
        ),
        inputSchema=_NO_ARGS,
    ),
    mt.Tool(
        name="get_overview",
        description=(
            "Return the persisted narrative overview body, or an explicit 'no overview drafted "
            "yet' result when none exists. Read-only and model-free."
        ),
        inputSchema=_NO_ARGS,
    ),
    mt.Tool(
        name="draft_overview",
        description=(
            "Draft the grounded narrative overview (Purpose / Use cases / Features / Design "
            "choices) from scratch by running the bounded agentic writer over the read-only "
            "target repository; persisted only when it passes the structure gate. Requires a "
            "configured model."
        ),
        inputSchema=_NO_ARGS,
    ),
    mt.Tool(
        name="refine_overview",
        description=(
            "Refine the narrative overview to the supplied guidance, re-grounded through the "
            "bounded agentic writer and gated before persistence. The guidance shapes WHAT the "
            "overview covers and is never echoed into it. Requires a configured model."
        ),
        inputSchema=_object_schema(dict(_GUIDANCE_PROPERTY), ["guidance"]),
    ),
)

#: The set of registered tool names — the dispatcher checks an incoming name against this so an
#: unknown tool is a structured error rather than an uncaught raise (Req 3.5).
TOOL_NAMES: frozenset[str] = frozenset(tool.name for tool in _TOOLS)


def tool_descriptors() -> list[mt.Tool]:
    """The eight typed :class:`mcp.types.Tool` descriptors in a stable order (Req 3.1, 3.2).

    Returns a fresh list (the same descriptor objects) the ``list_tools`` handler advertises
    and the dispatcher iterates. Pure: binds no session and consults no model.
    """
    return list(_TOOLS)


# --------------------------------------------------------------------------- #
# Structured tool-error envelopes                                             #
# --------------------------------------------------------------------------- #
#
# A protocol-level failure (unknown tool, missing/malformed argument) is returned as an
# ``mcp.types.CallToolResult`` with ``isError=True`` — the low-level framework passes a
# returned ``CallToolResult`` straight through, so the dispatch loop never crashes (Req 3.4,
# 3.5). The error text names the offending tool / argument so the client can correct the call.


def make_tool_error(message: str, *, structured: dict[str, Any] | None = None) -> mt.CallToolResult:
    """A structured MCP tool error (``isError=True``) carrying ``message`` as text content.

    The optional ``structured`` mapping is surfaced as ``structuredContent`` so a programmatic
    client can branch on it; the human-readable ``message`` is always present as a
    :class:`mcp.types.TextContent` block.
    """
    return mt.CallToolResult(
        content=[mt.TextContent(type="text", text=message)],
        structuredContent=structured,
        isError=True,
    )


def unknown_tool_error(name: str) -> mt.CallToolResult:
    """A structured tool error for an unregistered tool ``name`` (Req 3.5)."""
    return make_tool_error(
        f"unknown tool {name!r}; the registered tools are: "
        f"{', '.join(sorted(TOOL_NAMES))}",
        structured={"error": True, "code": "unknown_tool", "tool": name},
    )


def missing_argument_error(tool: str, argument: str) -> mt.CallToolResult:
    """A structured tool error for a missing/malformed required ``argument`` (Req 3.4)."""
    return make_tool_error(
        f"tool {tool!r} requires a string argument {argument!r}",
        structured={
            "error": True,
            "code": "missing_argument",
            "tool": tool,
            "argument": argument,
        },
    )


def no_workspace_error(tool: str) -> mt.CallToolResult:
    """A structured error: a tool was called before a workspace was opened (Req 2.x).

    The output directory is set by the agent via ``open_workspace`` rather than hardcoded at
    launch, so a tool that needs the workspace returns this (never a crash) until one is open.
    """
    return make_tool_error(
        f"tool {tool!r} needs an open workspace; call "
        "open_workspace(repo=..., out=...) first",
        structured={"error": True, "code": "no_workspace", "tool": tool},
    )


def open_workspace_failed_error(repo: str, reason: str) -> mt.CallToolResult:
    """A structured error when ``open_workspace`` could not resolve the workspace."""
    return make_tool_error(
        f"could not open workspace for {repo!r}: {reason}",
        structured={"error": True, "code": "open_failed", "repo": repo},
    )
