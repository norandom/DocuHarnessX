# Research & Design Decisions — harness-bundle-skeleton

## Summary
- **Feature**: `harness-bundle-skeleton`
- **Discovery Scope**: New Feature (greenfield package) built as a consumer/extension of
  the HarnessX library.
- **Key Findings**:
  - HarnessX cleanly separates behavior (`HarnessConfig`) from model binding
    (`ModelConfig.agentic(...)`); the skeleton must keep the model out of `make_docgen()`.
  - HarnessX already provides cost-guard, loop-detection, and HarnessJournal — the
    skeleton should compose existing bundles/processors, not build its own.
  - There is no first-class "ordered pipeline stage" abstraction in HarnessX; stages must
    be expressed as ordered processors on a single hook, exploiting HarnessX's
    intra-hook ordering guarantee.
  - The ontology vocabulary (roles/intents/subjects) is project-configurable and owned by
    `ontology-engine`; this skeleton must invoke ontology-engine's vocabulary/default-profile
    API for `dhx init` and its loader at run start, never reimplement the schema or profile,
    and place the loaded `Vocabulary` into `RunContext` for stages to read.

## Research Log

### HarnessX composition model
- **Context**: Determine the correct API for `make_docgen()` and model binding.
- **Sources Consulted**: `/tmp/HarnessX_investigate/docs/agents.md`,
  `docs/architecture.md`, `README.md`, `harnessx/core/builder.py`,
  `harnessx/core/model_config.py`, `harnessx/core/state.py`.
- **Findings**:
  - `HarnessBuilder() | bundle_a | bundle_b` then `.build()` returns a `HarnessConfig`;
    composition runs exhaustive conflict detection (`HarnessConflictError`) on
    `_singleton_group` collisions — no silent overwrites.
  - Model binding is `ModelConfig(main=provider).agentic(harness_config)` (or
    `provider.agentic(config)`). `HarnessConfig` has **no** `model_provider` field.
  - State carries a free-form slot store: `state.set_slot(key, slot_type, content)` /
    `state.get_slot(key) -> StateSlot | None`. `get_slot` returns `None` when absent.
- **Implications**: `make_docgen()` composes bundles via `|`; the CLI binds the model
  separately; stages read/write run data through `state` slots; the data-passing contract
  can rely on `get_slot` returning `None` for absent slots (Requirement 6.5).

### Control (cost guard + loop detection)
- **Context**: Requirement 2.2 / 7.4 / 8.4 — baseline Control for 25–40k LOC repos.
- **Sources Consulted**: `harnessx/bundles/control.py`,
  `harnessx/processors/control/cost_guard.py`,
  `harnessx/processors/control/loop_detection.py`.
- **Findings**:
  - `make_control(...)` returns a `HarnessBuilder` and exposes `loop_detection`,
    `loop_threshold`, `include_budget`, `max_cost_usd`, and step/token thresholds.
  - `CostGuardProcessor(max_usd=..., warning_threshold=...)` has
    `_singleton_group = "cost_guard"`; `LoopDetectionProcessor` has
    `_singleton_group = "loop_detection"`.
- **Implications**: The skeleton composes `make_control(...)` with loop detection on and a
  cost guard wired from configured budgets; conflict detection prevents double-registration.

### Observability / HarnessJournal
- **Context**: Requirements 2.3, 4.4, 8.1–8.2 — JSONL trace per run.
- **Sources Consulted**: `harnessx/tracing/journal.py`, `docs/agents.md` (rule 5).
- **Findings**:
  - `HarnessJournal` streams events to per-run JSONL files (`{run_id}.jsonl`,
    `{run_id}_trace.jsonl`) and writes recovery artifacts. `silent=True` suppresses console
    output. It is wired via the config tracer: `harness_config.copy(tracer=HarnessJournal())`.
- **Implications**: Observe is wired by setting the tracer to a `HarnessJournal` rooted at
  the resolved output directory; the journal location is reported on success (Requirement 8.3).

### Model resolution precedence
- **Context**: Requirement 3.2–3.4 — resolve model from config then env.
- **Sources Consulted**: `docs/agents.md` (rule 6), `harnessx/cli.py`.
- **Findings**: HarnessX CLI resolves model config from a config YAML, then
  `~/.harnessx/model_config.yaml`, then provider env vars (`ANTHROPIC_*`, `OPENAI_*`,
  `LITELLM_*`).
- **Implications**: `dhx` mirrors this precedence: explicit `--config` model > env vars;
  a hard failure with a clear message when nothing resolves (Requirement 3.4).

## Architecture Pattern Evaluation

| Option | Description | Strengths | Risks / Limitations | Notes |
|--------|-------------|-----------|---------------------|-------|
| Ordered processors on one hook | Each stage = a no-op processor appended in canonical order on the same hook | Uses HarnessX intra-hook ordering; no new abstraction; append-don't-replace honored | Relies on documented order convention | **Selected** — matches HarnessX grain |
| Single MultiHookProcessor dispatcher | One processor that internally calls all 8 stages | One registration | Hides stage seams; later specs cannot replace a single stage independently | Rejected — violates per-stage replaceability (5.6) |
| Custom pipeline runner outside HarnessX | Bespoke loop invoking stages | Full control | Re-implements run lifecycle; bypasses Journal/Control | Rejected — "real bundle, not inspired-by" |

## Design Decisions

### Decision: Stages are ordered no-op processors, registered via a thin registry helper
- **Context**: Requirement 5 — stages must register at a known hook and order, be
  replaceable individually, and append without replacing.
- **Alternatives Considered**:
  1. Single dispatcher MultiHookProcessor — hides stage seams.
  2. Ordered processors on one hook via an explicit ordered list — explicit and replaceable.
- **Selected Approach**: A `STAGES` ordered list of `(name, processor_factory)` plus a
  `register_stages(builder)` helper that appends each stage processor in canonical order
  using `{**config.processors, hook: [...existing, proc]}` semantics. Each stage stub lives
  in its own sub-package so a later spec swaps the factory without touching `make_docgen`.
- **Rationale**: Preserves per-stage replaceability and HarnessX append-don't-replace rule.
- **Trade-offs**: Order is a convention encoded in one list rather than enforced by types.
- **Follow-up**: Verify ordering via a journal assertion in the E2E test.

### Decision: Run context object wraps state-slot access and segment-store handle
- **Context**: Requirement 6 — single, auditable data-passing contract.
- **Selected Approach**: A `RunContext` value object exposing typed helpers over
  `state.set_slot`/`get_slot` (target repo path, output dir), a `segment_store`
  accessor whose type is the **interface imported from `ontology-engine`** (Protocol-level
  import; no implementation here), and a `vocabulary()` accessor returning the loaded
  `Vocabulary` (placed at `SLOT_VOCABULARY` at run start). Absent slots return an explicit
  `None`.
- **Rationale**: Keeps stages off globals; consumes the ontology contract without owning it.
- **Trade-offs**: Adds a thin wrapper; justified by being the single data seam.
- **Follow-up**: If `ontology-engine` has not published the interface yet, the skeleton
  declares a minimal typing-only Protocol alias and re-exports it, to be replaced by the
  real import — flagged as a revalidation trigger.

### Decision: Model resolution precedence config > env, fail fast
- **Context**: Requirement 3.
- **Selected Approach**: Resolve in order — `--config` YAML model field, then provider env
  vars per HarnessX convention; raise a clear non-zero-exit error when none resolves.
- **Rationale**: Mirrors HarnessX CLI behavior; deterministic and scriptable.
- **Trade-offs**: No interactive prompt; acceptable for a CLI/skeleton.

### Decision: Per-project ontology vocabulary is set up by `dhx init` and loaded at run start
- **Context**: Steering (product.md / tech.md) makes the ontology vocabulary
  (roles/intents/subjects) **project-configurable** to keep `make_docgen` reusable. The
  vocabulary schema and the shipped default profile are owned by `ontology-engine`; this
  spec owns only the *setup* and *loading* interaction (Requirements 9, 10).
- **Alternatives Considered**:
  1. Hardcode the 10 roles / 13 intents in this skeleton — rejected: closes the vocabulary,
     breaks reusability, and duplicates ontology-engine's schema (review Issue 5).
  2. Reimplement a YAML loader / default profile here — rejected: ontology-engine owns the
     schema, serializer, loader, and default profile; reimplementation would diverge.
- **Selected Approach**: A `dhx init` subcommand calls the `ontology-engine`
  vocabulary/default-profile API to build a `Vocabulary` (interactively or by seeding the
  default profile), calls `ontology-engine` `vocabulary_to_config(vocab) -> dict` to get a
  config dict matching the `.docuharnessx/ontology.yaml` schema, and writes that dict to
  `.docuharnessx/ontology.yaml` as YAML (the skeleton owns only the file write; schema
  serialization is delegated to `vocabulary_to_config`). On a normal run,
  `ontology_loader.load_project_vocabulary(...)` loads that
  file via the ontology-engine loader, falling back to the default profile (with a `dhx init`
  hint) when absent; the resulting `Vocabulary` is placed in `RunContext` at
  `SLOT_VOCABULARY` so stages read it. The config surface derives valid roles from this
  loaded `Vocabulary` and validates `--roles` against it.
- **Rationale**: Keeps the harness reusable across projects; respects ontology-engine's
  ownership of the schema/profile/loader; gives stages a single, auditable vocabulary seam.
- **Trade-offs**: Adds two thin modules (`ontology_setup`, `ontology_loader`) and a CLI
  subcommand; justified by reusability and by not reimplementing the ontology.
- **Follow-up**: Exact ontology-engine API names (`Vocabulary`, `load_vocabulary`,
  `vocabulary_to_config`, `default_profile`) are a revalidation trigger; confirm
  against the ontology-engine published surface before implementation.

### Decision: Pin the consumed SegmentStore contract and the package-root ownership
- **Context**: Cross-spec review Issues 1, 2 (store contract) and 3 (package-root
  ownership) between this spec and `ontology-engine`.
- **Selected Approach**:
  - Pin the exact import `from docuharnessx.ontology.store import SegmentStore`, co-importing
    `AxisFilter` and `Segment` from `docuharnessx.ontology` (or `.ontology.store`), through a
    single re-export module (`docuharnessx/ontology.py`) that adds no storage logic. The
    relied-upon signatures are exactly `put(segment) -> None`,
    `query(where: AxisFilter) -> tuple[Segment, ...]`,
    `list_segments() -> tuple[Segment, ...]`,
    `resolve_cross_links(segment_id: str) -> tuple[Segment, ...]`. Any pre-publication
    typing-only fallback alias mirrors those signatures verbatim.
  - This spec **solely** owns the package root — `pyproject.toml` and
    `docuharnessx/__init__.py`; `ontology-engine` creates only `docuharnessx/ontology/*`, so
    the two specs do not collide.
- **Rationale**: Removes ambiguity at the cross-spec seam; prevents duplicate/diverging
  store definitions and package-root collisions.
- **Trade-offs**: Couples this spec to ontology-engine's published import paths (recorded as
  a revalidation trigger).
- **Follow-up**: The consuming task carries a `_Depends:_` on the ontology-engine store and
  vocabulary tasks.

## Risks & Mitigations
- **Segment store interface not yet frozen by `ontology-engine`** — Mitigation: import the
  interface at the contract level behind a single module alias (`docuharnessx/ontology.py`)
  with the pinned `put`/`query`/`list_segments`/`resolve_cross_links` signatures; a
  typing-only fallback mirrors them verbatim; declare a revalidation trigger so a contract
  change forces re-check here.
- **Ontology vocabulary API (Vocabulary / loader / default-profile) not yet published by
  `ontology-engine`** — Mitigation: consume it only through the single `ontology.py`
  re-export and the thin `ontology_setup`/`ontology_loader` modules; the consuming tasks
  carry a `_Depends:_` on the ontology-engine vocabulary/store tasks; exact API names are a
  recorded revalidation trigger.
- **Package-root collision with `ontology-engine`** — Mitigation: this spec solely owns
  `pyproject.toml` and `docuharnessx/__init__.py`; `ontology-engine` owns only
  `docuharnessx/ontology/*`; the boundary is stated in requirements, design, and tasks.
- **HarnessX version drift in composition/journal API** — Mitigation: pin a compatible
  `harnessx` version in the manifest and centralize all HarnessX imports in the bundle
  module so an API change touches one file.
- **Empty pipeline still needs a runnable task** — Mitigation: drive the run with a minimal
  `BaseTask` whose description marks a skeleton/no-op run; success is "ran and journaled."

## References
- HarnessX agent guide — `/tmp/HarnessX_investigate/docs/agents.md`
- HarnessX architecture — `/tmp/HarnessX_investigate/docs/architecture.md`
- HarnessX builder/state/journal/control sources under `/tmp/HarnessX_investigate/harnessx/`
- Sibling spec `ontology-engine` (segment store interface owner) —
  `.kiro/specs/ontology-engine/`
