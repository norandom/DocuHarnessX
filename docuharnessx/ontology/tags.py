"""Namespaced MkDocs tag emission (the ontology ``tags`` component).

Maps a :class:`~docuharnessx.ontology.schema.Segment` to the exactly-namespaced
MkDocs tag set the Material ``tags`` plugin consumes (Req 8):

* one ``role:<role_id>`` per role (Req 8.1),
* one ``intent:<intent_id>`` for the intent (Req 8.1),
* one ``subject:<prefix:local>`` per subject, preserving the typed subject
  prefix (Req 8.1, 8.3).

Tags use *exactly* the ``role:`` / ``intent:`` / ``subject:`` namespaces and no
other prefix forms (Req 8.2). Emission is deterministic — the same segment and
vocabulary always yield the same ordered tuple (Req 8.4) — and a tag is emitted
*only* for an axis value that is a valid member of the supplied ``Vocabulary``
(Req 8.5): an unknown role/intent id, or a subject whose prefix is not a
vocabulary prefix, produces no tag for that value.

This component is a pure transform over a loaded ``Vocabulary``; it performs no
I/O and never reads a module-level enum (the vocabulary is project data).
"""

from __future__ import annotations

from docuharnessx.ontology.model import normalize_prefix
from docuharnessx.ontology.schema import Segment
from docuharnessx.ontology.vocabulary import Vocabulary

__all__ = ["emit_tags"]

#: The three (and only) allowed tag namespaces (Req 8.2).
ROLE_NAMESPACE = "role:"
INTENT_NAMESPACE = "intent:"
SUBJECT_NAMESPACE = "subject:"


def emit_tags(segment: Segment, vocab: Vocabulary) -> tuple[str, ...]:
    """Return the deterministic namespaced tag set for ``segment``.

    Ordering (stable and documented; design.md is silent on the exact sequence,
    so this is the deterministic order chosen — see CONCERNS in the task report):

    1. all ``role:`` tags, in the segment's declared role order,
    2. the single ``intent:`` tag,
    3. all ``subject:`` tags, in the segment's declared subject order.

    Only vocabulary-valid axis values produce a tag (Req 8.5): a role/intent id
    is checked via ``vocab.has_role`` / ``vocab.has_intent``, and a subject is
    emitted only when its (normalized) prefix is one of the vocabulary's
    subject prefixes. The subject's typed prefix is preserved verbatim in the
    emitted value via :meth:`Subject.canonical` (Req 8.3).
    """
    tags: list[str] = []

    # Role tags, in declared order, vocabulary-valid only (Req 8.1, 8.5).
    for role_id in segment.roles:
        if vocab.has_role(role_id):
            tags.append(f"{ROLE_NAMESPACE}{role_id}")

    # The single intent tag, only when it is a vocabulary member (Req 8.1, 8.5).
    if vocab.has_intent(segment.intent):
        tags.append(f"{INTENT_NAMESPACE}{segment.intent}")

    # Subject tags, in declared order, preserving the typed prefix (Req 8.1, 8.3),
    # only when the subject's prefix is a vocabulary prefix (Req 8.5). Prefixes are
    # normalized on both sides so the bare/colon written forms compare equally.
    allowed = {normalize_prefix(p) for p in vocab.subject_prefixes}
    for subject in segment.subjects:
        if normalize_prefix(subject.prefix) in allowed:
            tags.append(f"{SUBJECT_NAMESPACE}{subject.canonical()}")

    return tuple(tags)
