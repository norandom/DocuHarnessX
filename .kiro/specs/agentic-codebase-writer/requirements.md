# Requirements Document

## Introduction

The `agentic-codebase-writer` replaces the `cobesy-writer`'s content-free, single-shot
prose step with a bounded, HarnessX-agentic, codebase-grounded writer. The current Write
stage issues one `model.complete(messages, tools=[])` call whose prompt deliberately
excludes file contents ("invent no repository facts"; evidence is file paths only), so the
model cannot read the repository and emits generic skeleton text that the review gate
correctly rejects, leaving an empty site. This feature makes the Write stage run a real
HarnessX agent per planned segment: the agent explores the target repository with the
built-in read/grep/glob/bash tools over a read-only `Workspace` rooted at the repo, grounds
its prose in the actual source, and emits a substantive, `file:line`-cited,
Mermaid-diagrammed, COBESY-structured ontology `Segment`. The deterministic structure work
(COBESY blueprint, segment wiring, fallback) is preserved; the model's prose step becomes
agentic. A bounded guarantee is kept through HarnessX Control budgets (step/cost/token caps
plus loop detection), and a deterministic fallback body is produced on agent
failure/timeout/empty so a run never crashes and is always usable. The quality bar is
deepwiki-open: model-generated Mermaid with strict syntax, mandatory `file:line` citations,
and pages grounded in real source.

The change is a single-stage swap of `docuharnessx/stages/write.py` (the stable
`STAGE_NAME='write'`, `WriteStage`, `make_write_stage`, and module path are unchanged so the
stage registry and `make_docgen` need no edits), plus a minimal, idempotent `mkdocs.yml`
Mermaid-fence enablement so emitted diagrams render. Every other seam is consumed and
produced verbatim.

## Boundary Context

- **In scope**:
  - Replacing the Write stage's prose step with a bounded, per-segment HarnessX agentic run
    that reads the real repository and produces grounded, cited, diagrammed Markdown bodies.
  - Per-segment exploration scoped by `PlannedSegment.evidence` files and subjects, COBESY
    structure seeded from the existing blueprint, mandatory Mermaid diagram(s) and
    `file:line` citations in the body.
  - Bounding each per-segment run via HarnessX Control (max steps, max cost, token budget,
    loop detection) and surfacing per-run cost/steps/exit-reason in the bounded journal.
  - A deterministic fallback body on agent failure/timeout/empty so the run never crashes.
  - A scripted fake agent provider and crafted fixture repository that exercise the real run
    loop and real read/grep tools with no network or credentials, so the full pipeline
    (write → review → assemble → build) stays testable offline and the review accept path is
    reachable.
  - A minimal, idempotent enablement of the Material `pymdownx.superfences` mermaid custom
    fence in the assembler's `mkdocs.yml` so emitted diagrams render.
- **Out of scope** (separate follow-ups):
  - Planner subject-scoping (pages tagged with all components) — planner concern.
  - Home/index landing page — assembler concern.
  - Review-gate threshold / k-of-n recalibration — review concern.
  - Any custom embedding, RAG, or vector index — explicitly not built; HarnessX context is
    agentic-by-tools.
  - Changes to the registry, `make_docgen` bundle composition, the planner, the review gate,
    the assembler page rendering, or the deployer beyond the single `mkdocs.yml` fence line.
- **Adjacent expectations**:
  - The Plan stage publishes a `CoveragePlan` of `PlannedSegment`s (with `roles`, `intent`,
    `subjects`, `evidence`) to the coverage-plan slot; the writer consumes it verbatim.
  - The loaded `Vocabulary` and a `SegmentStore` handle are present in the run context.
  - The run context exposes the target-repository path the agent's read-only `Workspace`
    roots at.
  - The bound model (if any) is reached through the runtime-injected model configuration,
    exactly as the Plan stage reaches its relevance model.
  - The downstream review gate, assembler, and deployer consume the unchanged
    `WrittenSegments` / `Segment` output seam and must not require any change.

## Requirements

### Requirement 1: Single-stage in-place replacement

**Objective:** As a pipeline maintainer, I want the agentic writer to drop into the exact
slot the current Write stage occupies, so that the stage registry, the `make_docgen` bundle,
and every other pipeline stage need no edits.

#### Acceptance Criteria
1. The Write stage module shall keep the stable `STAGE_NAME` value `"write"`, the
   `WriteStage` class name, the `make_write_stage` factory, and its existing module path so
   the stage registry and `make_docgen` need no edits.
2. When the Write stage participates in the pipeline, the Write stage shall do its work as a
   side effect of the content-free step-end event and yield that event unchanged, modifying
   no generated content window.
3. While the Write stage is driven outside a harness (no run state bound), the Write stage
   shall forward the event unchanged and write nothing, exactly like the prior no-op base.
4. The Write stage shall obtain the live run state from the task-start event and read its
   inputs through the typed run-context accessors, mirroring the existing Plan stage
   lifecycle.
5. The agentic-codebase-writer shall not modify the stage registry, the `make_docgen` bundle
   composition, or any other pipeline stage's module.

### Requirement 2: Input boundary and fatal-input handling

**Objective:** As a pipeline operator, I want the writer to validate its inputs and halt
loudly on a missing or unsupported input, so that a misconfigured run fails with an
identifiable cause instead of emitting partial or guessed output.

#### Acceptance Criteria
1. The Write stage shall read the `CoveragePlan`, the optional repository analysis, the
   loaded `Vocabulary`, the `SegmentStore` handle, and the target-repository path through the
   typed run-context accessors.
2. If the coverage-plan slot is unset when a run state is bound, the Write stage shall raise
   a writer input error naming the missing slot and produce no partial output.
3. If the consumed `CoveragePlan` declares a schema version this build does not support, the
   Write stage shall raise a writer input error naming the unsupported version and produce no
   partial output.
4. If the vocabulary slot or the segment-store slot is unset when a run state is bound, the
   Write stage shall raise a writer input error naming the missing slot and produce no
   partial output.
5. Where the repository-analysis slot is unset, the Write stage shall tolerate the absence
   and proceed, grounding the agent on the planner evidence and the live repository alone.
6. If the target-repository path is unset or does not resolve to an existing directory, the
   Write stage shall record a deterministic flag and fall back to the deterministic body for
   every segment rather than crashing the run.

### Requirement 3: Per-segment agentic exploration of the target repository

**Objective:** As a documentation reader, I want each segment's prose grounded in the actual
source code, so that the documentation reflects what the repository really does rather than
generic boilerplate.

#### Acceptance Criteria
1. For each planned segment, the Write stage shall run a real HarnessX agentic loop that
   offers the agent the built-in read, grep, glob, and bash exploration tools.
2. The Write stage shall give the agent a file-system view rooted at the target repository in
   read-only mode, so the agent reads real source but cannot modify the target repository.
3. The Write stage shall scope each agentic run's task prompt to the segment's planner
   evidence files and subjects as the starting point, while permitting the agent to read
   further repository files as needed to ground the segment.
4. While the agent runs, the Write stage shall make the tool outputs (read/grep/glob/bash
   results) available to the model as conversation context, so the model's prose is derived
   from real source content rather than from file paths alone.
5. The Write stage shall use the final agent answer as the source of the segment body.
6. The agentic-codebase-writer shall not build or rely on any embedding, vector index, or
   retrieval-augmented store; repository context shall be obtained agentically through the
   exploration tools only.

### Requirement 4: COBESY-structured, cited, Mermaid-diagrammed body

**Objective:** As a documentation reader, I want each segment to be structured for fast
adoption, visually diagrammed, and traceable to source, so that I can understand and trust
the content quickly.

#### Acceptance Criteria
1. The Write stage shall seed each agentic run's prompt with the existing deterministic
   COBESY blueprint for the segment (SCQA opener, Minto lead-with-conclusion, working-memory
   chunks, REDUCE-barrier fast path, andragogy flag, title), so the agent fills that
   structure rather than inventing its own.
2. The Write stage's task prompt shall instruct the agent to include at least one valid
   Mermaid diagram grounded in the code, using a supported diagram type (for example
   `graph TD`, `sequenceDiagram`, `classDiagram`, or `erDiagram`), vertical orientation,
   short node labels, and valid arrow grammar.
3. The Write stage's task prompt shall instruct the agent to cite real `file:line` sources so
   the prose stays grounded and specific, requiring citations to at least a configured
   minimum number of source files.
4. When the agent returns a body, the Write stage shall validate that the body contains at
   least one fenced Mermaid diagram block and at least the configured minimum number of
   `file:line` citations, and shall treat a body that fails this validation as an unusable
   response.
5. When a body passes structure validation, the Write stage shall use it verbatim as the
   segment body so the emitted diagrams and citations reach the published site unchanged.
6. The agentic-codebase-writer shall hardcode no project roles, intents, or subjects;
   all audience/intent framing in the prompt shall derive from the loaded `Vocabulary`
   labels carried by the blueprint.

### Requirement 5: Bounded per-segment cost and steps

**Objective:** As a pipeline operator running against repositories of 25–40k LOC, I want each
segment's agentic run strictly bounded, so that documentation generation cannot run away in
cost, steps, or time.

#### Acceptance Criteria
1. The Write stage shall cap each per-segment agentic run with a maximum number of steps, a
   maximum cost budget, and a token budget, and shall enable loop detection so a repeating
   tool-call pattern halts the run.
2. While a per-segment run reaches its step, cost, or token bound, the Write stage shall stop
   that run and proceed using whatever grounded answer was produced, or the deterministic
   fallback when no usable answer was produced.
3. The Write stage shall apply the bounds per segment so one expensive segment cannot consume
   the budget intended for the others.
4. The Write stage shall obtain the bound model from the runtime-injected model configuration
   exactly as the Plan stage obtains its relevance model; if no model is reachable, the
   per-segment run shall not be attempted and the deterministic fallback shall be used.
5. The Write stage shall run the per-segment agentic loop off the pipeline run loop's thread
   so the agent's own event loop never nests inside the pipeline run loop.

### Requirement 6: Deterministic fallback and resilience

**Objective:** As a pipeline operator, I want the run to always complete with a usable
result, so that an agent failure, timeout, or empty answer never crashes the pipeline or
leaves a segment without content.

#### Acceptance Criteria
1. If a per-segment agentic run raises, times out, returns an empty answer, or returns a body
   that fails structure validation, the Write stage shall render the existing deterministic
   fallback body for that segment and continue.
2. The Write stage shall record the prose source provenance for each segment, distinguishing
   a model-grounded body from a deterministic-fallback body.
3. When no model is reachable for the run, the Write stage shall produce a deterministic
   fallback body for every planned segment without attempting an agentic run.
4. While an empty coverage plan is consumed, the Write stage shall produce an empty written
   set and complete without error.
5. The Write stage shall process planned segments in the coverage plan's existing
   deterministic order.
6. If a produced segment fails ontology validation against the loaded `Vocabulary`, or
   storing it conflicts with an existing id, the Write stage shall record a deterministic
   write flag for that segment and continue with the remaining segments.

### Requirement 7: Unchanged output seam for downstream stages

**Objective:** As an owner of the review, assemble, and deploy stages, I want the writer to
feed exactly the same output seam as before, so that those stages keep working without any
change.

#### Acceptance Criteria
1. The Write stage shall produce the same frozen written-segments output seam (the same value
   type at the same run-context slot) the review gate already consumes.
2. The Write stage shall store each successfully produced segment in the `SegmentStore` and
   include the same segment identities in the written-segments seam.
3. The Write stage shall populate every non-body field of each segment (id, title, roles,
   subjects, intent, related, schema version) deterministically from the planned segment and
   the blueprint, so only the body and summary come from the agent.
4. The Write stage shall represent every planned segment in the written-segments seam either
   as a written segment or as a write flag, so the seam stays auditable.
5. The agentic-codebase-writer shall require no change to the review gate, the assembler page
   rendering, or the deployer to consume its output.

### Requirement 8: Bounded, auditable journaling

**Objective:** As a pipeline operator, I want a bounded audit trail of what the writer did,
so that I can see per-run cost and provenance without the journal exploding on large repos.

#### Acceptance Criteria
1. When the Write stage completes, the Write stage shall record a participation entry in the
   run journal carrying a summary of the write (total planned count, written count, flagged
   count, a capped list of top-priority written segment ids, and the aggregate prose source).
2. The Write stage shall record per-segment agentic telemetry at a summary level — at least
   the step count, cost, and exit reason of each per-segment run — without writing full
   segment bodies, tool outputs, or conversation transcripts to the journal.
3. The Write stage shall keep the journal entries bounded for large plans by capping listed
   ids and omitting full segment objects.

### Requirement 9: Credential-free offline testability

**Objective:** As a developer, I want the agentic writer testable end-to-end with no network
or credentials, so that the full pipeline stays verifiable offline and in CI.

#### Acceptance Criteria
1. The agentic-codebase-writer shall provide a scripted fake agent provider that returns a
   deterministic sequence of tool calls (reading fixture files) followed by a final grounded
   body containing Mermaid and `file:line` citations.
2. When driven by the scripted fake provider over a crafted fixture repository, the Write
   stage shall exercise the real HarnessX run loop and the real read/grep exploration tools
   with no network access and no credentials.
3. The agentic-codebase-writer shall provide a crafted fixture repository whose contents make
   the scripted fake provider's reads and the produced citations deterministic.
4. When the scripted fake provider runs through the full pipeline, the produced segment shall
   pass the review gate's accept path so the assembled site is non-empty in tests.
5. The agentic-codebase-writer shall keep the deterministic core (blueprint, wiring,
   fallback) unit-testable without any model or agent.

### Requirement 10: Mermaid rendering enablement

**Objective:** As a documentation reader, I want the emitted Mermaid diagrams to render in
the published Material site, so that the diagrams the agent produces are actually visible.

#### Acceptance Criteria
1. The agentic-codebase-writer shall enable the Material `pymdownx.superfences` custom fence
   for Mermaid in the assembler's `mkdocs.yml` so fenced `mermaid` blocks render as diagrams.
2. The Mermaid-fence enablement shall be minimal and idempotent, adding only the configuration
   needed to render Mermaid and changing no other assembler behavior.
3. When the site is built after the enablement, a page containing a fenced Mermaid block
   shall build successfully without a strict-mode error.
