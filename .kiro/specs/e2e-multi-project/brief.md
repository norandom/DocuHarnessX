# Brief — e2e-multi-project

## Feature

The final end-to-end validation: prove `dhx` generates a correct, publishable,
**per-project** Material for MkDocs site for **arbitrary** software projects —
across multiple languages, ecosystems, and project shapes, not just malware_hashes.
Wave 4. This generalizes the roadmap's `e2e-malware-hashes` (malware_hashes becomes
one representative case among several).

## Why It Exists

Every pipeline stage is built (Waves 0–3). This wave validates the whole thing
working together on real, diverse projects and locks in that generality is a
permanent, tested property — guarding against any example-specific assumption
creeping back in.

## In Scope

- **Hermetic, credential-free e2e test suite** (`tests/test_e2e_multi_project.py`):
  small CRAFTED fixture repos of different types (at least Go, Python, JS/Node) that
  the test runs the FULL `dhx` pipeline against (ingest → analyze → classify → plan →
  write → review → assemble → deploy in emit-ci-workflow/build-only mode), with a fake
  model (no network/credentials). Per-fixture assertions: correct languages detected,
  a project-specific `CoveragePlan`, written + reviewed segments, an assembled site
  whose `mkdocs.yml` carries the per-target `/<repo>/` base-path, `mkdocs build`
  succeeds, the CI workflow is emitted, exit 0. Plus a cross-fixture assertion that
  different project types yield genuinely different plans/sites (not a template), and
  a guard that no example-specific (malware_hashes/Go-only) assumption is required.
- **One-off real-repo validation** (this session, evidence not a CI test): run the
  full pipeline against the representative real targets — malware_hashes (Go),
  DocuHarnessX itself (Python dogfood), pallets/click (Python), expressjs/express
  (JS), BurntSushi/ripgrep (Rust) — each into a throwaway copy/out dir, credential-free,
  asserting a correct per-project site builds with the right base-path. Capture a
  generalization report.

## Out of Scope

- New pipeline features (all built). Pushing to real remotes (gh-deploy push is never run).

## Dependencies

- All prior specs (the full Wave 0–3 pipeline).

## Key Constraints

- Persistent tests MUST be hermetic + credential-free (crafted fixtures + fake model;
  do NOT depend on the external clones or network in the suite). The real-repo
  validation is a one-off run this session against the pre-cloned targets at
  `/tmp/dhx_targets/{click,express,ripgrep}` + local malware_hashes + DocuHarnessX.
  Run `dhx` via the programmatic path with a fake provider (never the bare console
  script, which would hit the real model resolver). Use throwaway copies so no real
  repo is mutated.

## Acceptance Signal

The hermetic multi-language e2e suite passes (full `dhx` pipeline → buildable
per-project site for Go/Python/JS fixtures, project-specific output, correct
base-paths), the full suite stays green, AND the one-off run produces a correct,
buildable site for all five real targets — demonstrating DocuHarnessX works for any
project, with malware_hashes as just one example.
