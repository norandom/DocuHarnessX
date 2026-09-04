---
id: startup:cli.py
title: How does this program start?
subjects:
- cli.py
summary: 'The `dhx` program starts in `docuharnessx/cli.py`, whose `main()` is the
  console-script entry point, and the startup path is: entry point → env loading →
  argparse construction → argv normalization → dispatch to a subcommand handler (defaulting
  to `run`).'
related: []
cited_files:
- pyproject.toml
- docuharnessx/cli.py
- docuharnessx/ontology_loader.py
- docuharnessx/config.py
- docuharnessx/pipeline/run.py
---
# How does this program start?

The `dhx` program starts in `docuharnessx/cli.py`, whose `main()` is the console-script entry point, and the startup path is: entry point → env loading → argparse construction → argv normalization → dispatch to a subcommand handler (defaulting to `run`).

## The actual process entry point

Two routes reach `main()`:

- The installed console script: `pyproject.toml:32-33` declares `[project.scripts] dhx = "docuharnessx.cli:main"`, so running `dhx` invokes `docuharnessx.cli.main`.
- Direct module execution: `docuharnessx/cli.py:1535-1536` has `if __name__ == "__main__": raise SystemExit(main())`, so `python docuharnessx/cli.py` follows the same path and converts `main()`'s return code into the process exit status.

There is no package-level `__main__.py`, so `python -m docuharnessx` is not a startup route.

## What `main()` does first

`main()` is defined at `docuharnessx/cli.py:1446` with `argv=None`, `model_config=None`, `max_steps=None`, and `init_input=None` keyword seams. Its startup sequence is:

1. **Load `.env` files**: `_load_env_files()` is the first call (`cli.py:1474`). The helper at `cli.py:126-140` looks for `.env` in the cwd and then the project root (`_env_file_paths`, `cli.py:116-123`) and calls `load_dotenv(path, override=False)` — but bails out early when `PYTEST_CURRENT_TEST` is set so tests cannot pick up local secrets (`cli.py:132`).
2. **Build the parser**: `build_parser()` at `cli.py:1475` returns an `argparse.ArgumentParser` (`cli.py:199`) whose subparsers register `run`, `init`, `status`, `sufficient`, `evolve`, `hook`, `ci`, `install-hooks`, `install-ci`, and `mcp` (`cli.py:215-484`).
3. **Resolve argv**: when `argv is None` it falls back to `sys.argv[1:]` at `cli.py:1483-1484`, then `_normalize_argv(argv)` at `cli.py:1485` is applied before parsing.
4. **Parse**: `parser.parse_args(_normalize_argv(argv))` (`cli.py:1485`).

The normalizer (`cli.py:143-172`) implements the spec's bare form `dhx <target-repo> --out DIR --config YAML`: if the first token is a positional that is not a member of `_SUBCOMMANDS` (`cli.py:98-111`), it prepends `"run"` (`cli.py:172`); leading flags and known subcommands pass through unchanged (`cli.py:168`). So `dhx /path/to/repo --out /tmp/out` becomes `run /path/to/repo --out /tmp/out` before argparse ever sees it.

After parsing, if no command was given, `main()` prints help and returns exit code 2 (`cli.py:1487-1489`).

## Dependency guard and logging

`install-hooks` and `install-ci` are dispatched immediately (`cli.py:1491-1494`) because they need no runtime. For every other real command, `main()` calls `_require_harnessx()` (`cli.py:1498`), which imports `harnessx` lazily and raises a typed `DependencyError` naming the missing dependency and its install URL if it is not importable (`cli.py:175-196`). Then `_configure_run_logging(getattr(args, "verbose", False))` (`cli.py:1501`, defined at `cli.py:1375`) raises the console level from `WARNING` to `INFO` under `-v` and installs filters that drop benign noise (the HarnessX `todo_write` serialization warning and the httpx "Event loop is closed" teardown error, `cli.py:1334-1372`).

## Dispatch to handlers

Inside a `try` block (`cli.py:1503-1527`), the parsed `args.command` selects a handler:

- `run` → `_run_command(args, model_config=model_config, max_steps=max_steps)` (`cli.py:1504-1507`)
- `init` → `_init_command(args, input_fn=init_input)` (`cli.py:1508-1509`)
- `mcp` → `_mcp_command(args)` (`cli.py:1510-1511`)
- `status` / `sufficient` / `evolve` / `hook` / `ci` similarly (`cli.py:1512-1521`)

Any `DocuHarnessXError` raised by a handler is caught at `cli.py:1528-1532`, printed to stderr as `<ErrorType>: <message>`, and mapped to exit code 1.

## The `run` path in detail

`_run_command` (`cli.py:799-828`) chains three steps:

1. **`prepare_run`** (`cli.py:590-684`): validates the target first via `_validate_target_repo` (`cli.py:619`, defined at `cli.py:570-587` — raises `TargetRepoError` for a missing/non-directory target), calls `load_project_env(target_repo)` (`cli.py:620-622`), resolves the output dir (defaulting to `<target>/.docuharnessx/out` via `_DEFAULT_OUT_RELPATH`, `cli.py:533` and `cli.py:625-629`), loads the vocabulary with `load_project_vocabulary(target_repo)` (`cli.py:633`, defined in `docuharnessx/ontology_loader.py:55`), prints the "adopt the blueprint" hint when no ontology file exists (`cli.py:634-641`), then overlays CLI overrides onto `load_config(...)` (`cli.py:656`, defined in `docuharnessx/config.py:238`). Finally, unless a `model_config` was injected, it calls `docuharnessx.model_resolver.resolve_model(config.model)` and swallows `ModelResolutionError` into `model=None` (`cli.py:665-672`) — a no-model run is an honest-empty run, not a failure.
2. **`orchestrate_run`** (`cli.py:746-796`): imports `run_pipeline` under the alias `run_explore_pipeline` (`cli.py:765`) — deliberately aliased so it does not shadow this module's `RunOutcome` — creates `out_dir`, and calls it with `repo_path`, `out_dir`, `model`, `deploy_mode`, `regenerate_all`, and `regenerate_ids` (`cli.py:767-775`). If the pipeline accepted any pages, `_publish_if_accepted` (`cli.py:687-743`) then runs `deploy_site` with a command runner that rewrites `mkdocs` to `python -m mkdocs` (`cli.py:715-743`). Completed runs, including honest-empty, return `RunOutcome(exit_reason="done", exit_code=EXIT_OK)` (`cli.py:791-796`); a publish failure maps to `EXIT_RUN_FAILED`.
3. **Report**: `_run_command` prints `dhx run: completed ... Report: <out>/report.json` on success or the failure reason to stderr (`cli.py:814-828`), returning the outcome's exit code.

The actual documentation work happens in `run_pipeline` (`docuharnessx/pipeline/run.py:87-157`): it re-checks `repo_path` is a directory (`run.py:104`), then runs `scan(repo_path)`, `analyze(inventory)`, `plan_questions(analysis)`, writes unanswered/regenerate-requested questions through `write_questions`, persists accepted pages into a `FilesystemLivingPageStore`, writes the `RunReport`, and assembles a site only when accepted ≥ 1 (`run.py:109-156`).

## Other startup entry points in this module

- `dhx mcp` → `_mcp_command` (`cli.py:885-945`): guards the MCP SDK via `_require_mcp()` (`cli.py:916`), optionally validates the target with the same `_validate_target_repo` (`cli.py:927`), resolves the refine session via `resolve_session` (`cli.py:929`, wrapper at `cli.py:856-867`), and blocks serving stdio through `_run_stdio_blocking` → `asyncio.run(docuharnessx.mcp.run_stdio(session))` (`cli.py:870-882`, `cli.py:944`).
- `dhx init` → `_init_command` (`cli.py:1044-1180`): refuses an existing ontology without `--force` with `EXIT_INIT_FAILED` (`cli.py:1091-1100`), picks `--default` vs. interactive (TTY/`input_fn`) modes (`cli.py:1103-1140`), and delegates to `docuharnessx.ontology_setup.run_init` (`cli.py:1143-1148`).

Exit-code convention is defined at the module top: `EXIT_OK = 0` (`cli.py:537`), `EXIT_RUN_FAILED = 1` (`cli.py:542`), and `exit_code_for_reason` maps only the `"done"` terminal reason to 0 (`cli.py:545-555`).