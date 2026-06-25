# Research & Design Decisions

## Summary
- **Feature**: `docuharnessx-mcp-refine`
- **Discovery Scope**: Extension / new surface — a stdio MCP **server** that composes the
  existing DocuHarnessX generation core (no new engine, no RAG/embeddings).
  Integration-focused discovery against the installed `mcp` SDK and the existing modular
  functions.
- **Key Findings**:
  - DocuHarnessX has **no** MCP component. HarnessX ships only an MCP *client*
    (`harnessx/tools/mcp.py`, `harnessx/api/routes/mcp_servers.py`) — it can CONSUME MCP
    tools but is not a server. We therefore build a server with the standalone `mcp` SDK; we
    do not reuse HarnessX's client.
  - The `mcp` SDK (`1.28.0`, verified `importlib.metadata.version("mcp")`) is installed and
    provides both a high-level `FastMCP` (`.tool()` decorator, `.run("stdio")`) and the
    low-level `mcp.server.Server` (`@server.list_tools()` / `@server.call_tool()` decorators)
    over `mcp.server.stdio.stdio_server`. Both run on stdio and both expose a tool-dispatch
    layer exercisable in-process without a model. The spec selects the low-level `Server`.
  - The whole generation core is directly callable and reused verbatim: the bounded agentic
    writer (`AgenticProseRunner.run`), the deterministic structure gate
    (`validate_agent_body`), the blueprint builder (`build_blueprint`), the segment wiring
    (`wire_segment`) + id (`segment_id`), the deterministic fallback
    (`render_fallback_body/summary`), the segment store (`FilesystemSegmentStore`), the
    assembler (`assemble_site` + `resolve_site_identity` + `read_origin_remote` +
    `render_home_page`), the review model (`ReviewReport`/`ReviewAggregate`), and the model
    resolver (`resolve_model`). The MCP server is a thin composition layer over these.

## Research Log

### MCP server SDK choice (verified against the installed `mcp` 1.28.0)
- **Context**: We must pick a Python MCP server SDK and a transport, and the dispatch layer
  must be testable without a model.
- **Sources Consulted**: `mcp` package metadata (`importlib.metadata.version("mcp")` →
  `1.28.0`); `mcp.server.fastmcp.FastMCP`; `mcp.server.Server`
  (`= mcp.server.lowlevel.Server`); `mcp.server.stdio.stdio_server`; `mcp.types`
  (`Tool`, `TextContent`).
- **Findings**:
  - `FastMCP` exposes `tool()` (register a Python callable as an MCP tool with an input
    schema inferred from its signature) and `run(transport="stdio", ...)` (default transport
    is `stdio`; also `run_stdio_async()`).
  - The low-level `mcp.server.Server` exposes `list_tools` and `call_tool` as decorators,
    plus `create_initialization_options()` and an async
    `run(read_stream, write_stream, init_options)` driven by `stdio_server()` (an async
    context manager yielding the stdio read/write streams). `mcp.types.Tool` carries
    `name` / `description` / `inputSchema`; `TextContent` carries the tool result text.
    Verified present: `Server.list_tools`, `Server.call_tool`,
    `Server.create_initialization_options`, `FastMCP`, `mcp.types.Tool`,
    `mcp.types.TextContent`.
  - Both surfaces register handlers as plain (async) Python callables. A test can therefore
    import the server module, build the registry, and invoke a handler directly (or drive
    `Server.call_tool`) **in-process, without a network connection and without a model** —
    satisfying the credential-free dispatch requirement (Req 3.6, 10.3).
- **Implications & Decision**: Use the **low-level `mcp.server.Server`** as the primary
  server surface, driven over **stdio** by `stdio_server()`. Explicit `list_tools` /
  `call_tool` handlers give precise control over the typed `inputSchema` per tool, the
  structured error envelopes (Req 3.4/3.5), and the model-free dispatch contract the spec
  requires. A thin `build_refine_server(session) -> Server` factory registers the eight tools
  against one `RefineSession`. The factory + handlers are exercised directly in tests;
  `dhx mcp` wires the factory to the real stdio streams via `run_stdio(session)`. `FastMCP`
  is a viable alternative — its `tool()` ergonomics cut boilerplate — but the explicit handler
  shape keeps the structured error envelopes and the model-free dispatch test surface
  first-class.
- **Dependency declaration (must add)**: `mcp` is present in the working venv (`1.28.0`) but
  is **not** declared in `pyproject.toml` (only `harnessx`, `pyyaml>=6.0`, `mkdocs>=1.6`,
  `mkdocs-material>=9.5` are listed — confirmed). HarnessX pulls `mcp` in transitively for
  its MCP *client*, so it is importable today — but this feature makes `mcp` a **direct**
  runtime dependency of `docuharnessx`, so the spec MUST add `"mcp>=1.28"` to the
  `[project].dependencies` array in `pyproject.toml`. The `dhx mcp` path SHOULD also fail with
  a typed, dependency-naming error when `mcp` is not importable (mirroring the existing
  `_require_harnessx()` guard on the `run` path), so a stripped install reports the missing
  dependency cleanly instead of an opaque `ImportError`.

### How opencode / Claude Code / Cursor register a stdio MCP server
- **Context**: The acceptance signal requires an opencode (and Claude Code / Cursor) client
  to register and connect to the launched stdio server.
- **Findings** (MCP stdio convention, stable across these clients):
  - A stdio MCP server is registered by giving the client a **command + args** (and an
    optional working directory `cwd`) to spawn; the client speaks MCP over the spawned
    process's stdin/stdout. There is no port and no URL — the client owns the process
    lifecycle. The command is always the `dhx mcp` launcher, which reads the target repo and
    the output dir from its own CLI args and resolves the per-target session.
  - **opencode** (`opencode.json` / project config), MCP-servers map entry:
    ```json
    {
      "mcp": {
        "dhx-refine": {
          "type": "local",
          "command": ["dhx", "mcp", "--out", "<out-dir>", "<target-repo>"],
          "environment": { "ANTHROPIC_API_KEY": "..." }
        }
      }
    }
    ```
    A `local` server is a spawned stdio command; the provider API key the agentic writer needs
    is passed through the entry's `environment` map (or the client's inherited env).
  - **Claude Code**: `claude mcp add dhx-refine -- dhx mcp --out <out-dir> <target-repo>`, or
    the equivalent `.mcp.json` entry:
    ```json
    { "mcpServers": { "dhx-refine": {
        "command": "dhx",
        "args": ["mcp", "--out", "<out-dir>", "<target-repo>"]
    } } }
    ```
    Claude Code spawns it over stdio.
  - **Cursor** (`.cursor/mcp.json`), same stdio shape:
    ```json
    { "mcpServers": { "dhx-refine": {
        "command": "dhx",
        "args": ["mcp", "--out", "<out-dir>", "<target-repo>"]
    } } }
    ```
  - Across all three clients: `command = dhx`, `args = ["mcp", "--out", <out>, <repo>]`,
    `cwd` defaults to the project root (any cwd works because the launcher takes absolute-ish
    args); env carries the provider key.
- **Implications**: `dhx mcp` must be a clean stdio program — it must write **nothing** to
  stdout except the MCP protocol stream. All logs, the `dhx init` hint, and any human-facing
  text go to **stderr**, because stdout is the MCP channel. This extends the existing CLI
  logging discipline (`_configure_run_logging`); for `dhx mcp` the run-summary print is
  suppressed and everything noisy is routed to stderr.

### The reusable generation core (the functions the server composes)
- **Context**: The server must reuse the existing core, not duplicate it.
- **Sources Consulted**:
  `docuharnessx/composition/{agent,structure_gate,blueprint,task_prompt,wiring,fallback,budgets,model}.py`,
  `docuharnessx/ontology/{store,schema,vocabulary}.py`, `docuharnessx/ontology_loader.py`,
  `docuharnessx/assembler/{__init__,writer,identity,home}.py`, `docuharnessx/review/model.py`,
  `docuharnessx/model_resolver.py`, `docuharnessx/context.py`, `docuharnessx/cli.py`.
- **Findings (the exact reuse surface and signatures)**:
  - `AgenticProseRunner().run(blueprint, *, repo_path, model, min_citations=MIN_CITED_FILES,
    max_steps=WRITER_MAX_STEPS, max_cost_usd=WRITER_MAX_COST_USD,
    token_budget=WRITER_TOKEN_BUDGET) -> tuple[ProseResult | None, AgentRunStats]` (today's
    signature, verified in `composition/agent.py`). It builds a read-only repo harness, binds
    the model via `ModelConfig(main=model).agentic(config)`, runs a bounded `BaseTask`, takes
    `task_end.final_output`, gates it via `validate_agent_body`, and returns a `source="model"`
    `ProseResult` only on an accepted body — else `(None, stats)`. It is **synchronous** (drives
    the harness coroutine on a private `asyncio.run` loop) and **never raises**: every failure
    becomes `(None, stats)`. This is the server's single model surface for both rewrite and
    overview. **This spec adds one optional `guidance: str = ""` keyword** to `run` (and to
    `build_agent_task` / `_render_description` below) so the human refinement guidance reaches
    the agent's task; the default `""` is byte-identical to today's run (see "The human-guidance
    path" decision below).
  - `build_agent_task(blueprint, *, repo_path, min_citations=MIN_CITED_FILES,
    max_steps=WRITER_MAX_STEPS, max_cost_usd=WRITER_MAX_COST_USD,
    token_budget=WRITER_TOKEN_BUDGET) -> BaseTask` (today's signature, verified in
    `composition/task_prompt.py`) renders the agent's task `description` purely from
    blueprint-derived facts via `_render_description(blueprint, *, repo_path, min_citations)`.
    Both gain the additive `guidance: str = ""` keyword this spec introduces.
  - `validate_agent_body(body, *, min_citations=MIN_CITED_FILES) ->
    GateResult(accepted, mermaid_blocks, cited_files, reason)` — pure, total, model-free. The
    server's `validate_segment` tool returns this verdict directly; the rewrite/overview
    persist path requires `gate.accepted`.
  - `build_blueprint(planned: PlannedSegment, analysis: RepoAnalysis | None, vocab:
    Vocabulary) -> CompositionBlueprint` — pure, deterministic, model-free; derives the COBESY
    structure + evidence anchors from the planner segment's roles/intent/subjects looked up in
    the loaded vocabulary; tolerates an empty evidence set.
  - `wire_segment(planned, blueprint, prose) -> Segment` — sets all non-body fields
    deterministically (`segment_id(planned)` for the id; roles/subjects/intent from `planned`;
    title from `blueprint`) and takes `body`/`summary` only from `prose`. A rewrite therefore
    changes only body/summary; the stored id stays stable when the synthesized
    `PlannedSegment.segment_key` is stable.
  - `render_fallback_body(blueprint)` / `render_fallback_summary(blueprint)` — the
    deterministic fallback bodies surfaced (never silently persisted) when the gate rejects.
  - `FilesystemSegmentStore(directory, vocab)` implements the frozen `SegmentStore` Protocol
    (`put` / `query` / `list_segments` / `resolve_cross_links`). It **validates on put** and
    raises `IdConflictError` on a duplicate id — there is **no update method** — so a
    rewrite-in-place must **replace** the on-disk `<id>.md` (re-serialize to the existing path)
    rather than `put` a colliding id. The store parses `<out_dir>/segments/*.md` lazily on
    every call, so the on-disk content is the single source of truth (Req 4.5 / 9.4).
  - `assemble_site(report: ReviewReport, vocab, analysis, out_dir, identity) -> AssembledSite`
    — deterministic, model-free, network-free; consumes **only** `report.accepted`; renders
    one `docs/<segment>.md` per accepted segment, per-role/tag pages, the `docs/index.md` home
    page (`render_home_page`), the deepwiki theme, and `mkdocs.yml` under `<out_dir>/site`. The
    server's `reassemble_site` builds a `ReviewReport` from the live store and calls this
    verbatim.
  - `ReviewReport(schema_version, entries, accepted, aggregate)` with
    `ReviewAggregate(judged, accepted, rejected, unavailable, criterion_tally)` and
    `REVIEW_REPORT_SCHEMA_VERSION` — the seam `assemble_site` consumes. The server builds a
    minimal `ReviewReport(schema_version=REVIEW_REPORT_SCHEMA_VERSION, entries=(),
    accepted=tuple(store.list_segments()), aggregate=ReviewAggregate(judged=N, accepted=N,
    rejected=0, unavailable=0, criterion_tally=()))`. `entries=()` is acceptable because the
    assembler reads only `accepted` (every refined/overview segment is accepted by
    construction; the server-side gate is the structure gate, not the LLM judge).
  - `resolve_site_identity(target_repo, remote_url, overrides)` +
    `read_origin_remote(target_repo)` — derive the **per-target** `SiteIdentity` from the
    target's origin remote; never DocuHarnessX's identity. `read_origin_remote` is the only
    process-touching surface and degrades to `None` (no-remote fallback) on failure.
  - `resolve_model(model_id) -> ModelConfig` (config-then-env; raises `ModelResolutionError`
    when none). The server resolves it once at session start and holds `model_config.main` as
    the writer's model — but unlike `dhx run`, a missing model does **not** abort: the server
    starts and the model-touching tools degrade explicitly (Req 2.6, 5.6, 7.7); only an
    invalid target repo is fatal pre-launch.
  - `load_project_vocabulary(target_repo) -> (Vocabulary, used_default)` — loads the project
    vocabulary (default profile when no `ontology.yaml`); the `Vocabulary` binds the store and
    feeds `build_blueprint` and `assemble_site`.
- **Implications**: The server is assembled entirely from these public functions, plus **one
  minimal additive widening of the writer** (the optional `guidance` keyword on `run` /
  `build_agent_task` / `_render_description`; see "The human-guidance path" below). The one
  piece of new mcp-package glue is reconstructing a `PlannedSegment` from a stored `Segment` so
  `build_blueprint` can rebuild the COBESY blueprint for `rewrite_segment` (the planner is not
  re-run). The synthesized `PlannedSegment` copies the stored segment's roles/intent/subjects
  and derives a **stable** `segment_key` from the stored id so `segment_id()` round-trips to
  the same id and `wire_segment` rewrites in place. The human `guidance` reaches the agent via
  `AgenticProseRunner().run(..., guidance=guidance)` → `build_agent_task(..., guidance=guidance)`
  → `_render_description(..., guidance=guidance)`, where it is rendered as an applied,
  never-echoed author instruction near the mission — **not** through the frozen blueprint.

### The overview capability (capability B) — overview-shaped blueprint
- **Context**: The overview is a grounded narrative (Purpose, Use cases, Features, Design
  choices) that must reuse the agentic writer + structure gate, not a new engine.
- **Findings**: `build_agent_task(blueprint, repo_path=, min_citations=, ...)` renders the
  agent's task purely from blueprint-derived facts (the SCQA opener, the Minto key message,
  the working-memory chunks used as section headings, the evidence anchors as the files to
  start from, and the subject phrases). An **overview-shaped blueprint** is a
  `CompositionBlueprint` whose chunks are the four overview sections (Purpose / Use cases /
  Features / Design choices) as its chunk headings, whose subjects are the project's top
  subjects, and whose evidence anchors are derived from the optional `RepoAnalysis`'s salient
  entrypoints as available (else an empty tuple so the agent explores from the repo root).
  Building this blueprint deterministically
  (`build_overview_blueprint(identity, vocab, analysis, *, guidance: str = "") ->
  CompositionBlueprint`, with the reserved id `OVERVIEW_SEGMENT_ID = "overview"`) lets the
  **same** `AgenticProseRunner` produce the overview body, gated by the **same** structure gate.
  The `guidance` keyword is accepted for call-site uniformity but is **not** folded into the
  frozen blueprint; the human guidance reaches the agent through the writer's `guidance` keyword
  on `run` (`refine_overview(guidance)` forwards it; `draft_overview()` passes `""`).
- **Implications**: The overview reuses 100% of the model surface and the gate. The only new
  deterministic code is the overview-blueprint builder (pure, unit-testable without a model,
  mirroring `build_blueprint`) and the overview persistence (a reserved `Segment` with the
  fixed id `overview`, first-time `put`, then rewrite-in-place on refine, surfaced by the
  reassembled site as the human-friendly front door).

### Anti-slop / no-fabrication rationale and its mapping to the user requirement
- **Context**: The user's core constraint is "no made-up content / no slop" — every generated
  or refined body must be grounded in the real repository, never free-written.
- **The mechanism (re-grounding + gate citations)**:
  - **Re-grounding**: the server never free-writes prose. Both `rewrite_segment` and
    `draft_overview` / `refine_overview` call `AgenticProseRunner.run`, which re-explores the
    actual repository through the agent's read/grep/glob tools over a **read-only** workspace
    rooted at the target repo. The prose is produced *from what the agent reads*, not from the
    model's prior — this is the anti-slop substrate, reused verbatim from the agentic writer.
  - **Gate citations**: `validate_agent_body` is a deterministic, model-free gate that accepts
    a body only if it carries ≥1 valid Mermaid diagram **and** ≥`MIN_CITED_FILES` distinct
    `file:line` citations. A body without real, citable repository anchors cannot pass — so a
    hallucinated body is structurally rejected, not merely discouraged.
  - **Surface, never silently pass**: when the gate rejects, the server returns the gate
    verdict (`accepted=False`, `mermaid_blocks`, `cited_files`, `reason`) and the deterministic
    fallback body to the human, and persists **nothing**. There is no silent acceptance path
    (Req 5.5, 7.6, 9.3).
  - **Single source of truth**: human-approved edits are persisted into the
    `FilesystemSegmentStore` (the SSOT), so `reassemble_site` rebuilds the site from exactly
    what the human approved — no divergence between the reviewed content and the published
    content (Req 9.4).
  - **Bounded**: each writer run is Control-bounded (`make_control` loop/cost guards + the
    per-run `BaseTask` caps `WRITER_MAX_STEPS` / `WRITER_MAX_COST_USD` / `WRITER_TOKEN_BUDGET`,
    `DHX_WRITER_*`-overridable), so a refine action cannot run away (Req 5.7, 9.6).
- **Mapping to the requirement**: the user's example — "we generate docs with AI to manage
  docs at scale; we must ensure no made-up content / no slop" — maps one-to-one onto: writer
  re-grounding (no free-writing) + the citation gate (no uncitable claims) + verdict
  surfacing (no silent pass) + the store as SSOT (no drift). The server adds **no** new model
  path to audit; it inherits the writer's existing guarantees and the same gate, so the
  anti-slop posture is identical for refine and overview as it is for the batch run.

### Credential-free testability
- **Context**: The full refine loop and the protocol/dispatch layer must run with no network
  or credentials.
- **Sources Consulted**: the agentic-writer test substrate (`ScriptedAgentProvider` + the
  crafted `tests/fixtures/agentic_repo/`), `mcp.server.Server`.
- **Findings**: The agentic-writer spec already provides a `ScriptedAgentProvider` (a
  `BaseModelProvider`-shaped fake emitting a deterministic tool-call sequence then a final
  grounded body with Mermaid + `file:line` citations) and a fixture repo whose reads/citations
  are deterministic. `rewrite_segment` / `draft_overview` / `refine_overview` drive the real
  `AgenticProseRunner` over that fake + fixture, reach the gate accept path, and persist. The
  `list_segments` / `get_segment` / `validate_segment` / `reassemble_site` tools touch no
  model; the dispatch layer is invoked in-process by importing `build_refine_server(session)`
  and calling the registered handlers (or `Server.call_tool`) directly — no stdio subprocess,
  no network.
- **Implications**: Reuse the agentic-writer test substrate (scripted provider + fixture repo
  + fixture store). Add an in-process MCP-dispatch test harness that registers the tools
  against a fixture session and asserts each tool's structured result shape and error
  envelopes, all without a model.

## Architecture Pattern Evaluation

| Option | Description | Strengths | Risks / Limitations | Notes |
|--------|-------------|-----------|---------------------|-------|
| Thin MCP server composing the existing core (chosen) | A `docuharnessx/mcp/` package whose tool handlers call `AgenticProseRunner` / `validate_agent_body` / `FilesystemSegmentStore` / `assemble_site` | Zero blast radius on the frozen seams; reuses the gated, bounded writer; anti-slop guaranteed by reusing the gate | Must reconstruct a `PlannedSegment` from a stored `Segment` for rewrite; stable-id discipline | Mirrors how the stages compose the same core |
| Reuse HarnessX's MCP client | Adapt `harnessx/tools/mcp.py` | Already in the venv | It is a *client*, not a server — wrong direction; cannot expose tools | Rejected per the brief |
| Build a second generation engine for refine | A new model surface for rewrite/overview | Full control | Duplicates the writer; loses the gate/budget guarantees; explicitly out of scope | Rejected |
| FastMCP high-level decorators | `@mcp.tool()` callables, `.run("stdio")` | Less boilerplate | Less explicit control of the structured error envelopes + the model-free dispatch test surface | Viable alternative; low-level `Server` chosen for control |

## Design Decisions

### Decision: Build a stdio MCP server with the low-level `mcp.server.Server`, over stdio
- **Context**: Need a server (HarnessX only has a client), a transport, and a model-free
  dispatch test surface.
- **Alternatives Considered**: 1) FastMCP high-level decorators. 2) Reuse HarnessX's client
  (wrong direction). 3) Low-level `Server`.
- **Selected Approach**: A `build_refine_server(session) -> Server` factory registering eight
  tools via `@server.list_tools()` / `@server.call_tool()`, driven over stdio by
  `stdio_server()` from the `dhx mcp` launcher (`run_stdio(session)`).
- **Rationale**: Explicit handlers give precise control of the typed `inputSchema`, the
  structured error envelopes (Req 3.4/3.5), and an in-process dispatch test path (Req 3.6,
  10.3). stdio is the transport every target client (opencode/Claude Code/Cursor) spawns.
- **Trade-offs**: More boilerplate than FastMCP; accepted for control and testability.
- **Follow-up**: If the explicit error-envelope/dispatch control is later deemed unnecessary,
  FastMCP's `.tool()` ergonomics would cut the registration boilerplate.

### Decision: Reuse the bounded agentic writer + structure gate as the only model surface
- **Context**: Anti-slop is the core constraint; rewrite and overview must be re-grounded.
- **Selected Approach**: `rewrite_segment` and `draft_overview` / `refine_overview` call
  `AgenticProseRunner.run(blueprint, repo_path=target_repo, model=model_config.main)` and
  persist only when `validate_agent_body` accepts; the gate verdict (and any deterministic
  fallback) is surfaced, never silently passed.
- **Rationale**: The writer already re-explores the read-only repo through read/grep tools, is
  bounded by Control budgets, and is gated — exactly the anti-slop guarantees the spec demands,
  with no new model path to audit.
- **Trade-offs**: The agent's prose is non-deterministic (mitigated by the deterministic gate +
  the scripted-provider test path); a strict gate may reject a usable body (the human sees the
  verdict and the fallback and decides).

### Decision: Reconstruct a `PlannedSegment` from a stored `Segment` for rewrite
- **Context**: `build_blueprint` needs a `PlannedSegment`; the planner is not re-run in a
  refine session.
- **Selected Approach**: A pure `planned_from_segment(segment)` helper copies the stored
  segment's roles/intent/subjects and derives a **stable** `segment_key` from the stored id so
  `segment_id()` round-trips to the same id and `wire_segment` rewrites the same `<id>.md` in
  place; persistence replaces the existing file (`replace_segment_body`) rather than `put`-ing a
  colliding id (the store raises `IdConflictError` on a duplicate `put`). The human `guidance`
  reaches the agent via the writer's additive `guidance` keyword
  (`run(..., guidance=guidance)` → `build_agent_task` → `_render_description`), rendered as an
  applied, never-echoed author instruction — see "The human-guidance path into the writer".
- **Rationale**: Keeps non-body fields fixed by the deterministic wiring (Req 5.8) and the id
  stable so the rewrite replaces the segment rather than creating a duplicate.
- **Trade-offs**: The reconstructed evidence anchors are weaker than the planner's original
  (the blueprint tolerates empty evidence; the agent then explores from the repo root).
- **Follow-up**: Persist the original `PlannedSegment` / evidence alongside the segment so a
  rewrite re-grounds from the planner's anchors instead of the repo root.

### Decision: Overview as an overview-shaped blueprint through the same writer
- **Context**: The overview must be grounded and reuse the writer/gate.
- **Selected Approach**: A pure
  `build_overview_blueprint(identity, vocab, analysis, *, guidance: str = "") ->
  CompositionBlueprint` produces a `CompositionBlueprint` whose four chunks are Purpose / Use
  cases / Features / Design choices (the overview's chunk headings; reserved id `overview`) and
  whose evidence anchors are derived from `analysis` as available; the same `AgenticProseRunner`
  + gate produce and accept the overview body; it is persisted as a reserved first-class entry
  the reassembled site surfaces as the human-friendly front door. `draft_overview()` calls the
  builder with `guidance=""` and runs `run(..., guidance="")`; `refine_overview(guidance)`
  passes the human guidance and runs `run(..., guidance=guidance)`. The `guidance` keyword on
  the builder exists only so the call sites read uniformly — it is not folded into the frozen
  blueprint (the human guidance reaches the agent through the writer's `guidance` seam, never as
  a blueprint chunk/output heading).
- **Rationale**: 100% model-surface and gate reuse; only the overview-blueprint builder, the
  overview persistence, and the additive writer `guidance` keyword are new, all deterministic
  and unit-testable without a model.

### Decision: The human-guidance path into the writer (additive, never-echoed `guidance` keyword)
- **Context**: `rewrite_segment(id, guidance)` and `refine_overview(guidance)` carry a human
  refinement instruction that must reach the agent's task — but the existing writer has **no**
  path for it. Verified against the real code: `AgenticProseRunner.run` (composition/agent.py)
  takes no guidance; it calls `build_agent_task` (composition/task_prompt.py), which renders
  `_render_description` from **blueprint-derived facts only**; `build_blueprint` has no guidance
  parameter; and `CompositionBlueprint` is `@dataclass(frozen=True)`. Critically, a blueprint
  `chunk` is rendered as an **output section heading** in `_render_description`, so folding
  guidance into a chunk would **leak it as a doc section** — unacceptable.
- **Alternatives Considered**: 1) Add a `guidance` field to `CompositionBlueprint` — rejected:
  it is a frozen data seam and guidance is not a blueprint fact. 2) Route guidance through a
  blueprint chunk — rejected: chunks render as output headings, so the guidance would surface as
  a visible section (slop/leak). 3) **Thread an optional `guidance: str = ""` keyword through
  the writer** — chosen.
- **Selected Approach**: Add `guidance: str = ""` to `AgenticProseRunner.run` →
  `build_agent_task` → `_render_description`. In `_render_description`, when `guidance` is
  non-empty, render it as one explicit **author-guidance instruction near the mission** ("Apply
  this refinement guidance to WHAT you write and emphasise; do NOT quote it, name it, or add a
  section/heading for it") — *applied*, never echoed, exactly like the existing role and COBESY
  anti-echo rules already in `_render_description` (the audience role is a targeting signal that
  must never appear in the page; the COBESY method names are never written). When `guidance` is
  empty, no guidance line is emitted, so `(blueprint, repo_path, caps)` still yields a
  byte-identical task and every existing agentic-codebase-writer test passes unchanged.
- **Rationale**: This is the minimal, backward-compatible widening that gives the human guidance
  a concrete path to `BaseTask.description` without touching any frozen data seam and without
  leaking guidance as output. The mcp handlers pass `runner.run(..., guidance=guidance)`;
  `draft_overview` passes `guidance=""`.
- **Trade-offs**: Touches two writer files (`composition/agent.py`, `composition/task_prompt.py`)
  beyond `docuharnessx/mcp/` + the cli, so the spec's scope is "`docuharnessx/mcp/` + the cli
  `mcp` subcommand + the additive `guidance` keyword on `run`/`build_agent_task`/
  `_render_description` + the one `pyproject` `mcp>=1.28` dep". The additive default `""` keeps
  the change behaviour-preserving and the frozen seams untouched.

### Decision: `dhx mcp` keeps stdout clean for the MCP protocol
- **Context**: stdio is the MCP channel; logs must not corrupt it.
- **Selected Approach**: `dhx mcp` routes all logs and human text to stderr (extending
  `_configure_run_logging`), suppresses the run-summary print, starts even when no model
  resolves, and serves over the inherited stdin/stdout.
- **Rationale**: A client speaking MCP over the process's stdout requires a clean stdout.

## Risks & Mitigations
- **A stray write to stdout corrupts the MCP stream** → `dhx mcp` sends all logs/text to
  stderr; suppress the run-summary print; covered by a launcher test asserting stdout carries
  only protocol bytes.
- **A rewrite duplicates rather than replaces a segment** (the store raises `IdConflictError`
  on a colliding `put`) → the stable-id `planned_from_segment` + an explicit replace-in-place
  persistence (`replace_segment_body` overwrites the existing `<id>.md`); covered by a store
  round-trip test.
- **Agent emits invalid/no Mermaid or too-few citations** → the structure gate rejects; the
  server surfaces the verdict + the deterministic fallback and persists nothing (Req 5.5, 7.6,
  9.3).
- **Runaway cost on a large repo** → the per-run `BaseTask` caps + `make_control` loop/cost
  guards bound each rewrite/overview run (reused verbatim; Req 5.7, 9.6).
- **No model configured** → the server still starts; model-touching tools return an explicit
  "no model configured" result; the read-only/model-free tools stay fully usable (Req 2.6,
  5.6, 7.7).
- **`mcp` missing from a stripped install** → declare `"mcp>=1.28"` in `pyproject.toml` +
  a typed import guard on the `dhx mcp` path that names the missing dependency.
- **Server must be testable without a network** → the low-level `Server` handlers are invoked
  in-process; the agentic path uses the scripted provider + fixture repo (Req 10).

## Open Questions
- **Overview placement in the rebuilt site**: render the reserved `overview` segment as the
  `docs/index.md` home page directly, or as a top-level "Overview" page alongside the
  `render_home_page` landing page? The design leans to the front-door page; final placement is
  an assemble-time detail to confirm in implementation (the assembler change must stay within
  the declared boundary or be done by tagging, not by editing the renderer).
- **Evidence reconstruction for rewrite**: persisting the original `PlannedSegment` / evidence
  anchors alongside each segment (a future enhancement) would let a rewrite re-ground from the
  planner's anchors rather than the repo root.
- **opencode config key shape**: the exact opencode MCP-servers map key/field names (`type`,
  `command`, `environment`) follow the documented opencode local/stdio convention; verify
  against the installed opencode version at integration time (the `command` + `args` + `cwd`
  contract is stable; only the surrounding JSON key names vary by client).

## References
- Installed MCP SDK: `mcp` 1.28.0 — `mcp.server.Server` (`list_tools`/`call_tool` decorators,
  `create_initialization_options`, async `run(read, write, init_options)`),
  `mcp.server.fastmcp.FastMCP` (`tool`/`run(transport="stdio")`),
  `mcp.server.stdio.stdio_server`, `mcp.types` (`Tool`/`TextContent`).
- HarnessX MCP *client* (not reused): `harnessx/tools/mcp.py`,
  `harnessx/api/routes/mcp_servers.py`.
- DocuHarnessX reuse surface:
  `docuharnessx/composition/{agent,structure_gate,blueprint,task_prompt,wiring,fallback,budgets,model}.py`,
  `docuharnessx/ontology/{store,schema,vocabulary}.py`, `docuharnessx/ontology_loader.py`,
  `docuharnessx/assembler/{writer,identity,home}.py`, `docuharnessx/review/model.py`,
  `docuharnessx/model_resolver.py`, `docuharnessx/context.py`, `docuharnessx/cli.py`.
- Build config: `pyproject.toml` — add `"mcp>=1.28"` to `[project].dependencies` (it is
  currently transitive via HarnessX only).
- Writer extension (this spec): `docuharnessx/composition/agent.py`
  (`AgenticProseRunner.run`) + `docuharnessx/composition/task_prompt.py` (`build_agent_task`,
  `_render_description`) — additive optional `guidance: str = ""` keyword; default `""` =
  today's behaviour.
- MCP stdio client registration: opencode local/stdio MCP server config (command + args + env),
  Claude Code `claude mcp add -- <command>` / `.mcp.json`, Cursor `.cursor/mcp.json`
  (`command` + `args`).
- deepwiki-open — the grounding bar reused via the structure gate (model-generated Mermaid +
  mandatory `file:line` citations).
