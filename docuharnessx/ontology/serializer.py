"""Markdown front-matter serializer (the ontology ``serializer`` component).

This is the engine's only front-matter YAML touchpoint (the vocabulary loader is
the only *config* YAML touchpoint). It converts between a Markdown file with a
leading ``---``-fenced YAML block and the typed
:class:`~docuharnessx.ontology.schema.Segment` (Req 4.1, 4.4):

* :func:`parse_segment` splits the leading ``---`` fence, parses the block
  *safely* (``yaml.safe_load`` — never ``yaml.load``) into a raw mapping, and
  retains everything after the closing fence as the opaque ``body``. A missing
  fence, unparseable YAML, or a non-mapping block raises
  :class:`~docuharnessx.ontology.errors.MalformedFrontmatterError` (feeds
  Req 6.3). It performs no vocabulary lookups — ``roles``/``intent`` stay raw.
* :func:`to_segment` builds a :class:`Segment` from a :class:`ParsedSegment` and
  a loaded ``Vocabulary``: ``roles``/``intent`` are kept as raw id strings
  (validated later by the ``validation`` component, not here), while ``subjects``
  are coerced to typed :class:`~docuharnessx.ontology.model.Subject` against the
  vocabulary's allowed prefixes. An untypable subject is *surfaced* (the
  :class:`~docuharnessx.ontology.errors.MalformedSubjectError` from
  ``Subject.parse`` propagates) rather than silently dropped.
* :func:`serialize_segment` emits deterministic Markdown front matter with a
  stable canonical key order, subjects rendered in canonical ``prefix:local``
  form, followed by the body.

Round-trip determinism (Req 4.4): ``serialize_segment(to_segment(
parse_segment(t), vocab))`` is stable across runs, and a segment round-trips
``serialize -> parse`` back to an equivalent segment.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

import yaml

from docuharnessx.ontology.errors import MalformedFrontmatterError
from docuharnessx.ontology.model import Subject
from docuharnessx.ontology.schema import SCHEMA_VERSION, Segment
from docuharnessx.ontology.vocabulary import Vocabulary

__all__ = [
    "ParsedSegment",
    "parse_segment",
    "to_segment",
    "serialize_segment",
]

#: The fence delimiter for a front-matter block.
_FENCE = "---"

#: The canonical, stable key order for serialized front matter (Req 4.4). This is
#: the segment frontmatter field set in schema order, followed by the optional
#: fields and the version. ``body`` is emitted after the closing fence, not as a
#: key.
_CANONICAL_KEY_ORDER: tuple[str, ...] = (
    "id",
    "title",
    "roles",
    "subjects",
    "intent",
    "summary",
    "related",
    "schema_version",
)


@dataclass(frozen=True)
class ParsedSegment:
    """The raw result of parsing a front-matter document.

    ``frontmatter`` is the raw YAML mapping with ``roles``/``intent`` still as
    raw ids and ``subjects`` still as raw strings (typing happens in
    :func:`to_segment`). ``body`` is the opaque Markdown after the closing fence,
    preserved verbatim.
    """

    frontmatter: Mapping[str, Any]
    body: str


def parse_segment(text: str) -> ParsedSegment:
    """Split ``text`` into its front-matter mapping and opaque body.

    The document must begin with a ``---`` fence; the block between that fence
    and the next ``---`` fence is parsed with ``yaml.safe_load`` into a mapping,
    and everything after the closing fence is the ``body``.

    Raises :class:`MalformedFrontmatterError` when the leading fence is missing,
    there is no closing fence, the YAML fails to parse, or the parsed block is
    not a mapping (feeds Req 6.3). ``safe_load`` is used exclusively — no
    arbitrary object construction.
    """
    if not text.startswith(_FENCE):
        raise MalformedFrontmatterError(reason="missing leading '---' front-matter fence")

    # Drop the opening fence line. The opening fence is the first line; require it
    # to be exactly "---" (optionally with trailing whitespace) on its own line.
    after_open = text[len(_FENCE) :]
    if after_open[:1] not in ("\n", ""):
        # e.g. "----" or "---foo" is not a valid opening fence line.
        raise MalformedFrontmatterError(
            reason="malformed opening '---' front-matter fence"
        )
    after_open = after_open[1:] if after_open[:1] == "\n" else after_open

    # Find the closing fence: a line that is exactly "---".
    closing = _find_closing_fence(after_open)
    if closing is None:
        raise MalformedFrontmatterError(reason="missing closing '---' front-matter fence")

    block, body = closing

    try:
        data = yaml.safe_load(block)
    except yaml.YAMLError as exc:
        raise MalformedFrontmatterError(reason=f"unparseable YAML: {exc}") from exc

    if not isinstance(data, Mapping):
        raise MalformedFrontmatterError(
            reason="front-matter block is not a YAML mapping"
        )

    return ParsedSegment(frontmatter=data, body=body)


def _find_closing_fence(text: str) -> tuple[str, str] | None:
    """Return ``(block, body)`` split at the first line equal to ``---``.

    ``block`` is the YAML text before the closing fence; ``body`` is everything
    after the closing fence line. Returns ``None`` when no closing fence exists.
    """
    lines = text.split("\n")
    for index, line in enumerate(lines):
        if line.strip() == _FENCE:
            block = "\n".join(lines[:index])
            body = "\n".join(lines[index + 1 :])
            return block, body
    return None


def to_segment(parsed: ParsedSegment, vocab: Vocabulary) -> Segment:
    """Build a :class:`Segment` from a :class:`ParsedSegment` and a ``Vocabulary``.

    ``roles`` and ``intent`` are kept as raw id strings (membership against the
    vocabulary is the ``validation`` component's job, not the serializer's).
    ``subjects`` are coerced to typed :class:`Subject` via ``Subject.parse``
    using the vocabulary's allowed prefixes; an untypable subject raises
    :class:`~docuharnessx.ontology.errors.MalformedSubjectError` (it is surfaced,
    never silently dropped).

    Missing optional fields fall back to the :class:`Segment` defaults; missing
    *required* fields are left to the ``validation`` component to report, so this
    coercion is permissive on absence (it reads with ``.get`` and only fails on
    genuinely malformed values).
    """
    fm = parsed.frontmatter
    allowed_prefixes = frozenset(vocab.subject_prefixes)

    raw_subjects = fm.get("subjects", []) or []
    subjects = [Subject.parse(str(raw), allowed_prefixes) for raw in raw_subjects]

    raw_roles = fm.get("roles", []) or []
    roles = [str(role) for role in raw_roles]

    raw_related = fm.get("related", []) or []
    related = [str(target) for target in raw_related]

    declared_version = fm.get("schema_version", SCHEMA_VERSION)
    try:
        schema_version = int(declared_version)
    except (TypeError, ValueError):
        raise MalformedFrontmatterError(
            segment_id=str(fm.get("id", "")) or None,
            reason=f"schema_version must be an integer, got {declared_version!r}",
        ) from None

    return Segment(
        id=str(fm.get("id", "")),
        title=str(fm.get("title", "")),
        roles=roles,
        subjects=subjects,
        intent=str(fm.get("intent", "")),
        summary=str(fm.get("summary", "")),
        related=related,
        body=parsed.body,
        schema_version=schema_version,
    )


def serialize_segment(segment: Segment) -> str:
    """Serialize ``segment`` to deterministic Markdown front matter + body.

    Front-matter keys are emitted in the canonical
    :data:`_CANONICAL_KEY_ORDER` (Req 4.4) regardless of insertion order, so the
    same :class:`Segment` always serializes to identical text. Subjects are
    rendered in canonical ``prefix:local`` form. The body is appended verbatim
    after the closing fence.
    """
    ordered: dict[str, Any] = {
        "id": segment.id,
        "title": segment.title,
        "roles": list(segment.roles),
        "subjects": [subject.canonical() for subject in segment.subjects],
        "intent": segment.intent,
        "summary": segment.summary,
        "related": list(segment.related),
        "schema_version": segment.schema_version,
    }
    # Emit in canonical key order; pyyaml preserves dict insertion order when
    # sort_keys is disabled, so build the dict already ordered.
    ordered = {key: ordered[key] for key in _CANONICAL_KEY_ORDER}

    front = yaml.safe_dump(
        ordered,
        default_flow_style=False,
        sort_keys=False,
        allow_unicode=True,
    )

    return f"{_FENCE}\n{front}{_FENCE}\n{segment.body}"
