"""Unit tests for the optional gated LLM relevance hook (task 3.3, boundary: relevance).

These tests pin ``docuharnessx.planning.relevance.apply_relevance`` — the *only* path
in the deterministic planning core that may consult a model, built so a model can never
invent, drop, or alter the required writer fields of any planned segment (design
"relevance — optional gated LLM re-rank"; Req 8.2, 8.3, 8.4, 8.5).

Contract (design service interface)::

    def apply_relevance(plan, *, model=None, enabled=False, timeout_s=30.0) -> CoveragePlan

Three behaviors, exactly as the design pins them:

* **Disabled / model-less** — ``enabled is False`` *or* ``model is None`` returns the
  input plan unchanged (same object, ``relevance_applied is False``). The default; never
  an error; no model call (Req 8.3).
* **Enabled + model + success** — may reorder the existing segments and set per-segment
  ``relevance_note`` only; every segment's ``roles`` / ``intent`` / ``subjects`` (and the
  *set* of segments) is preserved, ``relevance_applied is True`` (Req 8.2).
* **Failure / timeout / out-of-bounds response** — logged and absorbed: the unchanged
  deterministic plan is returned so the run continues (Req 8.4).
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from docuharnessx.ontology import Subject, Vocabulary, default_profile
from docuharnessx.planning.model import (
    CandidateCell,
    Classification,
    CoveragePlan,
    EvidenceRef,
)
from docuharnessx.planning.planner import plan_coverage
from docuharnessx.planning.relevance import DEFAULT_RELEVANCE_TIMEOUT_S, apply_relevance


# --------------------------------------------------------------------------- #
# Fixtures: a multi-segment deterministic plan + fake models                   #
# --------------------------------------------------------------------------- #


def _vocab() -> Vocabulary:
    return default_profile()


def _subject(raw: str, vocab: Vocabulary) -> Subject:
    return Subject.parse(raw, frozenset(vocab.subject_prefixes))


def _cell(
    *,
    roles: tuple[str, ...],
    intent: str,
    subjects: tuple[Subject, ...] = (),
    evidence: tuple[EvidenceRef, ...] = (),
) -> CandidateCell:
    return CandidateCell(
        roles=roles, intent=intent, subjects=subjects, evidence=evidence
    )


def _plan(vocab: Vocabulary) -> CoveragePlan:
    """A deterministic three-segment plan over the default profile."""
    cells = (
        _cell(
            roles=("tech-savvy-user",),
            intent="install",
            subjects=(_subject("tech:go", vocab),),
            evidence=(EvidenceRef(kind="entrypoint", detail="main.go"),),
        ),
        _cell(
            roles=("manager",),
            intent="evaluate",
            subjects=(_subject("component:scanner", vocab),),
            evidence=(EvidenceRef(kind="doc", detail="README.md"),),
        ),
        _cell(
            roles=("developer",),
            intent="extend",
            subjects=(_subject("artifact:ci", vocab),),
            evidence=(EvidenceRef(kind="ci", detail=".github/workflows/ci.yml"),),
        ),
    )
    classification = Classification(
        repo_path="/repo",
        vocabulary_fingerprint="fp-xyz",
        subjects=(),
        cells=cells,
    )
    return plan_coverage(classification, vocab)


class _RecordingModel:
    """A fake model whose ``complete`` returns a canned content string.

    Records that it was called so tests can assert the disabled/model-less paths never
    consult it. Mirrors the duck-typed ``BaseModelProvider`` shape the hook expects:
    an awaitable ``complete(messages, tools, stream_callback=None)`` returning an object
    with a ``.content`` string.
    """

    def __init__(self, content: str) -> None:
        self._content = content
        self.calls = 0

    async def complete(
        self, messages: Any, tools: Any, stream_callback: Any = None
    ) -> Any:
        self.calls += 1

        class _Resp:
            content = self._content

        return _Resp()

    def count_tokens(self, messages: Any) -> int:
        return 1


class _BoomModel:
    """A fake model whose ``complete`` raises — to exercise the absorb-failure path."""

    def __init__(self) -> None:
        self.calls = 0

    async def complete(
        self, messages: Any, tools: Any, stream_callback: Any = None
    ) -> Any:
        self.calls += 1
        raise RuntimeError("model exploded")


def _reorder_payload(plan: CoveragePlan, order: list[int], notes: dict[int, str]
                     ) -> str:
    """A JSON re-rank instruction referencing existing segment_keys by index in *plan*."""
    keys = [s.segment_key for s in plan.segments]
    return json.dumps(
        {
            "order": [keys[i] for i in order],
            "notes": {keys[i]: note for i, note in notes.items()},
        }
    )


# --------------------------------------------------------------------------- #
# Disabled / model-less gate (Req 8.3, 8.5)                                    #
# --------------------------------------------------------------------------- #


def test_disabled_returns_input_unchanged() -> None:
    vocab = _vocab()
    plan = _plan(vocab)
    model = _RecordingModel(_reorder_payload(plan, [0, 1, 2], {}))

    result = apply_relevance(plan, model=model, enabled=False)

    assert result is plan  # same object, no copy
    assert result.relevance_applied is False
    assert model.calls == 0  # the gate never consults the model


def test_model_none_returns_input_unchanged() -> None:
    vocab = _vocab()
    plan = _plan(vocab)

    result = apply_relevance(plan, model=None, enabled=True)

    assert result is plan
    assert result.relevance_applied is False


def test_default_is_disabled() -> None:
    vocab = _vocab()
    plan = _plan(vocab)
    model = _RecordingModel(_reorder_payload(plan, [0, 1, 2], {}))

    # No enabled flag passed -> defaults to off (Req 8.5: no hidden activation).
    result = apply_relevance(plan, model=model)

    assert result is plan
    assert result.relevance_applied is False
    assert model.calls == 0


# --------------------------------------------------------------------------- #
# Enabled success: reorder + annotate, required fields preserved (Req 8.2)     #
# --------------------------------------------------------------------------- #


def test_enabled_success_sets_relevance_applied() -> None:
    vocab = _vocab()
    plan = _plan(vocab)
    model = _RecordingModel(_reorder_payload(plan, [2, 0, 1], {}))

    result = apply_relevance(plan, model=model, enabled=True)

    assert result.relevance_applied is True
    assert model.calls == 1


def test_enabled_success_reorders_segments() -> None:
    vocab = _vocab()
    plan = _plan(vocab)
    # Ask for a non-default order (reverse).
    model = _RecordingModel(_reorder_payload(plan, [2, 1, 0], {}))

    result = apply_relevance(plan, model=model, enabled=True)

    original_keys = [s.segment_key for s in plan.segments]
    new_keys = [s.segment_key for s in result.segments]
    assert new_keys == list(reversed(original_keys))


def test_enabled_success_sets_relevance_note() -> None:
    vocab = _vocab()
    plan = _plan(vocab)
    notes = {0: "most critical for new users", 1: "secondary"}
    model = _RecordingModel(_reorder_payload(plan, [0, 1, 2], notes))

    result = apply_relevance(plan, model=model, enabled=True)

    by_key = {s.segment_key: s for s in result.segments}
    k0 = plan.segments[0].segment_key
    k1 = plan.segments[1].segment_key
    k2 = plan.segments[2].segment_key
    assert by_key[k0].relevance_note == "most critical for new users"
    assert by_key[k1].relevance_note == "secondary"
    assert by_key[k2].relevance_note == ""  # not annotated -> stays empty


def test_enabled_preserves_required_writer_fields() -> None:
    vocab = _vocab()
    plan = _plan(vocab)
    model = _RecordingModel(_reorder_payload(plan, [1, 2, 0], {0: "note"}))

    result = apply_relevance(plan, model=model, enabled=True)

    # The set of segments (keyed by segment_key) is identical; roles/intent/subjects/
    # priority/evidence are byte-for-byte preserved per key — only order + note change.
    orig = {s.segment_key: s for s in plan.segments}
    new = {s.segment_key: s for s in result.segments}
    assert set(orig) == set(new)
    for key, seg in new.items():
        o = orig[key]
        assert seg.roles == o.roles
        assert seg.intent == o.intent
        assert seg.subjects == o.subjects
        assert seg.priority == o.priority
        assert seg.evidence == o.evidence


def test_enabled_never_adds_or_drops_segments() -> None:
    vocab = _vocab()
    plan = _plan(vocab)
    model = _RecordingModel(_reorder_payload(plan, [0, 1, 2], {}))

    result = apply_relevance(plan, model=model, enabled=True)

    assert len(result.segments) == len(plan.segments)


# --------------------------------------------------------------------------- #
# Out-of-bounds responses are absorbed -> deterministic plan unchanged (8.2/8.4)#
# --------------------------------------------------------------------------- #


def test_response_dropping_a_key_is_rejected() -> None:
    vocab = _vocab()
    plan = _plan(vocab)
    # Order omits one existing key -> would drop a segment -> reject, keep core.
    model = _RecordingModel(_reorder_payload(plan, [0, 1], {}))

    result = apply_relevance(plan, model=model, enabled=True)

    assert result == plan
    assert result.relevance_applied is False


def test_response_inventing_a_key_is_rejected() -> None:
    vocab = _vocab()
    plan = _plan(vocab)
    keys = [s.segment_key for s in plan.segments]
    payload = json.dumps({"order": keys + ["ghost__segment__deadbeef"], "notes": {}})
    model = _RecordingModel(payload)

    result = apply_relevance(plan, model=model, enabled=True)

    assert result == plan
    assert result.relevance_applied is False


def test_unparseable_response_is_absorbed() -> None:
    vocab = _vocab()
    plan = _plan(vocab)
    model = _RecordingModel("this is not json at all {{{")

    result = apply_relevance(plan, model=model, enabled=True)

    assert result == plan
    assert result.relevance_applied is False


def test_note_for_unknown_key_is_ignored_not_fatal() -> None:
    vocab = _vocab()
    plan = _plan(vocab)
    keys = [s.segment_key for s in plan.segments]
    payload = json.dumps(
        {"order": keys, "notes": {"unknown-key": "ignored", keys[0]: "kept"}}
    )
    model = _RecordingModel(payload)

    result = apply_relevance(plan, model=model, enabled=True)

    # A note for an unknown key is ignored; the valid note for a real key applies and the
    # re-rank still succeeds (out-of-bounds *notes* are not as fatal as a bad *order*).
    assert result.relevance_applied is True
    by_key = {s.segment_key: s for s in result.segments}
    assert by_key[keys[0]].relevance_note == "kept"


# --------------------------------------------------------------------------- #
# Failure / timeout absorbed (Req 8.4)                                         #
# --------------------------------------------------------------------------- #


def test_model_exception_returns_deterministic_plan_unchanged() -> None:
    vocab = _vocab()
    plan = _plan(vocab)
    model = _BoomModel()

    result = apply_relevance(plan, model=model, enabled=True)

    assert result == plan
    assert result.relevance_applied is False
    assert model.calls == 1  # it was attempted, then absorbed


def test_timeout_returns_deterministic_plan_unchanged() -> None:
    import asyncio

    vocab = _vocab()
    plan = _plan(vocab)

    class _SlowModel:
        async def complete(self, messages: Any, tools: Any, stream_callback: Any = None):
            await asyncio.sleep(5.0)

            class _Resp:
                content = "{}"

            return _Resp()

    result = apply_relevance(plan, model=_SlowModel(), enabled=True, timeout_s=0.05)

    assert result == plan
    assert result.relevance_applied is False


def test_empty_plan_with_relevance_enabled_is_safe() -> None:
    vocab = _vocab()
    empty = plan_coverage(
        Classification(
            repo_path="/repo", vocabulary_fingerprint="fp", subjects=(), cells=()
        ),
        vocab,
    )
    model = _RecordingModel(json.dumps({"order": [], "notes": {}}))

    result = apply_relevance(empty, model=model, enabled=True)

    # An empty plan reorders to itself; required-field preservation is trivially held.
    assert result.segments == ()


# --------------------------------------------------------------------------- #
# Misc contract                                                                #
# --------------------------------------------------------------------------- #


def test_default_timeout_constant_exposed() -> None:
    assert isinstance(DEFAULT_RELEVANCE_TIMEOUT_S, float)
    assert DEFAULT_RELEVANCE_TIMEOUT_S > 0


def test_result_is_a_coverage_plan() -> None:
    vocab = _vocab()
    plan = _plan(vocab)
    model = _RecordingModel(_reorder_payload(plan, [0, 1, 2], {}))
    result = apply_relevance(plan, model=model, enabled=True)
    assert isinstance(result, CoveragePlan)
