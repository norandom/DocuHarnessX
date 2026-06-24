# Implementation Plan

- [ ] 1. Foundation: writer budget constants and credential-free agent test substrate
- [ ] 1.1 Define writer budget defaults and the agentic structure-gate threshold
  - Add the writer budget constants (max steps, max cost, token budget, token compaction
    threshold, loop threshold) and the minimum cited-files threshold as named module-level
    defaults in the composition core, so every per-segment agentic run is bounded by shared,
    auditable values rather than scattered literals.
  - Observable completion: importing the composition core exposes the named budget defaults
    and the minimum-citations default, and a unit test asserts their concrete values and that
    they are positive.
  - _Requirements: 5.1, 4.3, 4.4_
  - _Boundary: composition core defaults_

- [ ] 1.2 Add a scripted fake-agent provider that drives the real run loop
  - Add a `BaseModelProvider`-shaped test provider whose completion returns a deterministic
    sequence of tool-call responses (read/grep over fixture files) followed by a final
    end-turn response whose content is a grounded body containing a valid Mermaid fence and at
    least the minimum number of `file:line` citations.
  - Observable completion: a unit test runs the provider through the real HarnessX run loop and
    confirms the scripted tools execute (real file reads occur) and the final answer carries
    the Mermaid fence and citations, with no network access.
  - _Requirements: 9.1, 9.2_
  - _Boundary: test fakes_
  - _Depends: 1.1_

- [ ] 1.3 Add a crafted fixture repository for deterministic exploration and citations
  - Add a small fixture repository whose files make the scripted provider's reads and the
    produced `file:line` citations deterministic and self-consistent (the cited paths and line
    numbers point at real fixture content).
  - Observable completion: a unit test reads the fixture files through the real read/grep tools
    rooted at the fixture directory and confirms the citations in the scripted body resolve to
    existing lines in the fixture.
  - _Requirements: 9.3_
  - _Boundary: test fixtures_
  - _Depends: 1.2_

- [ ] 2. Core: deterministic agentic-writer building blocks
- [ ] 2.1 (P) Build the deterministic agentic task-prompt assembler
  - Turn one COBESY blueprint plus the segment's evidence files, subject phrases, and the
    target-repo path into a bounded agentic task: the prompt instructs the agent to start from
    the evidence files, read real source with the tools, follow the blueprint's COBESY
    structure, include at least one valid Mermaid diagram (supported type, vertical, short
    nodes, valid arrows), and cite real `file:line` sources for at least the minimum number of
    files; all audience/intent framing comes from the blueprint labels with no hardcoded
    roles/intents/subjects.
  - Observable completion: a unit test confirms the assembled task carries the bounded caps,
    names the evidence files and subjects, embeds the COBESY moves and the Mermaid/citation
    demands, uses only blueprint-derived labels, and is byte-identical for equal inputs.
  - _Requirements: 3.3, 4.1, 4.2, 4.3, 4.6_
  - _Boundary: task_prompt_

- [ ] 2.2 (P) Build the deterministic structure gate for agent bodies
  - Validate an agent-produced body deterministically: accept only when it contains at least
    one fenced Mermaid block whose first content line names a supported diagram type and at
    least the minimum number of distinct `file:line` citations; report the counts and a reason.
  - Observable completion: unit tests show a body with a `graph TD` fence plus enough citations
    is accepted, a body with no Mermaid is rejected, a body with too few citations is rejected,
    and distinct cited files are counted correctly; the function never raises and is
    deterministic.
  - _Requirements: 4.4, 9.5_
  - _Boundary: structure_gate_

- [ ] 2.3 (P) Build the bounded writer-harness factory with a read-only repo workspace
  - Compose a model-free harness configuration from the context, window-management, and
    bounded control bundles, with the default exploration tool set (read/grep/glob/bash) and a
    workspace rooted read-only at the target repository, so the agent reads real source but
    cannot modify the target; the model is never embedded in the configuration.
  - Observable completion: a unit test confirms the configuration offers the exploration tools,
    roots a read-only workspace at the given repo path (a write attempt against the workspace
    is blocked), enables the bounded control budget, carries no model, and wires no embedding,
    vector index, or retrieval store (repository context is obtained agentically through the
    tools only).
  - _Requirements: 3.1, 3.2, 3.6, 5.1_
  - _Boundary: harness_factory_

- [ ] 2.4 Build the bounded agentic prose runner
  - Run one bounded agent per segment: build the read-only repo harness, bind the run's model,
    build the scoped task, execute the agentic loop so tool outputs become model context, take
    the final answer as the body, and run it through the structure gate; return a
    model-sourced prose result on an accepted body or nothing on raise/timeout/empty/over-budget
    /rejected, while emitting per-run telemetry (steps, cost, exit reason, accepted) that
    excludes the body, tool outputs, and transcript. The runner never raises and exposes a
    synchronous entry point so the stage can offload it off the pipeline run loop.
  - Observable completion: unit tests (using the scripted fake provider and fixture repo) show
    an accepted body yields a model-sourced result whose body is the agent's final answer
    verbatim with Mermaid and citations, a failing/empty/rejected run yields no result plus
    telemetry, the run is bounded per segment, and the body never appears in the telemetry.
  - _Requirements: 3.4, 3.5, 5.2, 5.3, 6.1, 8.2_
  - _Boundary: AgenticProseRunner_
  - _Depends: 2.1, 2.2, 2.3_

- [ ] 2.5 Re-export the agentic entry points from the composition namespace
  - Surface the task-prompt assembler, the structure gate, the harness factory, the agentic
    prose runner, the per-run telemetry record, and the budget defaults from the single
    composition namespace so the stage adapter and tests import them from one place, keeping
    the deterministic core entry points intact.
  - Observable completion: a package-surface unit test imports each new agentic entry point and
    the retained deterministic-core entry points from the composition namespace and confirms
    the public contract lists them.
  - _Requirements: 9.5_
  - _Boundary: composition namespace_
  - _Depends: 2.4_

- [ ] 3. Integration: swap the Write stage's prose surface to the bounded agent
- [ ] 3.1 Replace the per-segment prose call with the bounded agentic runner and fallback
  - In the existing Write stage (keeping the stable stage name, class, factory, module path,
    and the input boundary), additionally read the target-repository path; when a model is
    bound and the repo path resolves to a directory, offload the agentic runner off the
    pipeline run loop, accept its model-sourced body when the structure gate passed, and
    otherwise render the existing deterministic fallback; when no model is bound or the repo
    path is missing or invalid, produce the deterministic fallback for every segment without
    attempting a run. Preserve plan-order iteration, validation/id-conflict flagging, the
    segment-store writes, and the unchanged written-segments output seam.
  - Observable completion: with the scripted fake provider, fixture repo, and a populated
    repo-path slot, the stage drives the real run loop and stores a segment whose body has
    Mermaid and `file:line` citations; with no model the stage stores deterministic-fallback
    bodies for every planned segment; with no repo-path slot the stage falls back for every
    segment and never crashes; the published output-seam type and slot are unchanged.
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 4.5, 5.4, 5.5, 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 7.1, 7.2, 7.3, 7.4_
  - _Boundary: WriteStage_
  - _Depends: 2.4, 2.5_

- [ ] 3.2 Fold per-segment agentic telemetry into the bounded journal summary
  - Extend the stage's bounded journal participation to carry a summary-level aggregate of the
    per-segment agentic runs (for example total agent steps, total agent cost, and
    accepted-versus-fallback counts) alongside the existing counts, capped ids, and aggregate
    prose source, without writing any segment body, tool output, or conversation transcript.
  - Observable completion: a unit test asserts the journal participation detail includes the
    bounded agentic aggregate and the existing summary fields and contains no segment body or
    transcript.
  - _Requirements: 8.1, 8.2, 8.3_
  - _Boundary: WriteStage_
  - _Depends: 3.1_

- [ ] 4. Integration: enable Mermaid rendering in the assembled site
- [ ] 4.1 Add the Mermaid superfence to the mkdocs configuration builder
  - Extend the assembler's mkdocs configuration builder to emit a markdown-extensions entry
    enabling the Material custom fence that renders fenced `mermaid` blocks as diagrams,
    preserving the fence format reference so the renderer recognizes it, while changing no
    other configuration key and keeping the output byte-stable for equal inputs.
  - Observable completion: a unit test confirms the emitted configuration contains the Mermaid
    custom-fence markdown extension with the correct format reference and that all previously
    emitted keys are unchanged.
  - _Requirements: 10.1, 10.2_
  - _Boundary: build_mkdocs_yaml_

- [ ] 5. Validation: credential-free end-to-end and regression checks
- [ ] 5.1 Verify a Mermaid page builds under strict mode
  - Assemble a small site whose page contains a fenced Mermaid block and build it in strict
    mode to confirm the enabled custom fence renders without a strict-mode error.
  - Observable completion: an integration test performs the strict build of a Mermaid-bearing
    page and asserts the build succeeds.
  - _Requirements: 10.3_
  - _Boundary: assembler build_
  - _Depends: 4.1_

- [ ] 5.2 Verify the credential-free pipeline reaches the review accept path with a non-empty site
  - Run the full pipeline (write through assemble and build) with the scripted fake provider
    over the fixture repo and confirm the produced segment passes the review gate's accept path
    so the assembled site is non-empty and contains a rendered Mermaid diagram, with no network
    or credentials.
  - Observable completion: an end-to-end test shows the scripted run produces an accepted
    segment, a non-empty assembled site, and a built page carrying the Mermaid diagram, all
    offline.
  - _Requirements: 9.2, 9.4, 10.3_
  - _Boundary: end-to-end pipeline_
  - _Depends: 3.1, 4.1_

- [ ] 5.3 Verify existing downstream seams and tests are unaffected
  - Run the existing suite to confirm the review gate, assembler page/role rendering, and
    deployer consume the unchanged written-segments output seam without modification, and that
    the deterministic core (blueprint, wiring, fallback) remains unit-testable without a model.
  - Observable completion: the existing review, assemble, and deploy tests pass unchanged
    against the new writer, and the deterministic-core unit tests pass with no model bound.
  - _Requirements: 7.5, 9.5_
  - _Boundary: cross-stage regression_
  - _Depends: 3.1, 3.2, 4.1_
