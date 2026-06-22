# Brief — repo-ingestion-analysis

## Feature

Make the **Ingest + Analyze** pipeline stages real. Scan a target software project
(25–40k LOC, polyglot) and produce a structured, deterministic **RepoAnalysis** that
downstream stages consume. This is Wave 1, spec #1 — the first real work the empty
`dhx` pipeline performs.

## Why It Exists

The harness-bundle-skeleton ships `ingest.py` and `analyze.py` as no-op stubs. This
spec replaces those two stubs with real `Processor` stages that read the target repo
(via the `RunContext` target-repo slot) and emit an analysis the
classification-coverage-planner (Wave 1 spec #2) turns into a coverage plan.

## In Scope

- Replace `docuharnessx/stages/ingest.py` and `docuharnessx/stages/analyze.py` no-op
  stubs with real stage processors registered on the existing `PIPELINE_HOOK`
  (preserve canonical order; append-don't-replace; single-stage swap per skeleton design).
- **RepoAnalysis data model** (serializable, deterministic) capturing at least:
  languages + LOC, directory/file structure, entrypoints, build/config files
  (pyproject/go.mod/package.json/Dockerfile/etc.), CI workflows, test presence/layout,
  declared dependencies, component/module map, public surface (CLI flags, exported
  symbols where cheaply detectable), README/docs presence, and notable artifacts.
- **Output seam**: write `RepoAnalysis` into a new `RunContext` slot (e.g.
  `SLOT_REPO_ANALYSIS`). The slot-key constant is added to `docuharnessx/types.py`
  **append-only** (types.py is owned by harness-bundle-skeleton — extend, don't rewrite).
- Deterministic core scanning (filesystem walk + lightweight parsing) that is
  unit-testable without a model. Any LLM-based enrichment (e.g. architecture
  summary) must be OPTIONAL and gated, never required for the core analysis.
- Robust on large repos (bounded by the existing Control cost/loop guards) and on
  polyglot/edge cases (empty dirs, binary files, no build file).

## Out of Scope

- Mapping to the ontology / deciding what to document (classification-coverage-planner).
- Writing doc content (cobesy-writer), review, assembly, deploy.

## Dependencies

- `harness-bundle-skeleton` — `RunContext`, slot keys, stage base/registry, `make_docgen`.
- (No dependency on ontology-engine for the raw scan; the analysis is ontology-agnostic.)

## Key Constraints

- Python 3.12; deterministic + unit-testable core; reuse `RunContext` and the stage
  contract. Reference target: `/home/mc/Source/malware_hashes` (~6.8k LOC Go CLI).
- The `RepoAnalysis` model is the frozen seam the planner consumes — design it for stability.

## Acceptance Signal

Running the pipeline against a sample repo populates a `RepoAnalysis` in the run
context (languages, structure, entrypoints, build/CI/tests, components) and is recorded
in the journal; deterministic across runs; verified by unit tests on crafted fixtures
and against the reference repo.
