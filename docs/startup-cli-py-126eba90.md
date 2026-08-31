---
id: startup:cli.py
title: How does this program start?
subjects:
- cli.py
summary: 'The whole program starts at one function: `main` in `docuharnessx/cli.py`.
  It is installed as the `dhx` console script by `pyproject.toml` (`[project.scripts]
  dhx = "docuharnessx.cli:main"`, `pyproject.toml:39`), and it is also the module
  entry point — `if __name__ == "__main__": raise SystemExit(main())` (`docuharnessx/cli.py:1106`).
  So a bare `dhx` command, and `python` execution of the module, both land in `main(argv:
  Sequence[str] | None = None, *, model_config=None, max_steps=None, init_input=None)`
  (`docuharnessx/cli.py:1032`).'
related: []
---
# How does this program start?

# How `dhx` starts: the `docuharnessx/cli.py` entry path

The whole program starts at one function: `main` in `docuharnessx/cli.py`. It is installed as the `dhx` console script by `pyproject.toml` (`[project.scripts] dhx = "docuharnessx.cli:main"`, `pyproject.toml:39`), and it is also the module entry point — `if __name__ == "__main__": raise SystemExit(main())` (`docuharnessx/cli.py:1106`). So a bare `dhx` command, and `python` execution of the module, both land in `main(argv: Sequence[str] | None = None, *, model_config=None, max_steps=None, init_input=None)` (`docuharnessx/cli.py:1032`).

## Startup sequence inside `main`

`main` runs the following steps in order (`docuharnessx/cli.py:1060-1103`):

1. **Load `.env` files** via `_load_env_files()` (`docuharnessx/cli.py:1060`, helper at `docuharnessx/cli.py:112`). It calls `python-dotenv`'s `load_dotenv(path, override=False)` for `.env` in the cwd and then the install/source project root (`_env_file_paths`, `docuharnessx/cli.py:102`). It is skipped while pytest runs unless `force=True` (`docuharnessx/cli.py:118`).
2. **Build the argparse parser** with `build_parser()` (`docuharnessx/cli.py:1061`; parser at `docuharnessx/cli.py:185`). The parser exposes three subcommands — `run`, `init`, `mcp` — via `parser.add_subparsers(dest="command", ...)` (`docuharnessx/cli.py:201`).
3. **Normalize the bare CLI form**: `_normalize_argv(argv)` (`docuharnessx/cli.py:1071`, helper at `docuharnessx/cli.py:129`) prepends the implicit `run` subcommand when the first token is a positional that is not one of the known subcommands in `_SUBCOMMANDS = frozenset({"run", "init", "mcp"})` (`docuharnessx/cli.py:97`). This is what makes `dhx <target-repo> --out DIR --config YAML` work without typing `run` (`docuharnessx/cli.py:132-158`). When `argv is None` it is resolved to `sys.argv[1:]` before normalization (`docuharnessx/cli.py:1069-1070`).
4. **Handle the no-command case**: if `args.command is None` (e.g. bare `dhx`), it prints help and returns exit code `2` (`docuharnessx/cli.py:1073-1075`). `--help` exits via argparse's normal `SystemExit(0)` (`docuharnessx/cli.py:1041-1042`).
5. **Check the runtime dependency**: `_require_harnessx()` (`docuharnessx/cli.py:1079`, helper at `docuharnessx/cli.py:161`) does a deferred `import harnessx` and, on `ImportError`, raises `DependencyError` with the exact install command for the pinned HarnessX archive (`docuharnessx/cli.py:172-182`). The import is deferred so `dhx --help` and parser unit tests never need HarnessX.
6. **Configure logging**: `_configure_run_logging(getattr(args, "verbose", False))` (`docuharnessx/cli.py:1082`, helper at `docuharnessx/cli.py:961`) calls `harnessx.logging.configure_logging`, sets structlog's level, and installs two noise filters: `_DropHarnessSerializationNoise` (`docuharnessx/cli.py:920`) and `_DropEventLoopClosedNoise` (`docuharnessx/cli.py:938`). Without `-v` it also silences LiteLLM (`docuharnessx/cli.py:1017-1029`).
7. **Dispatch on the subcommand** (`docuharnessx/cli.py:1084-1098`): `run` → `_run_command`, `init` → `_init_command(args, input_fn=init_input)`, `mcp` → `_mcp_command(args)`; anything else prints `unknown command` and returns `1`.
8. **Catch the whole error family**: every boundary failure raises a `DocuHarnessXError` (base class at `docuharnessx/errors.py:38`, with subclasses `ConfigError`, `ModelResolutionError`, `TargetRepoError`, `DependencyError`, `OntologyConfigError`), which `main` prints to stderr as `<ErrorType>: <message>` and maps to exit code `1` (`docuharnessx/cli.py:1099-1103`).

## The `run` path

`_run_command` (`docuharnessx/cli.py:633`) is three steps: `prepare_run` → `orchestrate_run` → print the report path.

`prepare_run(args, *, model_config=None, stream=None)` (`docuharnessx/cli.py:431`) validates in a fixed order:

- **Target first**: `_validate_target_repo(args.target_repo)` (`docuharnessx/cli.py:460`, helper at `docuharnessx/cli.py:411`) raises `TargetRepoError` when the path is missing, nonexistent, or not a directory — before any run work (`docuharnessx/cli.py:418-428`).
- **Output directory**: `--out` absolutized, or the documented per-target default `os.path.join(target_repo, ".docuharnessx", "out")` from `_DEFAULT_OUT_RELPATH` (`docuharnessx/cli.py:374, 463-467`).
- **Ontology**: `load_project_vocabulary(target_repo)` (`docuharnessx/cli.py:471`) from `docuharnessx/ontology_loader.py:54` returns `(vocabulary, used_default)`. An absent `.docuharnessx/ontology.yaml` yields the engine's `default_profile()` plus a `dhx init` hint printed to stdout (`docuharnessx/cli.py:472-479`, `docuharnessx/ontology_loader.py:80-81`); a present-but-invalid file raises `OntologyConfigError` (`docuharnessx/ontology_loader.py:85-90`).
- **Config**: `load_config(config_path=args.config, cli_overrides=..., vocabulary=vocabulary)` (`docuharnessx/cli.py:494`, definition at `docuharnessx/config.py:238`) reads the YAML file first, then overlays CLI overrides (`out_dir`, `roles`, `deploy_mode`) so CLI wins (`docuharnessx/cli.py:483-493`). Roles are validated against the loaded `Vocabulary` and default to all of its role ids (`docuharnessx/config.py:288-291`).
- **Model**: unless a `ModelConfig` was injected, `resolve_model(config.model)` from `docuharnessx/model_resolver.py:246` is tried, and a `ModelResolutionError` is swallowed to `model=None` — an honest-empty run rather than a hard failure (`docuharnessx/cli.py:503-511`). The resolver itself uses config-then-env precedence and builds an `AnthropicProvider`, native `OpenAIProvider`, or `LiteLLMProvider` (`docuharnessx/model_resolver.py:246-279`).

`orchestrate_run(prepared, *, max_steps=None, task_description=None)` (`docuharnessx/cli.py:582`) creates the output dir, then calls `run_pipeline` imported as `run_explore_pipeline` from `docuharnessx.pipeline.run` (`docuharnessx/cli.py:601, 604-609`). `run_pipeline` (`docuharnessx/pipeline/run.py:82`) runs the sequential explore-first pipeline: `scan(repo_path)` → `analyze(inventory)` → `plan_questions(analysis)` → `write_questions(...)` → write the `RunReport` and accepted pages → assemble a site only when accepted ≥ 1 (`docuharnessx/pipeline/run.py:102-126`). Back in the CLI, `_publish_if_accepted` (`docuharnessx/cli.py:523`) invokes `deploy_site` via `docuharnessx/deployer` only when there is at least one accepted page and a `<out>/site/mkdocs.yml` exists (`docuharnessx/cli.py:539-579`). The outcome maps to exit code `0` for `done`, else `1` (`exit_code_for_reason`, `docuharnessx/cli.py:386-396`), and `_run_command` prints the `report.json` path (`docuharnessx/cli.py:648-662`).

## The `init` and `mcp` paths

`_init_command` (`docuharnessx/cli.py:850`) skips HarnessX entirely and delegates to `docuharnessx.ontology_setup.run_init` (`docuharnessx/ontology_setup.py:129`). With `--default` it seeds the shipped default profile; otherwise, when stdin is a TTY (or an `input_fn` is injected), it gathers roles/intents/subjects through `_gather_init_answers` / `_prompt_axis_terms` / `_prompt_subjects` (`docuharnessx/cli.py:782-847`) before calling `run_init` (`docuharnessx/cli.py:899-905`). A refused overwrite (`FileExistsError` without `--force`) returns `EXIT_INIT_FAILED = 1` (`docuharnessx/cli.py:906-914`); success prints the written `ontology.yaml` path and returns `0` (`docuharnessx/cli.py:916-917`).

`_mcp_command` (`docuharnessx/cli.py:719`) first guards the MCP SDK with `_require_mcp()` (`docuharnessx/cli.py:750`, helper at `docuharnessx/cli.py:665`), then — only when a `target_repo` was given — validates it with the same `_validate_target_repo` and builds a per-target session via `resolve_session(target_repo, out_dir, config_path=...)` (`docuharnessx/cli.py:759-763`, resolver at `docuharnessx/mcp/session.py:99`). Finally `_run_stdio_blocking(session)` (`docuharnessx/cli.py:778`, helper at `docuharnessx/cli.py:704`) wraps `asyncio.run(run_stdio(session))`, where `run_stdio` from `docuharnessx/mcp/server.py:206` builds the refine server and runs it over the stdio transport until the client disconnects. The launcher's human-readable messages go to stderr so stdout stays a clean MCP protocol channel (`docuharnessx/cli.py:764-774`).

In short: **`pyproject.toml:39` wires the `dhx` script to `cli.main`; `cli.py:1060-1103` loads env, parses/normalizes args, guards dependencies, configures logging, and dispatches to `_run_command` / `_init_command` / `_mcp_command`; the `run` path then flows through `prepare_run` (`cli.py:431`) → `orchestrate_run` (`cli.py:582`) → `run_pipeline` (`pipeline/run.py:82`) → `deploy_site` (`cli.py:573`).**
