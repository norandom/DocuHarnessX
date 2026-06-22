# Implementation Plan

- [x] 1. Foundation: composition data model and the written-segments seam
- [x] 1.1 Create the composition data model
  - Add `docuharnessx/composition/model.py` with frozen dataclasses: `SCQAOpener`, `Chunk`, `EvidenceAnchor`, `CompositionBlueprint`, `ProseResult`, `WriteFlag`, `WrittenSegments`, and the `WriterError`/`WriterInputError` hierarchy
  - Every collection field is a `tuple[...]`; types are `@dataclass(frozen=True)` so instances are deeply immutable and compare by value (mirrors `planning.model`)
  - Add `docuharnessx/composition/__init__.py` re-exporting only the model types created here (with their `__all__`); the core entry points are re-exported later by the integration task once their modules exist, so the parallel core tasks (2.1-2.4) each add only their own self-contained module file and never edit `__init__.py` (keeps their `(P)` claim contention-free)
  - Observable: importing `docuharnessx.composition` exposes all model types via `__all__`; constructing each type and comparing two equal instances returns `True`
  - _Requirements: 3.1, 3.6, 5.1, 6.2, 7.1, 7.4_
  - _Boundary: CompositionModel_

- [x] 1.2 Add the `SLOT_WRITTEN_SEGMENTS` slot key and `RunContext` accessor (append-only)
  - Append `SLOT_WRITTEN_SEGMENTS = "docuharnessx.written_segments"` to `docuharnessx/types.py` and add it to `__all__`, changing no existing slot key, `StageName`, or `STAGE_NAMES` entry
  - Append `_SLOT_TYPE_WRITTEN_SEGMENTS`, a TYPE_CHECKING import of `WrittenSegments`, and `set_written_segments(value)` / `written_segments()` accessors to `docuharnessx/context.py`
  - Observable: `RunContext.written_segments()` returns `None` on an unset slot and returns the stored `WrittenSegments` after `set_written_segments(...)`; the existing types/context test suites still pass unchanged
  - _Requirements: 7.1, 7.2, 7.3_
  - _Boundary: types/context additions_
  - _Depends: 1.1_

- [x] 2. Core: deterministic, model-free composition components
- [x] 2.1 (P) Build the deterministic COBESY blueprint builder
  - Add `docuharnessx/composition/blueprint.py` with `build_blueprint(planned, analysis, vocab) -> CompositionBlueprint`
  - Derive the SCQA opener, Minto key message, working-memory chunks, REDUCE fast-path, and the andragogy flag from the segment's `roles`/`intent` looked up in the loaded `Vocabulary` (`AxisTerm` label/description) — no hardcoded role/intent/subject literals
  - Decide andragogy (expert framing) per the loaded vocabulary term, not a closed role set; derive a deterministic `title` from the intent label + leading subject
  - Build `evidence_anchors` from `planned.evidence` verbatim, enriched by the matching `RepoAnalysis` finding when present and tolerating `analysis is None`
  - Observable: unit tests show the blueprint's SCQA/Minto/chunk/fast-path fields populated from a custom `Vocabulary`, the andragogy flag set for an expert role, evidence anchors built with and without analysis, and equal inputs producing an equal blueprint
  - _Requirements: 2.5, 2.6, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 9.1, 9.2_
  - _Boundary: Blueprint Builder_
  - _Depends: 1.1_

- [x] 2.2 (P) Build the deterministic prompt assembler
  - Add `docuharnessx/composition/prompt.py` with `build_request(blueprint) -> (messages, tools)`
  - System prompt instructs honoring SCQA → Minto lead → working-memory chunks → REDUCE fast path and grounding claims in the supplied evidence anchors, returning body + summary; user message carries a compact brief built only from blueprint-derived facts (axis labels, key message, chunk headings/points, fast-path, evidence anchors) — no raw repository file contents
  - Return `tools == []`; import `harnessx.core.events.Message` lazily with a plain-dict fallback so the core never hard-depends on the harness at import time
  - Observable: unit tests show equal blueprints produce equal `(messages, tools)`, the request contains only blueprint-derived facts (no file contents), and `tools` is empty
  - _Requirements: 4.1, 4.2_
  - _Boundary: Prompt Assembler_
  - _Depends: 1.1_

- [x] 2.3 (P) Build the deterministic segment wiring
  - Add `docuharnessx/composition/wiring.py` with `segment_id(planned)` and `wire_segment(planned, blueprint, prose) -> Segment`
  - `segment_id` derives a deterministic, filesystem-safe (no `/`, `\`, `.`/`..`), unique id from the `PlannedSegment` (sanitized `segment_key` + short stable hash) so equal plans yield equal ids
  - `wire_segment` sets `id`, `roles`, `subjects`, `intent`, `related` (default empty), `schema_version = ontology.SCHEMA_VERSION`, and `title` from the blueprint; `body`/`summary` come only from the prose result and the prose source never affects non-body fields
  - Observable: unit tests show deterministic safe ids, non-body fields mapped from the planned segment, `schema_version == SCHEMA_VERSION`, and identical non-body fields across `model`/`fallback`/`fake` prose sources
  - _Requirements: 4.3, 4.4, 4.5, 5.5_
  - _Boundary: Segment Wiring_
  - _Depends: 1.1_

- [x] 2.4 (P) Build the deterministic fallback body renderer
  - Add `docuharnessx/composition/fallback.py` with `render_fallback_body(blueprint)` and `render_fallback_summary(blueprint)`
  - Render a valid Markdown body honoring the blueprint structure (SCQA opener, Minto key-message lead, chunk subheads + bullets, REDUCE fast-path list, evidence anchor references) and a short summary
  - Observable: unit tests show a fallback body that, once wired, yields a `validate_segment`-valid `Segment` against a loaded `Vocabulary`, and equal blueprints produce equal fallback text
  - _Requirements: 6.3, 8.3_
  - _Boundary: Fallback Renderer_
  - _Depends: 1.1_

- [x] 2.5 Build the gated prose step (the only model surface)
  - Add `docuharnessx/composition/prose.py` with `generate_prose(blueprint, *, model, timeout_s=DEFAULT_PROSE_TIMEOUT_S) -> ProseResult | None`
  - Duck-type the provider over awaitable `complete(messages, tools, stream_callback=None)` returning `.content`; bridge sync→async via a private loop under `asyncio.wait_for(timeout_s)` exactly as `planning.relevance._complete_with_timeout`; never import or construct a provider class
  - Parse `.content` into `body`/`summary` deterministically; return `ProseResult(source="model")` on a clean response and `None` on a model-less, raised, timed-out, empty, or unparseable response; absorb and log all failures at WARNING; issue at most one `complete` call and add no loop
  - Observable: unit tests with a stub provider show a clean response yields `ProseResult(source="model")`, while a raising/timeout/empty/`None`-model case returns `None` without raising
  - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5_
  - _Boundary: Gated Prose Step_
  - _Depends: 1.1, 2.2_

- [x] 3. Integration: the real Write stage adapter (replace the stub in place)
- [x] 3.1 Finalize the composition namespace and replace the Write stage stub with the real adapter
  - Finalize `docuharnessx/composition/__init__.py` to also re-export the core entry points now that their modules exist (`build_blueprint`, `build_request`, `segment_id`, `wire_segment`, `render_fallback_body`, `render_fallback_summary`, `generate_prose`, `DEFAULT_PROSE_TIMEOUT_S`) with a self-consistent `__all__` (each re-export identity-equal to its submodule definition, mirroring `planning/__init__.py`)
  - Modify `docuharnessx/stages/write.py` in place: keep `STAGE_NAME = "write"`, `class WriteStage(NoOpStage)`, `make_write_stage`, the `make_noop_stage` re-export, and `__all__` stable; subclass `NoOpStage`, capture the run `State` in `on_task_start` (pass-through), do work in `on_step_end`, yield the event unchanged
  - Outside a harness (no captured `State`) forward the event and write nothing; with a bound `State`, read `SLOT_COVERAGE_PLAN`/`SLOT_REPO_ANALYSIS`/`SLOT_VOCABULARY`/`SLOT_SEGMENT_STORE`, pin `COVERAGE_PLAN_SCHEMA_VERSION`, and raise `WriterInputError` on an unsupported version or any missing plan/vocabulary/store slot (no partial output)
  - Observable: `docuharnessx.composition` exposes every core entry point via `__all__`; driven outside a harness the stage is a pass-through producing no segments; with a bound `State` and a missing plan/vocab/store slot or unsupported plan version it raises `WriterInputError` naming the cause; `register_stages`/`make_docgen` require no edits and the stage registry test suite passes unchanged
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 2.1, 2.2, 2.3, 2.4_
  - _Boundary: WriteStage, composition namespace_
  - _Depends: 1.2, 2.1, 2.2, 2.3, 2.4, 2.5_

- [x] 3.2 Wire the per-segment write orchestration into the stage
  - In `on_step_end`, iterate the plan's segments in order: `build_blueprint` → `build_request` → gated `generate_prose` (run off the run loop via `asyncio.to_thread` when a model is consulted, mirroring `PlanStage._maybe_apply_relevance`; obtain the model via `getattr(self, "_model_config", None).main` like `PlanStage._relevance_model`) → on `None` render the deterministic fallback (`source="fallback"`/`"fake"`) → `wire_segment`
  - Validate each produced `Segment` with `validate_segment` against the loaded `Vocabulary`; on valid call `store.put` and add it to the ordered written set; on invalid or `IdConflictError` record a `WriteFlag` (segment key + cause) and continue; tolerate absent `RepoAnalysis`/enrichment
  - Publish an ordered `WrittenSegments` (same `Segment` identities as stored, plan order) to `SLOT_WRITTEN_SEGMENTS`; an empty plan publishes an empty written set and completes without error
  - Observable: a credential-free run over a seeded plan stores one valid `Segment` per planned segment, populates `SLOT_WRITTEN_SEGMENTS` consistent with the store, flags an invalid/conflicting segment instead of aborting, and an empty plan yields an empty written set with no error
  - _Requirements: 2.5, 2.6, 5.1, 5.2, 5.3, 5.5, 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 7.1, 7.4, 7.5_
  - _Boundary: WriteStage_
  - _Depends: 2.1, 2.2, 2.3, 2.4, 2.5, 3.1_

- [x] 3.3 Add the bounded journal summary
  - Emit a `ProcessorTriggerEvent` to the run tracer (reusing the `NoOpStage` tracer resolution) carrying a summary-level detail only: stage name, `total_planned`, `written_count`, `flagged_count`, a capped list of top-priority written segment ids, and a `prose_source` marker (`model`/`fallback`/`fake`); never include full segment bodies; no-op when no tracer is bound
  - Observable: a journaled run records one Write-stage trigger whose detail carries the counts and the capped id list (and the `prose_source` marker for a fallback/fake run) and no full bodies
  - _Requirements: 8.1, 8.2, 8.3_
  - _Boundary: WriteStage_
  - _Depends: 3.2_

- [x] 4. Validation: credential-free end-to-end and reproducibility tests
- [x] 4.1 Add the credential-free stage integration test
  - Drive `WriteStage` through `make_docgen` bound to `FakeProvider.agentic(...)` over a seeded `CoveragePlan`/`RepoAnalysis`/`Vocabulary`/`InMemorySegmentStore`; assert one valid stored `Segment` per planned segment, a populated `SLOT_WRITTEN_SEGMENTS` consistent with the store, and a bounded journal record — with no network access
  - Add a gated-prose case: a stub provider returning a clean body yields `ProseResult.source == "model"`; the `FakeProvider`/no-model case yields the deterministic fallback while still producing one valid segment per planned segment with `prose_source` recorded
  - Observable: the integration test passes credential-free and asserts the stored-segment count, the written-set/store consistency, the prose-source marker, and the journal summary fields
  - _Requirements: 1.1, 1.3, 5.1, 5.4, 6.1, 7.1, 7.4, 8.1, 8.2, 8.3_
  - _Boundary: WriteStage_
  - _Depends: 3.3_

- [x] 4.2 Add failure-handling and reproducibility tests
  - Failure handling: a planned segment invalid under the loaded vocabulary is flagged and skipped while others are still written; an injected `IdConflictError` is flagged; an empty plan yields an empty written set with no error
  - Reproducibility: two writer runs over an equal plan with the deterministic fallback (no model) produce an equal `WrittenSegments` (equal ids, titles, bodies, summaries, and order)
  - Observable: the tests assert per-segment flags for the invalid/conflicting cases, an empty-plan empty result, and byte-equal `WrittenSegments` across two model-free runs
  - _Requirements: 6.2, 6.4, 6.5, 6.6, 9.3_
  - _Boundary: WriteStage_
  - _Depends: 4.1_
