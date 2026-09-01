"""No-model ``run_init`` also seeds the adoption record (task 2.1).

``OntologySetup`` still dumps the shipped default profile to
``.docuharnessx/ontology.yaml``. It now also writes ``AdoptionRecord`` to
``.docuharnessx/adoption.yaml`` with the package ``BLUEPRINT_VERSION`` and
``sufficient=False`` (Req 1.2, 1.6). Overwrite without ``force`` is refused
and both files stay unchanged (Req 1.4). Writes stay under ``.docuharnessx/``
(Req 1.5).

These tests touch no model and no network.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from docuharnessx.adoption import ADOPTION_RELPATH, AdoptionRecord, load_adoption, save_adoption
from docuharnessx.blueprint import BLUEPRINT_NAME, BLUEPRINT_VERSION
from docuharnessx.ontology_setup import ONTOLOGY_CONFIG_RELPATH, run_init


def _ontology_path(project_dir: str) -> str:
    return os.path.join(project_dir, ONTOLOGY_CONFIG_RELPATH)


def _adoption_path(project_dir: str) -> str:
    return os.path.join(project_dir, ADOPTION_RELPATH)


def _assert_iso8601_utc(stamp: str) -> None:
    parsed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    assert parsed.tzinfo is not None
    offset = parsed.utcoffset()
    assert offset is not None
    assert offset.total_seconds() == 0


# --------------------------------------------------------------------------- #
# Req 1.2, 1.6 — default seed writes adoption.yaml with BLUEPRINT_VERSION      #
# --------------------------------------------------------------------------- #


def test_run_init_default_writes_adoption_record_with_blueprint_version(tmp_path) -> None:
    project_dir = str(tmp_path)

    written = run_init(project_dir, use_default=True)

    assert written == _ontology_path(project_dir)
    assert os.path.isfile(written)
    assert os.path.isfile(_adoption_path(project_dir))

    loaded = load_adoption(project_dir)
    assert loaded is not None
    assert loaded.blueprint_name == BLUEPRINT_NAME
    assert loaded.blueprint_version == BLUEPRINT_VERSION
    assert loaded.sufficient is False
    assert loaded.sufficient_at is None
    assert loaded.sufficient_stale is False
    assert loaded.harness_snapshot is None
    _assert_iso8601_utc(loaded.adopted_at)


def test_run_init_does_not_put_adoption_fields_in_ontology_yaml(tmp_path) -> None:
    project_dir = str(tmp_path)

    run_init(project_dir, use_default=True)

    with open(_ontology_path(project_dir), "r", encoding="utf-8") as handle:
        on_disk = yaml.safe_load(handle)
    assert "blueprint_name" not in on_disk
    assert "blueprint_version" not in on_disk
    assert "sufficient" not in on_disk
    assert "harness_snapshot" not in on_disk


def test_run_init_interactive_answers_also_write_adoption_record(tmp_path) -> None:
    project_dir = str(tmp_path)
    answers = {
        "roles": [{"id": "solo", "label": "Solo", "description": "Only."}],
        "intents": [{"id": "read", "label": "Read", "description": "Read."}],
        "subjects": ["topic:"],
    }

    run_init(project_dir, answers=answers)

    loaded = load_adoption(project_dir)
    assert loaded is not None
    assert loaded.blueprint_name == BLUEPRINT_NAME
    assert loaded.blueprint_version == BLUEPRINT_VERSION
    assert loaded.sufficient is False


# --------------------------------------------------------------------------- #
# Req 1.4 — refuse overwrite without force; leave both files unchanged         #
# --------------------------------------------------------------------------- #


def test_run_init_refuses_overwrite_and_leaves_adoption_unchanged(tmp_path) -> None:
    project_dir = str(tmp_path)
    run_init(project_dir, use_default=True)

    ontology_bytes = Path(_ontology_path(project_dir)).read_bytes()
    adoption_bytes = Path(_adoption_path(project_dir)).read_bytes()

    with pytest.raises(FileExistsError) as excinfo:
        run_init(project_dir, use_default=True)

    message = str(excinfo.value)
    assert _ontology_path(project_dir) in message
    assert "adopted blueprint" in message
    assert Path(_ontology_path(project_dir)).read_bytes() == ontology_bytes
    assert Path(_adoption_path(project_dir)).read_bytes() == adoption_bytes


def test_run_init_force_rewrites_adoption_record(tmp_path) -> None:
    project_dir = str(tmp_path)
    run_init(project_dir, use_default=True)
    save_adoption(
        project_dir,
        AdoptionRecord(
            blueprint_name="other-blueprint",
            blueprint_version="0.0.0",
            adopted_at="2020-01-01T00:00:00+00:00",
            sufficient=True,
            sufficient_at="2020-01-02T00:00:00+00:00",
            sufficient_stale=True,
            harness_snapshot=".docuharnessx/harnesses/old.yaml",
        ),
    )

    run_init(project_dir, use_default=True, force=True)

    loaded = load_adoption(project_dir)
    assert loaded is not None
    assert loaded.blueprint_name == BLUEPRINT_NAME
    assert loaded.blueprint_version == BLUEPRINT_VERSION
    assert loaded.sufficient is False
    assert loaded.sufficient_at is None
    assert loaded.sufficient_stale is False
    assert loaded.harness_snapshot is None
    assert loaded.adopted_at != "2020-01-01T00:00:00+00:00"
    _assert_iso8601_utc(loaded.adopted_at)


# --------------------------------------------------------------------------- #
# Req 1.5 — no-model seed writes only under .docuharnessx/                     #
# --------------------------------------------------------------------------- #


def test_run_init_default_writes_only_under_docuharnessx(tmp_path) -> None:
    project_dir = str(tmp_path)
    sentinel = tmp_path / "README.md"
    sentinel.write_text("keep me", encoding="utf-8")

    run_init(project_dir, use_default=True)

    assert sentinel.read_text(encoding="utf-8") == "keep me"
    written = [path for path in tmp_path.rglob("*") if path.is_file()]
    extra = [path for path in written if path != sentinel]
    assert extra
    assert {path.relative_to(tmp_path).as_posix() for path in extra} == {
        ".docuharnessx/ontology.yaml",
        ".docuharnessx/adoption.yaml",
    }
