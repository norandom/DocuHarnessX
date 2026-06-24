# Brief — agentic-codebase-writer

## Feature

Replace the cobesy-writer's **content-free single-shot prose step** with a **bounded,
HarnessX-agentic, codebase-grounded writer**: per planned segment, run a real HarnessX
agent (tools + Workspace + Control) that *explores the target repository*, grounds its
prose in actual source, and emits a substantive, **cited**, **Mermaid-diagrammed**,
COBESY-structured `Segment`. This unlocks the project's latent HarnessX power so the
output is something a static-site generator (Hugo, etc.) cannot produce: AI-generated,
repo-grounded, diagram-rich documentation. deepwiki-open is the quality bar.

## Why It Exists

DocuHarnessX 1.0 produces meager boilerplate. The writer issues one
`model.complete(messages, tools=[])` call whose prompt **deliberately excludes file
contents** (`composition/prompt.py`: "invent no repository facts"; evidence = file
paths only), so the model cannot read the repo and emits generic skeleton text — which
the review gate correctly rejects, leaving an empty site. Meanwhile HarnessX's entire
value (agentic tool-loop, Workspace, Context/Memory/Compaction, Control budgets) sits
unused. HarnessX has **no built-in codebase RAG** — codebase context is *agentic* (the
model reads via `Read`/`Grep`/`Glob`/`Bash`). This spec uses that machinery as intended.

## In Scope

- **Replace `docuharnessx/stages/write.py` IN PLACE** (stable STAGE_NAME='write',
  WriteStage, make_write_stage, module path — registry/bundle untouched: single-stage swap).
- **Agentic generation per planned segment**: build a `HarnessConfig` from HarnessX
  bundles (`context | window_mgmt`) + a tool registry (`build_default_tools()` →
  read/grep/glob/bash), bound to the run's model via the existing model seam, with a
  `Workspace` rooted **read-only** at the target repo; run `Harness.run(BaseTask(...))`
  with a task prompt that:
  - scopes exploration to the segment's `PlannedSegment.evidence` files + subjects
    (start there, read real source, expand as needed),
  - follows the COBESY structure (SCQA opener → Minto lead → working-memory chunks →
    REDUCE fast path) from the existing blueprint,
  - emits **Mermaid diagrams** grounded in the code (deepwiki rules: `graph TD`/
    `sequenceDiagram`/`classDiagram`/`erDiagram`, vertical orientation, short nodes,
    valid arrow grammar), and
  - **cites real `file:line` sources** (deepwiki rule: cite ≥N source files) so prose
    stays grounded and specific.
  Produce a valid ontology `Segment` (body = grounded Markdown incl. Mermaid fences;
  title/summary; roles/intent/subjects from the plan) into the `SegmentStore` + the
  frozen `WrittenSegments` seam.
- **Bounded by Control** (the old "bounded" objective, HarnessX-native): cap each
  segment's agentic run with cost-guard + step/token budget + loop-detection so cost is
  capped (no runaway loops). Surface per-segment cost/steps in the bounded journal.
- **Mermaid rendering**: ensure the assembler's `mkdocs.yml` enables Material's
  `pymdownx.superfences` mermaid custom fence (small coordinated change so emitted
  diagrams render). Keep the change minimal/idempotent.
- **Reuse the existing COBESY blueprint** (`composition/blueprint.py`) to seed the
  agent's structure prompt — do not discard the deterministic structure work; the
  agentic loop fills it with grounded content + diagrams instead of placeholder text.

## Grounded in the Old Spec — Preserve / Change / Reconcile

- **PRESERVE**: the frozen `Segment` schema and `WrittenSegments` (`SLOT_WRITTEN_SEGMENTS`)
  seam (so quality-review-gate, mkdocs-site-assembler, github-pages-deploy are
  unchanged); CoveragePlan consumption; configurable ontology (Role×Intent×Subject);
  COBESY structure; per-project behavior; single-stage swap; the deterministic
  blueprint/wiring/fallback for structure + metadata.
- **CHANGE**: the prose step — from one content-free `complete()` to a bounded agentic
  `Harness.run()` with tools + a repo-rooted Workspace, producing grounded, cited,
  diagrammed bodies.
- **RECONCILE the "deterministic / bounded single-shot" objective**: the agentic loop is
  inherently non-deterministic, so determinism shifts to the *orchestration*
  (blueprint, wiring, segment assembly, bounded budgets) while the model's prose is
  model-dependent. The bounded guarantee is kept via Control (max steps/cost). The
  fallback path remains: on agent failure/timeout/empty, fall back to the deterministic
  body so a run never crashes and stays usable.

## Credential-Free Testability (critical)

The old writer was credential-free via a fake provider returning canned content. An
agentic loop calls tools, so tests need a **scripted fake provider** that emits a
deterministic sequence of tool-calls (read these files) then a final grounded body +
Mermaid, exercising the real run loop + real tools over a crafted fixture repo — with
NO network/credentials. Design must define this fake-agent harness so the full pipeline
(write → review → assemble → build) stays testable offline. The review gate's accept
path must be reachable with the fake (so the site is non-empty in tests).

## Out of Scope (separate follow-ups, keep this spec focused — avoid code explosion)

- Subject scoping in the planner (pages tagged with all components) — planner concern.
- Home/index landing page — assembler concern.
- Review-gate recalibration (threshold / k-of-n) — review concern (revisit after the
  writer produces real content).
- A custom embedding/RAG/vector index — explicitly NOT built; HarnessX is agentic-by-tools.

## Dependencies

- `cobesy-writer` (replaced in place; reuses its blueprint), `classification-coverage-planner`
  (CoveragePlan/evidence), `repo-ingestion-analysis` (RepoAnalysis), `ontology-engine`
  (Segment/SegmentStore), `harness-bundle-skeleton` (RunContext, bundle, model seam,
  Control). HarnessX: `build_default_tools`, `Workspace`, `bundles.context/window_mgmt`,
  `bundles.control` (make_control), `Harness.run`/`BaseTask`.

## Key Constraints

- Python 3.12; HarnessX-native (real `Harness.run` with tools + read-only Workspace on
  the target repo); **bounded** per-segment cost via Control; **credential-free
  testable** via a scripted fake provider; produces the **same frozen Segment /
  WrittenSegments seam**; single-stage swap (registry/bundle untouched); deterministic
  fallback retained.

## Acceptance Signal

Running the pipeline (with a scripted fake agent in tests; a real model in production)
produces, per planned segment, a `Segment` whose body is **grounded in real repo source
with `file:line` citations and at least one valid Mermaid diagram**, COBESY-structured,
within the per-segment Control budget — and the assembled Material site renders the
diagrams. On the reference targets (malware_hashes, etc.) the result is visibly richer
than a static-site generator's output (real architecture/flow diagrams + cited prose),
not boilerplate. Credential-free e2e stays green; existing seams/tests unaffected.
