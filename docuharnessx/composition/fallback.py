"""The deterministic fallback body renderer (cobesy-writer task 2.4).

This module owns the *Fallback Renderer* boundary of the Wave 2 ``cobesy-writer``:
:func:`render_fallback_body` and :func:`render_fallback_summary` turn a COBESY
:class:`~docuharnessx.composition.model.CompositionBlueprint` into a valid Markdown
``body`` and a short ``summary`` *without consulting any model* (design "Fallback
Renderer"; Req 6.3, 8.3).

It is the deterministic backbone the Write stage falls back to whenever no model is
bound, or the gated prose step (``prose.py``) returns ``None`` because the model raised,
timed out, or produced empty/unparseable content (Req 6.3). Because the fallback is pure
and deterministic, a credential-free ``FakeProvider`` run still produces one valid
``Segment`` per planned segment, and two model-free runs over an equal plan produce
byte-equal text (Req 8.3, 9.3).

The body honors the blueprint's COBESY structure in reading order:

1. A Markdown ``# title`` lead (the blueprint title).
2. The Minto **lead-with-conclusion** key message, stated first so the reader gets the
   answer up front.
3. The SCQA opener (Situation / Complication / Question), framing why the path matters;
   when the blueprint marks an **expert** audience (:attr:`CompositionBlueprint.andragogy`)
   the opener carries a short Knowles andragogy note (respect prior knowledge,
   problem-centered framing).
4. The working-memory **chunks** as ``## subheads`` with bullet points (the 7+/-2 plan).
5. The REDUCE-barrier **fast path** as an ordered list of barrier-removing steps to first
   success.
6. The **evidence anchors** as a grounding reference list so the body is anchored in real
   repository facts (and nothing is invented when none are present).

It is a **pure function**: it reads only the frozen blueprint, never mutates it, performs
no I/O, and emits a plain ``str``. Equal blueprints always yield equal text. It contains
no hardcoded role/intent/subject literals — every human label comes from the blueprint,
which derived it from the loaded ``Vocabulary`` (Req 9.1).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # the blueprint value object — typing-only import.
    from docuharnessx.composition.model import CompositionBlueprint

__all__ = ["render_fallback_body", "render_fallback_summary"]


# --------------------------------------------------------------------------- #
# Section renderers (each returns the lines for one COBESY section)            #
# --------------------------------------------------------------------------- #


def _opener_lines(blueprint: "CompositionBlueprint") -> list[str]:
    """The Minto lead conclusion plus the SCQA opener (with andragogy framing).

    Leads with the conclusion (``key_message``) so a time-poor reader gets the answer
    first (Minto), then states the SCQA Situation / Complication / Question. When the
    blueprint marks an expert audience, a short Knowles andragogy note is appended so the
    expert framing is honored and the rendered body is distinguishable from the
    non-expert one.
    """
    scqa = blueprint.scqa
    lines: list[str] = [
        blueprint.key_message,
        "",
        scqa.situation,
        scqa.complication,
        scqa.question,
    ]
    if blueprint.andragogy:
        # Knowles andragogy: respect the reader's prior knowledge, problem-centered
        # framing. Derived purely from the blueprint flag (no role-id literals).
        lines.append(
            "This assumes hands-on experience: it stays problem-centered and skips "
            "basics you already know."
        )
    return lines


def _chunk_lines(blueprint: "CompositionBlueprint") -> list[str]:
    """The working-memory chunks as ``## subheads`` with bullet points.

    Each :class:`~docuharnessx.composition.model.Chunk` becomes a level-2 subhead
    followed by its MECE points as Markdown bullets. Tolerates an empty chunk tuple
    (renders nothing) so a chunk-free blueprint still yields a valid body.
    """
    lines: list[str] = []
    for chunk in blueprint.chunks:
        lines.append("")
        lines.append(f"## {chunk.heading}")
        lines.append("")
        for point in chunk.points:
            lines.append(f"- {point}")
    return lines


def _fast_path_lines(blueprint: "CompositionBlueprint") -> list[str]:
    """The REDUCE-barrier fast path as an ordered list of steps to first success.

    Rendered as a numbered Markdown list under a fixed subhead so the reader follows the
    shortest barrier-removing sequence. Tolerates an empty fast path (renders nothing).
    """
    if not blueprint.fast_path:
        return []
    lines: list[str] = ["", "## Fast path", ""]
    for index, step in enumerate(blueprint.fast_path, start=1):
        lines.append(f"{index}. {step}")
    return lines


def _evidence_lines(blueprint: "CompositionBlueprint") -> list[str]:
    """The evidence anchors as a grounding reference list.

    Each anchor renders as ``- kind: detail`` plus its enrichment note when present, so
    the body is anchored in real repository facts (Req 3.5). Tolerates an empty anchor
    tuple (renders nothing) so no repository fact is invented when there is none
    (Req 2.5).
    """
    if not blueprint.evidence_anchors:
        return []
    lines: list[str] = ["", "## Evidence", ""]
    for anchor in blueprint.evidence_anchors:
        note = f" — {anchor.note}" if anchor.note else ""
        lines.append(f"- {anchor.kind}: {anchor.detail}{note}")
    return lines


# --------------------------------------------------------------------------- #
# Public entry points                                                         #
# --------------------------------------------------------------------------- #


def render_fallback_body(blueprint: "CompositionBlueprint") -> str:
    """Render a deterministic, valid Markdown ``body`` from ``blueprint`` (Req 6.3).

    Honors the blueprint's COBESY structure in reading order — an ``# title`` lead, the
    Minto lead-with-conclusion key message, the SCQA opener (with andragogy framing for an
    expert blueprint), the working-memory chunk subheads + bullets, the REDUCE-barrier
    fast-path list, and the evidence-anchor references — built only from blueprint-derived
    facts (no hardcoded role/intent/subject literals, no model). Tolerates empty
    chunks/fast-path/evidence so the body is always valid Markdown.

    Pure and deterministic: never mutates ``blueprint`` and equal blueprints yield equal
    text (Req 9.3). The returned string is the segment ``body`` the wiring carries into a
    ``validate_segment``-valid ``Segment``.
    """
    lines: list[str] = [f"# {blueprint.title}", ""]
    lines.extend(_opener_lines(blueprint))
    lines.extend(_chunk_lines(blueprint))
    lines.extend(_fast_path_lines(blueprint))
    lines.extend(_evidence_lines(blueprint))
    # A single trailing newline; collapse no internal structure so the rendering is a
    # stable, deterministic function of the blueprint.
    return "\n".join(lines).rstrip() + "\n"


def render_fallback_summary(blueprint: "CompositionBlueprint") -> str:
    """Render a short, deterministic ``summary`` from ``blueprint`` (Req 8.3).

    A single-line summary that leads with the Minto key message — the conclusion a reader
    or the review gate sees first. Pure and deterministic: never mutates ``blueprint`` and
    equal blueprints yield an equal summary.
    """
    return blueprint.key_message.strip()
