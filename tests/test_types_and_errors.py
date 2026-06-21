"""Unit import tests for task 1.2 (shared types, slot-key constants, errors).

Task 1.2 owns exactly two modules — ``docuharnessx.types`` and
``docuharnessx.errors`` — and pins their observable contract:

* ``types.py`` exposes ``StageName`` and the slot-key constants for the
  target repo, output dir, segment-store handle, and the loaded ``Vocabulary``
  (``SLOT_VOCABULARY``). It must NOT define a ``RoleId`` alias or any fixed
  role list — roles are derived from the loaded ``Vocabulary`` owned by
  ``ontology-engine`` (Req 6.2; design "NO RoleId alias").
* ``errors.py`` exposes the five explicit error types ``ConfigError``,
  ``ModelResolutionError``, ``TargetRepoError``, ``DependencyError``, and
  ``OntologyConfigError`` (Req 1.4, 6.2; design Error Handling section).

These are the boundary for task 1.2: types + errors only.
"""

from __future__ import annotations

import importlib
import typing

import pytest

# Canonical pipeline order the rest of the skeleton (StageRegistry, make_docgen)
# relies on: ingest -> analyze -> classify -> plan -> write -> review ->
# assemble -> deploy (Req 5.4).
CANONICAL_STAGES = (
    "ingest",
    "analyze",
    "classify",
    "plan",
    "write",
    "review",
    "assemble",
    "deploy",
)


# --------------------------------------------------------------------------- #
# types.py
# --------------------------------------------------------------------------- #


def test_types_module_imports() -> None:
    mod = importlib.import_module("docuharnessx.types")
    assert mod is not None


def test_stagename_is_exported() -> None:
    mod = importlib.import_module("docuharnessx.types")
    assert hasattr(mod, "StageName")


def test_stagename_covers_the_eight_canonical_stages() -> None:
    """StageName must constrain to exactly the eight canonical stage names."""
    mod = importlib.import_module("docuharnessx.types")
    args = typing.get_args(mod.StageName)
    assert set(args) == set(CANONICAL_STAGES)
    # canonical ordering is preserved by the Literal definition.
    assert tuple(args) == CANONICAL_STAGES


def test_stage_names_tuple_in_canonical_order() -> None:
    """A concrete, ordered tuple of names is exposed for the registry to use."""
    mod = importlib.import_module("docuharnessx.types")
    assert hasattr(mod, "STAGE_NAMES")
    assert tuple(mod.STAGE_NAMES) == CANONICAL_STAGES


@pytest.mark.parametrize(
    "const_name",
    ["SLOT_TARGET_REPO", "SLOT_OUTPUT_DIR", "SLOT_SEGMENT_STORE", "SLOT_VOCABULARY"],
)
def test_slot_key_constants_exist_and_are_nonempty_strings(const_name: str) -> None:
    mod = importlib.import_module("docuharnessx.types")
    assert hasattr(mod, const_name), f"missing slot-key constant {const_name}"
    value = getattr(mod, const_name)
    assert isinstance(value, str)
    assert value  # non-empty


def test_slot_key_constants_are_distinct() -> None:
    mod = importlib.import_module("docuharnessx.types")
    values = [
        mod.SLOT_TARGET_REPO,
        mod.SLOT_OUTPUT_DIR,
        mod.SLOT_SEGMENT_STORE,
        mod.SLOT_VOCABULARY,
    ]
    assert len(set(values)) == len(values), "slot keys must be unique"


def test_types_defines_no_roleid_alias_and_no_fixed_role_list() -> None:
    """Roles come from the loaded Vocabulary; the skeleton must not pin them."""
    mod = importlib.import_module("docuharnessx.types")
    assert not hasattr(mod, "RoleId"), "types.py must NOT define a RoleId alias"
    assert not hasattr(mod, "ROLES"), "types.py must NOT hardcode a fixed role list"
    assert not hasattr(mod, "ROLE_IDS")


def test_types_all_exports_named_symbols() -> None:
    mod = importlib.import_module("docuharnessx.types")
    exported = set(mod.__all__)
    for name in (
        "StageName",
        "STAGE_NAMES",
        "SLOT_TARGET_REPO",
        "SLOT_OUTPUT_DIR",
        "SLOT_SEGMENT_STORE",
        "SLOT_VOCABULARY",
    ):
        assert name in exported, f"{name} not in docuharnessx.types.__all__"


# --------------------------------------------------------------------------- #
# errors.py
# --------------------------------------------------------------------------- #

ERROR_NAMES = (
    "ConfigError",
    "ModelResolutionError",
    "TargetRepoError",
    "DependencyError",
    "OntologyConfigError",
)


def test_errors_module_imports() -> None:
    mod = importlib.import_module("docuharnessx.errors")
    assert mod is not None


@pytest.mark.parametrize("name", ERROR_NAMES)
def test_error_class_exists_and_is_exception_subclass(name: str) -> None:
    mod = importlib.import_module("docuharnessx.errors")
    assert hasattr(mod, name), f"missing error class {name}"
    cls = getattr(mod, name)
    assert isinstance(cls, type)
    assert issubclass(cls, Exception)


@pytest.mark.parametrize("name", ERROR_NAMES)
def test_error_carries_its_message(name: str) -> None:
    mod = importlib.import_module("docuharnessx.errors")
    cls = getattr(mod, name)
    err = cls("boom")
    assert str(err) == "boom"


def test_errors_all_exports_named_symbols() -> None:
    mod = importlib.import_module("docuharnessx.errors")
    exported = set(mod.__all__)
    for name in ERROR_NAMES:
        assert name in exported, f"{name} not in docuharnessx.errors.__all__"


def test_errors_share_a_common_base() -> None:
    """All explicit errors derive from a single skeleton base for catch-all."""
    mod = importlib.import_module("docuharnessx.errors")
    assert hasattr(mod, "DocuHarnessXError")
    base = mod.DocuHarnessXError
    assert issubclass(base, Exception)
    for name in ERROR_NAMES:
        cls = getattr(mod, name)
        assert issubclass(cls, base), f"{name} should derive from DocuHarnessXError"
