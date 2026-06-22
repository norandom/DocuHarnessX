# Implementation Plan

- [x] 1. Test scaffolding: reusable credential-free fakes
- [x] 1.1 Add the content-routing fake model provider to the test fakes
  - In `tests/_fakes.py` (append-only), add `RoutingFakeProvider` subclassing the existing `FakeProvider`: classify each `complete` call as a review prompt when the joined message text carries COBESY criterion names / criteria phrasing (key on `docuharnessx.review.COBESY_CRITERIA`), else a writer prompt; return a passing per-criterion JSON verdict (every criterion scored at or above threshold, overall pass, in the shape the verdict parser accepts) for review prompts and a `{body, summary}` non-trivial Markdown payload for writer prompts; always end the turn (`finish_reason="end_turn"`); perform no network/credential access; add it to `__all__`
  - Observable completion: a unit-level check shows a review-shaped prompt yields a verdict the deterministic parser accepts as pass, a writer-shaped prompt yields a non-empty `{body, summary}`, the existing `FakeProvider`/`ReplacementStage` exports are unchanged, and the new class is exported
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5_
  - _Boundary: tests/_fakes.py (RoutingFakeProvider)_

- [x] 1.2 (P) Add the python-m-mkdocs no-push build runner to the test fakes
  - In `tests/_fakes.py` (append-only), add `PyMkdocsNoPushRunner` subclassing `docuharnessx.deployer.commands.DefaultCommandRunner`: record every argv; raise (setting a `pushed` flag) if ever asked to run `mkdocs gh-deploy`; rewrite a leading `mkdocs` token to `[sys.executable, "-m", "mkdocs", ...]` before delegating to the real runner; delegate other commands (git reads) unchanged; expose `build_count()` and `pushed`; add it to `__all__`
  - Observable completion: a unit-level check shows a `mkdocs build` argv is rewritten to the interpreter form, a `mkdocs gh-deploy` argv raises and sets `pushed`, and `build_count()` counts builds
  - _Requirements: 7.1, 7.3_
  - _Boundary: tests/_fakes.py (PyMkdocsNoPushRunner)_
  - _Depends: 1.1_

- [x] 2. Fixtures and the full-pipeline driver
- [x] 2.1 Build the crafted multi-language fixtures (Go, Python, JS)
  - In `tests/test_e2e_multi_project.py`, add builders that create, under a temp dir, a Go fixture (go.mod + a `main.go` with enough source LOC to dominate, small README, optional small CI file), a Python fixture (pyproject/setup + a package module with enough source LOC, README), and a JS/Node fixture (package.json + a `.js`/index module with enough source LOC, README); each builder runs `git init` and `git remote add origin https://github.com/<distinct-owner>/<distinct-repo>.git` so a GitHub `/<repo>/` identity resolves; distinct owners/repos per fixture
  - Observable completion: each builder returns a fixture path whose scan-detectable primary language is the intended ecosystem language (Go/Python/JavaScript) and whose resolved `origin` remote yields a GitHub `owner/repo`
  - _Requirements: 1.1, 1.5_
  - _Boundary: tests/test_e2e_multi_project.py (fixture builders)_

- [x] 2.2 Implement the programmatic full-pipeline driver with runner injection
  - In `tests/test_e2e_multi_project.py`, add a `run_fixture(fixture_dir, *, deploy_mode, out_dir, target_tree=None)` helper that builds the run namespace via `cli.build_parser`, calls `cli.prepare_run(args, model_config=ModelConfig(main=RoutingFakeProvider()))`, injects a `PyMkdocsNoPushRunner` onto every live `DeployStage` on the prepared harness's processor table (the same walk `cli._thread_deploy_mode` uses), then calls `cli.orchestrate_run(prepared, max_steps=N)` and returns the `RunOutcome`; never invoke the bare console script; for emit-ci-workflow, route the deploy at a throwaway `target_tree`
  - Observable completion: `run_fixture` over a fixture returns a `RunOutcome` with `exit_reason == "done"` and a `run_context` whose analysis/plan/written/review/site/deploy slots are all populated, with no network access
  - _Requirements: 1.2, 1.3, 2.5, 8.4_
  - _Boundary: tests/test_e2e_multi_project.py (run_fixture driver)_
  - _Depends: 1.1, 1.2, 2.1_

- [x] 3. Per-fixture correctness assertions (full pipeline)
- [x] 3.1 Assert per-fixture language detection and project-specific coverage plan
  - For each fixture (Go/Python/JS), run the pipeline and assert from the run context: the intended ecosystem language is among detected languages and is the primary language; the coverage plan has at least one segment; every planned segment's roles/intent/subject prefixes are members of the loaded vocabulary; running the same fixture twice yields the same plan
  - Observable completion: three language tests pass (`Go`/`Python`/`JavaScript` primary), the plan-non-empty + vocab-validity assertions pass per fixture, and the determinism assertion passes
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 4.1, 4.2, 4.3_
  - _Boundary: tests/test_e2e_multi_project.py (language + plan assertions)_
  - _Depends: 2.2_

- [x] 3.2 (P) Assert written + reviewed non-empty accepted segments per fixture
  - For each fixture, assert the Write stage wrote one segment per planned segment with non-empty bodies persisted as Markdown under `<out>/segments`, and the Review stage accepted every segment with a non-empty accepted set and no `unavailable` entry; assert `accepted == written > 0`
  - Observable completion: per fixture, the written-count equals the planned-count, every body is non-empty, the accepted-count equals the written-count and is greater than zero, and no entry used the fail-closed unavailable default
  - _Requirements: 5.1, 5.2, 5.3_
  - _Boundary: tests/test_e2e_multi_project.py (write/review assertions)_
  - _Depends: 2.2_

- [x] 3.3 (P) Assert per-target assembled site and base-path per fixture
  - For each fixture, assert the assembled site's identity carries base-path `/<repo>/` and site URL `https://<owner>.github.io/<repo>/` derived from that fixture's remote, that the assembled `mkdocs.yml` carries that site URL, and that neither carries a DocuHarnessX-specific site identity
  - Observable completion: per fixture, the resolved base-path and site URL match the fixture's own `owner/repo` and the `mkdocs.yml` contains the per-target site URL with no DocuHarnessX identity string
  - _Requirements: 6.1, 6.2, 6.3_
  - _Boundary: tests/test_e2e_multi_project.py (assembled-site assertions)_
  - _Depends: 2.2_

- [x] 3.4 Assert a real mkdocs build under the per-target base-path per fixture
  - For each fixture, run the deploy via the injected `PyMkdocsNoPushRunner` (build-only for most fixtures), assert the built static site exists with at least one rendered page and a sitemap, every sitemap URL sits under that fixture's `/<repo>/` base-path, exactly one build ran, and no `gh-deploy` push ran
  - Observable completion: per fixture the build directory exists with rendered pages, the sitemap places every URL under `/<repo>/`, `build_count()` equals 1, and `pushed` is False
  - _Requirements: 7.1, 7.2, 7.3, 7.4_
  - _Boundary: tests/test_e2e_multi_project.py (build assertions)_
  - _Depends: 2.2_

- [x] 3.5 Assert emit-ci-workflow emission, isolation, and clean exit on a fixture
  - On at least one fixture, run the deploy in emit-ci-workflow mode into a throwaway target tree and assert: `mkdocs.yml`, a `docs/` directory, and a `.github/workflows/` workflow are written into the target tree; the workflow is parseable YAML carrying a push trigger on the target's default branch, the minimal Pages permissions (`pages: write`, `id-token: write`), and a build job plus a deploy-pages job; writes stay scoped to the output dir + target tree; the deploy result status is the emitted status; and the run exits with reason `done`
  - Observable completion: the three emit artifacts exist in the target tree, the parsed workflow carries the push trigger + Pages permissions + build/deploy jobs, no write escaped the output/target dirs, and the outcome reports `done` with the success exit code
  - _Requirements: 8.1, 8.2, 8.3, 8.4_
  - _Boundary: tests/test_e2e_multi_project.py (emit-ci-workflow assertions)_
  - _Depends: 2.2_

- [x] 4. Cross-fixture difference and no-example-hardcoding guard
- [x] 4.1 Assert cross-fixture difference (plans, identities, languages)
  - Compare two different-ecosystem fixtures and assert their planned-segment sets are not identical and their assembled base-paths and site URLs differ; assert the set of detected primary languages across the Go/Python/JS fixtures has more than one distinct value
  - Observable completion: the planned-segment sets of two fixtures differ, their base-paths/site URLs differ, and the primary-language set across the three fixtures is not a single value
  - _Requirements: 9.1, 9.2, 9.3_
  - _Boundary: tests/test_e2e_multi_project.py (cross-fixture diff)_
  - _Depends: 3.1, 3.3_

- [x] 4.2 Assert the no-example-hardcoding guard and active vendor exclusion
  - Assert the pipeline runs end to end on a non-Go, non-`malware_hashes` fixture (Python and JS) producing a correct per-project buildable site with no `malware_hashes`-specific value required; plant a heavy vendor/build directory (e.g. `node_modules`/`vendor`/`target`/`.venv`/`__pycache__`) containing dependency files in a fixture and assert no file under it appears in the produced analysis inventory; assert no fixture's assembled site identity or deploy result carries a DocuHarnessX-specific identity string
  - Observable completion: the Python and JS fixtures build correctly with no `malware_hashes` literal in the assertions, the planted vendor directory contributes zero inventory entries, and no DocuHarnessX identity string appears in any fixture's site identity or deploy result
  - _Requirements: 10.1, 10.2, 10.3_
  - _Boundary: tests/test_e2e_multi_project.py (no-hardcoding guard)_
  - _Depends: 3.3, 3.4_

- [x] 5. Suite health and one-off real-repo validation
- [x] 5.1 Confirm the full test suite stays green with the new module
  - Run `.venv/bin/python -m pytest -q` and confirm the new `tests/test_e2e_multi_project.py` passes and the overall suite remains green (no regressions to the existing tests)
  - Observable completion: the full pytest run reports all tests passing, including the new e2e module, with the prior baseline preserved
  - _Requirements: 1.4_
  - _Depends: 3.1, 3.2, 3.3, 3.4, 3.5, 4.1, 4.2_

- [x] 5.2 Run and capture the one-off real-repo generalization validation
  - Using a throwaway driver (not committed pipeline code), run the full pipeline credential-free via the programmatic path with the routing fake against the five representative targets — `malware_hashes` (Go), DocuHarnessX (Python), `pallets/click` (Python), `expressjs/express` (JS), `BurntSushi/ripgrep` (Rust); copy each target to a throwaway temp dir excluding heavy dirs (or use build-only) so no real repo is mutated; never push to any remote; for each target confirm the detected primary language matches its ecosystem, a non-empty accepted segment set, an assembled site under the target's `/<repo>/` base-path, and a successful build; confirm the scanner excluded heavy vendor/build dirs; capture a generalization report as session evidence
  - Observable completion: a generalization report is produced summarizing per-target primary language, accepted-segment count, resolved base-path, and build success for all five targets, confirming no real repo was mutated and no push occurred
  - _Requirements: 11.1, 11.2, 11.3, 11.4, 11.5_
  - _Depends: 1.1, 1.2_
