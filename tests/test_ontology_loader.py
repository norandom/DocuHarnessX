"""Run-start ontology loading tests for task 2.6 (OntologyLoader boundary).

Task 2.6 owns ``docuharnessx/ontology_loader.py`` and its single public
function ``load_project_vocabulary(project_dir) -> tuple[Vocabulary, bool]``.

Contract (design "OntologyLoader (run-start)"; Req 10.1, 10.3, 10.4, 10.5):

* Locate ``.docuharnessx/ontology.yaml`` under ``project_dir`` and load it via
  the ``ontology-engine`` loader, returning ``(vocabulary, used_default=False)``
  (Req 10.1).
* When the config file is absent, return the ``ontology-engine`` default-profile
  ``Vocabulary`` with ``used_default=True`` — this flag triggers the CLI's
  ``dhx init`` hint (Req 10.3).
* When a present file fails to load, raise :class:`OntologyConfigError` with an
  explicit message naming the offending file (Req 10.4).
* Reimplements neither the schema, the loader, nor the default profile — it only
  delegates to the engine via the skeleton's single re-export site (Req 10.5).
"""

from __future__ import annotations

import inspect
import os

import pytest

from docuharnessx._ontology import (
    Vocabulary,
    default_profile,
    load_vocabulary,
    vocabulary_to_config,
)
from docuharnessx.errors import OntologyConfigError
from docuharnessx.ontology_loader import load_project_vocabulary

# The canonical per-project config location the loader must locate.
_CONFIG_RELPATH = os.path.join(".docuharnessx", "ontology.yaml")


def _write_ontology(project_dir: str, content: str) -> str:
    """Write ``content`` to ``<project_dir>/.docuharnessx/ontology.yaml``."""
    config_path = os.path.join(project_dir, _CONFIG_RELPATH)
    os.makedirs(os.path.dirname(config_path), exist_ok=True)
    with open(config_path, "w", encoding="utf-8") as handle:
        handle.write(content)
    return config_path


# --------------------------------------------------------------------------- #
# Req 10.1 — a valid file loads into a Vocabulary, used_default is False.       #
# --------------------------------------------------------------------------- #


def test_loads_valid_ontology_file_into_vocabulary(tmp_path) -> None:
    project_dir = str(tmp_path)
    # Seed a real, valid config from the default profile so the engine loader
    # accepts it without the test reimplementing the schema.
    import yaml

    config_path = _write_ontology(
        project_dir, yaml.safe_dump(vocabulary_to_config(default_profile()))
    )
    assert os.path.exists(config_path)

    vocab, used_default = load_project_vocabulary(project_dir)

    assert isinstance(vocab, Vocabulary)
    assert used_default is False
    # The loaded vocabulary equals what the engine loader produces directly.
    assert vocab == load_vocabulary(config_path)


def test_custom_file_overrides_default_profile(tmp_path) -> None:
    """A non-default valid file is loaded as-is, not the default profile."""
    project_dir = str(tmp_path)
    _write_ontology(
        project_dir,
        "roles:\n"
        "  - id: solo\n"
        "    label: Solo\n"
        "    description: The only role.\n"
        "intents:\n"
        "  - id: read\n"
        "    label: Read\n"
        "    description: Read it.\n"
        "subjects:\n"
        '  - "topic:"\n',
    )

    vocab, used_default = load_project_vocabulary(project_dir)

    assert used_default is False
    assert [r.id for r in vocab.roles] == ["solo"]
    assert vocab != default_profile()


# --------------------------------------------------------------------------- #
# Req 10.3 — an absent file falls back to the default profile, used_default.    #
# --------------------------------------------------------------------------- #


def test_absent_file_returns_default_profile_with_used_default_true(tmp_path) -> None:
    project_dir = str(tmp_path)  # no .docuharnessx/ontology.yaml written
    assert not os.path.exists(os.path.join(project_dir, _CONFIG_RELPATH))

    vocab, used_default = load_project_vocabulary(project_dir)

    assert used_default is True
    assert vocab == default_profile()


def test_absent_when_docuharnessx_dir_exists_but_no_file(tmp_path) -> None:
    """A present ``.docuharnessx/`` dir without the file is still 'absent'."""
    project_dir = str(tmp_path)
    os.makedirs(os.path.join(project_dir, ".docuharnessx"))

    vocab, used_default = load_project_vocabulary(project_dir)

    assert used_default is True
    assert vocab == default_profile()


# --------------------------------------------------------------------------- #
# Req 10.4 — a present-but-invalid file raises OntologyConfigError.             #
# --------------------------------------------------------------------------- #


def test_present_but_invalid_file_raises_ontology_config_error(tmp_path) -> None:
    project_dir = str(tmp_path)
    # A mapping root that is missing required keys -> loader rejects it.
    config_path = _write_ontology(project_dir, "not_a_known_key: true\n")

    with pytest.raises(OntologyConfigError) as excinfo:
        load_project_vocabulary(project_dir)

    # The message must name the offending file (explicit, cause-naming).
    assert config_path in str(excinfo.value)


def test_unparseable_yaml_raises_ontology_config_error(tmp_path) -> None:
    project_dir = str(tmp_path)
    _write_ontology(project_dir, "roles: [unterminated\n")

    with pytest.raises(OntologyConfigError):
        load_project_vocabulary(project_dir)


def test_empty_file_raises_ontology_config_error(tmp_path) -> None:
    """A present-but-empty file is invalid, not 'absent'."""
    project_dir = str(tmp_path)
    _write_ontology(project_dir, "")

    with pytest.raises(OntologyConfigError):
        load_project_vocabulary(project_dir)


# --------------------------------------------------------------------------- #
# Req 10.5 — reimplements neither schema, loader, nor default profile.         #
# --------------------------------------------------------------------------- #


def test_loader_defines_no_local_storage_or_schema_class() -> None:
    """The module must not define any class — it only delegates to the engine."""
    import docuharnessx.ontology_loader as module

    for name, member in inspect.getmembers(module, inspect.isclass):
        # Only re-exported/imported engine + error types are allowed; nothing the
        # loader defines itself (i.e. nothing whose __module__ is this module).
        assert member.__module__ != module.__name__, (
            f"{name} must not be defined in ontology_loader; the schema, loader, "
            "and default profile come from ontology-engine"
        )


def test_signature_matches_design_contract() -> None:
    sig = inspect.signature(load_project_vocabulary)
    assert list(sig.parameters) == ["project_dir"]
