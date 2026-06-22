# Requirements Document

## Introduction

The Assemble stage is the bridge from "quality-gated segments in a store" to "a navigable, aesthetic website". The DocuHarnessX pipeline (Ingest → Analyze → Classify → Plan → Write → Review → Assemble → Deploy) currently ships `assemble` as a no-op stub: the upstream `quality-review-gate` has already produced a frozen `ReviewReport` whose `accepted` set is the segments that passed the COBESY quality gate, but nothing yet turns those segments into a publishable site.

This feature replaces that stub **in place** with the real Assemble stage. It consumes the accepted `Segment` set (verbatim, read-only), the loaded project `Vocabulary`, and the optional `RepoAnalysis` (for site identity), and emits a **Material for MkDocs** source tree under the run's output directory: one `docs/*.md` page per accepted segment, per-role landing pages with COBESY-structured guided agendas ordered by the vocabulary's intent order, tags-driven navigation, cross-links, content-tabs/admonitions for role switching, and a `mkdocs.yml` configuring the Material theme and the tags plugin.

Because DocuHarnessX documents **arbitrary target projects**, the site identity is derived **per-target** from the target repository's git remote — `site_name`, `repo_url`, `repo_name`, `edit_uri`, and crucially `site_url` plus the `/<repo>/` GitHub Pages base-path — never hardcoded to DocuHarnessX's own identity. The reference target `/home/mc/Source/malware_hashes` (remote `github.com/norandom/malware_hashes`) must resolve to a site published under the `/malware_hashes/` Pages subpath.

Assembly is **deterministic** (no model call): the same accepted segments, vocabulary, and target identity always produce a byte-stable site source tree, so the stage is fully unit-testable, and the generated `mkdocs.yml` must build cleanly under `mkdocs-material`. The stage publishes its result as a new `AssembledSite` value object on a new `SLOT_ASSEMBLED_SITE` slot — the stable seam the downstream `github-pages-deploy` stage consumes.

## Boundary Context

- **In scope**: Replacing the `assemble` stub in place; consuming `ReviewReport.accepted` + `Vocabulary` + optional `RepoAnalysis` + the ontology role-view/tag APIs; deriving per-target site identity (name/repo_url/site_url/base-path) from the target git remote with config/flag override and graceful fallback; emitting the Material for MkDocs source tree (`docs/*.md`, per-role landing pages + intent-ordered agendas, tags nav, cross-links, content-tabs/admonitions) and a `mkdocs.yml`; owning the `AssembledSite` value object and the new `SLOT_ASSEMBLED_SITE` seam; declaring `mkdocs` + `mkdocs-material` as dependencies.
- **Out of scope**: Publishing / GitHub Pages deployment, the GitHub Actions workflow emission, and `mkdocs gh-deploy` (owned by `github-pages-deploy`); repo scanning, classification, planning, writing, and reviewing (upstream waves); the segment frontmatter schema, the `Vocabulary` loader, `build_role_view`, and `emit_tags` (owned by `ontology-engine`, reused read-only); the `ReviewReport` shape (owned by `quality-review-gate`, consumed verbatim).
- **Adjacent expectations**: The accepted `Segment` objects are read-only and carry the same identities the upstream store/written set holds. The Assemble stage reads run data exclusively through the existing `RunContext` slots and replaces exactly one stub, leaving the stage registry, the bundle, and every sibling stage untouched. The downstream deploy stage reads the output directory, the target repo path, and the new `AssembledSite` seam from the run context.

## Requirements

### Requirement 1: In-place replacement of the Assemble stage stub

**Objective:** As a pipeline maintainer, I want the real Assemble stage to drop into exactly the slot the no-op stub occupied, so that the stage registry and the `make_docgen` bundle need no edits and a single-stage swap is preserved.

#### Acceptance Criteria
1. The Assemble Stage shall preserve the stable stage identity — the `STAGE_NAME` value `"assemble"`, the `AssembleStage` class name, the `make_assemble_stage` factory name, the `make_noop_stage` re-export, and the module path `docuharnessx.stages.assemble` — unchanged from the stub it replaces.
2. The Assemble Stage shall subclass the shared no-op stage base and attach to the same pipeline hook so the stage registry and the bundle composition require no edits.
3. While the stage is driven outside a harness with no bound run state, the Assemble Stage shall forward the lifecycle event unchanged and produce no site, exactly as the no-op base does.
4. When the stage runs as a side effect of the content-free lifecycle event, the Assemble Stage shall yield that event unchanged and modify no generated conversation content, publishing its result only into a run-context slot.

### Requirement 2: Consuming the accepted segments and run inputs

**Objective:** As the Assemble stage, I want to read the passed segments and the project vocabulary from the run context, so that I assemble exactly the quality-gated content under the active project ontology.

#### Acceptance Criteria
1. While a run state is bound, the Assemble Stage shall read the `ReviewReport` from the review-report slot, the loaded `Vocabulary` from the vocabulary slot, the optional `RepoAnalysis` from the analysis slot, the resolved output directory, and the target-repository path through the typed run-context accessors.
2. The Assemble Stage shall assemble the site from the `ReviewReport.accepted` set verbatim, treating each accepted `Segment` as read-only and never mutating it.
3. If the review-report slot or the vocabulary slot is unset while a run state is bound, then the Assemble Stage shall raise a typed assembler input error naming the missing slot and produce no site.
4. If the consumed `ReviewReport` declares a schema version this build does not support, then the Assemble Stage shall raise a typed assembler input error naming the unsupported version and produce no site.
5. Where the `RepoAnalysis` slot is unset, the Assemble Stage shall proceed with graceful site-identity fallback and produce a site without raising.
6. If the resolved output directory is unset while a run state is bound, then the Assemble Stage shall raise a typed assembler input error and produce no site.

### Requirement 3: Per-target site identity from the target git remote

**Objective:** As an operator documenting an arbitrary target project, I want the site identity derived from my target's git remote, so that the published site is correctly named and resolves under my project's GitHub Pages subpath rather than DocuHarnessX's.

#### Acceptance Criteria
1. The Assemble Stage shall derive the site identity — `site_name`, `repo_url`, `repo_name`, `edit_uri`, and `site_url` — from the target repository's `origin` git remote by parsing the `owner/repo` pair.
2. When the target remote is a GitHub remote for `owner/repo`, the Assemble Stage shall compute `site_url` as the project GitHub Pages URL `https://<owner>.github.io/<repo>/` and set the `/<repo>/` value as the site base-path.
3. The Assemble Stage shall configure `site_url` and directory-URL handling in the generated `mkdocs.yml` so internal links and static assets resolve under the project's `/<repo>/` Pages subpath.
4. The Assemble Stage shall parse both HTTPS (`https://github.com/<owner>/<repo>.git`) and SSH (`git@github.com:<owner>/<repo>.git`) GitHub remote forms, stripping any trailing `.git` suffix.
5. If the target has no git remote, then the Assemble Stage shall fall back to a target-directory-derived `site_name` with an empty `repo_url`/`edit_uri` and a root base-path, and produce a buildable site without raising.
6. If the target's `origin` remote is not a GitHub remote, then the Assemble Stage shall set `repo_url` to the detected remote URL while falling back to a root base-path and a target-derived `site_name`, and produce a buildable site without raising.
7. Where a `.docuharnessx/` site-identity configuration value or a `dhx` flag override is provided for `site_name`, `site_url`, `repo_url`, or `edit_uri`, the Assemble Stage shall use the override in place of the git-remote-derived value.
8. The Assemble Stage shall never derive or emit DocuHarnessX's own repository identity or Pages URL for a target run; the identity is always per-target.

### Requirement 4: Emitting one Markdown page per accepted segment

**Objective:** As a reader, I want each accepted content segment rendered as a Material for MkDocs page with its frontmatter-derived tags, so that the corpus is browsable and the segment's body is preserved.

#### Acceptance Criteria
1. The Assemble Stage shall emit one `docs/*.md` page under the output directory for each segment in the `ReviewReport.accepted` set, with a stable, deterministic page filename derived from the segment id.
2. The Assemble Stage shall write each page's title and the segment's Markdown body into the page, preserving the body content.
3. The Assemble Stage shall emit page frontmatter carrying the namespaced tag set produced by the ontology `emit_tags` API for the segment under the loaded vocabulary, so the Material tags plugin indexes the page.
4. The Assemble Stage shall render the segment's cross-links — the segment's `related` references — as in-page Markdown links to the corresponding generated pages, omitting any reference that has no corresponding accepted page.
5. The Assemble Stage shall emit the same page bytes for the same accepted segment, vocabulary, and target identity on repeated runs.

### Requirement 5: Per-role landing pages and intent-ordered guided agendas

**Objective:** As a reader in a given role, I want a landing page and a guided agenda ordered for my role, so that I reach first success on the shortest path framed for me.

#### Acceptance Criteria
1. The Assemble Stage shall emit one per-role landing page for each role in the loaded vocabulary that has at least one accepted segment carrying that role.
2. The Assemble Stage shall order each role's agenda by the loaded vocabulary's intent order, deriving the role's segment view through the ontology `build_role_view` API against a store populated with the accepted segments.
3. The Assemble Stage shall open each role landing page with a COBESY SCQA-style introduction that uses the role's display label and description from the loaded vocabulary, never a hardcoded role name.
4. The Assemble Stage shall render each role agenda as ordered links to the per-segment pages, so the role view is navigable without duplicating segment bodies.
5. Where the loaded vocabulary defines a role that no accepted segment carries, the Assemble Stage shall omit that role's landing page rather than emit an empty agenda.
6. The Assemble Stage shall derive roles, intents, and their ordering exclusively from the loaded `Vocabulary`, so a project that renames or reorders its vocabulary terms changes the generated landing pages and agendas with no code change.

### Requirement 6: Navigation, tags, and role-switching presentation

**Objective:** As a reader, I want tags-driven navigation and clear role-switching affordances, so that I can move between role views and discover related content.

#### Acceptance Criteria
1. The Assemble Stage shall generate the `mkdocs.yml` navigation referencing the per-role landing pages and the tags index, in a deterministic order.
2. The Assemble Stage shall configure the Material `tags` plugin in the generated `mkdocs.yml` so the namespaced `role:`/`subject:`/`intent:` tags produce a browsable tags index.
3. The Assemble Stage shall render role-switching affordances on the landing pages using Material content-tabs or admonitions, so a reader can move between role views.
4. The Assemble Stage shall configure the Material theme in the generated `mkdocs.yml`.

### Requirement 7: The AssembledSite output seam

**Objective:** As the downstream deploy stage, I want a stable `AssembledSite` value object on a dedicated slot, so that I can publish the assembled site without re-deriving its layout or identity.

#### Acceptance Criteria
1. When assembly completes, the Assemble Stage shall publish a frozen `AssembledSite` value object into the new assembled-site slot through a typed run-context accessor.
2. The `AssembledSite` value object shall carry the site source directory, the `mkdocs.yml` path, and the resolved per-target site metadata, including `site_name`, `repo_url`, `repo_name`, `site_url`, the `/<repo>/` base-path, and `edit_uri`.
3. The `AssembledSite` value object shall carry a single schema-version field, and a change to its frozen field set shall be a revalidation trigger for the deploy spec.
4. While the assembled-site slot is unset, a read through the run-context accessor shall return an explicit absent value rather than raising, matching the existing slot accessors.
5. The Assemble Stage shall add the assembled-site slot key and its run-context accessor as append-only additions, modifying no existing slot key, stage name, stage-name tuple entry, or existing run-context accessor.

### Requirement 8: Determinism, dependencies, and buildability

**Objective:** As a maintainer, I want the assembly deterministic and the output buildable without a model or network, so that the stage is reproducible and unit-testable.

#### Acceptance Criteria
1. The Assemble Stage shall perform no model call and no network access; the assembly is purely a deterministic transform over the accepted segments, the vocabulary, and the resolved target identity.
2. The Assemble Stage shall produce a byte-stable site source tree — identical `docs/*.md` pages, `mkdocs.yml`, and directory layout — for identical accepted segments, vocabulary, and target identity across repeated runs.
3. The project shall declare `mkdocs` and `mkdocs-material` as runtime dependencies.
4. The generated `mkdocs.yml` shall build cleanly under `mkdocs-material` via `mkdocs build`, producing a static site with the per-target base-path, with no broken internal links among the generated pages.
5. While documenting one target in a single run, the Assemble Stage shall write the site only under that run's resolved output directory for that one target, never into DocuHarnessX's own repository or a second target.
