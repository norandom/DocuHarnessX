# Requirements Document

## Introduction

This is the Wave 4 finale of DocuHarnessX: the end-to-end validation that the full `dhx` pipeline (Ingest → Analyze → Classify → Plan → Write → Review → Assemble → Deploy) produces a correct, publishable, **per-project** Material for MkDocs site for **arbitrary** software projects — across languages, ecosystems, and project shapes — not just the `malware_hashes` reference target. Every pipeline stage is already built and merged on `main` (Waves 0–3); a bare `dhx <repo> --out DIR` already runs the whole chain. This spec adds nothing to the pipeline. It **proves generality is a permanent, tested property** and guards against any example-specific assumption creeping back in.

The deliverable has two parts:

- **A hermetic, credential-free end-to-end test suite** (`tests/test_e2e_multi_project.py`). It ships small, **crafted** fixture repositories of different ecosystems — at least Go, Python, and JavaScript/Node — and runs the **full** `dhx` pipeline against each one via the **programmatic path** (`cli.prepare_run(args, model_config=<fake>)` then `cli.orchestrate_run(prepared)`), driven by a **content-routing fake model provider** (no network, no credentials). The routing fake returns a passing per-criterion JSON verdict for review/judge prompts (so the quality gate accepts segments and the site has real pages) and non-trivial Markdown prose otherwise (so the writer produces real bodies). Per fixture, the suite asserts: the correct primary language(s) detected for that ecosystem; a project-specific `CoveragePlan`; written **and** reviewed **non-empty** accepted segments; an assembled site whose `mkdocs.yml` carries that target's `/<repo>/` Pages base-path; a real `mkdocs build` succeeds under that base-path; the emit-ci-workflow files are emitted into a throwaway target tree; and the run finishes with exit reason `done`. The suite also asserts **cross-fixture difference** (different ecosystems yield genuinely different plans/sites, not one template) and includes a **no-example-hardcoding guard** (no `malware_hashes`/Go-only assumption is required, and heavy vendor/build directories are excluded from the scan).
- **A documented one-off real-repo validation** (run this session as captured evidence, **not** a persistent CI test). The full pipeline runs credential-free against five representative real targets — `malware_hashes` (Go), DocuHarnessX itself (Python dogfood), `pallets/click` (Python), `expressjs/express` (JS), `BurntSushi/ripgrep` (Rust) — each into a throwaway copy/output directory, asserting a correct per-project site builds with the right base-path, and capturing a generalization report.

Two findings from a grounding spike shape the requirements. First, the Deploy stage and the build-validation step invoke a bare `mkdocs` executable; when no `mkdocs` console script is on `PATH` the build crashes, so the suite must drive the build through the project interpreter (`python -m mkdocs`) via an injected command runner that also refuses any `gh-deploy` network push — exactly the pattern the existing deploy build-E2E suite uses. Second, on a tiny fixture a CI YAML file can out-LOC the intended source language and become the primary; crafted fixtures must therefore carry enough real source LOC that the intended ecosystem language is unambiguously primary.

## Boundary Context

- **In scope**: A new hermetic, credential-free end-to-end test module (`tests/test_e2e_multi_project.py`); the crafted multi-language fixture repositories (Go, Python, JS at minimum) and their builders; a reusable content-routing fake provider that accepts review prompts and emits prose otherwise; a reusable build runner that rewrites a bare `mkdocs` invocation to the project interpreter and refuses any `gh-deploy` push; per-fixture full-pipeline assertions (languages, project-specific plan, non-empty reviewed segments, assembled `mkdocs.yml` base-path, real `mkdocs build`, emitted CI workflow, exit `done`); a cross-fixture difference assertion; a no-example-hardcoding guard including a vendor/build-exclusion check; keeping the whole test suite green; and a one-off documented real-repo validation across the five representative targets with a captured generalization report.
- **Out of scope**: Any new or changed pipeline behavior — Ingest, Analyze, Classify, Plan, Write, Review, Assemble, Deploy and their core packages, `make_docgen`, the stage registry, the ontology APIs, the CLI argument surface, and the model resolver are all consumed read-only and are **not** modified. Pushing to any real remote (a `gh-deploy` network push is never run, in tests or in the one-off run). Adding the real external clones to the persistent suite (the persistent suite depends only on crafted fixtures + a fake model, never on the network or the pre-cloned repos). Non-MkDocs backends, multi-repo aggregation, model evolution, and docs i18n.
- **Adjacent expectations**: The pipeline is driven through the existing programmatic seam (`cli.prepare_run` with an injected `model_config`, then `cli.orchestrate_run`) so production model resolution is never touched; the bare `dhx` console script is never invoked in tests or the one-off run. Per-target site identity (`site_name`, `repo_url`, `site_url`, the `/<repo>/` `base_path`) is read from the `AssembledSite.identity` the assembler resolves from the target's git remote, not hardcoded. The fixtures and one-off targets must each have (or be given) an `origin` remote so a GitHub-shaped `/<repo>/` base-path is resolved. The scanner already excludes heavy directories (`.git`, `.venv`, `node_modules`, `vendor`, `target`, `__pycache__`, `dist`, `build`, `site`); a change to that exclusion set, to the programmatic run seam, to the `AssembledSite`/`SiteIdentity` shape, to `DeployResult`, or to the language-detection table is a revalidation trigger for this spec.

## Requirements

### Requirement 1: Hermetic, credential-free, multi-language fixture suite

**Objective:** As a DocuHarnessX maintainer, I want a self-contained test suite that exercises the full pipeline on multiple crafted ecosystems without any network or credentials, so that pipeline generality is enforced on every test run.

#### Acceptance Criteria
1. The end-to-end suite shall provide at least three crafted fixture repositories spanning distinct ecosystems — a Go project, a Python project, and a JavaScript/Node project — each created on local disk under a temporary directory at test time.
2. The end-to-end suite shall drive the pipeline only through the programmatic path — building the run namespace, calling the run-preparation entry point with an injected fake model configuration, and then calling the run-orchestration entry point — and shall never invoke the bare `dhx` console script.
3. The end-to-end suite shall never open a network connection, read a real model credential, or depend on the pre-cloned external repositories, so that the suite is hermetic and credential-free.
4. While the full test suite is executed, the end-to-end suite shall pass and the suite shall remain green.
5. Each crafted fixture repository shall carry enough source lines of code in its intended ecosystem language that this language is the unambiguous primary language, and shall be given an `origin` git remote so a GitHub project-Pages identity is resolved for it.

### Requirement 2: Content-routing fake model provider

**Objective:** As the end-to-end suite, I want a fake model provider that routes by prompt content, so that the quality review gate accepts segments and the assembled site has real pages instead of failing closed to an empty site.

#### Acceptance Criteria
1. The content-routing fake provider shall subclass the HarnessX base model provider so it is a genuine provider that binds via the standard agentic model configuration and passes provider type checks.
2. When the provider receives a review/judge prompt, the content-routing fake provider shall return a valid per-criterion JSON verdict scoring every COBESY criterion at or above the acceptance threshold with an overall pass, so the gate accepts the judged segment.
3. When the provider receives a non-review prompt, the content-routing fake provider shall return non-trivial Markdown writer prose (a body and a summary), so written segment bodies are non-empty.
4. The content-routing fake provider shall perform no network access and require no credentials.
5. While the routing fake is bound, the run shall reach the terminal exit reason `done`.

### Requirement 3: Per-fixture language detection

**Objective:** As a maintainer, I want each fixture's primary language detected correctly per ecosystem, so that language detection is proven to generalize beyond Go.

#### Acceptance Criteria
1. When the pipeline runs against the Go fixture, the Analyze stage shall report `Go` among the detected languages and as the primary language.
2. When the pipeline runs against the Python fixture, the Analyze stage shall report `Python` among the detected languages and as the primary language.
3. When the pipeline runs against the JavaScript/Node fixture, the Analyze stage shall report `JavaScript` among the detected languages and as the primary language.
4. The end-to-end suite shall read the detected languages and primary language(s) from the produced repository analysis through the run-context accessor, and shall assert them per fixture.

### Requirement 4: Per-fixture project-specific coverage plan

**Objective:** As a maintainer, I want each fixture to yield a non-empty, project-specific coverage plan, so that planning is proven to adapt to the project rather than emit a fixed template.

#### Acceptance Criteria
1. When the pipeline runs against any fixture, the Plan stage shall produce a coverage plan with at least one planned segment, read from the run context.
2. The end-to-end suite shall assert each planned segment's roles, intent, and subject prefixes are members of the loaded vocabulary.
3. The coverage plan produced for a given fixture shall be reproducible: running the pipeline twice over the same fixture yields the same plan.

### Requirement 5: Written and reviewed non-empty segments

**Objective:** As a maintainer, I want each fixture's segments written and accepted by the quality gate, so that the assembled site for an arbitrary project is provably non-empty.

#### Acceptance Criteria
1. When the pipeline runs against any fixture with the routing fake bound, the Write stage shall write one segment per planned segment, each with a non-empty body, and persist each as a Markdown file under the output segments directory.
2. When the Review stage judges the written segments with the routing fake bound, the Review stage shall accept every segment, the accepted set shall be non-empty, and no entry shall be judged via the unavailable fail-closed default.
3. The end-to-end suite shall assert the count of accepted segments equals the count of written segments and is greater than zero for each fixture.

### Requirement 6: Per-target assembled site and base-path

**Objective:** As a maintainer, I want each fixture's assembled site to carry that target's own Pages base-path, so that the site is provably per-project and never hardcoded to DocuHarnessX.

#### Acceptance Criteria
1. When the pipeline runs against a fixture whose `origin` remote is a GitHub remote `owner/repo`, the Assemble stage shall produce an assembled site whose identity carries the base-path `/<repo>/` and the site URL `https://<owner>.github.io/<repo>/`.
2. The assembled site's `mkdocs.yml` shall carry that target's site URL, and shall carry no DocuHarnessX-specific site identity.
3. The end-to-end suite shall assert each fixture's resolved base-path and site URL are derived from that fixture's remote and differ between fixtures with different remotes.

### Requirement 7: Real mkdocs build under the per-target base-path

**Objective:** As a maintainer, I want a real `mkdocs build` to succeed for each fixture under that target's base-path, so that the generated site is proven publishable for arbitrary projects.

#### Acceptance Criteria
1. When the Deploy stage runs in build-only or emit-ci-workflow mode for a fixture, the build shall be driven through the project interpreter's mkdocs module via an injected command runner so it resolves regardless of whether a bare `mkdocs` console script is on `PATH`.
2. When the build completes for a fixture, the produced static site shall exist as a directory containing at least one rendered page and a sitemap, and every URL in the sitemap shall sit under that fixture's `/<repo>/` Pages base-path.
3. If the injected command runner is ever asked to run a `gh-deploy` push, the runner shall raise instead of performing any network action, so the suite proves the push is never exercised.
4. The end-to-end suite shall assert exactly one build ran per fixture deploy and that no `gh-deploy` push ran.

### Requirement 8: Emitted CI workflow and successful exit

**Objective:** As a maintainer, I want the emit-ci-workflow mode to write a valid Pages workflow into a throwaway target tree and the run to exit cleanly, so that the publish handoff is proven for arbitrary projects without mutating any real repository.

#### Acceptance Criteria
1. When the Deploy stage runs in emit-ci-workflow mode for a fixture, it shall write `mkdocs.yml`, a `docs/` directory, and a `.github/workflows/` Pages workflow into the throwaway target tree, and the deploy result status shall be the emitted status.
2. The emitted workflow shall be parseable YAML carrying a push trigger on the target's default branch, the minimal Pages deployment permissions, and a build job and a deploy-pages job.
3. The emit-ci-workflow run shall write only under the run output directory and the throwaway target tree, leaving every other location untouched.
4. When the full pipeline run completes for a fixture, the orchestration outcome shall report the exit reason `done` and the mapped exit code for success.

### Requirement 9: Cross-fixture difference

**Objective:** As a maintainer, I want different ecosystems to produce genuinely different plans and sites, so that the pipeline is proven project-specific rather than templated.

#### Acceptance Criteria
1. The end-to-end suite shall compare the coverage plans produced for at least two different-ecosystem fixtures and assert the planned-segment sets are not identical.
2. The end-to-end suite shall compare the assembled site identities produced for at least two fixtures with different remotes and assert the base-paths and site URLs differ.
3. The end-to-end suite shall assert that the set of detected primary languages differs across the Go, Python, and JavaScript fixtures.

### Requirement 10: No-example-hardcoding guard

**Objective:** As a maintainer, I want an explicit guard that no `malware_hashes`/Go-only assumption is required and that heavy vendor directories are excluded, so that example-specific assumptions cannot creep back in.

#### Acceptance Criteria
1. The end-to-end suite shall run end to end on a non-Go, non-`malware_hashes` fixture (the Python and JavaScript fixtures) and assert a correct per-project buildable site, requiring no `malware_hashes`-specific value.
2. Where a fixture plants a heavy vendor or build directory (such as `node_modules`, `vendor`, `target`, `.venv`, or `__pycache__`) containing dependency files, the scan shall exclude that directory so no file under it appears in the produced repository analysis inventory.
3. The end-to-end suite shall assert that the assembled site identity and the deploy result for every fixture carry no DocuHarnessX-specific identity string.

### Requirement 11: One-off real-repo generalization validation

**Objective:** As a maintainer, I want a documented one-off run across five representative real repositories, so that the pipeline's generality is demonstrated on real diverse projects this session.

#### Acceptance Criteria
1. The one-off validation shall run the full pipeline credential-free, via the programmatic path with the content-routing fake provider, against five representative targets: `malware_hashes` (Go), DocuHarnessX itself (Python), `pallets/click` (Python), `expressjs/express` (JS), and `BurntSushi/ripgrep` (Rust).
2. Before running emit-ci-workflow against a target, the one-off validation shall copy the target to a throwaway temporary directory (excluding heavy directories) or use build-only mode, so that no real repository is mutated.
3. For each target, the one-off validation shall confirm the detected primary language matches the target's ecosystem, a non-empty accepted segment set, an assembled site under that target's `/<repo>/` base-path, and a successful build, and shall record the result.
4. The one-off validation shall never push to any real remote.
5. The one-off validation shall produce a captured generalization report summarizing per-target results and confirming the scanner excluded heavy vendor/build directories on the real targets, and this report shall be delivered as session evidence rather than a persistent CI test.
