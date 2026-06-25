# Requirements Document

## Introduction

The `docuharnessx-mcp-refine` feature adds a **stdio MCP (Model Context Protocol) server**
that exposes DocuHarnessX's own document-refinement tools to an interactive MCP client
(opencode primarily; also Claude Code / Cursor). After a batch `dhx` run produces the
role-based draft — segments persisted as `<id>.md` under `<out>/segments` by a
`FilesystemSegmentStore`, and a built Material site under `<out>/site` — a human opens the
output in opencode and conversationally refines the documentation through these tools. The
server reuses DocuHarnessX's existing modular core verbatim: the bounded agentic writer
(`AgenticProseRunner`), the deterministic structure gate (`validate_agent_body`), the
blueprint builder, the segment wiring and fallback renderer, the segment store, the
assembler (`assemble_site` + the per-target site-identity resolver), and the model resolver.
It builds **no** second generation engine and no RAG/embedding/vector index.

DocuHarnessX has no existing MCP component; HarnessX ships only an MCP *client*, so this
spec builds a server. The installed `mcp` SDK (1.28.0) provides the stdio transport and the
tool-dispatch layer, both usable without a model.

The agent sets the docs location **at run time** rather than the launcher binding a fixed
target: a first-class `open_workspace(repo, out, config?)` tool points the server at a target
repository and the output directory a prior `dhx run` wrote (config optionally selects the
model), resolving a per-target session on demand and setting it as the server's single mutable
**active workspace**. Every other tool acts on that active workspace. `dhx mcp` may still
**pre-open** one target as a convenience, but the client may switch at any time.

The server exposes two first-class capabilities. **(A) Interactive refine over the existing
surface**: list/get segments, rewrite a segment to human guidance (re-running the bounded
agentic writer so the new body is re-grounded in the real repository and gated by the
structure gate), validate a segment, and reassemble the themed Material site. **(B) A
human-friendly narrative overview layer**: draft and refine a grounded narrative overview
(Purpose, Use cases, Features, Design choices) as the site's initial human-friendly entry,
complementing the role pages — grounded in the real repository through the same agentic
writer with an overview-shaped blueprint and prompt.

The core constraint is **anti-slop / no-fabrication**: every generated or refined body is
re-grounded in the actual repository through the agentic writer's read/grep tools — the
server never free-writes prose; the structure gate enforces at least N distinct `file:line`
citations and a valid Mermaid diagram before a body can be accepted; gate verdicts (and any
deterministic fallback) are surfaced to the human and never silently passed; the segment
store is the single source of truth so human-approved edits persist into assemble; the
agent is bounded by the writer's Control budgets; and the protocol plus tool-dispatch layer
is credential-free testable.

All new code is confined to a new `docuharnessx/mcp/` package plus one `dhx mcp` CLI
subcommand, with **one minimal, backward-compatible extension of the writer**: an optional
`guidance: str = ""` keyword threaded through `AgenticProseRunner.run` → `build_agent_task` →
`_render_description` (default `""` = today's behaviour) so the human refinement guidance has a
concrete path into the agent's task. The FROZEN **data** seams (`Segment`, `WrittenSegments`,
the `SegmentStore` Protocol, `ReviewReport`, `AssembledSite`) and the existing stages and
assembler stay unchanged — the server composes their public functions, and the writer extension
only widens a function signature behind a default that reproduces the existing behaviour, never
edits a frozen data type.

## Boundary Context

- **In scope**:
  - A new `docuharnessx/mcp/` package: a stdio MCP server, the tool handlers, a per-target
    refine session object, the server's mutable active workspace, and the overview capability.
  - The workspace tool: `open_workspace` (the agent points the server at a target repo + output
    dir at run time, optionally selecting the model; sets the server's active workspace).
  - The refine tools: `list_segments`, `get_segment`, `rewrite_segment`,
    `validate_segment`, `reassemble_site`.
  - The overview tools: `get_overview`, `draft_overview`, `refine_overview`.
  - One `dhx mcp` CLI subcommand that launches the stdio server with an **optional** pre-opened
    target (when a target repo is given it resolves and pre-opens the session; otherwise the
    agent opens the workspace via `open_workspace`).
  - One minimal, backward-compatible writer extension: an optional `guidance: str = ""`
    keyword on `AgenticProseRunner.run`, `build_agent_task`, and `_render_description`
    (`composition/agent.py` + `composition/task_prompt.py`), through which `rewrite_segment` and
    `refine_overview` deliver the human guidance to the agent (default `""` = today's behaviour;
    no change to a frozen data seam).
  - Server-side anti-slop enforcement: re-grounding every generated/refined body through
    the agentic writer, gating it with the structure gate before persistence, and surfacing
    every gate verdict / fallback to the human.
  - A credential-free test substrate: a scripted provider that drives the agentic writer
    deterministically, and a protocol + dispatch test layer that runs without a model.
- **Out of scope** (separate concerns):
  - Editing the existing pipeline stages, the assembler renderers, the model resolver, or
    any frozen **data** seam (`Segment` / `WrittenSegments` / `SegmentStore` Protocol /
    `ReviewReport` / `AssembledSite`). The **one** intentional exception is the additive,
    backward-compatible `guidance: str = ""` keyword on the writer
    (`AgenticProseRunner.run` / `build_agent_task` / `_render_description`) named in scope
    above — a signature widening behind a behaviour-preserving default, not a data-seam change.
  - A second generation engine, or any embedding / RAG / vector index.
  - Non-stdio transports (SSE / streamable-HTTP).
  - Deploy / GitHub Pages push from the MCP server (deploy stays the batch `dhx` concern).
  - Multi-session / concurrent-client coordination, locking, or a long-lived daemon.
  - A new review / LLM-judge surface (the structure gate is the server-side gate).
- **Adjacent expectations**:
  - A prior batch `dhx` run has populated `<out>/segments` with `Segment` markdown files
    and (optionally) `<out>/site` with a built Material site.
  - The project `Vocabulary` is loadable from the target repo via
    `load_project_vocabulary` (default profile when absent).
  - The model, when used, is resolved through `resolve_model` (config-then-env), exactly as
    the `run` path resolves it; `rewrite_segment` and the overview tools use the resolved
    `ModelConfig.main` as the agentic writer's model.
  - The `SegmentStore` is a `FilesystemSegmentStore` rooted at `<out>/segments`, so reads
    and writes are the same on-disk source of truth the batch run produced.

## Requirements

### Requirement 1: A new, self-contained MCP package and CLI subcommand

**Objective:** As a pipeline maintainer, I want the MCP server confined to a new package and
a single CLI subcommand, so that the existing stages, assembler, and frozen seams need no
edits.

#### Acceptance Criteria
1. The feature SHALL add all server code under a new `docuharnessx/mcp/` package and SHALL
   add exactly one new `mcp` subcommand to the existing `dhx` argument parser; the **only**
   change outside `docuharnessx/mcp/` + the cli `mcp` subcommand + the `pyproject` `mcp>=1.28`
   dependency SHALL be the additive, backward-compatible `guidance: str = ""` keyword on the
   writer (`AgenticProseRunner.run` / `build_agent_task` / `_render_description`) defined in
   Requirement 5 and Requirement 7.
2. The feature SHALL NOT modify any existing pipeline stage module, the assembler renderers,
   the model resolver, or any frozen **data** seam type (`Segment`, `WrittenSegments`, the
   `SegmentStore` Protocol, `ReviewReport`, `AssembledSite`). The writer `guidance` keyword in
   AC 1 is a signature widening behind a behaviour-preserving default, not a frozen data-seam
   change, and SHALL keep `guidance=""` byte-identical to today's task so the existing
   agentic-writer tests pass unchanged.
3. WHEN the `dhx mcp` subcommand is added, the existing bare-form invocation
   (`dhx <target-repo> ...`), `dhx run`, and `dhx init` SHALL continue to work unchanged.
4. The MCP server SHALL reuse the existing composition core, segment store, assembler,
   model resolver, and site-identity resolver by calling their public functions, and SHALL
   NOT introduce a second generation engine or any embedding / RAG / vector index.
5. WHEN the `mcp` package is imported, it SHALL expose the server entry point, the session
   object, and the tool handlers from a single package namespace.

### Requirement 2: The `dhx mcp` launcher and the agent-set active workspace

**Objective:** As a documentation author, I want `dhx mcp` to launch a stdio MCP server whose
target docs the agent points at *at run time* (rather than a fixed target bound at launch), so
that I — or my MCP client — choose which project's docs to refine without restarting the
server, while still being able to pre-open one target for convenience.

#### Acceptance Criteria
1. The `dhx mcp` subcommand SHALL accept an **optional** target-repository path and an output
   directory (the same `--out` semantics as `dhx run`, defaulting to the documented per-target
   output path when omitted), and an optional `--config` / model selection. WHEN a target
   repository is given, `dhx mcp` SHALL **pre-open** it as the server's initial active workspace
   (a convenience); WHEN the target is omitted, the server SHALL launch generic and the agent
   SHALL set the active workspace via `open_workspace` before any other tool can act.
2. IF a target-repository path **is** given but is missing or is not an existing directory, the
   `dhx mcp` subcommand SHALL fail before launching the server with an identifiable error,
   exactly as the `run` path validates its target.
3. WHEN a workspace is opened (pre-opened at launch, or via `open_workspace`), it SHALL resolve
   a per-target session carrying the output directory, the target-repository path, the loaded
   project `Vocabulary`, a `FilesystemSegmentStore` rooted at `<out>/segments`, the resolved
   `ModelConfig` (or `None` when no model is configured), the resolved per-target `SiteIdentity`,
   and the optional `RepoAnalysis` when one is available.
4. WHEN a workspace is resolved, the per-target `SiteIdentity` SHALL be derived from the
   target repository via the existing site-identity resolver (origin remote → identity),
   and SHALL NEVER be hardcoded to DocuHarnessX's own identity.
5. WHEN `dhx mcp` starts (with or without a pre-opened target), the subcommand SHALL start the
   MCP server over the **stdio** transport and serve until the client disconnects.
6. IF no model can be resolved, the server SHALL still start and serve, and the
   model-touching tools SHALL degrade explicitly (per Requirement 5 and Requirement 7)
   rather than aborting server startup.
7. The active workspace SHALL be rooted per-target so it refines one target's documentation,
   and SHALL load the project `Vocabulary` via the project ontology loader (default profile
   when no project ontology file is present). The server SHALL hold a single **mutable** active
   workspace that `open_workspace` sets, so the agent MAY switch to a different repo/out without
   restarting the server.
8. WHEN the agent calls `open_workspace(repo, out, config?)`, the server SHALL resolve a session
   on demand from the agent-provided `repo` (required), `out` (optional; the per-target default
   when omitted), and `config` (optional; selects the model config-then-env), SHALL set it as
   the server's active workspace, and SHALL return a workspace summary carrying `opened`, the
   resolved `repo` and `out`, the `segment_count`, the per-target `site_name`, and
   `model_available`.
9. IF `open_workspace` cannot resolve the workspace (a missing/invalid target repo, a malformed
   `--config`, or an invalid ontology), the server SHALL return a **structured tool error**
   (code `open_failed`) naming the repo and the reason, and SHALL NOT crash the server process.
10. IF any tool other than `open_workspace` is called before a workspace is open, the server
    SHALL return a **structured tool error** (code `no_workspace`) directing the agent to call
    `open_workspace` first, and SHALL NOT operate on a hardcoded location or crash.

### Requirement 3: Tool registration and dispatch over stdio MCP

**Objective:** As an MCP client (opencode / Claude Code / Cursor), I want a well-formed set
of MCP tools with typed inputs, so that I can discover and call the refine and overview
capabilities conversationally.

#### Acceptance Criteria
1. The server SHALL register and advertise the workspace tool `open_workspace`, the refine
   tools `list_segments`, `get_segment`, `rewrite_segment`, `validate_segment`, and
   `reassemble_site`, and the overview tools `get_overview`, `draft_overview`, and
   `refine_overview` — **nine** tools in all — each with a name, a human description, and a
   typed input schema.
2. WHEN a client lists tools, the server SHALL return every registered tool with its input
   schema so the client can call it without out-of-band knowledge.
3. WHEN a client calls a registered tool with valid arguments, the server SHALL dispatch to
   the matching handler and return its result as MCP content.
4. IF a client calls a tool with a missing or malformed required argument (for example a
   `rewrite_segment` call with no segment id), the server SHALL return a structured tool
   error naming the offending argument and SHALL NOT crash the server process.
5. IF a client calls an unknown tool name, the server SHALL return a structured tool error
   rather than raising out of the dispatch loop.
6. The tool-registration and dispatch layer SHALL be exercisable in-process without a
   network connection and without a model, so the protocol contract is testable
   credential-free.

### Requirement 4: List and read drafted segments (read-only, model-free)

**Objective:** As a documentation author, I want to enumerate and read the drafted segments,
so that I can decide which to refine.

#### Acceptance Criteria
1. WHEN `list_segments` is called, the server SHALL return the segments currently in the
   session's `FilesystemSegmentStore` in the store's deterministic (by-id) order, each entry
   carrying at least the segment id, title, roles, intent, and subjects.
2. WHEN `get_segment(id)` is called for a stored id, the server SHALL return that segment's
   id, title, roles, intent, subjects, summary, and full Markdown body.
3. IF `get_segment(id)` is called for an id not present in the store, the server SHALL
   return a structured tool error naming the missing id, and SHALL NOT raise out of the
   handler.
4. `list_segments` and `get_segment` SHALL read only from the segment store and SHALL NOT
   consult a model, so they are fully usable credential-free.
5. WHEN the store is read, the segments SHALL be the same on-disk source of truth the batch
   run produced, so a refine session reflects the current persisted state.

### Requirement 5: Re-grounded segment rewrite (capability A core; anti-slop)

**Objective:** As a documentation author, I want to rewrite one segment to my guidance and
have the new body re-grounded in the real repository, so that the refined documentation
reflects the code and contains no fabricated content.

#### Acceptance Criteria
1. WHEN `rewrite_segment(id, guidance)` is called for a stored segment and a model is bound,
   the server SHALL run the bounded agentic writer (`AgenticProseRunner`) over a read-only
   workspace rooted at the target repository so the agent re-explores the real source with
   the read/grep/glob/bash tools and regenerates the segment body to the human's guidance.
2. The server SHALL seed the rewrite with the segment's existing structure — the
   deterministic blueprint reconstructed for that segment — and SHALL deliver the human
   `guidance` to the agent through the writer's additive `guidance` keyword
   (`AgenticProseRunner.run(..., guidance=guidance)` → `build_agent_task(..., guidance=guidance)`
   → `_render_description(..., guidance=guidance)`), so the agent fills a grounded body rather
   than free-writing, and SHALL NOT free-write prose itself. The `guidance` SHALL NOT be routed
   through the frozen blueprint or any blueprint chunk (chunks render as output headings).
9. WHEN a non-empty `guidance` is supplied, `_render_description` SHALL render it as an
   **applied author-guidance instruction near the mission** — directing WHAT the agent writes
   and emphasises — and the guidance text SHALL NOT be quoted verbatim, named, or rendered as a
   heading/section in the accepted body (the same applied-not-echoed discipline the writer
   already enforces for the audience role and the COBESY method names). WHEN `guidance` is the
   empty string, the rendered task SHALL be byte-identical to today's task so existing callers
   and tests are unaffected.
3. WHEN the agent returns a body, the server SHALL gate it with the deterministic structure
   gate (`validate_agent_body`): the body is accepted only with at least one valid Mermaid
   diagram and at least the configured minimum number of distinct `file:line` citations.
4. WHEN a rewritten body passes the structure gate, the server SHALL persist the updated
   segment to the `FilesystemSegmentStore` (replacing the prior body, keeping the segment's
   non-body fields fixed by the deterministic wiring) so the approved edit is the new source
   of truth.
5. IF the agentic run raises, times out, returns empty, exceeds its budget, or returns a
   body the structure gate rejects, the server SHALL NOT persist a fabricated body; it SHALL
   return the gate verdict (and the deterministic fallback body when one is rendered) to the
   human and SHALL leave the stored segment unchanged unless the human explicitly accepts the
   fallback.
6. IF no model is bound when `rewrite_segment` is called, the server SHALL return an explicit
   "no model configured" result naming how to configure one, and SHALL NOT silently produce
   or persist content.
7. The bounded agentic rewrite SHALL be capped by the writer's existing Control budgets
   (max steps, max cost, token budget, loop detection), so one rewrite cannot run away in
   cost, steps, or time.
8. The rewrite SHALL only ever change the segment's `body` and `summary`; every non-body
   field (id, title, roles, subjects, intent, schema version) SHALL be fixed by the existing
   deterministic wiring.

### Requirement 6: Structure-gate validation surface

**Objective:** As a documentation author, I want to validate a segment's body against the
anti-slop gate on demand, so that I can see why a body is or is not grounded before I accept
it.

#### Acceptance Criteria
1. WHEN `validate_segment(id)` is called for a stored segment, the server SHALL run the
   deterministic structure gate over that segment's body and return the verdict — accepted
   or rejected, the count of valid Mermaid blocks, the count of distinct cited files, and
   the human-readable reason.
2. `validate_segment` SHALL consult no model and perform no network access, so it is fully
   usable credential-free.
3. IF `validate_segment(id)` is called for an id not present in the store, the server SHALL
   return a structured tool error naming the missing id.
4. The validation verdict SHALL use the same minimum-citations threshold the rewrite path
   enforces, so a body that validates here is one the rewrite path would accept.

### Requirement 7: Grounded narrative overview (capability B; anti-slop)

**Objective:** As a documentation reader, I want a human-friendly narrative overview
(Purpose, Use cases, Features, Design choices) grounded in the real repository, so that I
have a trustworthy front door to the project that complements the role pages.

#### Acceptance Criteria
1. WHEN `draft_overview()` is called and a model is bound, the server SHALL run the bounded
   agentic writer over the read-only target repository with an **overview-shaped** blueprint
   (built by `build_overview_blueprint(identity, vocab, analysis, *, guidance="")`, whose chunk
   headings are Purpose / Use cases / Features / Design choices) and `guidance=""`, so the
   overview is grounded in the real source and structured around Purpose, Use cases, Features,
   and Design choices.
2. WHEN `refine_overview(guidance)` is called, the server SHALL re-run the bounded agentic
   writer over the overview-shaped blueprint and SHALL deliver the human guidance through the
   writer's `guidance` keyword (`AgenticProseRunner.run(..., guidance=guidance)`), so the
   revised overview stays grounded in the real repository. The guidance SHALL be applied to WHAT
   the overview covers and emphasises and SHALL NOT appear quoted, named, or as a heading/section
   in the accepted overview (the same applied-not-echoed discipline as the segment rewrite).
3. WHEN an overview body is produced, the server SHALL gate it with the deterministic
   structure gate before persisting it, so the overview meets the same grounding bar (valid
   Mermaid diagram + distinct `file:line` citations) as the role pages.
4. WHEN an overview body passes the gate, the server SHALL persist it as a first-class
   entry that the reassembled site surfaces as the initial human-friendly page, distinct
   from the per-role landing pages.
5. WHEN `get_overview()` is called, the server SHALL return the current persisted overview
   body, or an explicit "no overview drafted yet" result when none exists.
6. IF the overview agentic run raises, times out, returns empty, exceeds budget, or fails
   the structure gate, the server SHALL NOT persist a fabricated overview; it SHALL surface
   the gate verdict (and any deterministic fallback) to the human and leave any prior
   overview unchanged unless the human accepts the fallback.
7. IF no model is bound when an overview draft/refine is requested, the server SHALL return
   an explicit "no model configured" result and SHALL NOT silently produce content.
8. The overview capability SHALL reuse the existing agentic writer and structure gate as its
   only model surface and gate; it SHALL NOT introduce a separate generation engine.

### Requirement 8: Reassemble the themed Material site from approved edits

**Objective:** As a documentation author, I want to rebuild the themed Material site after
refining, so that my approved segment edits and the overview appear in the published site.

#### Acceptance Criteria
1. WHEN `reassemble_site()` is called, the server SHALL build a `ReviewReport` whose accepted
   set is the current segments in the session's `FilesystemSegmentStore` (plus the persisted
   overview when present) and SHALL call the existing `assemble_site` with the session's
   loaded `Vocabulary`, optional `RepoAnalysis`, output directory, and resolved per-target
   `SiteIdentity`.
2. WHEN `reassemble_site()` completes, the server SHALL return the resulting site directory,
   the per-segment page count, and the per-role landing-page count from the produced
   `AssembledSite`.
3. The reassembled site SHALL reflect the current persisted segment bodies and the overview,
   so an approved rewrite is visible in the rebuilt site.
4. `reassemble_site` SHALL consult no model (assembly is deterministic and model-free), so it
   is fully usable credential-free.
5. The reassembly SHALL write only under the session's output directory and SHALL reuse the
   existing per-target site identity, so it never derives DocuHarnessX's own identity and
   never writes into the target repository.
6. IF the segment store is empty when `reassemble_site()` is called, the server SHALL produce
   a well-formed (empty) site without error and report a zero page count.

### Requirement 9: Anti-slop / no-fabrication invariants (cross-cutting)

**Objective:** As a project owner, I want hard guarantees that the server never publishes
made-up content, so that AI-managed docs at scale stay trustworthy.

#### Acceptance Criteria
1. The server SHALL NOT free-write any segment or overview body itself; every generated or
   refined body SHALL come from the bounded agentic writer re-exploring the real repository
   through its read/grep tools.
2. Before any generated or refined body is persisted, the server SHALL require it to pass
   the deterministic structure gate (≥1 valid Mermaid diagram + ≥ the configured minimum of
   distinct `file:line` citations).
3. WHEN a body fails the structure gate, the server SHALL surface the gate verdict (and any
   deterministic fallback body) to the human and SHALL NOT silently persist or publish the
   failing body.
4. The `FilesystemSegmentStore` and the persisted overview SHALL be the single source of
   truth, so only human-approved, gate-passing edits flow into reassembly.
5. The agent's repository workspace SHALL be read-only, so a rewrite or overview run SHALL
   read real source but SHALL NOT modify the target repository.
6. The agentic runs SHALL be bounded by the writer's Control budgets, so the refine loop is
   cost-bounded and cannot run away.
7. The human refinement `guidance` SHALL be **applied, not echoed**: it SHALL reach the agent's
   task (`BaseTask.description`) only through the writer's additive `guidance` keyword as an
   author instruction near the mission, and it SHALL NOT appear quoted verbatim, named, or as a
   heading/section in any accepted segment or overview body — so guidance steers the content
   without leaking into it as slop.

### Requirement 10: Credential-free offline testability

**Objective:** As a developer, I want the whole refine surface testable with no network or
credentials, so that the server and the anti-slop guarantees stay verifiable offline and in
CI.

#### Acceptance Criteria
1. The feature SHALL provide a scripted fake provider that drives the bounded agentic writer
   deterministically (a sequence of tool calls reading fixture files, then a final grounded
   body containing a valid Mermaid diagram and the minimum number of `file:line` citations),
   reusing the agentic-writer test substrate, so `rewrite_segment` and the overview tools run
   with no network or credentials.
2. WHEN driven by the scripted provider over a crafted fixture repository, `rewrite_segment`
   and `draft_overview` / `refine_overview` SHALL exercise the real `AgenticProseRunner` run
   loop and the real read/grep tools and SHALL persist a gate-passing body.
3. The MCP protocol and tool-dispatch layer (tool listing, argument parsing, error
   envelopes, dispatch) SHALL be testable in-process without a model, so the read-only and
   model-free tools (`list_segments`, `get_segment`, `validate_segment`, `reassemble_site`)
   are fully covered credential-free.
4. WHEN the credential-free refine loop runs end-to-end (rewrite or overview → reassemble),
   the reassembled site SHALL be non-empty and SHALL contain the gate-passing body, with no
   network access.
5. The session resolution (`dhx mcp` validation, vocabulary load, store provisioning, model
   resolution) SHALL be unit-testable with an injected `ModelConfig` (or `None`) so no real
   provider is required.
