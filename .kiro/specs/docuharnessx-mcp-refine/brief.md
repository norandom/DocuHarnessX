# Brief — docuharnessx-mcp-refine

## Feature

A **stdio MCP (Model Context Protocol) server** that exposes DocuHarnessX's own
document-refinement tools to an interactive MCP client (**opencode** primarily; also
Claude Code / Cursor). After a batch `dhx` run produces the role-based draft (segments
under `<out>/segments`, a built Material site under `<out>/site`), a human opens the
output in opencode and **conversationally refines** the documentation USING these tools —
with the project's strong grounding / anti-slop guarantees enforced server-side. A new
`dhx mcp` CLI subcommand launches the server rooted at an output dir + target repo +
resolved model.

The server exposes two first-class capabilities:

- **A) Interactive refine over the existing surface** — `list_segments`, `get_segment(id)`,
  `rewrite_segment(id, guidance)` (re-runs the **bounded agentic writer** to RE-EXPLORE
  the repo and regenerate one segment to the human's guidance, gated by the structure
  gate), `validate_segment(id)` (structure-gate verdict), `reassemble_site()` (rebuild the
  themed Material site from the current accepted segments).
- **B) A human-friendly narrative OVERVIEW layer** — a first-class capability to
  draft/refine a narrative overview (**Purpose · Use cases · Features · Design choices**)
  as the initial human-friendly entry, complementing the role pages. It is GROUNDED in the
  real repo via the same agentic writer with an overview-shaped blueprint/prompt
  (anti-slop: no made-up content).

## Why It Exists

DocuHarnessX produces a role-based, COBESY-structured draft in one batch run. But the
last mile — a human reading the draft, saying "this segment is wrong / shallow / misses
X", and getting a re-grounded rewrite — has no interactive surface today. The whole
modular generation core (the bounded agentic writer, the structure gate, the segment
store, the assembler) is directly callable but only ever driven by the one-shot pipeline.
This feature surfaces that core to a conversational client so refinement is a guided,
tool-mediated loop instead of hand-editing Markdown (which loses the grounding
guarantees). A reader also needs a human-friendly *front door* — a narrative overview —
which the role-page corpus does not provide; that overview must be just as grounded as the
role pages (the user's example: "we generate docs with AI to manage docs at scale; we must
ensure no made-up content / no slop").

## Verified Facts (do not contradict)

- **No existing MCP component** in DocuHarnessX (nothing in `docuharnessx/`, no MCP spec,
  none in steering). This spec BUILDS a stdio MCP **server**.
- **HarnessX ships an MCP *client* only** (`harnessx/tools/mcp.py`,
  `api/routes/mcp_servers.py`): the harness can CONSUME MCP tools; it is NOT a server. We
  do **not** reuse HarnessX's client; we build a server.
- **The MCP SDK is installed**: `mcp` 1.28.0, exposing `mcp.server.fastmcp.FastMCP`
  (`.tool()` decorator, `.run("stdio")`) and the low-level `mcp.server.Server`
  (`.list_tools()` / `.call_tool()` decorators) over `mcp.server.stdio.stdio_server`. The
  tool-dispatch layer is testable WITHOUT a model.
- **The generation core is modular and directly callable** — reuse, do not duplicate (no
  second generation engine, no RAG/embeddings):
  - `composition.AgenticProseRunner.run(blueprint, repo_path=, model=, ...)` — the bounded
    agentic writer; the ONLY model surface; absorbs all failures (returns `(None, stats)`). This
    spec adds one optional `guidance: str = ""` keyword to it (and to `build_agent_task` /
    `_render_description`) so the human guidance reaches the agent's task; default `""` is
    byte-identical to today's run.
  - `composition.validate_agent_body(body, min_citations=)` — the structure gate
    (≥1 valid Mermaid fence + ≥N distinct `file:line` citations).
  - `composition.build_blueprint(planned, analysis, vocab)`,
    `composition.build_agent_task(...)`, the `composition.budgets` defaults
    (`WRITER_*` / `MIN_CITED_FILES`), `composition.wire_segment`,
    `composition.render_fallback_body/summary`, `_derive_summary`.
  - `ontology.FilesystemSegmentStore` (`put` / `query` / `list_segments` /
    `resolve_cross_links`) + `Segment` + `Vocabulary` + `ontology_loader.load_project_vocabulary`.
  - `assembler.assemble_site(report, vocab, analysis, out_dir, identity)` +
    `resolve_site_identity` + `read_origin_remote` + `render_home_page` + the deepwiki theme.
  - `review.model.ReviewReport` / `ReviewAggregate` / `SegmentReview` (to feed assemble).
  - `model_resolver.resolve_model(model_id)` → `ModelConfig` whose `.main` is the provider.
  - `context.RunContext` slots; `bundle.make_docgen`.
- **The CLI has a subparser surface** (`docuharnessx/cli.py`: `run`, `init`) to extend with
  a new `mcp` subcommand; the bare-form normalizer keys off `_SUBCOMMANDS`.

## In Scope

- A new `docuharnessx/mcp/` package: the stdio MCP server, the tool handlers, a session
  object holding the per-target refine state (output dir, target repo, loaded `Vocabulary`,
  `FilesystemSegmentStore`, resolved `ModelConfig`, resolved `SiteIdentity`,
  optional `RepoAnalysis`), and the overview capability.
- One minimal, backward-compatible writer extension: an optional `guidance: str = ""` keyword
  threaded through `AgenticProseRunner.run` → `build_agent_task` → `_render_description`
  (`composition/agent.py` + `composition/task_prompt.py`), so the human refinement guidance has
  a concrete path into the agent's task (rendered as an applied, never-echoed author
  instruction near the mission). Default `""` = today's behaviour; it touches no frozen data
  seam.
- Tools: `list_segments`, `get_segment`, `rewrite_segment`, `validate_segment`,
  `reassemble_site`, plus the overview tools (`get_overview`, `draft_overview`,
  `refine_overview`) for capability B.
- One `dhx mcp` CLI subcommand that resolves the session (output dir + target repo +
  model) and launches the stdio server.
- Anti-slop invariants enforced server-side: every generated/refined body is re-grounded
  via the agentic writer (read/grep tools over the read-only repo) and gated by the
  structure gate before it persists; gate verdicts (and any deterministic fallback) are
  surfaced to the human, never silently passed; the `FilesystemSegmentStore` is the single
  source of truth so human-approved edits persist into assemble.
- Credential-free test substrate: a scripted provider for `rewrite_segment` / overview, and
  a test harness that exercises the MCP protocol + tool-dispatch layer WITHOUT a model.

## Grounded in the Existing Code — Preserve / Reuse / Add

- **PRESERVE the FROZEN data seams** unchanged: `Segment` / `WrittenSegments` /
  `SegmentStore` Protocol / `ReviewReport` / `AssembledSite`. The existing stages and the
  assembler stay unchanged — this feature composes their public functions, it does not edit
  them.
- **REUSE** the agentic writer (`AgenticProseRunner`), the structure gate, the blueprint
  builder, the wiring, the fallback renderer, the segment store, the assembler, the model
  resolver, and the site-identity resolver verbatim. No new generation engine. The **one**
  intentional widening of the writer is the additive `guidance: str = ""` keyword on
  `AgenticProseRunner.run` / `build_agent_task` / `_render_description` (default `""` = today's
  behaviour) — the seam through which the human guidance reaches the agent; it is not a new
  model surface and not a frozen-data-seam change.
- **ADD** only: `docuharnessx/mcp/`, the one `dhx mcp` subcommand, the additive writer
  `guidance` keyword, and the `pyproject` `mcp>=1.28` dependency. The overview is a new
  *capability* expressed through the existing agentic writer (an overview-shaped blueprint
  + a small overview prompt), not a new model surface.

## Per-Target (never hardcoded to DocuHarnessX)

The server is rooted at the **target** repo + its output, exactly like the rest of
DocuHarnessX. The `SiteIdentity` is resolved per-target via `resolve_site_identity` /
`read_origin_remote`; nothing is hardcoded to DocuHarnessX's own identity. A `dhx mcp`
session can refine the docs of any target the batch run produced.

## Credential-Free Testability (critical)

`rewrite_segment` and the overview tools call the bounded agentic writer (which calls
tools), so tests need a **scripted fake provider** that emits a deterministic tool-call
sequence (read these files) then a final grounded body + Mermaid, exercising the real
`AgenticProseRunner` run loop + real read/grep tools over a crafted fixture repo — with NO
network/credentials. The **MCP protocol + tool-dispatch layer is testable WITHOUT a model**:
`list_segments` / `get_segment` / `validate_segment` / `reassemble_site` touch no model, and
the dispatch contract (tool registration, argument parsing, error envelopes) is asserted in
process against an in-memory client. The reassemble path must reach a non-empty built site
in tests.

## Out of Scope (keep this spec focused)

- Editing the existing pipeline stages, the assembler renderers, or the frozen **data** seams.
  The one intentional exception is the additive, backward-compatible `guidance: str = ""`
  keyword on the writer (`AgenticProseRunner.run` / `build_agent_task` / `_render_description`),
  named in scope above — a signature widening behind a behaviour-preserving default, not a
  data-seam change.
- A second generation engine / any embedding / RAG / vector index.
- Non-stdio MCP transports (SSE / streamable-HTTP) — stdio only.
- Auto-deploy / GitHub Pages push from the MCP server (a refine loop ends at a rebuilt
  local site; deploy stays the batch `dhx` concern).
- Multi-session / concurrent-client coordination, locking, or a daemon — one session per
  `dhx mcp` process.
- A new review/judge surface — the structure gate is the server-side acceptance gate;
  the LLM-judge stays a batch concern.

## Dependencies

- `agentic-codebase-writer` (the `AgenticProseRunner`, structure gate, blueprint, budgets,
  task prompt), `cobesy-writer` (blueprint/wiring/fallback), `ontology-engine` (`Segment` /
  `SegmentStore` / `Vocabulary`), `mkdocs-site-assembler` (`assemble_site` / identity /
  home / theme), `quality-review-gate` (`ReviewReport`), `harness-bundle-skeleton`
  (`RunContext`, `model_resolver`, CLI). External: the installed `mcp` SDK (FastMCP +
  stdio).

## Key Constraints

- Python 3.12; reuse the modular surface (no second engine, no RAG/embeddings); preserve
  the FROZEN data seams; per-target (rooted at target repo + output, never hardcoded);
  credential-free testable (scripted provider for rewrite/overview; protocol + dispatch
  testable without a model); new code confined to `docuharnessx/mcp/` + the one `dhx mcp`
  subcommand + the additive writer `guidance` keyword (`AgenticProseRunner.run` /
  `build_agent_task` / `_render_description`, default `""` = today's behaviour) + the one
  `pyproject` `mcp>=1.28` dependency; stdio transport only.

## Acceptance Signal

`dhx mcp --out <dir> <target-repo>` launches a stdio MCP server an opencode/Claude Code
client can register and connect to. Over it a human can: list the drafted segments, read
one, ask to rewrite it with guidance (the server re-runs the bounded agentic writer over
the read-only repo, the structure gate accepts a grounded Mermaid+citations body and
persists it to the segment store, or surfaces the gate verdict / deterministic fallback and
never silently passes slop), validate a segment, draft/refine a grounded narrative overview
(Purpose · Use cases · Features · Design choices), and reassemble the themed Material site
so the approved edits and the overview appear in the rebuilt site. The full refine loop runs
credential-free in tests with the scripted provider over the fixture repo; the protocol +
dispatch layer is asserted with no model; the existing seams/tests are unaffected.
