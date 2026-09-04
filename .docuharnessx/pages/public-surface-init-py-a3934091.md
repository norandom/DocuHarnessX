---
id: public_surface:__init__.py
title: How is the public surface used or extended?
subjects:
- __init__.py
summary: The package keeps the root `__init__.py` deliberately thin and pushes the
  real public surface down into subpackage `__init__.py` modules, which act as single
  namespaces whose `__all__` is treated as an authoritative, test-policed contract.
related: []
cited_files:
- docuharnessx/__init__.py
- tests/test_package_scaffold.py
- docuharnessx/mcp/__init__.py
- docuharnessx/analysis/__init__.py
- docuharnessx/ontology/__init__.py
- docuharnessx/planning/__init__.py
- docuharnessx/stages/base.py
- docuharnessx/_ontology.py
- tests/test_planning_package_surface.py
- tests/test_mcp_launcher.py
- tests/test_analysis_detectors_components_surface.py
- tests/_fakes.py
---
The package keeps the root `__init__.py` deliberately thin and pushes the real public surface down into subpackage `__init__.py` modules, which act as single namespaces whose `__all__` is treated as an authoritative, test-policed contract.

## The root exposes one symbol and nothing else

`docuharnessx/__init__.py` contains only the module docstring, `__version__ = "2.0.0"` (`docuharnessx/__init__.py:5`), and `__all__ = ["__version__"]` (`docuharnessx/__init__.py:7`). The only in-tree consumer of that root symbol is `docuharnessx/hooks.py`, which imports it at module scope — `from docuharnessx import __version__` (`hooks.py:12`) — and uses it to build the git-ref pin rendered into consumer hook configs: `return f"v{__version__}"` (`hooks.py:44`), which flows into `render_consumer_pre_commit_config`/`render_git_pre_commit_script`. The scaffold contract for the root is pinned by `tests/test_package_scaffold.py`, which imports the package via `importlib.import_module("docuharnessx")` and asserts `pkg.__version__` is a non-empty string (`tests/test_package_scaffold.py:24`), and also asserts the `dhx` console script resolves to `docuharnessx.cli:main` (`tests/test_package_scaffold.py:36`).

## Subpackage `__init__.py` files are the real public surface

The design intent is stated repeatedly in the package roots: downstream consumers should "import from a single namespace … rather than reaching into private submodules," with `__all__` as "the authoritative, self-consistent contract" (`docuharnessx/mcp/__init__.py:20-23`, `:44-46`). Each package root re-exports names from its private modules verbatim — identity-equal, "no shadow copies" — e.g. `docuharnessx/analysis/__init__.py:33-82` re-exports `analyze`, the detector functions (`detect_public_surface`, `map_components`, …), the frozen model records (`RepoAnalysis`, `PublicSymbol`, …), the serde functions (`to_dict`/`from_dict`/`to_json`), and the scanner (`scan`, `FileInventory`), then lists them in `__all__` at `docuharnessx/analysis/__init__.py:84-127`. The same pattern appears in `docuharnessx/ontology/__init__.py:7-13` ("the stable public API surface … importable directly from here verbatim") and in `docuharnessx/planning/__init__.py:13-16` ("single public namespace … rather than reaching into submodules").

This is a two-sided convention. Production modules consume the namespace surface: `AnalyzeStage` does `from docuharnessx.analysis import analyze, enrich` (`stages/analyze.py:63`); `docuharnessx/stages/base.py:187` lazily does `from docuharnessx.stages import stage_class_for`; the CLI's `dhx mcp` path imports `resolve_session` and `run_stdio` off the package root (`cli.py:865`, `cli.py:880`); and the contract shim `docuharnessx/_ontology.py:50-58` imports `SegmentStore`, `Vocabulary`, `load_vocabulary`, etc. from `docuharnessx.ontology`. Tests police the same contract from the other side: `tests/test_planning_package_surface.py:38-55` asserts re-exports are the same objects as their modules (`pkg.classify_repo is classifier.classify_repo`, `pkg.CoveragePlan is model.CoveragePlan`, `pkg.to_dict is serde.to_dict`), that every `__all__` name resolves with no duplicates (`test_planning_package_surface.py:86-92`), and that `from docuharnessx.planning import *` binds exactly the `__all__` set (`test_planning_package_surface.py:95-101`). `tests/test_mcp_launcher.py:36-51` defines a `_PUBLIC_SURFACE` set and checks it is a subset of `pkg.__all__`, with identity checks like `pkg.run_stdio is server.run_stdio` (`test_mcp_launcher.py:95-101`). Even the detectors' own tests assert the task-3.3 functions are both in `docuharnessx.analysis.detectors.__all__` and re-exported from the `docuharnessx.analysis` package root (`tests/test_analysis_detectors_components_surface.py:116-136`).

## The surface is extended additively, both by re-export and by behavior

Two kinds of extension appear in the source. First, additive re-export: the `__init__.py` docstrings record that later tasks "add" names to a namespace, each time growing the `__all__` contract — e.g. `analysis/__init__.py:15-28` traces tasks 1.2/2.2/3.1-3.3/4.1/4.2 adding serde, language, detector, and enrichment symbols, and `mcp/__init__.py:66-73` lists which tasks add `RefineSession`, `planned_from_segment`, the handlers, and `build_refine_server`/`run_stdio`.

Second, `docuharnessx/stages/__init__.py` is a package root that *executes* rather than just re-exports: it defines `STAGES` as an ordered `(StageName, factory)` list in canonical pipeline order (`stages/__init__.py:60-69`), `register_stages(builder)` which appends each stage's processor onto `PIPELINE_HOOK` with strictly positive `order` — "append-don't-replace," leaving any pre-existing hook processors ahead of the stages (`stages/__init__.py:108-132`) — and `stages_builder()` as a stages-only builder meant for `|` composition (`stages/__init__.py:135-148`). That behavior surface is consumed at the composition seam: `bundle.py:53` imports `from docuharnessx.stages import stages_builder`, and `make_docgen` composes `builder: HarnessBuilder = control | stages_builder()` (`bundle.py:131`). Extension-by-swap is explicitly modeled in `tests/_fakes.py`, whose `ReplacementStage`/`make_replacement_stage` are "a genuine, importable alternative stage processor (and its factory) a later spec could drop into `docuharnessx.stages.STAGES` in place of one no-op stub" (`tests/_fakes.py:20-27`, `:87-117`).

One further extension wrinkle is documented in `docuharnessx/_ontology.py:17-25`: because a top-level module can never shadow a same-named package, `import docuharnessx.ontology` "always loads the package's `__init__.py`"; the skeleton therefore keeps `_ontology.py` as a separate contract-level re-export shim so its own imports cannot collide with the ontology package root. In short, the public surface is consumed as a version constant and as per-package namespaces, and it is extended by editing each `__init__.py`'s re-export list/`__all__`, by behavior added inside `stages/__init__.py`, and by tests that freeze the contract (identity equality, star-import equality, and `__all__` self-consistency).