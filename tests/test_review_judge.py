"""Unit tests for the gated judge step (quality-review-gate task 3.1, boundary: Gated Judge Step).

These tests pin ``docuharnessx.review.judge.judge_segment`` — the **only** module in the
otherwise pure, model-free review core that may consult a model (design "Gated Judge
Step"; Req 5.1, 5.2, 5.3, 5.4, 5.6).

Contract (design service interface)::

    def judge_segment(criteria, *, model, timeout_s=DEFAULT_JUDGE_TIMEOUT_S) -> JudgeVerdict | None

Behaviors pinned here, exactly as the design fixes them:

* **Clean model response** — a stub provider that returns parseable per-criterion JSON
  (the strict ``{"criteria": {<name>: {...}}, "passed": ..., "reason": ...}`` shape the
  prompt instructs) yields a parsed :class:`~docuharnessx.review.model.JudgeVerdict`
  delegated to :func:`docuharnessx.review.parse.parse_verdict` (Req 5.1).
* **Model-less / raised / timed-out / empty / unparseable** — returns ``None`` (logged,
  never raised) so the caller (the ``ReviewStage`` / the verdict computer) applies the
  fail-closed default-reject (Req 5.4). All failures are absorbed.
* **Single, bounded call** — exactly one ``complete`` call per invocation; no loop
  (Req 5.3). The step is duck-typed over a ``BaseModelProvider``-shaped object (never
  imported/constructed here, Req 5.2) and sets no segment field (Req 5.6).
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from docuharnessx.review.criteria import COBESY_CRITERIA, CRITERION_THRESHOLD
from docuharnessx.review.judge import DEFAULT_JUDGE_TIMEOUT_S, judge_segment
from docuharnessx.review.model import (
    EvidenceAnchor,
    JudgeVerdict,
    RoleContext,
    SegmentCriteria,
)


# --------------------------------------------------------------------------- #
# Fixtures: a deterministic criteria context + duck-typed fake models          #
# --------------------------------------------------------------------------- #


def _criteria() -> SegmentCriteria:
    """A small, fully-populated deterministic criteria context (no model, no vocab lookup)."""
    return SegmentCriteria(
        segment_id="developer__extend__component-scanner",
        title="Extend the scanner",
        summary="How to add a detector.",
        body="# Extend the scanner\n\nRegister a detector in the scanner registry.",
        criteria=COBESY_CRITERIA,
        roles=(RoleContext(id="developer", label="Developer", description="Writes code."),),
        intent=RoleContext(id="extend", label="Extend", description="Add capability."),
        evidence_anchors=(
            EvidenceAnchor(kind="entrypoint", detail="scanner/registry.py", note=""),
        ),
    )


def _clean_verdict_json(passed: bool = True, score: float | None = None) -> str:
    """A strict, parseable per-criterion judge reply for every COBESY criterion."""
    if score is None:
        score = 0.95 if passed else 0.1
    return json.dumps(
        {
            "criteria": {
                name: {
                    "score": score,
                    "passed": passed,
                    "reason": f"{name} reason",
                }
                for name in COBESY_CRITERIA
            },
            "passed": passed,
            "reason": "overall reason",
        }
    )


class _RecordingModel:
    """A fake model whose ``complete`` returns a canned content string.

    Records its call count so tests can assert the single-call contract (Req 5.3) and
    the model-less path never consults it. Mirrors the duck-typed ``BaseModelProvider``
    shape the step expects: an awaitable ``complete(messages, tools, stream_callback=None)``
    returning an object with a ``.content`` string.
    """

    def __init__(self, content: Any) -> None:
        self._content = content
        self.calls = 0
        self.last_tools: Any = "unset"
        self.last_messages: Any = "unset"
        self.last_stream_callback: Any = "unset"

    async def complete(
        self, messages: Any, tools: Any, stream_callback: Any = None
    ) -> Any:
        self.calls += 1
        self.last_tools = tools
        self.last_messages = messages
        self.last_stream_callback = stream_callback

        content = self._content

        class _Resp:
            pass

        resp = _Resp()
        resp.content = content
        return resp

    def count_tokens(self, messages: Any) -> int:
        return 1


class _BoomModel:
    """A fake model whose ``complete`` raises — exercises the absorb-failure path."""

    def __init__(self) -> None:
        self.calls = 0

    async def complete(
        self, messages: Any, tools: Any, stream_callback: Any = None
    ) -> Any:
        self.calls += 1
        raise RuntimeError("judge model exploded")


# --------------------------------------------------------------------------- #
# Clean response -> parsed JudgeVerdict (Req 5.1)                              #
# --------------------------------------------------------------------------- #


def test_clean_json_response_yields_parsed_verdict() -> None:
    crit = _criteria()
    model = _RecordingModel(_clean_verdict_json(passed=True))

    verdict = judge_segment(crit, model=model)

    assert isinstance(verdict, JudgeVerdict)
    # Every configured COBESY criterion is scored, in the configured order.
    assert tuple(s.name for s in verdict.scores) == COBESY_CRITERIA
    assert all(s.passed for s in verdict.scores)
    assert verdict.overall_passed is True
    assert model.calls == 1  # exactly one bounded call (Req 5.3)


def test_clean_failing_response_is_parsed_verbatim() -> None:
    crit = _criteria()
    model = _RecordingModel(_clean_verdict_json(passed=False))

    verdict = judge_segment(crit, model=model)

    assert isinstance(verdict, JudgeVerdict)
    assert all(not s.passed for s in verdict.scores)
    assert verdict.overall_passed is False


def test_fenced_code_response_is_stripped_and_parsed() -> None:
    # The judge wraps its JSON in a markdown fence; the delegated parser strips it.
    crit = _criteria()
    fenced = "```json\n" + _clean_verdict_json(passed=True) + "\n```"
    model = _RecordingModel(fenced)

    verdict = judge_segment(crit, model=model)

    assert isinstance(verdict, JudgeVerdict)
    assert tuple(s.name for s in verdict.scores) == COBESY_CRITERIA


def test_missing_passed_flag_defaults_via_threshold() -> None:
    # A reply that omits per-criterion `passed` must default to the threshold rule
    # (delegated to parse): a high score passes, a low score fails.
    crit = _criteria()
    high = max(0.0, min(1.0, CRITERION_THRESHOLD + 0.05))
    payload = json.dumps(
        {
            "criteria": {
                name: {"score": high, "reason": "r"} for name in COBESY_CRITERIA
            }
        }
    )
    verdict = judge_segment(crit, model=_RecordingModel(payload))

    assert isinstance(verdict, JudgeVerdict)
    assert all(s.passed for s in verdict.scores)


def test_offers_no_tools_single_shot() -> None:
    crit = _criteria()
    model = _RecordingModel(_clean_verdict_json())

    judge_segment(crit, model=model)

    # Single-shot judgement: the request offers no tools (Req 5.3, mirrors build_request).
    assert model.last_tools == []


def test_passes_stream_callback_none() -> None:
    # The duck-typed bridge calls complete(messages, tools, stream_callback=None) —
    # a single-shot, non-streaming judgement.
    crit = _criteria()
    model = _RecordingModel(_clean_verdict_json())

    judge_segment(crit, model=model)

    assert model.last_stream_callback is None


# --------------------------------------------------------------------------- #
# Model-less / failure / timeout / empty / garbage -> None (Req 5.4)           #
# --------------------------------------------------------------------------- #


def test_model_none_returns_none_without_raising() -> None:
    # The credential-free path: no model bound -> None (the caller default-rejects).
    assert judge_segment(_criteria(), model=None) is None


def test_model_exception_is_absorbed_to_none() -> None:
    crit = _criteria()
    model = _BoomModel()

    verdict = judge_segment(crit, model=model)

    assert verdict is None
    assert model.calls == 1  # attempted once, then absorbed (Req 5.3, 5.4)


def test_empty_content_returns_none() -> None:
    crit = _criteria()
    model = _RecordingModel("   \n  ")

    assert judge_segment(crit, model=model) is None


def test_non_string_content_returns_none() -> None:
    crit = _criteria()
    model = _RecordingModel(12345)  # not a str

    assert judge_segment(crit, model=model) is None


def test_garbage_non_json_content_returns_none() -> None:
    crit = _criteria()
    model = _RecordingModel("this is not json at all")

    assert judge_segment(crit, model=model) is None


def test_wrong_shape_json_returns_none() -> None:
    # A JSON object with no `criteria` block scores no known criterion -> None.
    crit = _criteria()
    model = _RecordingModel(json.dumps({"verdict": "looks good"}))

    assert judge_segment(crit, model=model) is None


def test_no_known_criteria_returns_none() -> None:
    # A reply that scores only unknown criteria -> None (treated as unjudged).
    crit = _criteria()
    payload = json.dumps(
        {"criteria": {"made_up_axis": {"score": 1.0, "passed": True, "reason": "x"}}}
    )
    model = _RecordingModel(payload)

    assert judge_segment(crit, model=model) is None


def test_timeout_returns_none() -> None:
    crit = _criteria()

    class _SlowModel:
        def __init__(self) -> None:
            self.calls = 0

        async def complete(
            self, messages: Any, tools: Any, stream_callback: Any = None
        ) -> Any:
            self.calls += 1
            await asyncio.sleep(5.0)

            class _Resp:
                content = _clean_verdict_json()

            return _Resp()

    model = _SlowModel()
    verdict = judge_segment(crit, model=model, timeout_s=0.05)

    assert verdict is None


def test_response_without_content_attr_returns_none() -> None:
    # A provider whose response object has no `.content` -> getattr default "" -> None.
    crit = _criteria()

    class _NoContentModel:
        def __init__(self) -> None:
            self.calls = 0

        async def complete(
            self, messages: Any, tools: Any, stream_callback: Any = None
        ) -> Any:
            self.calls += 1

            class _Resp:
                pass

            return _Resp()

    assert judge_segment(crit, model=_NoContentModel()) is None


# --------------------------------------------------------------------------- #
# Single-call / no-mutation / contract                                         #
# --------------------------------------------------------------------------- #


def test_exactly_one_complete_call_per_invocation() -> None:
    crit = _criteria()
    model = _RecordingModel(_clean_verdict_json())

    judge_segment(crit, model=model)

    assert model.calls == 1


def test_does_not_mutate_criteria() -> None:
    # The step sets no segment field and never mutates its read-only input (Req 5.6).
    crit = _criteria()
    before = (
        crit.segment_id,
        crit.title,
        crit.summary,
        crit.body,
        crit.criteria,
        crit.roles,
        crit.intent,
        crit.evidence_anchors,
    )
    model = _RecordingModel(_clean_verdict_json())

    judge_segment(crit, model=model)

    after = (
        crit.segment_id,
        crit.title,
        crit.summary,
        crit.body,
        crit.criteria,
        crit.roles,
        crit.intent,
        crit.evidence_anchors,
    )
    assert before == after


def test_fakeprovider_without_valid_json_returns_none() -> None:
    # The shared tests/_fakes.FakeProvider returns "done" (not valid verdict JSON):
    # the fail-closed firewall treats it as unjudged -> None (the caller default-rejects).
    from tests._fakes import FakeProvider

    assert judge_segment(_criteria(), model=FakeProvider()) is None


def test_fakeprovider_returning_valid_verdict_json_parses() -> None:
    # A fake whose complete().content is valid verdict JSON exercises the parse path
    # credential-free (assert the gating shape, not exact judge prose).
    from tests._fakes import FakeProvider

    model = FakeProvider(content=_clean_verdict_json(passed=True))
    verdict = judge_segment(_criteria(), model=model)

    assert isinstance(verdict, JudgeVerdict)
    assert tuple(s.name for s in verdict.scores) == COBESY_CRITERIA


def test_default_timeout_constant_exposed() -> None:
    assert isinstance(DEFAULT_JUDGE_TIMEOUT_S, float)
    assert DEFAULT_JUDGE_TIMEOUT_S > 0


def test_equal_clean_response_is_deterministic() -> None:
    crit = _criteria()
    content = _clean_verdict_json(passed=True)

    v1 = judge_segment(crit, model=_RecordingModel(content))
    v2 = judge_segment(crit, model=_RecordingModel(content))

    assert v1 == v2


def test_judge_step_reexported_from_package_namespace() -> None:
    # The gated judge step + its budget are exposed on the single public namespace,
    # identity-equal to the submodule definitions (no shadow copies), mirroring the
    # earlier review-core entry points.
    import docuharnessx.review as review

    assert "judge_segment" in review.__all__
    assert "DEFAULT_JUDGE_TIMEOUT_S" in review.__all__
    assert review.judge_segment is judge_segment
    assert review.DEFAULT_JUDGE_TIMEOUT_S is DEFAULT_JUDGE_TIMEOUT_S
