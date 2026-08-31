---
id: component:deployer
title: What does deployer do?
subjects:
- deployer
summary: '`docuharnessx.deployer` is the pure, model-free deploy core of DocuHarnessX
  — the deterministic back end for the Wave 3 `github-pages-deploy` spec. Its module
  docstring calls it "the pure, model-free MkDocs deploy core" and "the deterministic,
  harness-free deploy core behind the thin `DeployStage` adapter" (`docuharnessx/deployer/__init__.py:1-4`).
  It does not run a model, touch the network by itself, or know about DocuHarnessX''s
  own repository: it consumes the frozen `AssembledSite` from `docuharnessx.assembler.model`
  verbatim and read-only, plus the run output dir and the target repo path, and "runs
  one of three configurable deploy modes against the **target project** (never DocuHarnessX''s
  own repo/Pages)" (`docuharnessx/deployer/__init__.py:3-10`).'
related: []
---
# What does deployer do?

# What `docuharnessx.deployer` does

`docuharnessx.deployer` is the pure, model-free deploy core of DocuHarnessX — the deterministic back end for the Wave 3 `github-pages-deploy` spec. Its module docstring calls it "the pure, model-free MkDocs deploy core" and "the deterministic, harness-free deploy core behind the thin `DeployStage` adapter" (`docuharnessx/deployer/__init__.py:1-4`). It does not run a model, touch the network by itself, or know about DocuHarnessX's own repository: it consumes the frozen `AssembledSite` from `docuharnessx.assembler.model` verbatim and read-only, plus the run output dir and the target repo path, and "runs one of three configurable deploy modes against the **target project** (never DocuHarnessX's own repo/Pages)" (`docuharnessx/deployer/__init__.py:3-10`).

## The three deploy modes

The supported modes are the `DeployMode` literal `Literal["emit-ci-workflow", "gh-deploy", "build-only"]` (`docuharnessx/deployer/model.py:73`):

- **`emit-ci-workflow`** (the default) — write `mkdocs.yml` + `docs/` + `.github/workflows/docs.yml` into the target working tree, no push;
- **`gh-deploy`** — `mkdocs gh-deploy` push to the target `gh-pages` branch, "the only network action";
- **`build-only`** — `mkdocs build` only, no publish (`docuharnessx/deployer/__init__.py:12-16`).

Mode selection is handled by `resolve_deploy_mode` in `docuharnessx/deployer/mode.py`: an absent/blank value returns the `_DEFAULT_MODE` `"emit-ci-workflow"`, a recognized value is returned trimmed, and anything else raises `DeployInputError` naming the bad value and the valid modes (`docuharnessx/deployer/mode.py:46-82`). The valid-mode set is derived from the `DeployMode` literal itself via `typing.get_args` (`docuharnessx/deployer/mode.py:42`), so the model is the single source of truth.

## How a mode is executed

The orchestrator `deploy_site` in `docuharnessx/deployer/deploy.py` runs the selected mode end to end and returns a frozen `DeployResult` (`docuharnessx/deployer/deploy.py:82-88`). Its three branches:

- `emit-ci-workflow`: calls `read_default_branch(target_repo, active_runner)`, renders the workflow with `render_pages_workflow(site.identity, default_branch)`, writes the target tree with `write_target_tree(site, target_repo, workflow_yaml)`, then runs `mkdocs build` validation, returning `status="emitted"` with the three written paths plus the built path (`docuharnessx/deployer/deploy.py:133-153`);
- `build-only`: only `run_mkdocs_build`, returning `status="built"` with `written_paths=()` (`docuharnessx/deployer/deploy.py:155-166`);
- `gh-deploy`: only `run_mkdocs_gh_deploy`, returning `status="published"` with no written paths and `built_path=""` (`docuharnessx/deployer/deploy.py:168-180`).

The orchestrator also has a defensive `ValueError` for any unknown mode that reaches it (`docuharnessx/deployer/deploy.py:184`).

## The pieces the orchestrator wires together

- **Workflow renderer** — `render_pages_workflow(identity, default_branch)` in `docuharnessx/deployer/workflow.py` produces the `.github/workflows/docs.yml` YAML: a `push` trigger on the target's default branch plus `workflow_dispatch` (`workflow.py:78-89`), minimal permissions `contents: read` / `pages: write` / `id-token: write` (`workflow.py:92-103`), and two jobs — a build job using `actions/checkout@v4`, `actions/setup-python@v5`, `python -m pip install mkdocs-material`, `mkdocs build --strict`, and `actions/upload-pages-artifact@v3`, plus a deploy job that `needs: build` and runs `actions/deploy-pages@v4` in the `github-pages` environment (`docuharnessx/deployer/workflow.py:106-151`). The body is deliberately target-agnostic; every per-target value stays in the assembled `mkdocs.yml` (`docuharnessx/deployer/workflow.py:154-181`).

- **Target-tree writer** — `write_target_tree` in `docuharnessx/deployer/tree.py` writes exactly three artifacts under the target repo: a verbatim copy of `site.mkdocs_yml_path` to `<target>/mkdocs.yml`, a recursive copy of `site.docs_dir` to `<target>/docs/`, and the workflow to `<target>/.github/workflows/docs.yml`, returning the three absolute paths in a fixed order (`docuharnessx/deployer/tree.py:79-137`). It is pure filesystem I/O — "Never pushes, commits, or invokes any git command" (`docuharnessx/deployer/tree.py:109-113`).

- **Command runner** — `docuharnessx/deployer/commands.py` isolates the only process-touching surface behind a `CommandRunner` protocol with a single `run(args, cwd, timeout)` method returning a frozen `CompletedResult` (`commands.py:92-131`). Production uses `DefaultCommandRunner`, which shells out via `subprocess.run` with `shell=False`, text mode, and `check=False` (`commands.py:144-171`). On top of it: `read_default_branch` reads `git symbolic-ref --short HEAD` then `git remote show origin`, degrading gracefully to `"main"` when git is missing or fails (`commands.py:179-232`); `run_mkdocs_build` runs `mkdocs build --strict --config-file <mkdocs_yml> --site-dir <built>` and raises `DeployError` on a non-zero exit or missing tooling, writing the output to a `site` subdirectory nested inside the assembled `site_dir` (`<out>/site/site/`) so the build never writes into the target repo (`commands.py:277-348`); `run_mkdocs_gh_deploy` runs `mkdocs gh-deploy --config-file <mkdocs_yml>` — the only network action — raising `DeployError` naming missing prerequisites when it fails (`commands.py:356-393`).

## The output seam and errors

The frozen data model lives in `docuharnessx/deployer/model.py`: `DeployResult` is a `@dataclass(frozen=True)` carrying `schema_version`, `mode`, `status`, `target_pages_url` (the per-target `AssembledSite.identity.site_url`, never DocuHarnessX's own), `written_paths`, `built_path`, and a one-line `detail` (`docuharnessx/deployer/model.py:87-121`). `DEPLOY_RESULT_SCHEMA_VERSION` is the single version authority, currently `1` (`docuharnessx/deployer/model.py:64`), and the error family is `DeployError` with the input-focused subclass `DeployInputError` (`docuharnessx/deployer/model.py:129-153`).

## Where it plugs into the pipeline

The actual HarnessX adapter is `DeployStage` in `docuharnessx/stages/deploy.py`, a thin wrapper over this package. On `on_step_end` it reads the `SLOT_ASSEMBLED_SITE`, `SLOT_OUTPUT_DIR`, and `SLOT_TARGET_REPO` slots through a `RunContext`, pins `ASSEMBLED_SITE_SCHEMA_VERSION`, resolves the mode via `resolve_deploy_mode`, and runs `deploy_site` with an injected `CommandRunner` (`docuharnessx/stages/deploy.py:145-198`). It then publishes the frozen `DeployResult` to `SLOT_DEPLOY_RESULT` via `run_context.set_deploy_result(result)` and journals only a bounded summary — mode, status, pages URL, written-path count, and a built flag — never page bodies (`docuharnessx/stages/deploy.py:328-345`). The package's `__init__.py` is the single public namespace re-exporting all of these symbols from the submodules (`docuharnessx/deployer/__init__.py:56-100`).
