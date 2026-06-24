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

from harnessx.core.events import Event, Message, ModelResponseEvent, ToolCall, ToolSchema
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
    "ScriptedAgentProvider",
    "ScriptedReviewAgentProvider",
    "SCRIPTED_AGENT_BODY",
    "SCRIPTED_AGENT_READS",
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


#: The distinctive opening of the agentic writer's task description
#: (:func:`docuharnessx.composition.task_prompt.build_agent_task`). Present in every
#: writer-agentic sub-run prompt and in neither the review/judge prompt nor the top-level
#: skeleton run-loop turn, so it is the routing signal that distinguishes a writer-agentic
#: turn (the scripted read/grep-then-body script) from the bare run-loop turn (end immediately).
_WRITER_AGENTIC_MARKER = (
    "writing one documentation segment for a software repository by "
    "exploring its real source code"
)


def _is_writer_agentic_prompt(messages: "Sequence[Any]") -> bool:
    """Classify a ``complete`` request as an agentic-writer sub-run prompt.

    The agentic Write stage runs a bounded HarnessX agent *per segment* whose task description
    opens with :data:`_WRITER_AGENTIC_MARKER`. That marker is carried into every step of that
    sub-run (it is the task's user message) and appears in no other request, so it reliably
    separates a writer-agentic turn — which must be answered by the scripted read/grep script —
    from the top-level skeleton run-loop turn, which must end immediately. Pure/deterministic.
    """
    return _WRITER_AGENTIC_MARKER in _message_text(messages)


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


# --------------------------------------------------------------------------- #
# ScriptedAgentProvider — drives the REAL HarnessX run loop offline            #
# (agentic-codebase-writer task 1.2, Req 9.1, 9.2)                             #
# --------------------------------------------------------------------------- #
#
# The Wave 2.5 ``agentic-codebase-writer`` replaces the writer's single-shot
# ``model.complete(messages, tools=[])`` step with a bounded, per-segment HarnessX
# AGENTIC run: the agent explores the target repository with the built-in
# read/grep/glob/bash tools over a read-only ``Workspace`` rooted at the repo and emits a
# grounded, ``file:line``-cited, Mermaid-diagrammed body (Req 3.x, 4.x). To keep that
# whole path testable end to end with NO network and NO credentials (Req 9.1, 9.2), the
# tests need a ``BaseModelProvider``-shaped fake whose ``complete`` returns a DETERMINISTIC
# SCRIPT — a fixed sequence of tool-call turns (read/grep over the crafted fixture repo)
# followed by a final end-turn grounded body — and that drives the REAL run loop:
#
#   • the run loop calls ``provider.complete(messages, tools)`` once per step;
#   • a scripted tool-call turn makes the run loop execute the REAL ``Read``/``Grep`` tools
#     against the fixture repo (real file reads occur), append the results as ``role=tool``
#     messages, and call ``complete`` again for the next step; and
#   • the final end-turn turn (``finish_reason="end_turn"``, no tool calls) ends the run
#     with ``exit_reason="done"`` and ``final_output`` = the grounded body.
#
# Determinism comes from STATELESS turn selection: each ``complete`` call counts how many
# of the provider's scripted tool-call turns are already present in ``messages`` (one
# assistant message carrying tool_calls per consumed turn) and returns the NEXT turn — or
# the final body once every scripted turn has been consumed. This mirrors how the run loop
# itself advances (each step appends one assistant message then the tool results), so the
# provider needs no internal step counter to stay correct across retries or re-entry.
#
# The fixture repo lives at ``tests/fixtures/agentic_repo`` (task 1.3): the scripted reads
# target ``app.py``/``engine.py``/``config.py`` with paths RELATIVE to the workspace root,
# which the read tool resolves through the active sandbox — so the SAME script works for any
# repo path the harness is rooted at. The final body cites four real ``file:line`` sources
# spanning THREE DISTINCT files, satisfying the structure gate's ``MIN_CITED_FILES`` (3)
# and carrying one valid ``graph TD`` Mermaid fence, so it also reaches the review accept
# path (Req 9.4, validated by later tasks).


#: The scripted exploration turns, in order. Each entry is one *tool-call turn*: a tuple of
#: ``(tool_name, tool_input)`` pairs the provider emits as a single assistant turn carrying
#: HarnessX :class:`~harnessx.core.events.ToolCall` objects. The run loop executes these
#: real builtin tools against the fixture repo. Paths are RELATIVE so the workspace sandbox
#: resolves them against whatever root the harness is rooted at (the fixture repo in tests).
SCRIPTED_AGENT_READS: tuple[tuple[tuple[str, dict], ...], ...] = (
    # Turn 1 — read the planner's primary evidence file.
    (("Read", {"file_path": "app.py"}),),
    # Turn 2 — follow the import into the engine, and grep for the entry symbol so a real
    #          Grep also executes (exercising both read and grep tools, Req 9.2).
    (
        ("Read", {"file_path": "engine.py"}),
        ("Grep", {"pattern": "def load_config", "output_mode": "files_with_matches"}),
    ),
    # Turn 3 — read the configuration module the engine depends on.
    (("Read", {"file_path": "config.py"}),),
)


#: The final grounded body the provider returns once every scripted tool-call turn has been
#: consumed. Contains exactly one valid ``graph TD`` Mermaid fence (vertical, short nodes,
#: valid arrows) and four ``file:line`` citations spanning THREE distinct fixture files
#: (``app.py``, ``engine.py``, ``config.py``) — at/above ``MIN_CITED_FILES`` (3) — so it
#: clears the deterministic structure gate and reaches the review accept path. The cited
#: lines resolve to real fixture content (``app.py:11`` Application, ``app.py:17`` run,
#: ``engine.py:16`` start, ``config.py:10`` load_config).
SCRIPTED_AGENT_BODY: str = (
    "# How the application starts\n\n"
    "The entry point wires an `Application` (`app.py:11`) to the work engine: calling\n"
    "`Application.run` (`app.py:17`) delegates straight to `Engine.start`\n"
    "(`engine.py:16`), which first loads the run configuration via `load_config`\n"
    "(`config.py:10`) and then drives one bounded work cycle.\n\n"
    "```mermaid\n"
    "graph TD\n"
    "  App[Application] --> Run[run]\n"
    "  Run --> Start[Engine.start]\n"
    "  Start --> Cfg[load_config]\n"
    "```\n\n"
    "Start from `app.py`, follow the import into `engine.py`, then read `config.py`\n"
    "to see the defaults the engine applies.\n"
)


class ScriptedAgentProvider(BaseModelProvider):
    """A no-network provider that drives the real run loop with a fixed agentic script.

    Subclasses :class:`BaseModelProvider` so it is a genuine provider (gains the
    ``agentic`` mixin and passes ``isinstance`` checks) while overriding only the two
    methods the run loop calls. Each :meth:`complete` returns, in order, one
    :class:`~harnessx.core.events.ModelResponseEvent` per scripted tool-call turn (carrying
    real :class:`~harnessx.core.events.ToolCall` objects, ``finish_reason="tool_use"``) and
    then a final end-turn response whose ``content`` is :data:`SCRIPTED_AGENT_BODY` — a
    grounded body with a valid Mermaid fence and ``file:line`` citations.

    The next turn is chosen STATELESSLY from the conversation: it counts how many scripted
    tool-call turns are already represented in ``messages`` (one assistant message with
    ``tool_calls`` per consumed turn) and returns the following turn. This keeps the run
    deterministic without an internal step counter, mirroring how the run loop advances. The
    optional :attr:`complete_calls` and :attr:`read_paths` counters let tests assert the
    script was actually exercised.
    """

    def __init__(
        self,
        reads: "Sequence[Sequence[tuple[str, dict]]] | None" = None,
        body: str = SCRIPTED_AGENT_BODY,
    ) -> None:
        # Freeze the script into tuples so it cannot be mutated mid-run.
        self._reads: tuple[tuple[tuple[str, dict], ...], ...] = tuple(
            tuple(turn) for turn in (reads if reads is not None else SCRIPTED_AGENT_READS)
        )
        self._body = body
        #: Number of ``complete`` calls the run loop made (one per step).
        self.complete_calls = 0
        #: Flattened list of file paths the scripted ``Read`` turns requested, in order,
        #: so a test can assert which fixture files the real read tool was driven over.
        self.read_paths: list[str] = [
            call_input["file_path"]
            for turn in self._reads
            for (name, call_input) in turn
            if name == "Read" and "file_path" in call_input
        ]

    async def complete(
        self,
        messages: "list[Message]",
        tools: "list[ToolSchema]",
        stream_callback: object | None = None,
    ) -> ModelResponseEvent:
        self.complete_calls += 1
        # Count how many scripted tool-call turns are already consumed: each consumed turn
        # left exactly one assistant message carrying tool_calls in the conversation.
        consumed = sum(
            1
            for m in messages
            if getattr(m, "role", None) == "assistant" and getattr(m, "tool_calls", ())
        )
        if consumed < len(self._reads):
            turn = self._reads[consumed]
            tool_calls = tuple(
                ToolCall(id=f"scripted-{consumed}-{idx}", name=name, input=dict(call_input))
                for idx, (name, call_input) in enumerate(turn)
            )
            return ModelResponseEvent(
                run_id="scripted-agent-run",
                step_id=consumed,
                content="",
                tool_calls=tool_calls,
                finish_reason="tool_use",
            )
        # Every scripted exploration turn is done — emit the final grounded body and end.
        return ModelResponseEvent(
            run_id="scripted-agent-run",
            step_id=consumed,
            content=self._body,
            finish_reason="end_turn",
        )

    def count_tokens(self, messages: "list[Message]") -> int:
        return 1


# --------------------------------------------------------------------------- #
# ScriptedReviewAgentProvider — full credential-free pipeline (write + review)  #
# (agentic-codebase-writer task 5.2, Req 9.2, 9.4)                             #
# --------------------------------------------------------------------------- #
#
# Task 5.2 drives the FULL pipeline (Write -> Review -> Assemble -> build) over the crafted
# fixture repo with NO network and NO credentials, and asserts the agentic writer reaches the
# REVIEW ACCEPT path so the assembled site is non-empty (Req 9.2, 9.4). The pipeline binds ONE
# model (``ModelConfig(main=provider)``), and BOTH the agentic Write stage and the single-shot
# Review stage call ``provider.complete`` on it. So the e2e provider must answer two kinds of
# request from one object:
#
#   • a WRITER-AGENTIC turn -> the deterministic scripted read/grep tool-call sequence then the
#     final grounded body (exactly :class:`ScriptedAgentProvider`), driving the REAL run loop's
#     real builtin tools over the read-only fixture workspace; and
#   • a REVIEW/JUDGE prompt -> a passing per-criterion COBESY verdict the deterministic verdict
#     parser accepts, so the gate ACCEPTS every written segment (Req 9.4).
#
# It routes by the SAME robust prompt-content signal :class:`RoutingFakeProvider` uses
# (:func:`_is_review_prompt`): the judge request opens with the distinctive
# :data:`_JUDGE_PROMPT_MARKER` phrase and lists the named COBESY criteria, whereas the
# writer-agentic task carries neither — so a review prompt is recognized first and every other
# ``complete`` call falls through to the scripted agentic turn selection.


class ScriptedReviewAgentProvider(ScriptedAgentProvider):
    """Drive the agentic Write loop AND the Review judge from one offline provider (task 5.2).

    Subclasses :class:`ScriptedAgentProvider` (a genuine :class:`BaseModelProvider`) so the
    bind ``ModelConfig(main=ScriptedReviewAgentProvider()).agentic(make_docgen(...))`` works
    and the writer-agentic path is the inherited scripted read/grep-then-body script. It
    overrides only :meth:`complete` to ROUTE by prompt content:

    * a **review/judge prompt** (classified by :func:`_is_review_prompt`) -> a single end-turn
      response whose ``content`` is a passing per-criterion COBESY verdict (every
      :data:`~docuharnessx.review.COBESY_CRITERIA` criterion at/above threshold with an overall
      pass), in the exact shape the deterministic verdict parser accepts — so the quality gate
      ACCEPTS every written segment (Req 9.4); and
    * any **other** prompt -> the inherited :class:`ScriptedAgentProvider` agentic turn (the
      scripted tool-call sequence, then the grounded :data:`SCRIPTED_AGENT_BODY`).

    Routing FIRST keeps the scripted tool-call turn-counting (which inspects the conversation's
    assistant ``tool_calls`` messages) from ever seeing a review prompt — a review request is a
    single-shot judgement (``tools == []``), never an agentic loop. No network, no credentials.
    The :attr:`review_calls` counter lets a test assert the judge path was exercised.
    """

    def __init__(
        self,
        reads: "Sequence[Sequence[tuple[str, dict]]] | None" = None,
        body: str = SCRIPTED_AGENT_BODY,
    ) -> None:
        super().__init__(reads=reads, body=body)
        #: Number of review/judge ``complete`` calls routed to the passing-verdict path.
        self.review_calls = 0

    async def complete(
        self,
        messages: "list[Message]",
        tools: "list[ToolSchema]",
        stream_callback: object | None = None,
    ) -> ModelResponseEvent:
        # Route a review/judge request to the passing verdict FIRST (it is a single-shot call,
        # never part of the agentic loop), so the scripted turn-counting only ever sees
        # writer-agentic conversations.
        if _is_review_prompt(messages):
            self.review_calls += 1
            self.complete_calls += 1
            return ModelResponseEvent(
                run_id="scripted-review-agent-run",
                step_id=0,
                content=RoutingFakeProvider._passing_verdict_json(),
                finish_reason="end_turn",
            )
        # A writer-agentic sub-run turn (the per-segment bounded agent): defer to the inherited
        # scripted read/grep-then-body script driving the real run loop's real tools.
        if _is_writer_agentic_prompt(messages):
            return await super().complete(messages, tools, stream_callback)
        # Otherwise this is the top-level skeleton run-loop turn. The pipeline stages do their
        # work as a side effect of the content-free step_end event, so the run loop's OWN turn
        # has nothing to do — end it immediately in one step (so the stages fire exactly once),
        # exactly like the bare FakeProvider.
        self.complete_calls += 1
        return ModelResponseEvent(
            run_id="scripted-review-agent-run",
            step_id=0,
            content="done",
            finish_reason="end_turn",
        )
