---
id: component:docuharnessx
title: What does docuharnessx do?
subjects:
- docuharnessx
summary: DocuHarnessX is a Python tool for **generating grounded, role-based developer
  documentation from a software repository** (`docuharnessx/__init__.py:1`), packaged
  as version 1.1.0 and described in `pyproject.toml:4` as a "Human-centric, role-based
  GitHub Pages documentation generator built on HarnessX". It installs a single console
  script, `dhx`, wired to `docuharnessx.cli:main` (`pyproject.toml:33`).
related: []
---
# What does docuharnessx do?

# What DocuHarnessX does

DocuHarnessX is a Python tool for **generating grounded, role-based developer documentation from a software repository** (`docuharnessx/__init__.py:1`), packaged as version 1.1.0 and described in `pyproject.toml:4` as a "Human-centric, role-based GitHub Pages documentation generator built on HarnessX". It installs a single console script, `dhx`, wired to `docuharnessx.cli:main` (`pyproject.toml:33`).

## The `dhx` CLI

The CLI exposes three subcommands — `run`, `init`, and `mcp` (`docuharnessx/cli.py:97`) — and also accepts the bare form `dhx <target-repo> --out DIR --config YAML`, which `_normalize_argv` rewrites by prepending the implicit `run` subcommand when the first token is a positional path rather than a known subcommand (`cli.py:129-158`). Every boundary failure raises a typed error from the `DocuHarnessXError` family, which `main` catches, prints as `<ErrorType>: <message>` to stderr, and maps to a non-zero exit (`cli.py:1099-1103`).

- **`dhx run`** — the documentation pipeline. `_validate_target_repo` first checks the target is an existing directory, raising `TargetRepoError` otherwise (`cli.py:411-428`). Then `prepare_run` loads the project vocabulary via `load_project_vocabulary` (`cli.py:471`), builds a `DocgenConfig` with `load_config` from a `--config` YAML overlaid with CLI overrides (`cli.py:494-498`), and resolves a writer model with `resolve_model` unless a `ModelConfig` was injected (`cli.py:503-510`). A missing model is not an error: it is an "honest-empty" run that writes a zero-page report rather than substituting outline pages. `orchestrate_run` then calls `docuharnessx.pipeline.run.run_pipeline` and, only if at least one page was accepted, `_publish_if_accepted` invokes `deployer.deploy_site` (`cli.py:523-579`) — running mkdocs via `python -m mkdocs` so the venv package is used — under the resolved deploy mode (`emit-ci-workflow`, `gh-deploy`, or `build-only`).

- **`dhx init`** — scaffolds the per-project ontology file `.docuharnessx/ontology.yaml`. It dispatches to `ontology_setup.run_init` (`cli.py:880`), either seeding the default profile with `--default` or interactively gathering roles, intents, and subject prefixes via `_gather_init_answers` (`cli.py:834-847`). An existing file without `--force` is refused with `EXIT_INIT_FAILED` (`cli.py:906-914`).

- **`dhx mcp`** — launches a stdio MCP refine server for a target's generated docs (`cli.py:719-779`). It guards the `mcp>=1.28,<2` SDK with a `DependencyError`, validates the target, resolves a per-target session through `resolve_session` (`cli.py:690-701`, delegating to `docuharnessx.mcp.resolve_session`), and serves the MCP protocol over stdin/stdout while logging to stderr. The target is optional — the client can point the server with `open_workspace(repo, out)` at run time.

## The run pipeline

`run_pipeline` owns the step order (`docuharnessx/pipeline/run.py:82-127`): `scan(repo_path)` inventories the repository, `analyze` produces an analysis, `plan_questions` plans software questions, and `write_questions` writes/gates each question — producing accepted `Page`s and closed-set omissions. Accepted pages are persisted under `<out>/pages/` (`pipeline/run.py:42-52`), a `RunReport` (planned/accepted/omitted counts) is always written, and a question-organised MkDocs site is assembled **only when accepted ≥ 1** (`_assemble_if_accepted`, `pipeline/run.py:55-79`). The CLI maps exit reasons so only `done` returns 0; every other terminal reason (`budget_exceeded`, `loop_detected`, `error`, …) is non-zero (`cli.py:386-396`).

## Harness composition and stages

`make_docgen` in `docuharnessx/bundle.py:73-140` is the composition seam. It builds a **model-free** `HarnessConfig` from three pieces: a baseline Control bundle from `harnessx.bundles.control.make_control` with a cost guard (when `max_cost_usd` is given) and loop-detection thresholds raised to `_LOOP_THRESHOLD = 12` / `_LOOP_WARN_THRESHOLD = 8` for 25–40k LOC repos (`bundle.py:69-70`); the eight pipeline stages appended via the `|` operator; and a `HarnessJournal` tracer rooted at the output directory. `bundle.py` is deliberately the single HarnessX import site for the bundle/stage path, and it re-exports `HarnessConflictError` so conflicting singleton control capabilities surface rather than being silently merged.

The stage registry in `docuharnessx/stages/__init__.py` defines the canonical order `ingest → analyze → classify → plan → write → review → assemble → deploy` in the `STAGES` list (`stages/__init__.py:60-69`). `register_stages` appends each stage factory onto the `PIPELINE_HOOK` with strictly positive, increasing `order` (1…8) using append-don't-replace semantics (`stages/__init__.py:108-132`), and `stages_builder()` returns a stages-only builder for `|` composition (`stages/__init__.py:135-148`).

## Configuration, ontology, and model resolution

`docuharnessx/config.py` owns the frozen `DocgenConfig` dataclass (`config.py:92-119`) holding `target_repo`, `out_dir`, `roles`, `model`, `max_cost_usd`, `max_steps`, and `deploy_mode`. `load_config` fails fast on unknown YAML keys, malformed budgets, or role selections absent from the loaded `Vocabulary` (`config.py:221-235`); a missing role selection defaults to **all** roles in the vocabulary, never a hardcoded list (`config.py:289-293`).

Ontology handling is split deliberately. `docuharnessx/_ontology.py:50-71` is the single contract-level re-export site for the `ontology-engine` surface — `SegmentStore`, `AxisFilter`, `Segment`, `Vocabulary`, `load_vocabulary`, `vocabulary_to_config`, and `default_profile` — placed in a `_ontology.py` shim because `docuharnessx/ontology/` is a package owned by `ontology-engine` and would shadow a same-named module. `ontology_loader.load_project_vocabulary` locates `<project_dir>/.docuharnessx/ontology.yaml` (`ONTOLOGY_CONFIG_RELPATH`, `ontology_loader.py:51`): an absent file returns `(default_profile(), True)` so the CLI prints a `dhx init` hint, while a present-but-invalid file raises `OntologyConfigError` (`ontology_loader.py:54-91`).

Model resolution is config-then-env (`docuharnessx/model_resolver.py:246-279`): a configured `claude-*`/`anthropic/*` id routes to `AnthropicProvider`, `gpt-*`/`o*`/`openai/*` ids (with an OpenAI key) route to the native `OpenAIProvider` (whose tool-call/result pairing fix the agentic writer needs), and everything else to `LiteLLMProvider`; otherwise `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, or `LITELLM_API_KEY` (with optional default-model vars) select a provider. The model is never placed inside a `HarnessConfig` — the CLI binds it separately via `ModelConfig(main=...).agentic(make_docgen(...))` (`model_resolver.py:256-258`).

## Error model

All failures flow through the typed hierarchy in `docuharnessx/errors.py`: `ConfigError`, `ModelResolutionError`, `TargetRepoError`, `DependencyError`, and `OntologyConfigError` all derive from `DocuHarnessXError` (`errors.py:38-88`), so the CLI can catch the whole family at the boundary while still distinguishing causes.

In short: point `dhx run` at any repository, and DocuHarnessX scans and analyzes it, plans questions against the project's ontology (roles/intents/subjects), writes and gates answers with a model, assembles an MkDocs site under `<out>/site`, and publishes it to GitHub Pages — with an MCP server (`dhx mcp`) for interactively refining the generated segments afterward.
