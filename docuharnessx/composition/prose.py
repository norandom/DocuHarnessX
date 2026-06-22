"""The gated prose step — the ONLY model surface of the composition core (task 2.5).

``docuharnessx.composition.prose`` is the single module in the otherwise pure,
model-free Wave 2 ``cobesy-writer`` composition core that may consult a model (design
"Gated Prose Step"; Req 5.1, 5.2, 5.3, 5.4, 5.5). Everything else — the blueprint
builder, the prompt assembler, the segment wiring, and the fallback renderer — is
deterministic and unit-testable without any credentials; this module isolates the one
fault-tolerant model call behind a narrow, duck-typed boundary so the whole stage stays
credential-free testable end to end.

Contract (design service interface)::

    def generate_prose(blueprint, *, model, timeout_s=DEFAULT_PROSE_TIMEOUT_S) -> ProseResult | None

Two outcomes, exactly as the design pins them:

* **Clean response** — when a ``model`` is bound and returns a parseable, non-empty
  ``.content``, the step parses it deterministically into a Markdown ``body`` (and a
  ``summary``, derived from the content when the model did not supply one) and returns a
  :class:`~docuharnessx.composition.model.ProseResult` with ``source="model"`` (Req 5.1,
  5.4). It sets only ``body``/``summary`` — never a non-body ``Segment`` field, which the
  deterministic wiring fixes (Req 5.5).
* **Model-less / failure / timeout / empty / unparseable** — returns ``None`` so the
  caller (the ``WriteStage``) renders the deterministic fallback (Req 5.4, and the Req 6.3
  driver). A ``None`` model, any exception from ``complete``, a model that does not answer
  within ``timeout_s``, a non-string content, and an empty/unparseable body are all
  **absorbed**: logged at WARNING and reduced to ``None``. This step never raises.

Bounded by construction: at most **one** ``complete`` call per invocation and no loop —
cost/step budgeting belongs to the inherited Control bundle (Req 5.3).

Model coupling is intentionally minimal and duck-typed (mirroring
:mod:`docuharnessx.planning.relevance` and :mod:`docuharnessx.analysis.enrich`): the step
expects only a HarnessX ``BaseModelProvider``-shaped object — an awaitable
``complete(messages, tools, stream_callback=None)`` returning an object with a ``.content``
string (a ``ModelResponseEvent`` in production; any stand-in in tests). The composition
package never imports a model class or constructs a provider — the bound model, if any, is
handed in by the :class:`~docuharnessx.stages.write.WriteStage` from the runtime. The
``(messages, tools)`` request is built by the deterministic
:func:`docuharnessx.composition.prompt.build_request`, so this module owns no prompt
content; it owns only the call, the timeout bridge, and the response parse.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING, Any

from docuharnessx.composition.model import ProseResult
from docuharnessx.composition.prompt import build_request

if TYPE_CHECKING:  # frozen seam consumed verbatim — typing-only import.
    from docuharnessx.composition.model import CompositionBlueprint

__all__ = [
    "generate_prose",
    "DEFAULT_PROSE_TIMEOUT_S",
]

_log = logging.getLogger(__name__)

#: Default wall-clock budget for a single prose model call. A model that does not answer
#: within this many seconds is treated as a (logged, absorbed) timeout so the prose step
#: can never stall the run; the caller then renders the deterministic fallback (Req 5.3,
#: 5.4). A generation call is heavier than the planner's re-rank, so the budget is larger
#: than ``DEFAULT_RELEVANCE_TIMEOUT_S`` while staying bounded.
DEFAULT_PROSE_TIMEOUT_S: float = 60.0


def generate_prose(
    blueprint: "CompositionBlueprint",
    *,
    model: Any | None,
    timeout_s: float = DEFAULT_PROSE_TIMEOUT_S,
) -> ProseResult | None:
    """Generate one segment's ``body``/``summary`` via the bound model, fault-tolerantly.

    The single model-dependent step of the writer (Req 5.1). Issues exactly one bounded
    ``complete`` call (Req 5.3) using the deterministic request from
    :func:`docuharnessx.composition.prompt.build_request`, parses the response into a
    Markdown ``body`` plus a ``summary``, and returns a
    :class:`~docuharnessx.composition.model.ProseResult` with ``source="model"`` on a
    clean response. The prose source only ever sets ``body``/``summary`` (Req 5.5).

    Args:
        blueprint: The deterministic COBESY blueprint for one planned segment. Used only
            to build the model request; never mutated.
        model: A bound HarnessX ``BaseModelProvider``-shaped object, or ``None``. Only its
            awaitable ``complete(messages, tools, stream_callback=None)`` (returning an
            object with a ``.content`` string) is used. The composition package never
            constructs a provider itself (Req 5.2).
        timeout_s: Wall-clock budget for the single model call. Exceeding it is an
            absorbed (logged) timeout, not a failure of the run (Req 5.3, 5.4).

    Returns:
        A :class:`ProseResult` with ``source="model"`` on a clean, parseable, non-empty
        response; ``None`` when ``model`` is ``None`` or on any
        failure/timeout/empty/unparseable response, so the caller renders the deterministic
        fallback (Req 5.4). Never raises.
    """
    # Gate: a model-less call is not an error — it is the credential-free path. Return
    # None so the caller renders the deterministic fallback (Req 5.4).
    if model is None:
        return None

    try:
        content = _complete_with_timeout(blueprint, model, timeout_s)
    except TimeoutError:
        _log.warning(
            "Prose generation timed out after %.3gs for segment %r; "
            "falling back to the deterministic body.",
            timeout_s,
            getattr(blueprint, "segment_key", "?"),
        )
        return None
    except Exception:
        _log.warning(
            "Prose generation model call failed for segment %r; "
            "falling back to the deterministic body.",
            getattr(blueprint, "segment_key", "?"),
            exc_info=True,
        )
        return None

    parsed = _parse_content(content)
    if parsed is None:
        _log.warning(
            "Prose generation response was empty or unparseable for segment %r; "
            "falling back to the deterministic body.",
            getattr(blueprint, "segment_key", "?"),
        )
        return None

    body, summary = parsed
    return ProseResult(body=body, summary=summary, source="model")


# --------------------------------------------------------------------------- #
# Model invocation (single bounded call; all failures surface to the caller)   #
# --------------------------------------------------------------------------- #


def _complete_with_timeout(
    blueprint: "CompositionBlueprint", model: Any, timeout_s: float
) -> Any:
    """Run the model's awaitable ``complete`` to completion under ``timeout_s``.

    The prose step is called from synchronous code that may itself be offloaded off the
    run loop (the ``WriteStage`` drives this via :func:`asyncio.to_thread`, mirroring
    :meth:`PlanStage._maybe_apply_relevance`), so we drive the model's coroutine on a
    private event loop via :func:`asyncio.run`, wrapping it in :func:`asyncio.wait_for` to
    bound it — exactly as :func:`docuharnessx.planning.relevance._complete_with_timeout`.
    A timeout surfaces as :class:`TimeoutError`; the cancelled coroutine is not awaited
    further. Issues exactly one ``complete`` call and adds no loop (Req 5.3). Returns the
    response's ``.content`` (any type); parsing/validation happens in the caller.
    """
    messages, tools = build_request(blueprint)

    async def _drive() -> Any:
        return await asyncio.wait_for(
            model.complete(messages, tools, stream_callback=None),
            timeout=timeout_s,
        )

    response = asyncio.run(_drive())
    return getattr(response, "content", "")


# --------------------------------------------------------------------------- #
# Deterministic response parsing (empty/unparseable -> None)                   #
# --------------------------------------------------------------------------- #


def _parse_content(content: Any) -> tuple[str, str] | None:
    """Parse a model response ``.content`` into ``(body, summary)`` deterministically.

    The prompt asks for a Markdown ``body`` plus a short ``summary``; a cooperative model
    answers with a JSON object ``{"body": ..., "summary": ...}``. We therefore try a
    structured JSON parse first and fall back to treating the whole content as the body
    (deriving a summary from its lead) when the model returned plain prose — so a
    non-conforming-but-usable response is still accepted (Req 5.4).

    Returns ``(body, summary)`` with a non-empty ``body`` on success; ``None`` for a
    non-string, empty, or otherwise unusable response so the caller falls back (Req 6.3
    driver). Pure and deterministic: equal content always yields an equal result.
    """
    if not isinstance(content, str):
        return None

    stripped = content.strip()
    if not stripped:
        return None

    structured, was_structured = _parse_structured(stripped)
    if structured is not None:
        return structured
    if was_structured:
        # The content *was* a structured JSON object (the model honored the instruction)
        # but its body was missing/empty/non-string — that is an unusable response, not
        # plain prose. Reject it so the caller falls back, rather than emitting the raw
        # JSON literal as a body (Req 6.3 driver).
        return None

    # Plain-prose fallback: the whole (non-empty) content is the body; derive a short
    # summary from its leading sentence/line so the segment always has a summary.
    body = stripped
    summary = _derive_summary(body)
    return body, summary


def _parse_structured(stripped: str) -> tuple[tuple[str, str] | None, bool]:
    """Try to read a ``{"body": ..., "summary": ...}`` JSON object from ``stripped``.

    Returns ``(result, was_structured)``:

    * ``result`` is ``(body, summary)`` when the content is a JSON object carrying a
      non-empty string ``body`` (the ``summary`` is taken when it is a non-empty string,
      else derived from the body), else ``None``.
    * ``was_structured`` is ``True`` when the content parsed as a JSON object (so the
      model honored the structured-response instruction) even if its body was unusable —
      this lets the caller reject an empty-body structured response instead of treating
      the raw JSON literal as plain prose (Req 6.3 driver). It is ``False`` when the
      content is not a JSON object or is malformed, so the caller may try the plain-prose
      path.
    """
    if not (stripped.startswith("{") and stripped.endswith("}")):
        return None, False
    try:
        payload = json.loads(stripped)
    except (ValueError, TypeError):
        return None, False
    if not isinstance(payload, dict):
        return None, False

    raw_body = payload.get("body")
    if not isinstance(raw_body, str):
        return None, True
    body = raw_body.strip()
    if not body:
        return None, True

    raw_summary = payload.get("summary")
    summary = (
        raw_summary.strip()
        if isinstance(raw_summary, str) and raw_summary.strip()
        else _derive_summary(body)
    )
    return (body, summary), True


def _derive_summary(body: str) -> str:
    """Derive a short, deterministic one-line summary from a Markdown ``body``.

    Used when the model returned a body but no usable ``summary``. Takes the first
    non-empty, non-heading line of the body as a one-paragraph summary; if every line is a
    heading (or there is no prose line), falls back to the first non-empty line stripped of
    its Markdown heading markers. Pure and deterministic.
    """
    lines = [line.strip() for line in body.splitlines()]
    for line in lines:
        if line and not line.startswith("#"):
            return line
    for line in lines:
        if line:
            return line.lstrip("#").strip()
    return body.strip()
