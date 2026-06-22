# Requirements Document

## Introduction

The Deploy stage is the finale of the DocuHarnessX pipeline (Ingest → Analyze → Classify → Plan → Write → Review → Assemble → Deploy): it takes the assembled Material for MkDocs site source tree and **publishes it to the target project's GitHub Pages**. The pipeline currently ships `deploy` as a no-op stub; the upstream `mkdocs-site-assembler` produces a frozen `AssembledSite` (the site source directory, `mkdocs.yml`, and the per-target site identity including the `/<repo>/` Pages base-path) on `SLOT_ASSEMBLED_SITE`, but nothing yet gets it published.

This feature replaces that stub **in place** with the real Deploy stage. It consumes the `AssembledSite` (verbatim, read-only) and runs one of three configurable deploy modes against the **target project** — never DocuHarnessX's own repository:

- **emit-ci-workflow (DEFAULT):** write `mkdocs.yml` + `docs/` + a `.github/workflows/docs.yml` (a build-and-deploy-pages GitHub Actions workflow) **into the target repository's working tree**, so the target self-publishes Pages on push. DocuHarnessX writes files for the operator to review and commit — **no auto-push**.
- **gh-deploy:** run `mkdocs gh-deploy` to push the built site to the target repository's `gh-pages` branch (requires the target's remote and push access at run time).
- **build-only:** run `mkdocs build` to produce the static site in the output directory; no publish.

Because DocuHarnessX documents **arbitrary target projects**, the deploy target — `owner/repo`, the remote URL, the default branch, the Pages URL, and the `/<repo>/` base-path — is derived **per-target**. The Deploy stage consumes the already-resolved `AssembledSite.identity` (which the assembler derived from the target git remote) so it does **not** re-parse the remote; it reads the target default branch from the target git repository at run time for the emitted workflow / `gh-deploy`. Per-project isolation is mandatory: one run publishes exactly one target, and the Deploy stage never deploys to DocuHarnessX's own repository or Pages.

`mkdocs build` is run as **build validation** — confirming the assembled site builds cleanly under the per-target base-path before the stage declares success. The `mkdocs gh-deploy` push is the **only** network action and is **never exercised in tests**; emit-ci-workflow and build-only are credential-free and fully unit-testable (assert the emitted files / workflow content and that `mkdocs build` succeeds). The stage publishes its result as a new `DeployResult` value object recorded in the run journal (and optionally a run-context slot), giving an auditable record of mode, written/built paths, target Pages URL, and status.

## Boundary Context

- **In scope**: Replacing the `deploy` stub in place; consuming the frozen `AssembledSite` (`SLOT_ASSEMBLED_SITE`) verbatim; the three configurable deploy modes (emit-ci-workflow default, gh-deploy, build-only); reading the deploy mode and overrides from `.docuharnessx/` config or `dhx` flags; deriving the target default branch from the target git repository for the emitted workflow / `gh-deploy`; running `mkdocs build` as build validation under the per-target base-path; emitting `mkdocs.yml` + `docs/` + `.github/workflows/docs.yml` into the target working tree for the default mode (no auto-push); running `mkdocs gh-deploy` for the gh-deploy mode; owning the `DeployResult` value object and recording it in the journal; declaring `mkdocs` + `mkdocs-material` as runtime dependencies.
- **Out of scope**: Assembling the site — the `docs/*.md` pages, per-role landing pages, tags index, `mkdocs.yml` content, and per-target `SiteIdentity` resolution are all owned by `mkdocs-site-assembler` and consumed read-only here; repo scanning / classification / planning / writing / reviewing (upstream waves); the `ReviewReport`, `Vocabulary`, `RepoAnalysis`, `Segment`, and ontology APIs (consumed/reused read-only only where needed, never redefined); the stage registry (`STAGES`), `make_docgen`, and every sibling stage module (untouched); `mike` doc-versioning (a future enhancement, not this spec).
- **Adjacent expectations**: The `AssembledSite` and its nested `SiteIdentity` are read-only and carry the per-target identity the assembler already resolved (`site_url`, `base_path` = `/<repo>/`, `repo_url`, `repo_name`, `edit_uri`, `site_name`). The Deploy stage reads run data exclusively through the existing `RunContext` slots (`SLOT_ASSEMBLED_SITE`, output dir, target repo) and replaces exactly one stub, leaving the stage registry, the bundle, and every sibling stage untouched. A change to the `AssembledSite` / `SiteIdentity` frozen field set or a bump of `ASSEMBLED_SITE_SCHEMA_VERSION` is a revalidation trigger for this spec.

## Requirements

### Requirement 1: In-place replacement of the Deploy stage stub

**Objective:** As a pipeline maintainer, I want the real Deploy stage to drop into exactly the slot the no-op stub occupied, so that the stage registry and the `make_docgen` bundle need no edits and a single-stage swap is preserved.

#### Acceptance Criteria
1. The Deploy Stage shall preserve the stable stage identity — the `STAGE_NAME` value `"deploy"`, the `DeployStage` class name, the `make_deploy_stage` factory name, the `make_noop_stage` re-export, and the module path `docuharnessx.stages.deploy` — unchanged from the stub it replaces.
2. The Deploy Stage shall subclass the shared no-op stage base and attach to the same pipeline hook so the stage registry and the bundle composition require no edits.
3. While the stage is driven outside a harness with no bound run state, the Deploy Stage shall forward the lifecycle event unchanged and perform no deploy action, exactly as the no-op base does.
4. When the stage runs as a side effect of the content-free lifecycle event, the Deploy Stage shall yield that event unchanged and modify no generated conversation content, recording its result only in the run journal and the run-context slot.

### Requirement 2: Consuming the assembled site and run inputs

**Objective:** As the Deploy stage, I want to read the assembled site and run inputs from the run context, so that I publish exactly the site the assembler produced for this one target.

#### Acceptance Criteria
1. While a run state is bound, the Deploy Stage shall read the `AssembledSite` from the assembled-site slot, the resolved output directory, and the target-repository path through the typed run-context accessors.
2. The Deploy Stage shall consume the `AssembledSite` — its site source directory, `docs/` directory, `mkdocs.yml` path, and resolved `SiteIdentity` — verbatim and read-only, never re-deriving the site layout or re-parsing the target git remote.
3. If the assembled-site slot is unset while a run state is bound, then the Deploy Stage shall raise a typed deploy input error naming the missing slot and perform no deploy action.
4. If the consumed `AssembledSite` declares a schema version this build does not support, then the Deploy Stage shall raise a typed deploy input error naming the unsupported version and perform no deploy action.
5. If the output directory or the target-repository path is unset while a run state is bound, then the Deploy Stage shall raise a typed deploy input error and perform no deploy action.

### Requirement 3: Selecting the deploy mode

**Objective:** As an operator, I want to choose how my docs are published — emit a CI workflow, push with gh-deploy, or just build — so that the same generator fits projects with different publishing setups.

#### Acceptance Criteria
1. The Deploy Stage shall support three deploy modes: `emit-ci-workflow`, `gh-deploy`, and `build-only`.
2. Where no deploy mode is configured, the Deploy Stage shall default to the `emit-ci-workflow` mode.
3. Where a deploy mode is provided through `.docuharnessx/` configuration or a `dhx` flag, the Deploy Stage shall use the configured mode in place of the default.
4. If the configured deploy mode is not one of the three supported modes, then the Deploy Stage shall raise a typed deploy input error naming the unsupported mode and the valid modes, and perform no deploy action.

### Requirement 4: emit-ci-workflow mode — write self-publishing files into the target tree

**Objective:** As an operator documenting an arbitrary target, I want DocuHarnessX to write a GitHub Actions workflow and the site source into my target repository, so that my project self-publishes Pages on push without giving DocuHarnessX push access.

#### Acceptance Criteria
1. While the deploy mode is `emit-ci-workflow`, the Deploy Stage shall write the assembled `mkdocs.yml` and the `docs/` tree into the target repository's working tree.
2. While the deploy mode is `emit-ci-workflow`, the Deploy Stage shall write a `.github/workflows/docs.yml` GitHub Actions workflow into the target repository's working tree that builds the MkDocs site and deploys it to GitHub Pages.
3. The Deploy Stage shall populate the emitted workflow with the target's default branch as the trigger branch, deriving the branch from the target git repository.
4. The Deploy Stage shall thread the per-target identity carried on `AssembledSite.identity` — the `site_url`, the `/<repo>/` base-path, the `repo_url`, and the `edit_uri` — into the emitted site configuration so the published Pages site resolves under the target's project subpath, without re-parsing the target git remote.
5. While the deploy mode is `emit-ci-workflow`, the Deploy Stage shall not push to any remote and shall not commit to the target repository, leaving the written files staged in the working tree for the operator to review and commit.
6. The Deploy Stage shall write the emit-ci-workflow files only into the resolved target repository for this one run, never into DocuHarnessX's own repository.

### Requirement 5: gh-deploy mode — push the built site to the target gh-pages branch

**Objective:** As an operator with push access, I want a one-shot publish that pushes the built site to my target's `gh-pages` branch, so that the docs go live immediately.

#### Acceptance Criteria
1. While the deploy mode is `gh-deploy`, the Deploy Stage shall run `mkdocs gh-deploy` against the assembled site so the built site is pushed to the target repository's `gh-pages` branch.
2. The Deploy Stage shall direct the `gh-deploy` push at the target repository derived from `AssembledSite.identity`, never at DocuHarnessX's own repository.
3. If the `gh-deploy` prerequisites are missing — no target git remote, or `mkdocs gh-deploy` is not runnable — then the Deploy Stage shall report a typed, explicit failure naming the missing prerequisite and shall not silently succeed.
4. While running in a test or credential-free environment, the Deploy Stage's `gh-deploy` push shall not be exercised; the push is the only network action and is invoked only on the real `gh-deploy` path.

### Requirement 6: build-only mode — produce the static site without publishing

**Objective:** As an operator, I want a no-publish build that just produces the static site, so that I can inspect or host the output myself.

#### Acceptance Criteria
1. While the deploy mode is `build-only`, the Deploy Stage shall run `mkdocs build` on the assembled site to produce the static site under the output directory and shall perform no publish action.
2. While the deploy mode is `build-only`, the Deploy Stage shall not write any file into the target repository's working tree and shall not push to any remote.

### Requirement 7: Build validation with the per-target base-path

**Objective:** As a maintainer, I want the assembled site proven to build under the target's Pages base-path before success is declared, so that a broken site is never reported as deployed.

#### Acceptance Criteria
1. While the deploy mode is `emit-ci-workflow` or `build-only`, the Deploy Stage shall run `mkdocs build` on the assembled site as build validation before declaring the deploy successful.
2. The Deploy Stage shall run the build validation against the per-target `site_url` and `/<repo>/` base-path carried on `AssembledSite.identity`, so the produced static site resolves links and assets under the target's Pages subpath.
3. If the build validation fails — `mkdocs build` exits non-zero or the build tooling is unavailable — then the Deploy Stage shall report a typed, explicit failure and shall not declare the deploy successful.
4. The Deploy Stage shall not perform a network action during build validation; only the `gh-deploy` push performs network access.

### Requirement 8: The DeployResult output seam

**Objective:** As a maintainer auditing a run, I want a structured `DeployResult` recorded for every deploy, so that the run journal shows what was published where and whether it succeeded.

#### Acceptance Criteria
1. When the deploy completes, the Deploy Stage shall produce a frozen `DeployResult` value object carrying the deploy mode, the written and built paths, the target Pages URL, and the deploy status.
2. The Deploy Stage shall record the `DeployResult` in the run journal as a bounded participation summary, without writing full page bodies to the trace.
3. The `DeployResult` value object shall carry a single schema-version field, and a change to its frozen field set shall be a revalidation trigger for any downstream consumer.
4. Where the Deploy Stage publishes the `DeployResult` into a run-context slot, the slot key and its run-context accessor shall be append-only additions, modifying no existing slot key, stage name, stage-name tuple entry, or existing run-context accessor, and a read through the accessor while the slot is unset shall return an explicit absent value rather than raising.

### Requirement 9: Per-project isolation and dependencies

**Objective:** As a maintainer, I want every deploy scoped to exactly one target and never to DocuHarnessX's own repo, so that the generator is safely reusable across arbitrary target projects.

#### Acceptance Criteria
1. The Deploy Stage shall act on exactly one target per run — the target derived from the run's `AssembledSite` and target-repository path — and shall never deploy to, write into, or push to DocuHarnessX's own repository or Pages.
2. The Deploy Stage shall derive every per-target deploy parameter (target repository path, Pages URL, base-path, remote URL, default branch) from the run inputs for that target, never from a hardcoded DocuHarnessX value.
3. The project shall declare `mkdocs` and `mkdocs-material` as runtime dependencies.
4. The Deploy Stage shall perform no model call; the deploy is a deterministic, mechanical transform over the assembled site and the run inputs, except for the single `mkdocs gh-deploy` network push on the gh-deploy path.
