# Requirements Document

## Introduction

Operators who adopt DocuHarnessX on a real repository do not want a one-shot dump. They want a **setup interview**: the harness **proposes ontology** (roles, intents, subjects) to accept or change, and asks for an API key and base URL with DeepSeek as the Enter default. Then they **grow a grounded document over many sessions**. Refine is rarely one rewrite: several steps are normal. Those sessions write **journals the project keeps**, and those journals **evolve the harness** so later similar work takes fewer steps, without ever publishing ungrounded pages.

Today `dhx init` either dumps YAML or asks blank ontology questions, `dhx run` is a batch, and `dhx mcp` offers one-shot rewrite tools on a retired segment store. This specification makes the product: interactive setup (credentials + ontology proposals) → adjust ontology → incremental pages → multi-step refine → evolve harness from tracked journals → operator declares sufficient.

## Boundary Context

- **In scope**: default setup is an **interactive interview** (credentials first, then harness-displayed ontology proposals to accept or change; DeepSeek Enter defaults; existing API key shown and reusable as `***`); a setup harness that adopts a named, versioned blueprint and writes/manages the local ontology; recording that version; operator and harness edits to roles/ontology; incremental generation; preserving refined pages unless explicitly regenerated; **multi-step** interactive refine over the living page store; harness evolution **from journals** whose goal is fewer steps-to-accept; journals, ontology, living pages, and the adoption record kept as project files and not gitignored; operator-visible coverage, step counts, and sufficiency; fail-closed grounding on every write. Secrets in `.env` stay gitignored.
- **Out of scope**: training or swapping the underlying language model; changing how software questions are planned; changing substance-gate accept criteria; evolving the substance gate away; Role × Intent as the page unit; hosted multi-repo services; a new documentation theme.
- **Adjacent expectations**: explore-first planning, explore-then-write, substance gate, and question-organised assemble remain the generation core. Optional GitHub Pages publish modes remain available after a non-empty assemble. MCP tool names may be kept; the store must be living pages. HarnessX `MetaAgent.evolve` is the allowed evolution engine for harness configs (tools / processors / templates), not `harnessx.rl` model training.

## Requirements

### Requirement 1: Setup harness adopts the blueprint and manages ontology

**Objective:** As an operator, I want the harness to initialise and manage this project's ontology at setup, so that I start from the shipped blueprint adapted to this repository rather than a silent default.

#### Acceptance Criteria

1. When the operator runs setup on an existing project directory, DocuHarnessX shall start a setup harness that writes local project configuration including roles, intents, and subject prefixes, starting from the shipped blueprint.
2. When setup completes, DocuHarnessX shall record the blueprint's name and version in that local configuration and shall report the written paths and the adopted blueprint version.
3. If the project directory is missing or is not a directory, then DocuHarnessX shall refuse setup with a non-zero exit and shall not write configuration.
4. If local configuration already exists and the operator did not request overwrite, then DocuHarnessX shall refuse to overwrite it and shall report that the project already has an adopted blueprint.
5. While the setup harness runs, DocuHarnessX shall allow it to write only the project's local documentation-configuration files, not the rest of the target repository.
6. If no usable model is configured, then DocuHarnessX shall still seed the shipped blueprint without an agent, shall record the blueprint version, and shall tell the operator that ontology was not agent-managed.
7. When the operator later runs setup to manage ontology (without a full overwrite of living pages), DocuHarnessX shall let the setup harness propose and apply ontology edits that the ontology accepts, keeping the recorded blueprint name and version unless a different blueprint version is adopted.
8. When the operator runs setup on a terminal without requesting the non-interactive default, DocuHarnessX shall first complete the credential interview (Requirement 12), then have the setup harness produce proposed roles, intents, and subject prefixes from the shipped blueprint and the target repository, shall display those proposals, and shall require the operator to accept or change them before writing the ontology.
9. When the operator accepts a displayed proposal unchanged, DocuHarnessX shall write that proposal. When the operator changes a proposed term, DocuHarnessX shall write the operator's term instead, provided the ontology accepts it.

### Requirement 2: Operator can still adjust roles and ontology

**Objective:** As an operator, I want to change which roles, intents, and subject prefixes apply, so that the team can override what the setup harness proposed.

#### Acceptance Criteria

1. When the operator supplies a subset of roles, intents, or subject prefixes at setup, DocuHarnessX shall write only those terms into the local configuration.
2. When the operator later edits the local configuration's roles, intents, or subject prefixes to values the ontology accepts, DocuHarnessX shall load that edited vocabulary on the next run without requiring a new adopt.
3. If the local configuration names a role, intent, or subject prefix the ontology does not accept, then DocuHarnessX shall refuse the run or setup with a non-zero exit and shall name the invalid term.
4. When the operator adjusts the local vocabulary by hand, DocuHarnessX shall keep the recorded blueprint name and version unless the operator adopts a different blueprint version.

### Requirement 3: Later runs use the adopted project vocabulary

**Objective:** As an operator, I want subsequent documentation runs on this repository to use the project's adopted ontology, so that the living document stays aligned with the local contract.

#### Acceptance Criteria

1. When a documentation run starts in a project that has a valid adopted configuration, DocuHarnessX shall load that configuration as the vocabulary for the run.
2. If no local configuration is present, then DocuHarnessX shall run with the shipped default blueprint and shall tell the operator that the project has not adopted a blueprint yet.
3. The generator shall not require the operator to pass role names on the command line in order to run after setup.

### Requirement 4: Grow the document incrementally

**Objective:** As an operator, I want each run to add missing grounded pages rather than replace the whole site, so that the document can become sufficient over many sessions.

#### Acceptance Criteria

1. When a project already has living pages and the operator runs documentation without requesting a full regenerate, DocuHarnessX shall write pages only for planned questions that do not already have an accepted living page.
2. When a planned question already has an accepted living page, DocuHarnessX shall leave that page's body unchanged in that run.
3. When new pages are accepted, DocuHarnessX shall assemble the site from the full set of living pages (previously kept plus newly accepted), not from the new pages alone.
4. If the operator explicitly requests regeneration of a page or of all pages, then DocuHarnessX shall rewrite those pages through the explore-first writer and the substance gate.

### Requirement 5: Living pages are the source of truth

**Objective:** As an operator, I want refined and generated pages to live with the project, so that a throwaway output directory is not the only copy of the document.

#### Acceptance Criteria

1. When a page is accepted, DocuHarnessX shall persist it in the project's living page store (a documented location under the project directory).
2. When the operator publishes or assembles, DocuHarnessX shall build the site from the living page store.
3. The generator shall not treat a retired segment store as the source of truth for living pages.

### Requirement 6: Multi-step interactive refine

**Objective:** As an operator, I want a refine session that can take several steps on the same page, so that I am not limited to a single rewrite when the first pass is not enough.

#### Acceptance Criteria

1. When the operator starts interactive refine for a project, DocuHarnessX shall list living pages from the living page store.
2. When the operator opens a refine session on a named living page, DocuHarnessX shall allow multiple successive explore/write/gate cycles on that page in one session, each cycle using the operator's latest guidance and re-exploring the target repository.
3. If a cycle's body fails the substance gate, then DocuHarnessX shall keep the last accepted living page unchanged, shall report the rejection, and shall allow another cycle in the same session.
4. When a cycle's body passes the substance gate, DocuHarnessX shall replace that page in the living page store and shall record how many cycles that session used.
5. When the operator stops a session without an accepted cycle, DocuHarnessX shall leave the living page unchanged.
6. When the operator requests reassemble after a refine session, DocuHarnessX shall rebuild the site from the current living page store.
7. If no usable model is configured, then DocuHarnessX shall still list, get, and validate living pages, and shall refuse write cycles with an explicit no-model result rather than crashing.
8. DocuHarnessX shall report per-session step or cycle count so the operator can see how much work a refine took.

### Requirement 7: Fail-closed grounding on every write

**Objective:** As a reader, I want every kept page — first draft or later refine — to stay grounded in this repository, so that iteration cannot smuggle in ungrounded prose.

#### Acceptance Criteria

1. The generator shall apply the same substance gate to every refine cycle that it applies to a batch write.
2. If a write or refine cycle is empty, times out, or is rejected, then DocuHarnessX shall omit or keep-previous rather than publish a substitute outline.
3. DocuHarnessX shall not echo the operator's refinement guidance as a heading or quoted block in the published page.

### Requirement 8: Sufficiency is visible and operator-declared

**Objective:** As an operator, I want to see what is still missing and to declare when the document is sufficient, so that "done" is a project decision rather than a single batch finishing.

#### Acceptance Criteria

1. When the operator asks for documentation status on a project, DocuHarnessX shall report the adopted blueprint version (or that none is adopted), the planned question ids, which of those have living pages, which were omitted and why, and which planned questions still have no living page.
2. When every planned question has a living page, DocuHarnessX shall report that generation coverage is complete for the current plan without implying the operator has declared the document sufficient.
3. When the operator declares the document sufficient, DocuHarnessX shall record that declaration with a timestamp in the local project configuration.
4. When the operator declares the document not sufficient, or has never declared, DocuHarnessX shall report the document as not yet sufficient.
5. A later documentation run that changes living pages shall not silently keep a previous sufficient declaration; DocuHarnessX shall mark sufficiency as stale until the operator declares again.

### Requirement 9: Optional publish after a non-empty assemble

**Objective:** As an operator, I want the existing publish modes to still work on the living document, so that a sufficient site can be previewed or published without a separate generator.

#### Acceptance Criteria

1. When the living page store has at least one accepted page and the operator requests assemble or publish, DocuHarnessX shall emit the question-organised site from those pages.
2. Where a publish mode is requested, DocuHarnessX shall use the existing publish modes after a non-empty assemble.
3. If the living page store is empty, then DocuHarnessX shall not emit a documentation site shell and shall still write or show the status report.

### Requirement 10: Evolve the harness to reduce refine steps

**Objective:** As an operator, I want the harness to get better at this project's refine work over time, so that pages that used to take many cycles take fewer.

#### Acceptance Criteria

1. When enough refine-session traces exist for a project, DocuHarnessX shall be able to run a harness-evolution pass that proposes a new harness configuration from those traces.
2. The evolution pass shall target fewer cycles or steps to a gate-accepted page on similar refine work, and shall report before/after step counts on a documented comparison.
3. If the proposed harness would skip or weaken the substance gate, then DocuHarnessX shall reject that proposal and keep the current harness.
4. When evolution produces a candidate that passes the comparison gate, DocuHarnessX shall store it as the project's current refine/setup harness without rewriting living pages as a side effect.
5. DocuHarnessX shall not require training or replacing the underlying language model in order to evolve the harness.
6. If traces are insufficient or evolution fails, then DocuHarnessX shall keep the current harness and shall report that no evolution was applied.

### Requirement 11: Evolution must not become a second generator

**Objective:** As an operator, I want evolved harnesses to still write through the explore-first path, so that “fewer steps” never means ungrounded pages.

#### Acceptance Criteria

1. DocuHarnessX shall not create documentation pages whose identity is a reader role combined with an intent in the absence of a software question.
2. An evolved refine harness shall still re-explore the target repository and shall still pass the substance gate before a living page is replaced.
3. Setup-harness ontology writes shall still be rejected when the resulting vocabulary is invalid.
4. Interactive refine shall not be a second generation engine with a different gate than batch write.

### Requirement 12: Interactive credentials at setup

**Objective:** As an operator, I want setup to ask for the model endpoint once, with DeepSeek as the Enter default, so that I can run the harness without hand-writing `.env` first.

#### Acceptance Criteria

1. When the operator runs setup on a terminal without requesting the non-interactive default, DocuHarnessX shall ask for an API key, a base URL, and a model id before running the setup harness.
2. The base-URL prompt shall show `https://api.deepseek.com` as the suggested default. If the operator answers empty, then DocuHarnessX shall use that URL.
3. The model-id prompt shall show the shipped DeepSeek default model id as the suggested default. If the operator answers empty, then DocuHarnessX shall use that model id.
4. If an API key is already present in the process environment or in the project's `.env`, then DocuHarnessX shall display it only as `***` and shall never print the full secret.
5. When an API key is already present, if the operator answers empty or answers `***`, then DocuHarnessX shall keep the existing key.
6. DocuHarnessX shall write accepted credentials only to the project's `.env` file, which remains ignored by version control.
7. If setup is not interactive (the non-interactive default, or no terminal), then DocuHarnessX shall not prompt for credentials and shall not print secrets.
8. If the operator leaves the API key empty and no key already exists, then DocuHarnessX shall continue as a no-model setup (Requirement 1.6) rather than writing a blank secret.

### Requirement 13: Journals are project artifacts

**Objective:** As an operator, I want refine and setup journals in the repository so evolution can run from history the team actually keeps.

#### Acceptance Criteria

1. When a setup or refine session finishes, DocuHarnessX shall write a journal under a documented path in the project directory.
2. DocuHarnessX shall not hide that journal path from version control.
3. If ignore rules would otherwise hide the project's documentation store, then DocuHarnessX shall still keep journals, ontology, living pages, and the adoption record eligible for version control, while keeping secrets ignored.
4. Evolution (Requirement 10) shall read those journals from the project path, not from a hidden cache alone.
