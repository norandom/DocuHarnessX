# Research & Design Decisions — ontology-engine

## Summary
- **Feature**: `ontology-engine`
- **Discovery Scope**: New Feature (greenfield, Wave 0 foundation)
- **Key Findings**:
  - The segment frontmatter schema is the project's most-shared cross-spec contract; stability and explicit versioning dominate every other design concern.
  - The ontology *vocabulary* (roles, intents, subject prefixes) is **project-configurable** per steering (product.md, tech.md decision 4, structure.md): it is loaded at runtime from `.docuharnessx/ontology.yaml` into a `Vocabulary` value object, with a shipped default profile (preset) seeding it. Roles/intents are therefore NOT closed Python enums — modelling them as enums would defeat the reusability premise of the harness.
  - All behavior is deterministic and pure (no LLM, no network), so the design reduces to a typed in-memory ontology model + a vocabulary loader + a thin, swappable store port — a hexagonal (ports & adapters) shape fits naturally.
  - Markdown-with-YAML-frontmatter is the de facto standard for content segments and is directly consumable by Material for MkDocs; the engine only needs frontmatter parse/serialize plus a stable Markdown body passthrough, not a full Markdown AST.

## Research Log

### Frontmatter format and parsing
- **Context**: Requirement 4 defines a segment as Markdown with a frontmatter block; Requirement 9.6 requires a filesystem implementation that round-trips Markdown files.
- **Sources Consulted**: Material for MkDocs front matter / metadata conventions; the Python `pyyaml` library; the MkDocs Material `tags` plugin documentation (axis A in steering tech.md).
- **Findings**:
  - YAML front matter delimited by `---` fences is the convention Material for MkDocs and its `tags` plugin read directly. Aligning the engine's on-disk format with this convention means the assembler stage can hand segment files to MkDocs with minimal transformation.
  - Parsing only needs: split the leading fenced block, parse it as YAML into a mapping, keep the remaining Markdown body as opaque text. No Markdown AST is required at this layer.
  - YAML parsing must be safe (no arbitrary object construction) and the parse step is where "malformed-frontmatter" (Req 6.3) is detected.
- **Implications**: Adopt YAML front matter as the on-disk contract; isolate parse/serialize behind a single serializer component so the rest of the engine works on typed objects, not raw text.

### Configurable vocabulary vs hardcoded enums
- **Context**: Requirements 1 and 2 require the Role/Intent/Subject vocabularies to be project-configurable; steering (product.md "Project-configurable vocabulary (reusability core)", tech.md key decision 4, structure.md "Ontology config") mandates a per-project `.docuharnessx/ontology.yaml`.
- **Sources Consulted**: steering `product.md`, `tech.md` (decision 4), `structure.md` (Ontology config / Naming Conventions); the boundary split with harness-bundle-skeleton (who owns the `dhx init` ask and config writing).
- **Findings**:
  - The harness (`make_docgen`) must be reusable across projects with different reader audiences. A closed `enum` for Role/Intent would hardcode one project's audience into the engine, breaking reuse — exactly what steering forbids.
  - The vocabulary is *data*, not a contract: it is loaded at runtime. What must stay frozen is the *config schema*, the *loader API*, the *segment schema*, and the *store port* — not the members.
  - The interaction that gathers vocabulary from a user (`dhx init`) and persists `.docuharnessx/ontology.yaml` is a CLI concern owned by harness-bundle-skeleton. This engine must expose a loader and a default-profile API that the skeleton calls; it must not prompt or write the file itself. This keeps a clean ownership boundary.
  - A shipped default profile (10 roles, 13 intents, 4 prefixes) preserves zero-config usability while staying a preset, not an enum.
- **Implications**: Replace `Role`/`Intent` enums with a loaded `Vocabulary` value object (`AxisTerm`s + subject prefixes). Add a `vocabulary.py` component with `load_vocabulary`, `default_profile`, `default_profile_config`. Validation and tagging take a `Vocabulary` parameter. The Subject parser takes the allowed-prefix set from the vocabulary rather than a module constant.
- **Decision (symmetric serializer)**: Add `vocabulary_to_config(vocab) -> dict` as the deterministic, I/O-free inverse of `load_vocabulary`, so harness-bundle-skeleton's interactive `dhx init` can serialize an arbitrarily-built `Vocabulary` to the `.docuharnessx/ontology.yaml` schema without reimplementing it (the skeleton still writes the YAML); round-trips via `load_vocabulary(vocabulary_to_config(v)) == v`.

### Schema versioning strategy
- **Context**: Requirement 5 mandates an explicit, single schema version with defined compatibility behavior; the brief calls the schema "the frozen cross-spec contract."
- **Sources Consulted**: Common schema-versioning practice (single integer/semver contract identifier, default-to-current on omission); steering roadmap.md "freeze it early" / "keep its interface stable."
- **Findings**:
  - A single, centralized version constant (one source of truth) is simpler and safer than per-field versioning for a contract this small. Downstream specs compare against this one identifier.
  - Default-to-current on omission (Req 5.3) keeps authoring frictionless while still allowing explicit declaration for forward compatibility.
  - Vocabularies (Role/Intent fixed sets, Subject prefix set) are part of the frozen contract and must be enumerated under the version (Req 5.4).
- **Implications**: One `SCHEMA_VERSION` constant in the schema module; a compatibility check that compares declared vs supported and rejects incompatible majors. The vocabularies live as frozen, ordered definitions in the model module.

### Store interface shape (build vs adopt)
- **Context**: Requirement 9 requires a store interface (put / query-by-axis / list / resolve-cross-links) with a filesystem implementation; steering names the segment store a stable handoff seam.
- **Sources Consulted**: Hexagonal/ports-and-adapters pattern; Python `typing.Protocol` for structural interfaces; steering structure.md ("stages communicate through the segment store, not globals").
- **Findings**:
  - No off-the-shelf store fits the tri-modal axis-query contract, so the store is custom — but the *interface* should be a port (Protocol) so later stages and tests can substitute an in-memory implementation.
  - Two implementations are justified by current requirements: a filesystem-backed store (Req 9.6, the real handoff) and an in-memory store (Req 11.3, test substitution). This is not speculative abstraction — both are needed now.
- **Implications**: Define the store as a `Protocol` port; ship filesystem and in-memory adapters.

## Architecture Pattern Evaluation

| Option | Description | Strengths | Risks / Limitations | Notes |
|--------|-------------|-----------|---------------------|-------|
| Hexagonal (ports & adapters) | Pure ontology/validation core; store as a port with filesystem + in-memory adapters | Testable pure core, swappable storage, clear seam for downstream | Slight indirection for one port | Chosen — matches steering "core never imports adapters" and the store-as-seam requirement |
| Single module, direct filesystem | One module mixing model, validation, and file I/O | Fewer files | Couples pure logic to disk; hard to unit-test deterministically; violates steering layering | Rejected |
| Full Markdown-AST model | Parse the whole document into a structured AST | Rich body manipulation | Out of scope (no content generation here); over-engineered | Rejected — body is opaque passthrough at this layer |

## Design Decisions

### Decision: YAML front matter as the on-disk segment contract
- **Context**: Need a deterministic, MkDocs-compatible on-disk segment format.
- **Alternatives Considered**:
  1. YAML front matter (`---` fenced) + opaque Markdown body — MkDocs-native.
  2. TOML front matter — also supported by some tools but not the MkDocs Material `tags` default.
  3. Sidecar JSON metadata files — splits content from metadata, breaks single-file segment model.
- **Selected Approach**: YAML front matter fenced by `---`, parsed safely into a typed `Segment`, with the remaining text retained verbatim as the body.
- **Rationale**: Directly consumable by the downstream MkDocs assembler and `tags` plugin; single-file segment model; safe deterministic parsing.
- **Trade-offs**: YAML edge cases (e.g., type coercion) must be constrained by validation; mitigated by validating typed fields after parse.
- **Follow-up**: Ensure serialize→parse round-trips are tested for determinism.

### Decision: Project-configurable vocabulary (loaded `Vocabulary`) instead of closed enums
- **Context**: Req 1, 2; steering reusability mandate — the same harness must serve projects with different roles/intents/tags.
- **Alternatives Considered**:
  1. Closed `enum.Enum` for `Role`/`Intent` baked into the engine.
  2. A `Vocabulary` value object loaded from `.docuharnessx/ontology.yaml`, with a shipped default profile preset; validation/tagging take the loaded vocabulary.
  3. Vocabulary hardcoded but extensible via subclassing.
- **Selected Approach**: (2) — a `vocabulary.py` component owning the config schema, a deterministic `load_vocabulary` loader, `default_profile()` / `default_profile_config()` presets, and the `Vocabulary` value object. Roles/intents are `AxisTerm`s (id/label/description). Validation, tagging, role views, and the Subject parser all consume a passed-in `Vocabulary`.
- **Rationale**: Directly satisfies the steering reusability core; keeps the engine project-agnostic; the schema/loader API/segment contract/store port stay frozen while the *members* are project data.
- **Trade-offs**: Validation/tagging gain a `Vocabulary` parameter (slightly more plumbing) and we lose `enum`'s compile-time exhaustiveness — acceptable and necessary for reuse; mitigated by membership checks + tests.
- **Boundary**: The `dhx init` ask and writing `.docuharnessx/ontology.yaml` from user prompts are OWNED BY harness-bundle-skeleton, which calls this engine's loader / default-profile API. This engine never prompts and never writes the config from user input.
- **Follow-up**: Cover default-profile contents, config loading, profile resolution, missing-file fallback, and malformed-config rejection with deterministic tests.

### Decision: Single centralized schema version with default-to-current
- **Context**: Req 5 — explicit version, compatibility behavior, frozen vocabularies.
- **Alternatives Considered**:
  1. Single `SCHEMA_VERSION` constant compared on validation.
  2. Per-field/per-axis versioning.
- **Selected Approach**: One `SCHEMA_VERSION` constant; segments may declare `schema_version`; omission defaults to current; incompatible declared versions are rejected with a version-mismatch error.
- **Rationale**: Smallest design that satisfies the contract; one source of truth for all downstream consumers.
- **Trade-offs**: Coarser granularity than per-field versioning, acceptable for a small frozen contract.
- **Follow-up**: Document the frozen field/vocabulary set per version in the schema module docstring.

### Decision: Store as a Protocol port with filesystem + in-memory adapters
- **Context**: Req 9 (store interface + filesystem impl) and Req 11.3 (test substitution).
- **Alternatives Considered**:
  1. Protocol port + two adapters (filesystem, in-memory).
  2. Concrete filesystem class only.
- **Selected Approach**: A `SegmentStore` Protocol with `FilesystemSegmentStore` and `InMemorySegmentStore` adapters.
- **Rationale**: Both adapters are required by current requirements; the port keeps the pure core and downstream consumers decoupled from storage.
- **Trade-offs**: One extra indirection layer — justified, not speculative.
- **Follow-up**: Keep query semantics identical across both adapters (covered by shared tests).

## Synthesis Outcomes
- **Generalization**: Validation of "value belongs to vocabulary" generalizes across Role and Intent; both are `AxisTerm`s in a loaded `Vocabulary` sharing one id-membership-check path, while Subject uses a prefix-rule check against the vocabulary's allowed prefixes. Axis querying generalizes across all three axes into one filter mechanism with per-axis OR / cross-axis AND semantics (Req 9.3, 9.4).
- **Build vs Adopt**: Adopt YAML front matter convention and a safe YAML parser (also used for the ontology config) rather than inventing a format; build the custom ontology model, vocabulary loader, validator, tag mapper, and store (no library fits the tri-modal, project-configurable contract).
- **Simplification**: No Markdown AST; body is opaque text. No per-field versioning. Vocabulary is loaded data (not enums), so there is no enum-evolution machinery — a config file plus a default profile preset covers all reuse cases. Role view = filter-by-role + intent ordering (a thin function over the store query), not a separate subsystem.

## Risks & Mitigations
- **Contract drift across specs** — Mitigation: single `SCHEMA_VERSION`, a frozen config schema + loader API + segment schema + store port (the loaded vocabulary *members* are project data, not a frozen seam), revalidation triggers documented in design boundary section.
- **Vocabulary/config misconfiguration** (typo'd role id, missing keys, unknown prefix) — Mitigation: loader rejects malformed config with `MalformedConfigError`; validation reports unknown role/intent ids and bad subject prefixes against the loaded vocabulary; deterministic-load tests.
- **Boundary leakage** (engine accidentally prompting or writing the config) — Mitigation: the loader is read-only and never prompts; the `dhx init` ask + file write are explicitly owned by harness-bundle-skeleton, which calls `default_profile_config()`.
- **YAML type-coercion surprises** (e.g., a bare `intent` value parsed unexpectedly) — Mitigation: validate typed fields after parse; reject anything that is not the expected shape.
- **Adapter divergence** (filesystem vs in-memory query results differ) — Mitigation: a shared store-conformance test suite run against both adapters.
- **Non-deterministic ordering** in queries/tags/role views — Mitigation: define explicit stable ordering keys (Req 6.7, 8.4, 9.5, 10.4) and test them.

## References
- Material for MkDocs — Metadata / front matter and `tags` plugin conventions (steering tech.md axis A).
- DocuHarnessX steering: `product.md` (Project-configurable vocabulary), `tech.md` (key decision 4: ontology config at `.docuharnessx/ontology.yaml`), `structure.md` (Ontology config naming), `roadmap.md`, and `.kiro/specs/ontology-engine/brief.md`.
