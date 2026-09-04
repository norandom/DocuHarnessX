---
id: component:mcp
title: What does mcp do?
subjects:
- mcp
summary: '`docuharnessx.mcp` is a **Model Context Protocol (MCP) server package that
  lets a human conversationally refine already-generated documentation**. It is described
  in its own docstring as "the stdio MCP refine server" (`docuharnessx/mcp/__init__.py:1`)
  and is the single public namespace for that interactive document-refinement service.'
related: []
cited_files:
- docuharnessx/mcp/__init__.py
- docuharnessx/mcp/server.py
- docuharnessx/mcp/session.py
- docuharnessx/mcp/schemas.py
- docuharnessx/mcp/overview.py
- docuharnessx/mcp/planned.py
---
`docuharnessx.mcp` is a **Model Context Protocol (MCP) server package that lets a human conversationally refine already-generated documentation**. It is described in its own docstring as "the stdio MCP refine server" (`docuharnessx/mcp/__init__.py:1`) and is the single public namespace for that interactive document-refinement service.

Here is what the code actually shows it doing:

## It is a thin "refine" layer on top of a batch run, not a new generator

The workflow is: a batch `dhx run` first produces role-based draft segments persisted as `<id>.md` under `<out>/segments` and a built Material site under `<out>/site`; then "a human opens the output in an MCP client (opencode / Claude Code / Cursor) and conversationally refines the documentation through the tools this package exposes" (`docuharnessx/mcp/__init__.py:4-9`). The package is explicitly "a **thin composition layer** over DocuHarnessX's existing modular core" that reuses `AgenticProseRunner`, `validate_agent_body`, the blueprint builder, `assemble_site`, and the model resolver, and builds "**no** second generation engine and no RAG / embedding / vector index" (`docuharnessx/mcp/__init__.py:9-16`).

## It runs as an MCP server speaking MCP over stdio

`build_refine_server` constructs a low-level `mcp.server.Server` named `docuharnessx-refine` (`docuharnessx/mcp/server.py:88-98`, name at `server.py:54`), registers a `@server.list_tools()` advertiser returning the typed `mcp.types.Tool` descriptors from `docuharnessx.mcp.schemas` (`server.py:101-104`), and a single `@server.call_tool(validate_input=False)` dispatcher that validates arguments, dispatches to handlers over the bound session, and never lets an exception escape the loop (`server.py:128-138`). `run_stdio` drives that server over the SDK's `stdio_server` transport, running `server.run(read_stream, write_stream, init_options)` and returning when the client disconnects (`docuharnessx/mcp/server.py:206-233`).

## The workspace is per-target and agent-set

A `RefineSession` dataclass holds the per-target state: `out_dir`, `target_repo`, the loaded `Vocabulary`, a `FilesystemSegmentStore` rooted at `<out>/segments`, an optional `ModelConfig`, the per-target `SiteIdentity`, optional `RepoAnalysis`, a `min_citations` bar, and a living-page store (`docuharnessx/mcp/session.py:67-88`). `resolve_session` validates the target repo first, defaults the output dir to `<target>/.docuharnessx/out`, loads the project vocabulary, provisions the segment store, resolves the site identity from the origin remote, and swallows a no-model `ModelResolutionError` to `None` so the server still starts (`docuharnessx/mcp/session.py:103-168`). The dispatcher treats `open_workspace` specially: the agent supplies `repo`/`out`/`config` at call time, `resolve_session` is invoked, and every other tool returns a structured no-workspace error until one is open (`server.py:106-126`, `server.py:147-155`).

## It exposes nine tools for reading, rewriting, and reassembling

`docuharnessx/mcp/schemas.py:120-212` owns the `mt.Tool` descriptors: `open_workspace`, the read-only/model-free `list_segments`, `get_segment`, `validate_segment`, `reassemble_site`, `get_overview`, and the model-touching `rewrite_segment`, `draft_overview`, `refine_overview`; `TOOL_NAMES` is the matching set the dispatcher checks against (`schemas.py:216`, dispatch check at `server.py:142-144`). Handlers live in `docuharnessx/mcp/handlers.py` and follow a "return a structured result, never raise for an expected domain condition" contract (`handlers.py:6-8`): a missing id yields the `_missing_segment_error` envelope (`handlers.py:95-107`) and a missing model yields `_no_model_result` (`handlers.py:110-129`).

- **Read tools** (`handlers.py:203-316`) read lazily from the session's store: `list_segments` returns each segment's `id`/`title`/`roles`/`intent`/`subjects`, `get_segment` adds `summary` and the Markdown `body`, and `validate_segment` runs the deterministic structure gate `validate_agent_body` at the same `session.min_citations` threshold the rewrite path enforces (`handlers.py:293-316`).
- **`rewrite_segment`** is the re-grounded rewrite: it reconstructs the segment's deterministic blueprint via `planned_from_segment` + `build_blueprint`, runs the bounded `AgenticProseRunner` over the read-only target repo with the human `guidance` passed as the writer's additive keyword, offloaded with `asyncio.to_thread` (`handlers.py:524-539`); on an accepted verdict it wires and overwrites the stored `<id>.md` in place via `_replace_segment_in_place` (`handlers.py:561-562`, helper at `handlers.py:324-354`), and on failure it surfaces the gate verdict over `render_fallback_body` and persists nothing (`handlers.py:542-558`).
- **Overview tools** build a dedicated overview-shaped blueprint whose four chunks are *Purpose / Use cases / Features / Design choices* (`docuharnessx/mcp/overview.py:107-112`, builder at `overview.py:281`) and persist the reserved first-class entry `overview.md` (`OVERVIEW_SEGMENT_ID = "overview"`, `overview.py:100`) in `<out>/segments` — `draft_overview` writes it from scratch, `refine_overview` re-runs the writer with guidance, and `get_overview` reads it back lazily (`handlers.py:689-762`).
- **`reassemble_site`** is the only assembling tool and is strictly model-free: it builds a `ReviewReport` whose `accepted` set is the current store segments plus the persisted overview (adapted by `_overview_accepted_entry` so the frozen `assemble_site` can accept the role-free overview), then calls the reused `assemble_site` and returns `site_dir`/`page_count`/`role_page_count` (`handlers.py:873-967`).

## Stable-id round-tripping makes rewrite-in-place possible

`docuharnessx/mcp/planned.py` exists because the `FilesystemSegmentStore` has no `update` method and `put` rejects an existing id — so a rewrite must reproduce the stored id exactly. `planned_from_segment` re-derives the planner's deterministic `segment_key` of the form `"<roles-joined>__<intent>__<subjects-digest>"` from fields that are persisted on the `Segment`, guaranteeing `segment_id(planned_from_segment(seg)) == seg.id` so the same `<id>.md` is re-serialised in place (`docuharnessx/mcp/planned.py:12-23`, `planned.py:102-141`).

In short: `mcp` turns the artifacts of a `dhx run` into a live, per-target refinement surface for MCP clients — reading stored segments, validating their structure, rewriting or drafting them through the reused bounded agentic writer plus structure gate, and deterministically reassembling the themed Material site — all while avoiding any second generation engine.