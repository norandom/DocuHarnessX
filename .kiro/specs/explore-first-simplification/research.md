# Research & Design Decisions

---
**Purpose**: Capture discovery findings, architectural investigations, and rationale that inform the technical design.

---

## Summary

- **Feature**: `explore-first-simplification`
- **Discovery Scope**: Extension of a brownfield generator with a significant authoring invert (light discovery, escalated architecture notes)
- **Key Findings**:
  - The inner HarnessX writer (`AgenticProseRunner`, `build_writer_harness`) already explores a read-only repo. The dummy outer `DONE` harness and the COBESY blueprint are what prevent that exploration from becoming the page.
  - `RepoAnalysis` already carries the signals a question planner needs (entrypoints, components, public surface, build/CI, tests). The Role × Intent matrix is a mis-use of those signals, not a missing scanner.
  - Publishable fallback (`render_fallback_body` + `WriteStage._fallback_prose`) is an explicit product path, pinned by tests. Fail-closed omission is a deletion of that path, not a new renderer.
  - Assembler identity / MkDocs emit / deploy modes can stay. Per-role landing pages (`assembler/roles.py`, home “choose your path”) cannot.

## Gap Analysis (kiro-validate-gap)

### Current State Investigation

| Area | Location | Pattern | Role today |
|------|----------|---------|------------|
| CLI | `docuharnessx/cli.py` | argparse, `prepare_run` / `orchestrate_run` | Validates target, loads ontology, binds `ModelConfig.agentic(make_docgen())`, runs a skeleton `BaseTask` whose description forbids tools |
| Outer harness | `docuharnessx/bundle.py`, `stages/` | 8 processors on `step_end` | Side-effect pipeline; dummy conversational turn |
| Analysis | `docuharnessx/analysis/` | Pure functions, frozen dataclasses | `analyze(FileInventory) -> RepoAnalysis`; model-free |
| Planning | `docuharnessx/planning/` | matrix + classifier + scorer | Role × Intent cells; evidence refs are file paths |
| Blueprint | `docuharnessx/composition/blueprint.py` | Label Mad Libs | Finished SCQA / key message / fast-path sentences |
| Fallback | `docuharnessx/composition/fallback.py` | Pure renderer | **Publishes** the blueprint as Markdown |
| Writer prompt | `docuharnessx/composition/task_prompt.py` | Embeds blueprint sentences | Tells the agent to honor the outline; “stop exploring” |
| Writer runtime | `composition/agent.py`, `harness_factory.py` | Nested HarnessX | Read-only workspace; structure gate; `None` → caller fallback |
| Structure gate | `composition/structure_gate.py` | Regex | ≥1 mermaid + ≥3 `path:line`; no path existence, no anti-template |
| Review | `docuharnessx/review/` | LLM judge | COBESY form (MECE, role-fit, no-slop); fail-closed if judge missing |
| Assembler | `docuharnessx/assembler/` | Pure render + write | Role landings, tags from vocabulary, MkDocs tree |
| Deploy | `docuharnessx/deployer/` | modes | `build-only` / `emit-ci-workflow` / `gh-deploy` |
| Ontology | `docuharnessx/ontology/` | Vocabulary + Segment | Segment requires roles + intent; `dhx init` seeds 10×13 |
| Fixture | `tests/fixtures/agentic_repo/` | Tiny Python app | Real files for scripted read/grep; symbols `Application`, `Engine.start`, `load_config` |
| Tests | `tests/test_*.py` (~146 files, ~48k LOC) | Pin determinism | Many assert fallback headings, `Locate the CLI.`, role landings, dummy harness |

**Conventions to preserve**: frozen dataclasses, pure planner/gate functions, HarnessX imports localized to adapters, `ModelConfig` never inside `HarnessConfig`, credential-free fakes in `tests/_fakes.py`.

### Requirement-to-Asset Map

| Req | Need | Existing asset | Gap |
|-----|------|----------------|-----|
| 1.1–1.2 | CLI run + invalid target | `cli.py` `_validate_target_repo` | Keep |
| 1.3 | No model → no pages + report | `orchestrate_run` still writes fallback segments today | **Missing** fail-closed no-model path |
| 1.4 | No roles required | `dhx init` / default vocabulary required for write validation | **Constraint**: Segment validation demands vocabulary roles |
| 2 | Question as page unit | `PlannedSegment` is role+intent+subjects | **Missing** `Question` / `QuestionPlan` |
| 3 | Questions from scan signals | `RepoAnalysis` fields exist; `matrix.py` maps them to personas | **Replace** matrix, **reuse** analysis |
| 4 | Cap question count | Scorer orders cells, no page cap | **Missing** documented cap |
| 5 | Explore-first prompt | `task_prompt.py` + `AgenticProseRunner` | **Rewrite** prompt; **keep** runner/factory |
| 6 | Omit on failure | `_fallback_prose` publishes outline | **Delete** publishable fallback |
| 7 | Substance gate | `structure_gate.py` (mermaid-required) | **Replace** criteria; mermaid optional; path must exist |
| 8 | Question-organised site | `home.py`, `roles.py`, `pages.py`, `writer.py` | **Rewrite** home/nav; **delete** role landings; **keep** page file emit + identity |
| 8.5 | Optional Pages | `deployer/` | Keep; call from new pipeline |
| 9 | Run report | Journal scalars (`agent_written_count`) | **Missing** operator-facing report with omission reasons |
| 10 | Retired authoring gone | Entire cobesy/matrix/roles path | **Delete** after CLI switch |
| 11 | Fixture grounded / no-explore omit | `agentic_repo` + scripted provider | **Replace** tests that pin fallback text |

### Implementation Approach Options

#### Option A: Extend existing stages in place

Keep `make_docgen` and `step_end` stages; change planner output and disable fallback.

- **Pros**: Less CLI churn; existing journal hooks.
- **Cons**: Dummy `DONE` agent remains; 8-stage bus still exists; leftover fallback is likely; does not reduce the project. Fails Req 10.

#### Option B: Greenfield package beside DocuHarnessX

New `dhx2` / new package.

- **Pros**: Clean.
- **Cons**: Throws away scanner, writer harness, MkDocs emit, model resolver; pet-project overkill.

#### Option C: Hybrid (recommended)

New `docuharnessx/pipeline/` that calls existing **functions** (`analyze`, writer harness, assembler emit, deploy). New question planner + substance gate + run report. CLI `orchestrate_run` switches to `run_pipeline`. Then delete dummy harness, stages-as-bus, fallback, matrix, role landings, COBESY review-as-publish-gate, and tests that pin them.

- **Pros**: Matches the invert; actually reduces LOC; reuses the parts that work.
- **Cons**: Large test deletion/rewrite; MCP refine (`dhx mcp`) will break (explicitly out of scope).
- **Phasing**: (1) new modules + tests, (2) CLI switch, (3) delete retired path.

**Effort**: L (about a week of focused pet-project work; not XL if deletion is allowed).
**Risk**: Medium — CLI and test corpus are the blast radius; writer runtime is already proven in isolation. High only if fallback is left “for safety.”

### Recommendations for design

- Prefer Option C.
- Introduce `Question`, `Page`, `RunReport` as the new seams; do not keep `PlannedSegment` as the page identity.
- Slim page metadata: do not require `roles[]` / `intent` to store or assemble a page.
- Substance gate is deterministic and model-free (same family as today’s structure gate).
- Writer remains the only HarnessX construct site.
- Cap: default max 12 questions, max 6 component questions; overridable later, documented now.
- Research needed during implementation: whether `AgenticProseRunner.run` already exposes a reliable “inspected files” signal via `steps` / exit reason, or whether the gate must infer inspection from citations + existing paths only. Default to inferring from citations of real paths plus `steps >= 2` (a tool turn) when stats are available.

## Architecture Pattern Evaluation

| Option | Description | Strengths | Risks | Notes |
|--------|-------------|-----------|-------|-------|
| Dummy outer harness + processors | Current | Journal, Control | Authoring inverted; dummy turn | Rejected |
| Python pipeline + writer adapter | Sequential functions | Small; testable; HarnessX only where needed | Must re-home deploy/journal | Selected |
| Single long-running agent for the whole repo | One task “document this repo” | Simple prompt | Unbounded; weak per-page omission; hard tests | Rejected for this spec |

## Design Decisions

### Decision: Python pipeline, HarnessX writer only

- **Context**: Req 1, 5, 6, 10. Dummy `DONE` task is the pipeline bus.
- **Alternatives**: Keep `make_docgen`; drop HarnessX entirely.
- **Selected**: `run_pipeline(...)` in `docuharnessx.pipeline`. Writer adapter constructs a HarnessX harness per question.
- **Rationale**: Analyze, question plan, gate, assemble need no agent loop.
- **Trade-offs**: Journal of the outer dummy run goes away; per-page writer stats still fold into `RunReport`.

### Decision: Question plan from RepoAnalysis, not Role × Intent

- **Context**: Req 2, 3, 4.
- **Selected**: Deterministic rules: entrypoints → startup question; each component (capped) → component question; public surface → extend/use question; build+CI → build question; tests present → test-layout question.
- **Rationale**: Signals already exist; personas were the wrong page unit.
- **Trade-offs**: Fewer pages; some audiences (manager/evaluate) lose a dedicated page — accepted.

### Decision: No publishable fallback

- **Context**: Req 6, 10, 11.2.
- **Selected**: Writer `None` / gate reject → omit. Delete `render_fallback_body` from the publish path.
- **Rationale**: Publishing the outline is the observed product failure.
- **Trade-offs**: Zero-page runs are valid and must be tested.

### Decision: Deterministic substance gate, mermaid optional

- **Context**: Req 7. Today’s gate forced mermaid and ignored path existence / template phrases.
- **Selected**: Accept iff (a) ≥2 distinct `path:line` files that exist under the target repo, (b) ≥1 known identifier from the question’s evidence/subject appears in the body, (c) body does not match retired template phrases, (d) optional mermaid is ignored for the accept decision.
- **Rationale**: Syntactic mermaid was gameable; missing paths were not caught; template dumps sometimes gained fake citations.
- **Trade-offs**: Weak models that cannot cite will omit pages (desired).

### Decision: Slim Page seam; ontology vocabulary not required to run

- **Context**: Req 1.4, 10.3. `FilesystemSegmentStore` + `validate_segment` require a Vocabulary.
- **Selected**: New `Page` value object written as Markdown with frontmatter `{id, title, subjects, summary, related}`. Store as files under `<out>/pages/`. Assembler reads `Page`s, not role views.
- **Rationale**: Forcing 10 roles to emit a page recreates the old product.
- **Trade-offs**: `dhx init` ontology becomes unused for the default run (out of scope to delete the command; do not call it from the default path).

### Decision: Switch CLI, then delete retired code

- **Context**: Req 10; reduction goal.
- **Selected**: Land new pipeline green, point `orchestrate_run` at it, then delete `make_docgen` stage bus, fallback, matrix, cobesy blueprint/prompt, role landings, review-as-publish-gate, and tests that pin them.
- **Rationale**: Leaving the old path “just in case” prevents reduction.
- **Follow-up**: `dhx mcp` will break; listed out of boundary.

## Synthesis

### Generalization

One abstraction covers Req 2–9: a **question** has evidence; a **page** is an accepted answer; a **report** accounts for planned / accepted / omitted. Write, gate, assemble, and report all speak those three types.

### Build vs adopt

- Adopt: existing `RepoAnalysis`, HarnessX writer loop, MkDocs emit, model resolver, deploy modes, `agentic_repo` fixture.
- Build: question planner, substance gate, pipeline runner, run report, slim `Page`.
- Do not adopt COBESY composition as page structure (skill itself says skip for factual lookup).

### Simplification

Remove: dummy outer harness, 8 `step_end` stage adapters as the run, Role × Intent matrix, COBESY blueprint-as-prose, publishable fallback, LLM form-judge as publish gate, per-role landings, required vocabulary for a default run. Do not add RAG, AST, or a second agent framework.

## Risks & Mitigations

- **Leftover fallback** — tests that assert “zero pages when writer does not inspect”; delete `fallback.py` from publish path in the same wave.
- **Writer still echoes the question** — substance gate rejects restatement without identifiers (Req 7.5).
- **OpenAI-compat tool-calling** — keep native provider routing already in `model_resolver.py`.
- **MCP refine breakage** — documented out of scope; do not spend this spec on it.
- **Test suite time** — delete rather than skip retired tests; do not maintain dual pipelines.

## References

- `.kiro/specs/explore-first-simplification/brief.md` — agreed invert
- `.kiro/specs/agentic-codebase-writer/brief.md` — prior diagnosis of 1.0 boilerplate
- `docuharnessx/cli.py` `_SKELETON_TASK_DESCRIPTION` — dummy outer task
- `docuharnessx/composition/fallback.py` — publishable outline
- `docuharnessx/model_resolver.py` — LiteLLM `content: null` production incident
- COBESY skill: skip for factual lookup; composition blueprint is a skeleton, not a published article
