# Research & Discovery Log — cobesy-writer

Discovery type: **Extension** (integration-focused, light discovery) — the writer replaces
an existing no-op stage stub in a built, merged foundation (Waves 0+1 on `main`). The
design is grounded in the real merged APIs, not assumptions.

## Discovery Scope

Read the merged foundation that the writer consumes or mirrors:
- `docuharnessx/planning/model.py` — frozen `CoveragePlan` (v1), `PlannedSegment`,
  `EvidenceRef`, `COVERAGE_PLAN_SCHEMA_VERSION`. `PlannedSegment` carries
  `segment_key/roles/intent/subjects/priority/evidence/relevance_note` and deliberately
  NO title/summary/body — the writer authors those.
- `docuharnessx/analysis/model.py` — frozen `RepoAnalysis` (v1) and nested findings;
  `enrichment` is optional (`None` when disabled) so a deterministic core is constructible
  without a model.
- `docuharnessx/ontology/` — `Segment` (required `id/title/roles/subjects/intent`; optional
  `summary/related/body/schema_version`; `SCHEMA_VERSION == 1`), `Subject` (typed
  `prefix:local`, `canonical()`), `Vocabulary` (`has_role`/`has_intent`/`intent_order`;
  roles/intents are `AxisTerm` with id/label/description), `validate_segment` (aggregates
  errors; never raises for content), `emit_tags`, `SegmentStore` port + `InMemory`/
  `Filesystem` adapters (`put` validates + raises `IdConflictError` on duplicate; ids must
  be filesystem-safe for the filesystem adapter).
- `docuharnessx/context.py` + `docuharnessx/types.py` — `RunContext` typed slot accessors;
  slot keys extended append-only by the analyzer and planner (the pattern this spec follows
  for `SLOT_WRITTEN_SEGMENTS`).
- `docuharnessx/stages/base.py`, `stages/plan.py`, `stages/write.py`, `stages/__init__.py`,
  `bundle.py`, `model_resolver.py` — the stage adapter pattern, registry (`STAGES`), and
  model binding.
- `docuharnessx/planning/relevance.py` — the canonical gated-model surface: duck-typed
  provider, `asyncio.run` under `wait_for`, all failures absorbed → keep deterministic
  result; the Plan stage bridges it off the run loop via `asyncio.to_thread`.
- `tests/_fakes.py` — `FakeProvider` (no-network, ends turn immediately) for
  credential-free runs.
- `cobesy` skill `references/composition.md` — the composition back-end: SCQA opener,
  Minto lead-with-conclusion, working-memory chunking, descriptive subheads + topic
  sentences, REDUCE fast path, andragogy for expert readers, evidence-grounding; the
  `composition_blueprint` (skeleton grid) is produced BEFORE prose.

## Key Findings → Design Implications

1. **Mirror `PlanStage` exactly.** The merged `PlanStage` is the proven template: capture
   `State` in `on_task_start`, do work in `on_step_end`, raise an input error only with a
   bound `State` + missing slot, journal a bounded summary, yield the event unchanged.
   → The writer is a thin adapter over a pure `composition` core, same as `PlanStage` over
   `planning`.

2. **Invert the relevance gate for prose.** `relevance.apply_relevance` is OFF by default
   (annotate/re-rank is optional). The writer's prose call is ON by default when a model is
   bound, but the deterministic **fallback** body guarantees a valid segment when no model /
   `FakeProvider` / failure — so the stage is credential-free testable and the deterministic
   core is independently testable. The async bridging (`asyncio.to_thread` over a
   sync `generate_prose` that uses `asyncio.run`+`wait_for`) is copied from the planner to
   avoid nesting event loops in the run loop.

3. **Configurable vocabulary, no hardcoded axes.** Roles/intents are `AxisTerm`s in the
   loaded `Vocabulary` with id/label/description. The blueprint derives SCQA framing,
   labels, and the andragogy (expert) decision from the loaded term, not from default-profile
   literals — preserving reusability (steering: configurable ontology).

4. **Filesystem-safe ids.** `FilesystemSegmentStore._path_for` rejects ids with `/`, `\`,
   `.`/`..`. `segment_id(planned)` must sanitize the plan-local `segment_key` and append a
   short stable hash for uniqueness, deterministically.

5. **The new seam is the contract the review gate reads.** `quality-review-gate`'s brief
   states it consumes `SLOT_WRITTEN_SEGMENTS` + the segment store. So the written set must
   be (a) an explicit slot + accessor (append-only), (b) consistent with the store
   identities, (c) ordered, and (d) carry per-segment flags so the gate sees which planned
   segments did not produce a segment.

## Synthesis Outcomes

- **Build a dedicated `composition` package** (not stage-internal helpers): generalizes the
  `planning` separation so blueprint/prompt/wiring/fallback are unit-testable with no model;
  only `composition/prose.py` touches a provider.
- **Adopt, don't reinvent**: reuse `validate_segment`, `SegmentStore.put`, `emit_tags`,
  `Subject`, `Vocabulary`, and the duck-typed provider contract from `relevance`. No new
  serialization, no new validation, no new store.
- **Simplification**: no write→review remediation loop (that is the review gate's call);
  `related` defaults empty to avoid unresolved cross-links during write; cross-linking is a
  Wave 3 assembler concern.
- **Stabilize `WrittenSegments`** as the single output value object so the downstream spec
  has one shape to depend on; evolve it additively if needed (revalidation trigger recorded
  in design.md).

## Risks

- HarnessX API drift (provider `complete` shape, `Message`, event types): mitigated by
  lazy/duck-typed coupling identical to `planning.relevance`/`analysis.enrich`.
- Coupling the blueprint to default-profile role ids: mitigated by deriving framing and
  expert-ness from the loaded `Vocabulary` term.
- Event-loop nesting: mitigated by `asyncio.to_thread` bridging copied from `PlanStage`.
