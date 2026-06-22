"""The gated judge step — the ONLY model surface of the review core (task 3.1).

``docuharnessx.review.judge`` is the single module in the otherwise pure, model-free Wave 2
``quality-review-gate`` review core that may consult a model (design "Gated Judge Step";
Req 5.1, 5.2, 5.3, 5.4, 5.6). Everything else — the criteria builder, the prompt assembler,
the verdict parser, the verdict computer, and the aggregator — is deterministic and
unit-testable without any credentials; this module isolates the one fault-tolerant model
call behind a narrow, duck-typed boundary so the whole stage stays credential-free testable
end to end. The COBESY gate is a **quality firewall**: an unjudged segment is never silently
passed, so a model-less / failed / timed-out / unparseable judge yields the absent value
(``None``) and the caller (the verdict computer / the ``ReviewStage``) applies the
deterministic, fail-closed default-reject with ``judge_source="unavailable"`` (Req 5.4, 6.3).

Contract (design service interface)::

    def judge_segment(criteria, *, model, timeout_s=DEFAULT_JUDGE_TIMEOUT_S) -> JudgeVerdict | None

Two outcomes, exactly as the design pins them:

* **Clean response** — when a ``model`` is bound and returns a parseable ``.content``
  carrying at least one known COBESY criterion, the step delegates parsing to the
  deterministic :func:`docuharnessx.review.parse.parse_verdict` (fenced-code stripping,
  score clamp to ``[0,1]``, per-criterion ``passed`` fallback to the threshold rule,
  known-criteria-only) and returns the bounded
  :class:`~docuharnessx.review.model.JudgeVerdict` (Req 5.1). It produces only the parsed
  verdict — per-criterion scores + the overall flag + a reason — and never touches a segment
  field (Req 5.6).
* **Model-less / failure / timeout / empty / unparseable** — returns ``None`` so the caller
  applies the fail-closed default-reject (Req 5.4). A ``None`` model, any exception from
  ``complete``, a model that does not answer within ``timeout_s``, a non-string content, and
  an empty / unparseable / no-known-criterion body are all **absorbed**: logged at WARNING
  and reduced to ``None``. This step never raises.

Bounded by construction: at most **one** ``complete`` call per invocation and no loop —
cost/step budgeting belongs to the inherited Control bundle (Req 5.3).

Model coupling is intentionally minimal and duck-typed (mirroring
:mod:`docuharnessx.composition.prose`, :mod:`docuharnessx.planning.relevance`, and
:mod:`docuharnessx.analysis.enrich`): the step expects only a HarnessX
``BaseModelProvider``-shaped object — an awaitable ``complete(messages, tools,
stream_callback=None)`` returning an object with a ``.content`` string (a
``ModelResponseEvent`` in production; a ``FakeProvider`` / stand-in in tests). The review
package never imports a model class or constructs a provider — the bound model, if any, is
handed in by the :class:`~docuharnessx.stages.review.ReviewStage` from the runtime. The
``(messages, tools)`` request is built by the deterministic
:func:`docuharnessx.review.prompt.build_request`, so this module owns no prompt content; it
owns only the call, the timeout bridge, and delegating the response parse.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from docuharnessx.review.parse import parse_verdict
from docuharnessx.review.prompt import build_request

if TYPE_CHECKING:  # frozen seam consumed verbatim — typing-only import.
    from docuharnessx.review.model import JudgeVerdict, SegmentCriteria

__all__ = [
    "judge_segment",
    "DEFAULT_JUDGE_TIMEOUT_S",
]

_log = logging.getLogger(__name__)

#: Default wall-clock budget for a single judge model call. A model that does not answer
#: within this many seconds is treated as a (logged, absorbed) timeout so the judge step
#: can never stall the run; the caller then applies the fail-closed default-reject (Req 5.3,
#: 5.4). A per-segment judgement is a bounded single-shot scoring call (lighter than a prose
#: generation), so the budget mirrors the planner's re-rank hook rather than prose.
DEFAULT_JUDGE_TIMEOUT_S: float = 30.0


def judge_segment(
    criteria: "SegmentCriteria",
    *,
    model: Any | None,
    timeout_s: float = DEFAULT_JUDGE_TIMEOUT_S,
) -> "JudgeVerdict | None":
    """Judge one segment against its COBESY criteria via the bound model, fault-tolerantly.

    The single model-dependent step of the review gate (Req 5.1). Issues exactly one
    bounded ``complete`` call (Req 5.3) using the deterministic request from
    :func:`docuharnessx.review.prompt.build_request`, then delegates parsing to the
    deterministic :func:`docuharnessx.review.parse.parse_verdict` and returns the bounded
    :class:`~docuharnessx.review.model.JudgeVerdict` on a clean response. The step produces
    only the parsed verdict and never sets a segment field (Req 5.6).

    Args:
        criteria: The deterministic per-segment
            :class:`~docuharnessx.review.model.SegmentCriteria` for one written segment.
            Used only to build the model request and to bound the parse to the configured
            COBESY criteria; never mutated.
        model: A bound HarnessX ``BaseModelProvider``-shaped object, or ``None``. Only its
            awaitable ``complete(messages, tools, stream_callback=None)`` (returning an
            object with a ``.content`` string) is used. The review package never constructs
            a provider itself (Req 5.2).
        timeout_s: Wall-clock budget for the single model call. Exceeding it is an absorbed
            (logged) timeout, not a failure of the run (Req 5.3, 5.4).

    Returns:
        A :class:`~docuharnessx.review.model.JudgeVerdict` on a clean, parseable response
        scoring at least one known COBESY criterion; ``None`` when ``model`` is ``None`` or
        on any failure / timeout / empty / unparseable / no-known-criterion response, so the
        caller applies the fail-closed default-reject (Req 5.4, 6.3). Never raises.
    """
    # Gate: a model-less call is not an error — it is the credential-free path. Return None
    # so the caller applies the fail-closed default-reject (Req 5.4, 6.3).
    if model is None:
        return None

    try:
        content = _complete_with_timeout(criteria, model, timeout_s)
    except TimeoutError:
        _log.warning(
            "Judge call timed out after %.3gs for segment %r; "
            "treating the segment as unjudged (default-reject).",
            timeout_s,
            getattr(criteria, "segment_id", "?"),
        )
        return None
    except Exception:
        _log.warning(
            "Judge model call failed for segment %r; "
            "treating the segment as unjudged (default-reject).",
            getattr(criteria, "segment_id", "?"),
            exc_info=True,
        )
        return None

    if not isinstance(content, str):
        _log.warning(
            "Judge response had a non-string content for segment %r; "
            "treating the segment as unjudged (default-reject).",
            getattr(criteria, "segment_id", "?"),
        )
        return None

    verdict = parse_verdict(content, criteria)
    if verdict is None:
        _log.warning(
            "Judge response was empty or unparseable for segment %r; "
            "treating the segment as unjudged (default-reject).",
            getattr(criteria, "segment_id", "?"),
        )
    return verdict


# --------------------------------------------------------------------------- #
# Model invocation (single bounded call; all failures surface to the caller)   #
# --------------------------------------------------------------------------- #


def _complete_with_timeout(
    criteria: "SegmentCriteria", model: Any, timeout_s: float
) -> Any:
    """Run the model's awaitable ``complete`` to completion under ``timeout_s``.

    The judge step is called from synchronous code that may itself be offloaded off the run
    loop (the ``ReviewStage`` drives this via :func:`asyncio.to_thread`, mirroring
    :meth:`PlanStage._maybe_apply_relevance` and the writer's prose step), so we drive the
    model's coroutine on a private event loop via :func:`asyncio.run`, wrapping it in
    :func:`asyncio.wait_for` to bound it — exactly as
    :func:`docuharnessx.composition.prose._complete_with_timeout` and
    :func:`docuharnessx.planning.relevance._complete_with_timeout`. A timeout surfaces as
    :class:`TimeoutError`; the cancelled coroutine is not awaited further. Issues exactly one
    ``complete`` call and adds no loop (Req 5.3). Returns the response's ``.content`` (any
    type); parsing/validation happens in the caller. Building the request never touches a
    segment field (Req 5.6).
    """
    messages, tools = build_request(criteria)

    async def _drive() -> Any:
        return await asyncio.wait_for(
            model.complete(messages, tools, stream_callback=None),
            timeout=timeout_s,
        )

    response = asyncio.run(_drive())
    return getattr(response, "content", "")
