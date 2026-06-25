# Implementation Plan

- [ ] 1. Foundation: the MCP package skeleton and the per-target session
- [ ] 1.1 Create the `docuharnessx/mcp/` package with a single public namespace
  - Add the empty `docuharnessx/mcp/` package whose `__init__.py` will re-export the server
    factory, the session, the resolver, and the handlers from one place, so the CLI and the
    tests import the MCP surface from a single namespace and no second generation engine is
    introduced.
  - Observable completion: importing `docuharnessx.mcp` succeeds and a package-surface unit
    test asserts the public names the package will expose are listed in its `__all__`.
  - _Requirements: 1.1, 1.5, 1.4_
  - _Boundary: mcp package namespace_

- [ ] 1.2 Build the per-target `RefineSession` and `resolve_session`
  - Add the `RefineSession` dataclass (out dir, target repo, loaded `Vocabulary`,
    `FilesystemSegmentStore` rooted at `<out>/segments`, resolved `ModelConfig` or `None`,
    per-target `SiteIdentity`, optional `RepoAnalysis`, `min_citations`) and a
    `resolve_session(target_repo, out_dir, *, model_config=None)` that validates the target is
    an existing directory, resolves the output dir (documented default when omitted), loads the
    project vocabulary (default profile when absent), provisions the filesystem store, resolves
    the per-target site identity from the target's origin remote (never DocuHarnessX's), loads
    an optional persisted analysis, and resolves the model — swallowing a no-model resolution to
    `None` so the server can still start.
  - Observable completion: a unit test with an injected `ModelConfig` (and with `None`) confirms
    the session carries the store rooted at `<out>/segments`, the loaded vocabulary, a
    per-target identity derived from a fake origin remote, and a `model()` that is the provider
    or `None`; an invalid target raises an identifiable error before any work, with no network
    and no real provider.
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.6, 2.7, 4.5, 9.4, 10.5_
  - _Boundary: RefineSession + resolve_session_
  - _Depends: 1.1_

- [ ] 2. Core glue: stable-id reconstruction and the overview blueprint (pure, model-free)
- [ ] 2.1 (P) Reconstruct a stable-id `PlannedSegment` from a stored `Segment`
  - Add a pure `planned_from_segment(segment) -> PlannedSegment` that copies the stored
    segment's roles/intent/subjects and derives a stable `segment_key` such that
    `segment_id(planned)` round-trips to the stored segment's id, so a later rewrite re-wires
    the same id in place; evidence is reconstructed best-effort (an empty set is tolerated by
    the blueprint builder). It consults no model and never mutates the input.
  - Observable completion: a unit test confirms `segment_id(planned_from_segment(seg)) == seg.id`
    for representative stored segments and that `build_blueprint(planned_from_segment(seg), None,
    vocab)` returns a well-formed blueprint, with no model.
  - _Requirements: 5.2, 5.8_
  - _Boundary: planned_from_segment_
  - _Depends: 1.1_

- [ ] 2.2 (P) Build the deterministic overview-shaped blueprint
  - Add a pure
    `build_overview_blueprint(identity, vocab, analysis, *, guidance: str = "") -> CompositionBlueprint`
    (mirroring `build_blueprint`) whose title is the project overview title, whose chunks are
    the four overview sections (Purpose / Use cases / Features / Design choices) as its chunk
    headings, whose subjects are the project's salient subjects, and whose evidence anchors are
    derived from the optional analysis's salient entrypoints/components as available (empty tuple
    when absent); all labels derive from the loaded vocabulary / identity with no hardcoded
    role/intent literals. The `guidance` keyword is accepted for call-site uniformity but is
    **not** folded into the frozen blueprint (the human guidance reaches the agent through the
    writer's `guidance` keyword, never as a blueprint chunk/output heading).
  - Observable completion: a unit test confirms the blueprint is byte-deterministic for equal
    inputs (independent of the `guidance` value), carries the four overview chunks in order, uses
    only vocabulary/identity-derived labels, and tolerates a `None` analysis — with no model.
  - _Requirements: 7.1, 7.8_
  - _Boundary: build_overview_blueprint_
  - _Depends: 1.1_

- [ ] 2.3 (P) Thread the additive `guidance` keyword through the bounded writer (never echoed)
  - Extend the reused bounded writer with one optional, backward-compatible `guidance: str = ""`
    keyword threaded through `AgenticProseRunner.run` (`composition/agent.py`) →
    `build_agent_task` → `_render_description` (`composition/task_prompt.py`). When `guidance` is
    non-empty, `_render_description` SHALL emit one explicit author-guidance instruction near the
    mission ("Apply this refinement guidance to WHAT you write and emphasise; do NOT quote it,
    name it, or add a section/heading for it"), modelled on the existing role/COBESY
    anti-echo rules; when `guidance` is the empty string, no guidance line is emitted so the
    rendered task is byte-identical to today's. This is the only change outside `docuharnessx/mcp/`
    + the cli + the `pyproject` dep; it touches no frozen data seam (`run`/`build_agent_task`/
    `_render_description` are widened behind a default that preserves today's behaviour).
  - Observable completion: a unit test confirms (a) with `guidance=""` the rendered
    `BaseTask.description` is byte-identical to today's (the existing agentic-writer suite still
    passes); (b) with a non-empty `guidance`, the guidance instruction reaches the rendered
    `BaseTask.description` (the applied author-guidance line is present near the mission); and
    (c) the verbatim guidance text does **not** appear as a heading/section line in the
    description (applied, not echoed) — all with no model.
  - _Requirements: 5.2, 5.9, 7.2, 9.1, 9.7_
  - _Boundary: writer guidance keyword (composition/agent.py + composition/task_prompt.py)_
  - _Depends: 1.1_

- [ ] 3. The tool handlers over a session (gate-before-persist; anti-slop)
- [ ] 3.1 Implement the read-only, model-free tools: list / get / validate
  - Implement `list_segments` (the store's segments in by-id order, each with id/title/roles/
    intent/subjects), `get_segment(id)` (full segment incl. body; a missing id yields a
    structured tool error), and `validate_segment(id)` (run the deterministic structure gate
    over the body and return accepted/mermaid_blocks/cited_files/reason; a missing id yields a
    structured error). None of these consult a model.
  - Observable completion: unit tests over a fixture store confirm the three tools return the
    documented shapes in by-id order, surface a structured error for a missing id, use the same
    minimum-citations threshold the rewrite path enforces, and consult no model.
  - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 6.1, 6.2, 6.3, 6.4_
  - _Boundary: read/validate handlers_
  - _Depends: 1.2_

- [ ] 3.2 Implement `rewrite_segment` (re-grounded, gated, replace-in-place)
  - Implement `rewrite_segment(id, guidance)`: load the stored segment; when no model is bound
    return an explicit "no model configured" result without producing content; otherwise
    reconstruct the blueprint via `planned_from_segment` + `build_blueprint`, deliver the human
    guidance through the writer's `guidance` keyword
    (`AgenticProseRunner().run(blueprint, repo_path=session.target_repo, model=session.model(),
    guidance=guidance, min_citations=session.min_citations)` — never through the frozen
    blueprint), run the reused bounded writer over the read-only target repo, and — only when the
    structure gate accepts — wire the segment with the new body/summary (non-body fields fixed)
    and replace the existing `<id>.md` in place; on raise/timeout/empty/over-budget/reject,
    return the gate verdict and the deterministic fallback body without persisting and leave the
    stored segment unchanged.
  - Observable completion: with the scripted agentic provider over the fixture repo and a
    fixture store, a unit test confirms an accepted rewrite replaces the stored segment in place
    (same id, changed body containing Mermaid + citations); the supplied guidance reaches the
    agent's task while its verbatim text does NOT appear as a heading/section in the accepted
    body (applied, not echoed); a rejected/empty run persists nothing and surfaces the verdict +
    fallback; a no-model session returns the explicit result; the run is bounded and never
    free-writes — all with no network.
  - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 5.8, 5.9, 9.1, 9.2, 9.3, 9.5, 9.6, 9.7_
  - _Boundary: rewrite_segment handler_
  - _Depends: 2.1, 2.3, 3.1_

- [ ] 3.3 Implement the overview tools: draft / refine / get (re-grounded, gated)
  - Implement `draft_overview()` and `refine_overview(guidance)`: build the overview-shaped
    blueprint via `build_overview_blueprint(session.identity, session.vocab, session.analysis,
    guidance=guidance)` and run the reused `AgenticProseRunner` over it —
    `draft_overview` with `guidance=""` (`run(..., guidance="")`), `refine_overview` forwarding
    the human guidance through the writer's `guidance` keyword (`run(..., guidance=guidance)`,
    never through the frozen blueprint) — gate the body, persist the overview as a reserved
    first-class entry only on accept, surface the verdict + fallback without persisting on
    reject, and return an explicit result with no model; and `get_overview()` (the persisted
    overview body or an explicit "no overview drafted yet" result).
  - Observable completion: with the scripted provider over the fixture repo, a unit test confirms
    `draft_overview` then `refine_overview` persist gate-passing overviews structured around
    Purpose/Use cases/Features/Design choices, the refine guidance reaches the agent's task while
    its verbatim text does NOT appear as a heading/section in the accepted overview (applied, not
    echoed), `get_overview` returns the persisted body, a rejected run persists nothing, and a
    no-model session returns the explicit result — no network, reusing the writer + gate only.
  - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7, 7.8, 9.1, 9.2, 9.3, 9.5, 9.6, 9.7_
  - _Boundary: overview handlers_
  - _Depends: 2.2, 2.3, 3.1_

- [ ] 3.4 Implement `reassemble_site` (ReviewReport-from-store; model-free)
  - Implement `reassemble_site()`: build a `ReviewReport` whose accepted set is the current
    store segments (plus the persisted overview when present) with a well-formed aggregate, call
    the reused `assemble_site` with the session's vocabulary, optional analysis, output dir, and
    per-target identity, and return the site directory and the per-segment / per-role page
    counts; an empty store yields a well-formed empty site with a zero page count. It consults
    no model and writes only under the output dir.
  - Observable completion: a unit test confirms a populated store yields a non-empty site
    reflecting the current bodies + overview, an empty store yields a well-formed empty site with
    zero pages, the per-target identity is reused (never DocuHarnessX's), and nothing is written
    into the target repo — with no model.
  - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 9.4_
  - _Boundary: reassemble_site handler_
  - _Depends: 3.1_

- [ ] 4. The MCP server: registration, dispatch, and the stdio launcher
- [ ] 4.1 Build the server factory: tool registration + dispatch with structured errors
  - Add `schemas.py` (the typed input schemas + the structured result/error envelopes) and
    `build_refine_server(session=None) -> Server` registering the nine tools (`open_workspace`,
    `list_segments`, `get_segment`, `rewrite_segment`, `validate_segment`, `reassemble_site`,
    `get_overview`, `draft_overview`, `refine_overview`) via the low-level MCP `list_tools` /
    `call_tool` decorators; `call_tool` validates arguments, dispatches to the matching handler
    over the bound session (offloading the model-touching handlers off the async loop), wraps the
    result as MCP content, and returns a structured tool error for a missing/malformed argument or
    an unknown tool without crashing the dispatch loop.
  - Observable completion: an in-process integration test (no stdio subprocess, no model) lists
    the nine tools with their schemas, dispatches a valid `list_segments` / `validate_segment`
    call, and confirms a missing required argument and an unknown tool each return a structured
    error rather than raising.
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 10.3_
  - _Boundary: build_refine_server + schemas_
  - _Depends: 3.1, 3.2, 3.3, 3.4_

- [ ] 4.3 Add the `open_workspace` tool + the mutable active-workspace holder
  - Add the `open_workspace` `mcp.types.Tool` descriptor to `schemas.py` (required `repo`,
    optional `out` / `config`) and the `no_workspace_error` (code `no_workspace`) +
    `open_workspace_failed_error` (code `open_failed`) envelopes; add `workspace_summary(session)`
    to `handlers.py` (`opened` / `repo` / `out` / `segment_count` / `site_name` /
    `model_available`). In `server.py`, hold a small mutable `_ActiveWorkspace(session)` set by
    the optional initial session, and route `open_workspace` through `_open_workspace(arguments)`
    that calls `resolve_session(repo, out, config_path=config)` on demand, sets `active.session`,
    and returns the summary — catching a `DocuHarnessXError` into the structured `open_failed`
    error rather than crashing. Every other tool returns the structured `no_workspace` error when
    `active.session is None`, so the agent sets the docs location at run time rather than the
    launcher hardcoding `--out`.
  - Observable completion: an in-process integration test confirms a server built with **no**
    session returns the structured `no_workspace` error for `list_segments` (and the other
    non-open tools) until `open_workspace(repo, out)` is called, after which those tools act on
    the resolved active workspace and `open_workspace` returns the summary; a bad target repo (or
    malformed `config`) returns the structured `open_failed` error rather than raising — all with
    no model and no stdio subprocess.
  - _Requirements: 2.7, 2.8, 2.9, 2.10, 3.1, 3.4, 3.5, 3.6, 10.3_
  - _Boundary: open_workspace tool + active-workspace holder_
  - _Depends: 4.1_

- [ ] 4.2 Add the stdio launcher and re-export the public surface
  - Add `run_stdio(session=None)` that opens the stdio transport, builds the server (forwarding
    the optional initial session), and drives `Server.run` over the inherited streams, and
    re-export `build_refine_server` / `run_stdio` / `RefineSession` / `resolve_session` / the
    handlers from the package `__init__`. The launcher writes nothing to stdout except the MCP
    protocol stream.
  - Observable completion: a unit test confirms the package re-exports the public surface and
    that `run_stdio` wires the built server to the stdio streams (driven against in-memory
    streams so it terminates), writing no non-protocol bytes to stdout.
  - _Requirements: 1.5, 2.5, 3.6_
  - _Boundary: run_stdio + package surface_
  - _Depends: 4.1, 4.3_

- [ ] 5. CLI integration: the `dhx mcp` subcommand
- [ ] 5.1 Declare the `mcp` SDK as a direct dependency
  - Add `"mcp>=1.28"` to `[project].dependencies` in `pyproject.toml`: the SDK is importable in
    the working venv (1.28.0) only because HarnessX pulls it in transitively for its MCP *client*,
    but this feature makes `mcp` a **direct** runtime dependency of `docuharnessx`, so it must be
    declared (a version floor matching the existing `mkdocs>=1.6` style, no upper pin); this is the
    only build-config change.
  - Observable completion: `pyproject.toml` lists `mcp>=1.28` as a direct dependency and a fresh
    `pip install -e .` resolves it (offline: importing `mcp.server` succeeds against the declared
    floor).
  - _Requirements: 1.4_
  - _Boundary: build config_

- [ ] 5.2 Add the `dhx mcp` subcommand and route it to the launcher (optional pre-open target)
  - Extend the existing `dhx` parser with an `mcp` subparser with an **optional** target repo
    (`nargs="?"`) plus `--out`, `--config`, `-v` mirroring `run`, add `"mcp"` to the subcommand
    set so the bare form still works, add a `_mcp_command(args)` that — **when a target repo is
    given** — validates it and resolves the session to **pre-open** it (passing
    `config_path=args.config`), otherwise launches generic with `session=None`, then launches the
    stdio server via `_run_stdio_blocking(session)`, and route `mcp` in `main` — sending all
    human/log output to stderr so stdout stays the MCP channel, and leaving `run`/`init`/bare-form
    untouched. Guard the `mcp`-SDK import with a typed, dependency-naming error (mirroring the
    existing `_require_harnessx()`) so a stripped install reports the missing SDK cleanly.
  - Observable completion: a unit test confirms `dhx mcp <repo>` parses to the `mcp` command and
    pre-opens the session (an invalid target exits non-zero with an identifiable error), `dhx mcp`
    with **no** target parses and launches generic (`session=None`, the agent opens the workspace
    via `open_workspace`), the launcher writes nothing to stdout except the protocol stream, and
    `dhx run` / `dhx init` / the bare `dhx <repo>` form still parse unchanged.
  - _Requirements: 1.1, 1.3, 2.1, 2.2, 2.5, 2.6_
  - _Boundary: dhx mcp subcommand_
  - _Depends: 4.2, 5.1_

- [ ] 6. Validation: credential-free end-to-end and regression checks
- [ ] 6.1 Verify the credential-free refine loop produces a non-empty site
  - Run an end-to-end refine loop with the scripted agentic provider over the fixture repo and a
    fixture store: rewrite a segment (or draft an overview), then reassemble the site, and
    confirm the rebuilt site is non-empty and contains the gate-passing body, with no network
    access and no credentials.
  - Observable completion: an end-to-end test drives rewrite/overview -> reassemble through the
    scripted provider and asserts the persisted gate-passing body appears in a non-empty rebuilt
    site, offline.
  - _Requirements: 10.1, 10.2, 10.4_
  - _Boundary: end-to-end refine loop_
  - _Depends: 3.2, 3.3, 3.4_

- [ ] 6.2 Verify the existing seams, stages, and tests are unaffected
  - Run the existing suite to confirm the MCP feature changed only `docuharnessx/mcp/`, the one
    `dhx mcp` subcommand, the `pyproject` `mcp>=1.28` dependency, and the additive `guidance`
    keyword on the writer (`composition/agent.py` + `composition/task_prompt.py`), and that the
    frozen data seams, the pipeline stages, the assembler renderers, the model resolver, and the
    `dhx run` / `dhx init` paths are unchanged. The writer change SHALL keep `guidance=""`
    byte-identical to today's task so the existing agentic-writer tests pass unchanged.
  - Observable completion: the existing pipeline, assembler, review, agentic-writer, and CLI
    tests pass unchanged against the added feature; a check confirms no frozen-data-seam / stage
    / assembler module was modified, and that the only writer edit is the additive `guidance`
    keyword (default `""` reproduces the prior task byte-for-byte).
  - _Requirements: 1.2, 1.4_
  - _Boundary: cross-feature regression_
  - _Depends: 5.2_
