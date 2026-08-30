"""Default ``dhx run`` path must not use the retired outline authoring model.

Task 5.1 / Req 6.1, 10.1–10.4: inspect the operator run modules for the
retired fallback renderer and dummy outer harness. These files must not call
``render_fallback_body``, compose ``make_docgen``, or keep the skeleton
``DONE`` bus leftovers.
"""

from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]

_DEFAULT_RUN_FILES = (
    _ROOT / "docuharnessx" / "cli.py",
    _ROOT / "docuharnessx" / "pipeline" / "run.py",
    _ROOT / "docuharnessx" / "composition" / "explore_writer.py",
)

_RETIRED_TOKENS = (
    "render_fallback_body",
    "make_docgen",
    "docuharnessx.composition.fallback",
    "docuharnessx.composition.blueprint",
    "docuharnessx.planning.matrix",
    "docuharnessx.stages",
)

_CLI_DUMMY_LEFTOVERS = (
    "_SKELETON_TASK_DESCRIPTION",
    "_SKELETON_MAX_STEPS",
    "_locate_journal_jsonl",
    "_thread_deploy_mode",
)


def test_default_run_path_does_not_call_render_fallback_body() -> None:
    for path in _DEFAULT_RUN_FILES:
        source = path.read_text(encoding="utf-8")
        assert "render_fallback_body" not in source, (
            f"{path.relative_to(_ROOT)} still names render_fallback_body"
        )


def test_default_run_path_does_not_import_retired_authoring() -> None:
    for path in _DEFAULT_RUN_FILES:
        source = path.read_text(encoding="utf-8")
        for token in _RETIRED_TOKENS:
            assert token not in source, (
                f"{path.relative_to(_ROOT)} still names retired token {token!r}"
            )


def test_cli_has_no_dummy_harness_bus() -> None:
    source = (_ROOT / "docuharnessx" / "cli.py").read_text(encoding="utf-8")
    for token in _CLI_DUMMY_LEFTOVERS:
        assert token not in source, f"cli.py still defines dummy leftover {token}"
