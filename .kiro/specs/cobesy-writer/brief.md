# Brief — cobesy-writer

## Feature

Make the **Write** pipeline stage real: turn each `PlannedSegment` in the
`CoveragePlan` into a written, COBESY-structured content **Segment** (filling the
`title`/`summary`/`body` the planner deliberately left blank). This is Wave 2,
spec #1 — the first stage that produces actual documentation prose, and the first
to make real LLM calls.

## Why It Exists

Replaces the `write` no-op stub. The planner decided *what* to document (roles ×
intent × subjects + evidence); the writer produces the human-facing content for
each planned segment, structured so time-poor readers reach first success fast.

## In Scope

- Replace `docuharnessx/stages/write.py` no-op stub IN PLACE (keep STAGE_NAME,
  WriteStage class, factory, module path stable — registry/bundle untouched).
- Consume (verbatim, do not reimplement): the frozen `CoveragePlan` (v1) from
  `SLOT_COVERAGE_PLAN`, the `RepoAnalysis` (v1) from `SLOT_REPO_ANALYSIS` for
  evidence/source grounding, the loaded `Vocabulary`, and the ontology `Segment`
  schema + `SegmentStore` (`RunContext.segment_store()`).
- For each `PlannedSegment`, produce a valid ontology `Segment` (id/title/roles/
  subjects/intent/summary/related from the plan; **body** newly written) and put it
  in the segment store; surface the written set via a new `SLOT_WRITTEN_SEGMENTS`
  (append-only addition to `types.py` + a `RunContext` accessor) for the review gate.
- **COBESY structure** (apply the `cobesy` skill's composition back-end): build a
  deterministic per-segment **composition blueprint** (SCQA opener tuned to the
  segment's role(s)+intent, Minto lead-with-conclusion, working-memory chunking,
  REDUCE-barrier fast path, andragogy for expert roles), then render a Markdown
  `body` that honors it. The body must be grounded in the segment's evidence refs.
- **Deterministic core / gated model split**: the blueprint construction + prompt
  assembly + segment wiring is deterministic and unit-testable WITHOUT a model; the
  prose generation is the only model-dependent step. The model is the harness-bound
  model (the writer runs within `make_docgen`'s harness / a model call per segment);
  apply the inherited Control cost/step budgets.
- Validate each produced `Segment` against the `Vocabulary` (reuse ontology
  validation + tagging); skip/flag invalid plans deterministically.

## Out of Scope

- Judging/quality-gating the prose (quality-review-gate, Wave 2 spec #2).
- MkDocs assembly / deploy. Generating the `CoveragePlan` (planner) or `RepoAnalysis`.

## Dependencies

- `classification-coverage-planner` — `CoveragePlan`/`PlannedSegment` (v1, consume verbatim).
- `repo-ingestion-analysis` — `RepoAnalysis` (evidence grounding).
- `ontology-engine` — `Segment` schema, validation, tagging, `SegmentStore`.
- `harness-bundle-skeleton` — `RunContext`, slots, stage base/registry, the bound model.

## Key Constraints

- Python 3.12. Deterministic blueprint/wiring core (unit-testable, no model). LLM
  prose step must be **credential-free testable** via a fake/recorded provider
  (assert structure + wiring + validity, NOT exact prose). Honor the configurable
  vocabulary. The written `Segment` set is the seam the review gate consumes.

## Acceptance Signal

Given a `CoveragePlan` + `RepoAnalysis` + `Vocabulary` and a fake model, the Write
stage produces one valid, COBESY-structured `Segment` per planned segment into the
store, surfaced via `SLOT_WRITTEN_SEGMENTS`, recorded in the journal; deterministic
blueprint verified by unit tests; runs credential-free end-to-end.
