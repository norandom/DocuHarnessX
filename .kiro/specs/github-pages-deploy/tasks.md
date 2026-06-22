# Implementation Plan

- [x] 1. Foundation: deploy data model, errors, and append-only seam
- [x] 1.1 Define the frozen DeployResult value object, deploy-mode/status literals, version authority, and error family
  - Add a deterministic, harness-free deploy core package; in its model module define the frozen `DeployResult` carrying the deploy mode, status, target Pages URL, written paths, built path, and a one-line detail, plus the supported deploy-mode and status literals and a single schema-version authority
  - Define the deploy error family (a base error and an input-error subclass) independent of the other specs' error families
  - Observable completion: constructing a `DeployResult` yields an immutable value whose schema-version field equals the module's version constant and that compares by value; the deploy-mode literal admits exactly the three modes
  - _Requirements: 8.1, 8.3, 2.3_
  - _Boundary: DeployResult model_

- [x] 1.2 Add the append-only DeployResult slot key and run-context accessors
  - Append the deploy-result slot key constant to the shared types module and its `__all__`, modifying no existing slot key, stage name, or stage-name tuple entry
  - Append a typed setter/getter accessor pair to the run context, with a typing-only import of the result type and a slot-type tag; an unset slot returns an explicit absent value
  - Observable completion: setting then getting the deploy result round-trips the same value, a fresh run context returns the absent value, and the existing slots/accessors/exports are unchanged
  - _Requirements: 8.4_
  - _Boundary: types/context additions_
  - _Depends: 1.1_

- [x] 1.3 Declare the mkdocs runtime dependencies
  - Add `mkdocs` and `mkdocs-material` to the project runtime dependencies (declared once, idempotent with any prior declaration)
  - Observable completion: a fresh environment install resolves `mkdocs` and `mkdocs-material`, and the `mkdocs` CLI is invocable
  - _Requirements: 9.3_

- [x] 2. Core: deterministic deploy components
- [x] 2.1 (P) Implement the deploy-mode resolver
  - Resolve a configured mode value to a supported deploy mode: absent/empty defaults to emit-ci-workflow; a recognised value passes through; any other value raises the deploy input error naming the bad value and the three valid modes
  - Observable completion: the resolver returns emit-ci-workflow for an absent value, returns each valid mode unchanged, and raises the input error for an unknown value
  - _Requirements: 3.1, 3.2, 3.3, 3.4_
  - _Boundary: Deploy-mode resolver_

- [x] 2.2 (P) Implement the GitHub Actions Pages workflow renderer
  - Render a byte-stable GitHub Actions workflow that triggers on push to the target's default branch, installs mkdocs + mkdocs-material, runs the site build, and deploys the built site to GitHub Pages with the minimal Pages deployment permissions
  - Take the per-target identity and the default branch as inputs so the workflow never re-parses the remote and never carries DocuHarnessX's identity
  - Observable completion: for a given identity and branch the rendered workflow contains the push trigger on that branch, a build step, and a Pages deploy job with the write/id-token permissions, and is identical across repeated renders
  - _Requirements: 4.2, 4.3, 4.4_
  - _Boundary: Workflow renderer_

- [x] 2.3 (P) Implement the target-tree writer
  - Copy the assembled site config and docs tree into the target repository's working tree and write the rendered workflow into the target's workflows directory, returning the written paths in deterministic order
  - Write only under the passed target repository path; never push, commit, or invoke any git write command
  - Observable completion: after a write the three artifacts (site config, docs tree, workflow file) exist under the target path and nowhere else, the returned paths name them, and no git history is modified
  - _Requirements: 4.1, 4.5, 4.6, 9.1_
  - _Boundary: Target-tree writer_

- [x] 2.4 (P) Implement the isolated command runner: git branch read, build validation, and gh-deploy
  - Provide a command-runner abstraction with a default subprocess implementation and a substitutable seam for tests; read the target's default branch with a safe fallback when git is unavailable; run the site build as validation against the assembled config (carrying the per-target base-path) and raise the deploy error on non-zero exit or missing tooling; run the gh-deploy push as the only network action, raising the deploy error naming the missing prerequisite when the remote or tooling is unavailable
  - Observable completion: with an injected fake runner, the default-branch read falls back when git fails, the build raises the deploy error on a simulated non-zero exit, and the gh-deploy entry point is callable but performs no real network call under the fake runner
  - _Requirements: 4.3, 5.1, 5.3, 7.1, 7.2, 7.3, 7.4_
  - _Boundary: Command runner_

- [x] 3. Core: the deploy orchestrator
- [x] 3.1 Implement the per-mode deploy orchestrator returning a DeployResult
  - Orchestrate the selected mode end to end using the components from task 2: emit-ci-workflow reads the default branch, renders the workflow, writes the target tree, then runs build validation; build-only runs build validation only and writes nothing into the target tree and pushes nothing; gh-deploy runs the network push only
  - Build validation runs for the emit-ci-workflow and build-only modes before success is declared; a failed build or push never declares success and surfaces the deploy error cause; derive every per-target parameter from the consumed site identity and the target path, never from a hardcoded DocuHarnessX value; perform no model call
  - Observable completion: each mode returns a `DeployResult` with the matching mode/status (emitted, built, published) and the per-target Pages URL; emit-ci-workflow lists the three written paths and a built path; build-only lists no written paths; gh-deploy invokes the (injected) push exactly once and is never invoked on the other modes
  - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 5.1, 5.2, 5.4, 6.1, 6.2, 7.1, 7.2, 7.3, 7.4, 8.1, 9.1, 9.2, 9.4_
  - _Boundary: Deploy orchestrator_
  - _Depends: 2.1, 2.2, 2.3, 2.4_

- [x] 4. Integration: the real Deploy stage and CLI mode wiring
- [x] 4.1 Replace the Deploy stage stub in place with the real adapter
  - Replace the no-op body with the real stage while preserving the stage name, class name, factory name, no-op re-export, exports, and module path so the stage registry and bundle need no edits; subclass the shared no-op base and attach to the same pipeline hook
  - Capture the run state at task start; on the content-free step event read the assembled-site, output-directory, and target-repository slots and the configured deploy mode, pin the assembled-site schema version, resolve and run the deploy, publish the result to the new slot, and yield the event unchanged; outside a harness with no bound state, forward the event and perform no deploy
  - Raise the deploy input error (no deploy action) when a required slot is unset, the assembled-site version is unsupported, or the configured mode is invalid; inject the command runner through a substitutable per-instance accessor so tests use a fake runner
  - Observable completion: a credential-free bundle run over a seeded assembled site in the default mode writes the three target-tree files, runs the (mocked) build, and publishes a well-formed deploy result into the new slot, with the registry and bundle unedited
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 2.1, 2.2, 2.3, 2.4, 2.5, 8.1_
  - _Boundary: DeployStage_
  - _Depends: 1.2, 3.1_

- [x] 4.2 Record a bounded DeployResult summary in the run journal
  - On completion with a bound run state, emit a bounded participation summary to the run tracer carrying the mode, status, target Pages URL, written-path count, and built flag, reusing the no-op base tracer resolution and writing no page bodies; no-op when no tracer is bound
  - Observable completion: a journaled run records one deploy participation entry whose detail carries the mode/status/Pages-URL/counts and no page bodies
  - _Requirements: 8.2_
  - _Boundary: DeployStage_
  - _Depends: 4.1_

- [x] 4.3 Add the deploy-mode config field and CLI flag and thread it into the run
  - Append a deploy-mode field (defaulting to emit-ci-workflow) to the run configuration, populated from the config file and a new run-subcommand flag; thread the resolved mode through the run orchestration so the Deploy stage reads it, leaving all existing run/init/bare-form behaviour unchanged
  - Observable completion: a run with the new flag set to a mode reaches the stage with that mode; a run with no flag reaches the stage with the emit-ci-workflow default; existing CLI behaviour is unchanged
  - _Requirements: 3.2, 3.3_
  - _Boundary: config/cli additions_
  - _Depends: 4.1_

- [x] 5. Validation: unit, integration, and build coverage
- [x] 5.1 (P) Unit-test the deterministic deploy components
  - Cover the mode resolver default/passthrough/reject paths; the workflow renderer's branch trigger, build step, Pages deploy permissions, byte-stability, and absence of DocuHarnessX identity; the tree writer's target-only writes and no-git-push behaviour including the reference target resolving to its own project subpath; the command runner's branch fallback, build-failure error, and that the fake runner is never asked to push on the validated modes
  - Observable completion: the component unit suite passes and asserts each referenced acceptance behaviour without spawning a real git or mkdocs process
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 5.3, 5.4, 7.2, 7.3, 7.4, 9.1, 9.2_
  - _Boundary: Deploy-mode resolver, Workflow renderer, Target-tree writer, Command runner_
  - _Depends: 2.1, 2.2, 2.3, 2.4_

- [x] 5.2 Integration-test the stage across modes and fatal-input paths
  - With a seeded assembled site and a fake command runner: assert the default mode publishes an emitted result with the three target-tree files; build-only writes nothing into the target tree and yields a built result; gh-deploy invokes the mocked push exactly once and yields a published result without any real network call; assert the fatal-input paths (missing assembled-site/output-dir/target-repo slot, unsupported assembled-site version, unsupported mode) each raise the deploy input error with no deploy, and that an out-of-harness drive forwards the event and does nothing; assert the slot round-trips and existing seams are unchanged
  - Observable completion: the stage integration suite passes, covering all three modes, every fatal-input path, the out-of-harness pass-through, and the append-only seam round-trip
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 2.1, 2.2, 2.3, 2.4, 2.5, 5.1, 5.2, 5.4, 6.1, 6.2, 8.1, 8.2, 8.4_
  - _Boundary: DeployStage_
  - _Depends: 4.1, 4.2, 4.3_

- [x] 5.3 Build-validate a real assembled tree under the per-target base-path
  - Run the real site build (no network) on an assembled tree and assert the static site is produced under the per-target project subpath, that the emit-ci-workflow files are present in the target tree, and that across all three modes the only writes are under the run output dir or the resolved target repo with the Pages URL always the per-target value and never DocuHarnessX's; the gh-deploy push is not exercised
  - Observable completion: the build/E2E test passes — the build succeeds under the per-target base-path, isolation holds across modes, and no gh-deploy network push runs
  - _Requirements: 7.1, 7.2, 9.1, 9.2, 9.3, 9.4_
  - _Boundary: Deploy orchestrator, DeployStage_
  - _Depends: 5.2_
