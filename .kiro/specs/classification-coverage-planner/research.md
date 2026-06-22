# Research & Discovery Log — classification-coverage-planner

## Discovery Scope

Discovery type: **Extension / Complex Integration** (integration-focused, against a
real merged Wave 0 foundation + a pinned upstream Wave 1 sibling contract). No external
web research was required: every dependency is in-repo and already implemented. Focus
was on reading the real APIs this spec must consume verbatim and on designing a frozen
output seam (`CoveragePlan`) for a Wave 2 consumer.

## Verified Foundation APIs (read from `main`)

### Harness skeleton (owned by `harness-bundle-skeleton`)

- `docuharnessx/context.py` — `RunContext(state)` wraps a HarnessX `State`. Existing
  accessors: `target_repo()`, `output_dir()`, `segment_store()`, `vocabulary()`; all
  route through `_get_content(key)` which returns `slot.content` or `None`. Setters call
  `state.set_slot(KEY, slot_type_tag, content)`. **New accessors mirror this exactly.**
- `docuharnessx/types.py` — owns `StageName` literal, `STAGE_NAMES`, and the slot
  constants. `__all__` is explicit. Append-only extension is the established pattern
  (`repo-ingestion-analysis` does the same for `SLOT_REPO_ANALYSIS` / `SLOT_FILE_INVENTORY`).
- `docuharnessx/stages/base.py` — `PIPELINE_HOOK = "step_end"`; `NoOpStage(MultiHookProcessor)`
  with `stage_name`, `_bind_runtime(rt)` capturing the runtime, `on_step_end` emitting a
  `ProcessorTriggerEvent(action="stage_participated", detail={"stage": name})` to the
  tracer then yielding the event unchanged. `_resolve_tracer()` returns `rt.tracer` or
  `None`. **A real stage does its work as a side effect (read slots, compute, write
  slots) and still yields the event unchanged — identical lifecycle to `NoOpStage`.**
- `docuharnessx/stages/__init__.py` — `STAGES` is the ordered `(StageName, factory)`
  list; `_STAGE_CLASSES` maps name→class; `register_stages` appends each on
  `PIPELINE_HOOK` with increasing `order`. The registry **imports `ClassifyStage`,
  `make_classify_stage`, `PlanStage`, `make_plan_stage` by name** — so those names and
  module paths MUST be preserved (verified the import lines).
- `docuharnessx/stages/classify.py` and `plan.py` — current no-op stubs. Each defines
  `STAGE_NAME`, a `NoOpStage` subclass (`ClassifyStage`/`PlanStage`), and a factory.
  **These two files are replaced in place; nothing else in `stages/` is edited.**

### Ontology engine (owned by `ontology-engine`)

- `docuharnessx/_ontology.py` is the skeleton's single re-export shim; the real package
  is `docuharnessx/ontology/` (re-exported from `docuharnessx.ontology`).
- `Vocabulary` (frozen): `roles: tuple[AxisTerm, ...]`, `intents: tuple[AxisTerm, ...]`,
  `subject_prefixes: tuple[str, ...]` (written colon form, e.g. `"component:"`).
  Methods: `has_role(id)`, `has_intent(id)`, `intent_order() -> tuple[str, ...]`.
- `AxisTerm` (frozen): `id`, `label`, `description`. **Membership/identity is keyed on
  `id`.** Default profile: 10 roles, 13 intents, prefixes
  `component:`/`tech:`/`artifact:`/`topic:`. These are presets, NOT enums.
- `Subject` (frozen): `prefix`, `local` (both normalized/case-folded). `Subject.parse(raw,
  allowed_prefixes: frozenset[str])` raises `MalformedSubjectError` on bad input;
  `Subject.canonical() -> "prefix:local"`. `normalize_prefix(p)` is the single
  normalizer (strips trailing `:`, casefolds).
- Segment frontmatter schema (frozen, `SCHEMA_VERSION = 1`): `Segment{id, title,
  roles: list[str], subjects: list[Subject], intent: str, summary, related, body,
  schema_version}`. `REQUIRED_FIELDS = (id, title, roles, subjects, intent)`. **The
  planned segment must key to this: a writer fills a CoveragePlan cell into a `Segment`
  by supplying title/summary/body, so the plan must carry roles/subjects/intent.**
- `emit_tags(segment, vocab)` already exists; the planner does NOT emit tags (that is the
  writer/assembler concern) — it only produces the axis values a segment will carry.

### Upstream sibling contract (owned by `repo-ingestion-analysis`, consumed VERBATIM)

- `RepoAnalysis` frozen model, `REPO_ANALYSIS_SCHEMA_VERSION == 1` on
  `RepoAnalysis.schema_version`. Read from `SLOT_REPO_ANALYSIS = "docuharnessx.repo_analysis"`
  via `RunContext.repo_analysis()` (returns `None` when unset).
- Fields consumed by the planner: `languages`, `primary_languages`, `structure`,
  `entrypoints`, `build_files`, `ci_workflows`, `tests`, `dependencies`, `components`,
  `public_surface`, `docs`, `artifacts`, `scan_stats`, optional `enrichment`. All
  collections are pre-sorted frozen tuples of `@dataclass(frozen=True)` records.
- The planner **pins `schema_version == 1`** and treats any other version as a fatal,
  identifiable error (documented downstream contract from the ingestion spec).

## Key Design Decisions (with rationale)

1. **Pure core + two thin stage adapters** (mirrors `repo-ingestion-analysis`). All
   logic lives in a model-free `planning/` package returning frozen value objects; only
   `stages/classify.py` and `stages/plan.py` know HarnessX. Keeps the core unit-testable
   without a harness and shields the frozen `CoveragePlan` seam from harness changes.
2. **Two stages, one inter-stage handoff.** Classify produces an intermediate
   `Classification` (subjects + activated cells + evidence); Plan scores/orders it into
   the `CoveragePlan`. The handoff travels through a new internal slot
   `SLOT_CLASSIFICATION` so each stage stays independently swappable (same pattern as
   ingestion's `SLOT_FILE_INVENTORY`). `SLOT_COVERAGE_PLAN` is the public output seam.
3. **Vocabulary-driven, never hardcoded.** Roles, intents, and subject prefixes are read
   from the loaded `Vocabulary`. Cell activation maps *analysis signals* to *intent ids*
   and *role ids*, but every produced id is filtered through `vocab.has_role` /
   `vocab.has_intent` and every subject prefix through the vocabulary's prefixes. A
   custom vocabulary therefore yields a different plan — proven by tests over default +
   custom vocabularies.
4. **Signal→cell rule table is data, not a fixed template.** A documented table maps
   analysis predicates (has CLI entrypoint, has CI, has tests, security/forensics
   signal, etc.) to *(role hint, intent hint)* pairs. The hints are vocabulary ids; rows
   whose ids are absent from the loaded vocabulary are skipped. This is decision
   intelligence (evidence-gated activation), not "always emit these N segments".
5. **Deterministic scoring + total ordering.** Score = evidence weight × role/intent
   weight, all integer/decimal-stable. Ties break by vocabulary role order, then
   `intent_order()`, then the stable plan-local segment key. Guarantees byte-identical
   ordering across runs.
6. **`CoveragePlan` designed for stability.** Frozen, tuple-only, versioned
   (`COVERAGE_PLAN_SCHEMA_VERSION = 1`), with deterministic `to_dict`/`from_dict`/
   `to_json` and a `CoveragePlanVersionError`. Evolution is additive. This is the Wave 2
   writer's input contract.
7. **Optional LLM hook is annotate/re-rank only.** Off by default; when enabled it may
   only re-rank or annotate candidate cells *within bounds* and can never change the set
   of deterministic cells or the required segment fields. Failure → fall back to the
   deterministic plan and continue. No env-driven activation.

## Synthesis Outcomes

- **Build-vs-adopt**: adopt `Vocabulary`/`Subject`/`AxisTerm`/segment schema and
  `RepoAnalysis` verbatim; build only the planning core + `CoveragePlan` model + the two
  stage bodies + the append-only slot/accessor extensions.
- **Generalization**: the signal→cell rule table generalizes the brief's examples ("CLI
  → install/use/troubleshoot; security tool → assess-quality/security") into one
  evidence-gated, vocabulary-filtered mechanism rather than per-archetype branches.
- **Simplification**: no separate "classification model file" beyond the intermediate
  `Classification` value object; subject derivation and cell activation are pure
  functions over `RepoAnalysis` + `Vocabulary`.

## Risks & Mitigations

- **Risk**: hidden coupling to default-profile ids inside the rule table. **Mitigation**:
  every rule-table id is filtered through the loaded vocabulary; a dedicated test runs a
  custom vocabulary (renamed roles/intents, extra prefix) and asserts the plan differs
  and contains only custom ids.
- **Risk**: `RepoAnalysis` contract drift breaking the planner. **Mitigation**: pin
  `schema_version == 1`; consume the model via its published types; document the
  revalidation trigger. Any upstream field/shape/version change re-validates here.
- **Risk**: non-determinism from dict iteration / set ordering. **Mitigation**: tuples
  only; `sort_keys=True` JSON; explicit total ordering keys; round-trip + byte-stability
  tests.
- **Risk**: `CoveragePlan` instability for Wave 2. **Mitigation**: freeze + version now;
  additive-only evolution; documented revalidation trigger for the writer.

## Revalidation Triggers Recorded

- Any change to `CoveragePlan` / `PlannedSegment` field set, nested shapes, serialized
  key names, or `COVERAGE_PLAN_SCHEMA_VERSION` → `cobesy-writer` must re-validate.
- Any change to `SLOT_COVERAGE_PLAN` (key string / slot type) or to the
  `set_coverage_plan()` / `coverage_plan()` accessor signatures.
- Upstream: any change to the consumed `RepoAnalysis` contract, `SLOT_REPO_ANALYSIS`, or
  `RunContext.repo_analysis()` → re-validate the planner's consumption.
- Ontology: any change to `Vocabulary`/`Subject`/`AxisTerm`/segment required-field set →
  re-validate subject derivation and matrix construction.
