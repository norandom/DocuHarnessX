---
id: component:composition
title: What does composition do?
subjects:
- composition
summary: '`docuharnessx/composition` is the documentation **writing core** of DocuHarnessX.
  Its package docstring calls it "the pure, model-free COBESY composition core": it
  turns each `PlannedSegment` of the frozen `CoveragePlan` into a COBESY-structured
  composition blueprint *before* any prose, and then renders an ontology `Segment`
  (`docuharnessx/composition/__init__.py:1-9`). The key architectural claim, repeated
  throughout the modules, is that **all structural work is deterministic and model-free**;
  only one gated prose step touches a model. `WriteStage` in `docuharnessx/stages/write.py`
  is described as a "thin HarnessX adapter" over this core (`docuharnessx/stages/write.py:6-9`).'
related: []
cited_files:
- docuharnessx/composition/__init__.py
- docuharnessx/stages/write.py
- docuharnessx/composition/blueprint.py
- docuharnessx/composition/model.py
- docuharnessx/composition/prompt.py
- docuharnessx/composition/prose.py
- docuharnessx/composition/fallback.py
- docuharnessx/composition/wiring.py
- docuharnessx/composition/agent.py
- docuharnessx/composition/budgets.py
- docuharnessx/composition/harness_factory.py
- docuharnessx/composition/explore_writer.py
---
# What `docuharnessx.composition` does

`docuharnessx/composition` is the documentation **writing core** of DocuHarnessX. Its package docstring calls it "the pure, model-free COBESY composition core": it turns each `PlannedSegment` of the frozen `CoveragePlan` into a COBESY-structured composition blueprint *before* any prose, and then renders an ontology `Segment` (`docuharnessx/composition/__init__.py:1-9`). The key architectural claim, repeated throughout the modules, is that **all structural work is deterministic and model-free**; only one gated prose step touches a model. `WriteStage` in `docuharnessx/stages/write.py` is described as a "thin HarnessX adapter" over this core (`docuharnessx/stages/write.py:6-9`).

The package is organized around a per-segment pipeline of deterministic functions plus one bounded model surface, re-exported from the single namespace `docuharnessx.composition` so downstream consumers (the `WriteStage` adapter and tests) never reach into submodules (`docuharnessx/composition/__init__.py:11-13`, `__init__.py:24-34`).

## The deterministic COBESY blueprint

`build_blueprint(planned, analysis, vocab)` (`docuharnessx/composition/blueprint.py:356`) is a pure function: it reads one frozen `PlannedSegment`, an optional `RepoAnalysis`, and the loaded `Vocabulary`, and returns a frozen `CompositionBlueprint` (`docuharnessx/composition/blueprint.py:401-415`). Every structural decision — the SCQA opener (`_build_scqa`), the Minto "lead-with-conclusion" key message (`_key_message`), the working-memory `Chunk` plan (`_build_chunks`), the REDUCE-barrier fast path (`_build_fast_path`), the andragogy flag, and the title (`_build_title`) — is derived from the segment's `roles`/`intent` looked up in the loaded `Vocabulary`'s `AxisTerm` labels and descriptions, never from hardcoded role/intent literals (`docuharnessx/composition/blueprint.py:10-18`). Evidence anchors copy `planned.evidence` verbatim and are enriched with a short `note` from a matching `RepoAnalysis` finding when one exists; an absent analysis yields `""` so no repository fact is invented (`docuharnessx/composition/blueprint.py:171-208`, `blueprint.py:25-28`).

The data model itself lives in `docuharnessx/composition/model.py`: `CompositionBlueprint` carries `scqa`, `key_message`, `chunks`, `fast_path`, `andragogy`, `evidence_anchors`, and the resolved `role_labels`/`intent_label` (`docuharnessx/composition/model.py:118-153`). All these value objects are `@dataclass(frozen=True)` with `tuple` collection fields so equal inputs yield an equal, hashable blueprint (`docuharnessx/composition/model.py:24-32`).

## From blueprint to a model request

`build_request(blueprint)` (`docuharnessx/composition/prompt.py:70`) assembles the `(messages, tools)` pair the prose step issues. It renders a fixed `_SYSTEM_PROMPT` naming the COBESY moves the model must honor (SCQA → Minto lead → working-memory chunks → REDUCE fast path), plus a user brief built only from blueprint-derived facts — axis labels, SCQA moves, chunk headings, fast-path steps, and evidence anchors (`docuharnessx/composition/prompt.py:50-67`, `prompt.py:121-167`). It never includes raw repository file contents (`prompt.py:22-26`), and `tools` is always `[]` because prose generation is a single-shot call, not an agentic loop (`docuharnessx/composition/prompt.py:94-96`). The `harnessx.core.events.Message` import is lazy with a plain-dict fallback so the core never hard-depends on HarnessX at import time (`docuharnessx/composition/prompt.py:99-118`).

## The single model surface, and its deterministic fallback

`generate_prose(blueprint, *, model, timeout_s=DEFAULT_PROSE_TIMEOUT_S)` (`docuharnessx/composition/prose.py:72`) is the only module in the core that may consult a model (`docuharnessx/composition/prose.py:1-9`). It makes at most one bounded `complete` call under `DEFAULT_PROSE_TIMEOUT_S = 60.0` (`docuharnessx/composition/prose.py:69`), driven by `asyncio.run` + `asyncio.wait_for` (`docuharnessx/composition/prose.py:145-168`), and parses the response deterministically — a structured JSON `{"body": ..., "summary": ...}` first, with a plain-prose fallback that derives a summary from the body's lead line (`docuharnessx/composition/prose.py:176-210`). Every failure (no model, raise, timeout, empty or unparseable content) is absorbed and returns `None`, never raising (`docuharnessx/composition/prose.py:103-137`).

When prose is `None`, the deterministic fallback renderer takes over: `render_fallback_body(blueprint)` and `render_fallback_summary(blueprint)` (`docuharnessx/composition/fallback.py`) produce a valid Markdown body honoring the blueprint's COBESY structure in reading order — title, Minto key message first, SCQA opener (with a Knowles andragogy note when `blueprint.andragogy` is set), `##` working-memory chunks, the REDUCE fast path as an ordered list, and the evidence anchors as a grounding reference list (`docuharnessx/composition/fallback.py:1-30`). Because it is pure, a credential-free run still produces one valid `Segment` per planned segment, byte-equal across model-free runs (`docuharnessx/composition/fallback.py:9-14`).

## Wiring the final ontology Segment

`wire_segment(planned, blueprint, prose)` (`docuharnessx/composition/wiring.py:99`) maps the non-body fields — `id` via `segment_id(planned)`, `roles`/`subjects`/`intent`, `title`, empty `related`, `schema_version` — from the planned segment and blueprint into a *new* ontology `Segment`, and takes `body`/`summary` **only** from the `ProseResult` (`docuharnessx/composition/wiring.py:106-126`, `wiring.py:13-18`). The model therefore can never influence any non-body field. `segment_id` (`docuharnessx/composition/wiring.py:78`) derives a deterministic, filesystem-safe id (`"<sanitized-segment_key>-<short-blake2b-hash>"`) that doubles as the matching key for the review gate and as a valid single-segment filename (`docuharnessx/composition/wiring.py:78-96`).

## The agentic writer surface

Alongside the single-shot `generate_prose`, the package grew a per-segment agentic writer. `AgenticProseRunner.run(...)` (`docuharnessx/composition/agent.py:129`) runs **one bounded HarnessX agent per planned segment**: it builds a model-free read-only harness config via `build_writer_harness(repo_path)` (`docuharnessx/composition/harness_factory.py`), binds the model with `ModelConfig(main=model).agentic(config)` inside a private event loop (`docuharnessx/composition/agent.py:324-344`), builds a scoped COBESY `BaseTask` via `build_agent_task` (`docuharnessx/composition/agent.py:214-222`), drives `await harness.run(task)`, takes the body from `result.task_end.final_output`, and pushes it through the deterministic structure gate `validate_agent_body` requiring ≥1 valid Mermaid fence and ≥`MIN_CITED_FILES` distinct `file:line` citations (`docuharnessx/composition/agent.py:260-283`). An accepted body becomes a `ProseResult(source="model")` verbatim; every failure path returns `(None, AgentRunStats)` so the caller renders the deterministic fallback — the runner never raises (`docuharnessx/composition/agent.py:27-37`, `agent.py:285-295`).

The bounds for that agent are pinned in `docuharnessx/composition/budgets.py` as shared, auditable constants — `WRITER_MAX_STEPS` (default 24), `WRITER_MAX_COST_USD` (5.00), `WRITER_TOKEN_BUDGET` (1,000,000), `WRITER_TOKEN_THRESHOLD` (150,000), `WRITER_LOOP_THRESHOLD` (6), and `MIN_CITED_FILES` (3) — each overridable at import time via a `DHX_WRITER_*` environment variable (`docuharnessx/composition/budgets.py:81-124`). `build_writer_harness` composes these into a `HarnessConfig` with `build_default_tools()` (read/grep/glob/bash), a `Workspace(agent_id="docuharnessx-writer", root=repo_path, mode="readonly")` jail, `make_control` loop detection + cost guard, and `make_window_mgmt` context compaction, and deliberately carries no model (`docuharnessx/composition/harness_factory.py:19-50`).

## The output seam and its consumer

The package also defines the frozen output seam the review gate consumes: `ProseResult`, `WrittenSegments`, `WriteFlag`, and the `WriterError`/`WriterInputError` hierarchy, all re-exported from `docuharnessx/composition/__init__.py` (`docuharnessx/composition/__init__.py:88-98`, `model.py:161-247`). The consumer, `WriteStage` (`docuharnessx/stages/write.py:156`), iterates `plan.segments` in plan order; for each segment `_compose_segment` calls `build_blueprint`, obtains prose (the bounded `AgenticProseRunner` offloaded via `asyncio.to_thread`, else the deterministic fallback), and calls `wire_segment` (`docuharnessx/stages/write.py:406-431`, `write.py:477-482`). It then validates and stores each `Segment` or records a `WriteFlag`, and publishes an ordered `WrittenSegments` into the `SLOT_WRITTEN_SEGMENTS` slot (`docuharnessx/stages/write.py:345-404`, `write.py:495-536`).

## One more variant: per-question writing

Finally, `docuharnessx/composition/explore_writer.py` reuses the same machinery in a question-oriented mode: `write_questions` drives the read-only writer harness once per planned `Question` via `build_question_task` and `validate_page_body`, returning either an accepted `Page` or a closed-set `Omission` (`docuharnessx/composition/explore_writer.py:31-70`); ungrounded results are omitted rather than replaced with an invented outline body (`docuharnessx/composition/explore_writer.py:1-8`).

In short: **composition is the deterministic writer core** — it builds a per-segment COBESY structure from the planner's `PlannedSegment` and the loaded `Vocabulary`, turns that blueprint into a model request or a model-free fallback body, wires the result into an ontology `Segment` where the model only ever contributes `body`/`summary`, and publishes the written set through a frozen `WrittenSegments` seam — with `AgenticProseRunner`/`AgentRunStats` added as a bounded, gated per-segment model surface and `write_questions` as the per-question adaptation of the same harness.