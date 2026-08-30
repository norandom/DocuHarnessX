# Implementation Plan

- [ ] 1. Foundation: new seams and a pipeline skeleton that cannot publish outlines
- [x] 1.1 Define the question plan types
  - Introduce the frozen question, question kind, and question-plan values the planner will emit (id, kind, title, subject name, evidence paths).
  - Ids follow `{kind}:{slug}` and do not include a reader role or intent.
  - Observable completion: equal constructed inputs compare equal; a unit test round-trips a sample startup question and rejects a role-intent shaped id in the documented id helper.
  - _Requirements: 2.2, 2.4_
  - _Boundary: QuestionPlanner_

- [x] 1.2 Define the page, omission, and run-report types
  - Introduce the frozen page (id, title, summary, body, subjects, related, cited files) with no roles or intent fields.
  - Introduce omission (question id + closed-set reason) and run report (planned / accepted / omitted counts, question ids, omissions; no bodies).
  - Observable completion: a unit test serializes a report with one omission reason `no_model` and asserts the payload has counts and no body text.
  - _Requirements: 1.4, 9.1, 9.2, 9.3, 10.3_
  - _Boundary: RunReport_

- [x] 1.3 Build a pipeline skeleton that analyzes, plans, reports, and never writes outline pages
  - The runner calls the existing analyzer, then the question planner (stub returning empty is acceptable until 2.1), skips writing when no model is bound, writes the run report under the output directory, and does not emit documentation pages or a role-based site shell.
  - The skeleton must not invoke the retired fallback outline renderer.
  - Observable completion: a no-model run against the shipped sample repository writes a report with zero accepted pages, no files under the pages output, and no “locate / smallest action” text anywhere in the output directory.
  - _Requirements: 1.1, 1.3, 6.1, 6.2, 8.4, 10.2_
  - _Boundary: PipelineRunner_
  - _Depends: 1.1, 1.2_

- [ ] 2. Core: question planning, substance gate, and explore-first writer task
- [x] 2.1 (P) Plan software questions from repository scan signals
  - Implement deterministic planning: entrypoints → startup; named components → component questions up to the component cap; public surface → one extend/use question; build or CI → one build/verify question; tests present → one test-layout question.
  - Apply the documented maximum question count; extra component questions are dropped, not authored as persona pages.
  - Empty or signal-free analysis yields an empty plan. Default reader-role lists do not activate questions.
  - Observable completion: unit tests on the shipped sample’s analysis (or an equivalent frozen analysis) assert stable question ids in a stable order, the expected kinds, the caps, empty-in/empty-out, and that no planned id contains a role-intent pair; two runs match (Req 11.3).
  - _Requirements: 2.1, 2.3, 2.4, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 4.1, 4.2, 4.3, 11.3_
  - _Boundary: QuestionPlanner_
  - _Depends: 1.1_

- [x] 2.2 (P) Gate accepted bodies on substance, not diagrams or outlines
  - Accept only when the body cites at least two distinct files that exist under the target repository in `path:line` form, names at least one identifier from the question’s subject or evidence, and is not a title-only restatement.
  - Reject retired slogans (fastest path for, who this is for, run the smallest action, verify first success, locate-the-subject as empty instruction).
  - A diagram is optional and must not be the accept condition.
  - Observable completion: unit tests accept a grounded sample body citing two real fixture files and `load_config` or `Engine`; reject template-slogan bodies, missing-path citations, title-only restatements, and mermaid-without-citations; mermaid plus valid citations still accepts.
  - _Requirements: 5.2, 6.3, 7.1, 7.2, 7.3, 7.4, 7.5, 10.4_
  - _Boundary: SubstanceGate_
  - _Depends: 1.1_

- [x] 2.3 (P) Build the explore-first writer task from the question and evidence only
  - The task description states the software question, the read-only repo root, the evidence files to read first, the duty to cite `path:line` and name real symbols, and that the final message is the Markdown body.
  - It must not include filled situation/complication/key-message/fast-path sentences, COBESY method names, or instructions to copy an outline.
  - Observable completion: a unit test over a sample question asserts evidence paths and the question title appear, and asserts the forbidden outline/slogan strings do not.
  - _Requirements: 5.1, 5.4_
  - _Boundary: ExploreWriter_
  - _Depends: 1.1_

- [x] 2.4 (P) Assemble a question-organised site from accepted pages only
  - Home page lists accepted page titles as links; navigation has no per-role landing pages.
  - Omitted questions leave no stub page. Zero accepted pages means no role-based empty site tree.
  - Reuse existing site identity and page-file emission; optional publish modes remain callable after a non-empty assemble.
  - Observable completion: given two accepted pages, the emitted home page lists both titles and contains no “pick your role” / role-directory index; given zero pages, no role landing files are written.
  - _Requirements: 2.3, 8.1, 8.2, 8.3, 8.4, 8.5, 10.1_
  - _Boundary: SiteAssembler_
  - _Depends: 1.2_

- [ ] 3. Writer adapter: explore, then omit on failure
- [x] 3.1 Run one bounded writer per question and omit instead of substituting an outline
  - For each planned question, run the existing bounded writer over a read-only copy of the target repository using the explore-first task.
  - If stats show no tool loop (`steps <= 1`), if the body is empty, or if the substance gate rejects, record an omission with the matching closed-set reason and do not write a page.
  - Never call the retired fallback outline renderer. Continue remaining questions after an omission.
  - If the repository path is not a directory at write time, omit all with `inspection_impossible`.
  - Observable completion: integration tests with the shipped sample and a scripted writer that reads files then returns a grounded body produce an accepted page; a scripted writer that answers immediately with outline text produces zero pages and `not_inspected` or `gate_rejected`; a missing repo path produces `inspection_impossible` and zero pages.
  - _Requirements: 5.2, 5.3, 6.1, 6.3, 6.4, 11.1, 11.2_
  - _Boundary: ExploreWriter_
  - _Depends: 2.2, 2.3_

- [ ] 4. Integration: full pipeline and CLI
- [x] 4.1 Wire analyze → questions → write/gate → assemble → report in the pipeline runner
  - Replace skeleton stubs with the real planner, writer adapter, substance gate, and site assembler.
  - No-model still plans (or reports skip) and writes zero pages. Empty plan writes a report and no site shell.
  - Fold writer stats into omission reasons without putting bodies in the report. Verbose logging must not dump full bodies into the report file.
  - Observable completion: a pipeline test on the shipped sample with the inspecting scripted writer yields ≥1 accepted page, a home list of question titles, and a report whose planned = accepted + omitted; a no-model run still yields zero pages and reason `no_model`.
  - _Requirements: 1.1, 1.3, 2.2, 6.2, 8.1, 8.4, 9.1, 9.2, 9.3, 9.4_
  - _Boundary: PipelineRunner_
  - _Depends: 2.1, 2.4, 3.1_

- [ ] 4.2 Switch the operator CLI onto the pipeline and drop the dummy run
  - Valid target + output directory runs the pipeline. Invalid target still exits non-zero with no pages.
  - Binding a writer model is optional; absence is a zero-page report, not outline pages. Reader-role selection is not required.
  - Stop driving documentation via a dummy conversational task that forbids tools. Optional publish modes run only after at least one accepted page.
  - Completed runs including honest-empty exit 0; invalid target exits non-zero.
  - Observable completion: invoking the CLI on a missing path fails as today; invoking it on the shipped sample without a model writes a report and zero documentation pages; invoking it with the inspecting fake (test injection) produces grounded pages and no role landings.
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 8.5, 10.1, 10.2, 10.3_
  - _Boundary: CLI_
  - _Depends: 4.1_

- [ ] 5. Reduction: remove the retired authoring path
- [ ] 5.1 Delete publishable fallback, outline blueprints, persona planning, role landings, and the dummy harness bus from the default product
  - Remove the default-run use of outline fallback rendering, Role × Intent coverage as page identity, per-role landing generation, COBESY form-judge as the publish gate, and the dummy outer harness that exists only to fire pipeline processors.
  - Keep repository analysis functions, the inner writer harness factory, model resolution, site identity/theme emit, and deploy modes.
  - Delete or rewrite tests that treated template slogans, fallback headings, role landings, or dummy-harness participation as success.
  - Observable completion: a search of the default run path finds no call to the fallback outline renderer; `dhx --help` still works; the test suite no longer asserts “Locate the CLI” / role index pages as success; analysis and writer-harness unit tests that remain still pass.
  - _Requirements: 10.1, 10.2, 10.3, 10.4, 6.1, 2.4, 8.2_
  - _Boundary: PipelineRunner_
  - _Depends: 4.2_

- [ ] 6. Validation: fixture-grounded accept and no-explore omit
- [ ] 6.1 Prove the shipped sample repository against both writer behaviours
  - Inspecting writer: at least one accepted page cites real sample files and names a symbol defined in those files; home lists that question; report counts add up.
  - Non-inspecting writer: zero accepted pages; omissions are `not_inspected` or `gate_rejected`; no template-slogan bodies in the output directory; report is written.
  - Two planning passes on the unchanged sample yield the same question ids in the same order.
  - Optional publish after accepts still invokes the existing deploy mode when requested.
  - Observable completion: the credential-free e2e for the shipped sample is green for both behaviours and fails if a fallback slogan reappears in output.
  - _Requirements: 8.5, 11.1, 11.2, 11.3_
  - _Boundary: PipelineRunner_
  - _Depends: 5.1_

## Implementation Notes

- Question ids: reject the retired `{role}__{intent}` delimiter (2–3 non-empty `__` tokens on the basename), not any `__`; keep `__main__.py` / `__init__.py` in the slug. Mint ids via `make_question_id`, not raw `Question(id=...)`.
- Pipeline skeleton: `plan_questions` is an empty stub until 2.1, so a default fixture no-model report is `planned=0`; `no_model` omissions appear only when the planner returns questions.
- Shipped `agentic_repo` scan reports no entrypoints (`app.py` is not a detector match); sample plan is `component:root` then `build:pyproject.toml`. Startup is covered by constructed analyses.
- Substance gate title-restatement: omit only leftover prose that is the title plus trivial glue; subject tokens already in the title (e.g. Engine) must not false-reject grounded bodies.
- ExploreWriter uses a local bounded harness loop (`build_question_task` + substance gate), not `AgenticProseRunner.run` (still COBESY until 5.1). Inspection is `steps <= 1` → `not_inspected`.
