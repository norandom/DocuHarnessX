# Implementation Plan

- [x] 1. Foundation: ontology subpackage and shared error types
- [x] 1.1 Create the ontology subpackage and public API surface
  - Create the `docuharnessx/ontology/` package with an `__init__.py` that will re-export the public API. Assume the package root `docuharnessx/__init__.py` already exists; it is owned by harness-bundle-skeleton and is NOT created or modified here. If the root is absent at implementation time, sequence this work after the skeleton's package scaffold rather than creating the root in this spec.
  - Do NOT create or modify `pyproject.toml`; the `pyyaml` dependency declaration is owned by harness-bundle-skeleton. This spec only imports `pyyaml`.
  - Observable completion: importing `docuharnessx.ontology` succeeds and the subpackage is discoverable by the test runner.
  - _Requirements: 11.3_
  - _Boundary: __init___
  - _Depends: (package root from harness-bundle-skeleton)_

- [x] 1.2 Define the typed error and result model
  - Define the discriminated error types (malformed config, malformed frontmatter, missing field, unknown role, unknown intent, malformed subject, version mismatch, duplicate id, unresolved link, self reference, id conflict), each carrying the offending value/field and segment or config identifier where applicable.
  - Define `ValidationResult` (per-segment) and `SetValidationResult` (per-set) with an `is_valid` flag and an ordered error list.
  - Observable completion: unit tests construct each error type and assert it exposes the offending value/field, and that an empty result reports `is_valid` true.
  - _Requirements: 1.6, 6.2, 6.3, 6.4, 6.5, 6.6, 7.2, 7.4_
  - _Boundary: errors_

- [x] 2. Core: ontology model, vocabulary, schema, and pure transforms
- [x] 2.1 Implement the axis primitives and subject namespace
  - Define the `AxisTerm` value object (`id`, `label`, `description`) — the structural unit of a role or intent, with a stable machine `id` distinct from its display `label`. Do NOT model roles/intents as closed enums.
  - Define the `Subject` value object with `parse(raw, allowed_prefixes)` (prefix validated against a supplied allowed-prefix set, non-empty normalized local name), `canonical()`, and deterministic normalization. The allowed prefixes are supplied by the caller from a loaded `Vocabulary`, not a module constant.
  - Observable completion: unit tests confirm `AxisTerm` keeps `id` stable when `label` changes; subjects parse for each supplied prefix while unknown-prefix and empty-local subjects raise a malformed-subject error; `Subject` normalization is idempotent.
  - _Requirements: 2.4, 3.1, 3.2, 3.3, 3.4, 3.5_
  - _Boundary: model_
  - _Depends: 1.2_

- [x] 2.2 Implement the project-configurable vocabulary: schema, loader, and default profile
  - Define the `.docuharnessx/ontology.yaml` config schema (`roles[]` {id,label,description}, `intents[]` {id,label,description}, `subjects` allowed prefixes/tags, optional `profile`).
  - Implement the `Vocabulary` value object (deterministic `roles`/`intents` accessors, `has_role`/`has_intent` id-membership checks, `subject_prefixes`, `intent_order()` for role views).
  - Implement `load_vocabulary(config_path)` (safe YAML read, optional `profile` resolution as a base then explicit overrides, deterministic), a missing-file fallback to the default profile, and `MalformedConfigError` on a present-but-invalid config.
  - Implement `default_profile()` (preset `Vocabulary`: the 10 default roles, 13 default intents, prefixes `component:`/`tech:`/`artifact:`/`topic:`) and `default_profile_config()` (serializable seed dict for harness-bundle-skeleton to write). These are presets, NOT closed enums.
  - Implement `vocabulary_to_config(vocab)`, the symmetric inverse of `load_vocabulary`: serialize any `Vocabulary` to a plain dict matching the `.docuharnessx/ontology.yaml` schema (`roles[]`, `intents[]`, `subjects`, optional `profile`), deterministically and with no file I/O or prompting (the skeleton writes the YAML).
  - Do NOT prompt the user and do NOT write `.docuharnessx/ontology.yaml`; that interaction is owned by harness-bundle-skeleton, which calls this API.
  - Observable completion: unit tests confirm the default profile has exactly 10 roles / 13 intents / 4 prefixes in stable order; a config file yields its configured vocabulary; a `profile` reference resolves a base then applies overrides; a missing file yields the default profile; a malformed/missing-key config raises `MalformedConfigError`; identical config yields an identical `Vocabulary`; and the config serializer round-trips, i.e. `load_vocabulary(vocabulary_to_config(v)) == v` for the default profile and a custom-built `Vocabulary`.
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9, 2.1, 2.2, 2.3, 2.5, 2.6, 11.4_
  - _Boundary: vocabulary_
  - _Depends: 2.1_

- [x] 2.3 Implement the segment schema and version contract
  - Define the `Segment` dataclass with the full field set (`id`, `title`, `roles: list[str]` role ids, `subjects: list[Subject]`, `intent: str` intent id, `summary`, `related`, `body`, `schema_version`), required-field set, and defaults for the optional fields. Roles/intent are stored as vocabulary ids, not enum members.
  - Define the single `SCHEMA_VERSION` constant, the documented per-version frozen field set, and the version-compatibility check (omitted version treated as current, incompatible declared version rejected). The vocabulary is NOT part of the frozen schema version.
  - Observable completion: unit tests confirm required fields and types, that optional fields default correctly, that an omitted version is treated as current, and that an incompatible declared version is reported as incompatible.
  - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 5.1, 5.2, 5.3, 5.4, 5.5_
  - _Boundary: schema_
  - _Depends: 2.1_

- [x] 2.4 (P) Implement namespaced tag emission
  - Map a segment to the exactly-namespaced tag set against a supplied `Vocabulary`: one `role:<role_id>` per role, one `intent:<intent_id>`, and one `subject:<prefix:local>` per subject, preserving the typed subject prefix.
  - Emit deterministically in a stable order and only for axis values that are valid members of the supplied `Vocabulary`, using no namespace forms other than `role:`/`intent:`/`subject:`.
  - Observable completion: unit tests assert the exact namespaced tag strings, subject-prefix preservation, deterministic ordering across repeated runs, and that only vocabulary-valid axis values produce tags.
  - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5_
  - _Boundary: tags_
  - _Depends: 2.2, 2.3_

- [x] 2.5 (P) Implement the frontmatter serializer
  - Parse Markdown with a leading `---`-fenced YAML block safely into a raw mapping plus an opaque body; keep `roles`/`intent` as raw ids and coerce `subjects` to typed `Subject` using the allowed prefixes from a supplied `Vocabulary`; serialize a `Segment` back to deterministic Markdown front matter with stable key order.
  - Raise a malformed-frontmatter error when the fenced block is missing or invalid YAML, and surface untypable subjects rather than dropping them.
  - Observable completion: a unit test round-trips a segment through serialize then parse (with a vocabulary) and gets an equivalent `Segment`, and a malformed front-matter input raises the malformed-frontmatter error.
  - _Requirements: 4.1, 4.4_
  - _Boundary: serializer_
  - _Depends: 2.2, 2.3_

- [x] 3. Core: validation and cross-link resolution
- [x] 3.1 Implement single-segment validation against a vocabulary with error aggregation
  - Validate a segment against a supplied `Vocabulary` for parseability, version compatibility, required-field presence, non-empty `roles`/`subjects`, role/intent id membership in the vocabulary, and subject-prefix membership, collecting every detected error into a `ValidationResult`.
  - Ensure identical inputs (segment + vocabulary) produce identical aggregated results.
  - Observable completion: a unit test on a segment with multiple faults returns all corresponding errors (not just the first); a role/intent valid under one vocabulary but not another is accepted/rejected accordingly; repeated runs produce an identical result.
  - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7_
  - _Boundary: validation_
  - _Depends: 1.2, 2.2, 2.3_

- [x] 3.2 Implement segment-set validation and cross-link resolution
  - Enforce unique `id` across a segment set, then resolve each `related` entry against the id index: unknown targets and self-references are reported as errors, valid links resolve deterministically.
  - Observable completion: a unit test over a set rejects a duplicate id, an unresolved `related` target (naming the missing id), and a self-reference, while valid links resolve to the correct target segments in a stable order.
  - _Requirements: 4.6, 7.1, 7.2, 7.3, 7.4_
  - _Boundary: validation_
  - _Depends: 3.1_

- [x] 4. Core: segment store port and adapters
- [x] 4.1 Define the frozen store port and in-memory adapter
  - Define the FROZEN `SegmentStore` Protocol (`put`, `query`, `list_segments`, `resolve_cross_links`) and `AxisFilter` (with `roles`/`intents` as id tuples and `subjects` as `Subject` tuples) exactly as pinned in design.md, then implement `InMemorySegmentStore(vocab)` with validate-on-put against the bound vocabulary (rejecting invalid segments and id conflicts), axis query semantics (per-axis OR, cross-axis AND), and deterministic `list_segments`.
  - Treat these signatures as the contract harness-bundle-skeleton imports verbatim; do not deviate from the pinned shape.
  - Observable completion: unit tests show `put` rejecting an invalid segment and an id conflict, an empty filter returning all segments, multi-value and multi-axis queries returning the correct subset, and `list_segments` returning a deterministic order.
  - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.7_
  - _Boundary: store_
  - _Depends: 3.2_

- [x] 4.2 Implement the filesystem-backed adapter
  - Implement `FilesystemSegmentStore(directory, vocab)` backed by a directory of Markdown files, using the serializer to read/write segments and the same validation (against the bound vocabulary) and query semantics as the in-memory adapter.
  - Observable completion: a unit test writes segments to a temporary directory, reads them back, and confirms axis queries and `list_segments` behave identically to the in-memory adapter.
  - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 9.7_
  - _Boundary: store_
  - _Depends: 4.1, 2.5_

- [x] 5. Consumer: role-view derivation
- [x] 5.1 Implement role-view derivation
  - Build a role view by querying the store for segments carrying the given role id, ordering them by the loaded `Vocabulary`'s intent order (`vocab.intent_order()`) with a stable secondary key for ties, and returning an empty view (not an error) when no segment matches.
  - Observable completion: a unit test confirms a multi-role segment appears in each of its roles' views, segments are ordered by the vocabulary's intent order then the tie-break key, and a role with no segments yields an empty view.
  - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5_
  - _Boundary: views_
  - _Depends: 4.1, 2.2_

- [x] 6. Integration and validation
- [x] 6.1 Wire and export the public ontology API
  - Populate `docuharnessx/ontology/__init__.py` to re-export the `Vocabulary` loader / default-profile / config-serializer API (`load_vocabulary`, `default_profile`, `default_profile_config`, `vocabulary_to_config`), `Segment`, `SCHEMA_VERSION`, validation entry points, tag emission, the `SegmentStore` port + `AxisFilter` + both store adapters, and role-view derivation as the stable public surface.
  - Observable completion: a unit test imports every documented public name directly from `docuharnessx.ontology` and confirms each is callable/usable.
  - _Requirements: 1.2, 1.4, 4.1, 5.1, 9.1, 11.3_
  - _Boundary: __init___
  - _Depends: 2.1, 2.2, 2.3, 2.4, 2.5, 3.1, 3.2, 4.1, 4.2, 5.1_

- [x] 6.2 Add the shared store-conformance and determinism test suite
  - Add a parametrized conformance suite that runs identical scenarios against both `InMemorySegmentStore` and `FilesystemSegmentStore` (put/validation rejection, id conflict, axis OR/AND queries, deterministic listing), plus determinism tests asserting byte-identical results for vocabulary loading, validation, tagging, query, and role-view operations on identical inputs.
  - Add a check asserting the core modules import no network/LLM dependency.
  - Observable completion: the parametrized suite passes for both adapters and the determinism/no-LLM assertions pass in CI.
  - _Requirements: 9.3, 9.4, 9.5, 9.6, 11.1, 11.2, 11.3, 11.4_
  - _Boundary: store, validation, tags, views, vocabulary_
  - _Depends: 6.1_

## Implementation Notes

- **1.1**: `docuharnessx/ontology/__init__.py` is minimal (docstring only); full public re-exports are deferred to task 6.1. Package root `docuharnessx/__init__.py` + `pyproject.toml` were bootstrapped (skeleton-owned) before this spec to enable building ontology first. Tests live under `tests/ontology/`; pytest rootdir discovery works without `tests/__init__.py`. Validation command: `cd /home/mc/Source/DocuHarnessX && .venv/bin/python -m pytest -q`.
- **1.2**: Error model lives in `docuharnessx/ontology/errors.py`. All errors subclass `OntologyError(Exception)` — they are raisable AND carry structured attributes for collection. De-facto constructor contract (downstream tasks MUST use these signatures):
  - `MalformedConfigError(config_path, reason="")`
  - `MalformedFrontmatterError(segment_id=None, reason="")`
  - `MissingFieldError(field, segment_id=None)`
  - `UnknownRoleError(value, field="roles", segment_id=None)`
  - `UnknownIntentError(value, field="intent", segment_id=None)`
  - `MalformedSubjectError(value, segment_id=None)`
  - `VersionMismatchError(declared, supported, segment_id=None)`
  - `DuplicateIdError(segment_id)`
  - `UnresolvedLinkError(target_id, segment_id=None)`
  - `SelfReferenceError(segment_id)`
  - `IdConflictError(segment_id)`
  - `ValidationResult(segment_id=None, errors=())` → `.is_valid`, `.errors` (tuple)
  - `SetValidationResult(errors=())` → `.is_valid`, `.errors` (tuple)
- **2.1**: `docuharnessx/ontology/model.py`. `AxisTerm(id, label, description="")` frozen dataclass (id stable, distinct from label, NOT an enum). `Subject(prefix, local)` frozen dataclass; `@classmethod Subject.parse(raw, allowed_prefixes: frozenset[str]) -> Subject` (allowed_prefixes is a param, raises `MalformedSubjectError(raw)` on unknown prefix / empty local); `canonical() -> "prefix:local"` (bare, feeds the `subject:<prefix:local>` tag in 2.4). Normalization casefolds prefix+local and strips a trailing colon on the prefix, so parse tolerates both `"component"` and `"component:"` allowed-prefix forms. GUIDANCE for 2.2: store ONE canonical prefix form in `Vocabulary.subject_prefixes` — use the trailing-colon written form (`component:`) to match Req 3.1; ensure `load_vocabulary(vocabulary_to_config(v)) == v` round-trips. Subjects are case-folded (spec is silent on case) — keep consistent downstream.
- **2.2**: `docuharnessx/ontology/vocabulary.py`. Frozen public API: `load_vocabulary(config_path_or_mapping)`, `default_profile() -> Vocabulary`, `default_profile_config() -> dict`, `vocabulary_to_config(vocab) -> dict`. `Vocabulary` is a frozen dataclass with `.roles`/`.intents` (tuples of `AxisTerm`), `.subject_prefixes` (ordered **tuple** of colon-form prefixes — NOT frozenset; pass `frozenset(vocab.subject_prefixes)` into `Subject.parse`), `.has_role(id)`, `.has_intent(id)`, `.intent_order()`, meaningful `__eq__`. `load_vocabulary` uses `yaml.safe_load`, missing file → default profile, present-but-invalid → `MalformedConfigError`, `profile` resolves base-then-overrides; accepts a path OR a parsed mapping (the round-trip vehicle). Round-trip `load_vocabulary(vocabulary_to_config(v)) == v` holds. AUTHORITATIVE default ids — ROLES: possible-adopter, developer, tech-savvy-user, manager, devops-admin, researcher, security-compliance-officer, contributor, integrator, support-sre. INTENTS (= intent_order for role views): install, configure, use, troubleshoot, monitor, operate, integrate, extend, evaluate, assess-quality, understand, contribute, deliver. PREFIXES: component:, tech:, artifact:, topic:.
- **2.3**: `docuharnessx/ontology/schema.py`. `Segment(id, title, roles: list[str], subjects: list[Subject], intent: str, summary="", related=[], body="", schema_version=SCHEMA_VERSION)` — plain (mutable) dataclass; roles/intent are vocabulary **id strings**, subjects are `Subject` objects. `SCHEMA_VERSION: int = 1`. `REQUIRED_FIELDS = ("id","title","roles","subjects","intent")`. `FROZEN_FIELDS_BY_VERSION: dict[int, tuple]`. `is_version_compatible(declared: int|None) -> bool` (None→current). `check_version(declared, segment_id=None)` raises `VersionMismatchError`. Module is vocabulary-free. Validation (required-field presence, non-empty roles/subjects Req 4.5, id-uniqueness Req 4.6, vocab membership) is OWNED by tasks 3.1/3.2, not the schema.
- **2.4**: `docuharnessx/ontology/tags.py`. `emit_tags(segment: Segment, vocab: Vocabulary) -> tuple[str, ...]`. Forms: `role:<id>` per role, one `intent:<id>`, `subject:<prefix:local>` per subject (via `Subject.canonical()`). Only emits vocab-valid axis values. Order: roles (declared) → intent → subjects (declared); stable, tested. FOLLOW-UP (non-blocking, for task 6.2 or a cleanup): tags.py re-implements prefix normalization identical to `model._normalize_prefix` — refactor to reuse the single canonical normalizer (expose a public helper in model/vocabulary) before any change to prefix-normalization semantics, to avoid silent divergence.
- **2.5**: `docuharnessx/ontology/serializer.py`. `parse_segment(text) -> ParsedSegment` (raw mapping + opaque body; raises `MalformedFrontmatterError` on missing fence / invalid YAML / non-mapping; `yaml.safe_load`). `to_segment(parsed, vocab) -> Segment` (keeps roles/intent as raw id strings; coerces subjects via `Subject.parse(raw, frozenset(vocab.subject_prefixes))` which RAISES `MalformedSubjectError` on bad prefix — so segments parsed via the serializer already have vocab-valid subjects; uses `.get(...,"")` defaults so MISSING required fields become empty strings, deferring required-field-presence reporting to validation 3.1). `serialize_segment(segment) -> str` (deterministic, canonical key order id,title,roles,subjects,intent,summary,related,schema_version; subjects as canonical prefix:local; `safe_dump sort_keys=False`). GUIDANCE for 3.1: validation receives a `Segment` and must treat empty/missing required fields (id/title/roles/subjects/intent) as `MissingFieldError`, and still re-check role/intent/subject-prefix membership against the supplied vocab (a Segment may be built programmatically or validated against a different vocab than it was parsed with).
- **3.1**: `docuharnessx/ontology/validation.py`. `validate_segment(segment: Segment, vocab: Vocabulary) -> ValidationResult`. Aggregates ALL errors (no short-circuit), stable order: version → required-fields (empty str/list = missing) → roles (per invalid) → intent → subjects (per invalid prefix). Vocab-relative; segment_id = segment.id or None. Reuses `model._normalize_prefix` for subject-prefix checks. CONSOLIDATION CLEANUP for task 6.x: prefix normalization now lives in 3 sites (model canonical, tags.py inlined copy, validation imports the private `_normalize_prefix`) — promote ONE public `normalize_prefix` in model and converge tags + validation onto it.
- **3.2**: also in `docuharnessx/ontology/validation.py`. `validate_segment_set(segments: Sequence[Segment], vocab: Vocabulary) -> SetValidationResult` (set-level ONLY: id-uniqueness via `DuplicateIdError` per-occurrence-after-first, + cross-link reporting `SelfReferenceError`/`UnresolvedLinkError`; does NOT re-run per-segment validate). `resolve_links(segment: Segment, index: Mapping[str, Segment]) -> list[Segment]` (declared order; silently skips self/unknown). The store (4.1) composes per-segment `validate_segment` in `put` and builds the id→Segment index for `resolve_cross_links`.
- **4.1**: `docuharnessx/ontology/store.py` — FROZEN seam (verbatim). `@dataclass(frozen=True) AxisFilter(roles: tuple[str,...]=(), intents: tuple[str,...]=(), subjects: tuple[Subject,...]=())`. `@runtime_checkable class SegmentStore(Protocol)` with `put(self, segment: Segment) -> None`, `query(self, where: AxisFilter) -> tuple[Segment, ...]`, `list_segments(self) -> tuple[Segment, ...]`, `resolve_cross_links(self, segment_id: str) -> tuple[Segment, ...]`. `InMemorySegmentStore(vocab)`: put validates via `validate_segment` (raises first error, nothing stored) + `IdConflictError` on dup id; query = per-axis OR / cross-axis AND, empty filter = all; ORDERING = **by segment id** (`sorted`), the single determinism authority. `resolve_cross_links` unknown id → `()`. RULING for 4.2: `FilesystemSegmentStore` MUST use the same by-id ordering so fs and in-memory return identical results for identical content.
- **4.2**: also in `docuharnessx/ontology/store.py`. `FilesystemSegmentStore(directory, vocab)` — `<id>.md` files via serializer; dir auto-created; lazy re-read per call. Shared module-level helpers (`_validate_for_put`, `_order_by_id`, `_matches`, `_query`, `_resolve_cross_links`) now back BOTH adapters (InMemory refactored to delegate; public behavior + frozen signatures unchanged). Parity test confirms fs == in-memory. For 6.2: still author the parametrized conformance suite running identical scenarios against both adapters as a shared fixture.
- **5.1**: `docuharnessx/ontology/views.py`. `build_role_view(store: SegmentStore, role_id: str, vocab: Vocabulary) -> tuple[Segment, ...]`. Queries `AxisFilter(roles=(role_id,))`, orders by `vocab.intent_order()` then segment id (unknown intents last), empty view (not error) for no matches. Reviewer-APPROVED.
- **cleanup-normalizer (DONE)**: the 2.4/3.1 follow-up is resolved. `model.normalize_prefix(prefix) -> str` is now PUBLIC (private `_normalize_prefix` aliases it); `tags.py` and `validation.py` both use the public function (no duplicated logic). Single source of truth. Reviewer-APPROVED.
- **6.1**: `docuharnessx/ontology/__init__.py` re-exports the full public surface with `__all__` (46 names) covering every submodule; `tests/ontology/test_public_api.py` drift-guards it. Frozen-seam names import directly from `docuharnessx.ontology`. Reviewer-APPROVED.
- **6.2**: `tests/ontology/test_store_conformance.py` — pytest-parametrized over BOTH adapters (in-memory + filesystem via tmp_path), plus determinism tests (vocab load/round-trip, validation, tagging, query, role-view) and a no-network/no-LLM import assertion (only `yaml` permitted as third-party). Reviewer-APPROVED.
- **HARDENING (post-validation, ultracode)**: closed two non-blocking edge cases the adversarial validation lens found, both now typed `MalformedFrontmatterError`: (a) `serializer.to_segment` non-integer `schema_version` (was raw ValueError) — aligns Req 6.3; (b) `FilesystemSegmentStore` id containing a path separator / `.`/`..` (was raw FileNotFoundError + dir escape). Tests in `tests/ontology/test_hardening.py`.

## Spec Status

ontology-engine implementation COMPLETE. Final validation panel (4 adversarial lenses + synthesis) returned **GO**, no blocking issues; frozen seam verified verbatim. Full suite: **220 passed** (`.venv/bin/python -m pytest -q`). Git commits deferred per user. Ready for downstream specs to depend on the frozen contract.
