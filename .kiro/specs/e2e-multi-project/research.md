# Research & Discovery Log — e2e-multi-project

## Discovery Scope

Extension/validation feature on a fully-built pipeline (Waves 0–3 on `main`). Discovery was integration-focused: confirm the programmatic credential-free run seam, the content-routing requirement for the review gate, the build-invocation pitfall, per-target identity resolution, and vendor-directory exclusion. A grounding spike ran the real pipeline end to end before writing the design.

## Key Findings

### F1 — Programmatic credential-free run works end to end (spike-confirmed)
`cli.prepare_run(args, model_config=ModelConfig(main=<fake>))` + `cli.orchestrate_run(prepared, max_steps=N)` drives the whole pipeline with no network and no real resolver. On a crafted Go fixture: ingest→analyze→classify→plan→write→review→assemble all fired; 9 planned → 9 written → 9 accepted; assembled site `base_path=/tool/`, `site_url=https://acme.github.io/tool/`; exit reason `done`. Outputs are readable via `RunContext` accessors (`repo_analysis`, `coverage_plan`, `written_segments`, `review_report`, `assembled_site`, `deploy_result`).

### F2 — A routing fake is mandatory (spike-confirmed)
A plain fake returning `"done"` makes the Review gate fail closed: every segment `judge_source="unavailable"`, `accepted=()`, empty site. The accept path needs a per-criterion passing JSON verdict (shape proven by `tests/test_stage_review_integration._passing_verdict_json`, using `docuharnessx.review.COBESY_CRITERIA`). The routing fake classifies a prompt as review when it contains COBESY criterion names / "criteria"; otherwise it returns `{body, summary}` writer prose. With the routing fake the spike got `accepted==written==9`.

### F3 — Build needs `python -m mkdocs`, not bare `mkdocs` (spike-confirmed)
The `DeployStage` build issued `["mkdocs", "build", ...]`; with no `mkdocs` console script on `PATH` the stage crashed with `FileNotFoundError: 'mkdocs'`. The existing deploy build-E2E suite (`tests/test_deploy_build_e2e_5_3._NoPushRealRunner`) already solves this: a `DefaultCommandRunner` subclass that rewrites a leading `mkdocs` token to `[sys.executable, "-m", "mkdocs", ...]` and raises on any `gh-deploy`. Injecting that runner onto the live `DeployStage._command_runner` (same processor-table walk as `cli._thread_deploy_mode`) made a real `python -m mkdocs build` succeed in build-only mode: status `built`, sitemap under `acme.github.io/tool/`, `build_count==1`, `pushed==False`, exit `done`.

### F4 — Tiny fixtures cause a primary-language tie (spike-confirmed)
With a minimal Go fixture, the CI `ci.yml` (YAML) out-LOC'd the Go source so `primary_languages=('YAML',)`. After bumping the Go source to ~40 funcs, `primary_languages=('Go',)`. Implication: each crafted fixture must carry enough real source LOC in its ecosystem language that this language is unambiguously primary; keep ancillary YAML/Markdown small.

### F5 — Per-target identity comes from the `origin` remote
`assembler.identity.resolve_site_identity` derives `site_url=https://<owner>.github.io/<repo>/` and `base_path=/<repo>/` from a GitHub `origin` remote; `stages/assemble.py` reads it via the mockable `read_origin_remote`. Fixtures must `git init` + `git remote add origin https://github.com/<owner>/<repo>.git` to get a GitHub base-path; different remotes → different base-paths (basis for the cross-fixture difference assertion).

### F6 — Scanner already excludes heavy dirs (spike-confirmed)
`scanner.DEFAULT_EXCLUDED_DIRS` covers `.git`, `.venv`, `node_modules`, `vendor`, `target`, `__pycache__`, `dist`, `build`, `site`, etc. A scan of the four real targets (`click`/`express`/`ripgrep`/`malware_hashes`) leaked **zero** vendor/build files. The freshly-cloned targets had no `node_modules`/`target` on disk, so the suite must assert exclusion **actively** by planting a `node_modules`/`vendor`/`target` dir in a fixture and checking nothing under it appears in the inventory.

### F7 — Project-specificity precedent
`tests/test_planning_project_specificity.py` already proves plans diverge by vocabulary. This spec's cross-fixture assertion extends that to diverge by **project shape** (different ecosystems/remotes), at the full-pipeline level.

## Synthesis / Decisions

- **Build vs adopt**: adopt the existing `FakeProvider` base and the `_NoPushRealRunner` pattern; add only `RoutingFakeProvider` and `PyMkdocsNoPushRunner` to `tests/_fakes.py` (append-only). No new production code.
- **Mode coverage**: exercise emit-ci-workflow on at least one fixture (to validate the emitted workflow + isolation) and build-only on the others; both drive a real build, neither pushes.
- **Hermeticity**: persistent suite uses crafted tmp fixtures only; the five real targets are a one-off session run, delivered as a captured generalization report, never a CI test.
- **No `tasks.md` edits / no commit** during the validation run, per the session constraint.

## Risks & Mitigations
- *Review-prompt heuristic too loose/tight* → mirror the proven `_passing_verdict_json` shape and key on `COBESY_CRITERIA`; covered by a helper-level check.
- *Build slowness across many fixtures* → keep fixtures tiny; build-only for most; emit-ci-workflow on one. (Spike build was sub-second.)
- *`mkdocs`/`mkdocs-material` absent* → already installed and declared runtime deps; guard with `pytest.importorskip` like the deploy build-E2E suite.
