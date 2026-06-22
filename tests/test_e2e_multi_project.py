"""Hermetic, credential-free, multi-language full-pipeline E2E suite (Wave 4 finale).

This is the e2e-multi-project deliverable: the permanent, tested guarantee that the full
``dhx`` pipeline (Ingest → Analyze → Classify → Plan → Write → Review → Assemble → Deploy)
generates a correct, publishable, **per-project** Material for MkDocs site for **arbitrary**
software projects — not just the ``malware_hashes`` reference target. It adds **no pipeline
behavior**; it drives the already-built pipeline read-only through its public programmatic
seam and asserts only observable outputs.

How it is driven (design "black-box end-to-end validation through the programmatic seam")
-----------------------------------------------------------------------------------------
For each crafted fixture the suite:

* builds a small but realistic repository of a distinct ecosystem (Go / Python / JS) on disk
  under ``tmp_path`` — a build manifest, an entrypoint, a couple of source files with enough
  real source LOC that the ecosystem language is the unambiguous primary, a README, plus an
  ``origin`` git remote so a GitHub project-Pages ``/<repo>/`` identity resolves
  (Req 1.1, 1.5);
* runs the FULL pipeline via the programmatic path — ``cli.build_parser`` →
  ``cli.prepare_run(args, model_config=ModelConfig(main=RoutingFakeProvider()))`` →
  ``cli.orchestrate_run(prepared)`` — NEVER the bare ``dhx`` console script (Req 1.2), with a
  content-routing fake provider so the Review gate ACCEPTS segments (Req 2.x) and a
  ``PyMkdocsNoPushRunner`` injected onto the live ``DeployStage`` so a REAL ``python -m
  mkdocs build`` runs under the per-target base-path while the ``gh-deploy`` push is refused
  (Req 7.x); and
* asserts, per fixture, the correct primary language (Req 3), a project-specific non-empty
  vocab-valid reproducible coverage plan (Req 4), written + reviewed non-empty accepted
  segments (Req 5), the per-target assembled site + base-path (Req 6), a real build under that
  base-path (Req 7), the emitted CI workflow + isolation + clean ``done`` exit (Req 8).

It then compares two different-ecosystem fixtures (different plans / identities / primary
languages — Req 9) and runs the no-example-hardcoding guard including the active
vendor-exclusion check (Req 10).

Hermetic / credential-free (Req 1.3): every run binds only :class:`RoutingFakeProvider` (no
network, no credentials), depends only on the crafted fixtures (never the pre-cloned external
repos), and the only subprocess is the local ``python -m mkdocs build`` / ``git`` read driven
through the injected runner — the ``gh-deploy`` network push is never exercised.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Callable

import pytest
import yaml
from harnessx.core.model_config import ModelConfig

from docuharnessx import cli
from docuharnessx.assembler.model import AssembledSite, SiteIdentity
from docuharnessx.context import RunContext
from docuharnessx.deployer.model import DeployResult
from docuharnessx.planning.model import CoveragePlan
from docuharnessx.review.model import ReviewReport
from docuharnessx.stages.deploy import DeployStage

from tests._fakes import PyMkdocsNoPushRunner, RoutingFakeProvider

# The doc framework is a declared runtime dependency and installed in the project venv; the
# guards skip gracefully if it is somehow absent rather than failing the whole E2E module
# (mirrors tests/test_deploy_build_e2e_5_3).
pytest.importorskip("mkdocs")
pytest.importorskip("material")


# A small per-run step budget large enough for the single-turn skeleton task; the no-op
# pipeline completes in one model turn, so a small ceiling keeps a degenerate run bounded.
_MAX_STEPS = 6

# Any DocuHarnessX-specific identity token must NEVER appear in a fixture's resolved site
# identity or deploy result — the site is per-project, never the generator's own (Req 10.3).
_FORBIDDEN_OWN_IDENTITY = ("docuharnessx", "DocuHarnessX")

# The reference example target the pipeline must NOT depend on. The Python/JS fixtures build
# correct sites with no ``malware_hashes``-specific value required (Req 10.1).
_EXAMPLE_TARGET_TOKEN = "malware_hashes"


# --------------------------------------------------------------------------- #
# Fixture descriptor                                                           #
# --------------------------------------------------------------------------- #


class _Fixture:
    """One crafted fixture repository: its on-disk path and its expected per-target identity."""

    def __init__(
        self,
        *,
        ecosystem: str,
        path: Path,
        owner: str,
        repo: str,
        primary_language: str,
    ) -> None:
        self.ecosystem = ecosystem
        self.path = path
        self.owner = owner
        self.repo = repo
        self.primary_language = primary_language

    @property
    def base_path(self) -> str:
        return f"/{self.repo}/"

    @property
    def site_url(self) -> str:
        return f"https://{self.owner}.github.io/{self.repo}/"


# --------------------------------------------------------------------------- #
# Fixture builders: crafted Go / Python / JS repos with an origin remote        #
# (Req 1.1, 1.5, 10.2)                                                         #
# --------------------------------------------------------------------------- #


def _git_init_with_remote(root: Path, owner: str, repo: str) -> None:
    """Init a git repo with a stable ``main`` default branch and a GitHub ``origin`` remote.

    The default branch is pinned to ``main`` via ``symbolic-ref`` (no commit needed) so the
    emitted Pages workflow's push trigger is deterministic regardless of the host git's
    ``init.defaultBranch`` setting, and the GitHub ``origin`` remote gives the per-target
    ``/<repo>/`` project-Pages identity (Req 1.5).
    """
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(
        ["git", "symbolic-ref", "HEAD", "refs/heads/main"], cwd=root, check=True
    )
    subprocess.run(
        ["git", "remote", "add", "origin", f"https://github.com/{owner}/{repo}.git"],
        cwd=root,
        check=True,
    )


def build_go_fixture(parent: Path, *, owner: str, repo: str) -> _Fixture:
    """A crafted Go project: ``go.mod`` + a ``main.go`` entrypoint + a source file + README.

    Carries enough real Go source LOC that ``Go`` is the unambiguous primary language even
    though a ``go.mod`` and a README are present (Req 1.5).
    """
    root = parent / repo
    root.mkdir(parents=True)
    (root / "go.mod").write_text(
        f"module github.com/{owner}/{repo}\n\ngo 1.21\n", encoding="utf-8"
    )
    main_lines = ["package main", "", 'import "fmt"', ""]
    main_lines += [f"// computeStep{i} documents step {i} of the run." for i in range(60)]
    main_lines += ["", "func main() {", '\tfmt.Println("running")', "}", ""]
    (root / "main.go").write_text("\n".join(main_lines), encoding="utf-8")
    util_lines = ["package main", ""]
    util_lines += [f"func Helper{i}() int {{ return {i} }}" for i in range(40)]
    (root / "util.go").write_text("\n".join(util_lines) + "\n", encoding="utf-8")
    (root / "README.md").write_text(
        f"# {repo}\n\nA small Go command-line tool.\n", encoding="utf-8"
    )
    _git_init_with_remote(root, owner, repo)
    return _Fixture(
        ecosystem="go", path=root, owner=owner, repo=repo, primary_language="Go"
    )


def build_python_fixture(parent: Path, *, owner: str, repo: str) -> _Fixture:
    """A crafted Python project: ``pyproject.toml`` + a package + a console entrypoint + README.

    A real ``pkg/`` package with a CLI module and a core module carries enough Python source
    LOC that ``Python`` is the unambiguous primary language (Req 1.5).
    """
    root = parent / repo
    root.mkdir(parents=True)
    (root / "pyproject.toml").write_text(
        "[project]\n"
        f'name = "{repo}"\n'
        'version = "0.1.0"\n'
        "\n[project.scripts]\n"
        f'{repo} = "{repo}.cli:main"\n',
        encoding="utf-8",
    )
    pkg = root / repo
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    cli_lines = ["import argparse", ""]
    cli_lines += [f"def handler_{i}() -> int:\n    return {i}" for i in range(40)]
    cli_lines += ["", "def main() -> None:", '    print("hello")', ""]
    (pkg / "cli.py").write_text("\n".join(cli_lines), encoding="utf-8")
    core_lines = [
        f"class Widget{i}:\n    value = {i}\n\n    def run(self) -> int:\n        return self.value"
        for i in range(20)
    ]
    (pkg / "core.py").write_text("\n\n".join(core_lines) + "\n", encoding="utf-8")
    (root / "README.md").write_text(
        f"# {repo}\n\nA small Python library with a CLI.\n", encoding="utf-8"
    )
    _git_init_with_remote(root, owner, repo)
    return _Fixture(
        ecosystem="python", path=root, owner=owner, repo=repo, primary_language="Python"
    )


def build_js_fixture(
    parent: Path, *, owner: str, repo: str, with_vendor_dir: bool = False
) -> _Fixture:
    """A crafted JS/Node project: ``package.json`` + ``src/``/``lib/``/``bin/`` + tests + README.

    A real source tree (``src/index.js`` + ``src/server.js`` + ``lib/util.js`` +
    ``bin/cli.js``) carries enough JavaScript source LOC that ``JavaScript`` is the
    unambiguous primary language, and the multiple components + entrypoint + CI workflow give
    the planner a project-specific surface to plan over (Req 1.5).

    When ``with_vendor_dir`` is set, a heavy ``node_modules/`` dependency directory is planted
    so the suite can assert the scanner excludes it from the analysis inventory (Req 10.2).
    """
    root = parent / repo
    root.mkdir(parents=True)
    (root / "package.json").write_text(
        "{\n"
        f'  "name": "{repo}",\n'
        '  "version": "1.0.0",\n'
        f'  "bin": {{ "{repo}": "bin/cli.js" }},\n'
        '  "scripts": { "test": "jest" },\n'
        '  "dependencies": { "express": "^4" }\n'
        "}\n",
        encoding="utf-8",
    )
    src = root / "src"
    src.mkdir()
    index_lines = ["'use strict';", ""]
    index_lines += [f"function feature{i}() {{ return {i}; }}" for i in range(50)]
    index_lines += ["", "module.exports = { feature0 };"]
    (src / "index.js").write_text("\n".join(index_lines) + "\n", encoding="utf-8")
    server_lines = ["'use strict';", "const http = require('http');", ""]
    server_lines += [f"const route{i} = {i};" for i in range(40)]
    (src / "server.js").write_text("\n".join(server_lines) + "\n", encoding="utf-8")
    lib = root / "lib"
    lib.mkdir()
    (lib / "util.js").write_text(
        "\n".join(f"exports.util{i} = function () {{ return {i}; }};" for i in range(40))
        + "\n",
        encoding="utf-8",
    )
    binr = root / "bin"
    binr.mkdir()
    bin_lines = ["#!/usr/bin/env node", "'use strict';", "require('../src/index.js');"]
    bin_lines += [f"// startup step {i}" for i in range(20)]
    (binr / "cli.js").write_text("\n".join(bin_lines) + "\n", encoding="utf-8")
    tdir = root / "test"
    tdir.mkdir()
    (tdir / "index.test.js").write_text(
        "const f = require('../src/index.js');\n"
        "test('feature0', () => { expect(f.feature0()).toBe(0); });\n",
        encoding="utf-8",
    )
    gh = root / ".github" / "workflows"
    gh.mkdir(parents=True)
    (gh / "ci.yml").write_text(
        "name: CI\non: [push]\njobs:\n  build:\n    runs-on: ubuntu-latest\n"
        "    steps:\n      - run: npm test\n",
        encoding="utf-8",
    )
    (root / "README.md").write_text(
        f"# {repo}\n\nA small Node.js package.\n", encoding="utf-8"
    )
    if with_vendor_dir:
        vendor = root / "node_modules" / "left-pad"
        vendor.mkdir(parents=True)
        (vendor / "index.js").write_text(
            "module.exports = function leftPad() {};\n" * 80, encoding="utf-8"
        )
        (vendor / "package.json").write_text(
            '{ "name": "left-pad", "version": "9.9.9" }\n', encoding="utf-8"
        )
    _git_init_with_remote(root, owner, repo)
    return _Fixture(
        ecosystem="js", path=root, owner=owner, repo=repo, primary_language="JavaScript"
    )


# --------------------------------------------------------------------------- #
# The programmatic full-pipeline driver (Req 1.2, 1.3, 2.5, 8.4)               #
# --------------------------------------------------------------------------- #


class _RunResult:
    """The outputs of one full-pipeline run, read through the typed ``RunContext`` slots."""

    def __init__(self, outcome: cli.RunOutcome, runner: PyMkdocsNoPushRunner) -> None:
        self.outcome = outcome
        self.runner = runner
        self.run_context: RunContext = outcome.run_context

    @property
    def exit_reason(self) -> str:
        return self.outcome.exit_reason


def run_fixture(
    fixture_dir: str,
    *,
    deploy_mode: str,
    out_dir: str,
    target_tree: str | None = None,
) -> _RunResult:
    """Drive the FULL pipeline once over ``fixture_dir`` via the programmatic seam.

    Builds the run namespace via :func:`cli.build_parser`, calls
    :func:`cli.prepare_run` with an injected :class:`RoutingFakeProvider` ``ModelConfig`` (so
    production model resolution is never touched — Req 1.2, 1.3), injects a
    :class:`PyMkdocsNoPushRunner` onto every live :class:`DeployStage` on the prepared
    harness's processor table (the same walk :func:`cli._thread_deploy_mode` uses) so the
    deploy runs a REAL ``python -m mkdocs build`` and refuses any push (Req 7.1, 7.3), then
    calls :func:`cli.orchestrate_run` and returns the outcome + runner. The bare console script
    is never invoked.

    ``target_tree`` is accepted for symmetry with the design's driver signature; the emit
    isolation test runs against a throwaway copy by passing that copy as ``fixture_dir``, so
    the original crafted fixture is never mutated (Req 8.3).
    """
    _ = target_tree  # documented seam; the emit test points fixture_dir at the throwaway copy
    args = cli.build_parser().parse_args(
        ["run", fixture_dir, "--out", out_dir, "--deploy-mode", deploy_mode]
    )
    prepared = cli.prepare_run(
        args, model_config=ModelConfig(main=RoutingFakeProvider())
    )

    runner = PyMkdocsNoPushRunner()
    runtime = getattr(prepared.harness, "_rt", None)
    processors = getattr(runtime, "processors", None) or {}
    injected = False
    for procs in processors.values():
        for proc in procs:
            if isinstance(proc, DeployStage):
                proc._command_runner = runner
                injected = True
    assert injected, "no live DeployStage found on the prepared harness to inject into"

    outcome = cli.orchestrate_run(prepared, max_steps=_MAX_STEPS)
    return _RunResult(outcome, runner)


# --------------------------------------------------------------------------- #
# Session-scoped per-fixture full-pipeline runs (built once, asserted many)     #
# --------------------------------------------------------------------------- #
#
# The full pipeline (with a real mkdocs build) is the expensive part, so each ecosystem
# fixture is built and run ONCE per session in build-only mode; the many per-fixture
# assertions below read the cached outputs. Distinct owner/repo per fixture so the resolved
# per-target identities genuinely differ (Req 6.3, 9.2).

_BUILDERS: dict[str, tuple[Callable[..., _Fixture], dict[str, str]]] = {
    "go": (build_go_fixture, {"owner": "go-acme", "repo": "go-widget"}),
    "python": (build_python_fixture, {"owner": "py-acme", "repo": "py-toolkit"}),
    "js": (build_js_fixture, {"owner": "js-acme", "repo": "js-bundler"}),
}


@pytest.fixture(scope="session")
def fixture_runs(tmp_path_factory: pytest.TempPathFactory) -> dict[str, _RunResult]:
    """Build + run each ecosystem fixture once; return ``{ecosystem: _RunResult}``."""
    base = tmp_path_factory.mktemp("e2e_fixtures")
    runs: dict[str, _RunResult] = {}
    for eco, (builder, kwargs) in _BUILDERS.items():
        repos = base / eco / "repos"
        out = base / eco / "out"
        out.mkdir(parents=True)
        fixture = builder(repos, **kwargs)
        runs[eco] = run_fixture(
            str(fixture.path), deploy_mode="build-only", out_dir=str(out)
        )
        # Pin the descriptor on the result so assertions can read the expected identity.
        runs[eco].fixture = fixture  # type: ignore[attr-defined]
    return runs


_ECOSYSTEMS = ("go", "python", "js")


def _read_outputs(result: _RunResult):
    rc = result.run_context
    return (
        rc.repo_analysis(),
        rc.coverage_plan(),
        rc.written_segments(),
        rc.review_report(),
        rc.assembled_site(),
        rc.deploy_result(),
    )


# --------------------------------------------------------------------------- #
# Req 1.2 / 2.5 / 8.4 — the run reaches the terminal exit reason 'done'          #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("eco", _ECOSYSTEMS)
def test_full_pipeline_reaches_done(eco: str, fixture_runs) -> None:
    """The full pipeline run completes with exit reason ``done`` and exit code 0 (Req 2.5, 8.4)."""
    result = fixture_runs[eco]
    assert result.exit_reason == "done"
    assert result.outcome.exit_code == cli.EXIT_OK
    # Every stage slot is populated — the whole chain ran, not just the model turn.
    analysis, plan, written, report, site, deploy = _read_outputs(result)
    assert analysis is not None
    assert plan is not None
    assert written is not None
    assert report is not None
    assert site is not None
    assert deploy is not None


# --------------------------------------------------------------------------- #
# Req 3 — per-fixture primary language detection                                #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("eco", _ECOSYSTEMS)
def test_primary_language_per_ecosystem(eco: str, fixture_runs) -> None:
    """The intended ecosystem language is detected and is the primary language (Req 3.1-3.4)."""
    result = fixture_runs[eco]
    analysis = result.run_context.repo_analysis()
    expected = result.fixture.primary_language  # type: ignore[attr-defined]
    detected = {stat.language for stat in analysis.languages}
    assert expected in detected, f"{eco}: {expected} not among detected {detected}"
    assert analysis.primary_languages == (expected,), (
        f"{eco}: primary {analysis.primary_languages!r} != ({expected!r},)"
    )


# --------------------------------------------------------------------------- #
# Req 4 — project-specific, vocab-valid, reproducible coverage plan              #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("eco", _ECOSYSTEMS)
def test_coverage_plan_non_empty_and_vocab_valid(eco: str, fixture_runs) -> None:
    """The plan has at least one segment whose roles/intent/subjects are vocabulary members (Req 4.1, 4.2)."""
    result = fixture_runs[eco]
    plan = result.run_context.coverage_plan()
    vocab = result.run_context.vocabulary()
    assert isinstance(plan, CoveragePlan)
    assert len(plan.segments) >= 1, f"{eco}: empty coverage plan"

    valid_roles = {term.id for term in vocab.roles}
    valid_intents = {term.id for term in vocab.intents}
    valid_prefixes = {prefix.rstrip(":") for prefix in vocab.subject_prefixes}
    for segment in plan.segments:
        for role in segment.roles:
            assert role in valid_roles, f"{eco}: role {role!r} not in vocabulary"
        assert segment.intent in valid_intents, (
            f"{eco}: intent {segment.intent!r} not in vocabulary"
        )
        for subject in segment.subjects:
            assert subject.prefix in valid_prefixes, (
                f"{eco}: subject prefix {subject.prefix!r} not in vocabulary"
            )


@pytest.mark.parametrize("eco", _ECOSYSTEMS)
def test_coverage_plan_is_reproducible(eco: str, fixture_runs, tmp_path) -> None:
    """Running the same fixture twice yields the same plan (Req 4.3).

    Re-runs the pipeline over the same crafted fixture into a fresh output dir and asserts the
    planned-segment sets are identical (the planner is deterministic; the routing fake never
    perturbs the deterministic plan).
    """
    result = fixture_runs[eco]
    fixture = result.fixture  # type: ignore[attr-defined]
    first = result.run_context.coverage_plan()

    out2 = tmp_path / "rerun_out"
    out2.mkdir()
    second_result = run_fixture(
        str(fixture.path), deploy_mode="build-only", out_dir=str(out2)
    )
    second = second_result.run_context.coverage_plan()

    assert [s.segment_key for s in first.segments] == [
        s.segment_key for s in second.segments
    ]


# --------------------------------------------------------------------------- #
# Req 5 — written + reviewed non-empty accepted segments                         #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("eco", _ECOSYSTEMS)
def test_written_and_accepted_segments_non_empty(eco: str, fixture_runs) -> None:
    """The writer wrote real bodies and the gate accepted every written segment (Req 5.1-5.3).

    Asserts: every planned segment is accounted for in ``segments`` or ``flags`` (the
    WrittenSegments invariant); every written segment has a non-empty body persisted as a
    Markdown file under ``<out>/segments``; the Review gate accepted EVERY written segment
    (``accepted == written > 0``) with no entry judged via the fail-closed ``unavailable``
    default.
    """
    result = fixture_runs[eco]
    written = result.run_context.written_segments()
    report = result.run_context.review_report()
    out_dir = result.run_context.output_dir()

    assert written is not None and report is not None
    # Every planned segment is represented (WrittenSegments invariant; a validation flag is a
    # legitimate, pipeline-defined outcome and is not the boundary under test).
    assert len(written.segments) + len(written.flags) == written.total_planned

    assert len(written.segments) > 0, f"{eco}: no segments written"
    for segment in written.segments:
        assert segment.body.strip(), f"{eco}: empty body for {segment.id}"
        md_path = Path(out_dir) / "segments" / f"{segment.id}.md"
        assert md_path.is_file(), f"{eco}: no persisted Markdown for {segment.id}"
        assert md_path.read_text(encoding="utf-8").strip(), (
            f"{eco}: empty persisted Markdown for {segment.id}"
        )

    # The gate accepted every written segment; none used the fail-closed unavailable default.
    assert report.aggregate.unavailable == 0, f"{eco}: a segment was judged unavailable"
    assert all(entry.judge_source != "unavailable" for entry in report.entries)
    assert report.aggregate.accepted == len(written.segments) > 0
    assert len(report.accepted) == len(written.segments)
    assert [s.id for s in report.accepted] == [s.id for s in written.segments]


# --------------------------------------------------------------------------- #
# Req 6 — per-target assembled site + base-path                                  #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("eco", _ECOSYSTEMS)
def test_assembled_site_carries_per_target_identity(eco: str, fixture_runs) -> None:
    """The assembled site's identity + ``mkdocs.yml`` carry the fixture's own Pages base-path (Req 6.1-6.3)."""
    result = fixture_runs[eco]
    fixture = result.fixture  # type: ignore[attr-defined]
    site = result.run_context.assembled_site()
    assert isinstance(site, AssembledSite)
    assert isinstance(site.identity, SiteIdentity)

    # Base-path and site URL are derived from THIS fixture's remote (Req 6.1).
    assert site.identity.base_path == fixture.base_path
    assert site.identity.site_url == fixture.site_url
    assert site.identity.repo_name == f"{fixture.owner}/{fixture.repo}"

    # The emitted mkdocs.yml carries the per-target site URL and no DocuHarnessX identity (Req 6.2).
    mkdocs_text = Path(site.mkdocs_yml_path).read_text(encoding="utf-8")
    assert fixture.site_url in mkdocs_text
    lowered = mkdocs_text.lower()
    for token in _FORBIDDEN_OWN_IDENTITY:
        assert token.lower() not in lowered, (
            f"{eco}: DocuHarnessX identity {token!r} leaked into mkdocs.yml"
        )


# --------------------------------------------------------------------------- #
# Req 7 — a real mkdocs build under the per-target base-path, no push            #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("eco", _ECOSYSTEMS)
def test_real_build_under_per_target_base_path(eco: str, fixture_runs) -> None:
    """A real ``python -m mkdocs build`` produced a static site under ``/<repo>/`` (Req 7.1-7.4).

    Asserts the built static site exists with at least one rendered page and a sitemap, every
    sitemap URL sits under the fixture's ``/<repo>/`` Pages base-path (so the build resolved
    links/assets under the project subpath, not the domain root), exactly one build ran, and
    no ``gh-deploy`` push ran.
    """
    result = fixture_runs[eco]
    fixture = result.fixture  # type: ignore[attr-defined]
    deploy = result.run_context.deploy_result()
    assert isinstance(deploy, DeployResult)
    assert deploy.status == "built"

    built = Path(deploy.built_path)
    assert built.is_dir(), f"{eco}: no built site dir"
    assert any(built.rglob("index.html")), f"{eco}: no rendered pages in the built site"
    sitemap = built / "sitemap.xml"
    assert sitemap.is_file(), f"{eco}: no sitemap in the built site"
    sitemap_text = sitemap.read_text(encoding="utf-8")
    # Every <loc> URL must sit under the per-target Pages base-path (Req 7.2).
    locs = [
        line.strip()[len("<loc>") : -len("</loc>")]
        for line in sitemap_text.splitlines()
        if line.strip().startswith("<loc>")
    ]
    assert locs, f"{eco}: sitemap has no URLs"
    for loc in locs:
        assert loc.startswith(fixture.site_url), (
            f"{eco}: sitemap URL {loc!r} not under {fixture.site_url!r}"
        )

    # Exactly one real build ran; the gh-deploy push was never reached (Req 7.4).
    assert result.runner.build_count() == 1
    assert result.runner.pushed is False


# --------------------------------------------------------------------------- #
# Req 8 — emit-ci-workflow emission, isolation, and clean exit (on one fixture)   #
# --------------------------------------------------------------------------- #


def test_emit_ci_workflow_emission_isolation_and_clean_exit(tmp_path) -> None:
    """emit-ci-workflow writes a valid Pages workflow into a throwaway target tree (Req 8.1-8.4).

    The Deploy stage emits into ``SLOT_TARGET_REPO`` — the run target. To prove the emit
    writes go into a THROWAWAY target tree and leave every other location untouched (Req 8.3),
    the pipeline is run against a fresh copy of the Go fixture: the copy is the throwaway
    target tree; the original crafted fixture is built in a sibling dir and is never touched.
    """
    repos = tmp_path / "repos"
    repos.mkdir()
    original = build_go_fixture(repos, owner="emit-acme", repo="emit-widget")

    # The throwaway target tree: a copy of the fixture (excluding .git), with its own remote.
    target = tmp_path / "target_copy"
    shutil.copytree(
        original.path, target, ignore=shutil.ignore_patterns(".git")
    )
    _git_init_with_remote(target, owner="emit-acme", repo="emit-widget")
    target_before = {p.name for p in target.iterdir()}

    out = tmp_path / "out"
    out.mkdir()
    result = run_fixture(
        str(target), deploy_mode="emit-ci-workflow", out_dir=str(out)
    )

    assert result.exit_reason == "done"
    assert result.outcome.exit_code == cli.EXIT_OK

    deploy = result.run_context.deploy_result()
    assert deploy.status == "emitted"

    # The three emit artifacts are present in the throwaway target tree (Req 8.1).
    mkdocs_yml = target / "mkdocs.yml"
    docs_dir = target / "docs"
    workflow = target / ".github" / "workflows" / "docs.yml"
    assert mkdocs_yml.is_file()
    assert docs_dir.is_dir()
    assert workflow.is_file()
    assert {Path(p) for p in deploy.written_paths} == {mkdocs_yml, docs_dir, workflow}

    # The emitted workflow is parseable YAML with the push trigger, Pages permissions, and the
    # build + deploy-pages jobs (Req 8.2). ``on:`` round-trips to the YAML 1.1 boolean True key.
    parsed = yaml.safe_load(workflow.read_text(encoding="utf-8"))
    assert isinstance(parsed, dict)
    on_block = parsed.get(True, parsed.get("on"))
    assert isinstance(on_block, dict)
    branches = on_block["push"]["branches"]
    assert branches == ["main"], f"unexpected push branches {branches!r}"
    assert parsed["permissions"]["pages"] == "write"
    assert parsed["permissions"]["id-token"] == "write"
    jobs = parsed["jobs"]
    assert "build" in jobs and "deploy" in jobs
    assert any(
        "deploy-pages" in str(step.get("uses", ""))
        for step in jobs["deploy"]["steps"]
    )

    # Isolation (Req 8.3): every write into the target tree stayed under the target tree, the
    # built site stayed under the output dir, and the ONLY new top-level target entries are the
    # three emitted artifacts.
    for written in deploy.written_paths:
        assert Path(written).is_relative_to(target)
    assert Path(deploy.built_path).is_relative_to(out)
    target_after = {p.name for p in target.iterdir()}
    assert target_after - target_before == {"mkdocs.yml", "docs", ".github"}

    # The original crafted fixture was never mutated (no emit artifacts landed there).
    original_names = {p.name for p in original.path.iterdir()}
    assert "mkdocs.yml" not in original_names
    assert ".github" not in original_names

    assert result.runner.pushed is False


# --------------------------------------------------------------------------- #
# Req 9 — cross-fixture difference (plans, identities, languages)                #
# --------------------------------------------------------------------------- #


def test_cross_fixture_plans_and_identities_differ(fixture_runs) -> None:
    """Two different-ecosystem fixtures yield non-identical plans and differing identities (Req 9.1, 9.2)."""
    go = fixture_runs["go"]
    py = fixture_runs["python"]

    go_keys = {s.segment_key for s in go.run_context.coverage_plan().segments}
    py_keys = {s.segment_key for s in py.run_context.coverage_plan().segments}
    assert go_keys != py_keys, "two ecosystems produced identical planned-segment sets"

    go_site = go.run_context.assembled_site()
    py_site = py.run_context.assembled_site()
    assert go_site.identity.base_path != py_site.identity.base_path
    assert go_site.identity.site_url != py_site.identity.site_url


def test_primary_language_set_differs_across_fixtures(fixture_runs) -> None:
    """The set of detected primary languages across Go/Python/JS is not a single value (Req 9.3)."""
    primaries = set()
    for eco in _ECOSYSTEMS:
        analysis = fixture_runs[eco].run_context.repo_analysis()
        primaries.update(analysis.primary_languages)
    assert len(primaries) > 1, f"primary-language set collapsed to {primaries}"
    assert {"Go", "Python", "JavaScript"} <= primaries


# --------------------------------------------------------------------------- #
# Req 10 — no-example-hardcoding guard + active vendor exclusion                 #
# --------------------------------------------------------------------------- #


def test_non_example_fixtures_build_without_example_value(fixture_runs) -> None:
    """The Python and JS fixtures build correct per-project sites with no ``malware_hashes`` value (Req 10.1).

    Neither fixture's owner/repo nor its resolved identity carries the reference example
    target's name, and both produce a real built site under their own base-path — proving the
    pipeline requires no ``malware_hashes``-specific value to work.
    """
    for eco in ("python", "js"):
        result = fixture_runs[eco]
        fixture = result.fixture  # type: ignore[attr-defined]
        assert _EXAMPLE_TARGET_TOKEN not in fixture.repo
        assert _EXAMPLE_TARGET_TOKEN not in fixture.owner

        site = result.run_context.assembled_site()
        deploy = result.run_context.deploy_result()
        assert _EXAMPLE_TARGET_TOKEN not in site.identity.site_url
        assert _EXAMPLE_TARGET_TOKEN not in deploy.target_pages_url
        # A real, buildable site under the fixture's own base-path.
        assert deploy.status == "built"
        assert Path(deploy.built_path).is_dir()
        assert site.identity.base_path == fixture.base_path


def test_no_docuharnessx_identity_in_any_fixture(fixture_runs) -> None:
    """No fixture's site identity or deploy result carries a DocuHarnessX identity string (Req 10.3)."""
    for eco in _ECOSYSTEMS:
        result = fixture_runs[eco]
        site = result.run_context.assembled_site()
        deploy = result.run_context.deploy_result()
        identity_blob = " ".join(
            [
                site.identity.site_name,
                site.identity.repo_name,
                site.identity.repo_url,
                site.identity.site_url,
                site.identity.base_path,
                deploy.target_pages_url,
            ]
        ).lower()
        for token in _FORBIDDEN_OWN_IDENTITY:
            assert token.lower() not in identity_blob, (
                f"{eco}: DocuHarnessX identity {token!r} in site/deploy identity"
            )


def test_vendor_directory_excluded_from_inventory(tmp_path) -> None:
    """A planted heavy ``node_modules/`` directory contributes ZERO inventory entries (Req 10.2).

    Builds a JS fixture WITH a heavy ``node_modules`` dependency dir, runs the full pipeline,
    and asserts no file under ``node_modules`` appears in the produced repository analysis
    inventory — proving the scanner actively excludes heavy vendor/build dirs (so dependency
    files never pollute the per-project analysis), while the project still detects JavaScript
    as primary and builds a correct site.
    """
    repos = tmp_path / "repos"
    repos.mkdir()
    out = tmp_path / "out"
    out.mkdir()
    fixture = build_js_fixture(
        repos, owner="vendor-acme", repo="vendor-pkg", with_vendor_dir=True
    )
    # Sanity: the heavy vendor dir really exists on disk before the scan.
    assert (fixture.path / "node_modules" / "left-pad" / "index.js").is_file()

    result = run_fixture(
        str(fixture.path), deploy_mode="build-only", out_dir=str(out)
    )
    assert result.exit_reason == "done"

    inventory = result.run_context.file_inventory()
    assert inventory is not None
    leaked = [
        entry.path
        for entry in inventory.entries
        if "node_modules" in entry.path.split("/")
    ]
    assert leaked == [], f"vendor files leaked into the inventory: {leaked}"

    # The project is still correctly analyzed + built despite the vendor dir.
    analysis = result.run_context.repo_analysis()
    assert analysis.primary_languages == ("JavaScript",)
    deploy = result.run_context.deploy_result()
    assert deploy.status == "built"
    assert deploy.target_pages_url == fixture.site_url


# --------------------------------------------------------------------------- #
# Hermetic guard — the run opens no OUTBOUND network connection                  #
# --------------------------------------------------------------------------- #


def test_run_opens_no_outbound_connection(monkeypatch, tmp_path) -> None:
    """The full pipeline run opens no outbound network connection (credential-free, Req 1.3).

    Trips ``socket.socket.connect`` / ``connect_ex`` to prove the orchestration body and every
    stage (bound only to the routing fake, never a real provider) reach out to no network host.
    A plain ``socket.socket`` is left intact because :func:`asyncio.run` legitimately allocates
    a loopback ``socketpair`` for its event-loop self-pipe — that is OS plumbing, not a network
    call; only an actual ``connect`` would mean the run dialed out. The only subprocess is the
    local ``python -m mkdocs build`` / ``git`` read driven through the runner, in its own
    process, so it does not trip the guard.
    """
    import socket

    repos = tmp_path / "repos"
    repos.mkdir()
    out = tmp_path / "out"
    out.mkdir()
    fixture = build_python_fixture(repos, owner="hermetic-acme", repo="hermetic-pkg")

    def _no_connect(self, *args, **kwargs):  # pragma: no cover - must not be called
        raise AssertionError("the credential-free run must open no outbound connection")

    monkeypatch.setattr(socket.socket, "connect", _no_connect, raising=True)
    monkeypatch.setattr(socket.socket, "connect_ex", _no_connect, raising=True)

    result = run_fixture(
        str(fixture.path), deploy_mode="build-only", out_dir=str(out)
    )
    assert result.exit_reason == "done"
    assert result.run_context.deploy_result().status == "built"
