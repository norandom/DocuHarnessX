# Requirements Document

## Introduction

DocuHarnessX ships its eight pipeline stages as no-op stubs (Wave 0). This spec
makes the **Ingest** and **Analyze** stages real: they scan a target software
project (target size 25–40k LOC, polyglot) and produce a structured,
deterministic **RepoAnalysis**. The Ingest stage walks the target repository's
filesystem (rooted at the `SLOT_TARGET_REPO` path) and produces a bounded,
classified inventory of files; the Analyze stage turns that inventory into the
`RepoAnalysis` model — languages and LOC, directory/file structure, entrypoints,
build/config files, CI workflows, test presence and layout, declared
dependencies, a component/module map, public surface signals, documentation
presence, and notable artifacts — and writes it into the run context at a new
`SLOT_REPO_ANALYSIS` slot.

`RepoAnalysis` is the **frozen seam** the downstream
`classification-coverage-planner` (Wave 1, spec #2) consumes to decide which
documentation segments a project needs. The scanning core is deterministic and
unit-testable without any model; any LLM-based enrichment (e.g. a narrative
architecture summary) is OPTIONAL, gated, and never required for the core
analysis. The whole scan runs inside the existing HarnessX Control cost/loop
guards composed by `make_docgen`, and records its participation in the
HarnessJournal.

## Boundary Context

- **In scope**: a deterministic filesystem scan + lightweight parse of the target
  repo; the serializable `RepoAnalysis` data model; the append-only
  `SLOT_REPO_ANALYSIS` slot key; replacing the `ingest.py` and `analyze.py` no-op
  stage stubs with real `Processor` stages registered on the existing
  `PIPELINE_HOOK` in canonical order; robustness on large/polyglot/edge-case
  repos; optional gated LLM enrichment that augments but never gates the core
  analysis.
- **Out of scope**: mapping the analysis onto the ontology or deciding what to
  document (owned by `classification-coverage-planner`); writing doc content,
  review, assembly, deploy; deep/semantic source parsing or call-graph
  construction; multi-repo aggregation; remote/VCS fetching (the repo is already
  on local disk at `SLOT_TARGET_REPO`).
- **Adjacent expectations**: the `RunContext`, slot-key constants, the stage
  base/registry contract, and `make_docgen` are owned by `harness-bundle-skeleton`
  and are extended append-only (the new slot key is ADDED to `types.py`; the two
  stage stub modules are REPLACED in place, one at a time, without editing the
  registry ordering or the bundle entry point). The scan is ontology-agnostic and
  does NOT depend on `ontology-engine` for the raw analysis. The downstream
  planner consumes `RepoAnalysis` exactly as frozen here.

## Requirements

### Requirement 1: Target repository filesystem ingestion

**Objective:** As the doc-generation pipeline, I want the Ingest stage to walk
the target repository and build a bounded, classified file inventory, so that the
Analyze stage has a deterministic, repo-shaped input without re-reading the
filesystem.

#### Acceptance Criteria

1. When the Ingest stage runs, the system shall read the target-repository path
   from the run context (`SLOT_TARGET_REPO`) and walk that directory tree to
   enumerate files.
2. If the target-repository slot is unset or the path does not exist or is not a
   directory, then the system shall raise an explicit, identifiable error naming
   the missing/invalid path and shall not produce a partial inventory.
3. When walking the tree, the system shall record, for each retained file, its
   repo-relative POSIX path, size in bytes, a binary-vs-text classification, and a
   detected language/file-type tag.
4. While walking, the system shall exclude common non-source noise directories
   (e.g. `.git`, `node_modules`, `vendor`, `.venv`, `__pycache__`, build/output
   directories) and shall not descend into them.
5. While walking, the system shall not follow symbolic links out of the
   repository root and shall skip entries it cannot read, recording each skipped
   entry rather than aborting the walk.
6. The system shall produce a file inventory whose entry ordering is stable
   (deterministically sorted) so that two runs over an unchanged repo yield
   byte-identical inventories.
7. The system shall make the file inventory available to the Analyze stage
   through the run context (not via globals or re-walking the filesystem).

### Requirement 2: Bounded scanning for large and polyglot repositories

**Objective:** As an operator running the pipeline on a 25–40k LOC repo, I want
the scan to stay bounded and resilient, so that a large or unusual repository
does not exhaust resources or crash the run.

#### Acceptance Criteria

1. The system shall classify a file as binary (and skip line/content parsing of
   it) when its content sampling indicates non-text data.
2. Where a file exceeds a configurable maximum-read-size threshold, the system
   shall record the file in the inventory but shall not read its full contents for
   line counting or parsing.
3. Where the total number of files or total scanned bytes exceeds configurable
   limits, the system shall stop adding further detail, record that a scan limit
   was reached, and still emit a well-formed `RepoAnalysis`.
4. When the scan encounters empty directories, zero-byte files, files without
   extensions, or unknown file types, the system shall handle them without error
   and classify them as a recognized "unknown/other" category.
5. While scanning, the system shall operate within the run's existing Control
   cost/loop guards and shall not require any additional network access.

### Requirement 3: Language and lines-of-code detection

**Objective:** As the planner, I want a deterministic per-language LOC and file
breakdown, so that I can reason about the project's primary languages and size.

#### Acceptance Criteria

1. When analyzing the inventory, the system shall map each text file to a language
   using a deterministic, extension-and-filename-based rule set.
2. The system shall compute, per detected language, the number of files and the
   total lines of code across those files.
3. The system shall identify the primary language(s) as the language(s) with the
   greatest LOC and expose the per-language breakdown in `RepoAnalysis`.
4. When a file's language cannot be determined, the system shall attribute it to
   an "unknown/other" language bucket rather than dropping it from the totals.
5. The system shall produce identical language/LOC results across repeated runs
   over an unchanged repository.

### Requirement 4: Structure, entrypoints, build/config, CI, and tests detection

**Objective:** As the planner, I want the project's structure, entrypoints,
build/configuration files, CI workflows, and test layout identified, so that I
can decide which install/operate/contribute documentation is warranted.

#### Acceptance Criteria

1. When analyzing the repository, the system shall produce a directory/structure
   summary (top-level directories and their dominant role/contents) capturing the
   repository's module layout.
2. The system shall detect entrypoints using deterministic signals appropriate to
   the detected languages (e.g. `main.go`, `__main__.py`, `cli.py`, `bin/`
   scripts, `[project.scripts]` console entries, `package.json` `bin`/`main`).
3. The system shall detect and classify build/config files (e.g. `pyproject.toml`,
   `go.mod`, `package.json`, `Makefile`, `Dockerfile`, lockfiles) including those
   nested in sub-projects, recording each with its repo-relative path and kind.
4. The system shall detect CI/workflow configuration (e.g. `.github/workflows/*`,
   and other recognized CI/pipeline config) and record the detected CI providers
   and workflow file paths.
5. The system shall detect test presence and layout (recognized test files,
   directories, and frameworks per detected language) and record whether tests are
   present and where they live.
6. Where a detection category has no matches in the repository, the system shall
   record that category as empty rather than omitting it, so the model shape is
   stable.

### Requirement 5: Dependencies, component map, public surface, docs, and artifacts

**Objective:** As the planner, I want declared dependencies, a component/module
map, cheaply-detectable public surface, documentation presence, and notable
artifacts captured, so that I can target reference, integration, and
extend-oriented documentation.

#### Acceptance Criteria

1. When a recognized manifest is present, the system shall extract declared
   dependencies from it (e.g. `pyproject.toml`/`requirements*.txt`, `go.mod`,
   `package.json`) and record them with their source manifest.
2. The system shall produce a component/module map — named units derived from the
   directory/package structure — each with its repo-relative path and a small set
   of representative files.
3. The system shall capture cheaply-detectable public surface signals (e.g. CLI
   flags/sub-commands and exported/public symbols) only where they are obtainable
   by lightweight parsing, and shall omit signals that would require deep semantic
   analysis.
4. The system shall record documentation presence (README, `docs/` directories,
   and other recognized documentation files) with their repo-relative paths.
5. The system shall record notable artifacts (e.g. license files, container
   images/Dockerfiles, schema/spec files, generated-output markers) it detects by
   filename/pattern.
6. When a recognized manifest is malformed or only partially parseable, the system
   shall record what it could extract, mark the manifest as partially parsed, and
   continue without aborting the analysis.

### Requirement 6: RepoAnalysis data model as a frozen, serializable seam

**Objective:** As the downstream `classification-coverage-planner`, I want a
stable, serializable `RepoAnalysis` contract, so that I can consume the analysis
without being broken by internal scan changes.

#### Acceptance Criteria

1. The system shall define a `RepoAnalysis` value type that aggregates the
   language/LOC breakdown, structure summary, entrypoints, build/config files, CI
   workflows, test layout, declared dependencies, component/module map, public
   surface, documentation presence, and notable artifacts.
2. The `RepoAnalysis` type and its nested record types shall be immutable
   (frozen) value objects so consumers cannot mutate shared analysis state.
3. The system shall carry an explicit `RepoAnalysis` schema-version identifier so
   downstream consumers can detect contract changes.
4. The system shall provide deterministic serialization of `RepoAnalysis` to a
   plain, ordered, JSON-compatible structure such that two runs over an unchanged
   repository serialize to byte-identical output.
5. The system shall provide a corresponding deserialization that reconstructs an
   equal `RepoAnalysis` from its serialized form (round-trip equality).
6. When the model is extended in a future version, the system shall keep existing
   field names and meanings stable (additive evolution), changing the schema
   version only when the frozen field set changes.

### Requirement 7: RunContext output seam (SLOT_REPO_ANALYSIS, append-only)

**Objective:** As a downstream stage, I want the analysis published at a known
run-context slot, so that I can read it through the typed `RunContext` surface
exactly as other stages read their inputs.

#### Acceptance Criteria

1. The system shall define a new slot-key constant `SLOT_REPO_ANALYSIS` and shall
   add it to `docuharnessx/types.py` append-only, without altering or removing any
   existing slot-key constant, `StageName`, or `STAGE_NAMES` entry.
2. When the Analyze stage completes its scan, the system shall write the produced
   `RepoAnalysis` into the run context at `SLOT_REPO_ANALYSIS`.
3. The system shall provide a typed `RunContext` accessor pair
   (set/get) for the `RepoAnalysis` slot consistent with the existing `RunContext`
   accessor style, returning `None` when the slot is unset.
4. When `SLOT_REPO_ANALYSIS` is read before the Analyze stage has run, the system
   shall return `None` (explicit unset) rather than raising.
5. The system shall not change the signatures or behavior of any existing
   `RunContext` accessor.

### Requirement 8: Stage replacement preserving the harness contract

**Objective:** As the harness maintainer, I want the real Ingest and Analyze
stages to drop into the existing pipeline without disturbing the other stages, so
that the single-stage-replaceability contract is honored.

#### Acceptance Criteria

1. The system shall replace the no-op stub bodies in
   `docuharnessx/stages/ingest.py` and `docuharnessx/stages/analyze.py` with real
   processors, keeping the module paths, the `IngestStage`/`AnalyzeStage` class
   names, the `make_ingest_stage`/`make_analyze_stage` factories, and the
   `STAGE_NAME` constants stable so the stage registry and `make_docgen` need no
   edits.
2. The system shall register the real stages on the existing `PIPELINE_HOOK` and
   preserve the canonical pipeline order ingest → analyze → … → deploy
   (append-don't-replace; the six other stages remain untouched no-op stubs).
3. While running, each real stage shall record its participation in the
   HarnessJournal as the no-op stages did, so the run trace still shows ingest and
   analyze participating.
4. When the Ingest or Analyze stage raises a scan error, the system shall surface
   it as an identifiable stage-scoped error that halts the run with a clear cause,
   rather than silently producing an empty or partial `RepoAnalysis`.
5. The real stages shall not import or require any model binding; the core scan
   shall run with no model present.

### Requirement 9: Deterministic core with optional gated LLM enrichment

**Objective:** As a maintainer who must trust and test the analysis, I want the
core analysis to be deterministic and model-free while any LLM enrichment is
strictly optional, so that the pipeline is reproducible and unit-testable.

#### Acceptance Criteria

1. The system shall compute the entire core `RepoAnalysis` (Requirements 3–5)
   deterministically from the filesystem inventory with no model, no network, and
   no nondeterministic ordering.
2. The system shall be unit-testable against crafted fixtures and against the
   reference repository, producing identical results across repeated runs.
3. Where LLM-based enrichment is enabled, the system shall add enrichment (e.g. a
   narrative architecture summary) into a clearly separated, optional region of
   `RepoAnalysis` without altering any deterministic core field.
4. While LLM enrichment is disabled (the default), the system shall still produce
   a complete, well-formed core `RepoAnalysis`, and the absence of enrichment
   shall not be treated as an error.
5. When LLM enrichment is enabled but fails or times out, the system shall log the
   failure, omit the enrichment region, and still emit the complete deterministic
   core analysis.

### Requirement 10: Observability and journaling

**Objective:** As an operator auditing a run, I want the ingest/analyze work
recorded, so that I can see what was scanned and the analysis summary.

#### Acceptance Criteria

1. When the Ingest and Analyze stages run, the system shall record their
   participation and a concise scan summary (e.g. file count, primary language,
   whether a scan limit was reached, whether enrichment ran) in the HarnessJournal.
2. While scanning, the system shall record skipped/unreadable entries and any
   scan-limit events so they are auditable after the run.
3. The system shall not write the full file inventory into the journal trace
   (only summary-level fields), to keep the trace bounded for large repos.
