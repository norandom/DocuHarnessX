# Requirements Document

## Introduction

The **quality-review-gate** makes the **Review** pipeline stage real. It replaces the
no-op `review` stub (`docuharnessx/stages/review.py`) with a stage that evaluates each
written ontology `Segment` against the **COBESY validation gate** and gates which
segments proceed to assembly. It is Wave 2, spec #2: the quality firewall before
publication.

The review gate consumes the written `Segment` set produced by the `cobesy-writer`
(read from `SLOT_WRITTEN_SEGMENTS`, with the same `Segment` identities available in the
`SegmentStore`), plus the `CoveragePlan` and the loaded `Vocabulary` for role/intent
context and the `RepoAnalysis` for evidence grounding. For each segment it applies the
COBESY anti-cringe gate — MECE structure, working-memory fit, role-fit (does the content
match the segment's roles and intent), clarity, falsifiability/evidence-grounding, and
absence of AI-slop — via a single **LLM-judge** call per segment, reusing HarnessX's
evaluation dimension where it fits rather than reinventing a judge.

The architecture follows the project's **deterministic core / gated model split**: the
gate criteria definition, the per-criterion-to-verdict aggregation, the accept/reject
decision, and the report assembly are deterministic and unit-testable **without a model**;
the judgement is the only model-dependent step and must be **credential-free testable**
via a fake or recorded judge (asserting the gating logic and the report shape — never the
exact judge prose). When no model is reachable (a fake provider, a model-less run, or a
failed judge), the gate degrades deterministically to a documented default verdict so a
credential-free run still produces a well-formed report and a defined accepted set.

The gate runs as a **single pass**: it judges each written segment once, records an
actionable verdict, and gates accept/reject. It does not re-invoke the writer to rewrite
failed segments; instead it surfaces per-segment findings and criterion scores so a later
iteration can act on them. The gate owns a new frozen output seam — the **`ReviewReport`**
(per-segment verdict, findings, criterion scores, and an aggregate) plus the **accepted**
segment set — surfaced through a new `SLOT_REVIEW_REPORT` slot (appended to `types.py`
with a `RunContext` accessor) so the Wave 3 `mkdocs-site-assembler` can consume exactly
the segments that passed. The `ReviewReport` shape is the stabilized contract for that
downstream spec.

## Boundary Context

- **In scope**: Replacing the `review` stub in place; consuming the written `Segment` set
  from `SLOT_WRITTEN_SEGMENTS` (and the `SegmentStore` handle), plus the `CoveragePlan`,
  `Vocabulary`, and `RepoAnalysis` for role/intent/evidence context; defining the COBESY
  gate criteria deterministically against the loaded `Vocabulary`; the single gated
  LLM-judge step per segment; the deterministic per-criterion-to-verdict aggregation and
  accept/reject decision; assembling the frozen `ReviewReport` and the accepted segment
  set; surfacing both via the new `SLOT_REVIEW_REPORT` slot and accessor; recording a
  bounded journal summary.
- **Out of scope**: Generating or rewriting prose content (owned by `cobesy-writer`); a
  write→review remediation loop that re-invokes the writer (deliberately not adopted — see
  the design's "single-pass gate" decision); MkDocs assembly, nav, cross-link rendering,
  or deploy (Wave 3); producing the `CoveragePlan`, `RepoAnalysis`, or the written
  segments; changing the frozen `CoveragePlan`, `RepoAnalysis`, `Segment`, `Vocabulary`,
  `SegmentStore`, or `WrittenSegments` contracts; model resolution (owned by
  `model_resolver`) and harness composition (owned by `make_docgen`).
- **Adjacent expectations**: The `WrittenSegments` value object at `SLOT_WRITTEN_SEGMENTS`
  (owned by `cobesy-writer`) is consumed verbatim — its `segments`, `flags`, and
  `total_planned` shape is a stabilized contract; any change to it is a revalidation
  trigger here. The frozen `CoveragePlan` (v1) and `RepoAnalysis` (v1) are consumed
  verbatim with pinned schema versions. The ontology `Segment` schema, `validate_segment`,
  `emit_tags`, and the `SegmentStore` port are reused as-is. The new `SLOT_REVIEW_REPORT`
  is the single seam the assembler reads; its content shape is a stabilized contract for
  that downstream spec.

## Requirements

### Requirement 1: Stable in-place Review stage replacement

**Objective:** As a DocuHarnessX maintainer, I want the review gate to drop into the exact
slot the `review` no-op stub occupied, so that the stage registry and `make_docgen` need
no edits and the single-stage replaceability contract holds.

#### Acceptance Criteria
1. The Review Stage shall preserve the existing `STAGE_NAME` value (`"review"`), the
   `ReviewStage` class name, the `make_review_stage` factory name, and the
   `docuharnessx/stages/review.py` module path so the stage registry and `make_docgen`
   require no changes.
2. The Review Stage shall attach to the same pipeline hook (`PIPELINE_HOOK` / `step_end`)
   and subclass the shared no-op stage base so the registry binds it identically to the
   other stages.
3. When the Review Stage is driven outside a harness (no run state bound), the Review
   Stage shall forward the lifecycle event unchanged and produce no report, matching the
   no-op base behavior.
4. The Review Stage shall yield the incoming lifecycle event unchanged, performing all
   work as a side effect of the content-free `step_end` event and never mutating generated
   conversation content.

### Requirement 2: Consume the writer and upstream seams verbatim

**Objective:** As a downstream consumer of the pipeline, I want the gate to read the
written `Segment` set and upstream context exactly as provided, so that the gate never
reinvents upstream decisions and fails loudly on a contract mismatch.

#### Acceptance Criteria
1. When the Review Stage runs with a bound run state, the Review Stage shall read the
   written segment set from `SLOT_WRITTEN_SEGMENTS`, the `CoveragePlan` from
   `SLOT_COVERAGE_PLAN`, the `Vocabulary` from `SLOT_VOCABULARY`, and the segment-store
   handle from `SLOT_SEGMENT_STORE` through the typed `RunContext` accessors.
2. The Review Stage shall pin the supported `CoveragePlan` schema version and, if the
   consumed `CoveragePlan` declares an unsupported version, halt the run with an error
   naming the offending version and produce no report.
3. If the written-segment slot is unset when the Review Stage has a bound run state, then
   the Review Stage shall halt the run with an error naming the offending slot and produce
   no report.
4. If the `Vocabulary` slot is unset when the Review Stage has a bound run state, then the
   Review Stage shall halt the run with an error naming the offending slot and produce no
   report.
5. Where the `RepoAnalysis` slot is unset, the Review Stage shall still judge segments
   using the written content and the planner-supplied evidence, without inventing
   repository facts.
6. The Review Stage shall treat the written segment set, the `CoveragePlan`, the
   `RepoAnalysis`, and the `Vocabulary` as read-only inputs and shall not mutate the
   consumed objects or the segments' content.

### Requirement 3: Deterministic COBESY gate criteria

**Objective:** As a documentation reader, I want each segment judged against the explicit
COBESY validation gate, so that only clear, MECE, role-fit, falsifiable, non-AI-slop
content reaches the site.

#### Acceptance Criteria
1. The Review Gate shall define a fixed, named set of COBESY criteria for each segment —
   MECE structure, working-memory fit, role-fit, clarity, falsifiability/evidence
   grounding, and absence of AI-slop — deterministically and without consulting any model.
2. The Review Gate shall derive each segment's role-fit and intent context from the
   segment's `roles` and `intent` as read from the loaded `Vocabulary`, never from a
   hardcoded role or intent list.
3. The Review Gate shall associate each segment with its evidence anchors derived from the
   matching `PlannedSegment` evidence (and any matching `RepoAnalysis` findings) so the
   falsifiability/evidence criterion can be judged against real repository facts.
4. Given equal inputs (same written segment, `CoveragePlan`, `RepoAnalysis`, and
   `Vocabulary`), the Review Gate shall produce equal criteria and equal evidence anchors
   for that segment on every run.
5. The Review Gate shall define an explicit per-criterion pass threshold and an explicit
   rule for combining the per-criterion outcomes into a single segment verdict, both
   deterministic and applied identically to every segment.

### Requirement 4: Deterministic judge-prompt assembly

**Objective:** As a test author, I want the judge-prompt assembly to be pure and
model-free, so that I can assert the gate's structure and grounding without any
credentials.

#### Acceptance Criteria
1. The Prompt Assembler shall build the judge request for a segment deterministically from
   that segment's content and criteria, without consulting any model.
2. The Prompt Assembler shall include in the request the segment's body and summary, its
   role/intent context, its evidence anchors, and the named criteria with their scoring
   instruction, and shall not include unrelated repository file contents.
3. The Prompt Assembler shall instruct the judge to return a structured per-criterion
   score and an overall pass/fail with a short reason, in a parseable format.
4. Given equal inputs, the Prompt Assembler shall produce an equal judge request on every
   run.

### Requirement 5: Single gated LLM-judge step

**Objective:** As an operator, I want the judgement to be the single model-dependent step,
gated and bounded, so that the gate runs credential-free in tests and within the inherited
cost and step budgets in production.

#### Acceptance Criteria
1. When a segment's judge request is ready and a model provider is bound, the Review Stage
   shall call the bound model once per segment to obtain that segment's per-criterion
   scores and overall verdict.
2. The Review Stage shall obtain the model provider from the harness-bound model
   configuration and shall not construct a provider itself or read provider credentials
   directly.
3. While judging, the Review Stage shall apply the inherited Control cost and step budgets
   and shall not introduce a separate uncapped judging loop.
4. If the judge call for a segment fails, times out, or returns an unparseable or empty
   response, then the Review Stage shall record a deterministic default verdict and a
   marker noting the judge was unavailable, and shall continue with the remaining
   segments, never aborting the run.
5. When the model is exercised through a fake or recorded judge with no network access,
   the Review Stage shall still produce a well-formed `ReviewReport` covering every written
   segment so the stage is testable end-to-end without credentials.
6. The judge step shall produce only per-criterion scores, an overall verdict, and a
   reason; it shall not modify the segment's content or any segment field.

### Requirement 6: Deterministic verdict, accept/reject, and failure handling

**Objective:** As a pipeline operator, I want each segment's verdict computed
deterministically from the judge output and the gate rules, with judge failures handled
deterministically, so that the accepted set is reproducible and a single bad judge call
never silently corrupts the run.

#### Acceptance Criteria
1. The Review Gate shall compute each segment's verdict (pass or fail) by applying the
   deterministic per-criterion thresholds and combination rule to the judge's per-criterion
   scores, independent of any free-form judge prose.
2. The Review Gate shall include in the accepted segment set exactly those segments whose
   verdict is pass, and shall exclude every segment whose verdict is fail.
3. When the judge is unavailable for a segment (failure, timeout, empty, or unparseable),
   the Review Gate shall apply the documented default verdict for the unavailable-judge
   case consistently to that segment and record the unavailable marker in the segment's
   report entry.
4. The Review Gate shall record, for every written segment, a per-segment report entry
   containing the segment id, the per-criterion scores, the overall verdict, the
   actionable findings, and the judge-source marker, leaving no written segment without an
   entry.
5. Given an empty written segment set (no segments to judge), the Review Stage shall
   produce a well-formed empty `ReviewReport`, surface an empty accepted set, and complete
   without error.
6. The Review Stage shall process the written segments in the written set's existing order
   so the report entries and the accepted set are deterministic across equal runs.

### Requirement 7: Surface the review report and accepted set (the assembler seam)

**Objective:** As the Wave 3 `mkdocs-site-assembler`, I want the gate to surface a frozen
review report and the accepted `Segment` set through a stable slot and accessor, so that I
assemble exactly the segments that passed the quality gate.

#### Acceptance Criteria
1. The Review Stage shall publish a frozen `ReviewReport` — carrying the per-segment
   entries, the accepted segment set, and an aggregate summary — to a new
   `SLOT_REVIEW_REPORT` slot via a typed `RunContext` accessor.
2. The slot-key constant and the `RunContext` accessor for the review report shall be added
   to the skeleton's shared types module and run-context module as an append-only addition,
   modifying no existing slot key, stage name, or accessor.
3. When the review report is read before the Review Stage has run, the `RunContext`
   accessor shall return an explicit absent value (`None`) rather than raising, matching the
   other slot accessors' absent-slot semantics.
4. The accepted segment set surfaced through `SLOT_REVIEW_REPORT` shall reference the same
   `Segment` identities as the written segments stored in the segment store, so a consumer
   can use either handle for the same content.
5. The `ReviewReport` shall expose its per-segment entries and accepted set in the written
   set's deterministic order so the downstream consumer reads a stable sequence across
   equal runs.
6. The `ReviewReport` shall carry an explicit schema version and a stabilized field set so
   the assembler can pin it; any change to that field set is a revalidation trigger for the
   assembler.

### Requirement 8: Aggregate quality summary

**Objective:** As a maintainer assessing a run, I want the report to carry an aggregate
quality summary, so that I can see overall acceptance and per-criterion outcomes at a
glance.

#### Acceptance Criteria
1. The `ReviewReport` shall include an aggregate summary carrying the total judged-segment
   count, the accepted count, the rejected count, and the count of segments judged via the
   unavailable-judge default.
2. The aggregate summary shall include a per-criterion pass/fail tally across all judged
   segments so a maintainer can see which COBESY criterion most often fails.
3. Given equal inputs and an equal (deterministic or recorded) judge source, the aggregate
   summary shall be equal on repeated runs.

### Requirement 9: Bounded observability

**Objective:** As a maintainer auditing a run, I want the Review Stage to record its
participation and a bounded summary in the journal, so that I can see the gate outcome
without bloating the trace on a large repository.

#### Acceptance Criteria
1. When the Review Stage completes on a bound run state, the Review Stage shall record its
   participation in the run journal with a summary-level detail only.
2. The journal summary shall include the total judged-segment count, the accepted count,
   the rejected count, the unavailable-judge count, and a capped list of top-priority
   accepted segment ids, and shall not include full segment bodies or full judge prose.
3. When the judge step is unavailable or runs against a fake judge, the Review Stage shall
   record in the bounded summary that verdicts were produced via the default or fake judge
   source so a credential-free run is auditable.

### Requirement 10: Configurable vocabulary and reproducibility

**Objective:** As a project using a custom ontology, I want the gate to adapt to my loaded
`Vocabulary` and behave reproducibly, so that the same harness gates content for any
project profile.

#### Acceptance Criteria
1. The Review Stage shall read all roles, intents, and subject prefixes from the loaded
   `Vocabulary` and shall contain no hardcoded role, intent, or subject literals in its
   criteria, prompt, aggregation, or wiring logic.
2. Where a segment's role or intent label or description differs from the default profile,
   the Review Gate shall use the loaded `Vocabulary`'s labels and descriptions when shaping
   the role-fit criterion and the judge prompt.
3. Given equal inputs and a deterministic (or recorded) judge source, the Review Stage
   shall produce an equal `ReviewReport` and accepted set on repeated runs, so a
   default-verdict or recorded run is fully reproducible.
