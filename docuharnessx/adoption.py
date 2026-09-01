"""Project-local adoption record (blueprint-adoption-loop task 1.2).

This module owns the ``Adoption`` service's data model and IO: a frozen
:class:`AdoptionRecord` persisted at ``.docuharnessx/adoption.yaml``. Blueprint
identity, sufficiency, and the optional harness-snapshot pointer live here —
never in ``ontology.yaml`` (ontology-engine vocabulary schema stays untouched).

Load of a missing file returns ``None`` rather than raising. Save round-trips
through YAML including ``harness_snapshot=None``. ``adopt_project`` /
``declare_sufficient`` / ``mark_stale`` and the CLI remain later tasks.
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from typing import Any, Mapping

import yaml

__all__ = [
    "ADOPTION_RELPATH",
    "AdoptionRecord",
    "load_adoption",
    "save_adoption",
]

# Canonical per-project adoption record, relative to a project dir. Distinct
# from ``ontology_setup.ONTOLOGY_CONFIG_RELPATH`` (Req 1.2: do not put these
# fields in ontology.yaml).
ADOPTION_RELPATH = os.path.join(".docuharnessx", "adoption.yaml")


@dataclass(frozen=True)
class AdoptionRecord:
    """Local record of the adopted blueprint, sufficiency, and harness pointer.

    ``adopted_at`` / ``sufficient_at`` are ISO-8601 timestamps stored as
    strings. ``harness_snapshot`` is a path under ``.docuharnessx/harnesses/``
    or ``None`` when no evolved snapshot is current (Req 10.4).
    """

    blueprint_name: str
    blueprint_version: str
    adopted_at: str  # ISO-8601
    sufficient: bool
    sufficient_at: str | None
    sufficient_stale: bool
    harness_snapshot: str | None  # path under .docuharnessx/harnesses/


def _adoption_path(project_dir: str) -> str:
    return os.path.join(project_dir, ADOPTION_RELPATH)


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _require_bool(value: Any, field: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"adoption.yaml field '{field}' must be a boolean, got {value!r}")
    return value


def _record_from_mapping(data: Mapping[str, Any]) -> AdoptionRecord:
    return AdoptionRecord(
        blueprint_name=str(data["blueprint_name"]),
        blueprint_version=str(data["blueprint_version"]),
        adopted_at=str(data["adopted_at"]),
        sufficient=_require_bool(data["sufficient"], "sufficient"),
        sufficient_at=_optional_str(data.get("sufficient_at")),
        sufficient_stale=_require_bool(data["sufficient_stale"], "sufficient_stale"),
        harness_snapshot=_optional_str(data.get("harness_snapshot")),
    )


def load_adoption(project_dir: str) -> AdoptionRecord | None:
    """Load ``<project_dir>/.docuharnessx/adoption.yaml``.

    Returns ``None`` when the file is missing (not adopted yet). A present
    file is parsed into :class:`AdoptionRecord`.
    """
    path = _adoption_path(project_dir)
    if not os.path.isfile(path):
        return None

    with open(path, "r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)

    if not isinstance(data, Mapping):
        raise ValueError(
            f"adoption record {path} must contain a mapping, got {type(data).__name__}"
        )
    return _record_from_mapping(data)


def save_adoption(project_dir: str, record: AdoptionRecord) -> str:
    """Write ``record`` to ``<project_dir>/.docuharnessx/adoption.yaml``.

    Creates the ``.docuharnessx/`` directory when needed. Returns the written
    path. Does not touch ``ontology.yaml``.
    """
    path = _adoption_path(project_dir)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        yaml.safe_dump(asdict(record), handle, sort_keys=False, allow_unicode=True)
    return path
