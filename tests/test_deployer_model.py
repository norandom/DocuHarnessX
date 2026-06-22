"""Unit tests for the frozen deploy data model (github-pages-deploy task 1.1).

These tests pin the *model boundary* (design "DeployResult model") of the Wave 3
``github-pages-deploy`` core: the frozen, deeply-immutable :class:`DeployResult` value
object, the single :data:`DEPLOY_RESULT_SCHEMA_VERSION` version authority, the
:data:`DeployMode` / :data:`DeployStatus` literals, and the :class:`DeployError` /
:class:`DeployInputError` error family.

Observable completion (tasks.md 1.1): constructing a :class:`DeployResult` yields an
immutable value whose ``schema_version`` field equals the module's version constant and
that compares by value; the deploy-mode literal admits exactly the three modes
(``emit-ci-workflow``, ``gh-deploy``, ``build-only``).

Task 1.1 owns only the model — it does NOT own the mode resolver, the workflow
renderer, the tree writer, the command runner, the orchestrator, or the stage adapter
(later tasks). This file asserts only the model contract.
"""

from __future__ import annotations

import dataclasses
import typing

import pytest

import docuharnessx.deployer as deployer
from docuharnessx.deployer import (
    DEPLOY_RESULT_SCHEMA_VERSION,
    DeployError,
    DeployInputError,
    DeployMode,
    DeployResult,
    DeployStatus,
)
from docuharnessx.deployer import model as deployer_model


# --------------------------------------------------------------------------- #
# Sample builder                                                               #
# --------------------------------------------------------------------------- #


def _result(
    *,
    schema_version: int = DEPLOY_RESULT_SCHEMA_VERSION,
    mode: str = "emit-ci-workflow",
    status: str = "emitted",
    target_pages_url: str = "https://norandom.github.io/malware_hashes/",
    written_paths: tuple[str, ...] = (
        "/target/mkdocs.yml",
        "/target/docs",
        "/target/.github/workflows/docs.yml",
    ),
    built_path: str = "/out/site/site",
    detail: str = "emitted 3 files; build ok",
) -> DeployResult:
    return DeployResult(
        schema_version=schema_version,
        mode=mode,  # type: ignore[arg-type]
        status=status,  # type: ignore[arg-type]
        target_pages_url=target_pages_url,
        written_paths=written_paths,
        built_path=built_path,
        detail=detail,
    )


# --------------------------------------------------------------------------- #
# Package namespace surface                                                    #
# --------------------------------------------------------------------------- #


def test_package_exports_all_model_types_via_all() -> None:
    expected = {
        "DEPLOY_RESULT_SCHEMA_VERSION",
        "DeployMode",
        "DeployStatus",
        "DeployResult",
        "DeployError",
        "DeployInputError",
    }
    assert expected.issubset(set(deployer.__all__))
    for name in expected:
        assert hasattr(deployer, name), name


def test_reexports_are_identity_equal_to_submodule_definitions() -> None:
    assert deployer.DeployResult is deployer_model.DeployResult
    assert deployer.DeployError is deployer_model.DeployError
    assert deployer.DeployInputError is deployer_model.DeployInputError
    assert (
        deployer.DEPLOY_RESULT_SCHEMA_VERSION
        is deployer_model.DEPLOY_RESULT_SCHEMA_VERSION
    )
    assert deployer.DeployMode is deployer_model.DeployMode
    assert deployer.DeployStatus is deployer_model.DeployStatus


def test_all_is_self_consistent_and_unique() -> None:
    assert len(deployer.__all__) == len(set(deployer.__all__))
    for name in deployer.__all__:
        assert hasattr(deployer, name), name


def test_star_import_exposes_exactly_all() -> None:
    namespace: dict[str, object] = {}
    exec("from docuharnessx.deployer import *", namespace)  # noqa: S102
    exported = {k for k in namespace if not k.startswith("__")}
    assert exported == set(deployer.__all__)


# --------------------------------------------------------------------------- #
# Version authority                                                            #
# --------------------------------------------------------------------------- #


def test_schema_version_is_one() -> None:
    assert DEPLOY_RESULT_SCHEMA_VERSION == 1


def test_schema_version_is_a_positive_int() -> None:
    assert isinstance(DEPLOY_RESULT_SCHEMA_VERSION, int)
    assert DEPLOY_RESULT_SCHEMA_VERSION >= 1


def test_result_carries_the_schema_version() -> None:
    assert _result().schema_version == DEPLOY_RESULT_SCHEMA_VERSION


# --------------------------------------------------------------------------- #
# Mode / status literals                                                       #
# --------------------------------------------------------------------------- #


def test_deploy_mode_admits_exactly_the_three_modes() -> None:
    assert set(typing.get_args(DeployMode)) == {
        "emit-ci-workflow",
        "gh-deploy",
        "build-only",
    }


def test_deploy_status_admits_exactly_the_four_statuses() -> None:
    assert set(typing.get_args(DeployStatus)) == {
        "emitted",
        "built",
        "published",
        "failed",
    }


# --------------------------------------------------------------------------- #
# Construction succeeds                                                        #
# --------------------------------------------------------------------------- #


def test_construct_deploy_result() -> None:
    result = _result()
    assert result.schema_version == DEPLOY_RESULT_SCHEMA_VERSION
    assert result.mode == "emit-ci-workflow"
    assert result.status == "emitted"
    assert result.target_pages_url == "https://norandom.github.io/malware_hashes/"
    assert result.written_paths == (
        "/target/mkdocs.yml",
        "/target/docs",
        "/target/.github/workflows/docs.yml",
    )
    assert result.built_path == "/out/site/site"
    assert result.detail == "emitted 3 files; build ok"


def test_written_paths_is_a_tuple() -> None:
    assert isinstance(_result().written_paths, tuple)


def test_construct_result_for_each_mode_and_status() -> None:
    for mode in ("emit-ci-workflow", "gh-deploy", "build-only"):
        for status in ("emitted", "built", "published", "failed"):
            result = _result(mode=mode, status=status)
            assert result.mode == mode
            assert result.status == status


# --------------------------------------------------------------------------- #
# Immutability (mutating a field raises) — deeply immutable                    #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("schema_version", 999),
        ("mode", "gh-deploy"),
        ("status", "failed"),
        ("target_pages_url", "https://x/"),
        ("written_paths", ()),
        ("built_path", "/x"),
        ("detail", "x"),
    ],
)
def test_result_is_immutable(field_name: str, value: object) -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(_result(), field_name, value)


# --------------------------------------------------------------------------- #
# Structural equality from equal inputs                                        #
# --------------------------------------------------------------------------- #


def test_results_from_equal_inputs_are_equal() -> None:
    assert _result() == _result()


def test_results_differ_when_inputs_differ() -> None:
    assert _result(status="failed") != _result()
    assert _result(written_paths=()) != _result()
    assert _result(mode="build-only") != _result()


# --------------------------------------------------------------------------- #
# Deep immutability => hashable (all-string/int members + tuple)               #
# --------------------------------------------------------------------------- #


def test_result_is_hashable() -> None:
    assert hash(_result()) == hash(_result())


# --------------------------------------------------------------------------- #
# Error hierarchy                                                              #
# --------------------------------------------------------------------------- #


def test_error_hierarchy() -> None:
    assert issubclass(DeployError, Exception)
    assert issubclass(DeployInputError, DeployError)


def test_deploy_input_error_is_raisable() -> None:
    with pytest.raises(DeployInputError):
        raise DeployInputError("missing slot: docuharnessx.assembled_site")


def test_deploy_input_error_catchable_as_base() -> None:
    with pytest.raises(DeployError):
        raise DeployInputError("x")


def test_deploy_error_independent_of_other_error_families() -> None:
    # The deploy error family is kept independent of the other specs'
    # families (matching how review / writer / planning / assembler each keep
    # their own), so a DeployError is none of them and vice versa.
    from docuharnessx.assembler import AssemblerError
    from docuharnessx.composition import WriterError
    from docuharnessx.planning import PlanningError
    from docuharnessx.review import ReviewError

    assert not issubclass(DeployError, ReviewError)
    assert not issubclass(DeployError, WriterError)
    assert not issubclass(DeployError, PlanningError)
    assert not issubclass(DeployError, AssemblerError)
    assert not issubclass(ReviewError, DeployError)
    assert not issubclass(WriterError, DeployError)
    assert not issubclass(PlanningError, DeployError)
    assert not issubclass(AssemblerError, DeployError)
