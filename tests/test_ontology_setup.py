"""``dhx init`` ontology setup tests for task 2.7 (OntologySetup boundary).

Task 2.7 owns ``docuharnessx/ontology_setup.py`` and its single public function
``run_init(project_dir, *, use_default=False, force=False, answers=None) -> str``.

Contract (design "OntologySetup (dhx init)"; Req 9.1-9.6):

* Build a ``Vocabulary`` either by seeding the ``ontology-engine`` default
  profile (``use_default``/no answers) or from interactive ``answers`` (Req 9.2,
  9.3), then delegate schema serialization to the ``ontology-engine``
  ``vocabulary_to_config(vocab) -> dict`` API and write that dict to
  ``.docuharnessx/ontology.yaml`` as YAML, returning the written path (Req 9.4).
* The written file must round-trip through the ``ontology-engine``
  ``load_vocabulary`` loader without error (Req 9.5).
* Refuse to overwrite an existing file unless ``force=True`` (Req 9.6).
* Reimplement neither the schema nor the default profile — the skeleton owns
  only the file write (Req 9.4).
"""

from __future__ import annotations

import inspect
import os

import pytest
import yaml

from docuharnessx._ontology import (
    Vocabulary,
    default_profile,
    load_vocabulary,
    vocabulary_to_config,
)
from docuharnessx.ontology import AxisTerm
from docuharnessx.ontology_setup import (
    ONTOLOGY_CONFIG_RELPATH,
    VocabularyAnswers,
    run_init,
)

_CONFIG_RELPATH = os.path.join(".docuharnessx", "ontology.yaml")


def _config_path(project_dir: str) -> str:
    return os.path.join(project_dir, _CONFIG_RELPATH)


# --------------------------------------------------------------------------- #
# Req 9.1, 9.3, 9.4, 9.5 — default-profile seed writes a valid loadable file.   #
# --------------------------------------------------------------------------- #


def test_run_init_default_writes_valid_ontology_file(tmp_path) -> None:
    project_dir = str(tmp_path)

    written = run_init(project_dir, use_default=True)

    # Returns the written path, which is the canonical per-project location.
    assert written == _config_path(project_dir)
    assert os.path.isfile(written)

    # Req 9.5 — the engine loader accepts the written file without error.
    vocab = load_vocabulary(written)
    assert isinstance(vocab, Vocabulary)
    # Seeded from the default profile (Req 9.3).
    assert vocab == default_profile()


def test_run_init_relpath_constant_matches_canonical_location() -> None:
    assert ONTOLOGY_CONFIG_RELPATH == _CONFIG_RELPATH


def test_run_init_default_file_contents_match_vocabulary_to_config(tmp_path) -> None:
    """The on-disk YAML is exactly the engine's vocabulary_to_config dict."""
    project_dir = str(tmp_path)

    written = run_init(project_dir, use_default=True)

    with open(written, "r", encoding="utf-8") as handle:
        on_disk = yaml.safe_load(handle)

    assert on_disk == vocabulary_to_config(default_profile())


def test_run_init_creates_docuharnessx_dir(tmp_path) -> None:
    project_dir = str(tmp_path)
    assert not os.path.exists(os.path.join(project_dir, ".docuharnessx"))

    run_init(project_dir, use_default=True)

    assert os.path.isdir(os.path.join(project_dir, ".docuharnessx"))


# --------------------------------------------------------------------------- #
# Req 9.2 — interactive answers assemble into a Vocabulary and a loadable file. #
# --------------------------------------------------------------------------- #


def test_run_init_interactive_answers_writes_loadable_file(tmp_path) -> None:
    project_dir = str(tmp_path)
    answers = VocabularyAnswers(
        roles=(AxisTerm("solo", "Solo", "The only role."),),
        intents=(AxisTerm("read", "Read", "Read it."),),
        subject_prefixes=("topic:",),
    )

    written = run_init(project_dir, answers=answers)

    vocab = load_vocabulary(written)
    assert [r.id for r in vocab.roles] == ["solo"]
    assert [i.id for i in vocab.intents] == ["read"]
    assert vocab != default_profile()


def test_run_init_interactive_answers_accepts_plain_mapping(tmp_path) -> None:
    """answers may also be a plain mapping of role/intent/subject dicts."""
    project_dir = str(tmp_path)
    answers = {
        "roles": [{"id": "solo", "label": "Solo", "description": "Only."}],
        "intents": [{"id": "read", "label": "Read", "description": "Read."}],
        "subjects": ["topic:"],
    }

    written = run_init(project_dir, answers=answers)

    vocab = load_vocabulary(written)
    assert [r.id for r in vocab.roles] == ["solo"]
    assert [i.id for i in vocab.intents] == ["read"]


# --------------------------------------------------------------------------- #
# Req 9.6 — refuse to overwrite an existing file unless force=True.             #
# --------------------------------------------------------------------------- #


def test_run_init_refuses_overwrite_without_force(tmp_path) -> None:
    project_dir = str(tmp_path)
    run_init(project_dir, use_default=True)

    with pytest.raises(FileExistsError) as excinfo:
        run_init(project_dir, use_default=True)

    # The message names the offending file (explicit, cause-naming).
    assert _config_path(project_dir) in str(excinfo.value)


def test_run_init_overwrites_with_force(tmp_path) -> None:
    project_dir = str(tmp_path)
    # First seed an interactive (non-default) file.
    answers = VocabularyAnswers(
        roles=(AxisTerm("solo", "Solo", "Only."),),
        intents=(AxisTerm("read", "Read", "Read."),),
        subject_prefixes=("topic:",),
    )
    run_init(project_dir, answers=answers)

    # Force-overwrite with the default profile.
    written = run_init(project_dir, use_default=True, force=True)

    assert load_vocabulary(written) == default_profile()


# --------------------------------------------------------------------------- #
# Req 9.4 — delegate schema/profile; the skeleton owns only the file write.     #
# --------------------------------------------------------------------------- #


def test_run_init_signature_matches_design_contract() -> None:
    sig = inspect.signature(run_init)
    params = sig.parameters
    assert list(params) == ["project_dir", "use_default", "force", "answers"]
    assert params["use_default"].kind is inspect.Parameter.KEYWORD_ONLY
    assert params["force"].kind is inspect.Parameter.KEYWORD_ONLY
    assert params["answers"].kind is inspect.Parameter.KEYWORD_ONLY
    assert params["use_default"].default is False
    assert params["force"].default is False
    assert params["answers"].default is None


def test_run_init_defines_no_schema_or_storage_class() -> None:
    """The module must not redefine the schema, loader, or a store/serializer.

    The only class it may define is the lightweight ``VocabularyAnswers`` DTO for
    the interactive path; everything ontology-schema-shaped comes from the engine.
    """
    import docuharnessx.ontology_setup as module

    locally_defined = {
        name
        for name, member in inspect.getmembers(module, inspect.isclass)
        if member.__module__ == module.__name__
    }
    assert locally_defined <= {"VocabularyAnswers"}, (
        "ontology_setup may only define the VocabularyAnswers DTO; the schema, "
        "loader, default profile, and serializer come from ontology-engine"
    )


def test_run_init_requires_answers_or_default(tmp_path) -> None:
    """Neither default nor answers -> explicit error (nothing to build)."""
    project_dir = str(tmp_path)

    with pytest.raises(ValueError):
        run_init(project_dir)
