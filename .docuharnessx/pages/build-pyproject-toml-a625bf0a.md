---
id: build:pyproject.toml
title: How is this project built and verified?
subjects:
- pyproject.toml
summary: 'The build is declared entirely in the root `pyproject.toml`. The package
  is built with **hatchling** rather than setuptools: `pyproject.toml:35-37` sets
  `requires = ["hatchling"]` and `build-backend = "hatchling.build"`, and `pyproject.toml:43-44`
  restricts the wheel to `packages = ["docuharnessx"]`. It requires Python `>=3.12`
  (`pyproject.toml:5`).'
related: []
cited_files:
- pyproject.toml
- docuharnessx/cli.py
- tests/fixtures/agentic_repo/pyproject.toml
- tests/test_deployer_pyproject_deps.py
- tests/test_mcp_pyproject_dep.py
- tests/test_fixture_agentic_repo.py
- README.md
---
# How DocuHarnessX is built and verified

## Build

The build is declared entirely in the root `pyproject.toml`. The package is built with **hatchling** rather than setuptools: `pyproject.toml:35-37` sets `requires = ["hatchling"]` and `build-backend = "hatchling.build"`, and `pyproject.toml:43-44` restricts the wheel to `packages = ["docuharnessx"]`. It requires Python `>=3.12` (`pyproject.toml:5`).

The distributable artifact is a console script, not just a library. `pyproject.toml:32-33` maps `dhx = "docuharnessx.cli:main"`, where `docuharnessx/cli.py` builds an `argparse` parser with subcommands `run`, `init`, `mcp`, `status`, `sufficient`, `evolve`, `hook`, `ci`, `install-hooks`, and `install-ci` (`docuharnessx/cli.py:98-111`); the module ends with `raise SystemExit(main())` under `__main__` so `python -m docuharnessx.cli` works too.

Two build details exist purely to make the dependency graph installable:

- `harnessx` is not on PyPI, so it is pinned as a direct-URL commit archive — `pyproject.toml:11` lists `harnessx @ https://github.com/Darwin-Agent/HarnessX/archive/bf5f199e....tar.gz` — and `pyproject.toml:39-41` enables `allow-direct-references = true` under `[tool.hatch.metadata]` so hatchling accepts that PEP 508 direct reference. The in-tree comment at `pyproject.toml:6-11` explains the pin avoids the broken `recipe/verl_harnessX/verl` submodule.
- The rest of the runtime deps (`pyyaml`, `python-dotenv`, `mkdocs`, `mkdocs-material`, `mcp>=1.28,<2`) are normal specifiers in `[project].dependencies` (`pyproject.toml:12-24`).

The second evidence `pyproject.toml` — `tests/fixtures/agentic_repo/pyproject.toml` — is deliberately a different, more old-school build: it uses `setuptools>=61` with `build-backend = "setuptools.build_meta"` (`tests/fixtures/agentic_repo/pyproject.toml:10-12`) and a `fixture-app = "app:main"` entry point (`tests/fixtures/agentic_repo/pyproject.toml:20-21`). Its header comment stresses it must stay portable (no machine-specific absolute paths) because the fake-agent tests root a read-only workspace there in CI.

## Verification

Unit verification is pytest, configured in the same file: the `dev` extra declares `pytest>=8.0` (`pyproject.toml:27-30`) and `[tool.pytest.ini_options]` sets `testpaths = ["tests"]` (`pyproject.toml:46-47`). Several tests verify the build metadata itself by parsing `pyproject.toml` at test time:

- `tests/test_deployer_pyproject_deps.py:26-33` loads the root `pyproject.toml` with `tomllib` and asserts `mkdocs` and `mkdocs-material` are declared exactly once, that no dependency is duplicated, and — offline — that the resolved environment carries them and that `python -m mkdocs --version` succeeds (`tests/test_deployer_pyproject_deps.py:90-101`).
- `tests/test_mcp_pyproject_dep.py:27-35` does the same for `mcp`, asserting the direct declaration has a `>=1.28` floor and a `<2` cap (`tests/test_mcp_pyproject_dep.py:88-104`) and that `import mcp.server` works against the installed distribution (`tests/test_mcp_pyproject_dep.py:118-123`).
- `tests/test_fixture_agentic_repo.py:119-129` checks the fixture repo has its build manifest, entrypoint, and source modules, and `tests/test_fixture_agentic_repo.py:132-143` rejects any `/home/...` absolute path in the fixture so it stays deterministic across machines.

End-to-end verification runs through the GitHub Actions in `.github/workflows`. `dhx.yml` dogfoods the reusable workflow on this repository: it calls `./.github/workflows/adopt.yml` with `source: checkout` (`dhx.yml:17-22`). The `docs` job of `adopt.yml` then executes the CLI's CI path in a clean environment:

```bash
uvx --python 3.12 --from . dhx ci .    # adopt.yml:76
```

(`source: git` would instead run `uvx ... --from "git+https://github.com/norandom/DocuHarnessX.git@${DHX_REF}" dhx ci .`, `adopt.yml:78`.) On the CLI side, `_ci_command` (`docuharnessx/cli.py:1272`) skips bot/`[dhx]` commits and keyless runs, then calls `_generate_docs` (`docuharnessx/cli.py:1240`), which drives the run pipeline with `deploy_mode="emit-ci-workflow"` (`docuharnessx/cli.py:1248`) — i.e. it assembles `docs/` plus `mkdocs.yml` into the target tree. When MkDocs itself must be run from a generated site, the publish path uses `_PythonMkdocsRunner`, which rewrites a `mkdocs` argv entry into `sys.executable -m mkdocs` so the venv package is used even when no console script is on `PATH` (`docuharnessx/cli.py:715-720`). `adopt.yml:80-98` then commits the resulting `docs`, `mkdocs.yml`, `.docuharnessx`, and `.github/workflows/docs.yml` paths with a `[dhx] update living docs and MkDocs` message.

Static-site deployment is verified separately by `.github/workflows/docs.yml`: it installs `mkdocs-material` (`docs.yml:22-24`), runs `mkdocs build --strict` (`docs.yml:26`) — strict mode fails the build on any MkDocs warning — uploads the `site` artifact (`docs.yml:28-30`), and deploys with `actions/deploy-pages@v4` (`docs.yml:38-40`).

For consumers, the project distributes CI by generation: `dhx install-ci` writes a `.github/workflows/dhx.yml` into the target repo (`docuharnessx/cli.py:1420-1430` dispatches to `install_ci_workflow`), and the reusable `adopt.yml` documents that install path in its header (`adopt.yml:2-12`). Local install follows the same Python 3.12 + uv story: `uv pip install -e .` after creating a venv, per `README.md:33-38`, or `uvx --python 3.12 --from git+... dhx` for a no-clone run (`README.md:12`).