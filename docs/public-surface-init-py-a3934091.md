---
id: public_surface:__init__.py
title: How is the public surface used or extended?
subjects:
- __init__.py
summary: 'The root `docuharnessx/__init__.py` is deliberately tiny: it defines only
  the version constant and advertises exactly that one name.'
related: []
---
# How is the public surface used or extended?

## The public surface of `docuharnessx/__init__.py`: a minimal root, extended through single-namespace subpackages

The root `docuharnessx/__init__.py` is deliberately tiny: it defines only the version constant and advertises exactly that one name.

```python
__version__ = "1.1.0"
__all__ = ["__version__"]
```

(`docuharnessx/__init__.py:5-7`). The string matches the distribution version in `pyproject.toml` (`version = "1.1.0"`, `pyproject.toml:3`), so the root surface is a version marker rather than an API hub. Nothing else — no pipeline, config, CLI, or model symbols — is re-exported at the root, and the `dhx` entry point is registered separately as a console script pointing at `docuharnessx.cli:main` (`pyproject.toml:33`). The scaffold test pins this contract: `test_docuharnessx_imports_and_has_version` asserts `import docuharnessx` yields a non-empty `__version__` (`tests/test_package_scaffold.py:24-27`), and `test_dhx_console_script_is_registered` asserts the `dhx` entry point resolves to `docuharnessx.cli:main` (`tests/test_package_scaffold.py:36-41`).

### Where the real public surface lives

The actual API is pushed down into each subpackage's `__init__.py`, which acts as the **single public namespace** for that core. The pattern is spelled out in the package docstrings: downstream consumers "import from the single `docuharnessx.analysis` namespace rather than reaching into submodules" (`docuharnessx/analysis/__init__.py:10-13`). `docuharnessx/analysis/__init__.py` re-exports the frozen seam — `RepoAnalysis`, `REPO_ANALYSIS_SCHEMA_VERSION`, the `AnalysisError` hierarchy, the serde trio `from_dict`/`to_dict`/`to_json`, the language functions `detect_language`/`aggregate_languages`, every detector (`summarize_structure`, `detect_entrypoints`, `detect_public_surface`, `map_components`, …), the scanner (`scan`, `FileInventory`, `DEFAULT_EXCLUDED_DIRS`), and the two entry points `analyze` and `enrich` (`docuharnessx/analysis/__init__.py:33-82`) — with `__all__` listed as "the authoritative, self-consistent contract for the package" (`docuharnessx/analysis/__init__.py:84-127`). The sibling cores repeat the exact same idiom: `docuharnessx/planning/__init__.py`, `docuharnessx/assembler/__init__.py`, `docuharnessx/composition/__init__.py`, `docuharnessx/ontology/__init__.py`, `docuharnessx/pipeline/__init__.py`, and `docuharnessx/pages/__init__.py` all re-export identity-equal names from private submodules and publish an `__all__`.

The ontology package is the sharpest example of the pattern's constraints. `docuharnessx/_ontology.py` is a shim whose docstring explains that `ontology-engine` owns the `docuharnessx/ontology/` directory, and because "Python resolves a *package* over a same-named top-level *module*", a literal `docuharnessx/ontology.py` would be permanently shadowed — so `_ontology.py` is the single contract-level re-export site, importing `SegmentStore`, `AxisFilter`, `Segment`, `Vocabulary`, `load_vocabulary`, `vocabulary_to_config`, and `default_profile` **from the `docuharnessx.ontology` package** (`docuharnessx/_ontology.py:17-25`, `docuharnessx/_ontology.py:50-58`). That is the public surface being consumed as a frozen contract seam, with the docstring even naming the revalidation trigger for any engine drift (`docuharnessx/_ontology.py:42-46`).

### How the surface is used

- **Tests assert the surface, not just the submodules.** `tests/test_analysis_detectors_components_surface.py` verifies the re-export contract directly: `test_task33_detectors_reexported_from_package` imports `docuharnessx.analysis` and asserts each detector name is both present on the package and listed in `pkg.__all__` (`tests/test_analysis_detectors_components_surface.py:127-136`); it also checks the names exist callable on the `detectors` module and in that module's `__all__` (`tests/test_analysis_detectors_components_surface.py:104-125`).
- **Internal modules import from the namespace, including lazily to break cycles.** `cli.py` exposes `resolve_session` as a module-level wrapper precisely because `docuharnessx.mcp.session` imports `_validate_target_repo` *from `cli.py`*; the real import is deferred to call time: `from docuharnessx.mcp import resolve_session as _resolve_session` (`docuharnessx/cli.py:690-701`), and `_run_stdio_blocking` likewise defers `from docuharnessx.mcp import run_stdio` (`docuharnessx/cli.py:704-716`). Exposing these as module-level names is explicitly so tests can monkeypatch `cli.resolve_session` / `cli._run_stdio_blocking` (`docuharnessx/cli.py:696-697`, `docuharnessx/cli.py:711-713`).
- **The CLI is the outermost consumer of the subpackage surfaces.** `cli.py`'s own `__all__` names `build_parser`, `main`, `prepare_run`, `PreparedRun`, `orchestrate_run`, `RunOutcome`, `exit_code_for_reason`, and `resolve_session` (`docuharnessx/cli.py:68-77`). `orchestrate_run` aliases the pipeline entry point `from docuharnessx.pipeline.run import run_pipeline as run_explore_pipeline` (`docuharnessx/cli.py:601`), and `_publish_if_accepted` imports `resolve_site_identity`, `AssembledSite`, `deploy_site`, and `resolve_deploy_mode` from the assembler/deployer namespaces (`docuharnessx/cli.py:547-549`).

### How the surface is extended

Extension is **additive and namespace-append-only**. The `analysis` docstring walks the accretion: the frozen seam (task 1.1), the error hierarchy (1.5), serde (1.2), languages (2.2), detectors (3.1–3.3), the `analyze` composition (4.1), and finally the gated `enrich` surface added "to this same package additively: the only place a model may touch the analysis" (`docuharnessx/analysis/__init__.py:13-28`). The `mcp` docstring says the same: "later tasks populate it as each module lands, each re-export identity-equal to its submodule definition (no shadow copies)" (`docuharnessx/mcp/__init__.py:25-30`), and its `__all__` lists the eight tool handlers (`list_segments`, `get_segment`, `validate_segment`, `rewrite_segment`, `reassemble_site`, `get_overview`, `draft_overview`, `refine_overview`) plus `build_refine_server`/`run_stdio` (`docuharnessx/mcp/__init__.py:74-89`). The `assembler` docstring likewise enumerates which task populated which re-export (`docuharnessx/assembler/__init__.py:20-33`).

`docuharnessx/stages/__init__.py` is a different kind of extension: it *extends HarnessX's builder* rather than the Python namespace. `STAGES` is the ordered `(StageName, factory)` list in canonical pipeline order (`docuharnessx/stages/__init__.py:60-69`), `register_stages` appends each stage processor onto `PIPELINE_HOOK` with strictly positive, increasing `order` — "append-don't-replace" semantics that keep pre-existing hook processors ahead of the eight stages (`docuharnessx/stages/__init__.py:108-132`) — and `stages_builder` returns a stages-only `HarnessBuilder` for `|` composition (`docuharnessx/stages/__init__.py:135-148`). The extension contract is exercised by `tests/_fakes.py`, where `ReplacementStage` / `make_replacement_stage` model "a genuine, importable alternative stage processor (and its factory) a later spec could drop into `docuharnessx.stages.STAGES`" (`tests/_fakes.py:20-26`, `tests/_fakes.py:87-117`).

Finally, the CLI surface itself is extended in `cli.py` as new subcommands land: `_SUBCOMMANDS` is the frozenset `{"run", "init", "mcp"}` used by the bare-form normalizer (`docuharnessx/cli.py:97`), `build_parser` adds the three subparsers plus flags such as `--deploy-mode` (`docuharnessx/cli.py:185-328`), and `main` dispatches each command (`docuharnessx/cli.py:1085-1092`). In every case the root `__init__.py` stays untouched — the pattern is: keep the root to `__version__`, and grow the public surface by adding identity-equal re-exports to the per-core subpackage namespaces, verified by tests that check both `hasattr` and `__all__` membership.
