"""The segment store port and its adapters (the ``store`` component).

This module is one of the engine's **frozen contract surfaces** (see the design's
"Revalidation Triggers"). harness-bundle-skeleton imports :class:`SegmentStore`
and :class:`AxisFilter` *verbatim*, so their shapes — method signatures, the
``AxisFilter`` field set, and the axis-query semantics — must not drift. Any
change here triggers downstream re-validation.

It defines:

* :class:`AxisFilter` — the frozen query value object. ``roles`` and ``intents``
  are tuples of vocabulary *ids*; ``subjects`` is a tuple of typed
  :class:`~docuharnessx.ontology.model.Subject`. Each axis defaults to an empty
  tuple, which means "no constraint on this axis" (so the empty filter matches
  all segments).
* :class:`SegmentStore` — the frozen :class:`typing.Protocol` for the store seam:
  ``put`` / ``query`` / ``list_segments`` / ``resolve_cross_links``.
* :class:`InMemorySegmentStore` — an in-memory adapter (Req 11.3) that binds a
  :class:`~docuharnessx.ontology.vocabulary.Vocabulary` at construction and:

  - **validates on ``put``** against that bound vocabulary, raising the first
    aggregated validation error for an invalid segment (Req 9.2) and an
    :class:`~docuharnessx.ontology.errors.IdConflictError` for a duplicate id
    rather than silently overwriting (Req 9.7);
  - **queries by axis** with per-axis OR (a segment matches an axis if it carries
    *any* of the supplied values) and cross-axis AND (it must match every
    *non-empty* axis); an empty filter matches all (Req 9.3, 9.4);
  - **lists deterministically** — ``list_segments`` and ``query`` both return a
    tuple ordered by segment ``id`` (Req 9.5), matching the frozen port's
    documented "deterministic order (by id)";
  - **resolves cross-links** via :func:`~docuharnessx.ontology.validation.resolve_links`
    over an id→segment index built from the stored segments, returning declared
    targets and silently skipping self/unknown (Req 7.3); an unknown
    ``segment_id`` yields an empty tuple.

The core dependency direction is preserved: this adapter imports the core
(``validation``, ``schema``, ``model``, ``vocabulary``), never the reverse.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Protocol, runtime_checkable

from docuharnessx.ontology.errors import (
    IdConflictError,
    MalformedFrontmatterError,
    OntologyError,
)
from docuharnessx.ontology.model import Subject
from docuharnessx.ontology.schema import Segment
from docuharnessx.ontology.serializer import (
    parse_segment,
    serialize_segment,
    to_segment,
)
from docuharnessx.ontology.validation import resolve_links, validate_segment
from docuharnessx.ontology.vocabulary import Vocabulary

__all__ = [
    "AxisFilter",
    "SegmentStore",
    "InMemorySegmentStore",
    "FilesystemSegmentStore",
]


# --------------------------------------------------------------------------- #
# FROZEN seam — harness-bundle-skeleton imports this verbatim (Req 9.1)        #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class AxisFilter:
    """A query filter over the three ontology axes.

    Each axis is a tuple of values to match with OR semantics; an empty axis
    (the default) imposes no constraint, so a default-constructed ``AxisFilter``
    matches every stored segment. ``roles``/``intents`` carry vocabulary ids;
    ``subjects`` carries typed :class:`Subject` value objects (compared by value
    equality). Frozen so a filter is an immutable, hashable value object.
    """

    roles: tuple[str, ...] = ()  # role ids from the loaded Vocabulary
    intents: tuple[str, ...] = ()  # intent ids from the loaded Vocabulary
    subjects: tuple[Subject, ...] = ()


@runtime_checkable
class SegmentStore(Protocol):
    """The frozen segment-store port (Req 9.1).

    Downstream stages (writer, review gate, assembler) and harness-bundle-skeleton
    depend on exactly these four methods. Adapters implement them; this Protocol
    is the contract, not an implementation.
    """

    def put(self, segment: Segment) -> None:
        """Validate and store ``segment``; raise on invalid / id conflict."""
        ...

    def query(self, where: AxisFilter) -> tuple[Segment, ...]:
        """Return segments matching every non-empty axis (per-axis OR / AND)."""
        ...

    def list_segments(self) -> tuple[Segment, ...]:
        """Return all stored segments in deterministic (by id) order."""
        ...

    def resolve_cross_links(self, segment_id: str) -> tuple[Segment, ...]:
        """Return the resolved ``related`` targets for ``segment_id``."""
        ...


# --------------------------------------------------------------------------- #
# Shared adapter helpers — the single source of match/order/validate/resolve   #
# semantics, so the in-memory and filesystem adapters return IDENTICAL results #
# for identical content (design "store" invariant; RULING for task 4.2).       #
# --------------------------------------------------------------------------- #


def _validate_for_put(segment: Segment, vocab: Vocabulary) -> None:
    """Validate ``segment`` against ``vocab``; raise the first error if invalid.

    Shared by both adapters' ``put`` so validation-on-put is byte-identical
    (Req 9.2). Nothing is stored when this raises — the caller writes only after
    it returns cleanly.
    """
    result = validate_segment(segment, vocab)
    if not result.is_valid:
        first = result.errors[0]
        if isinstance(first, OntologyError):
            raise first
        raise OntologyError(str(first))  # pragma: no cover - defensive


def _order_by_id(segments: Iterable[Segment]) -> list[Segment]:
    """Return ``segments`` ordered by ``id`` — the single determinism authority.

    Both adapters route every listing/query through this so identical content
    always yields the identical order (Req 9.5, 9.6 parity).
    """
    return sorted(segments, key=lambda segment: segment.id)


def _matches(segment: Segment, where: AxisFilter) -> bool:
    """Per-axis OR / cross-axis AND match (Req 9.3, 9.4); empty axis = no constraint."""
    if where.roles and not any(r in where.roles for r in segment.roles):
        return False
    if where.intents and segment.intent not in where.intents:
        return False
    if where.subjects and not any(s in where.subjects for s in segment.subjects):
        return False
    return True


def _query(segments: Iterable[Segment], where: AxisFilter) -> tuple[Segment, ...]:
    """Apply ``where`` to ``segments`` and return matches in by-id order."""
    return tuple(
        segment for segment in _order_by_id(segments) if _matches(segment, where)
    )


def _resolve_cross_links(
    segment_id: str, index: Mapping[str, Segment]
) -> tuple[Segment, ...]:
    """Resolve the ``related`` targets of ``segment_id`` against ``index`` (Req 7.3).

    Delegates to :func:`resolve_links` (declared order, silently skipping
    self/unknown). An unknown ``segment_id`` yields an empty tuple.
    """
    segment = index.get(segment_id)
    if segment is None:
        return ()
    return tuple(resolve_links(segment, index))


# --------------------------------------------------------------------------- #
# In-memory adapter (Req 9.2-9.5, 9.7, 11.3)                                   #
# --------------------------------------------------------------------------- #


class InMemorySegmentStore:
    """An in-memory :class:`SegmentStore`, bound to a :class:`Vocabulary`.

    Segments are held in an id→segment map; the bound vocabulary is the one every
    ``put`` validates against. Listing and querying are deterministic (ordered by
    id) so identical content yields identical results across runs (Req 11.2).
    """

    def __init__(self, vocab: Vocabulary) -> None:
        self._vocab = vocab
        self._segments: dict[str, Segment] = {}

    # -- mutation ----------------------------------------------------------- #

    def put(self, segment: Segment) -> None:
        """Validate ``segment`` against the bound vocabulary, then store it.

        Validation runs first (Req 9.2): if the aggregated
        :class:`~docuharnessx.ontology.errors.ValidationResult` reports any error,
        the first such error is raised and nothing is stored. Then the id-conflict
        check (Req 9.7): a segment whose ``id`` is already present raises
        :class:`IdConflictError` rather than overwriting. Only a valid,
        non-conflicting segment is stored.
        """
        _validate_for_put(segment, self._vocab)

        if segment.id in self._segments:
            raise IdConflictError(segment.id)

        self._segments[segment.id] = segment

    # -- queries ------------------------------------------------------------ #

    def query(self, where: AxisFilter) -> tuple[Segment, ...]:
        """Return stored segments matching ``where`` (per-axis OR, cross-axis AND).

        A segment matches the roles axis if it carries any of ``where.roles``
        (and likewise for intents and subjects); an empty axis is no constraint.
        A segment is returned only if it matches *every* non-empty axis. Results
        are in deterministic (by id) order (Req 9.3, 9.4, 9.5).
        """
        return _query(self._segments.values(), where)

    def list_segments(self) -> tuple[Segment, ...]:
        """Return all stored segments in deterministic (by id) order (Req 9.5)."""
        return tuple(_order_by_id(self._segments.values()))

    def resolve_cross_links(self, segment_id: str) -> tuple[Segment, ...]:
        """Return the resolved ``related`` targets of ``segment_id`` (Req 7.3).

        Builds an id→segment index over the stored segments and delegates to the
        shared :func:`_resolve_cross_links`, which returns targets in declared
        order while silently skipping self-references and unknown ids. An unknown
        ``segment_id`` (not stored) yields an empty tuple.
        """
        return _resolve_cross_links(segment_id, self._segments)


# --------------------------------------------------------------------------- #
# Filesystem adapter (Req 9.2-9.7, 11.3)                                       #
# --------------------------------------------------------------------------- #


class FilesystemSegmentStore:
    """A filesystem-backed :class:`SegmentStore`, bound to a :class:`Vocabulary`.

    Segments are persisted as Markdown files with YAML front matter (Req 9.6),
    one ``<id>.md`` file per segment, in the bound ``directory`` (created if it
    does not exist). The serializer (:func:`serialize_segment` /
    :func:`parse_segment` + :func:`to_segment`) is the only on-disk format
    touchpoint.

    To guarantee the design's "store" invariant — that the filesystem and
    in-memory adapters return identical results for identical content — this
    adapter shares the SAME validation, by-id ordering, axis-match, and
    cross-link-resolution helpers as :class:`InMemorySegmentStore`. Listing and
    querying read the directory lazily on each call and parse every ``.md`` file
    through the serializer with the bound vocabulary, so the on-disk content is
    the single source of truth and results are deterministic across runs
    (Req 11.2).
    """

    def __init__(self, directory, vocab: Vocabulary) -> None:
        self._dir = Path(directory)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._vocab = vocab

    # -- mutation ----------------------------------------------------------- #

    def put(self, segment: Segment) -> None:
        """Validate ``segment`` against the bound vocabulary, then write it.

        Validation runs first (Req 9.2) via the shared :func:`_validate_for_put`;
        if invalid, the first aggregated error is raised and NOTHING is written.
        Then the id-conflict check (Req 9.7): if a file already exists for that
        ``id`` (or a stored segment carries it), an :class:`IdConflictError` is
        raised rather than overwriting. Only a valid, non-conflicting segment is
        serialized to ``<id>.md``.
        """
        _validate_for_put(segment, self._vocab)

        if segment.id in self._load_index():
            raise IdConflictError(segment.id)

        path = self._path_for(segment.id)
        path.write_text(serialize_segment(segment), encoding="utf-8")

    # -- queries ------------------------------------------------------------ #

    def query(self, where: AxisFilter) -> tuple[Segment, ...]:
        """Return on-disk segments matching ``where`` (per-axis OR / cross-axis AND).

        Reads and parses the directory, then applies the shared :func:`_query`
        (by-id order). Identical to :class:`InMemorySegmentStore` for identical
        content (Req 9.3, 9.4, 9.5, 9.6).
        """
        return _query(self._load_index().values(), where)

    def list_segments(self) -> tuple[Segment, ...]:
        """Return all on-disk segments in deterministic (by id) order (Req 9.5)."""
        return tuple(_order_by_id(self._load_index().values()))

    def resolve_cross_links(self, segment_id: str) -> tuple[Segment, ...]:
        """Return the resolved ``related`` targets of ``segment_id`` (Req 7.3).

        Loads the directory into an id→segment index and delegates to the shared
        :func:`_resolve_cross_links`. An unknown ``segment_id`` yields ``()``.
        """
        return _resolve_cross_links(segment_id, self._load_index())

    # -- internals ---------------------------------------------------------- #

    def _path_for(self, segment_id: str) -> Path:
        """The deterministic ``<id>.md`` file path for ``segment_id``.

        The filesystem adapter has one precondition the in-memory adapter does
        not: an ``id`` must be a safe single-segment filename. An id containing a
        path separator (or ``.``/``..``) is reported as a typed
        :class:`MalformedFrontmatterError` rather than leaking a raw OS error or
        escaping the store directory.
        """
        if (
            not segment_id
            or "/" in segment_id
            or "\\" in segment_id
            or segment_id in (".", "..")
        ):
            raise MalformedFrontmatterError(
                segment_id=segment_id or None,
                reason=(
                    "segment id is not a valid filesystem name "
                    "(path separators are not allowed)"
                ),
            )
        return self._dir / f"{segment_id}.md"

    def _load_index(self) -> dict[str, Segment]:
        """Parse every ``.md`` file in the directory into an id→segment map.

        Each file is read through :func:`parse_segment` + :func:`to_segment` with
        the bound vocabulary, exactly as a downstream consumer would, so on-disk
        content is the single source of truth. Files are read in a stable order;
        the by-id ordering helpers impose the final determinism.
        """
        index: dict[str, Segment] = {}
        for path in sorted(self._dir.glob("*.md")):
            text = path.read_text(encoding="utf-8")
            segment = to_segment(parse_segment(text), self._vocab)
            index[segment.id] = segment
        return index
