"""Tests for the adoption record load/save (task 1.2, boundary: Adoption).

Pins the project-local adoption record:

* ``AdoptionRecord`` is a frozen dataclass with blueprint name/version,
  adopted_at, sufficient, sufficient_at, sufficient_stale, and a nullable
  ``harness_snapshot`` pointer (Req 1.2, 8.3, 8.4, 10.4).
* Load/save round-trips through ``.docuharnessx/adoption.yaml``, not
  ``ontology.yaml``.
* A missing file returns ``None`` rather than raising.
* ``harness_snapshot=None`` survives the round-trip as ``None``.

These tests touch no model and no network.
"""

from __future__ import annotations

import dataclasses
import os
from pathlib import Path

import yaml

from docuharnessx.adoption import (
    ADOPTION_RELPATH,
    AdoptionRecord,
    load_adoption,
    save_adoption,
)
from docuharnessx.blueprint import BLUEPRINT_NAME, BLUEPRINT_VERSION

_ONTOLOGY_RELPATH = os.path.join(".docuharnessx", "ontology.yaml")


def _record(
    *,
    blueprint_name: str = BLUEPRINT_NAME,
    blueprint_version: str = BLUEPRINT_VERSION,
    adopted_at: str = "2026-09-01T12:00:00+00:00",
    sufficient: bool = False,
    sufficient_at: str | None = None,
    sufficient_stale: bool = False,
    harness_snapshot: str | None = None,
) -> AdoptionRecord:
    return AdoptionRecord(
        blueprint_name=blueprint_name,
        blueprint_version=blueprint_version,
        adopted_at=adopted_at,
        sufficient=sufficient,
        sufficient_at=sufficient_at,
        sufficient_stale=sufficient_stale,
        harness_snapshot=harness_snapshot,
    )


# --------------------------------------------------------------------------- #
# Data model — frozen field set (Req 1.2, 8.3, 8.4, 10.4)                      #
# --------------------------------------------------------------------------- #


def test_adoption_record_field_set_matches_design() -> None:
    fields = {field.name for field in dataclasses.fields(AdoptionRecord)}
    assert fields == {
        "blueprint_name",
        "blueprint_version",
        "adopted_at",
        "sufficient",
        "sufficient_at",
        "sufficient_stale",
        "harness_snapshot",
    }


def test_adoption_record_is_frozen() -> None:
    record = _record()
    assert dataclasses.is_dataclass(record)
    assert record.__dataclass_params__.frozen is True


def test_adoption_relpath_is_not_ontology_yaml() -> None:
    assert ADOPTION_RELPATH == os.path.join(".docuharnessx", "adoption.yaml")
    assert ADOPTION_RELPATH != _ONTOLOGY_RELPATH


# --------------------------------------------------------------------------- #
# Missing file returns None (observable completion)                            #
# --------------------------------------------------------------------------- #


def test_load_adoption_missing_file_returns_none(tmp_path: Path) -> None:
    assert load_adoption(str(tmp_path)) is None


def test_load_adoption_missing_dir_returns_none(tmp_path: Path) -> None:
    missing = tmp_path / "no-such-project"
    assert load_adoption(str(missing)) is None


# --------------------------------------------------------------------------- #
# Round-trip including harness_snapshot=None (observable completion)           #
# --------------------------------------------------------------------------- #


def test_save_load_round_trip_equal_with_null_harness_snapshot(tmp_path: Path) -> None:
    original = _record(harness_snapshot=None)

    written = save_adoption(str(tmp_path), original)

    assert written == os.path.join(str(tmp_path), ADOPTION_RELPATH)
    assert os.path.isfile(written)
    loaded = load_adoption(str(tmp_path))
    assert loaded == original
    assert loaded is not None
    assert loaded.harness_snapshot is None


def test_round_trip_sufficient_declaration_with_timestamp(tmp_path: Path) -> None:
    original = _record(
        sufficient=True,
        sufficient_at="2026-09-01T18:00:00+00:00",
        sufficient_stale=False,
        harness_snapshot=".docuharnessx/harnesses/refine-v1.yaml",
    )

    save_adoption(str(tmp_path), original)
    loaded = load_adoption(str(tmp_path))

    assert loaded == original
    assert loaded is not None
    assert loaded.sufficient is True
    assert loaded.sufficient_at == "2026-09-01T18:00:00+00:00"
    assert loaded.harness_snapshot == ".docuharnessx/harnesses/refine-v1.yaml"


def test_not_yet_sufficient_is_the_default_record_shape(tmp_path: Path) -> None:
    original = _record(sufficient=False, sufficient_at=None, sufficient_stale=False)

    save_adoption(str(tmp_path), original)
    loaded = load_adoption(str(tmp_path))

    assert loaded is not None
    assert loaded.sufficient is False
    assert loaded.sufficient_at is None
    assert loaded.sufficient_stale is False


# --------------------------------------------------------------------------- #
# Adoption lives in adoption.yaml, never ontology.yaml (Req 1.2)               #
# --------------------------------------------------------------------------- #


def test_save_writes_adoption_yaml_not_ontology_yaml(tmp_path: Path) -> None:
    save_adoption(str(tmp_path), _record())

    adoption_path = tmp_path / ".docuharnessx" / "adoption.yaml"
    ontology_path = tmp_path / ".docuharnessx" / "ontology.yaml"
    assert adoption_path.is_file()
    assert not ontology_path.exists()

    on_disk = yaml.safe_load(adoption_path.read_text(encoding="utf-8"))
    assert on_disk["blueprint_name"] == BLUEPRINT_NAME
    assert on_disk["blueprint_version"] == BLUEPRINT_VERSION
    assert "roles" not in on_disk
    assert "intents" not in on_disk
    assert "subject_prefixes" not in on_disk
    assert "harness_snapshot" in on_disk
    assert on_disk["harness_snapshot"] is None
