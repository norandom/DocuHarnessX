# Requirements Document

## Introduction

The **classification-coverage-planner** is Wave 1, spec #2 of DocuHarnessX. It turns
the structured facts about a repository (the `RepoAnalysis` produced by
`repo-ingestion-analysis`) plus the project's loaded, configurable `Vocabulary`
(roles × intents × subject prefixes, owned by `ontology-engine`) into a deterministic,
prioritized **CoveragePlan**: an ordered list of planned content segments — each a
`(roles[], subjects[], intent, evidence, priority)` cell keyed to the ontology segment
schema — that tells the Wave 2 writer *what* to document for *whom* and *why*, and in
what order.

It is the decision-intelligence core of the pipeline. Today the `classify` and `plan`
pipeline stages are no-op stubs that participate in the run lifecycle but produce
nothing. This feature replaces those two stubs in place with real `Processor` stages:
the **Classify** stage maps `RepoAnalysis` findings onto ontology `Subject` values
(typed prefixes such as `component:` / `tech:` / `artifact:` / `topic:`) and onto the
relevant role×intent cells for the project; the **Plan** stage scores and orders those
cells into a frozen, serializable `CoveragePlan` and publishes it to the run context.

The planner is **deterministic and unit-testable** without a model, and it **adapts to
whatever `Vocabulary` is loaded** — it never hardcodes roles, intents, or subject
prefixes, so the same harness produces project-specific (not templated) plans across
the default profile and any custom vocabulary. Any LLM-assisted relevance judgement is
strictly optional, gated, and incapable of altering the deterministic core plan.

The `CoveragePlan` is the **frozen seam** the `cobesy-writer` (Wave 2) consumes; it is
designed for stability and additive evolution.

## Boundary Context

- **In scope**: Replacing the `classify` and `plan` stage stubs with real deterministic
  processors; mapping `RepoAnalysis` findings onto ontology `Subject` values and onto
  role×intent coverage cells over the loaded `Vocabulary`; scoring/prioritizing cells
  from evidence in the analysis; emitting a frozen, versioned, serializable
  `CoveragePlan` keyed to the segment schema; publishing it at a new
  `SLOT_COVERAGE_PLAN` run-context slot with a typed accessor; an optional, gated LLM
  relevance hook that never alters the deterministic plan; bounded journal summaries.
- **Out of scope**: Generating segment *content* (`cobesy-writer`); the quality review
  gate; MkDocs assembly; deploy; the raw repository scan and the `RepoAnalysis` model
  itself (owned by `repo-ingestion-analysis`); the `Vocabulary`/`Subject`/segment-schema
  definitions (owned by `ontology-engine`); changes to `make_docgen`, the stage
  registry ordering, `RunContext` structure, existing slot keys, or `StageName`.
- **Adjacent expectations**: The planner consumes the `RepoAnalysis` frozen contract
  from `SLOT_REPO_ANALYSIS` via `RunContext.repo_analysis()` (schema_version == 1) and
  the loaded `Vocabulary` from `RunContext.vocabulary()`; both are populated upstream.
  It reuses ontology `Subject`, `AxisTerm`, the segment frontmatter field set, and the
  `subject:` tag namespacing verbatim — it does not reimplement them. It extends
  `types.py` and `context.py` append-only (a shared-seam extension flagged for the
  owning `harness-bundle-skeleton` spec).

## Requirements

### Requirement 1: Stage replacement preserving the pipeline contract

**Objective:** As a pipeline maintainer, I want the Classify and Plan stages to become
real processors that drop into the existing pipeline unchanged, so that the
decision-intelligence work runs in canonical order without touching `make_docgen`, the
registry, or sibling stages.

#### Acceptance Criteria

1. The ClassifyStage and PlanStage shall remain real, module-level classes at their
   existing module paths `docuharnessx.stages.classify.ClassifyStage` and
   `docuharnessx.stages.plan.PlanStage`, keeping their existing class names,
   `STAGE_NAME` constants (`"classify"`, `"plan"`), and `make_classify_stage` /
   `make_plan_stage` factory names so the stage registry needs no edit.
2. The ClassifyStage and PlanStage shall each subclass the shared NoOpStage and attach
   to the existing `PIPELINE_HOOK` (`step_end`), doing their real work as a side effect
   and then yielding the lifecycle event unchanged so no generated content is mutated.
3. When a stage executes, the DocuHarnessX planner shall emit the stage's participation
   trigger to the run journal exactly as the no-op base does, in addition to its own
   bounded summary detail.
4. The DocuHarnessX planner shall not modify `make_docgen`, the `STAGES` registry
   ordering, the `StageName` literal, `STAGE_NAMES`, or any of the six other stage
   modules.
5. Where the six other pipeline stages are still no-op stubs, the DocuHarnessX planner
   shall leave them untouched and the full pipeline shall still compose and run.

### Requirement 2: Consuming the upstream RepoAnalysis and Vocabulary contracts

**Objective:** As the decision-intelligence core, I want to read the repository facts
and the project vocabulary from the run context exactly as published upstream, so that
planning is grounded in real analysis and the active project ontology.

#### Acceptance Criteria

1. When the Classify stage executes, the DocuHarnessX planner shall read the
   `RepoAnalysis` from `SLOT_REPO_ANALYSIS` via `RunContext.repo_analysis()` and the
   loaded `Vocabulary` from `RunContext.vocabulary()`.
2. The DocuHarnessX planner shall consume the `RepoAnalysis` frozen field set, nested
   record shapes, and serialized key names exactly as defined by
   `repo-ingestion-analysis`, without reimplementing, copying, or diverging from that
   model.
3. While reading the `RepoAnalysis`, the DocuHarnessX planner shall accept
   `schema_version == 1` and, if the `RepoAnalysis` declares a schema version it does
   not support, then it shall halt the run with an identifiable cause rather than
   producing a partial plan.
4. If `RunContext.repo_analysis()` returns `None` (the analysis slot is unset), then the
   DocuHarnessX planner shall halt the run with an identifiable cause naming the missing
   slot rather than emitting an empty or guessed plan.
5. If `RunContext.vocabulary()` returns `None` (the vocabulary slot is unset), then the
   DocuHarnessX planner shall halt the run with an identifiable cause naming the missing
   slot rather than falling back to a hardcoded role/intent set.

### Requirement 3: Classifying analysis findings onto ontology subjects

**Objective:** As a documentation planner, I want repository findings mapped onto typed
ontology `Subject` values, so that each planned segment carries the correct subject tags
and the writer and assembler can interconnect content.

#### Acceptance Criteria

1. When classifying a `RepoAnalysis`, the DocuHarnessX planner shall derive ontology
   `Subject` values from analysis findings using the loaded `Vocabulary`'s subject
   prefixes, producing well-formed `Subject` objects via the ontology `Subject` API.
2. The DocuHarnessX planner shall map components and structural modules to
   `component:`-prefixed subjects, primary/detected languages and frameworks to
   `tech:`-prefixed subjects, build/CI/license/schema/generated artifacts to
   `artifact:`-prefixed subjects, and cross-cutting concerns to `topic:`-prefixed
   subjects, where each corresponding prefix exists in the loaded `Vocabulary`.
3. Where a subject prefix that a mapping would use is absent from the loaded
   `Vocabulary`, the DocuHarnessX planner shall omit subjects for that prefix rather
   than emit a subject whose prefix is not a vocabulary member.
4. The DocuHarnessX planner shall produce subject local names deterministically from the
   analysis (normalized, lower-cased via the ontology `Subject` normalization) so that
   identical analyses and vocabularies yield identical subject sets.
5. The DocuHarnessX planner shall record, for each derived subject, the analysis
   evidence (source path(s) or finding) it was derived from so the plan is auditable.

### Requirement 4: Building the coverage matrix over the loaded vocabulary

**Objective:** As a documentation planner, I want a coverage matrix built over whatever
roles and intents the project's `Vocabulary` declares, so that planning is
project-configurable and never bound to a fixed role/intent template.

#### Acceptance Criteria

1. The DocuHarnessX planner shall build the coverage matrix as the set of candidate
   role×intent cells drawn exclusively from the loaded `Vocabulary`'s roles and intents,
   never from a hardcoded role or intent list.
2. When the loaded `Vocabulary` contains custom roles, intents, or subject prefixes, the
   DocuHarnessX planner shall use those custom terms for the matrix and subject mapping
   so the resulting plan differs from the default-profile plan for the same analysis.
3. The DocuHarnessX planner shall determine which role×intent cells are *relevant* for
   the project from evidence in the `RepoAnalysis` (for example: a detected CLI surface
   activates install/use/troubleshoot cells; detected CI/build files activate
   operate/deploy-oriented cells; security/forensics signals activate
   assess-quality/security cells; detected tests and public surface activate
   contribute/extend cells), only for role and intent ids that exist in the loaded
   `Vocabulary`.
4. The DocuHarnessX planner shall preserve the `Vocabulary`'s documented intent ordering
   (`vocabulary.intent_order()`) as a stable secondary ordering key so plan ordering is
   consistent with role-view ordering used elsewhere in the system.
5. The DocuHarnessX planner shall be deterministic: identical `RepoAnalysis` and
   `Vocabulary` inputs shall always produce the identical set of relevant cells.

### Requirement 5: Scoring and prioritizing coverage cells

**Objective:** As a reader-focused documentation system, I want the relevant cells
scored and ordered by evidence strength, so that the writer generates the
highest-value segments first instead of a generic dump.

#### Acceptance Criteria

1. The DocuHarnessX planner shall assign each relevant cell a deterministic priority
   score derived from the strength and amount of supporting analysis evidence and from a
   documented role/intent weighting, using only ids present in the loaded `Vocabulary`.
2. The DocuHarnessX planner shall order the planned segments by descending priority
   score, breaking ties deterministically using the `Vocabulary`'s role order then
   intent order then a stable segment key, so the ordering is total and reproducible.
3. When two runs are given identical inputs, the DocuHarnessX planner shall produce
   byte-identical ordering and scores.
4. The DocuHarnessX planner shall record, per planned segment, the evidence references
   that contributed to its score so the prioritization is auditable.
5. Where no relevant cell can be supported by any evidence in the analysis, the
   DocuHarnessX planner shall emit a well-formed empty `CoveragePlan` (no planned
   segments) rather than fabricating segments or raising an error.

### Requirement 6: The CoveragePlan frozen data model

**Objective:** As the downstream Wave 2 writer, I want a frozen, versioned, serializable
`CoveragePlan` keyed to the segment schema, so that I can consume a stable contract that
evolves additively.

#### Acceptance Criteria

1. The DocuHarnessX planner shall define `CoveragePlan` and its nested
   planned-segment record as immutable value objects whose collections are exposed as
   tuples (never lists) so instances are deeply immutable.
2. The DocuHarnessX planner shall make each planned-segment record carry, at minimum,
   the fields the ontology segment frontmatter schema requires for a writer to fill it:
   `roles` (role ids), `subjects` (typed `Subject` values), and `intent` (intent id),
   plus a deterministic plan-local segment key, the priority score, and the evidence
   references it was derived from.
3. The DocuHarnessX planner shall carry a single explicit
   `COVERAGE_PLAN_SCHEMA_VERSION` integer on every `CoveragePlan` instance as the one
   version authority for the contract.
4. The DocuHarnessX planner shall provide deterministic serialization such that
   serializing a `CoveragePlan` yields byte-identical output across runs for equal
   inputs.
5. The DocuHarnessX planner shall provide deserialization that reconstructs a
   `CoveragePlan` equal to the original (round-trip equality), and if deserialization
   encounters an unsupported `CoveragePlan` schema version, then it shall raise an
   identifiable version error.
6. The DocuHarnessX planner shall keep `CoveragePlan` field names and meanings stable;
   evolution shall be additive (new optional fields with defaults) and shall bump
   `COVERAGE_PLAN_SCHEMA_VERSION` only when the frozen field set changes.

### Requirement 7: Publishing the plan to the run context (the output seam)

**Objective:** As a pipeline stage, I want the finished `CoveragePlan` placed into the
run context under a stable slot, so that the Wave 2 writer reads it through a typed
accessor exactly as later stages expect.

#### Acceptance Criteria

1. The DocuHarnessX planner shall add a new `SLOT_COVERAGE_PLAN` slot-key constant to
   `docuharnessx/types.py` append-only, also added to that module's `__all__`, without
   modifying any existing constant, `StageName`, or `STAGE_NAMES` entry.
2. The DocuHarnessX planner shall add an append-only typed accessor pair to
   `docuharnessx/context.py` (a setter that records the plan at `SLOT_COVERAGE_PLAN` and
   a getter that returns the plan or `None` when the slot is unset) without changing any
   existing accessor's signature or behavior.
3. When the Plan stage finishes computing the plan, the DocuHarnessX planner shall write
   the `CoveragePlan` to `SLOT_COVERAGE_PLAN` via the run-context setter.
4. When the coverage-plan slot has not been set, the DocuHarnessX planner's getter shall
   return `None` rather than raising.
5. The DocuHarnessX planner shall flag the `types.py` and `context.py` additions as a
   shared-seam extension of `harness-bundle-skeleton`-owned modules and keep them purely
   additive.

### Requirement 8: Deterministic core with an optional gated LLM hook

**Objective:** As a maintainer who values reproducibility, I want the planning core to
be deterministic and model-free with any LLM use optional and unable to alter the core
plan, so that plans are testable and auditable.

#### Acceptance Criteria

1. The DocuHarnessX planner's classification, matrix construction, scoring, and ordering
   shall be a pure, deterministic core that requires no model and no network access.
2. Where an optional LLM relevance hook is enabled, the DocuHarnessX planner shall use it
   only to annotate or re-rank candidate cells within documented bounds, and the
   deterministic core cells, scores, and required segment fields shall remain unchanged.
3. While the LLM relevance hook is disabled (the default) or no model is bound, the
   DocuHarnessX planner shall produce the full deterministic `CoveragePlan` without
   attempting any model call.
4. If the optional LLM relevance hook fails or times out, then the DocuHarnessX planner
   shall log the failure, fall back to the deterministic plan, and continue the run
   rather than aborting.
5. The DocuHarnessX planner shall expose the LLM hook only through an explicit
   stage-level gate (no hidden environment-driven activation).

### Requirement 9: Observability of planning decisions

**Objective:** As an operator auditing a run, I want the journal to record a bounded
summary of what was classified and planned and why, so that planning decisions are
traceable without bloating the trace.

#### Acceptance Criteria

1. When the Classify stage finishes, the DocuHarnessX planner shall record a bounded
   journal summary (for example: counts of derived subjects per prefix and count of
   activated role×intent cells), not the full subject or cell listing.
2. When the Plan stage finishes, the DocuHarnessX planner shall record a bounded journal
   summary (for example: total planned segments, top-priority segment keys, and whether
   the LLM hook was applied).
3. The DocuHarnessX planner shall never write the full `CoveragePlan` to the journal
   trace.
4. Where the plan is empty because no evidence supported any cell, the DocuHarnessX
   planner shall record that outcome in the journal summary so the empty result is
   explainable.
