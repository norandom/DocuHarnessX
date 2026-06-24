# Research & Design Decisions

## Summary
- **Feature**: `agentic-codebase-writer`
- **Discovery Scope**: Extension (replaces the merged `cobesy-writer` Write stage in place;
  integration-focused light discovery)
- **Key Findings**:
  - HarnessX has no codebase RAG. Codebase context is agentic: an agent reads the repo via
    the built-in read/grep/glob/bash tools, and the run loop appends each tool result as a
    `role=tool` message the model then reads. This is the intended mechanism for grounding.
  - The existing Write stage is already a thin HarnessX adapter over a pure composition core
    with a stable contract (`STAGE_NAME`/`WriteStage`/`make_write_stage`/module path), a
    deterministic blueprint/wiring/fallback, and a single model surface
    (`composition.prose.generate_prose`). Only the prose surface needs to become agentic; the
    blueprint, wiring, fallback, and the `WrittenSegments`/`Segment` output seam are reused
    verbatim, so the single-stage-swap constraint holds.
  - All HarnessX agentic APIs the brief names are present and verified against the installed
    package: `build_default_tools()`, `Workspace(... mode="readonly")`, `bundles.context`,
    `make_window_mgmt`, `make_control(...)`, `ModelConfig(main=...).agentic(config)`, and
    `Harness.run(BaseTask(...))` returning a `HarnessResult` whose `task_end` carries
    `final_output`, `final_messages`, `total_cost_usd`, `total_steps`, and `exit_reason`.

## Research Log

### HarnessX agentic surface (verified against `.venv/lib/python3.12/site-packages/harnessx`)
- **Context**: The writer must be built as a real agent, not another single-shot `complete()`.
- **Sources Consulted**: `tools/builtin/__init__.py` (`build_default_tools`),
  `workspace/workspace.py` (`Workspace`), `bundles/context.py` (`make_context`/`context`,
  `make_window_mgmt`), `bundles/control.py` (`make_control`), `core/model_config.py`
  (`ModelConfig.main`, `.agentic`), `core/harness.py` (`Harness.run`, `BaseTask`,
  `HarnessResult`, `HarnessConfig`), `core/events.py` (`TaskEndEvent`, `ModelResponseEvent`,
  `ToolCall`).
- **Findings**:
  - `build_default_tools()` returns an `InMemoryToolRegistry` registered with
    `bash/read/write/edit/glob/grep` (+ web/spawn). Filesystem tools route through the active
    sandbox/workspace set by `Harness.run` via `get_current_sandbox()`. We will offer the
    registry but root it at a **read-only** workspace so write/edit cannot mutate the target.
  - `Workspace` accepts `agent_id`, an explicit `root=<target repo path>`, and
    `mode="readonly"`; a readonly workspace raises `WorkspaceWriteError` on any write, and
    `resolve()` jails paths to `root`. This is exactly the read-only repo view the brief asks
    for.
  - `make_control(loop_threshold=..., max_cost_usd=..., include_budget=True,
    token_threshold=..., message_threshold=...)` composes `LoopDetectionProcessor`,
    `CostGuardProcessor`, and (with `include_budget`) compaction/budget processors — the
    bounded guarantee.
  - `BaseTask(description=..., max_steps=..., max_cost_usd=..., token_budget=...)` carries the
    per-run hard caps; `state.budget_exceeded()` halts on step or cost overflow.
  - `HarnessResult.task_end.final_output` is the final assistant text; `final_messages` is the
    full end-of-task conversation; `total_cost_usd`/`total_steps`/`exit_reason` are the bounded
    telemetry the journal records.
- **Implications**: The agentic writer is assembled as `HarnessConfig` =
  `context | window_mgmt | control(bounded)` with `tool_registry=build_default_tools()` and a
  read-only `Workspace`, bound to the run's model via `ModelConfig(main=...).agentic(config)`,
  and run per segment via `await harness.run(BaseTask(...))`. The segment body is
  `task_end.final_output`.

### The existing Write stage and composition core (the slot to preserve)
- **Context**: The new writer must drop into the exact same slot and reuse the deterministic
  structure work.
- **Sources Consulted**: `docuharnessx/stages/write.py`, `docuharnessx/stages/plan.py`,
  `docuharnessx/composition/{__init__,model,blueprint,prompt,prose,wiring,fallback}.py`,
  `docuharnessx/context.py`, `docuharnessx/planning/model.py`,
  `docuharnessx/assembler/mkdocs_config.py`, `tests/_fakes.py`.
- **Findings**:
  - `WriteStage(NoOpStage)` captures the run `State` on `on_task_start`, reads inputs through
    `RunContext`, composes per planned segment (blueprint → prose → fallback → wiring →
    validate → store), publishes `WrittenSegments` to `SLOT_WRITTEN_SEGMENTS`, and journals a
    bounded summary. The model is reached via `_writer_model()` over
    `getattr(self, "_model_config", None).main` — identical to `PlanStage._relevance_model`.
  - The model-touching call is offloaded with `asyncio.to_thread` so its private loop never
    nests inside the pipeline run loop. The agentic `Harness.run` (a coroutine) needs the same
    treatment.
  - `build_blueprint`, `wire_segment`, `render_fallback_body/summary`, the `ProseResult`
    carrier, the `WriteFlag`/`WrittenSegments` seam, and `WriterInputError` are all reusable
    unchanged. Only `composition.prompt.build_request` (single-shot, `tools=[]`) and
    `composition.prose.generate_prose` (single `complete()`) are replaced by agentic
    equivalents.
  - `Harness._instantiate_runtime`/`run` binds `_model_config` and `_rt` onto processors
    (`proc._bind_model_config(...)`, `proc._bind_runtime(...)`), so the stage already receives
    the model config the agentic writer reuses.
- **Implications**: A new module `composition/agent.py` (the agentic prose surface) plus a
  new `composition/task_prompt.py` (the agentic task prompt builder) are added beside the
  existing core; `stages/write.py` swaps its `_prose_for` model call from `generate_prose`
  to the agentic runner. `blueprint.py`/`wiring.py`/`fallback.py`/`model.py` are untouched.

### Mermaid rendering in the assembled site
- **Context**: Emitted Mermaid fences must render in Material.
- **Sources Consulted**: `docuharnessx/assembler/mkdocs_config.py`. No `markdown_extensions`
  block is currently emitted.
- **Findings**: Material renders Mermaid through the `pymdownx.superfences` custom fence
  (`name: mermaid`, `class: mermaid`, `format: !!python/name:pymdownx.superfences.fence_code_format`).
  This requires a `markdown_extensions` entry in `mkdocs.yml`. The current builder emits
  `theme`/`plugins`/`nav` but no `markdown_extensions`.
- **Implications**: Add a single deterministic `markdown_extensions` block enabling
  `pymdownx.superfences` with the mermaid custom fence to `build_mkdocs_yaml`. This is the only
  edit outside the Write stage; it is idempotent (one fixed block) and changes no other key.

### Credential-free testability with a scripted fake agent
- **Context**: The agentic loop calls tools, so the old single-`complete` fake is insufficient.
- **Sources Consulted**: `tests/_fakes.py` (`FakeProvider`, `RoutingFakeProvider`),
  `core/events.py` (`ModelResponseEvent.tool_calls`, `ToolCall`).
- **Findings**: A `BaseModelProvider`-shaped fake whose `complete` returns a
  `ModelResponseEvent` carrying `tool_calls` drives the real run loop to execute those tools
  (real read/grep over a fixture repo); a subsequent `complete` returning `content` (with
  Mermaid + `file:line` citations) and `finish_reason="end_turn"` ends the turn. The existing
  `RoutingFakeProvider` already routes by prompt content for the writer/judge accept path, so
  the fixture body must satisfy both the new structure validation and the judge's accept path.
- **Implications**: Add a `ScriptedAgentProvider` test fake that returns a deterministic
  sequence of tool-call responses then a final grounded body, plus a crafted fixture repo, so
  the full pipeline stays green offline and the assembled site is non-empty.

## Architecture Pattern Evaluation

| Option | Description | Strengths | Risks / Limitations | Notes |
|--------|-------------|-----------|---------------------|-------|
| Agentic prose surface behind the existing thin adapter (chosen) | Replace only `generate_prose` with an agentic runner; keep blueprint/wiring/fallback/seam | Minimal blast radius; single-stage swap holds; determinism stays in orchestration | Agentic prose is non-deterministic (mitigated by structure validation + fallback) | Mirrors the existing `prose.py` boundary |
| Rewrite the whole Write stage | New stage logic, new seam | Clean slate | Violates single-stage-swap; breaks review/assemble/deploy; huge blast radius | Rejected |
| Build a custom RAG/embedding index | Pre-index repo, retrieve chunks | Deterministic retrieval | Explicitly out of scope; HarnessX is agentic-by-tools; large new subsystem | Rejected per brief |

## Design Decisions

### Decision: Isolate the agentic run behind the existing prose-surface boundary
- **Context**: The brief requires a single-stage swap and reuse of the deterministic core.
- **Alternatives Considered**: 1) Full stage rewrite. 2) New parallel stage. 3) Agentic
  surface behind the existing boundary.
- **Selected Approach**: Add `composition/agent.py` (`generate_segment_agentically`) and
  `composition/task_prompt.py` (`build_agent_task`) beside the existing core. `WriteStage`
  keeps its lifecycle and only changes which function it offloads to a worker thread.
- **Rationale**: Keeps the change surgical; the deterministic blueprint/wiring/fallback and
  the frozen output seam are untouched, so review/assemble/deploy need no change.
- **Trade-offs**: The agentic runner is heavier than a single `complete()`; bounded via
  Control + per-task caps. Non-determinism is contained by structure validation + fallback.
- **Follow-up**: Verify per-segment cost isolation and the `asyncio.to_thread` offload.

### Decision: Determinism shifts to orchestration; correctness gated by structure validation
- **Context**: The agentic loop is non-deterministic, conflicting with the old "deterministic
  bounded single-shot" objective.
- **Selected Approach**: The orchestration (blueprint, task prompt assembly, wiring, segment
  ordering, bounded budgets) is deterministic. The agent's prose is model-dependent but must
  pass a deterministic structure gate (≥1 valid Mermaid fence, ≥N `file:line` citations) to be
  accepted; otherwise the deterministic fallback body is used.
- **Rationale**: Preserves the bounded + always-usable guarantees while unlocking grounded
  content.
- **Trade-offs**: A strict gate may reject a usable-but-unconventional body (acceptable: the
  fallback keeps the run usable, and the gate threshold is configurable).

### Decision: Read-only Workspace rooted at the target repo
- **Context**: The agent must read real source but never modify the target.
- **Selected Approach**: `Workspace(agent_id="docuharnessx-writer", root=<target_repo>,
  mode="readonly")`. The default tool registry is offered, but writes are jailed/blocked by the
  readonly workspace.
- **Rationale**: Native HarnessX safety; no custom tool filtering needed.
- **Trade-offs**: `bash` is still offered (read-only filesystem); acceptable for exploration
  and bounded by Control. A tighter tool subset is a possible future refinement.

### Decision: Scripted fake-agent provider + crafted fixture repo for offline tests
- **Context**: Tests must exercise the real run loop and real tools with no network.
- **Selected Approach**: A `ScriptedAgentProvider` returning a deterministic sequence of
  tool-call `ModelResponseEvent`s then a final grounded body; a fixture repo under
  `tests/fixtures/` whose files make the reads and citations deterministic.
- **Rationale**: Mirrors the existing `_fakes.py` approach; reaches the review accept path so
  the site is non-empty.

## Risks & Mitigations
- **Non-determinism breaks reproducible tests** → Use the scripted fake in tests; production
  uses a real model. The deterministic core stays unit-testable without a model.
- **Runaway cost on large repos** → Per-segment `max_steps`/`max_cost_usd`/`token_budget` +
  loop detection; bounds applied per segment so one segment cannot starve the rest.
- **Agent emits invalid/no Mermaid or no citations** → Deterministic structure gate rejects
  the body; fallback renders a usable deterministic body; provenance recorded.
- **`asyncio.run` nesting inside the pipeline run loop** → Offload `Harness.run` via
  `asyncio.to_thread`, exactly as `PlanStage`/`prose.py` do today.
- **Mermaid fence change regresses the strict build** → One idempotent `markdown_extensions`
  block; covered by an assembler build test with a Mermaid page.

## References
- HarnessX installed package: `.venv/lib/python3.12/site-packages/harnessx/`
  (`tools/builtin`, `workspace/workspace.py`, `bundles/{context,control}.py`,
  `core/{harness,model_config,events}.py`).
- Material for MkDocs Mermaid via `pymdownx.superfences` custom fence (steering `tech.md`
  output target).
- deepwiki-open — quality bar: model-generated Mermaid with strict syntax + mandatory
  `file:line` citations + pages grounded in real source.
