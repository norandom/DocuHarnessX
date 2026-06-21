"""The skeleton's single contract-level re-export site for ``ontology-engine``.

Task 2.4 — "Consume the ontology-engine interfaces at the contract level". This
module is the *one* place the harness-bundle-skeleton names the ``ontology-engine``
surface it consumes (``config``, ``context``, ``ontology_loader``, and
``ontology_setup`` import from here, not from the engine submodules), so the
downstream blast radius of any engine contract drift is a single file.

It adds **no** storage, schema, loader, or profile logic — it re-exports the
already-published ``ontology-engine`` symbols verbatim and nothing else
(design "Out of Boundary": the segment-store interface, the ``Vocabulary`` model,
the YAML loader/serializer, and the default profile are all owned by
``ontology-engine``).

Name-clash resolution
---------------------
``ontology-engine`` owns the package ``docuharnessx/ontology/`` (a directory). The
design pinned the single re-export site as ``docuharnessx.ontology`` — but Python
resolves a *package* over a same-named top-level *module*, so a literal
``docuharnessx/ontology.py`` would be permanently shadowed and unreachable
(verified: `import docuharnessx.ontology` always loads the package's
``__init__.py``). The design's task-2.4 implementation note therefore pins a
``docuharnessx/_ontology.py`` **shim** as the single import site instead, so the
two specs do not collide on the package root and ``import docuharnessx.ontology``
keeps resolving the real ontology package untouched.

Consumed surface (the frozen seams the skeleton relies on)
----------------------------------------------------------
* ``SegmentStore`` — the frozen store port. The skeleton relies on EXACTLY these
  four signatures (verbatim from ``ontology-engine``)::

      put(self, segment: Segment) -> None
      query(self, where: AxisFilter) -> tuple[Segment, ...]
      list_segments(self) -> tuple[Segment, ...]
      resolve_cross_links(self, segment_id: str) -> tuple[Segment, ...]

* ``AxisFilter`` / ``Segment`` — co-imported value types for the store port.
* ``Vocabulary`` + ``load_vocabulary`` + ``vocabulary_to_config`` — the frozen
  vocabulary loader/serializer seam.
* ``default_profile`` — the shipped default-profile API.

The ``ontology-engine`` contract is published, so these are the REAL imports; no
typing-only fallback alias is needed. The design records the matching revalidation
trigger: any change to the ``SegmentStore`` shape, the ``Vocabulary`` model, the
loader/serializer signatures, or the default-profile API must be re-validated here.
"""

from __future__ import annotations

from docuharnessx.ontology import (
    AxisFilter,
    Segment,
    SegmentStore,
    Vocabulary,
    default_profile,
    load_vocabulary,
    vocabulary_to_config,
)

__all__ = [
    # store port (frozen seam) + its value types
    "SegmentStore",
    "AxisFilter",
    "Segment",
    # vocabulary model + loader/serializer (frozen seam)
    "Vocabulary",
    "load_vocabulary",
    "vocabulary_to_config",
    # default-profile API
    "default_profile",
]
