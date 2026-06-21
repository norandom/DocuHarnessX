# Brief — harness-bundle-skeleton

## Feature

The runnable skeleton of DocuHarnessX as a real HarnessX bundle: `make_docgen()`
returning a composed `HarnessConfig`, the `dhx` CLI entry point, HarnessX wiring
(Control + Observe/Journal), and `uv` packaging. This is Wave 0 foundation #2 — the
chassis every later pipeline stage plugs its processor into.

## Why It Exists

The user's locked decision is to build on HarnessX *for real*, not inspired-by. Every
later spec (ingestion, classifier, writer, review gate, assembler, deploy) is a
processor or processor group registered into `make_docgen`. That composition point and
the run lifecycle must exist and be runnable first.

## In Scope

- **Package scaffold**: `docuharnessx/` package, `pyproject.toml`, `uv` env, depends on
  `harnessx`. Stage sub-packages stubbed (`ingest/ analyze/ classify/ plan/ write/
  review/ assemble/ deploy/`).
- **`make_docgen()`**: compose a `HarnessConfig` using the HarnessX builder (`|`),
  including baseline Control (cost guard, loop detection for 25–40k LOC repos) and
  Observe (HarnessJournal JSONL traces). No model in `HarnessConfig`.
- **Model binding**: `ModelConfig(main=...).agentic(make_docgen())` pattern; resolve
  model from config/env per HarnessX conventions.
- **`dhx` CLI**: entry point `dhx <target-repo> [--out DIR] [--config YAML]`; wires the
  target repo path into harness state/slots; runs the pipeline; writes a run journal.
- **Pipeline contract**: define how stages register (hook points / processor order) and
  how they pass data (harness state/slots + the segment store interface from
  `ontology-engine`). Provide a no-op end-to-end run that exercises the empty pipeline.
- **Config surface**: target repo path, output dir, role selection (default all 10),
  model selection, cost/step budgets.

## Out of Scope

- Actual repo scanning, classification, writing, review, assembly, deploy — those are
  later specs. Here the stages are registered stubs/no-ops.
- The ontology/segment schema itself (consumed from `ontology-engine`).

## Dependencies

None for skeleton wiring (Wave 0). Consumes the segment store *interface* from
`ontology-engine` at the contract level; coordinate the interface, do not reimplement it.

## Key Constraints

- HarnessX rules: model in `ModelConfig` not `HarnessConfig`; compose with `|` (rely on
  conflict detection); append-don't-replace processor hooks; core never imports
  benchmark libs.
- Python 3.12; `uv` packaging matching HarnessX.
- A no-op `dhx` run must succeed and produce a HarnessJournal trace.

## Acceptance Signal

`dhx /home/mc/Source/malware_hashes --out /tmp/out` runs the empty pipeline end-to-end,
emits a HarnessJournal JSONL trace, exits cleanly, and exposes registration points where
Wave 1+ stages attach.
