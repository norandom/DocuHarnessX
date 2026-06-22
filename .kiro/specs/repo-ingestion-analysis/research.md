# Research Log — repo-ingestion-analysis

## Discovery Scope

Discovery type: **Extension / integration-focused** (Wave 1 spec building on the
merged Wave 0 foundation). Focus: integration points with the harness skeleton,
existing patterns to follow, and the reference target repo's real shape. No
external dependencies are introduced (Python 3.12 stdlib only for the core).

## Key Findings

### F1 — Stages do work as a side effect of a content-free `step_end` event
`PIPELINE_HOOK = "step_end"`; `StepEndEvent` carries no message/content window, so
a stage structurally cannot mutate generated content. `NoOpStage` already binds the
live runtime (`_bind_runtime`) and emits a `ProcessorTriggerEvent` then yields the
event unchanged. **Implication**: the real Ingest/Analyze stages read inputs and
write outputs through `RunContext` slots (a side effect) and still yield the
unchanged event — identical lifecycle behavior, richer journal record. They reach
the run `State` via the bound runtime, wrapped in a `RunContext`.

### F2 — `types.py` and `RunContext` are skeleton-owned; extend append-only
`types.py` (`SLOT_*`, `StageName`, `STAGE_NAMES`) and `context.py` are owned by
`harness-bundle-skeleton`. **Implication**: add `SLOT_REPO_ANALYSIS` (and the
inter-stage `SLOT_FILE_INVENTORY`) append-only + new `RunContext` accessor pairs
mirroring the `_get_content` pattern; touch no existing line. Flagged as a
shared-seam extension and a revalidation trigger.

### F3 — Single-stage replaceability requires stable module/class/factory names
`stages/__init__.py` imports `IngestStage`/`make_ingest_stage` and
`AnalyzeStage`/`make_analyze_stage` by name and lists them in `STAGES` in canonical
order; `make_docgen` composes the registry. **Implication**: replace only the two
module *bodies*; keep `STAGE_NAME`, class names, factory names, and module paths so
the registry and bundle need no edits and the other six stubs stay untouched.

### F4 — Reference repo confirms the polyglot/edge-case requirements
`/home/mc/Source/malware_hashes` (~2.9k LOC Go) has: root `go.mod` + a nested
`.dagger/go.mod`; `.github/workflows/` (GitHub Actions) + `dagger.json` (Dagger CI);
`main.go` entrypoint; `*_test.go` tests; README + 17 `.md` files; `.sample`/`.json`
data; binary git artifacts (`.pack`/`.idx`). **Implication**: detectors must handle
nested sub-project manifests, multiple CI providers, binary files, and extensionless
files; primary language detection must be LOC-weighted (lots of `.md` files but Go
is primary by LOC).

### F5 — Determinism is achievable with stdlib only
Walk via `os.walk(followlinks=False)` + realpath-within-root guard; binary
detection via a bounded head sample (NUL byte / decode heuristic); LOC via newline
counting; manifests via `tomllib`/`json`/line parsing. All pure functions of bytes.
**Implication**: no third-party parser dependency; the entire core is unit-testable
without a model or network. Sorting every collection at the analyzer guarantees
byte-identical serialization across runs.

## Architecture Pattern Evaluation

- **Pure-core + stage-adapter** (chosen): scanning/analysis logic in
  `docuharnessx/analysis/`; only the two stage modules know HarnessX. Maximizes
  testability and shields the planner-facing model from harness drift.
- **Logic inside the stage classes** (rejected): couples deterministic logic to the
  HarnessX lifecycle, making the core hard to unit-test and the model harder to
  freeze independently.
- **Third-party scanners (e.g. `linguist`, `tokei`, `tree-sitter`)** (rejected for
  now): violates "core never imports third-party/benchmark libs" and adds
  nondeterminism/version risk; stdlib extension+filename mapping is sufficient and
  fully deterministic for the target.

## Synthesis Outcomes

- **Generalization**: a single `FileInventory` (built once by Ingest) feeds every
  detector, avoiding repeated filesystem walks (Req 1.7) and keeping Analyze pure.
- **Build-vs-adopt**: build the deterministic core on stdlib; adopt nothing new.
- **Simplification**: one frozen aggregate `RepoAnalysis` with nested frozen
  records and a single schema-version authority; the analyzer (not the model) owns
  all sorting, so the model stays a passive value object.
- **Seam stability**: `RepoAnalysis` field names/meanings frozen now; evolution is
  additive (new optional fields + version bump only on frozen-set change), so the
  planner can pin to schema_version 1.

## Risks & Mitigations

- **Over-eager public-surface regex** → keep conservative; omit on doubt (Req 5.3).
- **Large/pathological repos** → `ScanLimits` caps + inherited Control guards
  (Req 2.2, 2.3, 2.5).
- **Harness API drift** (runtime/State access) → confined to the two stage modules;
  the core is HarnessX-free.
- **Seam drift** → `RepoAnalysis` changes are explicit revalidation triggers for
  the planner spec.
