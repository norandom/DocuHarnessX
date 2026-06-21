"""Test-scoped fakes for credential-free DocuHarnessX runs.

The empty pipeline still drives the HarnessX run loop, which calls
``provider.complete()``. There are no live API keys in CI, so any test that binds
a model (or actually runs the harness) injects :class:`FakeProvider` instead of a
real provider. This is deliberately **test-only**: production model resolution
(:mod:`docuharnessx.model_resolver`) still resolves real providers from config/env
and is never touched by this module.

:class:`FakeProvider` satisfies the HarnessX
:class:`~harnessx.providers.base.BaseModelProvider` protocol (it subclasses it so
``isinstance(..., BaseModelProvider)`` holds and ``.agentic`` is available):

* ``complete(...)`` returns a single end-turn :class:`ModelResponseEvent` with no
  tool calls and ``finish_reason='end_turn'`` — the run loop accepts ``'end_turn'``
  (or ``'stop'``) as a terminal turn, so a real run reaches ``exit_reason='done'``
  in one step with NO network call.
* ``count_tokens(...)`` returns a small constant int.

:class:`ReplacementStage` / :func:`make_replacement_stage` model a *single* Wave 1+
stage swap: a genuine, importable alternative stage processor (and its factory) a
later spec could drop into :data:`docuharnessx.stages.STAGES` in place of one no-op
stub. It lives here, at module scope, so HarnessX can serialize it to a real
``_target_`` import path (a class defined inside a test function cannot be) — which
is exactly what the single-stage replaceability validation (task 5.2, Req 5.6)
needs to prove the swap flows through ``make_docgen`` unchanged.
"""

from __future__ import annotations

from typing import AsyncIterator

from harnessx.core.events import Event, Message, ModelResponseEvent, ToolSchema
from harnessx.core.processor import Processor
from harnessx.providers.base import BaseModelProvider

from docuharnessx.stages.base import PIPELINE_HOOK

__all__ = ["FakeProvider", "ReplacementStage", "make_replacement_stage"]


class FakeProvider(BaseModelProvider):
    """A no-network provider that ends the turn immediately.

    Subclasses :class:`BaseModelProvider` so it is a genuine provider (gains the
    ``agentic`` mixin and passes ``isinstance`` checks) while overriding only the
    two methods the run loop calls.
    """

    def __init__(self, content: str = "done") -> None:
        self._content = content

    async def complete(
        self,
        messages: list[Message],
        tools: list[ToolSchema],
        stream_callback: object | None = None,
    ) -> ModelResponseEvent:
        # Single end-turn response, no tool calls: the run loop treats
        # finish_reason 'end_turn' as a terminal turn and exits with 'done'.
        return ModelResponseEvent(
            run_id="fake-run",
            step_id=0,
            content=self._content,
            finish_reason="end_turn",
        )

    def count_tokens(self, messages: list[Message]) -> int:
        return 1


class ReplacementStage:
    """A distinguishable, importable alternative pipeline stage (Wave 1+ swap).

    Mirrors the no-op stub contract — it attaches to :data:`PIPELINE_HOOK` and its
    ``process`` is a pure pass-through — but is a *different* class with a sentinel
    ``stage_name`` so a swap of it into :data:`docuharnessx.stages.STAGES` is
    observable. Because it is defined at module scope it serializes to a real
    ``_target_`` (``_fakes.ReplacementStage``), so the single-stage replaceability
    test can see the swap survive ``make_docgen``'s composition (Req 5.6).
    """

    #: Bound hook the registry/bundle attach this processor to (same hook as the
    #: no-op stubs, so the swap stays a single-hook, single-stage change).
    _hook = PIPELINE_HOOK

    #: Sentinel stage identity so the swap is distinguishable from any no-op stub.
    stage_name = "classify-REPLACED"

    async def process(self, event: Event) -> AsyncIterator[Event]:
        # Pure pass-through, like the no-op stubs: forward the event unchanged.
        yield event


def make_replacement_stage() -> Processor:
    """Factory for :class:`ReplacementStage` (mirrors a ``make_<stage>_stage``).

    Returns a fresh :class:`ReplacementStage` each call, matching the per-stage
    factory contract a Wave 1+ spec uses when it replaces one entry's factory in
    :data:`docuharnessx.stages.STAGES`.
    """
    return ReplacementStage()
