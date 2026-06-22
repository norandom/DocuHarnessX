# Implementation Plan

- [x] 1. Foundation: assembler package, frozen seam, dependencies, append-only slot
- [x] 1.1 Declare the MkDocs runtime dependencies and scaffold the assembler package
  - Add `mkdocs` and `mkdocs-material` to the project's runtime dependencies so the assembled site can build and the deploy stage can run `mkdocs build`.
  - Create the `docuharnessx/assembler/` package with a single public namespace, mirroring the existing pure-core package layout (review/composition/planning).
  - Observable completion: a fresh environment install pulls in `mkdocs` + `mkdocs-material`; importing the new package succeeds and exposes its (initially empty) public surface.
  - _Requirements: 8.3_
  - _Boundary: assembler package, pyproject_

- [x] 1.2 Define the frozen AssembledSite + SiteIdentity model, version authority, and error family
  - Define the frozen, deeply-immutable `SiteIdentity` (site_name, repo_name, repo_url, site_url, base_path, edit_uri) and `AssembledSite` (schema_version, site_dir, docs_dir, mkdocs_yml_path, identity, page_count, role_page_count) value objects, plus the single `ASSEMBLED_SITE_SCHEMA_VERSION` constant.
  - Define the assembler error family (a base error and a fatal input error), kept independent of the other specs' error families, matching the review/writer error pattern.
  - Observable completion: importing the model exposes the two value objects, the version constant, and the error types; constructing an `AssembledSite` from sample values yields a frozen, structurally-equal value object (two equal constructions compare equal).
  - _Requirements: 7.1, 7.2, 7.3, 2.3_
  - _Boundary: AssembledSite model_
  - _Depends: 1.1_

- [x] 1.3 Append the assembled-site slot key and run-context accessor (append-only seam)
  - Append the assembled-site slot-key constant to the shared types module and add it to that module's export list, modifying no existing slot key, stage name, or stage-name tuple entry.
  - Append the typed set/read accessors and the slot-type tag to the run context, with a TYPE_CHECKING import of the model; an unset slot returns the absent value like every other accessor.
  - Observable completion: setting then reading the assembled-site slot through the run context round-trips the value; reading it on a fresh state returns the absent value; existing slot accessors and exports are unchanged.
  - _Requirements: 7.4, 7.5_
  - _Boundary: types/context additions_
  - _Depends: 1.2_

- [x] 2. Core: deterministic site-identity resolution
- [x] 2.1 Implement the pure per-target site-identity resolver
  - Implement a pure resolver that takes the target path, an optional origin remote URL string, and an overrides mapping, and returns a `SiteIdentity`: parse GitHub HTTPS and SSH remote forms into owner/repo (stripping any trailing `.git`), compute the GitHub project Pages `site_url` and the `/<repo>/` base-path and an edit_uri; for a non-GitHub remote keep the remote URL as repo_url with a root base-path and a target-directory-derived site_name; for no remote derive site_name from the target directory with an empty repo_url and a root base-path; apply per-field overrides (site_name, site_url, repo_url, edit_uri) over the derived value; never emit DocuHarnessX's own identity.
  - Observable completion: unit tests assert the GitHub HTTPS and SSH forms yield the same owner/repo with `site_url` ending in `/<repo>/` and base-path `/<repo>/`; the no-remote and non-GitHub fallbacks produce a root base-path and a target-derived name without raising; each override field wins; the reference target `github.com/norandom/malware_hashes` resolves to base-path `/malware_hashes/` and a non-DocuHarnessX identity.
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8_
  - _Boundary: SiteIdentity resolver_
  - _Depends: 1.2_

- [x] 2.2 Implement the isolated, mockable origin-remote read helper
  - Implement a thin helper that performs a read-only origin-remote read for the target repository and returns the remote URL or the absent value, swallowing a missing remote, a missing git executable, and any non-zero/failed invocation so a git-less environment degrades to the no-remote fallback rather than aborting the run.
  - Observable completion: unit tests (with the git invocation stubbed) assert a present remote returns its URL, and an absent remote / failed invocation / missing executable each return the absent value without raising.
  - _Requirements: 3.1, 3.5, 2.5_
  - _Boundary: SiteIdentity resolver_
  - _Depends: 1.2_

- [x] 3. Core: deterministic page and config renderers (no model)
- [x] 3.1 (P) Implement the per-segment Markdown page renderer
  - Implement a stable, deterministic, filesystem-safe page filename derived from the segment id, and a renderer that, for one accepted segment plus the loaded vocabulary and the set of accepted segment ids, produces the page relative path and Markdown content: frontmatter tags equal to the ontology tag-emission output for the segment under the vocabulary, the title as a heading, the body preserved verbatim, and a related-links section built from the segment's related references filtered to ids present in the accepted set; treat the segment read-only.
  - Observable completion: unit tests assert the frontmatter tag set equals the ontology tag output, the body is preserved, related references render as links with dangling ids dropped, and equal inputs yield byte-identical page content.
  - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5_
  - _Boundary: Segment page renderer_
  - _Depends: 1.2_

- [x] 3.2 (P) Implement the per-role landing page renderer with intent-ordered agenda
  - Implement a renderer that, for one role term, an accepted-segment store, the loaded vocabulary, and the list of all emitted role pages, derives the role's segment view through the ontology role-view API (intent-ordered) and renders a landing page: a COBESY SCQA-style opener using the role's display label and description from the loaded vocabulary (never a hardcoded name), the agenda as ordered links to the per-segment pages (no body duplication), and a role-switching affordance (content tabs or admonition) listing the other available role landing pages.
  - Observable completion: unit tests assert the agenda order equals the role-view (intent) order, the opener uses the vocabulary label/description, a renamed/reordered custom vocabulary changes the rendered page with no code change, and the role-switch affordance lists the other roles.
  - _Requirements: 5.2, 5.3, 5.4, 5.6, 6.3_
  - _Boundary: Role landing page renderer_
  - _Depends: 1.2_

- [x] 3.3 (P) Implement the mkdocs.yml builder
  - Implement a pure builder that, from the resolved site identity, the emitted role pages, and the loaded vocabulary, emits the `mkdocs.yml` string: site_name from the identity, the per-target site_url and directory-URL handling so links and assets resolve under the project base-path, repo_url/edit_uri when present, the Material theme, the tags plugin, and a deterministic nav referencing the per-role landing pages (in vocabulary role order) and a tags index.
  - Observable completion: unit tests assert the emitted yaml carries the Material theme and the tags plugin, sets site_url and directory-URL handling to the per-target base-path, and produces a deterministic nav over the emitted role pages plus the tags index.
  - _Requirements: 3.3, 6.1, 6.2, 6.4_
  - _Boundary: mkdocs.yml builder_
  - _Depends: 1.2_

- [x] 4. Core: site writer (orchestration of renderers + byte-stable tree)
- [x] 4.1 Implement the site writer orchestrating the renderers and emitting the tree
  - Implement the writer that, from the review report, the loaded vocabulary, the optional analysis, the output directory, and the resolved identity, builds a fresh in-memory store from the accepted segments, renders one page per accepted segment, renders a landing page only for each vocabulary role that has at least one accepted segment (omitting empty roles), builds a tags index page, builds the mkdocs.yml, writes the whole tree under the run's output directory, and returns the frozen AssembledSite with the correct page and role-page counts; perform no model call and no network access; tolerate an absent analysis.
  - Observable completion: a unit test over a seeded accepted set produces one page per accepted segment, one landing page per role that has content (and none for empty roles), a tags index, and a mkdocs.yml under the output dir, returning an AssembledSite with matching counts; an absent analysis still produces a site; two runs over equal inputs produce byte-identical trees.
  - _Requirements: 4.1, 5.1, 5.5, 7.1, 8.1, 8.2, 8.5_
  - _Boundary: Site writer_
  - _Depends: 2.1, 3.1, 3.2, 3.3_

- [x] 5. Integration: the real Assemble stage adapter (in-place stub replacement)
- [x] 5.1 Replace the assemble stub with the real stage adapter wiring the core
  - Replace the no-op assemble module body in place while keeping the stage-name constant, the stage class name, the factory name, the module path, the no-op re-export, and the export set stable so the stage registry and the bundle need no edits; subclass the shared no-op base and attach to the same pipeline hook.
  - Capture the run state on task start; on step end, when a state is bound, read the review-report, vocabulary, optional analysis, output-directory, and target-repository slots; pin the review-report schema version and raise the fatal assembler input error naming the cause on an unsupported version or a missing review-report, vocabulary, or output-directory slot, producing no site; tolerate an absent analysis; outside a harness, forward the event unchanged and produce nothing.
  - Read the identity overrides (from the config/flags overrides mapping; absent means an empty mapping) and the origin remote via the read helper, resolve the per-target identity, run the site writer, publish the AssembledSite into the assembled-site slot, then yield the lifecycle event unchanged; consume each accepted segment read-only.
  - Observable completion: a credential-free integration run via the bundle over a seeded review report, vocabulary, output dir, and target path publishes a well-formed AssembledSite (correct counts and per-target identity) into the assembled-site slot, with the registry and bundle unedited.
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 7.1_
  - _Boundary: AssembleStage_
  - _Depends: 1.3, 4.1, 2.2_

- [x] 5.2 Add the bounded journal summary on the Assemble stage
  - On completion with a bound state, emit a participation trigger to the run tracer carrying a summary-level detail only: the page count, the role-page count, the resolved site_name, and the base-path; never include page bodies; no-op when no tracer is bound.
  - Observable completion: the integration run records a single bounded participation trigger whose detail carries the counts, the site_name, and the base-path, with no page body present.
  - _Requirements: 1.4_
  - _Boundary: AssembleStage_
  - _Depends: 5.1_

- [x] 6. Validation: credential-free integration, build, determinism, and replaceability tests
- [x] 6.1 Stage integration, input-gating, and append-only seam tests
  - Verify, credential-free through the bundle, that a seeded review report yields one page per accepted segment and one landing page per role with accepted content; that a missing review-report, vocabulary, or output-directory slot and an unsupported review-report version each raise the fatal assembler input error with no site; that an absent analysis still produces a site; and that an out-of-harness direct drive forwards the event unchanged and produces nothing.
  - Verify the assembled-site slot round-trips through the run context, a fresh state returns the absent value, and the existing slot keys, accessors, and exports are unchanged.
  - Observable completion: the integration test suite passes, asserting page/role-page coverage, the four fatal input paths, the absent-analysis path, the out-of-harness pass-through, and the append-only seam round-trip.
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 5.1, 5.5, 7.4, 7.5, 1.3_
  - _Boundary: AssembleStage, types/context additions_
  - _Depends: 5.1, 5.2_

- [x] 6.2 MkDocs build, base-path, determinism, and isolation tests
  - Run a real `mkdocs build` on the emitted tree across the default vocabulary, a custom vocabulary, and varying target remotes (GitHub project, no remote, non-GitHub), asserting the build succeeds with the per-target base-path and no broken internal links among the generated pages.
  - Verify two assembly runs over equal inputs produce byte-identical trees, that the only write target is the run's output directory, and that a target run never derives DocuHarnessX's own identity or Pages URL.
  - Observable completion: the build test passes for every (vocabulary, remote) combination; the determinism test confirms byte-identical trees; the isolation test confirms the single output-dir write target and a non-DocuHarnessX identity.
  - _Requirements: 8.2, 8.4, 8.5, 3.2, 3.5, 3.6, 3.8, 5.6_
  - _Boundary: assembler package, AssembleStage_
  - _Depends: 6.1_

- [x] 6.3 Stable replaceability and reproducibility tests
  - Verify the stage-name constant, class name, factory name, no-op re-export, export set, and module path are unchanged and that the stage registry and bundle composition need no edits.
  - Verify that two assemble runs over an equal review report and equal target identity produce an equal AssembledSite (equal identity, paths relative layout, counts) and equal site bytes.
  - Observable completion: the replaceability test confirms the unchanged public surface and that the registry/bundle are unedited; the reproducibility test confirms two equal-input runs yield an equal AssembledSite and equal bytes.
  - _Requirements: 1.1, 1.2, 8.2_
  - _Boundary: AssembleStage_
  - _Depends: 6.2_
