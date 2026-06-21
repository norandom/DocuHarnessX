# Requirements Document

## Introduction

The ontology-engine defines the tri-modal ontology (Role × Intent × Subject) and the content-segment contract that every other DocuHarnessX stage reads and writes. It is Wave 0 foundation #1 and the most-shared seam in the project: the segment frontmatter schema is the cross-spec contract that the classification-coverage-planner, cobesy-writer, quality-review-gate, and mkdocs-site-assembler all depend on. Because downstream stages cannot be implemented against a moving contract, the schema must be stable and explicitly versioned from the start.

Critically, the ontology *vocabulary* (the roles, intents, and subject prefixes/tags) is **project-configurable, not hardcoded**. It is loaded at runtime from a per-project ontology config file (`.docuharnessx/ontology.yaml`) into a `Vocabulary` value object. The 10 roles / 13 intents / subject prefixes ship as a **default profile (preset)** that can seed a config, but they are NOT closed enums. This is what keeps the `make_docgen` harness reusable across different projects: a different project supplies a different vocabulary, and segments validate against the loaded vocabulary rather than a global enum.

This feature delivers five user-observable capabilities: (1) a project-configurable ontology vocabulary loaded from `.docuharnessx/ontology.yaml` (with a shipped default profile that can seed it), (2) a versioned segment frontmatter schema with required/optional field rules, (3) deterministic validation of segments against the *loaded* vocabulary that rejects malformed segments with clear, actionable errors, (4) a segment store interface (put / query-by-axis / list / resolve-cross-links) plus deterministic namespaced MkDocs tag emission, and (5) cross-link resolution. All behavior is deterministic and unit-testable with no LLM calls.

## Boundary Context

- **In scope**: the ontology vocabulary config schema (`.docuharnessx/ontology.yaml`) and its loader; the shipped default profile (preset) and the ability to produce it when no config exists; the `Vocabulary` value object (loaded roles + intents + subjects for a project); the Subject open namespace with typed prefixes; the segment frontmatter schema and its version field; validation of segments and cross-links against the loaded `Vocabulary`; deterministic mapping of a segment to namespaced MkDocs tags derived from the vocabulary; the segment store interface and a filesystem-backed implementation; deriving a role view by filtering on role plus intent ordering; explicit schema versioning and compatibility behavior.
- **Out of scope**: generating segment *content* (owned by cobesy-writer); deciding *which* segments a project needs / coverage planning (owned by classification-coverage-planner); MkDocs site assembly, navigation, and rendering (owned by mkdocs-site-assembler); any LLM invocation. **The interactive `dhx init` ask (prompting the user for which roles/intents/tags apply) and writing `.docuharnessx/ontology.yaml` from those user prompts are owned by harness-bundle-skeleton, NOT this spec.** This spec owns the config *schema*, the *loader*, the *default profile*, and *validation-against-vocabulary*; harness-bundle-skeleton calls this engine's loader / default-profile API to perform the interaction and persist the file.
- **Package-root ownership**: `docuharnessx/__init__.py` (the package root) and `pyproject.toml` are owned by harness-bundle-skeleton. This spec creates ONLY `docuharnessx/ontology/*` and assumes the package root already exists (sequence after the skeleton's package scaffold, or treat the root as a given foundation).
- **Adjacent expectations**: downstream stages consume the frozen frontmatter schema, the namespaced tag strings, the `Vocabulary` loader / default-profile API, and the segment store interface. They expect the schema version to be declared and changes to the schema to be signaled so they can re-validate. They expect tag names to be namespaced exactly `subject:` / `intent:` / `role:`, derived deterministically from the loaded vocabulary.

## Requirements

### Requirement 1: Project-Configurable Ontology Vocabulary
**Objective:** As a project owner, I want the Role and Intent vocabularies and the Subject prefixes to be loaded from a per-project config file rather than hardcoded, so that the same `make_docgen` harness is reusable across projects with different reader audiences.

#### Acceptance Criteria
1. The Ontology Engine shall define a per-project ontology config schema for a file at `.docuharnessx/ontology.yaml` containing: `roles[]` (each with `id`, `label`, `description`), `intents[]` (each with `id`, `label`, `description`), `subjects` (the allowed subject prefixes/tags), and an optional `profile` reference.
2. The Ontology Engine shall provide a loader that reads `.docuharnessx/ontology.yaml` and produces a `Vocabulary` value object holding the project's roles, intents, and subjects.
3. When no ontology config file exists at the given location, the Ontology Engine's loader shall be able to produce a `Vocabulary` from the shipped default profile rather than failing.
4. The Ontology Engine shall expose the shipped default profile (the 10 roles, 13 intents, and default subject prefixes `component:`/`tech:`/`artifact:`/`topic:`) as a preset that can seed a config or back a `Vocabulary`, NOT as a closed enumeration.
5. When a config declares a `profile` reference, the Ontology Engine shall resolve that profile (e.g., the default profile) as the base vocabulary that the file's explicit entries extend or override.
6. If the ontology config file is present but malformed or missing required keys, then the Ontology Engine's loader shall reject it with a clear, actionable error identifying the offending config.
7. The Ontology Engine shall load and resolve the vocabulary deterministically, so that the same config file always yields the same `Vocabulary`.
8. The Ontology Engine shall NOT prompt the user for vocabulary values or write `.docuharnessx/ontology.yaml`; that interaction belongs to harness-bundle-skeleton, which calls this engine's loader / default-profile API.
9. The Ontology Engine shall provide a symmetric serializer `vocabulary_to_config(vocab)` that, given a `Vocabulary`, returns a plain dict matching the `.docuharnessx/ontology.yaml` schema (`roles[]`, `intents[]`, `subjects`, optional `profile`) such that `load_vocabulary` can round-trip it; the serialization shall be deterministic and perform no file I/O or prompting (the skeleton writes the YAML). The round-trip `load_vocabulary(vocabulary_to_config(v))` shall equal `v`.

### Requirement 2: Vocabulary Value Object and Default Profile Contents
**Objective:** As a downstream pipeline stage, I want a single loaded `Vocabulary` to query for valid roles, intents, and subject prefixes, so that every segment is validated against the project's configured ontology.

#### Acceptance Criteria
1. The Ontology Engine's default profile shall define exactly ten default roles: Possible Adopter, Developer, Tech-savvy User, Manager, DevOps/Admin, Researcher, Security/Compliance Officer, Contributor, Integrator/API consumer, and Support/On-call (SRE).
2. The Ontology Engine's default profile shall define exactly thirteen default intents: install, configure, use, troubleshoot, monitor, operate, integrate, extend, evaluate, assess-quality, understand, contribute, and deliver.
3. When a caller requests the roles or intents of a loaded `Vocabulary`, the Ontology Engine shall return them in a stable, deterministic order derived from the config (or the default profile when unconfigured).
4. The Ontology Engine shall expose a stable machine identifier (`id`) for each role and intent in a `Vocabulary` that does not change when its display `label` changes.
5. When a caller submits a role or intent value that is not a member of the loaded `Vocabulary`, the Ontology Engine shall report it as unknown for that axis.
6. The Ontology Engine shall expose, for a loaded `Vocabulary`, a stable documented default ordering of its intents that is used to order content within a role view.

### Requirement 3: Subject Namespace
**Objective:** As a content author or upstream planner, I want an open Subject namespace whose typed prefixes come from the loaded vocabulary, so that I can describe what/how a segment covers without a closed enumeration while keeping subjects well-formed and project-configurable.

#### Acceptance Criteria
1. The Ontology Engine shall accept Subject values only when they begin with one of the typed prefixes configured in the loaded `Vocabulary` (default profile prefixes: `component:`, `tech:`, `artifact:`, `topic:`).
2. If a Subject value has no recognized prefix or a prefix not present in the loaded `Vocabulary`, then the Ontology Engine shall reject it as a malformed subject and identify the offending value.
3. The Ontology Engine shall treat the portion after the prefix as an open, free-form local name and shall not require it to belong to a fixed list.
4. If a Subject value has a recognized prefix but an empty or whitespace-only local name, then the Ontology Engine shall reject it as a malformed subject.
5. The Ontology Engine shall normalize and compare Subject values deterministically so that the same subject string always maps to the same canonical subject.

### Requirement 4: Segment Frontmatter Schema
**Objective:** As a downstream pipeline stage, I want a single, explicitly defined segment frontmatter schema, so that every stage reads and writes segments against the same contract.

#### Acceptance Criteria
1. The Ontology Engine shall define a segment as a Markdown file with a frontmatter block containing the fields `id`, `title`, `roles`, `subjects`, `intent`, `summary`, and `related`.
2. The Ontology Engine shall require the fields `id`, `title`, `roles`, `subjects`, and `intent` to be present in every valid segment.
3. The Ontology Engine shall treat `summary` and `related` as optional fields with defined default values when absent.
4. The Ontology Engine shall define `roles`, `subjects`, and `related` as lists, `intent` as a single value, and `id`, `title`, and `summary` as text values.
5. When `roles` or `subjects` is present, the Ontology Engine shall require it to contain at least one value.
6. The Ontology Engine shall require each segment `id` to be unique within a given segment set.

### Requirement 5: Schema Versioning and Stability
**Objective:** As a downstream spec owner, I want the segment schema and vocabularies to carry an explicit version and a defined compatibility contract, so that I can detect contract changes and re-validate safely.

#### Acceptance Criteria
1. The Ontology Engine shall expose a single, explicit schema version identifier for the segment frontmatter contract.
2. Where a segment declares a schema version, the Ontology Engine shall validate it against the engine's supported version and report a version mismatch when they are incompatible.
3. When a segment omits a schema version, the Ontology Engine shall treat it as the engine's current supported version.
4. The Ontology Engine shall document, for each schema version, which fields and which axis vocabularies are part of the frozen contract.
5. When the schema version or any axis vocabulary changes, the Ontology Engine shall surface the change through the version identifier so that downstream consumers can detect it.

### Requirement 6: Segment Validation
**Objective:** As a content author or upstream stage, I want segments validated with clear, specific errors, so that malformed content is rejected before it reaches later stages.

#### Acceptance Criteria
1. When a segment is submitted for validation together with a loaded `Vocabulary`, the Ontology Engine shall accept it only if its frontmatter parses, all required fields are present, and all axis values are members of that loaded `Vocabulary`.
2. If a segment is missing a required field, then the Ontology Engine shall reject it and identify the missing field.
3. If a segment's frontmatter cannot be parsed, then the Ontology Engine shall reject it and report a malformed-frontmatter error that identifies the segment.
4. If a segment references a role or intent that is not in the loaded `Vocabulary`, then the Ontology Engine shall reject it and identify the unknown value and the field it appeared in.
5. If a segment contains a malformed subject, then the Ontology Engine shall reject it and identify the offending subject value.
6. When validation fails for multiple reasons, the Ontology Engine shall report all detected errors rather than only the first.
7. The Ontology Engine shall produce identical validation results for identical inputs across repeated runs.

### Requirement 7: Cross-Link Resolution
**Objective:** As a content author, I want `related[]` cross-links validated against the segment set, so that interconnections between segments are guaranteed to resolve.

#### Acceptance Criteria
1. When a segment set is validated, the Ontology Engine shall verify that every `related` entry refers to the `id` of a segment that exists in the set.
2. If a `related` entry refers to an `id` that does not exist in the set, then the Ontology Engine shall reject the referencing segment and identify the unresolved target id.
3. When a caller requests the cross-links for a segment, the Ontology Engine shall return the resolved related segments deterministically.
4. If a segment lists its own `id` in `related`, then the Ontology Engine shall report it as an invalid self-reference.

### Requirement 8: Namespaced Tag Emission
**Objective:** As the MkDocs site assembler, I want a deterministic mapping from a segment to namespaced tags, so that the Material tags plugin receives correctly namespaced tags.

#### Acceptance Criteria
1. When the Ontology Engine emits tags for a segment, it shall produce one `role:` tag for each role, one `intent:` tag for the intent, and one `subject:` tag for each subject.
2. The Ontology Engine shall namespace tag names exactly as `role:`, `intent:`, and `subject:` with no other prefix forms.
3. The Ontology Engine shall preserve the typed subject prefix within the emitted subject tag value so that the subject type remains distinguishable.
4. The Ontology Engine shall emit the tag set for a given segment deterministically, producing the same ordered tag set for identical input.
5. The Ontology Engine shall emit tags only for axis values that are valid members of the loaded `Vocabulary`, deriving the `role:` / `intent:` / `subject:` namespacing deterministically from that vocabulary.

### Requirement 9: Segment Store Interface
**Objective:** As a downstream stage (writer, review gate, assembler), I want a stable segment store interface, so that segments can be written, queried, listed, and cross-linked through one contract.

#### Acceptance Criteria
1. The Ontology Engine shall expose a segment store interface supporting put a segment, query by axis filter, list all segments, and resolve cross-links.
2. When a caller puts a segment, the Ontology Engine shall validate it and reject the operation if the segment is invalid.
3. When a caller queries by axis filter (role, intent, and/or subject), the Ontology Engine shall return all segments matching every supplied axis criterion.
4. When a query supplies multiple values for an axis, the Ontology Engine shall return segments that match any of the supplied values for that axis.
5. When a caller lists segments, the Ontology Engine shall return all stored segments in a deterministic order.
6. The Ontology Engine shall provide a filesystem-backed implementation of the segment store interface that reads and writes segments as Markdown files with frontmatter.
7. If a caller puts a segment whose `id` already exists in the store, then the Ontology Engine shall report an id conflict rather than silently overwriting.

### Requirement 10: Role View Derivation
**Objective:** As a downstream assembler, I want a role view derived by filtering on role and ordering by intent, so that one corpus produces many role-targeted views through reuse rather than duplication.

#### Acceptance Criteria
1. When a caller requests a role view for a given role, the Ontology Engine shall return all segments that include that role.
2. While building a role view, the Ontology Engine shall order the included segments by the documented default intent ordering.
3. The Ontology Engine shall include a segment in every role view for each role it carries, without duplicating the segment's stored content.
4. When two segments share the same intent within a role view, the Ontology Engine shall order them by a stable, deterministic secondary key.
5. Where a role has no matching segments, the Ontology Engine shall return an empty role view rather than an error.

### Requirement 11: Determinism and Testability
**Objective:** As a maintainer, I want the engine to be deterministic and unit-testable with no LLM calls, so that ontology behavior is reproducible and verifiable in CI.

#### Acceptance Criteria
1. The Ontology Engine shall not perform any LLM call or non-deterministic external request in any of its operations.
2. The Ontology Engine shall produce identical outputs (validation results, tag sets, query results, role views) for identical inputs across repeated runs.
3. The Ontology Engine shall expose its vocabulary loading, validation, tagging, store, and role-view behavior through interfaces that can be exercised by unit tests without external services.
4. The Ontology Engine shall load and resolve a `Vocabulary` from identical config input identically across repeated runs.
