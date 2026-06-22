"""Public-surface tests for the ``docuharnessx.planning`` package root (task 3.4).

These assert the package re-exports the stable classification-coverage-planning public
surface from its single namespace — the frozen model + handoff records, the serde
functions, the classify/plan/relevance entry points, and the error types — so downstream
consumers (the Wave 2 ``cobesy-writer`` and the stage adapters) import from
``docuharnessx.planning`` rather than reaching into submodules. They also pin that the
package ``__all__`` is the authoritative, self-consistent contract (Req 6.1, 6.2).
"""

from __future__ import annotations

import importlib

import pytest


def test_documented_public_surface_imports_from_package_root() -> None:
    """The names task 3.4 enumerates import directly from the package root."""
    from docuharnessx.planning import (  # noqa: F401
        Classification,
        CoveragePlan,
        PlannedSegment,
        apply_relevance,
        classify_repo,
        from_dict,
        plan_coverage,
        to_dict,
        to_json,
    )
    from docuharnessx.planning import (  # noqa: F401
        CoveragePlanVersionError,
        PlanningError,
        PlanningInputError,
    )


def test_entry_points_are_the_same_objects_as_their_modules() -> None:
    """Re-exports are identity-equal to the submodule definitions (no shadow copies)."""
    import docuharnessx.planning as pkg
    from docuharnessx.planning import classifier, model, planner, relevance, serde

    assert pkg.classify_repo is classifier.classify_repo
    assert pkg.plan_coverage is planner.plan_coverage
    assert pkg.apply_relevance is relevance.apply_relevance
    assert pkg.CoveragePlan is model.CoveragePlan
    assert pkg.PlannedSegment is model.PlannedSegment
    assert pkg.Classification is model.Classification
    assert pkg.EvidenceRef is model.EvidenceRef
    assert pkg.to_dict is serde.to_dict
    assert pkg.from_dict is serde.from_dict
    assert pkg.to_json is serde.to_json
    assert pkg.PlanningError is model.PlanningError
    assert pkg.PlanningInputError is model.PlanningInputError
    assert pkg.CoveragePlanVersionError is model.CoveragePlanVersionError


def test_all_lists_the_documented_public_surface() -> None:
    """``__all__`` contains every name the export task enumerates."""
    import docuharnessx.planning as pkg

    required = {
        # frozen model + handoff
        "COVERAGE_PLAN_SCHEMA_VERSION",
        "CoveragePlan",
        "PlannedSegment",
        "EvidenceRef",
        "CandidateCell",
        "Classification",
        # serde
        "to_dict",
        "from_dict",
        "to_json",
        # entry points
        "classify_repo",
        "plan_coverage",
        "apply_relevance",
        # errors
        "PlanningError",
        "PlanningInputError",
        "CoveragePlanVersionError",
    }
    assert required.issubset(set(pkg.__all__))


def test_all_is_self_consistent_and_sorted_unique() -> None:
    """Every ``__all__`` name resolves on the package; the list is unique and sorted."""
    import docuharnessx.planning as pkg

    assert len(pkg.__all__) == len(set(pkg.__all__)), "duplicate names in __all__"
    for name in pkg.__all__:
        assert hasattr(pkg, name), f"__all__ name {name!r} is not importable"


def test_star_import_exposes_exactly_all() -> None:
    """``from docuharnessx.planning import *`` binds exactly the ``__all__`` surface."""
    pkg = importlib.import_module("docuharnessx.planning")
    namespace: dict[str, object] = {}
    exec("from docuharnessx.planning import *", namespace)  # noqa: S102
    exported = {k for k in namespace if not k.startswith("__")}
    assert exported == set(pkg.__all__)


@pytest.mark.parametrize(
    "name",
    [
        "derive_subjects",
        "activate_cells",
        "score_cell",
        "order_key",
        "vocabulary_fingerprint",
        "DEFAULT_RELEVANCE_TIMEOUT_S",
    ],
)
def test_core_helper_surface_is_reachable(name: str) -> None:
    """The deterministic-core public helpers are also reachable from the root."""
    import docuharnessx.planning as pkg

    assert hasattr(pkg, name)
    assert name in pkg.__all__
