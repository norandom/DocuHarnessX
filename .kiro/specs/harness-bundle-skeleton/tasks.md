# Implementation Plan

- [x] 1. Foundation: package scaffold, environment, shared types, and errors
- [x] 1.1 Scaffold the installable package and uv manifest (sole package-root owner)
  - Create `pyproject.toml` naming the distribution, targeting Python 3.12, declaring `harnessx` as a runtime dependency and a YAML parser dependency (for `--config` only), and registering the `dhx` console-script entry point.
  - Create the `docuharnessx/` package with `__init__.py` and the empty `stages/` sub-package, plus a `tests/` directory.
  - This task is the **sole owner** of the package root: `pyproject.toml` and `docuharnessx/__init__.py`. Do not create `docuharnessx/ontology/*` here — that package is owned by `ontology-engine`. The two specs must not collide on the package root.
  - Observable completion: `uv pip install -e .` into a Python 3.12 env succeeds, `import docuharnessx` works, and `dhx --help` runs from the environment path.
  - _Requirements: 1.1, 1.2, 1.3, 1.5_
  - _Boundary: pyproject (OWNED HERE), docuharnessx/__init__.py (OWNED HERE), package layout_

- [x] 1.2 Define shared types, slot-key constants, and explicit error types
  - Add `types.py` with `StageName` and the slot-key constants (target repo, output dir, segment-store handle, and `SLOT_VOCABULARY`). Do NOT define a `RoleId` alias or any fixed role list — roles are derived from the loaded `Vocabulary` (imported from `ontology-engine`).
  - Add `errors.py` with `ConfigError`, `ModelResolutionError`, `TargetRepoError`, `DependencyError`, and `OntologyConfigError`.
  - Observable completion: importing `docuharnessx.types` and `docuharnessx.errors` exposes all named constants and error classes (including `SLOT_VOCABULARY` and `OntologyConfigError`) and no `RoleId` alias; a unit import test passes.
  - _Requirements: 1.4, 6.2_
  - _Boundary: types, errors_

- [x] 2. Core: configuration, model resolution, context, and stage stubs
- [x] 2.1 (P) Implement the configuration surface and precedence
  - Add `config.py` with a `DocgenConfig` holding target repo, output dir, role selection, model selection, and cost/step budgets; load from YAML and apply CLI-argument overrides for overlapping settings.
  - Derive valid roles from the loaded `Vocabulary` (passed in / imported from `ontology-engine`); default the role selection to all roles in that `Vocabulary` when none is provided; raise `ConfigError` listing valid roles when a selected role is not in the `Vocabulary`; raise `ConfigError` on malformed YAML or unknown settings. Do NOT hardcode a ten-role list.
  - Observable completion: a unit test loads a YAML config, overrides a value via a CLI-arg dict, sees the override win, sees the role default equal to the `Vocabulary` roles when roles are omitted, gets `ConfigError` (listing valid roles) for a role not in the `Vocabulary`, and gets `ConfigError` on a malformed/unknown-key file.
  - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.6_
  - _Depends: 2.4_
  - _Boundary: DocgenConfig_

- [x] 2.2 (P) Implement model resolution with config-then-env precedence
  - Add `model_resolver.py` that builds a `ModelConfig` from the configured model identifier first, then from provider environment variables per HarnessX conventions.
  - Raise `ModelResolutionError` with an explicit message when no model can be resolved.
  - Observable completion: a unit test resolves a model from config, falls back to a set env var when config is empty, and raises `ModelResolutionError` when both are absent.
  - _Requirements: 3.2, 3.3, 3.4_
  - _Boundary: ModelResolver_

- [x] 2.3 (P) Implement the RunContext data-passing seam
  - Add `context.py` with `RunContext` providing typed setters/getters over harness state slots for the target-repo path and output dir using the slot-key constants, returning `None` for absent slots.
  - Add a `segment_store()` accessor returning the handle typed by the consumed `SegmentStore` interface, and a `vocabulary()` accessor returning the loaded `Vocabulary` stored at `SLOT_VOCABULARY` (both imported via `docuharnessx.ontology`).
  - Observable completion: a unit test round-trips the target-repo and output-dir slots, gets `None` for an unset slot, retrieves a segment-store handle of the interface type, and retrieves the slotted `Vocabulary` via `vocabulary()`.
  - _Requirements: 6.1, 6.2, 6.4, 6.5, 10.2_
  - _Depends: 2.4_
  - _Boundary: RunContext_

- [x] 2.4 (P) Consume the ontology-engine interfaces at the contract level (pinned imports)
  - Add `ontology.py` (the single re-export site) that PINS these exact imports and adds NO storage, schema, loader, or profile logic:
    - `from docuharnessx.ontology.store import SegmentStore`
    - co-import `AxisFilter` and `Segment` from `docuharnessx.ontology` (or `.ontology.store`)
    - re-export `Vocabulary`, the vocabulary loader (`load_vocabulary`), the inverse serializer (`vocabulary_to_config`), and the default-profile API (`default_profile`) from `ontology-engine`.
  - The `SegmentStore` the skeleton relies on has exactly these signatures: `put(segment) -> None`, `query(where: AxisFilter) -> tuple[Segment, ...]`, `list_segments() -> tuple[Segment, ...]`, `resolve_cross_links(segment_id: str) -> tuple[Segment, ...]`. If `ontology-engine` has not yet published `SegmentStore`/`Vocabulary`/loader, declare a typing-only fallback alias under the same symbol that MIRRORS those four signatures VERBATIM, with a comment marking the revalidation trigger.
  - Observable completion: importing `docuharnessx.ontology` exposes `SegmentStore`, `AxisFilter`, `Segment`, `Vocabulary`, the loader, and the default-profile symbol, and contains no concrete store/schema/loader implementation; a unit test asserts the re-exports and that no storage class is defined locally.
  - _Requirements: 6.3, 6.4, 6.6, 10.5_
  - _Depends: ontology-engine `store` (SegmentStore/AxisFilter/Segment) task; ontology-engine `Vocabulary` model + YAML loader + default-profile task_
  - _Boundary: ontology (re-export only; ontology-engine owns docuharnessx/ontology/*)_

- [x] 2.5 (P) Implement the no-op stage stubs and the stage base
  - Add `stages/base.py` with the `PIPELINE_HOOK` constant and a shared no-op stage factory whose processor yields the lifecycle event unchanged and modifies no generated content.
  - Add the eight stage modules (ingest, analyze, classify, plan, write, review, assemble, deploy), each producing a no-op processor via the shared factory in its own file so a later spec can replace exactly one stub.
  - Observable completion: a unit test instantiates each of the eight stage processors, runs the hook, and asserts each is a pass-through that leaves run content unchanged.
  - _Requirements: 5.2, 5.3_
  - _Boundary: Stage stubs, stages/base_

- [x] 2.6 (P) Implement run-start ontology loading into the run context
  - Add `ontology_loader.py` with `load_project_vocabulary(project_dir) -> tuple[Vocabulary, bool]` that locates `.docuharnessx/ontology.yaml` and loads it via the `ontology-engine` loader; when the file is absent, return the `ontology-engine` default-profile `Vocabulary` with `used_default=True`; when a present file fails to load, raise `OntologyConfigError`. Reimplement neither the schema, loader, nor default profile.
  - Observable completion: a unit test loads a valid ontology file into a `Vocabulary`, gets the default profile with `used_default=True` when the file is absent, and gets `OntologyConfigError` for a present-but-invalid file.
  - _Requirements: 10.1, 10.3, 10.4, 10.5_
  - _Depends: 2.4_
  - _Boundary: OntologyLoader_

- [x] 2.7 (P) Implement the `dhx init` ontology setup helpers
  - Add `ontology_setup.py` with `run_init(project_dir, *, use_default=False, force=False, answers=None) -> str` that builds a `Vocabulary` either interactively (roles, intents, tags/subjects) or by seeding the `ontology-engine` default profile (`default_profile()`), then calls the `ontology-engine` `vocabulary_to_config(vocab) -> dict` API to obtain a config dict matching the `.docuharnessx/ontology.yaml` schema, and writes that dict to `.docuharnessx/ontology.yaml` as YAML, returning the written path. Schema serialization is delegated to `vocabulary_to_config`; the skeleton owns only the file write and must NOT assemble the config schema itself or use a Segment serializer. Refuse to overwrite an existing file unless `force=True`. After writing, round-trip-load the file via `load_vocabulary` to prove validity. Reimplement neither the schema nor the default profile.
  - Observable completion: writes a valid `.docuharnessx/ontology.yaml` that the `ontology-engine` `load_vocabulary` loader accepts (loads without error) — verified for both a default-profile file and an interactive-answers file; a test asserts a second call without `force` refuses to overwrite.
  - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6_
  - _Depends: 2.4; ontology-engine `Vocabulary` model + `vocabulary_to_config` + `default_profile` task_
  - _Boundary: OntologySetup (dhx init)_

- [x] 3. Stage registration and bundle composition
- [x] 3.1 Implement the stage-registration contract and canonical ordering
  - Add `stages/__init__.py` with the ordered `STAGES` list mapping each `StageName` to its stage factory in canonical order ingest → analyze → classify → plan → write → review → assemble → deploy, and a `register_stages(builder)` helper.
  - Append each stage processor on `PIPELINE_HOOK` using append-don't-replace semantics so pre-existing processors on the hook are retained ahead of the stages.
  - Observable completion: a unit test runs `register_stages` on a builder, then asserts the resulting hook contains the eight stages in canonical order and that a processor pre-added to the hook is preserved.
  - _Requirements: 5.1, 5.4, 5.5, 5.6_
  - _Depends: 2.5_
  - _Boundary: StageRegistry_

- [x] 3.2 Implement make_docgen bundle composition
  - Add `bundle.py` with `make_docgen(...)` composing a `HarnessBuilder()` with the baseline Control bundle (cost-guard + loop-detection tuned for 25–40k LOC repos) and the stage registry using the `|` operator, and wiring Observe by setting the config tracer to a `HarnessJournal` rooted at the resolved output directory.
  - Return a `HarnessConfig` with no model binding; let HarnessX conflict detection surface `HarnessConflictError` on conflicting singleton capabilities.
  - Centralize all HarnessX imports in this module per the design's drift-mitigation note.
  - Observable completion: a unit test asserts `make_docgen()` returns a `HarnessConfig` that has no model binding, exposes the pipeline hook with the eight stages, and carries a journal tracer; composing two conflicting control capabilities raises `HarnessConflictError`.
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 8.1_
  - _Depends: 3.1_
  - _Boundary: make_docgen_

- [x] 4. Integration: the dhx CLI and run orchestration
- [x] 4.1 Implement the dhx CLI argument parsing, validation, ontology loading, and model binding
  - Add `cli.py` exposing the `dhx` entry point with two subcommands: the run command parsing `<target-repo>`, `--out DIR`, `--config YAML`, and `--roles`, and an `init` subcommand parsing `[project-dir]`, `--default`, and `--force`.
  - For the run command: validate the target path is an existing directory before any run; load the project vocabulary via `load_project_vocabulary(...)` (default-profile fallback + `dhx init` hint when absent; `OntologyConfigError` exit on invalid file); load config (YAML then CLI overrides) and validate `--roles`/config roles against the loaded `Vocabulary`; resolve the model via the resolver.
  - Bind the model with `ModelConfig(main=...).agentic(make_docgen(...))`, keeping the model out of the `HarnessConfig`, and apply configured cost/step budgets through the baseline Control capability.
  - Observable completion: a unit test invokes `main` with a bad target path and gets a non-zero return and an explicit `TargetRepoError` message before any run; another asserts the model is bound via `.agentic(...)` and not present in the `HarnessConfig`; another asserts a `--roles` value not in the loaded `Vocabulary` exits non-zero listing valid roles; another asserts a present-but-invalid ontology file exits non-zero with `OntologyConfigError`.
  - _Requirements: 3.1, 4.1, 4.7, 7.3, 7.5, 10.1, 10.3, 10.4_
  - _Depends: 2.1, 2.2, 2.6, 3.2_
  - _Boundary: dhx CLI_

- [x] 4.2 Orchestrate the end-to-end run, journaling, reporting, and exit codes
  - In `cli.py`, populate the run-context slots (target-repo path, output dir, loaded `Vocabulary` at `SLOT_VOCABULARY`) before the run, execute the composed pipeline once with a minimal skeleton `BaseTask`, and write the HarnessJournal trace under the resolved output directory (documented default when `--out` is omitted).
  - Report the journal path on success and map exit reasons to exit codes: `done` → 0; `budget_exceeded`, unexpected error, unresolved model, bad config, invalid ontology, and unknown role → non-zero, with the budget-exceeded outcome recorded in the journal.
  - Observable completion: a unit/integration test runs `main` on a temp repo dir, sees slots populated (including the vocabulary slot), a journal file written under the out dir, the journal path reported, and exit 0; a simulated `budget_exceeded` result yields a non-zero exit.
  - _Requirements: 4.2, 4.3, 4.4, 4.5, 4.6, 8.3, 8.4, 8.5, 10.2_
  - _Depends: 4.1, 2.3_
  - _Boundary: dhx CLI_

- [x] 4.3 Wire the `dhx init` subcommand to ontology setup
  - In `cli.py`, dispatch `dhx init` to `OntologySetup.run_init(...)`, passing the resolved project dir, `--default`/interactive choice, and `--force`; report the written `.docuharnessx/ontology.yaml` path on success; map a refused overwrite (existing file, no `--force`) to a non-zero exit with an explicit message.
  - Observable completion: a unit/integration test runs `dhx init --default` in a temp project, sees a `.docuharnessx/ontology.yaml` written, exit 0, and the path reported; a second `dhx init` without `--force` exits non-zero.
  - _Requirements: 9.1, 9.2, 9.3, 9.6_
  - _Depends: 2.7_
  - _Boundary: dhx CLI_

- [x] 5. Validation: end-to-end acceptance and observability
- [x] 5.1 End-to-end acceptance test on the empty pipeline and `dhx init`
  - Add `tests/test_cli_e2e.py` running `dhx <target-repo> --out DIR` against a directory target and asserting the empty pipeline runs start to finish, a HarnessJournal JSONL trace is written under DIR, the journal records run start/end and the participation of all eight stages in canonical order, and the process exits 0.
  - Add an acceptance case running `dhx init` in a fresh project and asserting it writes a `.docuharnessx/ontology.yaml` that the `ontology-engine` loader loads without error.
  - Include the acceptance invocation form `dhx /home/mc/Source/malware_hashes --out /tmp/out` as the reference path the test mirrors (using a fixture/temp dir when the reference repo is unavailable in CI).
  - Observable completion: the E2E tests pass, demonstrating a clean end-to-end run with a journal trace under the output directory and exit 0, plus a valid `.docuharnessx/ontology.yaml` produced by `dhx init`.
  - _Requirements: 4.8, 8.1, 8.2, 9.1, 9.5_
  - _Depends: 4.2, 4.3_
  - _Boundary: dhx CLI, make_docgen, StageRegistry, OntologySetup_

- [x] 5.2 Validation tests for failure paths and stage replaceability
  - Verify the bad-target-path failure exits non-zero before any run, the unresolved-model and malformed-config paths exit non-zero with explicit messages, the unknown-role and invalid-ontology paths exit non-zero with explicit messages, the absent-ontology path falls back to the default profile with a `dhx init` hint, and swapping one stage factory changes only that stage in the registry without editing the bundle entry point.
  - Observable completion: tests pass for each failure/fallback path (non-zero exit + explicit message, or default-profile fallback + hint) and for single-stage replaceability with `make_docgen` unchanged.
  - _Requirements: 3.4, 5.6, 7.3, 7.6, 8.4, 8.5, 10.3, 10.4_
  - _Depends: 5.1_
  - _Boundary: dhx CLI, StageRegistry, ModelResolver, DocgenConfig, OntologyLoader_
