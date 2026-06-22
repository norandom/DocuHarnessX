# Requirements Document

## Introduction

The **cobesy-writer** makes the **Write** pipeline stage real. It replaces the no-op
`write` stub (`docuharnessx/stages/write.py`) with a stage that turns each
`PlannedSegment` in the frozen `CoveragePlan` (produced by the
`classification-coverage-planner` and read from `SLOT_COVERAGE_PLAN`) into a written,
COBESY-structured ontology `Segment` — filling the `title`/`summary`/`body` that the
planner deliberately left blank. It is Wave 2, spec #1: the first stage that produces
actual documentation prose and the first to make real model calls.

The writer consumes the planner's decision (`roles × intent × subjects + evidence` per
segment), grounds each segment in the upstream `RepoAnalysis` evidence (read from
`SLOT_REPO_ANALYSIS`), and produces human-facing content shaped so a time-poor reader
reaches first success on the shortest path. It applies the COBESY composition back-end:
a **deterministic per-segment composition blueprint** (SCQA opener tuned to the
segment's role(s) and intent, Minto lead-with-conclusion, working-memory chunking,
REDUCE-barrier fast path, andragogy for expert roles) is built **before** any prose,
then a single **gated model step** renders the Markdown `body` to honor that blueprint.

The architecture follows the project's **deterministic core / gated model split**: the
blueprint construction, prompt assembly, segment wiring, validation, and result
aggregation are deterministic and unit-testable **without a model**; the prose
generation is the only model-dependent step and must be **credential-free testable** via
a fake or recorded provider (asserting structure, wiring, validity, and gating — never
exact prose). The vocabulary is configurable: the writer reads roles/intents/subjects
from the loaded `Vocabulary` and never hardcodes them.

The writer owns a new output seam, `SLOT_WRITTEN_SEGMENTS`, that surfaces the written
`Segment` set (appended to `types.py` with a `RunContext` accessor) so the Wave 2
`quality-review-gate` can consume it.

## Boundary Context

- **In scope**: Replacing the `write` stub in place; consuming the `CoveragePlan`,
  `RepoAnalysis`, `Vocabulary`, and `SegmentStore`; building a deterministic
  composition blueprint per planned segment; the single gated model prose step per
  segment; assembling and validating each produced `Segment`; storing valid segments;
  surfacing the written set via the new `SLOT_WRITTEN_SEGMENTS` slot and accessor;
  recording a bounded journal summary.
- **Out of scope**: Judging or quality-gating the prose (owned by `quality-review-gate`,
  Wave 2 spec #2); MkDocs assembly, nav, cross-link rendering, or deploy; producing the
  `CoveragePlan` (planner) or the `RepoAnalysis` (analyzer); changing the frozen
  `CoveragePlan`, `RepoAnalysis`, `Segment`, `Vocabulary`, or `SegmentStore` contracts;
  model resolution (owned by `model_resolver`) and harness composition (owned by
  `make_docgen`).
- **Adjacent expectations**: The frozen `CoveragePlan` (v1) and `RepoAnalysis` (v1) are
  consumed verbatim — the writer pins their schema versions and halts on a mismatch
  rather than guessing. The ontology `Segment` schema, `validate_segment`, `emit_tags`,
  and the `SegmentStore` port are reused as-is. The new `SLOT_WRITTEN_SEGMENTS` is the
  single seam the review gate reads; its content shape is a stabilized contract for that
  downstream spec.

## Requirements

### Requirement 1: Stable in-place Write stage replacement

**Objective:** As a DocuHarnessX maintainer, I want the writer to drop into the exact
slot the `write` no-op stub occupied, so that the stage registry and `make_docgen` need
no edits and the single-stage replaceability contract holds.

#### Acceptance Criteria
1. The Write Stage shall preserve the existing `STAGE_NAME` value (`"write"`), the
   `WriteStage` class name, the `make_write_stage` factory name, and the
   `docuharnessx/stages/write.py` module path so the stage registry and `make_docgen`
   require no changes.
2. The Write Stage shall attach to the same pipeline hook (`PIPELINE_HOOK` /
   `step_end`) and subclass the shared no-op stage base so the registry binds it
   identically to the other stages.
3. When the Write Stage is driven outside a harness (no run state bound), the Write
   Stage shall forward the lifecycle event unchanged and produce no segments, matching
   the no-op base behavior.
4. The Write Stage shall yield the incoming lifecycle event unchanged, performing all
   work as a side effect of the content-free `step_end` event and never mutating
   generated conversation content.

### Requirement 2: Consume the planner and analyzer seams verbatim

**Objective:** As a downstream consumer of the pipeline, I want the writer to read the
frozen `CoveragePlan`, `RepoAnalysis`, `Vocabulary`, and `SegmentStore` exactly as
provided, so that the writer never reinvents upstream decisions and fails loudly on a
contract mismatch.

#### Acceptance Criteria
1. When the Write Stage runs with a bound run state, the Write Stage shall read the
   `CoveragePlan` from `SLOT_COVERAGE_PLAN`, the `RepoAnalysis` from
   `SLOT_REPO_ANALYSIS`, the `Vocabulary` from `SLOT_VOCABULARY`, and the segment-store
   handle from `SLOT_SEGMENT_STORE` through the typed `RunContext` accessors.
2. The Write Stage shall pin the supported `CoveragePlan` schema version and, if the
   consumed `CoveragePlan` declares an unsupported version, halt the run with an error
   naming the offending version and produce no segments.
3. If the `CoveragePlan` slot is unset when the Write Stage has a bound run state, then
   the Write Stage shall halt the run with an error naming the offending slot and
   produce no segments.
4. If the `Vocabulary` slot or the segment-store slot is unset when the Write Stage has
   a bound run state, then the Write Stage shall halt the run with an error naming the
   offending slot and produce no segments.
5. Where the `RepoAnalysis` slot is unset or its `enrichment` region is absent, the
   Write Stage shall still produce segments using only the planner-supplied evidence,
   without inventing repository facts.
6. The Write Stage shall treat the `CoveragePlan` segments, their `roles`, `intent`,
   `subjects`, `priority`, `evidence`, and `relevance_note` as read-only inputs and
   shall not mutate the consumed plan, analysis, or vocabulary objects.

### Requirement 3: Deterministic per-segment composition blueprint

**Objective:** As a documentation reader, I want each segment's content structured by
COBESY before any prose is written, so that the content leads with the conclusion, fits
working memory, and routes me to first success for my role and intent.

#### Acceptance Criteria
1. The Composition Planner shall build, for each `PlannedSegment`, a deterministic
   composition blueprint without consulting any model.
2. The Composition Planner shall derive the blueprint's SCQA opener from the segment's
   role(s) and intent as read from the loaded `Vocabulary`, never from a hardcoded role
   or intent list.
3. The Composition Planner shall encode a Minto lead-with-conclusion ordering, a
   working-memory chunking plan, and a REDUCE-barrier fast-path cue in the blueprint.
4. Where a segment serves an expert role (as defined by the loaded `Vocabulary`), the
   Composition Planner shall mark the blueprint to apply andragogy (respect prior
   knowledge, problem-centered framing) for that segment.
5. The Composition Planner shall derive the blueprint's evidence anchors from the
   segment's `evidence` references (and any matching `RepoAnalysis` findings) so the
   rendered body can be grounded in real repository facts.
6. Given equal inputs (same `PlannedSegment`, `RepoAnalysis`, and `Vocabulary`), the
   Composition Planner shall produce an equal blueprint on every run.

### Requirement 4: Deterministic prompt assembly and segment wiring

**Objective:** As a test author, I want the prompt assembly and segment wiring to be
pure and model-free, so that I can assert the writer's structure, grounding, and field
mapping without any credentials.

#### Acceptance Criteria
1. The Prompt Assembler shall build the model request for a segment deterministically
   from that segment's blueprint and evidence anchors, without consulting any model.
2. The Prompt Assembler shall include in the request only the planner-supplied and
   analysis-supplied facts (segment axis values, evidence refs, and matching analysis
   findings) and shall not include unrelated repository file contents.
3. The Segment Wiring shall populate the produced `Segment`'s `id`, `roles`,
   `subjects`, `intent`, and `related` from the `PlannedSegment` and shall set
   `schema_version` to the current ontology schema version.
4. The Segment Wiring shall derive a deterministic, unique segment `id` from the
   `PlannedSegment` so that two writer runs over an equal plan produce equal ids.
5. Given equal inputs, the Prompt Assembler and Segment Wiring shall produce equal
   requests and equal non-body `Segment` fields on every run.

### Requirement 5: Gated model prose step

**Objective:** As an operator, I want the prose generation to be the single
model-dependent step, gated and bounded, so that the writer runs credential-free in
tests and within the inherited cost and step budgets in production.

#### Acceptance Criteria
1. When a segment's request is ready and a model provider is bound, the Write Stage
   shall call the bound model once per segment to generate that segment's Markdown
   `body` and `summary` text.
2. The Write Stage shall obtain the model provider from the harness-bound model
   configuration and shall not construct a provider itself or read provider credentials
   directly.
3. While generating prose, the Write Stage shall apply the inherited Control cost and
   step budgets and shall not introduce a separate uncapped generation loop.
4. When the model is exercised through a fake or recorded provider with no network
   access, the Write Stage shall still produce one valid `Segment` per planned segment
   so the stage is testable end-to-end without credentials.
5. The model step shall produce only the `body` and `summary` text; it shall not set or
   override the segment's `roles`, `subjects`, `intent`, `id`, or `related`, which are
   fixed by the deterministic wiring.

### Requirement 6: Validate, store, and handle failures deterministically

**Objective:** As a pipeline operator, I want each produced segment validated against
the loaded `Vocabulary` and stored, with invalid or failed segments handled
deterministically, so that only well-formed segments reach the review gate and a single
bad segment never silently corrupts the run.

#### Acceptance Criteria
1. The Write Stage shall validate each produced `Segment` against the loaded
   `Vocabulary` using the ontology validation, and shall store only valid segments in
   the segment store.
2. If a produced `Segment` fails validation, then the Write Stage shall skip storing
   that segment, record a deterministic flag for it (segment key and the validation
   cause), and continue with the remaining planned segments.
3. If the model call for a segment fails, times out, or returns empty content, then the
   Write Stage shall apply a deterministic fallback body derived from the blueprint and
   evidence, validate it, and either store the fallback segment or flag it like any
   other invalid segment.
4. If storing a segment raises an id conflict, then the Write Stage shall record a
   deterministic flag for that segment and continue, rather than aborting the run.
5. Given an empty `CoveragePlan` (no planned segments), the Write Stage shall produce no
   segments, surface an empty written set, and complete without error.
6. The Write Stage shall process planned segments in the plan's existing order so the
   set of stored segments and recorded flags is deterministic across equal runs.

### Requirement 7: Surface the written segment set (the review-gate seam)

**Objective:** As the Wave 2 `quality-review-gate`, I want the writer to surface the
written `Segment` set through a stable slot and accessor, so that I can consume exactly
the segments the writer produced for quality judging.

#### Acceptance Criteria
1. The Write Stage shall publish the set of successfully written, valid `Segment`
   objects to a new `SLOT_WRITTEN_SEGMENTS` slot via a typed `RunContext` accessor.
2. The slot-key constant and the `RunContext` accessor for the written segment set
   shall be added to the skeleton's shared types module and run-context module as an
   append-only addition, modifying no existing slot key, stage name, or accessor.
3. When the written segment set is read before the Write Stage has run, the
   `RunContext` accessor shall return an explicit absent value (`None`) rather than
   raising, matching the other slot accessors' absent-slot semantics.
4. The written segment set surfaced through `SLOT_WRITTEN_SEGMENTS` shall be consistent
   with the segments stored in the segment store (same segment identities), so a
   consumer can use either handle for the same content.
5. The written segment set shall be exposed in the plan's deterministic order so the
   downstream consumer reads a stable sequence across equal runs.

### Requirement 8: Bounded observability

**Objective:** As a maintainer auditing a run, I want the Write Stage to record its
participation and a bounded summary in the journal, so that I can see what was written
without bloating the trace on a large repository.

#### Acceptance Criteria
1. When the Write Stage completes on a bound run state, the Write Stage shall record its
   participation in the run journal with a summary-level detail only.
2. The journal summary shall include the total planned-segment count, the count of
   successfully written segments, the count of flagged or skipped segments, and a
   capped list of top-priority written segment ids, and shall not include full segment
   bodies.
3. When the model step is unavailable or runs against a fake provider, the Write Stage
   shall record that prose was produced via fallback or fake generation in the bounded
   summary so a credential-free run is auditable.

### Requirement 9: Configurable vocabulary and reproducibility

**Objective:** As a project using a custom ontology, I want the writer to adapt to my
loaded `Vocabulary` and behave reproducibly, so that the same harness writes correct
content for any project profile.

#### Acceptance Criteria
1. The Write Stage shall read all roles, intents, and subject prefixes from the loaded
   `Vocabulary` and shall contain no hardcoded role, intent, or subject literals in its
   blueprint, prompt, validation, or wiring logic.
2. Where a segment's role or intent label or description differs from the default
   profile, the Composition Planner shall use the loaded `Vocabulary`'s labels and
   descriptions when shaping the blueprint.
3. Given equal inputs and a deterministic (or recorded) prose source, the Write Stage
   shall produce an equal written segment set on repeated runs, so a model-free or
   recorded run is fully reproducible.
