# Implementation Plan

- [x] 1. Foundation: data model, serialization, and harness seams
- [x] 1.1 Define the frozen RepoAnalysis model and its nested record types
  - Implement immutable (frozen) value objects for the full analysis: per-language stats, directory/structure summary, entrypoints, build/config files, CI workflows, test layout, dependencies, component map, public-surface symbols, documentation presence, notable artifacts, scan statistics, and the optional enrichment region
  - Use tuple-typed collections (not lists) so instances are deeply immutable
  - Carry an explicit RepoAnalysis schema-version identifier on the aggregate root
  - Observable: importing the model package yields a fully-typed `RepoAnalysis` aggregate with a populated schema version, and instances reject mutation
  - _Requirements: 6.1, 6.2, 6.3, 6.6_
  - _Boundary: model_

- [x] 1.2 Implement deterministic serialize/deserialize for RepoAnalysis
  - Provide ordered, JSON-compatible serialization and a round-trip deserialization that reconstructs an equal `RepoAnalysis`
  - Reject an unknown schema version on deserialization with an identifiable error
  - Observable: a unit test proves `from_dict(to_dict(a)) == a` and that JSON output is byte-identical for equal inputs across repeated calls
  - _Requirements: 6.3, 6.4, 6.5, 6.6_
  - _Boundary: serde_
  - _Depends: 1.1_

- [x] 1.3 Add the append-only slot keys for the inventory handoff and RepoAnalysis
  - Append a file-inventory handoff slot key and a `SLOT_REPO_ANALYSIS` slot key to the skeleton's shared types module, extending its export list, without altering any existing slot key, stage name, or stage-order entry
  - Observable: both new constants import successfully and a test confirms the pre-existing slot keys, `StageName`, and `STAGE_NAMES` are unchanged (shared-seam extension)
  - _Requirements: 7.1_
  - _Boundary: types_

- [x] 1.4 Add typed RunContext accessors for the inventory and RepoAnalysis slots
  - Add set/get accessor pairs for the file-inventory and RepoAnalysis slots mirroring the existing accessor style, returning `None` when a slot is unset
  - Leave every existing RunContext accessor signature and behavior unchanged
  - Observable: reading the RepoAnalysis slot before it is set returns `None`; setting then getting returns the stored analysis; existing accessor tests still pass
  - _Requirements: 7.3, 7.4, 7.5_
  - _Boundary: context_
  - _Depends: 1.3_

- [x] 1.5 Define the analysis error hierarchy
  - Implement a small stage-scoped error hierarchy (analysis base error plus ingest, analyze, and version-mismatch errors) used by the scanner, stages, and serde
  - Observable: each error type is importable and carries a clear message identifying the offending slot/path/version
  - _Requirements: 6.3, 8.4_
  - _Boundary: analysis errors_

- [x] 2. Core scanning: filesystem walk and language/LOC
- [x] 2.1 Implement the bounded, deterministic repository scanner
  - Walk the target repo into a sorted file inventory recording each retained file's repo-relative POSIX path, byte size, binary-vs-text classification, detected language tag, and line count
  - Exclude common noise directories without descending; do not follow symlinks outside the repo root; skip unreadable entries and count them rather than aborting
  - Enforce per-file read cap, total-file cap, and total-byte cap; mark a file as read-truncated when over the per-file cap and set a limit-reached flag plus a scan note when a total cap trips, still returning a well-formed inventory
  - Handle empty directories, zero-byte files, extensionless files, and unknown types as an "other" category without error
  - Observable: scanning a crafted fixture tree twice yields byte-identical inventories; over-size files appear with zero LOC and a truncation flag; an excluded directory is absent from the inventory
  - _Requirements: 1.3, 1.4, 1.5, 1.6, 2.1, 2.2, 2.3, 2.4, 2.5_
  - _Boundary: scanner_
  - _Depends: 1.1_

- [x] 2.2 (P) Implement deterministic language detection and LOC aggregation
  - Map files to canonical languages via an extension-and-filename rule set with an "other" fallback, and aggregate per-language file counts and total LOC
  - Identify the primary language(s) as those tied for the greatest LOC, exposed alongside the per-language breakdown
  - Observable: a fixture with many docs files but a higher-LOC source language reports that source language as primary, and repeated runs produce identical breakdowns
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5_
  - _Boundary: languages_
  - _Depends: 1.1_

- [x] 3. Core detectors: signals over the inventory
- [x] 3.1 (P) Detect structure, entrypoints, build/config, and CI workflows
  - Produce a top-level directory/structure summary (dominant contents/role per directory), detect language-appropriate entrypoints, classify build/config files including those nested in sub-projects, and detect CI/workflow configuration with provider and path
  - Record each detection category as empty rather than omitting it when there are no matches, keeping the model shape stable
  - Observable: against the reference repo both top-level and nested manifests are classified, GitHub Actions CI is detected, and the entrypoint is identified
  - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.6_
  - _Boundary: detectors_
  - _Depends: 2.1_

- [x] 3.2 (P) Detect test presence/layout and parse declared dependencies
  - Detect recognized test files, directories, and frameworks per language and record whether tests are present and where; extract declared dependencies from recognized manifests with their source manifest and scope
  - On a malformed or partially parseable manifest, record what could be extracted, mark it partially parsed, and continue without aborting
  - Observable: a fixture with a malformed manifest yields a partial dependency list plus a "partially parsed" scan note, and reference-repo `*_test.go` files are reported as present
  - _Requirements: 4.5, 4.6, 5.1, 5.6_
  - _Boundary: detectors_
  - _Depends: 2.1_

- [x] 3.3 (P) Build the component map and detect public surface, docs, and artifacts
  - Derive a component/module map from the directory/package structure (each unit with its path and a small representative file set), capture cheaply-detectable public surface (CLI flags/subcommands and exported symbols) while omitting anything needing deep semantic analysis, and record documentation presence and notable artifacts by filename/pattern
  - Observable: the reference repo yields a component for its main package, detects its README, and produces conservative public-surface entries with no deep-parse signals
  - _Requirements: 5.2, 5.3, 5.4, 5.5, 4.6_
  - _Boundary: detectors_
  - _Depends: 2.1_

- [x] 4. Core analyzer and optional enrichment
- [x] 4.1 Compose the deterministic analyzer
  - Combine language/LOC aggregation and all detectors into a single deterministic, model-free `RepoAnalysis` with every collection pre-sorted and empty categories present as empty tuples, enrichment absent
  - Observable: analyzing a fixture inventory twice returns equal `RepoAnalysis` objects with no model or network involved
  - _Requirements: 3.1, 3.2, 3.3, 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 9.1, 9.2_
  - _Boundary: analyzer_
  - _Depends: 2.2, 3.1, 3.2, 3.3_

- [x] 4.2 Implement the optional, gated LLM enrichment hook
  - Add an enrichment step that, only when explicitly enabled and given a bound model, attaches a narrative architecture summary into the separated enrichment region without altering any deterministic core field
  - When disabled or model-less, return the analysis unchanged (enrichment absent) and treat that as success; on failure or timeout, log, omit enrichment, and still return the complete core analysis
  - Observable: with enrichment disabled the result has no enrichment and equals the core analysis; a simulated enrichment failure still returns the complete core analysis
  - _Requirements: 9.3, 9.4, 9.5_
  - _Boundary: enrich_
  - _Depends: 4.1_

- [x] 5. Stage integration: replace the Ingest and Analyze stubs
- [x] 5.1 Replace the Ingest stub with the real scanning stage
  - Replace the no-op Ingest body so the stage reads the target-repository path from the run context, runs the scanner, and publishes the file inventory to the handoff slot, keeping the stage name, class name, factory, and module path stable
  - Raise an identifiable ingest error that halts the run when the repo slot is unset or the path is missing/not a directory, without producing a partial inventory; record participation and a bounded scan summary in the journal
  - Observable: driving the stage against a state with a valid repo populates the inventory slot and emits a participation trigger; an unset/invalid repo path raises the ingest error
  - _Requirements: 1.1, 1.2, 1.7, 8.1, 8.2, 8.3, 8.4, 8.5, 10.1, 10.2, 10.3_
  - _Boundary: IngestStage_
  - _Depends: 1.4, 1.5, 2.1_

- [x] 5.2 Replace the Analyze stub with the real analysis stage
  - Replace the no-op Analyze body so the stage reads the file inventory from the run context, runs the deterministic analyzer, applies the gated enrichment, and writes the `RepoAnalysis` to its slot, keeping the stage name, class name, factory, and module path stable
  - Raise an identifiable analyze error that halts the run when the inventory slot is unset, without producing a partial analysis; record participation and a bounded analysis summary in the journal; require no model binding for the core path
  - Observable: driving the stage after Ingest populates the `RepoAnalysis` slot and emits a participation trigger; a missing inventory raises the analyze error
  - _Requirements: 7.2, 8.1, 8.2, 8.3, 8.4, 8.5, 9.1, 9.4, 10.1, 10.2, 10.3_
  - _Boundary: AnalyzeStage_
  - _Depends: 1.4, 1.5, 4.1, 4.2_

- [x] 6. Validation
- [x] 6.1 Unit-test the deterministic core against crafted fixtures
  - Cover excluded-dir non-descent, symlink-escape non-follow, binary/text classification, over-size truncation, total-limit trip, edge-case files, language/LOC ordering and primary-language ties, serde round-trip and byte-stable JSON, version rejection, nested-manifest and CI/test detection, malformed-manifest partial parse, and conservative public-surface extraction
  - Observable: the suite passes and asserts byte-identical results across two runs over the same fixtures
  - _Requirements: 1.3, 1.4, 1.5, 1.6, 2.1, 2.2, 2.3, 2.4, 3.1, 3.2, 3.3, 3.4, 3.5, 4.3, 4.4, 4.5, 5.1, 5.3, 5.6, 6.4, 6.5, 6.6, 9.1, 9.2_
  - _Boundary: scanner, languages, detectors, serde, model_
  - _Depends: 1.2, 2.1, 2.2, 3.1, 3.2, 3.3_

- [x] 6.2 Integration-test the stages, slots, and enrichment gating
  - Drive Ingest then Analyze over a harness state and assert the inventory and `RepoAnalysis` slots are populated, participation triggers are emitted, missing repo/inventory raise the expected stage errors, the enrichment gate is honored (disabled equals core; failure still emits core), and `make_docgen` still composes with unchanged stage ordering and the other six stages remaining no-ops
  - Observable: the integration suite passes end-to-end from Ingest through a populated `RepoAnalysis` slot, and the bundle smoke test confirms canonical stage order is preserved
  - _Requirements: 1.7, 7.2, 7.4, 8.1, 8.2, 8.3, 8.4, 9.3, 9.4, 9.5, 10.1, 10.3_
  - _Boundary: IngestStage, AnalyzeStage_
  - _Depends: 5.1, 5.2_

- [x] 6.3 Validate determinism against the reference repository
  - Run the analysis against the reference Go CLI repo and assert primary language is Go, both root and nested manifests are detected, GitHub Actions CI is detected, tests and README are present, and two consecutive runs serialize byte-identically
  - Observable: the reference-repo test passes and demonstrates run-to-run determinism on a real polyglot project
  - _Requirements: 3.3, 4.3, 4.4, 4.5, 5.4, 9.2_
  - _Boundary: analyzer_
  - _Depends: 4.1, 4.2_
