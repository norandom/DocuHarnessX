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

import json
import sys
from collections.abc import Sequence
from typing import Any, AsyncIterator

from harnessx.core.events import Event, Message, ModelResponseEvent, ToolSchema
from harnessx.core.processor import Processor
from harnessx.providers.base import BaseModelProvider

from docuharnessx.deployer.commands import CompletedResult, DefaultCommandRunner
from docuharnessx.review import COBESY_CRITERIA
from docuharnessx.stages.base import PIPELINE_HOOK

__all__ = [
    "FakeProvider",
    "ReplacementStage",
    "make_replacement_stage",
    "RoutingFakeProvider",
    "PyMkdocsNoPushRunner",
]


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


# --------------------------------------------------------------------------- #
# RoutingFakeProvider — content-routing accept-path judge + writer prose        #
# (e2e-multi-project Req 2.1-2.5)                                               #
# --------------------------------------------------------------------------- #
#
# The bare :class:`FakeProvider` returns ``"done"`` for every ``complete`` call.
# That string is neither a parseable COBESY verdict nor parseable writer prose, so a
# full-pipeline run fails CLOSED: the Review gate marks every segment
# ``judge_source="unavailable"`` and rejects it, the accepted set is empty, and the
# assembled site has no real pages. To exercise the *accept* path end to end — so the
# assembled site for an arbitrary project is provably NON-empty — the e2e suite needs a
# provider that ROUTES BY PROMPT CONTENT:
#
# * a REVIEW/judge prompt -> a passing per-criterion JSON verdict the deterministic
#   verdict parser accepts (every COBESY criterion at/above threshold, overall pass), so
#   the gate accepts the judged segment (Req 2.2); and
# * any OTHER (writer) prompt -> a non-trivial ``{"body", "summary"}`` Markdown payload
#   the prose parser accepts, so written segment bodies are non-empty (Req 2.3).
#
# Routing key (validated by a grounding spike): the deterministic judge prompt assembler
# (:mod:`docuharnessx.review.prompt`) opens its system message with the distinctive phrase
# "objective COBESY documentation quality evaluator" and lists the COBESY criterion names,
# whereas the writer prompt assembler (:mod:`docuharnessx.composition.prompt`) does not.
# The classifier keys on that phrase plus the presence of the criterion-name markers, so a
# review prompt is recognized robustly while every writer prompt falls through to prose.


#: The distinctive phrase the deterministic judge system prompt opens with
#: (:data:`docuharnessx.review.prompt._SYSTEM_PROMPT`). Present in every review/judge
#: request and in no writer request, so it is the primary routing signal.
_JUDGE_PROMPT_MARKER = "COBESY documentation quality evaluator"


def _message_text(messages: "Sequence[Any]") -> str:
    """Join the textual content of a provider ``complete`` message list.

    Each message is a HarnessX :class:`~harnessx.core.events.Message` (a ``.content``
    string) or a plain ``{"role", "content"}`` dict (the lazy fallback the pure prompt
    assemblers emit when the harness ``Message`` import fails). Tolerates either shape and
    a missing/non-string content so the router never raises on an unexpected message.
    """
    parts: list[str] = []
    for message in messages:
        content = getattr(message, "content", None)
        if content is None and isinstance(message, dict):
            content = message.get("content", "")
        if content is not None:
            parts.append(str(content))
    return "\n".join(parts)


def _is_review_prompt(messages: "Sequence[Any]") -> bool:
    """Classify a ``complete`` request as a review/judge prompt (else a writer prompt).

    A review prompt is the deterministic judge request (:mod:`docuharnessx.review.prompt`):
    its system message carries the distinctive :data:`_JUDGE_PROMPT_MARKER` phrase and lists
    the named COBESY criteria. Requiring both the phrase and at least one criterion marker
    keeps the classification robust — a writer prompt (which carries neither) always falls
    through to the prose path. Pure and deterministic.
    """
    text = _message_text(messages)
    if _JUDGE_PROMPT_MARKER not in text:
        return False
    return any(name in text for name in COBESY_CRITERIA)


class RoutingFakeProvider(FakeProvider):
    """A no-network provider that ROUTES by prompt content (e2e-multi-project Req 2.x).

    Subclasses :class:`FakeProvider` (itself a :class:`BaseModelProvider`) so binding via
    ``ModelConfig(main=RoutingFakeProvider()).agentic(make_docgen(...))`` works and provider
    type checks pass (Req 2.1). It overrides only :meth:`complete` to classify each call and
    return the matching payload:

    * **review/judge prompt** -> a passing per-criterion JSON verdict (every
      :data:`~docuharnessx.review.COBESY_CRITERIA` criterion scored at/above threshold with
      ``passed=True`` and an overall pass), in the exact shape the deterministic verdict
      parser accepts — so the quality gate ACCEPTS the judged segment (Req 2.2); and
    * **writer prompt** -> a non-trivial ``{"body", "summary"}`` Markdown payload the prose
      parser accepts — so written segment bodies are non-empty (Req 2.3).

    Every response is a single end-turn :class:`~harnessx.core.events.ModelResponseEvent`
    (so the run reaches ``exit_reason="done"``, Req 2.5); no network access and no
    credentials are used (Req 2.4). ``count_tokens`` is inherited from :class:`FakeProvider`.
    """

    #: A constant, non-trivial Markdown writer body. Real headings + sections + bullet
    #: points so the prose parser accepts it and the assembled page is non-empty; it carries
    #: no project-specific literal so it is target-agnostic across every fixture.
    _WRITER_BODY = (
        "# Overview\n\n"
        "This segment documents one slice of the project for its intended audience.\n\n"
        "## Getting started\n\n"
        "- Read this section first.\n"
        "- Follow the steps in order.\n\n"
        "## Details\n\n"
        "The supporting detail lives here, grounded in the supplied evidence anchors.\n"
    )
    _WRITER_SUMMARY = "A concise one-line summary of this documentation segment."

    def __init__(self) -> None:
        super().__init__(content="")
        #: Per-class call counters so a test can assert both paths were exercised.
        self.review_calls = 0
        self.writer_calls = 0

    async def complete(
        self,
        messages: "list[Message]",
        tools: "list[ToolSchema]",
        stream_callback: object | None = None,
    ) -> ModelResponseEvent:
        if _is_review_prompt(messages):
            self.review_calls += 1
            content = self._passing_verdict_json()
        else:
            self.writer_calls += 1
            content = self._writer_payload_json()
        return ModelResponseEvent(
            run_id="routing-fake-run",
            step_id=0,
            content=content,
            finish_reason="end_turn",
        )

    @staticmethod
    def _passing_verdict_json() -> str:
        """A clean, passing per-criterion JSON verdict the verdict parser accepts (Req 2.2).

        Mirrors ``tests/test_stage_review_integration._passing_verdict_json``: every named
        COBESY criterion is scored ``1.0`` with ``passed=True`` and an overall ``passed=True``,
        so the verdict computer's threshold + all-of rule yields ``pass``.
        """
        return json.dumps(
            {
                "criteria": {
                    name: {"score": 1.0, "passed": True, "reason": "meets the criterion"}
                    for name in COBESY_CRITERIA
                },
                "passed": True,
                "reason": "all criteria met",
            }
        )

    @classmethod
    def _writer_payload_json(cls) -> str:
        """A ``{"body", "summary"}`` JSON payload the prose parser accepts (Req 2.3)."""
        return json.dumps({"body": cls._WRITER_BODY, "summary": cls._WRITER_SUMMARY})


# --------------------------------------------------------------------------- #
# PyMkdocsNoPushRunner — real `python -m mkdocs build`, refuses any push         #
# (e2e-multi-project Req 7.1, 7.3)                                              #
# --------------------------------------------------------------------------- #


class PyMkdocsNoPushRunner(DefaultCommandRunner):
    """A real :class:`DefaultCommandRunner` that builds via ``python -m mkdocs``, never pushes.

    Mirrors the deploy build-E2E ``_NoPushRealRunner`` (``tests/test_deploy_build_e2e_5_3``)
    so the e2e-multi-project suite drives a REAL ``mkdocs build`` under each fixture's
    per-target base-path while proving the ``gh-deploy`` network push is never exercised
    (Req 7.1, 7.3):

    * the leading ``mkdocs`` token the deploy orchestrator builds is rewritten to
      ``[sys.executable, "-m", "mkdocs", ...]`` before the real subprocess runs, so the build
      resolves through the project interpreter's installed ``mkdocs`` + ``mkdocs-material``
      regardless of whether a bare ``mkdocs`` console script is on ``PATH`` (Req 7.1);
    * a ``mkdocs gh-deploy`` argv sets :attr:`pushed` and raises — the push is refused, never
      a real network action (Req 7.3);
    * every other command (the ``git`` default-branch read) is delegated unchanged so the
      real deploy core still reads the target's default branch.

    :meth:`build_count` and :attr:`pushed` let assertions confirm exactly one build ran and
    no push ran (Req 7.4).
    """

    def __init__(self) -> None:
        self.commands: list[list[str]] = []
        self.pushed = False

    def run(
        self, args: "Sequence[str]", cwd: str, timeout: float | None = None
    ) -> CompletedResult:
        argv = list(args)
        self.commands.append(argv)
        if len(argv) >= 2 and argv[0] == "mkdocs" and argv[1] == "gh-deploy":
            self.pushed = True
            raise AssertionError(
                "the e2e-multi-project deploy modes must never reach the gh-deploy push"
            )
        if argv and argv[0] == "mkdocs":
            argv = [sys.executable, "-m", "mkdocs", *argv[1:]]
        return super().run(argv, cwd, timeout=timeout)

    def build_count(self) -> int:
        """Number of recorded ``mkdocs build`` invocations (Req 7.4)."""
        return sum(
            1
            for argv in self.commands
            if len(argv) >= 2 and argv[0] == "mkdocs" and argv[1] == "build"
        )
