---
id: tests:tests
title: How are tests organized?
subjects:
- tests
summary: All tests for DocuHarnessX live in a single `tests/` directory at the repository
  root. The only pytest configuration in the project is `pyproject.toml:46-47`, which
  sets `testpaths = ["tests"]`, and the dev extra declares the sole test dependency
  `pytest>=8.0` (`pyproject.toml:28-29`). There is no `conftest.py` anywhere in the
  tree, and `tests/` has no `__init__.py`; the top level contains 127 `test_*.py`
  modules plus two support entries — `tests/_fakes.py` and the `tests/fixtures/` directory
  — and one nested subdirectory, `tests/ontology/`, holding 16 more modules.
related: []
cited_files:
- pyproject.toml
- tests/test_ontology_loader.py
- tests/test_ontology_setup.py
- tests/test_deploy_build_e2e_5_3.py
- tests/ontology/test_package_import.py
- tests/_fakes.py
- tests/test_cli_e2e.py
- tests/test_mcp_session.py
- tests/test_pipeline_run.py
- tests/test_fixture_agentic_repo.py
- tests/ontology/test_errors.py
- tests/ontology/test_store_conformance.py
- tests/ontology/test_model.py
- tests/test_composition_package_surface.py
- tests/test_mcp_package_surface.py
- tests/test_pipeline_integration.py
- tests/test_mcp_refine_loop_e2e.py
- tests/test_analysis_reference_repo.py
- tests/test_written_segments_seam.py
- docuharnessx/cli.py
- tests/test_guardrails_no_rl.py
---
# How are tests organized?

All tests for DocuHarnessX live in a single `tests/` directory at the repository root. The only pytest configuration in the project is `pyproject.toml:46-47`, which sets `testpaths = ["tests"]`, and the dev extra declares the sole test dependency `pytest>=8.0` (`pyproject.toml:28-29`). There is no `conftest.py` anywhere in the tree, and `tests/` has no `__init__.py`; the top level contains 127 `test_*.py` modules plus two support entries — `tests/_fakes.py` and the `tests/fixtures/` directory — and one nested subdirectory, `tests/ontology/`, holding 16 more modules.

## Filenames mirror the `docuharnessx` module layout

The naming convention is one test file per package module or boundary, and the prefixes form recognizable groups. The suite contains 14 `planning` files, 14 `composition`, 14 `mcp`, 14 `assembler` (plus `test_assembled_site_seam.py`), 12 `analysis`, 9 `review`, 8 `cli`, 8 `deployer`/`deploy`, 4 `pipeline`, and 4 top-level `ontology_*` files, with one-offs such as `test_config.py`, `test_context.py`, `test_model_resolver.py`, and `test_pages_model.py`.

Each file's docstring names the exact boundary it pins. `tests/test_ontology_loader.py:1-9` opens with "Run-start ontology loading tests for task 2.6 (OntologyLoader boundary)" and documents that it owns `docuharnessx/ontology_loader.py` and the single public function `load_project_vocabulary(project_dir)`. `tests/test_ontology_setup.py:1-10` similarly pins `run_init` in `docuharnessx/ontology_setup.py`, and `tests/test_validation.py:1-7` says it covers `validate_segment` from `docuharnessx/ontology/validation.py`. The e2e file `tests/test_deploy_build_e2e_5_3.py:1-3` identifies itself as "the github-pages-deploy *task 5.3* deliverable."

## `tests/ontology/` is the one nested mirror

The single structural deviation from the flat layout is `tests/ontology/`, which mirrors `docuharnessx/ontology/` module-for-module: `test_errors.py`, `test_model.py`, `test_schema.py`, `test_serializer.py`, `test_vocabulary.py`, `test_validation.py`, `test_validation_set.py`, `test_tags.py`, `test_views.py`, plus store suites `test_store_inmemory.py`, `test_store_filesystem.py`, and the shared `test_store_conformance.py`. The scaffold tests `tests/ontology/test_package_import.py:11-22` assert only that `docuharnessx.ontology` is an importable package (`hasattr(ontology, "__path__")`), while `test_public_api.py` iterates `docuharnessx.ontology.__all__` to check every exported name is usable. The two store suites are task-scoped: `test_store_inmemory.py:1-3` tests the frozen `SegmentStore` port and `InMemorySegmentStore` ("task 4.1"), and `test_store_filesystem.py:1-3` tests `FilesystemSegmentStore` ("task 4.2").

## Shared infrastructure replaces conftest

Because there is no `conftest.py`, shared setup comes from two plain modules:

1. **`tests/_fakes.py`** — test-only fakes for credential-free runs. Its docstring states "There are no live API keys in CI, so any test that binds a model (or actually runs the harness) injects `FakeProvider` instead of a real provider" (`tests/_fakes.py:1-8`). Its `__all__` (`tests/_fakes.py:44-54`) exports `FakeProvider`, `RoutingFakeProvider`, `ScriptedAgentProvider`, `ScriptedReviewAgentProvider`, `ReplacementStage`, `make_replacement_stage`, `PyMkdocsNoPushRunner`, and constants `SCRIPTED_AGENT_BODY` / `SCRIPTED_AGENT_READS`. `FakeProvider` subclasses `harnessx.providers.base.BaseModelProvider` (`tests/_fakes.py:57`) and returns a single end-turn `ModelResponseEvent`, so a real HarnessX run loop reaches `exit_reason='done'` without a network call. Because `tests/` has no `__init__.py`, both import spellings work and appear in the suite: `from _fakes import FakeProvider` in `tests/test_cli_e2e.py:18`, and `from tests._fakes import FakeProvider` in `tests/test_mcp_session.py:36` and `tests/test_pipeline_run.py:26` (resolved via namespace package).

2. **`tests/fixtures/agentic_repo/`** — a small realistic fixture repository (`README.md`, `app.py`, `config.py`, `engine.py`, `pyproject.toml`). Test files root it as `_FIXTURE_REPO = Path(__file__).parent / "fixtures" / "agentic_repo"` (`tests/test_fixture_agentic_repo.py:41`) and copy it into `tmp_path` with `shutil.copytree(_FIXTURE_REPO, dest)` (`tests/test_fixture_agentic_repo.py:96-97`) before driving real HarnessX runs over it. That file doubles as a unit test of the fixture itself, checking that scripted-body `path:line` citations resolve to real fixture symbols.

## Suites are anchored to spec tasks and requirement numbers

Module docstrings open by naming the SDLC task and the "Req" numbers they pin. `tests/ontology/test_errors.py:1-10` starts "Tests for the typed error and result model (task 1.2)" and lists the discriminated error types from design.md's `errors` component. `tests/ontology/test_store_conformance.py:1-13` describes itself as the "cross-adapter conformance and reproducibility gate" in three parts: parametrized store conformance, determinism, and a no-network/no-LLM import check. Inside modules, `# ---- #` banner comments group tests by contract area — for example "Base / discriminated-error contract", "Config-level error (Req 1.6)", and "ValidationResult (per-segment) — Req 6.6" in `tests/ontology/test_errors.py:19-21,63-65,168-170`. 112 of the test modules reference "Req" somewhere. Some suites group further into classes: `tests/test_analysis_core_validation.py` defines `TestScannerEdgeCases` (line 193), `TestLanguageOrdering` (316), `TestSerdeContract` (458), `TestDetectorSignals` (506), and `TestEndToEndDeterminism` (612).

## Depth is layered: unit → package surface → conformance → integration → offline e2e

- **Unit**: one file per module using `tmp_path` for file-touching tests, and `pytest.mark.parametrize` where convenient — e.g. `@pytest.mark.parametrize("prefix", ["component", "tech", "artifact", "topic"])` over `Subject.parse` in `tests/ontology/test_model.py:67-72`.
- **Package-surface boundary**: recurring `test_*_package_surface.py` suites assert that a package root re-exports its public surface identity-equal to submodule definitions. `tests/test_composition_package_surface.py:1-14` requires every re-export (e.g. `build_blueprint`, `generate_prose`, `WrittenSegments`) to be "identity-equal to its submodule definition (no shadow copies)", mirroring `docuharnessx.planning.__init__`; the MCP variant, `tests/test_mcp_package_surface.py:1-15`, pins the `docuharnessx.mcp` package as the single public namespace.
- **Cross-adapter conformance**: `tests/ontology/test_store_conformance.py:83-94` runs one set of scenario bodies against both store adapters via `@pytest.fixture(params=["in_memory", "filesystem"])`, yielding a fresh `InMemorySegmentStore` or a `tmp_path`-backed `FilesystemSegmentStore`, so the same assertions exercise both adapters with no copy-pasted second suite.
- **Integration**: `tests/test_pipeline_integration.py:1-14` wires the real planner, writer (substance gate inside), and `assemble_question_site` for the `PipelineRunner` boundary; `tests/test_pipeline_run.py` substitutes only the model provider.
- **End-to-end, still offline**: `tests/test_deploy_build_e2e_5_3.py:60-62` guards optional deps with `pytest.importorskip("mkdocs")` / `importorskip("material")`, then runs a *real* `mkdocs build` through `_NoPushRealRunner`, a `DefaultCommandRunner` subclass (line 79) that "fails loud if ever asked to push." `tests/test_mcp_refine_loop_e2e.py:1-14` drives the whole MCP refine loop — rewrite, overview draft/refine, reassemble — over a throwaway copy of `tests/fixtures/agentic_repo` with `ScriptedAgentProvider`. `tests/test_cli_e2e.py:1-6` runs the real `dhx` CLI with `FakeProvider` injected.
- **Reference repository**: `tests/test_analysis_reference_repo.py:54` sets `REFERENCE_REPO = "/home/mc/Source/malware_hashes"` and runs `scan()` → `analyze()` against that real polyglot project, skipping cleanly when it is absent (lines 83-84).
- **Seam/regression**: files named `*_seam.py` (`test_assembled_site_seam.py`, `test_review_report_seam.py`, `test_written_segments_seam.py`, `test_deploy_result_seam.py`) pin append-only slot-key constants and `get_slot`/`set_slot` accessors — `tests/test_written_segments_seam.py:56-69` asserts the `SLOT_WRITTEN_SEGMENTS` key exists with a pinned value and is exported. `tests/test_mcp_regression_seams_6_2.py` is a cross-feature diff-boundary suite that asserts the MCP-refine feature stayed inside its declared blast radius vs `HEAD`.

## Determinism and no-network/no-LLM are first-class concerns

The suite enforces the project's constraints directly. The CLI's env loader refuses to load `.env` files while pytest is running — `docuharnessx/cli.py:132` returns early when `os.environ.get("PYTEST_CURRENT_TEST")` is set, "so the credential-free suite cannot pick up a developer's local secrets." `tests/ontology/test_store_conformance.py:27-30` describes part 3 of that module as re-importing every `docuharnessx.ontology.*` module in a fresh subprocess to assert no network/LLM library leaks in (the only permitted third-party import is `yaml`). `tests/test_guardrails_no_rl.py:11-13` pins that `make_question_id` rejects role-intent-shaped ids (`"developer__extend"` → `ValueError` matching `reader-role`) and that `docuharnessx` never imports `harnessx.rl`.

In short: pytest-driven with `testpaths = ["tests"]`, no `conftest.py`, one-file-per-module naming that mirrors `docuharnessx` (with `tests/ontology/` as the only nested mirror), shared fakes (`tests/_fakes.py`) and a fixture repo (`tests/fixtures/agentic_repo`) in place of conftest fixtures, docstrings tracing each suite to a spec task and requirement numbers, and a deliberate ladder from unit through package-surface/conformance/integration to offline end-to-end runs that keeps every test credential-free and deterministic.