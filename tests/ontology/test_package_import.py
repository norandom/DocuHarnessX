"""Scaffolding test for the ontology subpackage (task 1.1).

Verifies that ``docuharnessx.ontology`` is importable and discoverable so
later tasks can populate the public API surface.
"""

from types import ModuleType


def test_ontology_package_importable():
    import docuharnessx.ontology as ontology

    assert isinstance(ontology, ModuleType)


def test_ontology_package_is_a_package():
    import docuharnessx.ontology as ontology

    # A package exposes __path__; a plain module does not.
    assert hasattr(ontology, "__path__")
