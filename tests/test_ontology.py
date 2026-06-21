"""Contract-level re-export tests for task 2.4.

Task 2.4 owns the skeleton's single ontology re-export site. The skeleton must
*consume* the ``ontology-engine`` surface — it adds NO storage, schema, loader,
or profile logic of its own.

Name-clash resolution (design.md task 2.4 / "ontology re-export" implementation
notes): ``ontology-engine`` owns the package ``docuharnessx/ontology/`` (a
directory). Python resolves a package over a same-named top-level module, so a
``docuharnessx/ontology.py`` module would be shadowed and unreachable. The design
therefore pins a ``docuharnessx/_ontology.py`` shim as the single re-export site,
while ``import docuharnessx.ontology`` keeps resolving the real ontology package.
Both must work without breaking the 220 ontology tests.

The frozen ``SegmentStore`` port the skeleton relies on has EXACTLY these
signatures (mirrored verbatim from ``ontology-engine``):

    put(self, segment) -> None
    query(self, where: AxisFilter) -> tuple[Segment, ...]
    list_segments(self) -> tuple[Segment, ...]
    resolve_cross_links(self, segment_id: str) -> tuple[Segment, ...]
"""

from __future__ import annotations

import importlib
import inspect

import pytest

# The exact surface task 2.4 must re-export at the skeleton's single import site.
REEXPORTED = (
    "SegmentStore",
    "AxisFilter",
    "Segment",
    "Vocabulary",
    "load_vocabulary",
    "vocabulary_to_config",
    "default_profile",
)


# --------------------------------------------------------------------------- #
# The package import must still resolve the ontology-engine package.           #
# --------------------------------------------------------------------------- #


def test_package_import_resolves_to_ontology_engine_package() -> None:
    """`import docuharnessx.ontology` must resolve the package, not a module."""
    pkg = importlib.import_module("docuharnessx.ontology")
    # A package has __path__; a plain module does not.
    assert hasattr(pkg, "__path__"), "docuharnessx.ontology must be the package"
    assert pkg.__file__.endswith("ontology/__init__.py")


# --------------------------------------------------------------------------- #
# The skeleton's single re-export site exposes the consumed surface.           #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("name", REEXPORTED)
def test_reexport_site_exposes_consumed_symbol(name: str) -> None:
    shim = importlib.import_module("docuharnessx._ontology")
    assert hasattr(shim, name), f"re-export site missing {name}"


@pytest.mark.parametrize("name", REEXPORTED)
def test_reexport_is_the_same_object_as_ontology_engine(name: str) -> None:
    """Re-exports must be identical objects — pure aliases, not copies."""
    shim = importlib.import_module("docuharnessx._ontology")
    engine = importlib.import_module("docuharnessx.ontology")
    assert getattr(shim, name) is getattr(engine, name)


def test_reexport_site_declares_all() -> None:
    shim = importlib.import_module("docuharnessx._ontology")
    exported = set(shim.__all__)
    for name in REEXPORTED:
        assert name in exported, f"{name} not in docuharnessx._ontology.__all__"


# --------------------------------------------------------------------------- #
# The re-export site adds NO concrete storage / schema / loader logic.         #
# --------------------------------------------------------------------------- #


def test_reexport_site_defines_no_local_storage_class() -> None:
    """No concrete store / schema / loader is defined in the shim itself."""
    shim = importlib.import_module("docuharnessx._ontology")
    for member_name, member in inspect.getmembers(shim, inspect.isclass):
        # Anything that *is* a class must come from the ontology-engine package,
        # never be defined locally in the shim module.
        assert member.__module__.startswith("docuharnessx.ontology"), (
            f"{member_name} ({member.__module__}) must not be defined in the "
            "re-export shim; the shim re-exports only"
        )


def test_reexport_site_defines_no_local_functions() -> None:
    """The loader / serializer / profile are re-exported, not reimplemented."""
    shim = importlib.import_module("docuharnessx._ontology")
    for fn_name, fn in inspect.getmembers(shim, inspect.isfunction):
        assert fn.__module__.startswith("docuharnessx.ontology"), (
            f"{fn_name} ({fn.__module__}) must not be defined in the re-export "
            "shim; loader/serializer/profile come from ontology-engine"
        )


# --------------------------------------------------------------------------- #
# The consumed SegmentStore port has the four pinned signatures verbatim.      #
# --------------------------------------------------------------------------- #


def test_segment_store_has_the_four_pinned_methods() -> None:
    from docuharnessx._ontology import SegmentStore

    for method in ("put", "query", "list_segments", "resolve_cross_links"):
        assert hasattr(SegmentStore, method), f"SegmentStore missing {method}"


def test_segment_store_signatures_match_the_pinned_contract() -> None:
    from docuharnessx._ontology import SegmentStore

    put = inspect.signature(SegmentStore.put)
    assert list(put.parameters) == ["self", "segment"]

    query = inspect.signature(SegmentStore.query)
    assert list(query.parameters) == ["self", "where"]

    list_segments = inspect.signature(SegmentStore.list_segments)
    assert list(list_segments.parameters) == ["self"]

    resolve = inspect.signature(SegmentStore.resolve_cross_links)
    assert list(resolve.parameters) == ["self", "segment_id"]


def test_axis_filter_and_segment_are_usable_value_types() -> None:
    """AxisFilter and Segment co-imports are concrete usable types."""
    from docuharnessx._ontology import AxisFilter, Segment

    # AxisFilter default-constructs (empty filter matches all).
    flt = AxisFilter()
    assert flt.roles == ()
    assert flt.intents == ()
    assert flt.subjects == ()
    # Segment is a class.
    assert isinstance(Segment, type)


def test_default_profile_and_loader_round_trip_via_reexports() -> None:
    """The re-exported loader/serializer/profile actually interoperate."""
    from docuharnessx._ontology import (
        Vocabulary,
        default_profile,
        vocabulary_to_config,
    )

    vocab = default_profile()
    assert isinstance(vocab, Vocabulary)
    cfg = vocabulary_to_config(vocab)
    assert isinstance(cfg, dict)
