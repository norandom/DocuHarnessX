# Implementation Plan

- [x] 1. Foundation: review-core package + frozen data model + seam additions
- [x] 1.1 Create the review-core package skeleton and frozen `ReviewReport` data model
  - Create the `docuharnessx/review/` package with a single public namespace, mirroring the planning/composition package layout.
  - Define the frozen, tuple-based value objects: the per-segment review entry, the per-criterion score, the parsed judge verdict, the aggregate, the per-criterion tally, and the top-level review report; plus the verdict and judge-source value types and the version authority constant.
  - Define the review error hierarchy (a base error and a fatal input error), kept independent of the skeleton-wide error family, matching the planning/writer error pattern.
  - Observable completion: importing the package exposes the report model, the version constant, and the error types; constructing a report from sample entries yields a frozen, structurally-equal value object (two equal constructions compare equal).
  - _Requirements: 6.1, 6.4, 7.1, 7.6, 8.1_
  - _Boundary: ReviewModel_

- [x] 1.2 Define the COBESY criteria constants and the deterministic gate rules
  - Define the fixed named COBESY criteria set (MECE, working-memory fit, role-fit, clarity, falsifiability/evidence, no-AI-slop), the single per-criterion pass threshold constant, the documented all-of combination rule, and the fail-closed default-verdict constant for an unavailable judge.
  - Observable completion: the criteria names, threshold, and default-verdict are importable constants; a unit test asserts the named criteria set and that the default-unavailable verdict is reject.
  - _Requirements: 3.1, 3.5, 6.3_
  - _Boundary: ReviewModel, Criteria Builder_
  - _Depends: 1.1_

- [x] 1.3 Append the review-report slot key and run-context accessor (append-only seam)
  - Append the `SLOT_REVIEW_REPORT` slot-key constant to the shared types module and add it to that module's export list, modifying no existing slot key, stage name, or stage-name tuple entry.
  - Append the typed `set_review_report` / `review_report` accessors and the slot-type tag to the run context, with a TYPE_CHECKING import of the report model; an unset slot returns `None` like every other accessor.
  - Observable completion: setting then reading the report slot through the run context round-trips the report value; reading it on a fresh state returns `None`; existing slot accessors and exports are unchanged.
  - _Requirements: 7.1, 7.2, 7.3_
  - _Boundary: types/context additions_
  - _Depends: 1.1_

- [x] 2. Core: deterministic review-core components (no model)
- [x] 2.1 (P) Implement the deterministic criteria builder
  - Build, for one written segment plus its matching planned segment, analysis, and the loaded vocabulary, a deterministic per-segment criteria context: the named criteria, the role/intent context derived from the loaded vocabulary's labels and descriptions (never hardcoded), and the evidence anchors derived from the matching planned-segment evidence and any matching analysis finding.
  - Tolerate absent analysis (anchors fall back to evidence refs alone) and a written segment with no matching planned segment (empty anchors, still produced); treat all inputs read-only.
  - Observable completion: a unit test builds criteria for a segment under a custom vocabulary and asserts the criteria names, the role-fit context taken from the custom vocab labels, evidence anchors with and without a matching analysis finding, and that equal inputs yield equal criteria and anchors.
  - _Requirements: 2.5, 2.6, 3.1, 3.2, 3.3, 3.4, 10.1, 10.2_
  - _Boundary: Criteria Builder_
  - _Depends: 1.2_

- [x] 2.2 (P) Implement the deterministic judge-prompt assembler
  - Build the model-free judge request from a per-segment criteria context: a system instruction to score each named criterion in range with a one-line reason and an overall pass/fail in a strict JSON shape, and a user message carrying the segment body/summary, the vocab-derived role/intent context, and the evidence anchors; include no unrelated repository file contents; offer no tools.
  - Import the harness message type lazily with a plain-dict fallback so the core never hard-depends on the harness at import time.
  - Observable completion: a unit test asserts the request is deterministic for equal criteria, carries the segment content + role/intent context + evidence anchors + the structured-verdict instruction, contains no unrelated file contents, and offers an empty tools list.
  - _Requirements: 4.1, 4.2, 4.3, 4.4_
  - _Boundary: Judge Prompt Assembler_
  - _Depends: 1.2_

- [x] 2.3 (P) Implement the deterministic verdict parser
  - Parse the judge's JSON content into a bounded verdict: strip fenced code, decode JSON, clamp each criterion score to range, coerce the per-criterion and overall pass flags (defaulting a missing flag to the threshold rule), and keep only known criterion names; return an absent value on malformed, empty, or wrong-shape content without raising.
  - Observable completion: unit tests parse a clean verdict, strip a fenced-code wrapper, clamp out-of-range scores, default a missing pass flag via the threshold, drop an unknown criterion, and return the absent value for malformed/empty input.
  - _Requirements: 4.3, 6.1_
  - _Boundary: Verdict Parser_
  - _Depends: 1.2_

- [x] 2.4 (P) Implement the deterministic verdict computer
  - Compute a per-segment review entry from a parsed verdict (or the absent value) plus the criteria and a judge-source marker: apply the per-criterion threshold and the all-of combination rule to derive the pass/fail verdict independent of free-form prose; on the absent verdict apply the fail-closed default-reject with the unavailable judge-source and a marker finding; derive one actionable finding per failing criterion; always produce an entry.
  - Observable completion: unit tests show all-pass criteria yield pass, one failing criterion yields fail with a finding, an absent verdict yields default-reject with the unavailable source and marker, and equal inputs yield equal entries.
  - _Requirements: 3.5, 6.1, 6.3, 6.4_
  - _Boundary: Verdict Computer_
  - _Depends: 1.2_

- [x] 2.5 Implement the deterministic aggregator and report assembler
  - From the ordered per-segment entries and a map from segment id to the written segment, build the accepted set as exactly the pass entries in written order carrying the same segment identities; compute the aggregate counts (judged, accepted, rejected, unavailable) and the per-criterion pass/fail tally; assemble the frozen report with the schema version; an empty entries input yields a well-formed empty report.
  - Observable completion: unit tests assert the accepted set equals the pass entries in order with identical segment identities, the aggregate counts and per-criterion tally are correct, an empty input yields an empty report, and equal inputs yield an equal report.
  - _Requirements: 6.2, 6.5, 7.1, 7.4, 7.5, 8.1, 8.2, 8.3_
  - _Boundary: Aggregator_
  - _Depends: 2.4_

- [x] 3. Core (gated model): the single judge step
- [x] 3.1 Implement the gated, fault-tolerant per-segment judge step
  - Implement the only model-touching module: over a duck-typed provider, build the request (reusing the prompt assembler), drive the provider's awaitable completion once under a wall-clock timeout on a private loop, and delegate parsing to the verdict parser; absorb every failure, timeout, empty, or unparseable response by returning the absent value and logging a warning; never raise; never construct a provider; set no segment field.
  - Observable completion: unit tests with a stub provider returning clean JSON yield a parsed verdict; a raising provider, a timing-out provider, and an empty/garbage response each yield the absent value without raising; exactly one completion call is issued per invocation.
  - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.6_
  - _Boundary: Gated Judge Step_
  - _Depends: 2.2, 2.3_

- [x] 4. Integration: the real Review stage adapter (in-place stub replacement)
- [x] 4.1 Replace the review stub with the real stage adapter wiring the core
  - Replace the no-op review module body in place while keeping the stage-name constant, the stage class name, the factory name, the module path, and the no-op re-export stable so the registry and the bundle need no edits; subclass the shared no-op base and attach to the same pipeline hook.
  - Capture the run state on task start; on step end, when a state is bound, read the written-segment set, coverage plan, analysis, vocabulary, and segment-store slots; pin the coverage-plan schema version and raise the fatal input error on an unsupported version or a missing written-segment or vocabulary slot, producing no report; outside a harness, forward the event unchanged and produce nothing.
  - Build the plan lookup once; for each written segment in written order, build criteria, assemble the request, run the gated judge off the run loop (in a worker thread) when a model is bound (obtained from the harness-bound model config, degrading to the default-reject path on any failure to reach it), compute the verdict with the appropriate judge-source, aggregate, assemble the report, and publish it to the review-report slot; then yield the lifecycle event unchanged.
  - Observable completion: a credential-free integration run via the bundle bound to the fake provider over a seeded written set, coverage plan, analysis, vocabulary, and in-memory store publishes a well-formed report covering every written segment into the report slot, with the registry and bundle unedited.
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 5.1, 5.2, 6.5, 6.6, 7.1, 7.4, 7.5_
  - _Boundary: ReviewStage_
  - _Depends: 1.3, 2.1, 2.5, 3.1_

- [x] 4.2 Add the bounded journal summary and judge-source markers
  - On completion with a bound state, emit a participation trigger to the run tracer carrying a summary-level detail only: the judged, accepted, rejected, and unavailable counts, a capped list of top-priority accepted segment ids, and a judge-source breakdown marker; never include full bodies or full judge prose; no-op when no tracer is bound.
  - Observable completion: the integration run records a single bounded participation trigger whose detail carries the four counts, a capped accepted-id list, and the judge-source breakdown, with no segment body present.
  - _Requirements: 9.1, 9.2, 9.3_
  - _Boundary: ReviewStage_
  - _Depends: 4.1_

- [x] 5. Validation: credential-free end-to-end and reproducibility tests
- [x] 5.1 Stage integration and gating tests via the bundle with the fake provider
  - Verify, credential-free through the bundle, that every written segment gets exactly one report entry; that the accepted set is consistent with the per-segment verdicts and references the same stored segment identities; that a stub provider returning a clean passing verdict produces accepted passes while a model-less or fake run produces fail-closed default-reject entries with the unavailable source and an empty accepted set; and that an injected raising/timing-out/unparseable judge default-rejects only that segment while the run completes without aborting.
  - Verify an empty written set yields a well-formed empty report with no error.
  - Observable completion: the integration test suite passes, asserting report coverage, the accept path under a passing stub judge, the fail-closed path under the fake/absent judge, per-segment failure isolation, and the empty-set case.
  - _Requirements: 5.4, 5.5, 6.2, 6.3, 6.4, 6.5_
  - _Boundary: ReviewStage_
  - _Depends: 4.1, 4.2_

- [x] 5.2 Stable replaceability and reproducibility tests
  - Verify the stage-name constant, class name, factory name, and module path are unchanged and that the stage registry and bundle composition need no edits, and that an out-of-harness direct drive of the stage forwards the event unchanged and produces nothing.
  - Verify two review runs over an equal written set with an equal recorded/default judge source produce an equal report (equal entries, scores, verdicts, accepted set, aggregate, and order).
  - Observable completion: the replaceability test confirms the unchanged public surface and the pass-through behavior; the reproducibility test confirms two equal-input runs yield an equal report.
  - _Requirements: 1.1, 1.3, 8.3, 10.3, 6.6_
  - _Boundary: ReviewStage_
  - _Depends: 5.1_
