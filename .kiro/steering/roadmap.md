# Roadmap

## Overview

DocuHarnessX is a role-based documentation generator built as a HarnessX bundle
(`make_docgen`) + `dhx` CLI. It reads a target repo and publishes a COBESY-structured,
role-targeted Material for MkDocs site to GitHub Pages. The work decomposes into a
pipeline (Ingest → Analyze → Classify → Plan → Write → Review → Assemble → Deploy)
on top of two foundations (the ontology and the harness skeleton).

## Approach Decision

- **Chosen**: Multi-spec decomposition, built in dependency waves via `/kiro-spec-batch`.
- **Why**: Each pipeline stage has a distinct concern, reviewer profile, and acceptance
  surface (ontology schema vs. repo parsing vs. LLM-judge gating vs. MkDocs assembly).
  Waves keep parallel work conflict-free while respecting hard data dependencies
  (everything reads the ontology; the writer needs the coverage plan; the assembler
  needs reviewed segments).
- **Rejected alternatives**:
  - *Single MVP spec*: would produce a >30-task list mixing harness wiring, prompt
    engineering, and MkDocs theming under one reviewer.
  - *Per-role specs*: roles are a data dimension, not a build boundary — splitting by
    role would duplicate the writer and assembler across nine specs.

## Scope

- **In**: ontology engine, harness bundle skeleton + CLI, repo ingestion/analysis,
  classification + coverage planner (decision intelligence), COBESY writer, LLM-judge
  quality gate, MkDocs site assembler (role views + agendas), GitHub Pages deploy,
  end-to-end validation on `malware_hashes`.
- **Out**: non-MkDocs backends, multi-repo aggregation, hosted SaaS, model-evolution
  (Train) loop, i18n of generated docs.

## Constraints

- **Language/runtime**: Python 3.12; `uv` env; depends on HarnessX as a library.
- **HarnessX rules**: model in `ModelConfig` not `HarnessConfig`; compose with `|`;
  core never imports benchmark libs; append-don't-replace processor hooks.
- **Output contract**: valid Markdown + `mkdocs.yml`; tags namespaced `subject:` /
  `intent:`; segments carry `{roles[], subjects[], intent}` frontmatter.
- **Reproducibility**: deterministic planner; LLM-judge output gated and logged via
  HarnessJournal.

## Boundary Strategy

- **Shared seams to watch**:
  - **Segment frontmatter schema** (owned by `ontology-engine`) is the contract every
    later spec reads/writes. Freeze it early.
  - **Segment store** (where written segments live) is the handoff between writer,
    review gate, and assembler. Keep its interface stable.
  - **Coverage plan** (output of `classification-coverage-planner`) is the writer's input.
  - **`make_docgen` composition** (owned by `harness-bundle-skeleton`) is where every
    stage's processor is registered.

## Specs (dependency order, by wave)

**Wave 0 — Foundations (no dependencies, parallel)** — SPECS GENERATED ✅
- [x] ontology-engine — tri-modal model (Role × Subject × Intent) as a **project-configurable
      Vocabulary** (default profile + `.docuharnessx/ontology.yaml`), segment frontmatter
      schema + validation, tag namespacing, frozen `SegmentStore` port + `vocabulary_to_config`
      serializer. Dependencies: none. _(spec.json: tasks-generated, approved)_
- [x] harness-bundle-skeleton — `make_docgen()` HarnessConfig skeleton, `dhx` CLI +
      `dhx init` (per-project ontology setup), HarnessX wiring (Control/Observe/Journal),
      `uv` packaging. Consumes ontology contract. Dependencies: none. _(spec.json: tasks-generated, approved)_

**Wave 1 — Understand the codebase**
- [ ] repo-ingestion-analysis — scan target repo: structure, languages, entrypoints,
      config, CI, tests, architecture signals. Dependencies: harness-bundle-skeleton.
- [ ] classification-coverage-planner — map analysis onto the ontology; build the
      coverage matrix; decision-intelligence on which segments to generate and in what
      priority. Dependencies: ontology-engine, repo-ingestion-analysis.

**Wave 2 — Generate & gate**
- [ ] cobesy-writer — generate COBESY-structured segments (SCQA opener, Minto lead,
      REDUCE fast path) per role/intent from the coverage plan. Dependencies:
      ontology-engine, classification-coverage-planner.
- [ ] quality-review-gate — LLM-judge (HarnessX Evaluate) enforcing the COBESY
      validation gate (MECE, working-memory fit, role-fit, falsifiability); iterate or
      reject segments. Dependencies: cobesy-writer.

**Wave 3 — Publish**
- [ ] mkdocs-site-assembler — assemble reviewed segments into Material for MkDocs:
      per-role landing pages + guided agendas, tags-driven nav, cross-links, content
      tabs/admonitions. Dependencies: ontology-engine, quality-review-gate.
- [ ] github-pages-deploy — GitHub Actions + `mkdocs gh-deploy`; `mike` versioning.
      Dependencies: mkdocs-site-assembler.

**Wave 4 — Validate end-to-end**
- [ ] e2e-malware-hashes — run the full pipeline against `/home/mc/Source/malware_hashes`,
      verify a published role-based site and COBESY adoption paths. Dependencies: all above.

## Implementation Status

- **Wave 0 — IMPLEMENTED & MERGED to `main`** (2026-06-21). Both specs complete,
  reviewer-gated, adversarial GO/NO-GO passed. 428 tests green. `dhx <repo> --out DIR`
  runs the empty 8-stage pipeline with a HarnessJournal trace; `dhx init` writes
  `.docuharnessx/ontology.yaml`. The 8 stage modules are no-op stubs awaiting Wave 1+.
- **Waves 1–4 — specs not yet generated.**

## Next Step

Run `/kiro-spec-batch` to create requirements/design/tasks for **Wave 1**
(`repo-ingestion-analysis`, `classification-coverage-planner`), then implement and
proceed wave by wave. Each later wave replaces stage stubs in `docuharnessx/stages/`
one at a time.
