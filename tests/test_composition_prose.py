"""Unit tests for the gated prose step (cobesy-writer task 2.5, boundary: Gated Prose Step).

These tests pin ``docuharnessx.composition.prose.generate_prose`` — the **only** module
in the otherwise pure, model-free composition core that may consult a model (design
"Gated Prose Step"; Req 5.1, 5.2, 5.3, 5.4, 5.5).

Contract (design service interface)::

    def generate_prose(blueprint, *, model, timeout_s=DEFAULT_PROSE_TIMEOUT_S) -> ProseResult | None

Behaviors pinned here, exactly as the design fixes them:

* **Clean model response** — a model that returns a parseable ``.content`` carrying a
  body (and, when present, a summary) yields a ``ProseResult(source="model")`` whose
  ``body``/``summary`` are derived deterministically from the content (Req 5.1, 5.4).
* **Model-less / raised / timed-out / empty / unparseable** — returns ``None`` (logged,
  never raised) so the caller renders the deterministic fallback (Req 5.4). All failures
  are absorbed.
* **Single, bounded call** — at most one ``complete`` call per invocation; no loop
  (Req 5.3). The prose step sets only ``body``/``summary`` (never a non-body Segment
  field — that is the wiring's job, Req 5.5), and the call is duck-typed over a
  ``BaseModelProvider``-shaped object (never imported/constructed here, Req 5.2).
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from docuharnessx.composition.model import (
    Chunk,
    CompositionBlueprint,
    EvidenceAnchor,
    ProseResult,
    SCQAOpener,
)
from docuharnessx.composition.prose import (
    DEFAULT_PROSE_TIMEOUT_S,
    generate_prose,
)


# --------------------------------------------------------------------------- #
# Fixtures: a deterministic blueprint + duck-typed fake models                 #
# --------------------------------------------------------------------------- #


def _blueprint() -> CompositionBlueprint:
    """A small, fully-populated deterministic blueprint (no model, no vocab lookup)."""
    return CompositionBlueprint(
        segment_key="developer__extend__component-scanner",
        roles=("developer",),
        intent="extend",
        subjects=(),
        title="Extend the scanner",
        scqa=SCQAOpener(
            situation="You maintain the scanner.",
            complication="A new file type is unsupported.",
            question="How do you add support?",
            answer="Register a detector in the scanner registry.",
        ),
        key_message="Register a detector in the scanner registry.",
        chunks=(
            Chunk(heading="Where detectors live", points=("scanner/registry.py",)),
            Chunk(heading="Register your detector", points=("Add an entry", "Run tests")),
        ),
        fast_path=("Open registry.py", "Add the detector", "Run the suite"),
        andragogy=True,
        evidence_anchors=(
            EvidenceAnchor(kind="entrypoint", detail="scanner/registry.py", note=""),
        ),
        role_labels=("Developer",),
        intent_label="Extend",
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

    async def complete(
        self, messages: Any, tools: Any, stream_callback: Any = None
    ) -> Any:
        self.calls += 1
        self.last_tools = tools

        class _Resp:
            content = self._content

        return _Resp()

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
        raise RuntimeError("model exploded")


# --------------------------------------------------------------------------- #
# Clean response -> ProseResult(source="model") (Req 5.1, 5.4)                 #
# --------------------------------------------------------------------------- #


def test_clean_json_response_yields_model_result() -> None:
    bp = _blueprint()
    content = json.dumps(
        {"body": "# Extend the scanner\n\nRegister a detector.", "summary": "How to add a detector."}
    )
    model = _RecordingModel(content)

    result = generate_prose(bp, model=model)

    assert isinstance(result, ProseResult)
    assert result.source == "model"
    assert "Register a detector." in result.body
    assert result.summary == "How to add a detector."
    assert model.calls == 1  # exactly one bounded call (Req 5.3)


def test_clean_plain_text_response_yields_model_result() -> None:
    bp = _blueprint()
    # A model that ignores the JSON instruction and returns plain Markdown prose still
    # parses deterministically: the body is the content; a summary is derived.
    model = _RecordingModel("# Extend the scanner\n\nRegister a detector in the registry.")

    result = generate_prose(bp, model=model)

    assert isinstance(result, ProseResult)
    assert result.source == "model"
    assert result.body.strip() != ""
    assert result.summary.strip() != ""


def test_offers_no_tools_single_shot() -> None:
    bp = _blueprint()
    model = _RecordingModel(json.dumps({"body": "Body text.", "summary": "Sum."}))

    generate_prose(bp, model=model)

    # Single-shot generation: the request offers no tools (Req 5.3, mirrors build_request).
    assert model.last_tools == []


# --------------------------------------------------------------------------- #
# Model-less / failure / timeout / empty -> None (Req 5.4)                      #
# --------------------------------------------------------------------------- #


def test_model_none_returns_none_without_raising() -> None:
    bp = _blueprint()
    assert generate_prose(bp, model=None) is None


def test_model_exception_is_absorbed_to_none() -> None:
    bp = _blueprint()
    model = _BoomModel()

    result = generate_prose(bp, model=model)

    assert result is None
    assert model.calls == 1  # attempted once, then absorbed (Req 5.3, 5.4)


def test_empty_content_returns_none() -> None:
    bp = _blueprint()
    model = _RecordingModel("   \n  ")

    assert generate_prose(bp, model=model) is None


def test_non_string_content_returns_none() -> None:
    bp = _blueprint()
    model = _RecordingModel(12345)  # not a str

    assert generate_prose(bp, model=model) is None


def test_json_with_empty_body_returns_none() -> None:
    bp = _blueprint()
    model = _RecordingModel(json.dumps({"body": "   ", "summary": "non-empty"}))

    # An empty body is treated as an unusable response -> fall back (Req 6.3 driver).
    assert generate_prose(bp, model=model) is None


def test_timeout_returns_none() -> None:
    bp = _blueprint()

    class _SlowModel:
        async def complete(
            self, messages: Any, tools: Any, stream_callback: Any = None
        ) -> Any:
            await asyncio.sleep(5.0)

            class _Resp:
                content = json.dumps({"body": "late", "summary": "late"})

            return _Resp()

    result = generate_prose(bp, model=_SlowModel(), timeout_s=0.05)

    assert result is None


# --------------------------------------------------------------------------- #
# Misc contract                                                                #
# --------------------------------------------------------------------------- #


def test_default_timeout_constant_exposed() -> None:
    assert isinstance(DEFAULT_PROSE_TIMEOUT_S, float)
    assert DEFAULT_PROSE_TIMEOUT_S > 0


def test_only_sets_body_and_summary_on_model_result() -> None:
    # The prose step's product carries only body/summary/source — never a Segment field
    # (Req 5.5). ProseResult has exactly those three fields, so a successful result is
    # structurally incapable of carrying non-body Segment data.
    bp = _blueprint()
    model = _RecordingModel(json.dumps({"body": "B", "summary": "S"}))

    result = generate_prose(bp, model=model)

    assert result is not None
    assert set(vars(result)) == {"body", "summary", "source"}


def test_equal_clean_response_is_deterministic() -> None:
    bp = _blueprint()
    content = json.dumps({"body": "Deterministic body.", "summary": "Det summary."})

    r1 = generate_prose(bp, model=_RecordingModel(content))
    r2 = generate_prose(bp, model=_RecordingModel(content))

    assert r1 == r2
