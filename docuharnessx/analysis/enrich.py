"""The optional, gated LLM enrichment hook (task 4.2).

``docuharnessx.analysis.enrich`` is the **only** surface in the otherwise pure,
model-free analysis core that may consult a model — and it is built so a model can
never gate, block, or alter the deterministic core
:class:`~docuharnessx.analysis.model.RepoAnalysis` (design "enrich — optional gated
LLM enrichment"; Req 9.3, 9.4, 9.5). The analyzer (task 4.1) always produces a
complete core with ``enrichment=None``; this hook wraps that core and *optionally*
attaches a narrative architecture summary into the separated
:class:`~docuharnessx.analysis.model.Enrichment` region. It never reads from or
writes to the deterministic core fields.

Contract (design service interface)::

    def enrich(analysis, *, model=None, enabled=False, timeout_s=30.0) -> RepoAnalysis

Three behaviors, exactly as the design pins them:

* **Disabled / model-less** — when ``enabled is False`` *or* ``model is None`` the
  input ``analysis`` is returned **unchanged** (same object, ``enrichment is None``).
  This is the default and is treated as *success*, never an error (Req 9.4). The
  model is never consulted in this path.
* **Enabled + model + success** — the model is asked for a short architecture
  summary; on success the result is ``dataclasses.replace(analysis,
  enrichment=Enrichment(...))``. Because ``replace`` copies the frozen aggregate and
  overrides only the ``enrichment`` field, **every deterministic core field is
  byte-for-byte identical** to the input — enrichment only *adds* the separated
  region (Req 9.3).
* **Failure / timeout** — any exception from the model, or a model that does not
  answer within ``timeout_s``, is **absorbed**: the failure is logged at WARNING and
  the *complete, unchanged* core analysis is returned (``enrichment is None``). The
  run continues; enrichment is best-effort and never fatal (Req 9.5).

Determinism is preserved by construction: enrichment is *off by default*, the gate
is an explicit caller flag (no env-driven hidden behavior), and a failed/disabled
enrichment leaves the analysis exactly as the deterministic analyzer produced it,
so a model-free run is fully reproducible (Req 9.1, 9.4).

Model coupling is intentionally minimal and duck-typed. The hook expects only a
HarnessX ``BaseModelProvider``-shaped object: an awaitable
``complete(messages, tools, stream_callback=None)`` returning an object with a
``.content`` string (a ``ModelResponseEvent`` in production; any stand-in in
tests). The analysis package never imports a model class or constructs a provider —
the bound model, if any, is handed in by the Analyze stage from the runtime.
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import os
from typing import Any

from docuharnessx.analysis.model import Enrichment, RepoAnalysis

__all__ = [
    "enrich",
    "DEFAULT_ENRICH_TIMEOUT_S",
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


#: Default wall-clock budget for a single enrichment model call. A model that does not answer
#: within this many seconds is treated as a (logged, absorbed) timeout so enrichment can never
#: stall the run (Req 9.5). Sized generously for slow models; raisable/lowerable via
#: ``DHX_ENRICH_TIMEOUT_S``.
DEFAULT_ENRICH_TIMEOUT_S: float = _timeout_from_env("DHX_ENRICH_TIMEOUT_S", 120.0)

#: A compact, model-agnostic instruction prompt. The deterministic core is rendered
#: into a small textual brief (no file bodies) so the model summarizes only what the
#: analyzer already established — the summary is narrative, never authoritative over
#: the core fields (Req 9.3).
_SYSTEM_PROMPT = (
    "You are summarizing a software repository for documentation planning. "
    "Given a deterministic structural analysis, write a brief (2-4 sentence) "
    "narrative description of the project's architecture and purpose. "
    "Do not invent facts beyond the analysis. Respond with prose only."
)


def enrich(
    analysis: RepoAnalysis,
    *,
    model: Any | None = None,
    enabled: bool = False,
    timeout_s: float = DEFAULT_ENRICH_TIMEOUT_S,
) -> RepoAnalysis:
    """Optionally attach a narrative architecture summary to *analysis*.

    Args:
        analysis: The complete, deterministic core :class:`RepoAnalysis` from the
            analyzer (``enrichment`` expected to be ``None``).
        model: A bound HarnessX ``BaseModelProvider``-shaped object, or ``None``.
            Only its awaitable ``complete(messages, tools, stream_callback=None)``
            (returning an object with a ``.content`` string) is used. The analysis
            package never constructs a provider itself.
        enabled: The explicit gate. Enrichment is attempted only when this is
            ``True`` *and* a ``model`` is given; otherwise the core is returned
            unchanged (Req 9.4).
        timeout_s: Wall-clock budget for the single model call. Exceeding it is an
            absorbed (logged) timeout, not a failure of the run (Req 9.5).

    Returns:
        The unchanged input ``analysis`` (``enrichment is None``) when disabled,
        model-less, or on any failure/timeout; otherwise a copy with the
        :class:`Enrichment` region set, leaving every deterministic core field
        identical (Req 9.3, 9.4, 9.5).
    """
    # Gate: off by default, and model-less is not an error. Return the *same* object
    # so a disabled run is provably the bare core analysis (Req 9.4).
    if not enabled or model is None:
        return analysis

    try:
        summary = _run_enrichment(analysis, model, timeout_s)
    except Exception:  # pragma: no cover - defensive: _run_enrichment self-absorbs
        # Belt-and-braces: _run_enrichment already absorbs and logs, but if anything
        # leaks (e.g. constructing the prompt), never let it gate the core (Req 9.5).
        _log.warning(
            "Repository enrichment failed unexpectedly; "
            "returning the deterministic core analysis unchanged.",
            exc_info=True,
        )
        return analysis

    # An empty/whitespace summary carries no information — treat it as "nothing to
    # attach" so we never emit an empty enrichment region (the absent region and an
    # empty one would otherwise be indistinguishable to the planner).
    if not summary or not summary.strip():
        return analysis

    model_id = _model_id(model)
    return dataclasses.replace(
        analysis,
        enrichment=Enrichment(
            architecture_summary=summary.strip(),
            model_id=model_id,
        ),
    )


def _run_enrichment(analysis: RepoAnalysis, model: Any, timeout_s: float) -> str:
    """Call the model for a summary, absorbing any failure/timeout into ``""``.

    Bridges the synchronous, deterministic analyzer world to the model's awaitable
    ``complete``. Any exception (model error, bad shape, timeout) is logged at
    WARNING and converted to an empty string so the caller returns the unchanged
    core analysis (Req 9.5). Never raises.
    """
    try:
        response = _complete_with_timeout(model, analysis, timeout_s)
    except TimeoutError:
        _log.warning(
            "Repository enrichment timed out after %.3gs; "
            "omitting enrichment and returning the deterministic core analysis.",
            timeout_s,
        )
        return ""
    except Exception:
        _log.warning(
            "Repository enrichment model call failed; "
            "omitting enrichment and returning the deterministic core analysis.",
            exc_info=True,
        )
        return ""

    content = getattr(response, "content", "")
    return content if isinstance(content, str) else ""


def _complete_with_timeout(model: Any, analysis: RepoAnalysis, timeout_s: float) -> Any:
    """Run the model's awaitable ``complete`` to completion under ``timeout_s``.

    The enrichment hook is called from synchronous, deterministic code (the analyzer
    composition / the Analyze stage), so we drive the model's coroutine on a private
    event loop via :func:`asyncio.run`, wrapping it in :func:`asyncio.wait_for` to
    bound it. A timeout surfaces as :class:`TimeoutError`; the cancelled coroutine is
    not awaited further. Building the request never touches the core fields.
    """
    messages, tools = _build_request(analysis)

    async def _drive() -> Any:
        return await asyncio.wait_for(
            model.complete(messages, tools, stream_callback=None),
            timeout=timeout_s,
        )

    return asyncio.run(_drive())


def _build_request(analysis: RepoAnalysis) -> tuple[list[Any], list[Any]]:
    """Build the ``(messages, tools)`` request for the bound model.

    Messages follow the HarnessX :class:`~harnessx.core.events.Message` shape — a
    system instruction plus a user message carrying a compact textual brief of the
    deterministic analysis (read-only; never the file bodies). No tools are offered:
    enrichment is a single-shot summary, not an agentic loop. HarnessX is imported
    lazily and behind a fallback so the pure analysis core never hard-depends on the
    harness at import time.
    """
    brief = _render_brief(analysis)
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


def _render_brief(analysis: RepoAnalysis) -> str:
    """Render a small, deterministic textual brief of the core analysis.

    Read-only over the core fields — it summarizes counts and top-level signals the
    analyzer already established (languages, entrypoints, components, tests, docs) so
    the model has context without any file content. Pure: it returns a string and
    never mutates ``analysis`` (Req 9.3).
    """
    primary = ", ".join(analysis.primary_languages) or "unknown"
    lang_bits = ", ".join(
        f"{stat.language} ({stat.loc} LOC, {stat.files} files)"
        for stat in analysis.languages
    ) or "none detected"
    entrypoints = ", ".join(ep.path for ep in analysis.entrypoints) or "none detected"
    components = ", ".join(comp.name for comp in analysis.components) or "none detected"
    return (
        f"Repository path: {analysis.repo_path}\n"
        f"Primary language(s): {primary}\n"
        f"Total: {analysis.total_loc} LOC across {analysis.total_files} files\n"
        f"Languages: {lang_bits}\n"
        f"Entrypoints: {entrypoints}\n"
        f"Components: {components}\n"
        f"Tests present: {analysis.tests.present}\n"
        f"README present: {analysis.docs.has_readme}\n"
    )


def _model_id(model: Any) -> str:
    """Best-effort id of the producing model for the :class:`Enrichment` record.

    Reads a ``.model`` attribute (HarnessX providers expose one); falls back to the
    class name, then to ``""``. Never raises — a missing id must not gate the summary
    we already obtained.
    """
    candidate = getattr(model, "model", None)
    if isinstance(candidate, str) and candidate:
        return candidate
    try:
        return type(model).__name__
    except Exception:  # pragma: no cover - defensive
        return ""
