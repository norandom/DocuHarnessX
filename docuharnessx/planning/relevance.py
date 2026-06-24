"""The optional, gated LLM relevance hook: annotate / re-rank only (task 3.3).

``docuharnessx.planning.relevance`` is the **only** surface in the otherwise pure,
model-free planning core that may consult a model — and it is built so a model can
never invent, drop, or alter the deterministic core of a
:class:`~docuharnessx.planning.model.CoveragePlan` (design "relevance — optional gated
LLM re-rank"; Req 8.2, 8.3, 8.4, 8.5). The planner (task 3.2) always produces a
complete, ordered plan with ``relevance_applied=False``; this hook wraps that plan and
*optionally* re-orders the existing segments and sets per-segment ``relevance_note``.
It never reads from or writes to the required writer fields (``roles`` / ``intent`` /
``subjects``), never changes a segment's ``priority`` or ``evidence``, and never adds or
removes a segment.

Contract (design service interface)::

    def apply_relevance(plan, *, model=None, enabled=False, timeout_s=30.0) -> CoveragePlan

Three behaviors, exactly as the design pins them:

* **Disabled / model-less** — when ``enabled is False`` *or* ``model is None`` the input
  ``plan`` is returned **unchanged** (same object, ``relevance_applied is False``). This
  is the default and is treated as *success*, never an error (Req 8.3). The model is
  never consulted in this path, and the gate is an explicit caller flag — no env-driven
  hidden activation (Req 8.5).
* **Enabled + model + success** — the model is asked, given the existing segment keys, to
  return a re-ranking (a permutation of those keys) plus optional per-key notes. When the
  response is a valid permutation of *exactly* the existing keys, the plan is rebuilt with
  the segments in that order and the notes attached, via ``dataclasses.replace(plan,
  segments=..., relevance_applied=True)``. Because each segment is carried over by key
  with only its ``relevance_note`` overridden, **every required writer field and the set
  of segments is byte-for-byte preserved** — the model can only reorder and annotate
  (Req 8.2).
* **Failure / timeout / out-of-bounds response** — any exception from the model, a model
  that does not answer within ``timeout_s``, or a response that is not a clean permutation
  of the existing keys (drops, invents, or duplicates a key, or is unparseable) is
  **absorbed**: the failure is logged at WARNING and the *complete, unchanged*
  deterministic plan is returned (``relevance_applied is False``). The run continues; the
  hook is best-effort and never fatal (Req 8.4).

Determinism is preserved by construction: relevance is *off by default*, the gate is an
explicit caller flag, and a failed/disabled/out-of-bounds hook leaves the plan exactly as
the deterministic planner produced it, so a model-free run is fully reproducible
(Req 8.1, 8.3).

Model coupling is intentionally minimal and duck-typed (mirroring
:mod:`docuharnessx.analysis.enrich`). The hook expects only a HarnessX
``BaseModelProvider``-shaped object: an awaitable
``complete(messages, tools, stream_callback=None)`` returning an object with a
``.content`` string (a ``ModelResponseEvent`` in production; any stand-in in tests). The
planning package never imports a model class or constructs a provider — the bound model,
if any, is handed in by the Plan stage from the runtime.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
import os
from typing import Any

from docuharnessx.planning.model import CoveragePlan, PlannedSegment

__all__ = [
    "apply_relevance",
    "DEFAULT_RELEVANCE_TIMEOUT_S",
]

_log = logging.getLogger(__name__)


def _timeout_from_env(name: str, default: float) -> float:
    """Positive float seconds from environment variable *name*, else *default*."""
    raw = os.environ.get(name, "").strip()
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


#: Default wall-clock budget for a single relevance model call. A model that does not answer
#: within this many seconds is treated as a (logged, absorbed) timeout so the hook can never
#: stall the run (Req 8.4). Sized generously for slow models; raisable/lowerable via
#: ``DHX_RELEVANCE_TIMEOUT_S``.
DEFAULT_RELEVANCE_TIMEOUT_S: float = _timeout_from_env("DHX_RELEVANCE_TIMEOUT_S", 120.0)

#: A compact, model-agnostic instruction prompt. The model is shown only the existing
#: segment keys (no file content) and is constrained to *reordering* them and adding
#: short notes — it cannot invent, drop, or alter segments; any attempt to do so is
#: rejected downstream and the deterministic plan is kept (Req 8.2).
_SYSTEM_PROMPT = (
    "You are prioritizing documentation segments for a software repository. "
    "You are given a list of segment keys already chosen by a deterministic planner. "
    "Re-rank them by reader relevance (most important first) and optionally add a short "
    "note explaining each ranking. You MUST NOT add, remove, rename, or merge keys: "
    "return every given key exactly once. Respond with a single JSON object: "
    '{"order": [<segment keys, most relevant first>], '
    '"notes": {<segment key>: <short note string>}}. JSON only, no prose.'
)


def apply_relevance(
    plan: CoveragePlan,
    *,
    model: Any | None = None,
    enabled: bool = False,
    timeout_s: float = DEFAULT_RELEVANCE_TIMEOUT_S,
) -> CoveragePlan:
    """Optionally re-rank and annotate *plan*'s segments within strict bounds.

    Args:
        plan: The complete, deterministic :class:`CoveragePlan` from the planner
            (``relevance_applied`` expected to be ``False``).
        model: A bound HarnessX ``BaseModelProvider``-shaped object, or ``None``. Only
            its awaitable ``complete(messages, tools, stream_callback=None)`` (returning
            an object with a ``.content`` string) is used. The planning package never
            constructs a provider itself.
        enabled: The explicit gate. The hook is attempted only when this is ``True``
            *and* a ``model`` is given; otherwise the plan is returned unchanged
            (Req 8.3, 8.5).
        timeout_s: Wall-clock budget for the single model call. Exceeding it is an
            absorbed (logged) timeout, not a failure of the run (Req 8.4).

    Returns:
        The unchanged input ``plan`` (``relevance_applied is False``) when disabled,
        model-less, or on any failure/timeout/out-of-bounds response; otherwise a copy
        with the same segments **re-ordered** and ``relevance_note`` set where the model
        provided one, ``relevance_applied=True`` — every segment's ``roles`` / ``intent``
        / ``subjects`` / ``priority`` / ``evidence`` and the *set* of segments preserved
        (Req 8.2, 8.3, 8.4).
    """
    # Gate: off by default, and model-less is not an error. Return the *same* object so a
    # disabled run is provably the bare deterministic plan (Req 8.3, 8.5).
    if not enabled or model is None:
        return plan

    try:
        directive = _run_relevance(plan, model, timeout_s)
    except Exception:  # pragma: no cover - defensive: _run_relevance self-absorbs
        # Belt-and-braces: _run_relevance already absorbs and logs, but if anything
        # leaks (e.g. building the prompt), never let it gate the core (Req 8.4).
        _log.warning(
            "Plan relevance hook failed unexpectedly; "
            "returning the deterministic plan unchanged.",
            exc_info=True,
        )
        return plan

    if directive is None:
        # Disabled-equivalent outcome (failure/timeout/out-of-bounds, already logged):
        # keep the deterministic plan exactly as produced (Req 8.4).
        return plan

    order, notes = directive
    reordered = _reorder(plan.segments, order, notes)
    return dataclasses.replace(
        plan, segments=reordered, relevance_applied=True
    )


# --------------------------------------------------------------------------- #
# Re-rank application (pure, bounds-preserving)                                #
# --------------------------------------------------------------------------- #


def _reorder(
    segments: tuple[PlannedSegment, ...],
    order: tuple[str, ...],
    notes: dict[str, str],
) -> tuple[PlannedSegment, ...]:
    """Rebuild *segments* in ``order``, attaching ``notes`` — required fields preserved.

    ``order`` is a validated permutation of every segment key (see
    :func:`_validate_order`), so each original segment is emitted exactly once. Only
    ``relevance_note`` is overridden (from ``notes`` when present, else carried as-is);
    every other field — ``roles`` / ``intent`` / ``subjects`` / ``priority`` /
    ``evidence`` / ``segment_key`` — is copied verbatim via ``dataclasses.replace``, so
    the model cannot alter a writer field (Req 8.2).
    """
    by_key = {seg.segment_key: seg for seg in segments}
    rebuilt: list[PlannedSegment] = []
    for key in order:
        seg = by_key[key]
        note = notes.get(key, seg.relevance_note)
        if note == seg.relevance_note:
            rebuilt.append(seg)
        else:
            rebuilt.append(dataclasses.replace(seg, relevance_note=note))
    return tuple(rebuilt)


# --------------------------------------------------------------------------- #
# Model invocation + response parsing (all failures absorbed -> None)          #
# --------------------------------------------------------------------------- #


def _run_relevance(
    plan: CoveragePlan, model: Any, timeout_s: float
) -> tuple[tuple[str, ...], dict[str, str]] | None:
    """Call the model and parse a bounded re-rank directive, absorbing failures.

    Bridges the synchronous, deterministic planner world to the model's awaitable
    ``complete``. Returns ``(order, notes)`` when the model returns a clean permutation
    of exactly the plan's segment keys; returns ``None`` (logged) on any model error,
    timeout, unparseable response, or out-of-bounds order so the caller keeps the
    deterministic plan (Req 8.2, 8.4). Never raises.
    """
    try:
        response = _complete_with_timeout(model, plan, timeout_s)
    except TimeoutError:
        _log.warning(
            "Plan relevance hook timed out after %.3gs; "
            "keeping the deterministic plan.",
            timeout_s,
        )
        return None
    except Exception:
        _log.warning(
            "Plan relevance model call failed; keeping the deterministic plan.",
            exc_info=True,
        )
        return None

    content = getattr(response, "content", "")
    if not isinstance(content, str):
        _log.warning(
            "Plan relevance response had a non-string content; "
            "keeping the deterministic plan."
        )
        return None

    return _parse_directive(content, plan)


def _parse_directive(
    content: str, plan: CoveragePlan
) -> tuple[tuple[str, ...], dict[str, str]] | None:
    """Parse the model's JSON re-rank directive against the plan's keys.

    Accepts a JSON object ``{"order": [...], "notes": {...}}``. The ``order`` must be a
    permutation of *exactly* the plan's segment keys — same multiset, no drops, no
    inventions, no duplicates — or the directive is rejected (``None``) and the
    deterministic plan is kept (Req 8.2). ``notes`` is best-effort: only string notes for
    keys present in the plan are kept; unknown keys or non-string values are dropped
    without rejecting the whole re-rank (a stray note is far less dangerous than a bad
    order). Any malformed JSON or wrong shape is absorbed to ``None``.
    """
    try:
        payload = json.loads(content)
    except (ValueError, TypeError):
        _log.warning(
            "Plan relevance response was not valid JSON; "
            "keeping the deterministic plan."
        )
        return None

    if not isinstance(payload, dict):
        _log.warning(
            "Plan relevance response was not a JSON object; "
            "keeping the deterministic plan."
        )
        return None

    plan_keys = [seg.segment_key for seg in plan.segments]
    order = _validate_order(payload.get("order"), plan_keys)
    if order is None:
        return None

    notes = _validate_notes(payload.get("notes"), set(plan_keys))
    return order, notes


def _validate_order(
    raw_order: Any, plan_keys: list[str]
) -> tuple[str, ...] | None:
    """Validate ``raw_order`` is a permutation of exactly ``plan_keys``.

    Returns the order as a tuple when it contains every plan key exactly once (a clean
    permutation), else ``None`` (logged). This is the single guard that makes the hook
    incapable of dropping or inventing a segment: an order that is not a bijection over
    the existing keys is rejected wholesale (Req 8.2).
    """
    if not isinstance(raw_order, list) or not all(
        isinstance(k, str) for k in raw_order
    ):
        _log.warning(
            "Plan relevance 'order' was missing or not a list of strings; "
            "keeping the deterministic plan."
        )
        return None

    # A clean permutation: same multiset of keys (rejects drops, inventions, and dupes).
    if sorted(raw_order) != sorted(plan_keys):
        _log.warning(
            "Plan relevance 'order' was not a permutation of the planned segment "
            "keys (it dropped, invented, or duplicated a key); "
            "keeping the deterministic plan."
        )
        return None

    return tuple(raw_order)


def _validate_notes(raw_notes: Any, known_keys: set[str]) -> dict[str, str]:
    """Extract per-key string notes for keys that exist in the plan (best-effort).

    A missing/ill-typed ``notes`` block yields no notes (the re-rank still applies). Only
    entries whose key is a real plan key and whose value is a string are kept; everything
    else is ignored — a stray note never rejects a valid re-rank.
    """
    if not isinstance(raw_notes, dict):
        return {}
    return {
        key: value
        for key, value in raw_notes.items()
        if isinstance(key, str) and key in known_keys and isinstance(value, str)
    }


def _complete_with_timeout(model: Any, plan: CoveragePlan, timeout_s: float) -> Any:
    """Run the model's awaitable ``complete`` to completion under ``timeout_s``.

    The relevance hook is called from synchronous, deterministic code (the planner
    composition / the Plan stage), so we drive the model's coroutine on a private event
    loop via :func:`asyncio.run`, wrapping it in :func:`asyncio.wait_for` to bound it. A
    timeout surfaces as :class:`TimeoutError`; the cancelled coroutine is not awaited
    further. Building the request never touches the segment fields.
    """
    messages, tools = _build_request(plan)

    async def _drive() -> Any:
        return await asyncio.wait_for(
            model.complete(messages, tools, stream_callback=None),
            timeout=timeout_s,
        )

    return asyncio.run(_drive())


def _build_request(plan: CoveragePlan) -> tuple[list[Any], list[Any]]:
    """Build the ``(messages, tools)`` request for the bound model.

    Messages follow the HarnessX :class:`~harnessx.core.events.Message` shape — a system
    instruction plus a user message carrying a compact, deterministic brief of the
    existing segments (key + roles + intent + a short subject list; never file content).
    No tools are offered: the hook is a single-shot re-rank, not an agentic loop.
    HarnessX is imported lazily and behind a fallback so the pure planning core never
    hard-depends on the harness at import time.
    """
    brief = _render_brief(plan)
    try:
        from harnessx.core.events import Message

        messages = [
            Message(role="system", content=_SYSTEM_PROMPT),
            Message(role="user", content=brief),
        ]
    except Exception:
        # Fallback to plain dicts if the harness Message type is unavailable; the
        # provider protocol only requires an iterable of message-like records.
        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": brief},
        ]
    return messages, []


def _render_brief(plan: CoveragePlan) -> str:
    """Render a small, deterministic textual brief of the planned segments.

    Read-only over the plan — for each segment it lists the key, roles, intent, and the
    canonical subject strings the deterministic planner already established (no file
    content). Pure: returns a string and never mutates ``plan``.
    """
    lines = [
        f"Repository: {plan.repo_path}",
        f"Segments ({len(plan.segments)}):",
    ]
    for seg in plan.segments:
        roles = ",".join(seg.roles)
        subjects = ", ".join(s.canonical() for s in seg.subjects) or "none"
        lines.append(
            f"- key={seg.segment_key} roles=[{roles}] intent={seg.intent} "
            f"subjects=[{subjects}]"
        )
    return "\n".join(lines)
