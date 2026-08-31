---
id: tests:tests
title: How are tests organized?
subjects:
- tests
summary: 'Every test in the repository lives under a single `tests/` directory at
  the repo root. Discovery is configured in `pyproject.toml`, where the only pytest
  configuration in the project is:'
related: []
---
# How are tests organized?

# How the tests are organized

## Layout and discovery

Every test in the repository lives under a single `tests/` directory at the repo root. Discovery is configured in `pyproject.toml`, where the only pytest configuration in the project is:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
```

(`pyproject.toml:46-47`). The `dev` extra declares a single test dependency, `pytest>=8.0` (`pyproject.toml:28-30`). There is **no `conftest.py` anywhere** in the tree — I searched with `find` and found none — and `tests/` has no `__init__.py`. Shared setup is instead provided by two plain modules/directories described below.

The suite is large and flat: 112 `test_*.py` modules at the top level of `tests/` plus a dedicated `tests/ontology/` subpackage with 16 more modules; a grep for `def test_` across the tree counts 1,857 test functions, with 55 `@pytest.mark.parametrize`, 11 `@pytest.mark.skip`, and 4 `@pytest.fixture` decorators.

## Filenames mirror the package layout

The naming convention maps a test file to exactly one `docuharnessx` module or boundary:

- `tests/test_analysis_analyzer.py` → `docuharnessx/analysis/analyzer.py`
- `tests/test_mcp_session.py` → `docuharnessx/mcp/session.py`
- `tests/test_planning_planner.py` → `docuharnessx/planning/planner.py`
- `tests/test_review_judge.py` → `docuharnessx/review/judge.py`
- `tests/ontology/test_*.py` → `docuharnessx/ontology/*.py`

The one structural deviation is the `ontology` suite, which is nested in `tests/ontology/` to mirror the `docuharnessx/ontology/` package (16 modules: `test_errors.py`, `test_model.py`, `test_schema.py`, `test_store_*.py`, `test_validation*.py`, `test_vocabulary.py`, and so on). A recurring boundary variant is the package-surface suite — `test_analysis_package_surface`-style files such as `tests/test_composition_package_surface.py` — which asserts that the public namespace re-exports are *identity-equal* to their submodule definitions rather than shadow copies (`tests/test_composition_package_surface.py:24-56`).

## Shared test infrastructure (instead of conftest)

Two pieces of shared infrastructure sit at the top of `tests/`:

1. **`tests/_fakes.py`** — a test-only module for credential-free runs. Its docstring is explicit that there are no live API keys in CI, so any test that binds a model injects `FakeProvider` instead of a real provider (`tests/_fakes.py:1-8`). It exports `FakeProvider`, `RoutingFakeProvider`, `ScriptedAgentProvider`, `ScriptedReviewAgentProvider`, `ReplacementStage`, `make_replacement_stage`, `PyMkdocsNoPushRunner`, and the constants `SCRIPTED_AGENT_BODY` / `SCRIPTED_AGENT_READS` (`tests/_fakes.py:44-54`). Test modules import it both as `from _fakes import FakeProvider` (`tests/test_cli.py:34`) and as `from tests._fakes import ...` (`tests/test_mcp_session.py:36`, `tests/test_pipeline_integration.py:28`). `FakeProvider` subclasses `harnessx.providers.base.BaseModelProvider` and returns a single end-turn `ModelResponseEvent` so a real HarnessX run reaches `exit_reason='done'` with no network call (`tests/_fakes.py:57-81`).

2. **`tests/fixtures/agentic_repo/`** — a small but realistic fixture repository (`README.md`, `app.py`, `config.py`, `engine.py`, `pyproject.toml`). It is rooted in tests by `_FIXTURE_REPO = Path(__file__).parent / "fixtures" / "agentic_repo"` (`tests/test_fixture_agentic_repo.py:41`, `tests/test_pipeline_integration.py:30`, `tests/test_mcp_refine_loop_e2e.py:59`) and copied into `tmp_path` before being driven through real harness runs. `test_fixture_agentic_repo.py` is itself a unit test for the fixture: it checks that the scripted agent body's `path:line` citations (`app.py:11` → `class Application`, `engine.py:16` → `def start`, …) actually resolve to those symbols on those lines (`tests/test_fixture_agentic_repo.py:50-55`).

## Suites are anchored to spec tasks and requirement numbers

Nearly every module docstring opens by naming the SDLC task and the requirement ("Req") numbers it pins. For example:

- `tests/ontology/test_errors.py:1-10` — “Tests for the typed error and result model (task 1.2)”, covering the discriminated error types from design.md’s `errors` component.
- `tests/test_analysis_core_validation.py:1-2` — “Task 6.1 — unit-test the deterministic core against crafted fixtures.”
- `tests/test_deploy_build_e2e_5_3.py:1-35` — “Task 5.3 — build-validate a real assembled tree…”, ending with `_Requirements: 7.1, 7.2, 9.1, 9.2, 9.3, 9.4_`.
- `tests/ontology/test_store_conformance.py:1-23` — a three-part conformance/determinism/no-network suite tied to Req 9.x and 11.x.

Inside a module, banner comments (`# --- #`) group tests by contract area — e.g. “Base / discriminated-error contract”, “Config-level error (Req 1.6)”, “ValidationResult (per-segment) — Req 6.6” in `tests/ontology/test_errors.py:19-21,63-65,168-170`. Some suites go further and group tests into classes; `test_analysis_core_validation.py` publishes a coverage map naming `TestScannerEdgeCases`, `TestLanguageOrdering`, `TestSerdeContract`, `TestDetectorSignals`, and `TestEndToEndDeterminism` (`tests/test_analysis_core_validation.py:31-47`), and `test_analysis_reference_repo.py` adds `TestReferenceRepoAnalysisShape` / `TestReferenceRepoDeterminism`.

## Depth is layered: unit → integration → end-to-end

- **Unit**: one file per module, mostly pure and self-contained — small hand-built inputs and `tmp_path` for anything that reads files (`tests/test_analysis_analyzer.py:27-30`). `tests/ontology/test_model.py:67-72` shows the parametrize style: `@pytest.mark.parametrize("prefix", ["component", "tech", "artifact", "topic"])`.
- **Cross-adapter conformance**: `tests/ontology/test_store_conformance.py` runs one set of scenario bodies against *both* store adapters via `@pytest.fixture(params=["in_memory", "filesystem"])` (`tests/ontology/test_store_conformance.py:83-94`), so the same assertions exercise `InMemorySegmentStore` and `FilesystemSegmentStore` with no copy-pasted second suite.
- **Integration**: `tests/test_pipeline_integration.py:1-13` (“Pipeline integration: analyze → questions → write/gate → assemble → report”) wires the real planner, writer, and assembler together, substituting only the model.
- **End-to-end, still offline**: `tests/test_deploy_build_e2e_5_3.py` runs a *real* `mkdocs build` through a `_NoPushRealRunner` subclass of `DefaultCommandRunner` that fails loud if the orchestrator ever reaches the `gh-deploy` push (`tests/test_deploy_build_e2e_5_3.py:79-114`), guarding optional deps with `pytest.importorskip("mkdocs")` / `importorskip("material")` (`tests/test_deploy_build_e2e_5_3.py:61-62`). `tests/test_mcp_refine_loop_e2e.py:1-33` drives the whole MCP refine loop — rewrite, draft/refine overview, reassemble — over a throwaway copy of the fixture repo with `ScriptedAgentProvider`.
- **Reference repository**: `tests/test_analysis_reference_repo.py:54` defines `REFERENCE_REPO = "/home/mc/Source/malware_hashes"` and runs `scan() -> analyze()` against that real polyglot project, skipping cleanly when it is not checked out.

## Determinism and no-network/no-LLM are first-class test concerns

The suite enforces the project’s core constraints directly:

- Determinism suites assert byte-identical JSON across repeated runs — e.g. `test_analysis_core_validation.py` (“byte-stable JSON”, “byte-identical across two runs”) and `test_assembler_build_determinism.py`.
- `tests/ontology/test_store_conformance.py` imports every `docuharnessx.ontology.*` module in a fresh subprocess and asserts no network/LLM library leaks into `sys.modules` (`test_ontology_imports_no_network_or_llm_library`, line 384) and that the only third-party top-level import is `yaml` (`test_ontology_third_party_imports_limited_to_yaml`, line 415).
- `tests/test_deploy_build_e2e_5_3.py:465-484` monkeypatches `socket.socket` to prove the deploy orchestrator body opens no socket of its own.
- Robustness regressions pin that malformed inputs surface as typed `OntologyError` subclasses, never raw `ValueError` / `FileNotFoundError` (`tests/ontology/test_hardening.py:38-45`).

In short: pytest-driven, `tests/`-rooted with no conftest, one-file-per-module naming that mirrors `docuharnessx`, shared fakes + a fixture repo in place of conftest fixtures, docstrings that trace each suite to a spec task and requirement numbers, and a deliberate ladder from unit through conformance/integration to offline end-to-end runs that keeps every test credential-free and deterministic.
