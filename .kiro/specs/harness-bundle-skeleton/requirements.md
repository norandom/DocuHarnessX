# Requirements Document

## Introduction

DocuHarnessX is a role-based documentation generator built as a HarnessX bundle plus a
`dhx` CLI. This feature delivers the runnable skeleton — the chassis — onto which every
later pipeline stage (ingest, analyze, classify, plan, write, review, assemble, deploy)
attaches as a processor or processor group. The skeleton must compose a behavior pipeline
(`make_docgen()` returning a `HarnessConfig`) that includes baseline safety/cost control
and an observability journal, bind it to a model, and expose a CLI that runs an empty,
no-op pipeline end-to-end against a target repository while emitting an auditable trace.

The deliverable is intentionally behavior-free for documentation generation: the eight
stages are registered as no-ops so that the registration mechanism, the run lifecycle, the
data-passing contract (harness state/slots plus the segment store interface), the
project-configurable ontology vocabulary loading, and the packaging are all proven and
stable before Wave 1 work begins. The acceptance signal is a clean end-to-end run:
`dhx /home/mc/Source/malware_hashes --out /tmp/out` runs, writes a HarnessJournal trace,
and exits cleanly; plus `dhx init` produces a valid `.docuharnessx/ontology.yaml`.

The ontology vocabulary (roles, intents, subjects/tags) is **project-configurable** to keep
the `make_docgen` harness reusable across projects. The vocabulary schema and the shipped
default profile are owned by `ontology-engine`; this skeleton owns only the *setup* and
*loading* interaction: a `dhx init` command that writes a per-project
`.docuharnessx/ontology.yaml`, and run-start loading of that file into the run context so
stages can read the active `Vocabulary`.

## Boundary Context

- **In scope**: the installable `docuharnessx` package with `uv`/`pyproject.toml`
  depending on `harnessx`; sole ownership of the **package root** — `pyproject.toml` and
  `docuharnessx/__init__.py`; `make_docgen()` composing a `HarnessConfig` with baseline
  Control (cost guard + loop detection) and Observe (HarnessJournal); model binding via
  `ModelConfig(main=...).agentic(make_docgen())` with model resolved from config/env; the
  `dhx <target-repo> [--out DIR] [--config YAML]` CLI; a `dhx init` command that writes a
  per-project `.docuharnessx/ontology.yaml` (interactively or by seeding the default
  profile) via the `ontology-engine` vocabulary/default-profile API; run-start loading of
  `.docuharnessx/ontology.yaml` through the `ontology-engine` loader into a `Vocabulary`
  placed in the run context; eight no-op stage stubs registered at defined hook points in a
  defined order; the stage-registration contract and the data-passing contract over harness
  state/slots; the configuration surface (target repo, output dir, role selection derived
  from the loaded `Vocabulary`, model selection, cost/step budgets).
- **Out of scope**: actual repo scanning, classification, writing, review, assembly, and
  deploy logic (later specs); the ontology/segment frontmatter schema, the **ontology
  vocabulary schema**, the **default profile content**, the **vocabulary YAML
  loader/serializer**, and the segment store implementation itself (all owned by
  `ontology-engine`); MkDocs site assembly and GitHub Pages deployment.
- **Adjacent expectations**: the segment store **interface** and the **`Vocabulary` model,
  its YAML loader, and the default-profile API** are owned by `ontology-engine`; this
  feature consumes them at the contract level only and must not reimplement or redefine
  them. The skeleton derives valid roles/intents/subjects from the **loaded `Vocabulary`**
  (imported from `ontology-engine`) — it must not hardcode a fixed ten-role list or define a
  `RoleId` alias independent of the ontology. Package-root ownership: this spec **solely**
  owns `pyproject.toml` and `docuharnessx/__init__.py`; `ontology-engine` only creates
  `docuharnessx/ontology/*` and must not touch the package root.

## Requirements

### Requirement 1: Installable Package and Environment

**Objective:** As a DocuHarnessX maintainer, I want an installable Python package scaffolded with `uv` and depending on HarnessX, so that the generator can be developed, installed, and run as a real HarnessX bundle.

#### Acceptance Criteria

1. The DocuHarnessX package shall declare a project manifest that names the distribution, targets Python 3.12, and declares `harnessx` as a runtime dependency.
2. When the package is installed in editable mode into a Python 3.12 environment, the DocuHarnessX package shall be importable and shall expose the `dhx` command on the environment path.
3. The DocuHarnessX package shall provide a top-level package containing the bundle composition module, the CLI module, and the eight pipeline stage sub-packages (ingest, analyze, classify, plan, write, review, assemble, deploy).
4. If a required runtime dependency is unavailable at import time, then the DocuHarnessX package shall fail with an explicit error that names the missing dependency rather than failing silently.
5. This feature shall be the sole owner of the package root — `pyproject.toml` and `docuharnessx/__init__.py` — so that the `ontology-engine` feature (which creates only `docuharnessx/ontology/*`) does not collide with the package-root files.

### Requirement 2: Bundle Composition via make_docgen

**Objective:** As a pipeline stage author, I want `make_docgen()` to return a composed `HarnessConfig` with baseline control and observability, so that I have a stable chassis to register my stage's processor into.

#### Acceptance Criteria

1. When `make_docgen()` is invoked, the bundle composer shall return a `HarnessConfig` produced through the HarnessX builder using the `|` composition operator.
2. The returned `HarnessConfig` shall include a baseline Control capability that provides cost-guard and loop-detection behavior suitable for repositories in the 25–40k LOC range.
3. The returned `HarnessConfig` shall include an Observe capability that writes HarnessJournal JSONL traces for each run.
4. The `HarnessConfig` returned by `make_docgen()` shall not contain any model or model-provider binding.
5. While composing the pipeline, if two composed capabilities declare conflicting singleton behavior, the bundle composer shall surface the HarnessX conflict error rather than silently overwriting a capability.
6. When a stage processor is added to the pipeline, the bundle composer shall append it to the relevant hook without replacing processors already registered on that hook.

### Requirement 3: Model Binding and Resolution

**Objective:** As an operator running the generator, I want the model bound separately from the behavior pipeline and resolved from configuration or environment, so that I can choose a model without editing the bundle.

#### Acceptance Criteria

1. The runnable generator shall be produced by binding a model to `make_docgen()` via the `ModelConfig(main=...).agentic(...)` pattern, with the model never embedded in the `HarnessConfig`.
2. When the operator provides a model identifier through the configuration file, the generator shall use that model.
3. When no model is specified in the configuration file, the generator shall resolve the model from environment variables following HarnessX conventions.
4. If no model can be resolved from configuration or environment, then the CLI shall exit with a non-zero status and an explicit message stating that no model is configured.

### Requirement 4: dhx CLI and End-to-End Run

**Objective:** As an operator, I want a `dhx` command that takes a target repository and runs the pipeline, so that I can generate documentation (eventually) and verify the skeleton runs cleanly today.

#### Acceptance Criteria

1. The `dhx` CLI shall accept a required target-repository path argument and the optional flags `--out DIR` and `--config YAML`.
2. When invoked with a target repository, the `dhx` CLI shall record the target repository path into the harness run state so that registered stages can read it.
3. When invoked, the `dhx` CLI shall execute the composed pipeline once from start to finish.
4. When the run completes, the `dhx` CLI shall write a HarnessJournal trace into the resolved output directory.
5. Where `--out DIR` is provided, the `dhx` CLI shall write run artifacts and the journal under that directory; where it is omitted, the CLI shall use a documented default output location.
6. When the empty pipeline run completes without error, the `dhx` CLI shall exit with a zero status code.
7. If the target-repository path does not exist or is not a directory, then the `dhx` CLI shall exit with a non-zero status and an explicit error identifying the invalid path before starting a run.
8. When invoked as `dhx /home/mc/Source/malware_hashes --out /tmp/out`, the `dhx` CLI shall run the empty pipeline end-to-end, emit a HarnessJournal JSONL trace under `/tmp/out`, and exit cleanly.

### Requirement 5: Stage Registration Contract

**Objective:** As a pipeline stage author, I want a defined way to register my stage into the pipeline at a known hook point and execution order, so that stages compose predictably without conflicting with one another.

#### Acceptance Criteria

1. The skeleton shall define a stage-registration contract that specifies the hook point and relative execution order at which a stage's processor attaches to the pipeline.
2. The skeleton shall register all eight pipeline stages (ingest, analyze, classify, plan, write, review, assemble, deploy) through this contract.
3. While the skeleton ships no documentation-generation logic, each registered stage shall be a no-op that participates in the run lifecycle without modifying generated content.
4. When the pipeline runs, the stage-registration contract shall cause stages to execute in the canonical pipeline order ingest → analyze → classify → plan → write → review → assemble → deploy.
5. When a new stage processor is registered, the registration contract shall append it without replacing previously registered stage processors on the same hook.
6. The skeleton shall expose the registration points such that a Wave 1+ stage can replace a no-op stub with real behavior without changing the bundle composition entry point.

### Requirement 6: Data-Passing Contract Between Stages

**Objective:** As a pipeline stage author, I want stages to exchange data through harness state/slots and the segment store interface rather than globals, so that stages stay decoupled and the data flow is auditable.

#### Acceptance Criteria

1. The skeleton shall define a data-passing contract in which stages read and write run data exclusively through harness state/slots and the segment store interface.
2. When the CLI starts a run, the skeleton shall make the target-repository path and the resolved output directory available to stages through harness state/slots.
3. The skeleton shall consume the segment store interface from `ontology-engine` at the contract level by importing `SegmentStore` from `docuharnessx.ontology.store` and co-importing `AxisFilter` and `Segment` from `docuharnessx.ontology`, and shall not reimplement or redefine that interface or add any storage logic.
4. While the segment store implementation is not the responsibility of this feature, the skeleton shall expose how a stage obtains a segment store handle from the run context, where the handle conforms exactly to the `ontology-engine` signatures `put(segment) -> None`, `query(where: AxisFilter) -> tuple[Segment, ...]`, `list_segments() -> tuple[Segment, ...]`, and `resolve_cross_links(segment_id: str) -> tuple[Segment, ...]`.
5. If a stage requests a state slot that has not been set, then the data-passing contract shall return an explicit absent result rather than an undefined value.
6. If the `ontology-engine` `SegmentStore` symbol is not yet importable when this feature is implemented, then the skeleton shall use a typing-only fallback alias that mirrors those four signatures verbatim, replaced by the real import once `ontology-engine` publishes the symbol.

### Requirement 7: Configuration Surface

**Objective:** As an operator, I want to control target repository, output directory, role selection, model, and budgets through configuration, so that I can tune runs without code changes.

#### Acceptance Criteria

1. The configuration surface shall accept the target-repository path, the output directory, a role selection, a model selection, and cost and step budgets.
2. The configuration surface shall derive the set of valid roles from the loaded `Vocabulary` (imported from `ontology-engine`) and shall not hardcode a fixed role list; where no role selection is provided, the configuration surface shall default to all roles present in the loaded `Vocabulary`.
3. When a role selection (via `--roles` or the config file) names a role that is not in the loaded `Vocabulary`, the CLI shall exit with a non-zero status and an explicit message listing the valid roles.
4. When a `--config YAML` file is provided, the CLI shall load configuration values from it and shall let command-line arguments override file values for any overlapping setting.
5. When cost and step budgets are configured, the generator shall apply them to the run through the baseline Control capability.
6. If the configuration file is malformed or contains an unknown setting, then the CLI shall exit with a non-zero status and an explicit message identifying the problem.

### Requirement 8: Run Observability and Clean Exit

**Objective:** As an operator, I want every run to produce an auditable journal and a clear exit status, so that I can confirm what happened and integrate the CLI into scripts.

#### Acceptance Criteria

1. When a run executes, the Observe capability shall record run lifecycle events to a HarnessJournal JSONL trace.
2. The HarnessJournal trace shall record, at minimum, the start and end of the run and the participation of each registered stage.
3. When a run completes successfully, the CLI shall report the location of the written journal trace.
4. If the run terminates because a configured cost or step budget is exceeded, then the CLI shall exit with a non-zero status and the journal shall record the budget-exceeded outcome.
5. If the run fails with an unexpected error, then the CLI shall exit with a non-zero status and surface an explicit error message.

### Requirement 9: Per-Project Ontology Setup via `dhx init`

**Objective:** As an operator onboarding a new project, I want a `dhx init` command that creates a per-project ontology config, so that the same reusable harness adapts its roles, intents, and tags to my project.

#### Acceptance Criteria

1. The `dhx` CLI shall provide an `init` subcommand that produces a per-project `.docuharnessx/ontology.yaml` for the current (or specified) project directory.
2. When run interactively, `dhx init` shall ask which roles exist, what the intents are, and which tags/subjects apply, and shall assemble the answers into a `Vocabulary` using the `ontology-engine` vocabulary API.
3. Where the operator declines interactive entry or requests a default setup, `dhx init` shall seed the shipped default profile by calling the `ontology-engine` default-profile API.
4. The `dhx init` command shall delegate schema serialization to the `ontology-engine` `vocabulary_to_config(vocab) -> dict` API to convert the resulting `Vocabulary` into a config dict matching the `.docuharnessx/ontology.yaml` schema, then shall write that dict to `.docuharnessx/ontology.yaml` as YAML; the skeleton owns only writing the file and shall not reimplement the vocabulary schema, the default profile, or assemble the config schema itself.
5. When `dhx init` completes, the written `.docuharnessx/ontology.yaml` shall be a valid vocabulary file that the `ontology-engine` loader can load without error.
6. If a `.docuharnessx/ontology.yaml` already exists, then `dhx init` shall not overwrite it silently and shall require an explicit overwrite confirmation or flag.

### Requirement 10: Run-Start Ontology Loading into Run Context

**Objective:** As a pipeline stage author, I want the active project vocabulary loaded into the run context at run start, so that my stage can read the project's roles, intents, and subjects without owning the ontology.

#### Acceptance Criteria

1. When a `dhx <repo>` run starts, the skeleton shall load `.docuharnessx/ontology.yaml` from the project via the `ontology-engine` loader and build a `Vocabulary`.
2. When the vocabulary is loaded, the skeleton shall place the `Vocabulary` into the harness run context (state/slots / `RunContext`) so that registered stages can read it.
3. If no `.docuharnessx/ontology.yaml` exists for the project, then the skeleton shall fall back to the `ontology-engine` default profile and shall hint the operator to run `dhx init`.
4. If the `.docuharnessx/ontology.yaml` file exists but fails to load against the `ontology-engine` loader, then the CLI shall exit with a non-zero status and an explicit message identifying the invalid vocabulary file.
5. The skeleton shall obtain the `Vocabulary`, its loader, and the default profile exclusively from `ontology-engine` and shall not reimplement the vocabulary schema, loader, or default profile.
