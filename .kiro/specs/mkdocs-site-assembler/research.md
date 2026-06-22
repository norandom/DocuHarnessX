# Research & Design Decisions — mkdocs-site-assembler

## Summary
- **Feature**: `mkdocs-site-assembler`
- **Discovery Scope**: Extension (in-place replacement of an existing no-op stage stub on a merged Wave 0-2 foundation).
- **Key Findings**:
  - Every consumed contract already exists on `main` and is frozen/stable: `ReviewReport.accepted: tuple[Segment, ...]` (review/model.py, schema v1), `Vocabulary` + `build_role_view` + `emit_tags` (ontology), `RepoAnalysis` (analysis/model.py, schema v1). The assembler is a pure consumer — it reimplements none of them.
  - The stage-replacement pattern is established and proven by the now-real Plan/Write/Review stages: keep `STAGE_NAME`/class/factory/module-path/`make_noop_stage` re-export stable, subclass `NoOpStage`, capture run `State` in `on_task_start`, do the work in `on_step_end`, yield the event unchanged, publish to a slot. The registry (`STAGES`) and `bundle.make_docgen` need no edits.
  - `RunContext` + `types.py` are extended **append-only** by each wave (file_inventory → repo_analysis → classification → coverage_plan → written_segments → review_report). This spec adds exactly one more pair: `SLOT_ASSEMBLED_SITE` + `set_assembled_site`/`assembled_site`.
  - The CLI `orchestrate_run` already provisions `SLOT_TARGET_REPO`, `SLOT_OUTPUT_DIR`, `SLOT_VOCABULARY`, and `SLOT_SEGMENT_STORE` before the run. The assembler reads those plus `SLOT_REVIEW_REPORT` and `SLOT_REPO_ANALYSIS`; **no CLI change is required** to provision new inputs (unlike Wave 2, which needed the store provisioned).
  - The reference target `/home/mc/Source/malware_hashes` has remote `https://github.com/norandom/malware_hashes.git` → owner `norandom`, repo `malware_hashes` → `site_url=https://norandom.github.io/malware_hashes/`, base-path `/malware_hashes/`.

## Research Log

### Consumed contract: ReviewReport.accepted
- **Context**: The assembler must consume the passed segments verbatim, read-only.
- **Sources Consulted**: `docuharnessx/review/model.py` (frozen `ReviewReport`, `REVIEW_REPORT_SCHEMA_VERSION = 1`).
- **Findings**: `ReviewReport.accepted` is a `tuple[Segment, ...]` of the *same* ontology `Segment` identities present in the store, in written/priority order. `Segment` is a non-frozen dataclass (`id, title, roles[], subjects[], intent, summary, related[], body`). The report carries `schema_version`.
- **Implications**: Pin `REVIEW_REPORT_SCHEMA_VERSION` at the stage boundary (mirror ReviewStage pinning `COVERAGE_PLAN_SCHEMA_VERSION`). Treat each `Segment` read-only; never mutate `related`/`roles`.

### Reusing the ontology role-view and tag APIs
- **Context**: Per-role agendas must be intent-ordered and tags must be namespaced — both already solved in `ontology-engine`.
- **Sources Consulted**: `ontology/views.py` (`build_role_view(store, role_id, vocab)`), `ontology/tags.py` (`emit_tags(segment, vocab)`), `ontology/vocabulary.py` (`Vocabulary.intent_order()`, `has_role`, `roles`/`intents` of `AxisTerm{id,label,description}`).
- **Findings**: `build_role_view` queries a `SegmentStore` via `AxisFilter(roles=(role_id,))` and orders by `vocab.intent_order()` with `id` tie-break — exactly the agenda order needed. `emit_tags` returns the deterministic `role:`/`intent:`/`subject:` tag tuple, vocabulary-valid only. `AxisTerm` carries `label`+`description` for the SCQA opener.
- **Implications**: The assembler needs a `SegmentStore` populated with the accepted segments to call `build_role_view`. Decision below: build an ephemeral `InMemorySegmentStore` from the accepted set rather than relying on the run's `SLOT_SEGMENT_STORE` (which holds all written segments, including rejected ones). This guarantees agendas contain ONLY accepted segments and keeps the assembler self-contained and deterministic.

### Site identity from the target git remote
- **Context**: Locked multi-project requirement — site identity is per-target, from the target remote, never DocuHarnessX's.
- **Sources Consulted**: `git -C /home/mc/Source/malware_hashes remote -v`; Material for MkDocs config docs (`site_url`, `use_directory_urls`, `repo_url`, `edit_uri`, `theme.name: material`, `plugins: [tags]`).
- **Findings**: GitHub project Pages serve at `https://<owner>.github.io/<repo>/`, so `site_url` MUST carry the `/<repo>/` subpath for assets/links to resolve. `use_directory_urls: true` (Material default) combined with a correct `site_url` makes relative links resolve under the subpath. Remote parsing must handle HTTPS + SSH forms and strip `.git`.
- **Implications**: A small deterministic `git remote get-url origin` parse (stdlib `subprocess`, read-only, no network) yields `owner/repo`. Fallbacks: no remote → target-dir basename as `site_name`, root base-path; non-GitHub remote → keep `repo_url`, root base-path. Overrides come from `DocgenConfig`/flags (the existing config layer) — the assembler accepts an already-resolved identity-override mapping so it stays pure.

### MkDocs build validation without network
- **Context**: Req 8.4 requires `mkdocs build` to succeed with the per-target base-path; the brief says build validation runs `mkdocs build`.
- **Sources Consulted**: brief (assembler), github-pages-deploy brief (the deploy stage runs `mkdocs build` as its credential-free validation).
- **Findings**: `mkdocs build` is offline and credential-free. The two briefs split responsibility: the assembler *emits* the buildable source; the deploy stage *runs* `mkdocs build` as part of publish validation. To keep the assembler's own acceptance honest (Req 8.4), the assembler's test suite runs `mkdocs build` on the emitted tree (a test-time check), but the stage itself does not shell out at runtime — keeping it deterministic and dependency-light at run time.
- **Implications**: Declare `mkdocs` + `mkdocs-material` as runtime deps (the deploy stage needs them at run time; the assembler tests need them). The assembler runtime does pure file emission only.

## Architecture Pattern Evaluation

| Option | Description | Strengths | Risks / Limitations | Notes |
|--------|-------------|-----------|---------------------|-------|
| Pure core + thin stage adapter (CHOSEN) | A deterministic, harness-free `assembler` package (identity resolver, page renderer, role-page renderer, mkdocs.yml builder, site writer) wrapped by a thin `AssembleStage` that reads slots and publishes `AssembledSite` | Mirrors review/write/plan; unit-testable without a harness; byte-stable | Requires one more package | Matches steering "behavior lives in processors / pure core"; review gate is the precedent |
| Logic inside the stage class | Put rendering directly in `AssembleStage.on_step_end` | Fewer files | Not unit-testable without a harness; violates the established pattern | Rejected |
| Template engine (Jinja) for pages | Render via a templating dependency | Familiar | New dependency; non-trivial determinism; overkill for Markdown | Rejected — deterministic f-string/`io` Markdown emission is simpler and byte-stable |

## Design Decisions

### Decision: Ephemeral in-memory store for role views, built from the accepted set
- **Context**: `build_role_view` needs a `SegmentStore`; the run's `SLOT_SEGMENT_STORE` holds ALL written segments (including review-rejected ones).
- **Alternatives Considered**:
  1. Reuse the run `SegmentStore` and filter — risks including rejected segments in agendas; couples the assembler to store contents.
  2. Build a fresh `InMemorySegmentStore` from `ReviewReport.accepted` and pass it to `build_role_view`.
- **Selected Approach**: Option 2. The assembler `put`s each accepted segment into a fresh `InMemorySegmentStore(vocab)`, then calls `build_role_view(store, role_id, vocab)` per role. Accepted-only and deterministic.
- **Rationale**: Guarantees agendas reflect exactly the published pages; keeps the assembler self-contained; reuses the frozen ontology APIs verbatim.
- **Trade-offs**: A second in-memory store instance at run time — negligible for a 25-40k LOC repo's segment count.

### Decision: AssembledSite is frozen, versioned, and owns SLOT_ASSEMBLED_SITE
- **Context**: The deploy spec consumes the seam; it must be stable like `ReviewReport`/`RepoAnalysis`.
- **Selected Approach**: A `@dataclass(frozen=True) AssembledSite` with `schema_version`, `site_dir`, `mkdocs_yml_path`, and a nested frozen `SiteIdentity` (`site_name`, `repo_url`, `repo_name`, `site_url`, `base_path`, `edit_uri`). `ASSEMBLED_SITE_SCHEMA_VERSION = 1`. Append `SLOT_ASSEMBLED_SITE` to `types.py` and `set_assembled_site`/`assembled_site` to `RunContext`, append-only.
- **Rationale**: Mirrors the frozen seam pattern; gives the deploy stage everything it needs (where the source is + the per-target Pages identity) without re-parsing the remote.
- **Trade-offs**: One more slot; acceptable and consistent with the established append-only seam pattern.

### Decision: Site identity resolution is pure; the stage resolves overrides before calling the core
- **Context**: Overrides come from `.docuharnessx/` config / `dhx` flags; the core must stay deterministic and harness-free.
- **Selected Approach**: A pure `resolve_site_identity(target_repo, remote_url, overrides)` function takes the already-read remote URL string (or `None`) and an overrides mapping, and returns a `SiteIdentity`. The stage performs the read-only `git remote get-url origin` call (a thin, mockable helper) and reads overrides from the config slot/flags, then calls the pure resolver. Tests drive the resolver directly with crafted remote strings — no real git needed.
- **Rationale**: Keeps the network/process-touching surface (the git read) tiny and isolated; the identity logic itself is a pure, fully-tested transform across HTTPS/SSH/non-GitHub/no-remote.

## Risks & Mitigations
- **Risk**: Material `tags` plugin or theme name drift breaks `mkdocs build`. — Pin the known-good `mkdocs.yml` shape (`theme.name: material`, `plugins: [tags]`) and assert `mkdocs build` succeeds in tests across default + custom vocab + varying remotes.
- **Risk**: Broken internal links under the `/<repo>/` base-path. — Use relative links between generated pages and set `site_url` with the subpath + `use_directory_urls`; the build test fails on broken nav.
- **Risk**: Non-deterministic ordering (dict iteration, role order). — Drive every order from the vocabulary (`roles` tuple order, `intent_order()`) and segment `id` tie-breaks; assert byte-stability across two runs.
- **Risk**: Accidentally documenting DocuHarnessX's own repo. — Identity is always derived from the passed target repo path; the per-run output dir is the only write target; a test asserts a non-DocuHarnessX identity for a target run.

## References
- `docuharnessx/review/model.py` — `ReviewReport`, `REVIEW_REPORT_SCHEMA_VERSION`.
- `docuharnessx/ontology/{views,tags,vocabulary,store,schema}.py` — reused read-only APIs.
- `docuharnessx/analysis/model.py` — `RepoAnalysis` (site-identity context).
- `docuharnessx/context.py`, `docuharnessx/types.py`, `docuharnessx/stages/{base,review,__init__}.py`, `docuharnessx/cli.py` — extension points + the stage-replacement precedent.
- Material for MkDocs configuration (`site_url`, `use_directory_urls`, `repo_url`, `edit_uri`, theme, tags plugin).
