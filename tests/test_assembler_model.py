"""Unit tests for the frozen assembled-site data model (mkdocs-site-assembler task 1.2).

These tests pin the *model boundary* (design "AssembledSite model") of the Wave 3
``mkdocs-site-assembler`` core: the frozen, deeply-immutable value objects
(:class:`SiteIdentity`, :class:`AssembledSite`), the single
:data:`ASSEMBLED_SITE_SCHEMA_VERSION` version authority, and the
:class:`AssemblerError` / :class:`AssemblerInputError` error family.

Observable completion (tasks.md 1.2): importing the model exposes the two value
objects, the version constant, and the error types (via the package ``__all__`` and as
identity-equal re-exports of the submodule definitions); constructing an
:class:`AssembledSite` from sample values yields a frozen, structurally-equal value
object (two equal constructions compare equal).

Task 1.2 owns only the model — it does NOT own the identity resolver, the renderers,
the writer, or the stage adapter (later tasks). This file asserts only the model
contract.
"""

from __future__ import annotations

import dataclasses

import pytest

import docuharnessx.assembler as assembler
from docuharnessx.assembler import (
    ASSEMBLED_SITE_SCHEMA_VERSION,
    AssembledSite,
    AssemblerError,
    AssemblerInputError,
    SiteIdentity,
)
from docuharnessx.assembler import model as assembler_model


# --------------------------------------------------------------------------- #
# Sample builders                                                              #
# --------------------------------------------------------------------------- #


def _identity(
    *,
    site_name: str = "malware_hashes",
    repo_name: str = "norandom/malware_hashes",
    repo_url: str = "https://github.com/norandom/malware_hashes",
    site_url: str = "https://norandom.github.io/malware_hashes/",
    base_path: str = "/malware_hashes/",
    edit_uri: str = "edit/main/docs/",
) -> SiteIdentity:
    return SiteIdentity(
        site_name=site_name,
        repo_name=repo_name,
        repo_url=repo_url,
        site_url=site_url,
        base_path=base_path,
        edit_uri=edit_uri,
    )


def _site(
    *,
    schema_version: int = ASSEMBLED_SITE_SCHEMA_VERSION,
    site_dir: str = "/out/site",
    docs_dir: str = "/out/site/docs",
    mkdocs_yml_path: str = "/out/site/mkdocs.yml",
    identity: SiteIdentity | None = None,
    page_count: int = 3,
    role_page_count: int = 2,
) -> AssembledSite:
    return AssembledSite(
        schema_version=schema_version,
        site_dir=site_dir,
        docs_dir=docs_dir,
        mkdocs_yml_path=mkdocs_yml_path,
        identity=_identity() if identity is None else identity,
        page_count=page_count,
        role_page_count=role_page_count,
    )


# --------------------------------------------------------------------------- #
# Package namespace surface                                                    #
# --------------------------------------------------------------------------- #


def test_package_exports_all_model_types_via_all() -> None:
    expected = {
        "ASSEMBLED_SITE_SCHEMA_VERSION",
        "SiteIdentity",
        "AssembledSite",
        "AssemblerError",
        "AssemblerInputError",
    }
    assert expected.issubset(set(assembler.__all__))
    for name in expected:
        assert hasattr(assembler, name), name


def test_reexports_are_identity_equal_to_submodule_definitions() -> None:
    assert assembler.SiteIdentity is assembler_model.SiteIdentity
    assert assembler.AssembledSite is assembler_model.AssembledSite
    assert assembler.AssemblerError is assembler_model.AssemblerError
    assert assembler.AssemblerInputError is assembler_model.AssemblerInputError
    assert (
        assembler.ASSEMBLED_SITE_SCHEMA_VERSION
        is assembler_model.ASSEMBLED_SITE_SCHEMA_VERSION
    )


def test_all_is_self_consistent_and_unique() -> None:
    assert len(assembler.__all__) == len(set(assembler.__all__))
    for name in assembler.__all__:
        assert hasattr(assembler, name), name


def test_star_import_exposes_exactly_all() -> None:
    namespace: dict[str, object] = {}
    exec("from docuharnessx.assembler import *", namespace)  # noqa: S102
    exported = {k for k in namespace if not k.startswith("__")}
    assert exported == set(assembler.__all__)


# --------------------------------------------------------------------------- #
# Version authority                                                            #
# --------------------------------------------------------------------------- #


def test_schema_version_is_one() -> None:
    assert ASSEMBLED_SITE_SCHEMA_VERSION == 1


def test_schema_version_is_a_positive_int() -> None:
    assert isinstance(ASSEMBLED_SITE_SCHEMA_VERSION, int)
    assert ASSEMBLED_SITE_SCHEMA_VERSION >= 1


def test_site_carries_the_schema_version() -> None:
    assert _site().schema_version == ASSEMBLED_SITE_SCHEMA_VERSION


# --------------------------------------------------------------------------- #
# Construction succeeds                                                        #
# --------------------------------------------------------------------------- #


def test_construct_site_identity() -> None:
    ident = _identity()
    assert ident.site_name == "malware_hashes"
    assert ident.repo_name == "norandom/malware_hashes"
    assert ident.repo_url == "https://github.com/norandom/malware_hashes"
    assert ident.site_url == "https://norandom.github.io/malware_hashes/"
    assert ident.base_path == "/malware_hashes/"
    assert ident.edit_uri == "edit/main/docs/"


def test_construct_assembled_site() -> None:
    site = _site()
    assert site.schema_version == ASSEMBLED_SITE_SCHEMA_VERSION
    assert site.site_dir == "/out/site"
    assert site.docs_dir == "/out/site/docs"
    assert site.mkdocs_yml_path == "/out/site/mkdocs.yml"
    assert site.identity == _identity()
    assert site.page_count == 3
    assert site.role_page_count == 2


def test_assembled_site_embeds_the_identity_value_object() -> None:
    ident = _identity(site_name="custom")
    site = _site(identity=ident)
    assert isinstance(site.identity, SiteIdentity)
    assert site.identity is ident
    assert site.identity.site_name == "custom"


# --------------------------------------------------------------------------- #
# Immutability (mutating a field raises) — deeply immutable                    #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("obj", "field_name", "value"),
    [
        (_identity(), "site_name", "x"),
        (_identity(), "repo_name", "x"),
        (_identity(), "repo_url", "x"),
        (_identity(), "site_url", "x"),
        (_identity(), "base_path", "/x/"),
        (_identity(), "edit_uri", "x"),
        (_site(), "schema_version", 999),
        (_site(), "site_dir", "/x"),
        (_site(), "docs_dir", "/x"),
        (_site(), "mkdocs_yml_path", "/x"),
        (_site(), "identity", _identity(site_name="other")),
        (_site(), "page_count", 99),
        (_site(), "role_page_count", 99),
    ],
)
def test_value_objects_are_immutable(
    obj: object, field_name: str, value: object
) -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(obj, field_name, value)


# --------------------------------------------------------------------------- #
# Structural equality from equal inputs                                        #
# --------------------------------------------------------------------------- #


def test_identities_from_equal_inputs_are_equal() -> None:
    assert _identity() == _identity()


def test_sites_from_equal_inputs_are_equal() -> None:
    assert _site() == _site()


def test_sites_differ_when_inputs_differ() -> None:
    assert _site(page_count=5) != _site()
    assert _site(identity=_identity(site_name="other")) != _site()


# --------------------------------------------------------------------------- #
# Deep immutability => hashable (all-string/int members + frozen nested)       #
# --------------------------------------------------------------------------- #


def test_identity_is_hashable() -> None:
    assert hash(_identity()) == hash(_identity())


def test_assembled_site_is_hashable() -> None:
    assert hash(_site()) == hash(_site())


# --------------------------------------------------------------------------- #
# Error hierarchy                                                              #
# --------------------------------------------------------------------------- #


def test_error_hierarchy() -> None:
    assert issubclass(AssemblerError, Exception)
    assert issubclass(AssemblerInputError, AssemblerError)


def test_assembler_input_error_is_raisable() -> None:
    with pytest.raises(AssemblerInputError):
        raise AssemblerInputError("missing slot: docuharnessx.review_report")


def test_assembler_input_error_catchable_as_base() -> None:
    with pytest.raises(AssemblerError):
        raise AssemblerInputError("x")


def test_assembler_error_independent_of_review_writer_planning_errors() -> None:
    # The assembler error family is kept independent of the other specs'
    # families (matching how review / writer / planning each keep their own),
    # so an AssemblerError is none of them and vice versa.
    from docuharnessx.composition import WriterError
    from docuharnessx.planning import PlanningError
    from docuharnessx.review import ReviewError

    assert not issubclass(AssemblerError, ReviewError)
    assert not issubclass(AssemblerError, WriterError)
    assert not issubclass(AssemblerError, PlanningError)
    assert not issubclass(ReviewError, AssemblerError)
    assert not issubclass(WriterError, AssemblerError)
    assert not issubclass(PlanningError, AssemblerError)
