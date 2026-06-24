"""Strict-mode Mermaid build integration test (agentic-codebase-writer task 5.1).

This test pins the **build** boundary of task 5.1: assemble a small site whose accepted
segment carries a fenced ```` ```mermaid ```` block, then run a real ``mkdocs build --strict``
of the emitted tree and confirm the build succeeds (Req 10.3). With the
``pymdownx.superfences`` Mermaid custom fence enabled by the assembler's
:func:`~docuharnessx.assembler.mkdocs_config.build_mkdocs_yaml` (task 4.1), the fenced
``mermaid`` block must render as a ``class="mermaid"`` diagram container rather than a fenced
code block, and ``--strict`` must not abort.

Boundary (task 5.1): the **assembler build** — the deterministic assembler core
(:func:`~docuharnessx.assembler.writer.assemble_site` over the real
:func:`~docuharnessx.assembler.identity.resolve_site_identity`) plus a real, network-free
``mkdocs build --strict`` subprocess. No model, no network, no credentials: the identity is
resolved from an explicit in-test remote string and the segment body is supplied directly, so
this exercises only that an emitted Mermaid page builds clean under strict mode and that the
custom fence preserves the diagram.

This file owns only the strict Mermaid-build validation; the unit-level
``build_mkdocs_yaml`` custom-fence emission is covered by ``test_assembler_mkdocs_mermaid``
and the broader vocab/remote strict-build matrix by ``test_assembler_build_determinism``.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

from docuharnessx.assembler.identity import resolve_site_identity
from docuharnessx.assembler.model import SiteIdentity
from docuharnessx.assembler.pages import page_filename
from docuharnessx.assembler.writer import assemble_site
from docuharnessx.ontology import Segment, Subject, default_profile
from docuharnessx.review.model import (
    REVIEW_REPORT_SCHEMA_VERSION,
    ReviewAggregate,
    ReviewReport,
)

# The doc framework + Material theme are declared runtime deps installed in the project venv;
# skip gracefully if absent rather than erroring (this is a guard, not an expected path).
pytest.importorskip("mkdocs")
pytest.importorskip("material")
pytest.importorskip("pymdownx")


# --------------------------------------------------------------------------- #
# Builders / fixtures                                                         #
# --------------------------------------------------------------------------- #

_GITHUB_REMOTE = "https://github.com/norandom/malware_hashes.git"
_TARGET_REPO = "/home/operator/projects/widgets"

#: A COBESY-shaped body carrying exactly the structure the agentic writer's structure gate
#: demands: a Minto lead, a valid vertical ``graph TD`` Mermaid fence (short nodes, valid
#: arrows), and ``file:line`` citations. This is the body whose Mermaid fence must survive the
#: strict build as a rendered diagram container.
_MERMAID_BODY = """\
The write stage swaps its prose surface for a bounded agentic run.

```mermaid
graph TD
  Plan[Plan stage] --> Write[Write stage]
  Write --> Agent[Bounded agent]
  Agent --> Body[Cited body]
  Body --> Gate[Structure gate]
  Gate --> Store[Segment store]
```

The flow is grounded in `docuharnessx/stages/write.py:1` and the deterministic core in
`docuharnessx/composition/blueprint.py:1`, so the prose stays traceable to real source.
"""


def _mermaid_segment() -> Segment:
    """An accepted segment whose body carries a fenced Mermaid diagram + citations."""
    return Segment(
        id="architecture-overview",
        title="Architecture Overview",
        roles=["developer"],
        subjects=[Subject(prefix="component", local="architecture")],
        intent="extend",
        summary="How the write stage is wired.",
        related=[],
        body=_MERMAID_BODY,
    )


def _report(*accepted: Segment) -> ReviewReport:
    return ReviewReport(
        schema_version=REVIEW_REPORT_SCHEMA_VERSION,
        entries=(),
        accepted=tuple(accepted),
        aggregate=ReviewAggregate(
            judged=len(accepted),
            accepted=len(accepted),
            rejected=0,
            unavailable=0,
            criterion_tally=(),
        ),
    )


def _identity() -> SiteIdentity:
    """Resolve a per-target GitHub identity through the real resolver (no git read)."""
    return resolve_site_identity(_TARGET_REPO, _GITHUB_REMOTE, {})


def _run_mkdocs_build(
    mkdocs_yml_path: str, site_out: Path
) -> subprocess.CompletedProcess:
    """Run a real, strict ``mkdocs build`` of the emitted tree into ``site_out``.

    ``--strict`` turns any build warning (including an unrecognized/broken fence) into a
    non-zero exit, so a clean exit proves the Mermaid custom fence is recognized and the page
    builds without a strict-mode error (Req 10.3). Invoked via the project interpreter's
    ``-m mkdocs`` so it uses the installed ``mkdocs-material`` theme; local + network-free.
    """
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "mkdocs",
            "build",
            "-f",
            mkdocs_yml_path,
            "-d",
            str(site_out),
            "--strict",
        ],
        capture_output=True,
        text=True,
    )


def _built_page_html(built: Path, segment_id: str) -> str:
    """Return the built HTML for the segment's page (its ``<page>/index.html``)."""
    # use_directory_urls maps ``docs/<file>.md`` to ``<file>/index.html``.
    stem = page_filename(segment_id)[: -len(".md")]
    candidates = list(built.rglob(f"{stem}/index.html")) + list(
        built.rglob(f"{stem}.html")
    )
    assert candidates, f"no built page found for segment {segment_id!r} under {built}"
    return candidates[0].read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# Req 10.3: a Mermaid-bearing page builds under --strict                       #
# --------------------------------------------------------------------------- #


def test_mermaid_page_builds_under_strict_mode(tmp_path: Path) -> None:
    """A page with a fenced Mermaid block builds clean under ``mkdocs build --strict``.

    The assembler emits the page with the ``pymdownx.superfences`` Mermaid custom fence
    enabled (task 4.1); building it in strict mode must succeed (returncode 0) with no
    strict-mode error, proving the enabled fence is recognized (Req 10.3).
    """
    out = tmp_path / "run"
    out.mkdir()
    site = assemble_site(_report(_mermaid_segment()), default_profile(), None, str(out), _identity())

    # Sanity: the emitted source page really carries the verbatim mermaid fence.
    md = Path(site.docs_dir) / page_filename("architecture-overview")
    assert md.is_file()
    assert "```mermaid" in md.read_text(encoding="utf-8")

    built = tmp_path / "_built"
    result = _run_mkdocs_build(site.mkdocs_yml_path, built)
    assert result.returncode == 0, (
        "strict mkdocs build of a Mermaid-bearing page failed:\n"
        f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )
    assert any(built.rglob("index.html")), "no built pages produced"


def test_mermaid_fence_renders_as_diagram_container_not_code_block(tmp_path: Path) -> None:
    """The fenced Mermaid block renders as a ``class="mermaid"`` container, not a code fence.

    With the custom fence enabled, ``pymdownx.superfences`` emits the diagram source inside a
    ``<pre class="mermaid">`` / ``<div class="mermaid">`` container (which Material's Mermaid
    integration hydrates client-side) rather than a syntax-highlighted ``<code>`` block. This
    confirms the diagram is *preserved* through the strict build (Req 10.3) — the agent's
    diagram actually reaches the published page as a diagram.
    """
    out = tmp_path / "run"
    out.mkdir()
    site = assemble_site(_report(_mermaid_segment()), default_profile(), None, str(out), _identity())

    built = tmp_path / "_built"
    result = _run_mkdocs_build(site.mkdocs_yml_path, built)
    assert result.returncode == 0, (
        f"strict build failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )

    html = _built_page_html(built, "architecture-overview")
    # The custom fence wraps the diagram source in a Mermaid-classed *container* element
    # (``<pre class="mermaid">`` / ``<div class="mermaid">``), which Material hydrates into a
    # diagram. Without the superfence the same fence renders as a plain highlighted code block
    # (``<pre><code class="language-mermaid">``) whose ``mermaid`` token only appears on the
    # inner ``<code>`` — so this container-level match is the superfence-specific signal.
    assert re.search(r'<(?:pre|div)[^>]*\bclass="(?:[^"]*\s)?mermaid(?:\s[^"]*)?"', html), (
        "the Mermaid fence did not render as a mermaid-classed container; it was likely "
        "treated as a plain code fence (the superfence was not recognized). HTML:\n"
        + html
    )
    # It is NOT a plain highlighted code block (which would expose the source instead of a
    # diagram); the language-classed code form is the non-superfence fallback we must not hit.
    assert 'class="language-mermaid"' not in html
    # The diagram source survives into the rendered container (the agent's diagram is preserved).
    assert "graph TD" in html
    assert "Plan stage" in html


def test_strict_build_emits_no_strict_error(tmp_path: Path) -> None:
    """The strict build produces no aborting strict-mode error for the Mermaid fence.

    A clean (returncode 0) ``--strict`` build means MkDocs raised no warning-as-error. We
    additionally confirm the captured output carries no aborting strict-mode error marker, so
    the pass is the absence of an error rather than a swallowed one (Req 10.3).
    """
    out = tmp_path / "run"
    out.mkdir()
    site = assemble_site(_report(_mermaid_segment()), default_profile(), None, str(out), _identity())

    built = tmp_path / "_built"
    result = _run_mkdocs_build(site.mkdocs_yml_path, built)
    assert result.returncode == 0, (
        f"strict build failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )
    combined = (result.stdout + result.stderr).lower()
    assert "aborted with" not in combined, result.stdout + result.stderr
    assert "error reading page" not in combined, result.stdout + result.stderr
