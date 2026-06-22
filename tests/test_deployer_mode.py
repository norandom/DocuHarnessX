"""Unit tests for the deploy-mode resolver (github-pages-deploy task 2.1).

These tests pin the *Deploy-mode resolver* boundary (design "Deploy-mode resolver"):
:func:`docuharnessx.deployer.mode.resolve_deploy_mode`, a pure, total, deterministic
function that maps the configured mode value (``DocgenConfig.deploy_mode`` / ``--deploy-mode``,
or ``None``/blank) onto a supported :data:`~docuharnessx.deployer.model.DeployMode`.

Observable completion (tasks.md 2.1): the resolver returns ``emit-ci-workflow`` for an
absent value, returns each valid mode unchanged, and raises the input error for an unknown
value.

Acceptance behaviour pinned here:

* Req 3.2 — absent/empty/whitespace-only ``configured`` defaults to ``emit-ci-workflow``.
* Req 3.3 — a recognised value passes through unchanged.
* Req 3.4 — any other value raises :class:`DeployInputError` naming the bad value and the
  three valid modes, and performs no deploy action (the resolver simply raises).
* Req 3.1 — the resolver admits exactly the three supported modes.

Task 2.1 owns only the resolver — not the workflow renderer, tree writer, command runner,
orchestrator, or stage adapter (later tasks). This file asserts only the resolver contract.
"""

from __future__ import annotations

import typing

import pytest

import docuharnessx.deployer as deployer
from docuharnessx.deployer import DeployInputError, DeployMode
from docuharnessx.deployer import mode as deployer_mode
from docuharnessx.deployer.mode import resolve_deploy_mode

_VALID_MODES: tuple[str, ...] = ("emit-ci-workflow", "gh-deploy", "build-only")


# --------------------------------------------------------------------------- #
# Package namespace surface                                                    #
# --------------------------------------------------------------------------- #


def test_package_reexports_resolver() -> None:
    assert "resolve_deploy_mode" in deployer.__all__
    assert hasattr(deployer, "resolve_deploy_mode")


def test_reexport_is_identity_equal_to_submodule_definition() -> None:
    assert deployer.resolve_deploy_mode is deployer_mode.resolve_deploy_mode
    assert deployer.resolve_deploy_mode is resolve_deploy_mode


def test_module_all_is_self_consistent() -> None:
    assert "resolve_deploy_mode" in deployer_mode.__all__
    assert len(deployer_mode.__all__) == len(set(deployer_mode.__all__))
    for name in deployer_mode.__all__:
        assert hasattr(deployer_mode, name), name


# --------------------------------------------------------------------------- #
# Req 3.2 — absent / empty defaults to emit-ci-workflow                        #
# --------------------------------------------------------------------------- #


def test_none_defaults_to_emit_ci_workflow() -> None:
    assert resolve_deploy_mode(None) == "emit-ci-workflow"


def test_empty_string_defaults_to_emit_ci_workflow() -> None:
    assert resolve_deploy_mode("") == "emit-ci-workflow"


@pytest.mark.parametrize("blank", ["   ", "\t", "\n", "  \t \n "])
def test_whitespace_only_defaults_to_emit_ci_workflow(blank: str) -> None:
    assert resolve_deploy_mode(blank) == "emit-ci-workflow"


# --------------------------------------------------------------------------- #
# Req 3.3 — a recognised value passes through unchanged                        #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("mode", _VALID_MODES)
def test_valid_mode_passes_through(mode: str) -> None:
    assert resolve_deploy_mode(mode) == mode


@pytest.mark.parametrize("mode", _VALID_MODES)
def test_valid_mode_passes_through_with_surrounding_whitespace(mode: str) -> None:
    # A YAML/flag value may carry surrounding whitespace; it is trimmed, not rejected.
    assert resolve_deploy_mode(f"  {mode}  ") == mode


def test_resolver_covers_every_literal_member() -> None:
    # The resolver passes through exactly the DeployMode literal set (Req 3.1).
    for mode in typing.get_args(DeployMode):
        assert resolve_deploy_mode(mode) == mode


# --------------------------------------------------------------------------- #
# Req 3.4 — an unknown value raises DeployInputError naming bad + valid modes  #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "bad",
    [
        "deploy",
        "emit",
        "ci-workflow",
        "gh_deploy",  # underscore, not the hyphenated literal
        "EMIT-CI-WORKFLOW",  # case-sensitive
        "publish",
        "mkdocs",
    ],
)
def test_unknown_value_raises_input_error(bad: str) -> None:
    with pytest.raises(DeployInputError):
        resolve_deploy_mode(bad)


def test_unknown_value_message_names_the_bad_value_and_valid_modes() -> None:
    with pytest.raises(DeployInputError) as exc_info:
        resolve_deploy_mode("bogus-mode")
    message = str(exc_info.value)
    assert "bogus-mode" in message
    for valid in _VALID_MODES:
        assert valid in message


def test_unknown_value_raises_the_base_deploy_error() -> None:
    from docuharnessx.deployer import DeployError

    with pytest.raises(DeployError):
        resolve_deploy_mode("nope")


# --------------------------------------------------------------------------- #
# Determinism / totality                                                       #
# --------------------------------------------------------------------------- #


def test_resolver_is_deterministic() -> None:
    assert resolve_deploy_mode("gh-deploy") == resolve_deploy_mode("gh-deploy")
    assert resolve_deploy_mode(None) == resolve_deploy_mode("")
