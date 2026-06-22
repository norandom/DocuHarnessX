# Research & Design Decisions — github-pages-deploy

## Summary
- **Feature**: `github-pages-deploy`
- **Discovery Scope**: Extension (in-place replacement of an existing pipeline-stage stub, consuming a frozen upstream seam)
- **Key Findings**:
  - The merged foundation (Waves 0-2) already provides the exact extension pattern this stage must follow: in-place stub replacement (`ReviewStage` as the closest precedent), append-only seam extension on `types.py` + `RunContext`, and a pure harness-free core package paired with a thin `step_end` adapter.
  - The upstream `mkdocs-site-assembler` spec (Wave 3, spec #1) owns and freezes `AssembledSite` + nested `SiteIdentity` on `SLOT_ASSEMBLED_SITE`; this stage consumes them verbatim — including the already-resolved per-target `site_url` and `/<repo>/` `base_path` — so it never re-parses the target git remote.
  - The only network action is the `mkdocs gh-deploy` push; emit-ci-workflow and build-only are credential-free and unit-testable, so all process calls (git branch read, `mkdocs build`, `gh-deploy`) must be isolated behind one mockable command runner.

## Research Log

### Consumed seam — AssembledSite / SiteIdentity (mkdocs-site-assembler)
- **Context**: This stage's entire input is the assembler's output; the contract must be consumed verbatim, not re-derived.
- **Sources Consulted**: `.kiro/specs/mkdocs-site-assembler/design.md` (frozen `AssembledSite`/`SiteIdentity` definition, `ASSEMBLED_SITE_SCHEMA_VERSION=1`, the emitted filesystem contract, revalidation triggers) and `requirements.md` (Req 3 per-target identity, Req 7 the `AssembledSite` seam).
- **Findings**:
  - `AssembledSite{schema_version, site_dir, docs_dir, mkdocs_yml_path, identity, page_count, role_page_count}`; `SiteIdentity{site_name, repo_name, repo_url, site_url, base_path, edit_uri}`.
  - The assembler already computes `site_url = https://<owner>.github.io/<repo>/` and `base_path = /<repo>/` for GitHub project Pages, root base-path for non-GitHub/no-remote, and writes them into the emitted `mkdocs.yml` (`use_directory_urls: true`).
  - The assembler's emitted `mkdocs.yml` lives at `<out>/site/mkdocs.yml` with `docs/` beside it.
- **Implications**: The deploy stage reads `assembled_site()` from the run context, pins `ASSEMBLED_SITE_SCHEMA_VERSION`, and uses `identity.site_url`/`identity.base_path` directly. For emit mode it copies the assembled `mkdocs.yml` + `docs/` into the target tree (they already carry the per-target base-path) and writes a workflow; for build/gh-deploy it runs `mkdocs` against the assembled `mkdocs.yml`. No remote re-parsing.

### Stage-replacement + append-only seam pattern (foundation)
- **Context**: The stage must drop into the stub slot with no registry/bundle edits and extend the seam modules append-only.
- **Sources Consulted**: `docuharnessx/stages/deploy.py` (current stub: `STAGE_NAME="deploy"`, `DeployStage(NoOpStage)`, `make_deploy_stage`, `make_noop_stage`, `__all__`), `docuharnessx/stages/review.py` (the closest real precedent — `on_task_start` state capture, `on_step_end` slot read + work + bounded journal, `_resolve_run_context`/`_read_inputs`/`_journal_participation`, model accessor overridable for tests), `docuharnessx/stages/base.py` (`NoOpStage`, `PIPELINE_HOOK="step_end"`, tracer resolution), `docuharnessx/types.py` + `docuharnessx/context.py` (seven prior append-only seam extensions), `docuharnessx/cli.py` (`orchestrate_run` provisions target_repo/output_dir/vocabulary/segment_store).
- **Findings**:
  - The stub already subclasses `NoOpStage` and serializes to a real module-level `_target_`, so replacing only the body keeps the registry/bundle untouched.
  - `ReviewStage` injects its model via a named per-instance accessor (`_judge_model`) that tests override; the same seam lets this stage inject a fake `CommandRunner` so no real subprocess/network runs in tests.
  - `orchestrate_run` is where any new run input (the `deploy_mode`) must be threaded; it already binds `DocgenConfig` and sets the slots before the run.
- **Implications**: Mirror `ReviewStage` structure exactly; add `SLOT_DEPLOY_RESULT` + `set_deploy_result`/`deploy_result` append-only; add a `deploy_mode` config field + `--deploy-mode` flag threaded through `orchestrate_run`.

### GitHub Pages publishing modes
- **Context**: The locked requirement is a multi-mode deploy defaulting to emitting a self-publishing GitHub Actions workflow into the target tree.
- **Sources Consulted**: `brief.md` (the three modes + no-auto-push default), steering `tech.md` (`mkdocs gh-deploy` / GitHub Actions; `mike` future), the GitHub Pages Actions deployment model (`actions/upload-pages-artifact` + `actions/deploy-pages`, `pages: write` + `id-token: write` permissions).
- **Findings**:
  - Default emit-ci-workflow: write `mkdocs.yml` + `docs/` + `.github/workflows/docs.yml` into the target tree; the target's own Actions publishes Pages on push; DocuHarnessX never needs the target's credentials.
  - gh-deploy: `mkdocs gh-deploy` builds + force-pushes to `gh-pages` (needs remote + push access) — the only network action.
  - build-only: `mkdocs build` to a static dir, no publish.
- **Implications**: A `DeployMode` literal + a pure resolver (default + validate); a workflow renderer; a target-tree writer (no push); a command runner for `mkdocs build` (validation) and `gh-deploy` (push). `mike` is explicitly out of scope.

## Architecture Pattern Evaluation

| Option | Description | Strengths | Risks / Limitations | Notes |
|--------|-------------|-----------|---------------------|-------|
| Pure core + thin stage adapter (chosen) | Deterministic `deployer/` package + a `step_end` `DeployStage` adapter; process calls behind one mockable runner | Matches `review/`+`assembler/`; credential-free testable; single-stage swap | Requires disciplined runner isolation so `gh-deploy` is never reached in tests | Selected — consistent with the whole codebase |
| Stage does the work inline | Put all file/subprocess logic directly in `DeployStage` | Fewer files | Couples deterministic logic to the harness; hard to unit-test; breaks the established pure-core pattern | Rejected |
| Import mkdocs as a library | Call mkdocs Python API instead of the CLI | No subprocess | mkdocs CLI is the supported, stable surface; `gh-deploy` is CLI-centric; harder to mock cleanly | Rejected — subprocess via a mockable runner is simpler and matches `gh-deploy` reality |

## Design Decisions

### Decision: Consume AssembledSite verbatim; never re-resolve identity
- **Context**: Both the assembler and this stage need the per-target identity; duplicating remote-parsing would risk drift.
- **Alternatives Considered**:
  1. Re-parse the target git remote in the deploy stage.
  2. Consume `AssembledSite.identity` (chosen).
- **Selected Approach**: Read `identity.{site_url, base_path, repo_url, repo_name, edit_uri, site_name}` from the consumed seam; pin `ASSEMBLED_SITE_SCHEMA_VERSION`.
- **Rationale**: Single source of truth; the assembler is the declared owner; the assembler's revalidation trigger already names this stage.
- **Trade-offs**: A field-set/version change upstream forces a re-check here (acceptable, explicitly tracked).
- **Follow-up**: Pin the version in the stage; halt loudly on mismatch.

### Decision: Isolate all process calls behind one mockable CommandRunner
- **Context**: `git` branch read, `mkdocs build`, and `mkdocs gh-deploy` are the only impure surfaces; the push is network and must never run in tests.
- **Selected Approach**: A `CommandRunner` protocol + `DefaultCommandRunner`, injected into the stage via a named per-instance accessor (mirrors `ReviewStage._judge_model`).
- **Rationale**: Makes emit/build paths deterministic and credential-free; guarantees the `gh-deploy` push is only reachable on the explicit mode and is mocked in tests.
- **Trade-offs**: One extra indirection; worth it for testability and the locked credential-free constraint.
- **Follow-up**: Assert in tests that the fake runner is never asked to push on the validated modes.

### Decision: deploy_mode via append-only config field + CLI flag
- **Context**: Mode must be configurable via `.docuharnessx/` config or a `dhx` flag, defaulting to emit-ci-workflow.
- **Selected Approach**: Append a `deploy_mode` field to `DocgenConfig` (default `"emit-ci-workflow"`), add `--deploy-mode`, thread it through `orchestrate_run` to the stage; validate at the stage via `resolve_deploy_mode`.
- **Rationale**: Reuses the existing config/CLI surface; append-only; safe default for the bare `dhx <repo>` form.
- **Trade-offs**: Touches `config.py`/`cli.py`, but additively only.
- **Follow-up**: Bad mode surfaces as `DeployInputError` at the stage, consistent with the other input gates.

## Risks & Mitigations
- **Risk**: The `gh-deploy` network push leaks into a test path — Mitigation: it is reachable only through the injected runner on the explicit gh-deploy mode; tests inject a fake runner and assert no push on other modes.
- **Risk**: Writing outside the target tree / into DocuHarnessX's own repo — Mitigation: the tree writer writes only under the passed `target_repo`; the orchestrator derives every path from `AssembledSite.identity` + `target_repo`; isolation is asserted.
- **Risk**: Upstream `AssembledSite` field-set/version drift — Mitigation: pin `ASSEMBLED_SITE_SCHEMA_VERSION`, halt loudly on mismatch; the assembler already lists this stage as a revalidation trigger.
- **Risk**: `mkdocs build` failing silently and a broken site reported as deployed — Mitigation: build validation raises `DeployError` on non-zero exit / missing tooling; success is declared only after the build passes (validated modes).

## References
- `.kiro/specs/mkdocs-site-assembler/design.md` — the consumed `AssembledSite`/`SiteIdentity` seam, `ASSEMBLED_SITE_SCHEMA_VERSION`, emitted filesystem contract, revalidation triggers.
- `docuharnessx/stages/review.py` — the in-place real-stage adapter precedent (state capture, slot read, bounded journal, injectable model/runner accessor).
- `docuharnessx/stages/base.py`, `docuharnessx/types.py`, `docuharnessx/context.py` — the stage base + append-only seam-extension pattern.
- `docuharnessx/cli.py` (`orchestrate_run`) — where the `deploy_mode` is threaded and the run-context slots are provisioned.
- GitHub Pages Actions deployment (`actions/upload-pages-artifact`, `actions/deploy-pages`, `pages: write` / `id-token: write`).
