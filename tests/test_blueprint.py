"""Tests for the package-shipped blueprint identity (task 1.1, boundary: Blueprint).

Pins the named contract operators adopt:

* ``import docuharnessx.blueprint`` exposes ``BLUEPRINT_NAME`` and
  ``BLUEPRINT_VERSION`` as non-empty strings (Req 1.2 — name and version exist
  to be recorded at setup; Req 10.1 — evolution starts from this identity).
* The name is stable: ``docuharnessx-default``.
* The version is the shipped package contract ``2.0.0`` (bumped only when the
  default vocabulary/page contract changes).

This module is distinct from :mod:`docuharnessx.composition.blueprint` (COBESY
composition blueprint). These tests touch no model and no network.
"""

from __future__ import annotations

import importlib


def test_blueprint_module_exposes_nonempty_name_and_version() -> None:
    blueprint = importlib.import_module("docuharnessx.blueprint")

    assert isinstance(blueprint.BLUEPRINT_NAME, str)
    assert blueprint.BLUEPRINT_NAME
    assert isinstance(blueprint.BLUEPRINT_VERSION, str)
    assert blueprint.BLUEPRINT_VERSION


def test_blueprint_name_is_stable() -> None:
    from docuharnessx.blueprint import BLUEPRINT_NAME

    assert BLUEPRINT_NAME == "docuharnessx-default"


def test_blueprint_version_is_shipped_contract() -> None:
    from docuharnessx.blueprint import BLUEPRINT_VERSION

    assert BLUEPRINT_VERSION == "2.0.0"
