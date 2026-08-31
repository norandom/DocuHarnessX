---
id: build:pyproject.toml
title: How is this project built and verified?
subjects:
- pyproject.toml
summary: The build is driven entirely by `pyproject.toml`, which is the PEP 621 metadata
  source and the only build manifest in the repo. The `[project]` table names the
  distribution `docuharnessx`, pins `version = "1.1.0"` (`pyproject.toml:2`), and
  requires `python = ">=3.12"` (`pyproject.toml:5`); the version string is mirrored
  in `docuharnessx/__init__.py:5` (`__version__ = "1.1.0"`).
related: []
---
# How is this project built and verified?

# How DocuHarnessX is built and verified

## Packaging and build

The build is driven entirely by `pyproject.toml`, which is the PEP 621 metadata source and the only build manifest in the repo. The `[project]` table names the distribution `docuharnessx`, pins `version = "1.1.0"` (`pyproject.toml:2`), and requires `python = ">=3.12"` (`pyproject.toml:5`); the version string is mirrored in `docuharnessx/__init__.py:5` (`__version__ = "1.1.0"`).

The backend is **Hatchling**:

- `[build-system]` declares `requires = ["hatchling"]` and `build-backend = "hatchling.build"` (`pyproject.toml:35-37`).
- The wheel target is restricted to the `docuharnessx` package via `[tool.hatch.build.targets.wheel] packages = ["docuharnessx"]` (`pyproject.toml:43-44`).
- Because `harnessx` is not on PyPI, the manifest enables `[tool.hatch.metadata] allow-direct-references = true` (`pyproject.toml:39-41`) so the direct-URL dependency `harnessx @ https://github.com/Darwin-Agent/HarnessX/archive/bf5f199e….tar.gz` (`pyproject.toml:11`) is legal to declare and installs reproducibly without cloning HarnessX's broken `recipe/verl_harnessX/verl` submodule (the comment at `pyproject.toml:7-10`).

The other runtime dependencies named in `[project].dependencies` (`pyproject.toml:6-25`) map directly to code: `pyyaml>=6.0` for `--config` / `ontology.yaml` parsing, `python-dotenv>=1.0` for the `.env` load in the CLI, `mkdocs>=1.6` + `mkdocs-material>=9.5` for the emitted site and `mkdocs build`, and `mcp>=1.28,<2` for the `dhx mcp` stdio server.

The one console script is the `dhx` entry point: `dhx = "docuharnessx.cli:main"` (`pyproject.toml:32-33`). The `main` function is the argparse boundary in `docuharnessx/cli.py` (imported under `__all__` at `cli.py:68-77`) and it calls `from dotenv import load_dotenv` / `load_dotenv(path, override=False)` per candidate `.env` file at CLI start (`docuharnessx/cli.py:121-126`).

## Verification

The verification contract is also declared in `pyproject.toml`: the `dev` extra adds `pytest>=8.0` (`pyproject.toml:27-30`) and `[tool.pytest.ini_options] testpaths = ["tests"]` (`pyproject.toml:46-47`) tells `pytest` where to collect. Beyond that, the tests verify the manifest *and* the built environment in several concrete ways:

**1. Tests parse the manifest itself.** `tests/test_mcp_pyproject_dep.py` and `tests/test_deployer_pyproject_deps.py` load `pyproject.toml` with `tomllib` (`_runtime_dependencies()` at `tests/test_mcp_pyproject_dep.py:33-35`, `tests/test_deployer_pyproject_deps.py:31-33`) and assert the runtime dependencies are declared exactly once with the right specifiers — e.g. `mcp` must carry a `>=1.28` floor and a `<2` upper bound (`tests/test_mcp_pyproject_dep.py:88-104`), and `mkdocs` / `mkdocs-material` must each appear once (`tests/test_deployer_pyproject_deps.py:52-67`). Those tests also confirm the *installed* environment satisfies the floor via `importlib.metadata.version` and by importing `mcp.server` (`tests/test_mcp_pyproject_dep.py:110-123`).

**2. Tests verify the built console script.** `tests/test_package_scaffold.py` checks `import docuharnessx` exposes a non-empty `__version__` (`test_package_scaffold.py:24-27`), that `dhx` is registered in `console_scripts` with value exactly `docuharnessx.cli:main` (`test_package_scaffold.py:36-42`), and that `cli.main(["--help"])` exits 0 (`test_package_scaffold.py:44-50`). The `python-dotenv` behavior is covered by `tests/test_cli_dotenv.py`, which calls `cli._load_env_files(force=True)` and asserts file values load without overriding the live environment (`tests/test_cli_dotenv.py:13-32`).

**3. Tests run real `mkdocs` builds of emitted trees.** The strict-build integration test in `tests/test_assembler_mermaid_strict_build.py:113-137` invokes `sys.executable -m mkdocs build -f <mkdocs_yml> -d <out> --strict` against a site produced by `assemble_site(...)` / `build_mkdocs_yaml` (`docuharnessx/assembler/mkdocs_config.py`, whose `pymdownx.superfences` Mermaid custom fence is enabled around `mkdocs_config.py:27`) and asserts returncode 0 with no `aborted with` / `error reading page` in the output (`test_assembler_mermaid_strict_build.py:156-236`). Production deploy validation uses the same mechanism through the isolated process seam: `run_mkdocs_build` in `docuharnessx/deployer/commands.py:291-348` builds with `mkdocs build --strict --config-file <mkdocs_yml_path> --site-dir <nested site>` and raises `DeployError` on any non-zero exit (`commands.py:342-347`); `DeployStage` reaches it via `deploy_site(...)` with the injectable `CommandRunner` / `DefaultCommandRunner` (`docuharnessx/stages/deploy.py:184-186`), and `tests/test_deployer_pyproject_deps.py:90-102` additionally proves the tooling is invocable by running `python -m mkdocs --version` as a subprocess.

**4. The fixture repo verifies its own build manifest is portable.** `tests/fixtures/agentic_repo/pyproject.toml` is a deliberately portable setuptools manifest — `build-backend = "setuptools.build_meta"` (`tests/fixtures/agentic_repo/pyproject.toml:10-12`) — whose `[project.scripts]` declares `fixture-app = "app:main"` (`tests/fixtures/agentic_repo/pyproject.toml:20-21`), matching the real `main()` in `tests/fixtures/agentic_repo/app.py:22-23`. `tests/test_fixture_agentic_repo.py` asserts the fixture keeps that contract: no file may contain a machine-specific path like `/home/` (`tests/test_fixture_agentic_repo.py:132-143`), the cited `file:line` tokens must resolve to real existing lines (`tests/test_fixture_agentic_repo.py:199-212`), and each pinned line must still contain the symbol it claims — `class Application`, `def run`, `def start`, `def load_config` — via the `_CITED_SYMBOLS` table (`tests/test_fixture_agentic_repo.py:215-226`).

In short: Hatchling builds the `docuharnessx` wheel from `pyproject.toml`, installs the `dhx` console script, and verification is `pytest` over `tests/` (per `testpaths`) plus a battery of tests that re-read the manifest with `tomllib`, check the installed distributions and entry points, and run genuine strict `mkdocs build` subprocesses against assembled sites to prove the emitted output is buildable.
