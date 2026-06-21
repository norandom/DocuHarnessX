"""Run-start ontology loading into the run context (task 2.6 boundary).

This module owns the ``OntologyLoader`` service: a single function,
:func:`load_project_vocabulary`, that the CLI calls at run start (after target
validation, before model resolution) to materialize the per-project
``.docuharnessx/ontology.yaml`` into a :class:`Vocabulary` for placement into the
``RunContext`` ``SLOT_VOCABULARY`` slot (design "OntologyLoader (run-start)";
Req 10.1, 10.2, 10.3, 10.4, 10.5).

Contract
--------
* When the file is **present and valid**, return ``(vocabulary, False)``: the
  ``ontology-engine`` loader builds the ``Vocabulary`` (Req 10.1).
* When the file is **absent**, return ``(default_profile(), True)``. The
  ``used_default=True`` flag tells the CLI to surface a ``dhx init`` hint
  (Req 10.3). A missing file is deliberately *not* an error.
* When the file is **present but invalid** (the loader rejects it), raise
  :class:`OntologyConfigError` with a message naming the offending file, mapped
  by the CLI to a non-zero exit (Req 10.4).

Delegation (Req 10.5)
---------------------
This module reimplements neither the schema, the loader, nor the default profile.
It imports both from the skeleton's single ontology re-export site
(:mod:`docuharnessx._ontology`), so any ``ontology-engine`` contract drift has a
single blast radius. It owns only two concerns: locating the per-project config
file, and translating the engine's :class:`MalformedConfigError` into the
skeleton's boundary :class:`OntologyConfigError`.

Revalidation trigger (recorded risk): a change to the ``load_vocabulary`` /
``default_profile`` signatures, or to the ``MalformedConfigError`` type the loader
raises for a present-but-invalid config, must be re-validated here.
"""

from __future__ import annotations

import os

from docuharnessx._ontology import (
    Vocabulary,
    default_profile,
    load_vocabulary,
)
from docuharnessx.errors import OntologyConfigError
from docuharnessx.ontology.errors import MalformedConfigError

__all__ = ["load_project_vocabulary", "ONTOLOGY_CONFIG_RELPATH"]

# The canonical per-project ontology config location, relative to a project dir.
# ``dhx init`` writes here and run-start loading reads from here (Req 9.1, 10.1).
ONTOLOGY_CONFIG_RELPATH = os.path.join(".docuharnessx", "ontology.yaml")


def load_project_vocabulary(project_dir: str) -> tuple[Vocabulary, bool]:
    """Load ``<project_dir>/.docuharnessx/ontology.yaml`` into a ``Vocabulary``.

    Returns a ``(vocabulary, used_default)`` pair (design Service Interface):

    * ``used_default`` is ``False`` and ``vocabulary`` is the loaded config when a
      valid file is present (Req 10.1).
    * ``used_default`` is ``True`` and ``vocabulary`` is the ``ontology-engine``
      default profile when no config file is found (Req 10.3); the caller surfaces
      a ``dhx init`` hint on this flag.

    Raises :class:`OntologyConfigError` when a *present* file fails to load
    against the ``ontology-engine`` loader (Req 10.4). A missing file is not an
    error.

    The schema, loader, and default profile are owned by ``ontology-engine``; this
    function only locates the file and maps the loader's error to the skeleton's
    boundary error (Req 10.5).
    """
    config_path = os.path.join(project_dir, ONTOLOGY_CONFIG_RELPATH)

    # Absent file -> default-profile fallback with the dhx-init hint flag (10.3).
    # We resolve presence *here* rather than relying on the loader's own
    # missing-file fallback, because the caller needs the used_default signal that
    # the loader (which silently returns the default profile for a missing path)
    # does not expose.
    if not os.path.isfile(config_path):
        return default_profile(), True

    # Present file -> delegate loading to the engine; translate its rejection of a
    # present-but-invalid config into the skeleton's boundary error (10.4).
    try:
        vocabulary = load_vocabulary(config_path)
    except MalformedConfigError as exc:
        raise OntologyConfigError(
            f"invalid ontology config '{config_path}': {exc}"
        ) from exc

    return vocabulary, False
