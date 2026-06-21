"""Scaffold tests for task 1.1 (Requirement 1: installable package and environment).

These tests pin the observable contract of the package root that task 1.1 owns:

* ``import docuharnessx`` works and exposes a version (Req 1.5 — package root).
* The top-level package contains the ``stages`` sub-package and the ``cli``
  module (Req 1.3 — package layout; ``cli`` carries the ``dhx`` entry point).
* The ``dhx`` console-script entry point is declared and runnable as
  ``main(["--help"])`` (Req 1.2 — exposes the ``dhx`` command).
* ``main`` exposes ``init`` and run subcommand placeholders so 4.x can flesh
  them out without renaming the entry point.

Task 1.1 does NOT own ontology, config, model resolution, etc. — those live in
later tasks. This file only asserts the scaffold contract.
"""

from __future__ import annotations

import importlib
import importlib.metadata as md

import pytest


def test_docuharnessx_imports_and_has_version() -> None:
    pkg = importlib.import_module("docuharnessx")
    assert isinstance(pkg.__version__, str)
    assert pkg.__version__  # non-empty


def test_docuharnessx_reexports_make_docgen() -> None:
    # Req 1.5: the package root re-exports the bundle composition seam so callers
    # reach it as ``docuharnessx.make_docgen`` (not only via the bundle module).
    import docuharnessx
    from docuharnessx.bundle import make_docgen as bundle_make_docgen

    assert docuharnessx.make_docgen is bundle_make_docgen
    assert "make_docgen" in docuharnessx.__all__


def test_stages_subpackage_exists() -> None:
    # Req 1.3: top-level package provides the stages sub-package.
    stages = importlib.import_module("docuharnessx.stages")
    assert stages is not None


def test_cli_module_exposes_main() -> None:
    # Req 1.3 / 1.2: the CLI module exists and exposes a callable main().
    cli = importlib.import_module("docuharnessx.cli")
    assert callable(cli.main)


def test_dhx_console_script_is_registered() -> None:
    # Req 1.2: the dhx command is on the environment path (entry point declared).
    eps = md.entry_points(group="console_scripts")
    names = {ep.name: ep.value for ep in eps}
    assert "dhx" in names, f"dhx console-script not registered: {sorted(names)}"
    assert names["dhx"] == "docuharnessx.cli:main"


def test_dhx_help_exits_zero() -> None:
    # Req 1.2: dhx --help runs (argparse raises SystemExit(0) for --help).
    from docuharnessx import cli

    with pytest.raises(SystemExit) as exc:
        cli.main(["--help"])
    assert exc.value.code == 0


def test_dhx_has_init_and_run_subcommands() -> None:
    # The stub must expose init + run placeholders for 4.x to flesh out.
    from docuharnessx import cli

    with pytest.raises(SystemExit) as exc:
        cli.main(["init", "--help"])
    assert exc.value.code == 0

    with pytest.raises(SystemExit) as exc:
        cli.main(["run", "--help"])
    assert exc.value.code == 0


def test_dhx_no_args_returns_nonzero() -> None:
    # Invoking with no subcommand should not crash; it returns a non-zero code.
    from docuharnessx import cli

    rc = cli.main([])
    assert isinstance(rc, int)
    assert rc != 0
