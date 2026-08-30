# Brief: explore-first-simplification

## Problem

The project owner (a developer using DocuHarnessX as a pet documentation generator) needs docs that help someone understand a codebase. Today the generator emits pages that restate its own planning prompts. Reading the source is more useful than reading the site. That makes the product fail its original job: help developers, not pretty-print outlines.

## Current State

Waves 0–4 shipped an 8-stage HarnessX bundle. The outer run is a dummy agent told to reply `DONE` and call no tools. Processors on `step_end` then:

- scan the repo into a `RepoAnalysis`
- activate Role × Intent cells
- fill a COBESY blueprint with Mad-lib sentences (`This page documents {subject}.`, `Locate {subject}.`, `Run the smallest action…`)
- optionally nest a second HarnessX agent that is instructed to honor that blueprint exactly
- on any agent miss, **publish the blueprint as the page**
- judge COBESY form, assemble per-role MkDocs, deploy

The inner agent *can* read the repo. The authoring model decides the page before that happens. Tests pin the template dump as correct. ~23k lines of product and ~48k lines of tests protect the wrong center.

## Desired Outcome

A smaller generator that:

1. Inspects the repository first.
2. Plans a bounded set of **software questions** (how it starts, what a component does, where config lives, how to extend it).
3. Writes each page with a real explore-then-write agent given the question and evidence files — not pre-written answer sentences.
4. **Omits** any page the agent did not ground in source. Missing pages plus a run report beat a site full of outlines.
5. Assembles only accepted pages into a wiki-style site organised by those questions, not by reader job titles.

The operator still runs `dhx <repo> --out DIR` and gets a previewable site, or an honest empty site with a report.

## Approach

**Chosen: invert the author, keep the inner agent, drop the dummy pipeline bus.**

- Ordinary Python pipeline: analyze → questions → write → gate → assemble → (optional) deploy.
- HarnessX is used only as the per-page writer (read-only workspace, read/grep/glob/bash, bounded steps/cost).
- `RepoAnalysis` stays as the signal source for questions.
- MkDocs emit stays, without per-role landing pages.
- Publishable fallback, Role × Intent as the page unit, and COBESY-as-outline are removed.

Rejected alternatives:

- *Tune prompts / raise budgets on the current pipeline* — the blueprint is still the document; exploration stays decoration.
- *Multi-spec rewrite of planner, writer, review, bundle, assembler separately* — that is how the current overbuild happened; one reduction spec keeps the invert coherent.
- *Throw away HarnessX* — the inner writer is the right tool; the dummy outer harness is not.

## Scope

- **In**:
  - Replace the dummy outer run with a Python documentation pipeline.
  - Replace Role × Intent coverage with a bounded question plan derived from analysis.
  - Replace explore-optional writing + publishable fallback with explore-first writing + fail-closed omission.
  - Replace the COBESY form judge as the publish gate with a substance gate (grounded citations, real symbols, no template-phrase pages).
  - Assemble a question-organised MkDocs site from accepted pages only.
  - Operator-visible run report (planned / accepted / omitted + reasons).
  - Delete or stop shipping the retired authoring path and the tests that pin template dumps.
  - Align steering (`product.md`, `tech.md`, `structure.md`) with explore-first developer docs.
- **Out**:
  - Hosted SaaS, multi-repo aggregation, non-MkDocs backends.
  - Retraining / evolving the generator (Train dimension).
  - Rewriting HarnessX itself.
  - MCP refine server (`docuharnessx-mcp-refine`) — may break; follow-up spec.
  - Deep semantic/AST analysis or a vector index (agentic reads remain the grounding method).
  - Per-role adoption campaigns, SCQA/Minto/REDUCE as required page structure.

## Boundary Candidates

- **Pipeline runner** — drives analyze → questions → write → gate → assemble; not an agent loop.
- **Question planner** — `RepoAnalysis` → bounded software questions + evidence files.
- **Explore-first writer** — one bounded HarnessX agent per question; body or omission.
- **Substance gate** — accept / omit a body; never invent a replacement body.
- **Site assembler** — accepted pages → MkDocs tree; no role views.
- **Run report** — counts and omission reasons for the operator.

## Out of Boundary

- HarnessX runtime internals (providers, workspace, control bundles) except how this project *calls* them.
- GitHub Pages deploy modes already shipped (`build-only`, `emit-ci-workflow`, `gh-deploy`) — keep as an optional last step, do not redesign hosting.
- Material for MkDocs theming beyond dropping role-nav.
- The MCP refine surface.

## Upstream / Downstream

- **Upstream**: `repo-ingestion-analysis` (`RepoAnalysis`), inner writer harness factory + `AgenticProseRunner`, model resolver (native OpenAI tool-calling), MkDocs assembler identity/theme, CLI `dhx`.
- **Downstream**: future MCP refine (must consume the new page + rewrite entry), any GitHub Pages workflow that reads `docs/` + `mkdocs.yml`.

## Existing Spec Touchpoints

- **Extends / supersedes (authoring)**: `cobesy-writer`, `agentic-codebase-writer`, `classification-coverage-planner`, `quality-review-gate`, `harness-bundle-skeleton` (outer dummy run only).
- **Reuses without expanding**: `repo-ingestion-analysis`, `mkdocs-site-assembler` (emit path), `github-pages-deploy` (modes).
- **Adjacent, do not expand**: `ontology-engine` (page metadata may slim down; do not add axes), `docuharnessx-mcp-refine`, `e2e-multi-project` (replace e2e assertions that only check “body non-empty”).

## Constraints

- Python 3.12; `uv`; HarnessX as a library for the **writer only**.
- No new heavy dependencies.
- Credential-free tests via a scripted fake that actually reads fixture files.
- A run must remain bounded (per-page step/cost caps; bounded question count).
- Pet-project scope: one coherent invert, not another 11-spec wave.
- Target repos remain ~25–40k LOC; reference targets include `malware_hashes` and DocuHarnessX itself.
