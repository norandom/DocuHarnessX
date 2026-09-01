# Implementation Plan

- [ ] 1. Foundation: blueprint identity, adoption record, living page store
- [x] 1.1 (P) Ship the named blueprint version
  - Add `docuharnessx/blueprint.py` with `BLUEPRINT_NAME` and `BLUEPRINT_VERSION` (package-shipped contract, bumped only when the default vocabulary/page contract the operator adopts changes).
  - Observable completion: `import docuharnessx.blueprint` exposes both constants as non-empty strings; a unit test asserts the name is stable (`docuharnessx-default`).
  - _Requirements: 1.2, 10.1_
  - _Boundary: Blueprint_

- [x] 1.2 Define and round-trip the adoption record
  - Add `AdoptionRecord` and load/save for `.docuharnessx/adoption.yaml` (blueprint name/version, adopted_at, sufficient, sufficient_at, sufficient_stale, nullable `harness_snapshot`).
  - Do not put these fields in `ontology.yaml`.
  - Observable completion: a unit test writes a record including `harness_snapshot=None`, loads it equal, and a missing file returns `None` rather than raising.
  - _Requirements: 1.2, 8.3, 8.4, 10.4_
  - _Boundary: Adoption_
  - _Depends: 1.1_

- [x] 1.3 (P) Living page store on the target project
  - Add `LivingPageStore` protocol + filesystem adapter at `<project>/.docuharnessx/pages/` using existing `page_filename` / question-page frontmatter.
  - Operations: `list`, `get`, `has`, `put`.
  - Observable completion: a unit test puts a sample `Page`, lists it by id, gets equal fields, and `has` is true; missing id returns a documented empty/miss result (no crash).
  - _Requirements: 5.1, 5.3_
  - _Boundary: LivingPageStore_

- [x] 1.4 (P) Track the project documentation store in git
  - Remove the blanket `.docuharnessx/` ignore. Keep `.env` ignored. Ignore only throwaway `.docuharnessx/out/`.
  - Journals, living pages, ontology, adoption record, and harness snapshots remain eligible for version control.
  - Observable completion: `git check-ignore -q .env` exits 0; `git check-ignore -q .docuharnessx/journals/example.jsonl` exits 1; `git check-ignore -q .docuharnessx/out/report.json` exits 0.
  - _Requirements: 12.6, 13.2, 13.3_
  - _Boundary: ProjectStore_

- [ ] 2. Adopt and adjust
- [x] 2.1 No-model / `--default` setup still seeds the blueprint
  - `dhx init --default` or init with no model dumps shipped `default_profile`, writes `AdoptionRecord` with `BLUEPRINT_VERSION`, `sufficient=False`.
  - Refuse overwrite without `--force`. Print paths and blueprint version. Do not prompt for credentials or print secrets.
  - Observable completion: `dhx init --default` in an empty temp project writes `ontology.yaml` and `adoption.yaml` with `BLUEPRINT_VERSION`; a second init without `--force` exits non-zero and leaves files unchanged; no credential prompts appear.
  - _Requirements: 1.2, 1.4, 1.5, 1.6, 12.7_
  - _Boundary: OntologySetup_
  - _Depends: 1.1, 1.2_

- [x] 2.2 Load adopted vocabulary on run; hint when missing
  - If `adoption.yaml` is valid, load `.docuharnessx/ontology.yaml` as today.
  - If ontology is absent, keep default_profile and print that the project has not adopted a blueprint.
  - Invalid ontology terms still fail with the named term (existing loader).
  - Editing ontology.yaml must not rewrite `blueprint_version`.
  - Observable completion: a project with a custom role set in ontology.yaml and an adoption record uses that vocabulary on run; deleting adoption.yaml still runs with the default profile and prints the not-adopted hint; changing only ontology.yaml leaves adoption version intact.
  - _Requirements: 2.2, 2.3, 2.4, 3.1, 3.2, 3.3_
  - _Boundary: OntologyLoader_
  - _Depends: 2.1_

- [x] 2.3 Refuse adopt on a bad target path
  - Missing or non-directory project path: non-zero exit, no files written.
  - Observable completion: `dhx init /no/such/dir` exits non-zero and creates no `.docuharnessx`.
  - _Requirements: 1.3_
  - _Boundary: CLI_
  - _Depends: 2.1_

- [x] 2.4 Interactive credentials with DeepSeek Enter defaults
  - Default `dhx init` on a terminal asks for API key, base URL, and model **before** the setup harness runs.
  - Base-URL prompt shows `https://api.deepseek.com`; empty answer uses it. Model prompt shows the shipped DeepSeek default id; empty answer uses it.
  - Existing key (env or project `.env`) is shown as `***`; empty answer or the literal `***` keeps it; never print the raw secret.
  - Write only to `<project>/.env` (gitignored). `--default` / non-TTY does not prompt.
  - Empty API key with no existing key does not write a blank secret and continues as no-model setup.
  - Later `dhx` commands load `<project>/.env` then cwd `.env` without overriding a live process environment.
  - Observable completion: scripted interview with empty base URL writes that DeepSeek URL to `.env`; pre-set key appears as `***` in captured stdout and not in full; answering `***` leaves the existing key unchanged; `.env` is still ignored by git.
  - _Requirements: 12.1, 12.2, 12.3, 12.4, 12.5, 12.6, 12.7, 12.8_
  - _Boundary: SetupInterview_
  - _Depends: 2.1_

- [x] 2.5 (P) Setup harness produces ontology proposals
  - Build a HarnessX setup harness whose writes are jailed to `.docuharnessx/` (ontology, adoption, journals).
  - It starts from the shipped blueprint, may read the repo, and **returns** proposed roles, intents, and subject prefixes. It does not commit those files until the interview accepts or edits them.
  - A scripted attempt to write outside `.docuharnessx/` is rejected. Invalid vocabulary is not committed.
  - Observable completion: credential-free scripted harness returns a proposal `load_vocabulary` would accept; a scripted write outside the jail is rejected and no ontology file is written yet.
  - _Requirements: 1.1, 1.5, 1.7, 11.3_
  - _Boundary: SetupHarness_
  - _Depends: 2.1_

- [ ] 2.6 Display proposals, accept or edit, then write
  - Integration task: wire SetupInterview (2.4) to SetupHarness (2.5) and persist the agreed ontology.
  - After credentials (2.4) and harness proposals (2.5), interactive setup **displays** proposed roles, intents, and subjects and waits for accept or edit before writing.
  - Accept persists the proposal. Edit persists the operator's term if the ontology accepts it (including a subset of proposed terms). Invalid vocabulary is not committed.
  - `dhx init` with a model uses this path after credentials. `dhx init --manage` edits ontology only and does not touch living pages.
  - A setup journal is written under `.docuharnessx/journals/` when the session finishes.
  - Observable completion: a scripted accept writes the proposed terms to `ontology.yaml` + `adoption.yaml`; a scripted edit writes the operator's role and not the discarded proposal; `--manage` on a project with living pages leaves page bytes unchanged; a setup journal file exists under `.docuharnessx/journals/`.
  - _Requirements: 1.1, 1.7, 1.8, 1.9, 2.1, 2.3, 13.1_
  - _Boundary: SetupInterview_
  - _Depends: 2.4, 2.5_

- [ ] 3. Incremental generation against the living store
- [ ] 3.1 Skip planned questions that already have a living page
  - After `plan_questions`, write only questions where `not store.has(id)` unless regenerate is requested.
  - Assemble from `store.list()` union newly accepted pages.
  - Persist accepted pages with `store.put`.
  - Observable completion: fixture with one stored page and a two-question plan; a no-regenerate run leaves the stored body byte-identical and adds at most the missing question (or omits it via the gate).
  - _Requirements: 4.1, 4.2, 4.3, 5.1, 5.2_
  - _Boundary: PipelineRunner_
  - _Depends: 1.3_

- [ ] 3.2 Explicit regenerate
  - `--regenerate` rewrites all planned ids; `--regenerate-id ID` rewrites one.
  - Regenerated bodies still pass through the substance gate; failure keeps the previous living page.
  - Observable completion: unit/CLI test with a scripted writer: regenerate-id replaces a page only when the fake body is accepted; a rejected fake leaves the old bytes.
  - _Requirements: 4.4, 7.1, 7.2_
  - _Boundary: PipelineRunner_
  - _Depends: 3.1_

- [ ] 3.3 Empty living store still has no site shell
  - Zero living pages after a run: no documentation site tree; status/report still written.
  - Observable completion: no-model incremental run on a project with no pages writes a report and no `docs/` role/question site shell.
  - _Requirements: 9.3_
  - _Boundary: PipelineRunner_
  - _Depends: 3.1_

- [ ] 4. Status and sufficiency
- [ ] 4.1 (P) `dhx status`
  - Report adopted blueprint version or none; planned ids; living ids; omissions with reasons; missing planned ids; sufficient / not / stale.
  - Omission reasons come from the last persisted `RunReport` under the documented project out path (`<project>/.docuharnessx/out` unless `--out` was used). A planned id with no living page and no omission row is **missing**, not omitted.
  - No model required.
  - Observable completion: a temp project with adoption + two planned ids and one living page prints the missing id and `sufficient: no`; after a run that omitted the other id, status shows that omission reason from the saved report.
  - _Requirements: 8.1, 8.2, 8.4_
  - _Boundary: Status_
  - _Depends: 1.2, 1.3_

- [ ] 4.2 Declare sufficient and stale after page changes
  - `dhx sufficient` / `dhx sufficient --not` set flags and timestamp.
  - Integration: any successful `store.put` after a true declaration calls `mark_stale` so `sufficient_stale=True`.
  - Observable completion: declare sufficient → status shows sufficient; put a page → status shows stale until declared again.
  - _Requirements: 8.3, 8.4, 8.5_
  - _Boundary: Adoption_
  - _Depends: 4.1, 1.3_

- [ ] 5. Wire interactive refine to living pages
- [ ] 5.1 Bind MCP session to the living page store
  - `resolve_session` opens `LivingPageStore` on the target project; do not use `<out>/segments` as source of truth.
  - List/get/validate read living pages; no-model still allows those three.
  - Keep old MCP tool names as aliases that bind to living pages. Overview tools (`draft_overview` / `refine_overview` / `get_overview`) fail closed.
  - Observable completion: a session over a temp store lists the seeded page id; `validate` returns a substance-gate verdict; missing id is a structured error; calling an overview tool returns an explicit unsupported/fail-closed result rather than writing a page.
  - _Requirements: 5.3, 6.1, 6.7_
  - _Boundary: RefineSession_
  - _Depends: 1.3_

- [ ] 5.2 One refine cycle with guidance
  - Reuse the explore-first writer + `validate_page_body`. Map a living `Page` to writer inputs. Add `guidance` on the question-task path if missing.
  - Do not call `AgenticProseRunner`, the structure gate, or outline fallback.
  - Fail → previous page unchanged; pass → `put` + mark sufficiency stale.
  - Do not echo guidance as a heading.
  - If no usable model is configured, refuse the write cycle with an explicit no-model result rather than crashing.
  - Observable completion: scripted provider: rejected cycle leaves file bytes equal; accepted cycle updates body and does not contain the guidance string as a heading; no-model cycle returns a structured no-model result and does not change the page.
  - _Requirements: 6.2, 6.3, 6.4, 6.7, 7.1, 7.2, 7.3_
  - _Boundary: RefineHandlers_
  - _Depends: 5.1_

- [ ] 5.3 Reassemble from the living store
  - Rebuild the question-organised site from `store.list()`; optional existing deploy modes when the operator asked to publish.
  - Observable completion: two living pages → home lists both titles; emit-ci-workflow still offered only when accepted ≥ 1.
  - _Requirements: 6.6, 9.1, 9.2_
  - _Boundary: RefineHandlers_
  - _Depends: 5.1_

- [ ] 5.4 Multi-step refine session
  - One session can run several cycles on the same page; each cycle uses the latest guidance.
  - Stop without accept leaves the living page unchanged. Record `RefineSessionStats` (cycles, accepted, steps) in the journal/report.
  - Observable completion: first cycle rejects, second accepts → store updates only after cycle 2 and stats.cycles == 2; abort after a reject → original bytes.
  - _Requirements: 6.2, 6.3, 6.4, 6.5, 6.8_
  - _Boundary: RefineSession_
  - _Depends: 5.2_

- [ ] 6. Guardrails and docs
- [ ] 6.1 Guardrails: no role-intent pages, no model RL
  - Page ids remain `{kind}:{slug}`.
  - `docuharnessx` must not import `harnessx.rl`. `harnessx.meta_harness` is allowed only from the evolve module.
  - Observable completion: a unit test fails if `harnessx.rl` is imported; existing question-id tests still reject role-intent ids.
  - _Requirements: 10.5, 11.1, 11.4_
  - _Boundary: Package_

- [ ] 6.2 README adoption paragraph
  - After install, one short flow: `dhx init` interview (credentials with DeepSeek Enter defaults, then ontology proposals) → adjust ontology if needed → `dhx run` / multi-step `dhx mcp` / `dhx evolve` / `dhx status` until sufficient → link to the GitHub Page.
  - Observable completion: README contains those steps, mentions `***` keep-existing for an API key, and still documents uvx release vs HEAD.
  - _Requirements: 1.5, 1.8, 3.2, 8.1, 12.2, 12.5_
  - _Boundary: Docs_
  - _Depends: 2.1, 2.4, 4.1_

- [ ] 7. Evolve the harness to reduce refine steps
- [ ] 7.1 Journal refine sessions with cycle counts
  - Persist under `<project>/.docuharnessx/journals/` (cycle count, gate accept/reject, task kind/page id). Do not put full page bodies in the operator status report.
  - Do not put secrets in journals. Journals remain eligible for version control (ignore rules already set in 1.4).
  - Observable completion: after a two-cycle accept, a journal file under `.docuharnessx/journals/` contains cycles=2 and accepted=true; `git check-ignore` on that file exits 1 (not ignored).
  - _Requirements: 6.8, 10.1, 13.1, 13.2, 13.4_
  - _Boundary: RefineSession_
  - _Depends: 5.4, 1.4_

- [ ] 7.2 Evolution pass with comparison gate
  - `dhx evolve` loads traces from the project journals path, runs `MetaAgent.evolve` on the current writer/setup config, compares cycles-to-accept, rejects candidates that drop the substance gate or fail to improve.
  - On accept, write a snapshot under `.docuharnessx/harnesses/` and point `AdoptionRecord.harness_snapshot` at it; do not rewrite living pages.
  - Insufficient traces or failure: keep current harness and report no evolution.
  - Observable completion: too-few-traces → snapshot unchanged; a stub candidate that omits the gate is rejected; a stub candidate with lower cycle count is saved and living pages are byte-identical.
  - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 11.2, 11.3, 13.4_
  - _Boundary: Evolve_
  - _Depends: 7.1, 2.6_
