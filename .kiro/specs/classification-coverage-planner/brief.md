# Brief — classification-coverage-planner

## Feature

Make the **Classify + Plan** pipeline stages real. Consume the `RepoAnalysis` (from
repo-ingestion-analysis) plus the loaded project `Vocabulary`, map findings onto the
tri-modal ontology, and produce a prioritized **CoveragePlan**: which content
segments the project needs (Role × Intent × Subject) and in what order — using
decision intelligence, not a fixed template. This is Wave 1, spec #2.

## Why It Exists

Replaces the `classify.py` and `plan.py` no-op stubs. It is the decision-intelligence
core: given what the repo IS (RepoAnalysis) and who reads it (the configured roles)
and why (intents), decide WHAT to document and prioritize it, so the Wave 2 writer
generates the right segments rather than a generic dump.

## In Scope

- Replace `docuharnessx/stages/classify.py` and `docuharnessx/stages/plan.py` no-op
  stubs with real stage processors on `PIPELINE_HOOK` (canonical order; append-don't-replace).
- **Classification**: map RepoAnalysis features onto ontology Subjects (typed prefixes
  `component:`/`tech:`/`artifact:`/`topic:`), and determine the relevant Role×Intent
  cells for this project (e.g. a CLI tool → install/use/troubleshoot for Tech-savvy
  User, evaluate for Manager; a security/forensics tool → Security/Compliance segments).
- **Coverage planning (decision intelligence)**: build a coverage matrix over the
  loaded `Vocabulary` (roles × intents), score/prioritize cells by evidence in the
  analysis, and emit a **CoveragePlan** = an ordered list of planned segments, each
  with `{roles[], subjects[], intent, evidence/source refs, priority}` keyed to the
  segment schema so the writer can fill them.
- **Output seam**: write `CoveragePlan` into a new `RunContext` slot (e.g.
  `SLOT_COVERAGE_PLAN`); add the slot key to `docuharnessx/types.py` **append-only**.
- Deterministic planning core (heuristics testable without a model). Any LLM-based
  relevance judgement must be OPTIONAL and gated.
- Reuse ontology-engine APIs (`Vocabulary`, `Subject`, intents/roles, tag emission,
  segment schema) — do NOT reimplement them.

## Out of Scope

- Generating segment content (cobesy-writer), review gate, MkDocs assembly, deploy.
- The raw repo scan (repo-ingestion-analysis owns `RepoAnalysis`).

## Dependencies

- `ontology-engine` — `Vocabulary`, `Subject`, segment schema, tagging.
- `repo-ingestion-analysis` — the `RepoAnalysis` model + `SLOT_REPO_ANALYSIS` (consume; don't reimplement).
- `harness-bundle-skeleton` — `RunContext`, slot keys, stage base/registry.

## Key Constraints

- Python 3.12; deterministic + unit-testable planner; `CoveragePlan` is the frozen
  seam the Wave 2 writer consumes — design for stability. Vocabulary is project-
  configurable, so planning must adapt to whatever roles/intents/subjects are loaded.

## Acceptance Signal

Given a `RepoAnalysis` + a `Vocabulary`, the planner produces a deterministic,
prioritized `CoveragePlan` (segments with roles/subjects/intent + evidence) into the
run context, recorded in the journal; covered by unit tests over crafted analyses and
multiple vocabularies (default + custom), proving project-specific, not templated, output.
