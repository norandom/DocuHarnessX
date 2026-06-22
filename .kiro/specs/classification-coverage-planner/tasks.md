# Implementation Plan

- [x] 1. Foundation: planning package, frozen model, and serde
- [x] 1.1 Create the planning package and the frozen CoveragePlan data model
  - Add a new `docuharnessx/planning/` package with `model.py` defining the immutable,
    tuple-only value objects: `EvidenceRef`, `PlannedSegment`, `CoveragePlan`, and the
    intermediate `Classification`/`CandidateCell` handoff records, reusing the ontology
    `Subject` type for the `subjects` field
  - Define `COVERAGE_PLAN_SCHEMA_VERSION = 1` carried on every `CoveragePlan` instance as
    the single version authority
  - Define the planning error hierarchy: `PlanningError` base, `PlanningInputError`,
    `CoveragePlanVersionError`
  - Observable completion: constructing a `CoveragePlan`/`PlannedSegment` succeeds, all
    collection fields are tuples, attempting to mutate a field raises, and two instances
    built from equal inputs compare equal
  - _Requirements: 6.1, 6.2, 6.3_
  - _Boundary: model_
- [x] 1.2 Implement deterministic CoveragePlan serialization and round-trip deserialization
  - Add `serde.py` with `to_dict`, `from_dict`, and `to_json` that serialize each
    `Subject` to its canonical string and rebuild it on load, emitting JSON with
    `sort_keys=True` for byte-stability
  - Raise `CoveragePlanVersionError` from `from_dict` when the declared schema version is
    unsupported
  - Observable completion: `from_dict(to_dict(plan)) == plan` for a populated plan,
    `to_json` returns byte-identical strings for equal inputs across repeated calls, and
    an unknown `schema_version` raises `CoveragePlanVersionError`
  - _Requirements: 6.4, 6.5, 6.6_
  - _Boundary: serde_
  - _Depends: 1.1_

- [x] 2. Core: deterministic classification (subjects + coverage matrix)
- [x] 2.1 (P) Derive typed ontology Subjects from RepoAnalysis findings
  - Add `subjects.py` mapping components/modules to `component:`, languages/frameworks to
    `tech:`, build/CI/license/schema/generated artifacts to `artifact:`, and inferred
    cross-cutting concerns to `topic:`, building each via the ontology `Subject.parse`
    against the loaded vocabulary's prefixes
  - Omit any subject whose prefix is absent from the loaded vocabulary; attach an
    `EvidenceRef` (source path/token) to every derived subject
  - Observable completion: given a crafted `RepoAnalysis` and the default vocabulary, the
    function returns deterministically ordered `(Subject, EvidenceRef)` pairs; given a
    vocabulary missing the `topic:` prefix, no `topic:` subjects are returned
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5_
  - _Boundary: subjects_
  - _Depends: 1.1_
- [x] 2.2 (P) Build the evidence-gated signal-to-cell rule table over the loaded vocabulary
  - Add `matrix.py` whose candidate space is `vocab.roles x vocab.intents` only, with a
    documented rule table mapping analysis predicates (CLI entrypoint, CI+build, tests,
    public surface, security/forensics signal, integration surface, docs) to (role id,
    intent id) hint pairs
  - Activate a cell only when its evidence predicate fires and both its role id and
    intent id are members of the loaded vocabulary; skip rows whose ids are absent; attach
    the derived subjects and activating evidence; order cells by `vocab.intent_order()`
  - Observable completion: a `RepoAnalysis` with a CLI entrypoint activates
    install/use/troubleshoot cells for the matching user role; a vocabulary lacking those
    intents produces no such cells; repeated runs over equal inputs return identical cells
  - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5_
  - _Boundary: matrix_
  - _Depends: 1.1_
- [x] 2.3 Compose subjects and matrix into the Classification, consuming RepoAnalysis verbatim
  - Add `classifier.py` with `classify_repo(analysis, vocab)` that derives subjects,
    activates cells, and returns a fully-populated `Classification` (subjects + cells +
    evidence + vocabulary fingerprint), reading the upstream `RepoAnalysis` fields/shapes
    exactly as published without reimplementing the model
  - Observable completion: `classify_repo` over a crafted analysis returns a
    `Classification` whose subjects and cells match the component outputs, is identical
    across two runs, and references only `RepoAnalysis` fields defined by the upstream
    contract
  - _Requirements: 2.1, 2.2, 3.1, 4.1_
  - _Boundary: classifier_
  - _Depends: 2.1, 2.2_

- [x] 3. Core: deterministic scoring, ordering, and plan materialization
- [x] 3.1 (P) Implement deterministic cell scoring and the total ordering key
  - Add `scorer.py` assigning each candidate cell an integer priority from evidence
    strength/count plus documented role and intent weights resolved by id position in the
    loaded vocabulary, and an `order_key` of (priority desc, role order, intent order,
    segment key)
  - Observable completion: a cell with more supporting evidence scores strictly higher
    than an otherwise-equal cell; the ordering key produces a total, reproducible order;
    scores are identical across two runs over equal inputs
  - _Requirements: 5.1, 5.2, 5.3_
  - _Boundary: scorer_
  - _Depends: 1.1_
- [x] 3.2 Materialize the scored, ordered CoveragePlan from a Classification
  - Add `planner.py` with `plan_coverage(classification, vocab)` that builds one
    `PlannedSegment` per activated cell (deterministic `segment_key`, scored priority,
    sorted subjects, sorted evidence), orders segments by the scoring order key, and sets
    `schema_version`, `repo_path`, and `vocabulary_fingerprint`
  - Return a well-formed `CoveragePlan` with an empty `segments` tuple when no cell is
    activated, never raising and never fabricating segments
  - Observable completion: over a crafted `Classification` the returned plan lists
    segments in descending priority with each segment carrying roles/subjects/intent and
    evidence; an empty `Classification` yields an empty-but-valid plan; two runs are equal
  - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 6.1, 8.1_
  - _Boundary: planner_
  - _Depends: 1.1, 3.1_
- [x] 3.3 Add the optional gated LLM relevance hook (annotate/re-rank only)
  - Add `relevance.py` with `apply_relevance(plan, *, model, enabled, timeout_s)` that
    returns the input unchanged when disabled or no model is bound, and otherwise may
    reorder segments and set per-segment `relevance_note` while preserving every
    segment's roles/intent/subjects and the set of cells
  - On any exception or timeout, log and return the unchanged deterministic plan so the
    run continues; expose activation only via the explicit `enabled` flag
  - Observable completion: disabled returns `relevance_applied=False` with identical
    segments; a simulated hook failure returns the deterministic plan unchanged; an
    enabled success reorders/annotates but leaves every segment's required writer fields
    unchanged
  - _Requirements: 8.2, 8.3, 8.4, 8.5_
  - _Boundary: relevance_
  - _Depends: 3.2_
- [x] 3.4 Export the planning core public surface
  - Populate `docuharnessx/planning/__init__.py` re-exporting `classify_repo`,
    `plan_coverage`, `apply_relevance`, `CoveragePlan`, `PlannedSegment`,
    `Classification`, the serde functions, and the error types
  - Observable completion: `from docuharnessx.planning import classify_repo,
    plan_coverage, CoveragePlan, to_dict, from_dict` succeeds and the package `__all__`
    lists the public surface
  - _Requirements: 6.1, 6.2_
  - _Boundary: planning package_
  - _Depends: 1.2, 2.3, 3.2, 3.3_

- [x] 4. Integration: harness seams (slots, accessors) and stage replacement
- [x] 4.1 Extend the slot-key and RunContext seams append-only
  - Add `SLOT_CLASSIFICATION` and `SLOT_COVERAGE_PLAN` constants to `docuharnessx/types.py`
    append-only and add both to `__all__`, modifying no existing constant, `StageName`, or
    `STAGE_NAMES` entry
  - Add append-only `set_classification`/`classification` and
    `set_coverage_plan`/`coverage_plan` accessor pairs to `docuharnessx/context.py`,
    mirroring the existing slot-type-tag + `_get_content` style, with the getters
    returning `None` when the slot is unset and no existing accessor changed
  - Observable completion: setting then getting a plan via `RunContext` round-trips the
    object, `coverage_plan()` returns `None` on an unset slot, and the existing skeleton
    test suite still passes unchanged
  - _Requirements: 7.1, 7.2, 7.4, 7.5_
  - _Boundary: types, context_
  - _Depends: 1.1_
- [x] 4.2 Replace the Classify stub with the real ClassifyStage
  - Replace the no-op body in `docuharnessx/stages/classify.py` so `on_step_end` wraps the
    bound runtime `State` in a `RunContext`, reads `repo_analysis()` and `vocabulary()`,
    raises `PlanningInputError` when either is missing or the analysis declares an
    unsupported schema version, else runs `classify_repo` and publishes the
    `Classification` via `set_classification`, keeping `STAGE_NAME`, `ClassifyStage`, and
    `make_classify_stage` unchanged
  - Emit the stage participation trigger plus a bounded classify summary detail (subject
    counts per prefix, activated-cell count), then yield the lifecycle event unchanged
  - Observable completion: driving `ClassifyStage.on_step_end` against a `State` carrying a
    valid analysis + vocabulary leaves a `Classification` in `SLOT_CLASSIFICATION` and a
    participation trigger in the journal; a missing analysis or vocabulary raises
    `PlanningInputError`
  - _Requirements: 1.1, 1.2, 1.3, 2.1, 2.3, 2.4, 2.5, 9.1, 9.3_
  - _Boundary: ClassifyStage_
  - _Depends: 2.3, 4.1_
- [x] 4.3 Replace the Plan stub with the real PlanStage
  - Replace the no-op body in `docuharnessx/stages/plan.py` so `on_step_end` reads
    `classification()` (raising `PlanningInputError` when missing) and `vocabulary()`,
    runs `plan_coverage`, optionally applies the gated relevance hook, and publishes the
    `CoveragePlan` via `set_coverage_plan`, keeping `STAGE_NAME`, `PlanStage`, and
    `make_plan_stage` unchanged
  - Emit the stage participation trigger plus a bounded plan summary detail (total
    segments, top segment keys, `relevance_applied`, empty-plan reason), then yield the
    lifecycle event unchanged, and never write the full plan to the trace
  - Observable completion: driving `PlanStage.on_step_end` after Classify leaves a
    `CoveragePlan` in `SLOT_COVERAGE_PLAN` and a bounded summary in the journal; a missing
    classification raises `PlanningInputError`; an empty plan records an explainable
    reason
  - _Requirements: 1.1, 1.2, 1.3, 5.5, 7.3, 8.2, 8.3, 8.4, 9.2, 9.3, 9.4_
  - _Boundary: PlanStage_
  - _Depends: 3.4, 4.1, 4.2_

- [x] 5. Validation: determinism, project-specificity, and pipeline integration
- [x] 5.1 (P) Unit-test the deterministic core (subjects, matrix, scorer, serde)
  - Cover subject derivation per prefix and prefix omission, evidence-gated cell
    activation with vocabulary filtering and `intent_order()` ordering, monotonic
    evidence-driven scoring with total tie-breaking, and serde round-trip plus
    byte-stability plus the version error
  - Observable completion: the unit suite passes and demonstrates byte-identical
    serialization and identical scores/cells across two runs over equal inputs
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 4.3, 4.4, 4.5, 5.1, 5.2, 5.3, 6.4, 6.5, 6.6, 8.1_
  - _Boundary: subjects, matrix, scorer, serde_
  - _Depends: 2.1, 2.2, 3.1, 1.2_
- [x] 5.2 Test project-specificity across default and custom vocabularies (acceptance signal)
  - Run the full classify-then-plan core over one crafted `RepoAnalysis` with the default
    profile and again with a custom `Vocabulary` (renamed roles/intents plus an extra
    subject prefix), asserting the two plans differ and the custom plan contains only
    custom role/intent/subject ids
  - Observable completion: the test proves the planner output is project-specific (not
    templated) by showing diverging plans and the absence of any default-profile id in the
    custom-vocabulary plan
  - _Requirements: 4.1, 4.2_
  - _Boundary: classifier, planner_
  - _Depends: 2.3, 3.2_
- [x] 5.3 Integration-test the stages and the relevance gate against a harness State
  - Drive `ClassifyStage` then `PlanStage` via `on_step_end` to confirm the
    `Classification` and `CoveragePlan` slots are populated, the input-error paths raise
    `PlanningInputError` (missing analysis, missing vocabulary, missing classification,
    unsupported analysis schema version), an empty-evidence analysis yields a well-formed
    empty plan, and the relevance hook gates/falls-back correctly
  - Observable completion: the integration suite passes, showing both slots populated on
    the happy path, each input-error path raising with an identifiable cause, and the
    deterministic plan retained on a simulated relevance failure
  - _Requirements: 1.2, 1.3, 2.3, 2.4, 2.5, 5.5, 7.3, 8.2, 8.3, 8.4, 9.1, 9.2, 9.4_
  - _Boundary: ClassifyStage, PlanStage, relevance_
  - _Depends: 4.2, 4.3, 3.3_
- [x] 5.4 Smoke-test pipeline composition and reference-repo-shaped planning
  - Assert `make_docgen()` still composes, the `STAGES` order is unchanged, and the six
    other stages remain no-ops; and that a `RepoAnalysis` shaped like the
    `malware_hashes` Go CLI (go.mod, GitHub Actions, `*_test.go`, README, forensic topic)
    activates install/use/troubleshoot for a user role, evaluate for adopter/manager, and
    assess-quality for security/compliance, deterministically across two runs
  - Observable completion: the bundle composes without conflict, the registry ordering is
    intact, and the reference-shaped plan contains the expected role x intent cells with
    identical output across two runs
  - _Requirements: 1.4, 1.5, 4.3, 5.2, 5.3_
  - _Boundary: ClassifyStage, PlanStage, planning package_
  - _Depends: 4.3, 5.2_
