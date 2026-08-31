---
id: component:analysis
title: What does analysis do?
subjects:
- analysis
summary: '`docuharnessx.analysis` is the pure, model-free repository-scanning and
  analysis core of DocuHarnessX. Its own docstring says it "turns a target repository
  on local disk into a frozen `RepoAnalysis`" and is "deterministic, side-effect-free...
  stdlib-only and unit-testable without any harness" (`docuharnessx/analysis/__init__.py:1-7`).
  Everything downstream — the HarnessX stages and the classification-coverage-planner
  — consumes the single frozen `RepoAnalysis` value object, which is why the package
  re-exports `RepoAnalysis`, its nested record types, `REPO_ANALYSIS_SCHEMA_VERSION`,
  the serde functions (`to_dict`/`from_dict`/`to_json`), the scanner, the detectors,
  and `enrich` from one namespace (`docuharnessx/analysis/__init__.py:33-82`).'
related: []
---
# What does analysis do?

## What `docuharnessx.analysis` does

`docuharnessx.analysis` is the pure, model-free repository-scanning and analysis core of DocuHarnessX. Its own docstring says it "turns a target repository on local disk into a frozen `RepoAnalysis`" and is "deterministic, side-effect-free... stdlib-only and unit-testable without any harness" (`docuharnessx/analysis/__init__.py:1-7`). Everything downstream — the HarnessX stages and the classification-coverage-planner — consumes the single frozen `RepoAnalysis` value object, which is why the package re-exports `RepoAnalysis`, its nested record types, `REPO_ANALYSIS_SCHEMA_VERSION`, the serde functions (`to_dict`/`from_dict`/`to_json`), the scanner, the detectors, and `enrich` from one namespace (`docuharnessx/analysis/__init__.py:33-82`).

### 1. Scan the repo into an inventory

Before analysis there is scanning. `docuharnessx.analysis.scanner` walks a target directory into a bounded, classified, deterministically-sorted `FileInventory` (`docuharnessx/analysis/scanner.py:3-6`). For each retained file it records the repo-relative POSIX path, byte size, a binary-vs-text classification from an 8 KiB head sample, a coarse language tag, a line count (0 for binary/over-cap files), and a `read_truncated` flag (`docuharnessx/analysis/scanner.py:11-19`). Boundedness comes from `ScanLimits`, whose defaults are `max_file_bytes=1_000_000`, `max_total_files=50_000`, `max_total_bytes=500_000_000`, plus an `excluded_dirs` set that skips `.git`, `node_modules`, `venv`, `__pycache__`, `dist`, and friends without descending (`docuharnessx/analysis/scanner.py:60-84`, `docuharnessx/analysis/scanner.py:99-102`).

### 2. Compose inventory → `RepoAnalysis`

The single composition layer is `analyze(inv: FileInventory) -> RepoAnalysis` (`docuharnessx/analysis/analyzer.py:84`). It "owns *assembly only*" and "performs **no** model call and **no** network access" (`docuharnessx/analysis/analyzer.py:7-12`). In order it:

- derives `total_files` and `total_loc` directly from the inventory entries (`docuharnessx/analysis/analyzer.py:115-116`);
- runs `aggregate_languages(entries)` from the language layer, which folds `.language`/`.loc` into `LanguageStat` records sorted by LOC descending then name ascending, plus the primary languages tied for max LOC (`docuharnessx/analysis/analyzer.py:110`, `docuharnessx/analysis/languages.py:17-21`);
- calls the inventory-only detectors — `summarize_structure`, `detect_entrypoints`, `detect_build_files`, `detect_ci`, `detect_tests`, `map_components`, `detect_docs`, `detect_artifacts` (`docuharnessx/analysis/analyzer.py:119-126`);
- calls the two file-reading detectors, `extract_dependencies_with_notes(inv, repo_path)` and `detect_public_surface(inv, repo_path)` (`docuharnessx/analysis/analyzer.py:129-130`);
- folds the dependency parser's "partially parsed" notes into `ScanStats.notes` via `_merge_notes` (sorted + deduplicated union) while carrying every other counter through unchanged (`docuharnessx/analysis/analyzer.py:72-81`, `docuharnessx/analysis/analyzer.py:134-140`);
- returns a `RepoAnalysis` with `enrichment=None` — a complete deterministic core with no model (`docuharnessx/analysis/analyzer.py:160`).

A key design point: the analyzer never re-sorts a detector's output — each layer already returns its collection pre-sorted in the order the model documents, so two runs over an unchanged inventory produce equal objects that serialize byte-identically (`docuharnessx/analysis/analyzer.py:14-22`).

### 3. The detectors: signal extraction

`docuharnessx.analysis.detectors` is "the pure, model-free *signal layer*": one pure function per concern over the `FileInventory` (`docuharnessx/analysis/detectors.py:3-12`). Concretely:

- `summarize_structure` produces one `DirectorySummary` per directory (file count, dominant language by LOC with name-asc tie-break, heuristic role via `_classify_role`) sorted by path (`docuharnessx/analysis/detectors.py:272-323`, `docuharnessx/analysis/detectors.py:217-248`);
- `detect_entrypoints` finds exact entrypoint basenames (`main.go`, `__main__.py`, `cli.py`, …) and direct files under `bin/`/`scripts/`, sorted by `(path, kind)` (`docuharnessx/analysis/detectors.py:347-390`);
- `detect_build_files` classifies manifests, lockfiles, and `requirements*.txt` by case-folded basename at any depth, so a nested sub-project `go.mod` is found too (`docuharnessx/analysis/detectors.py:458-474`);
- `detect_ci` recognizes GitHub Actions under `.github/workflows/`, `.circleci/`, `.gitlab-ci.yml`, `dagger.json`, etc. (`docuharnessx/analysis/detectors.py:517-534`);
- `detect_tests` rolls per-file naming conventions (Go `*_test.go`, Python `test_*.py`, JS/TS `*.test.*`/`*.spec.*`) and conventional test dirs into a `TestLayout` of `present` + sorted `frameworks` + sorted `paths` (`docuharnessx/analysis/detectors.py:605-641`);
- `extract_dependencies_with_notes` (and its notes-dropping seam `extract_dependencies`) re-reads `pyproject.toml` via `tomllib`, `go.mod` by line parse, `requirements*.txt` line-by-line, and `package.json` via `json`, returning `Dependency` records sorted by `(source, name, scope, version_spec)`; malformed manifests are absorbed as "partially parsed" notes, never exceptions (`docuharnessx/analysis/detectors.py:997-1054`, `docuharnessx/analysis/detectors.py:670-687`);
- `map_components` derives a component map from directories that *directly* contain source files, with a ≤5 representative-file set and the repo root named `"root"` (`docuharnessx/analysis/detectors.py:1078-1121`);
- `detect_public_surface` applies shallow regexes for Go cobra/`flag`/pflag CLI flags and capitalized exported funcs/types (minus `Test`/`Benchmark`/… harness names) and Python `argparse` flags/subcommands plus `__all__` entries, sorted by `(source, kind, name)` (`docuharnessx/analysis/detectors.py:1244-1292`);
- `detect_docs` builds a `DocPresence` of README paths, `doc`/`docs` directories, and recognized standalone docs like `CONTRIBUTING`/`CHANGELOG` (`docuharnessx/analysis/detectors.py:1357-1392`);
- `detect_artifacts` classifies licenses, Dockerfiles, generated-output markers, and schema/spec files into `Artifact` records (`docuharnessx/analysis/detectors.py:1490-1508`).

Every category returns an empty tuple / falsey singular record when nothing matches so the model shape stays stable (`docuharnessx/analysis/detectors.py:26-27`).

### 4. The frozen seam

The output is `RepoAnalysis`, a `@dataclass(frozen=True)` aggregate: `schema_version` (always `REPO_ANALYSIS_SCHEMA_VERSION = 1`), `repo_path`, `languages`, `primary_languages`, `total_loc`/`total_files`, `structure`, `entrypoints`, `build_files`, `ci_workflows`, `tests`, `dependencies`, `components`, `public_surface`, `docs`, `artifacts`, `scan_stats`, and the optional `enrichment` field defaulted to `None` (`docuharnessx/analysis/model.py:229-257`, `docuharnessx/analysis/model.py:56`). Every collection is a `tuple`, never a `list`, so the instance is deeply immutable and hashable (`docuharnessx/analysis/model.py:12-17`).

### 5. Optional, gated LLM enrichment

The one place a model may touch the analysis is `enrich()` in `docuharnessx.analysis.enrich` — "the **only** surface in the otherwise pure, model-free analysis core that may consult a model" (`docuharnessx/analysis/enrich.py:3-11`). Its gate is explicit: `if not enabled or model is None: return analysis`, so a disabled or model-less run returns the *same* object unchanged (`docuharnessx/analysis/enrich.py:123-124`). When enabled and successful, it calls the duck-typed model's awaitable `complete(messages, tools, stream_callback=None)` under `asyncio.wait_for` with `DEFAULT_ENRICH_TIMEOUT_S` (read from `DHX_ENRICH_TIMEOUT_S`, default 120.0) (`docuharnessx/analysis/enrich.py:79`, `docuharnessx/analysis/enrich.py:183-200`), then uses `dataclasses.replace` to attach an `Enrichment(architecture_summary, model_id)` — so every deterministic core field stays byte-for-byte identical (`docuharnessx/analysis/enrich.py:145-151`). Any failure or timeout is logged at WARNING and absorbed, returning the unchanged core (`docuharnessx/analysis/enrich.py:126-136`, `docuharnessx/analysis/enrich.py:154-180`).

### 6. Errors

Fatal, stage-scoped conditions are modelled as typed errors under `AnalysisError` — `IngestError` (bad/missing target repo), `AnalyzeError` (missing file-inventory slot), and `RepoAnalysisVersionError` (unknown `schema_version` in `serde.from_dict`) (`docuharnessx/analysis/errors.py:50-87`). Recoverable in-scan conditions — unreadable files, partially-parseable manifests, tripped scan limits — are deliberately *not* errors; they are absorbed into `ScanStats.notes`/counters (`docuharnessx/analysis/errors.py:15-20`).

In short: analysis scans a repository into a bounded inventory, runs the language layer and ten deterministic detectors over it, and composes the pre-sorted results into one frozen, versioned `RepoAnalysis` that a downstream planner consumes — with an optional, best-effort LLM summary layered on top that can never change or gate the deterministic core.
