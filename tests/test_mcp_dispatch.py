"""In-process tool registration + dispatch + error envelopes (mcp-refine task 4.1).

Task 4.1 owns ``docuharnessx.mcp.schemas`` (the typed input schemas + the structured
result/error envelopes) and ``docuharnessx.mcp.server.build_refine_server(session)`` — a
low-level :class:`mcp.server.Server` that registers the **eight** refine/overview tools
(``list_segments`` / ``get_segment`` / ``rewrite_segment`` / ``validate_segment`` /
``reassemble_site`` / ``get_overview`` / ``draft_overview`` / ``refine_overview``) via the
``list_tools`` / ``call_tool`` decorators, validates arguments, dispatches to the matching
handler over the bound :class:`~docuharnessx.mcp.session.RefineSession`, wraps the result as
MCP content, and returns a **structured tool error** for a missing/malformed argument or an
unknown tool **without crashing the dispatch loop** (Req 3.1-3.6, 10.3).

These tests exercise the factory **in-process** — no stdio subprocess, no model — by invoking
the handlers the decorators register into ``server.request_handlers`` with the matching MCP
request objects, exactly as the protocol layer would. They build a real
:class:`FilesystemSegmentStore` over a tmp dir and a model-free :class:`RefineSession`, so the
whole protocol contract is testable credential-free.
"""

from __future__ import annotations

import asyncio

import mcp.types as mt
import pytest

from docuharnessx.composition import MIN_CITED_FILES, validate_agent_body
from docuharnessx.composition.blueprint import build_blueprint
from docuharnessx.composition.model import ProseResult
from docuharnessx.composition.wiring import wire_segment
from docuharnessx.mcp import handlers
from docuharnessx.mcp.server import build_refine_server
from docuharnessx.mcp.session import RefineSession
from docuharnessx.ontology import (
    AxisTerm,
    FilesystemSegmentStore,
    Segment,
    Subject,
    Vocabulary,
)
from docuharnessx.planning.model import PlannedSegment

# The eight tools the server registers (Req 3.1).
_EXPECTED_TOOLS = {
    "list_segments",
    "get_segment",
    "rewrite_segment",
    "validate_segment",
    "reassemble_site",
    "get_overview",
    "draft_overview",
    "refine_overview",
}

_PREFIXES = frozenset({"component", "tech", "artifact", "topic"})

_GROUNDED_BODY = (
    "## Overview\n\n"
    "```mermaid\n"
    "graph TD\n"
    "  A --> B\n"
    "```\n\n"
    "The CLI entrypoint lives in cli.py:10 and dispatches to the runner in "
    "agent.py:42, validated by gate.py:7.\n"
)


def _subject(raw: str) -> Subject:
    return Subject.parse(raw, _PREFIXES)


def _vocab() -> Vocabulary:
    return Vocabulary(
        roles=(
            AxisTerm("platform-dev", "Platform Developer", "Builds on the platform."),
            AxisTerm("auditor", "Compliance Auditor", "Assesses compliance."),
        ),
        intents=(
            AxisTerm("extend", "Extend", "Add capabilities."),
            AxisTerm("review", "Review", "Judge quality."),
        ),
        subject_prefixes=("component:", "tech:", "artifact:", "topic:"),
    )


def _stored_segment(vocab: Vocabulary) -> Segment:
    roles = ("platform-dev", "auditor")
    intent = "extend"
    subjects = (_subject("component:cli"), _subject("tech:python"))
    planned = PlannedSegment(
        segment_key="platform-dev,auditor__extend__seed",
        roles=roles,
        intent=intent,
        subjects=subjects,
        priority=0,
        evidence=(),
    )
    blueprint = build_blueprint(planned, None, vocab)
    return wire_segment(
        planned,
        blueprint,
        ProseResult(body=_GROUNDED_BODY, summary="A grounded segment.", source="fake"),
    )


def _session(tmp_path) -> RefineSession:
    """A model-free RefineSession over a real store seeded with one grounded segment."""
    vocab = _vocab()
    store = FilesystemSegmentStore(str(tmp_path / "segments"), vocab)
    store.put(_stored_segment(vocab))
    return RefineSession(
        out_dir=str(tmp_path / "out"),
        target_repo=str(tmp_path),
        vocab=vocab,
        store=store,
        model_config=None,  # no model — the dispatch layer is model-free
        identity=object(),
        analysis=None,
    )


# --------------------------------------------------------------------------- #
# In-process protocol helpers (no stdio subprocess, no model).                 #
# --------------------------------------------------------------------------- #


def _list_tools(server) -> list[mt.Tool]:
    handler = server.request_handlers[mt.ListToolsRequest]
    result = asyncio.run(handler(mt.ListToolsRequest(method="tools/list")))
    return list(result.root.tools)


def _call_tool(server, name: str, arguments: dict | None) -> mt.CallToolResult:
    handler = server.request_handlers[mt.CallToolRequest]
    req = mt.CallToolRequest(
        method="tools/call",
        params=mt.CallToolRequestParams(name=name, arguments=arguments),
    )
    result = asyncio.run(handler(req))
    return result.root


# --------------------------------------------------------------------------- #
# Registration (Req 3.1, 3.2).                                                 #
# --------------------------------------------------------------------------- #


def test_build_refine_server_registers_the_eight_tools_with_schemas(tmp_path) -> None:
    server = build_refine_server(_session(tmp_path))
    tools = _list_tools(server)

    names = {tool.name for tool in tools}
    assert names == _EXPECTED_TOOLS
    assert len(tools) == 8  # no duplicates

    for tool in tools:
        # Each tool advertises a human description and an object-typed input schema (Req 3.1).
        assert tool.description, f"{tool.name} has no description"
        assert isinstance(tool.inputSchema, dict)
        assert tool.inputSchema.get("type") == "object"
        assert "properties" in tool.inputSchema


def test_argument_tools_declare_their_required_arguments(tmp_path) -> None:
    server = build_refine_server(_session(tmp_path))
    by_name = {tool.name: tool for tool in _list_tools(server)}

    # The id-taking tools require ``id``; rewrite/refine require their text args.
    assert "id" in by_name["get_segment"].inputSchema.get("required", [])
    assert "id" in by_name["validate_segment"].inputSchema.get("required", [])
    assert "id" in by_name["rewrite_segment"].inputSchema.get("required", [])
    assert "guidance" in by_name["rewrite_segment"].inputSchema.get("required", [])
    assert "guidance" in by_name["refine_overview"].inputSchema.get("required", [])

    # The no-argument tools accept an empty object.
    for nullary in ("list_segments", "reassemble_site", "get_overview", "draft_overview"):
        assert by_name[nullary].inputSchema.get("required", []) == []


# --------------------------------------------------------------------------- #
# Dispatch of valid calls (Req 3.3).                                          #
# --------------------------------------------------------------------------- #


def test_dispatch_list_segments_returns_structured_content(tmp_path) -> None:
    session = _session(tmp_path)
    server = build_refine_server(session)

    result = _call_tool(server, "list_segments", {})

    assert result.isError is False
    # The handler's structured result is surfaced as a list under a documented key.
    stored = session.store.list_segments()
    listed = result.structuredContent["segments"]
    assert [entry["id"] for entry in listed] == [s.id for s in stored]
    # And there is at least one text content block for the human-facing client.
    assert result.content and result.content[0].type == "text"


def test_dispatch_validate_segment_returns_the_gate_verdict(tmp_path) -> None:
    session = _session(tmp_path)
    server = build_refine_server(session)
    target = session.store.list_segments()[0]

    result = _call_tool(server, "validate_segment", {"id": target.id})

    assert result.isError is False
    expected = validate_agent_body(target.body, min_citations=session.min_citations)
    assert result.structuredContent["accepted"] == expected.accepted
    assert result.structuredContent["mermaid_blocks"] == expected.mermaid_blocks
    assert result.structuredContent["cited_files"] == expected.cited_files


def test_dispatch_get_segment_missing_id_is_a_domain_result_not_a_crash(tmp_path) -> None:
    # A missing-but-well-formed id is a structured DOMAIN result from the handler (the call
    # itself succeeds — the dispatch loop never crashes). Req 4.3 + 3.3.
    session = _session(tmp_path)
    server = build_refine_server(session)

    result = _call_tool(server, "get_segment", {"id": "no-such-id"})

    assert result.structuredContent.get("error") is True
    assert "no-such-id" in result.structuredContent["message"]


# --------------------------------------------------------------------------- #
# Structured errors: malformed args + unknown tool (Req 3.4, 3.5).             #
# --------------------------------------------------------------------------- #


def test_missing_required_argument_returns_structured_error_not_raise(tmp_path) -> None:
    server = build_refine_server(_session(tmp_path))

    # ``get_segment`` requires ``id``; calling it with none must NOT raise out of dispatch.
    result = _call_tool(server, "get_segment", {})

    assert result.isError is True
    assert result.content and result.content[0].type == "text"
    # The error names the offending argument (Req 3.4).
    assert "id" in result.content[0].text


def test_unknown_tool_returns_structured_error_not_raise(tmp_path) -> None:
    server = build_refine_server(_session(tmp_path))

    result = _call_tool(server, "no_such_tool", {})

    assert result.isError is True
    assert result.content and result.content[0].type == "text"
    assert "no_such_tool" in result.content[0].text


def test_dispatch_loop_survives_a_sequence_of_good_and_bad_calls(tmp_path) -> None:
    # The dispatch loop must never crash: a bad call followed by a good one both return.
    server = build_refine_server(_session(tmp_path))

    bad = _call_tool(server, "no_such_tool", {})
    assert bad.isError is True

    good = _call_tool(server, "list_segments", {})
    assert good.isError is False


def test_schemas_module_exposes_the_eight_tool_descriptors() -> None:
    from docuharnessx.mcp import schemas

    descriptors = schemas.tool_descriptors()
    assert {tool.name for tool in descriptors} == _EXPECTED_TOOLS
    # The descriptors are the same typed mcp Tool objects the server registers.
    assert all(isinstance(tool, mt.Tool) for tool in descriptors)
