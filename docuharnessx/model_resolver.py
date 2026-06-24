"""Model resolution with config-then-env precedence (task 2.2 boundary).

The DocuHarnessX skeleton keeps the model *out* of the ``HarnessConfig``: the
behavior pipeline (``make_docgen``) is model-free, and the model is bound
separately via ``ModelConfig(main=...).agentic(make_docgen(...))`` (Req 3.1).
This module owns the single seam that produces that ``ModelConfig`` — and only
that. It performs no binding, no harness composition, and no network call.

Resolution precedence (design "ModelResolver"; Req 3.2–3.4):

1. **Configured model identifier first** (Req 3.2). When the operator names a
   model in the config file (or via ``--model``), build a provider for exactly
   that model id. Anthropic models (``claude-*`` / ``anthropic/*``) use
   :class:`AnthropicProvider`; OpenAI models (``gpt-*`` / ``o*`` / ``openai/*``)
   with an ``OPENAI_API_KEY`` present use the native :class:`OpenAIProvider`;
   everything else uses :class:`LiteLLMProvider`. (The Anthropic SDK round-trips
   extended-thinking signatures LiteLLM cannot; the native OpenAI provider runs
   OpenAI's strict tool-call/result pairing fix and coerces empty assistant
   content to ``""`` — both things LiteLLM's generic path does *not* do, see the
   note on agentic tool-calling below.) The matching provider API key / base URL
   are still read from the environment so a configured model id does not also
   force the key into the config file.

2. **Provider environment variables next** (Req 3.3), following HarnessX
   conventions:

   ===========================  ==========================  =================
   API-key var                  model var                   provider
   ===========================  ==========================  =================
   ``ANTHROPIC_API_KEY``        ``ANTHROPIC_DEFAULT_MAIN_MODEL``  AnthropicProvider
   ``OPENAI_API_KEY``           ``OPENAI_DEFAULT_MAIN_MODEL``     OpenAIProvider (native)
   ``LITELLM_API_KEY``          ``LITELLM_DEFAULT_MAIN_MODEL``    LiteLLMProvider
   ===========================  ==========================  =================

   **Why OpenAI uses the native provider, not LiteLLM** (regression: the agentic
   writer fell back to boilerplate on every segment in production). LiteLLM's
   provider serialises an assistant tool-call turn with ``content: null`` and has
   no tool-call/result pairing repair; OpenAI's API then rejects the *next* turn
   with ``BadRequestError: Invalid value for 'content': expected a string, got
   null``, killing the multi-turn tool loop. The 1.0 single-shot writer never hit
   this (one call, no tool round-trip), but the agentic writer reads files across
   turns, so it must use HarnessX's native :class:`OpenAIProvider`, which coerces
   empty content to ``""`` and runs ``_fix_tool_call_pairing``. LiteLLM is kept
   for genuinely-LiteLLM providers (``LITELLM_API_KEY``, e.g. Gemini, proxies).

   The Anthropic → OpenAI → LiteLLM order matches HarnessX so a DocuHarnessX run
   resolves the same model a bare ``harnessx`` run would. Either the key or the
   model var is enough to select a provider; a provider-specific default model
   fills in when only the key is present.

3. **Fail fast** (Req 3.4). When neither a configured model id nor any provider
   environment variable yields a model, raise :class:`ModelResolutionError` with
   an explicit message naming the env-var convention — never silently fall back
   to a hard-coded model that may not match the operator's endpoint.

Deviation from design note: the design's flow sketches resolution as a thin
``resolve_model`` returning a provider; HarnessX's real surface is a
``ModelConfig`` whose ``main`` key holds the provider, so this resolver returns a
``ModelConfig`` directly (which is exactly what ``.agentic(...)`` consumes). All
HarnessX imports are kept local to the functions, consistent with the design's
drift-mitigation note about centralising HarnessX coupling.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from .errors import ModelResolutionError

if TYPE_CHECKING:  # pragma: no cover - typing only
    from harnessx.core.model_config import ModelConfig

__all__ = ["resolve_model", "ModelResolutionError"]

# Anthropic model identifiers route to the direct Anthropic SDK provider; this
# mirrors HarnessX's own ``_is_anthropic_model`` check (claude-* / anthropic/*).
_ANTHROPIC_MODEL_PREFIXES = ("claude-", "anthropic/")

# OpenAI model identifiers route to the native OpenAIProvider (when an OpenAI key
# is present) rather than the generic LiteLLM path: only the native provider runs
# OpenAI's tool-call/result pairing fix and coerces empty assistant content to ""
# (the LiteLLM path sends content=null on tool-call turns, which OpenAI rejects on
# the next turn — breaking the agentic writer's multi-turn tool loop).
_OPENAI_MODEL_PREFIXES = ("openai/", "gpt-", "o1", "o3", "o4", "chatgpt")

# Default models used when a provider env key is present but its model var is not
# (taken verbatim from HarnessX ``cli.py`` ``_build_model`` so behavior matches).
_ANTHROPIC_DEFAULT_MODEL = "claude-sonnet-4-6"
_OPENAI_DEFAULT_MODEL = "gpt-4o"
_LITELLM_DEFAULT_MODEL = "claude-sonnet-4-6"

# HarnessX's OpenAIProvider always sends ``max_tokens=self.max_tokens`` to the OpenAI
# SDK; left at ``None`` the SDK serialises it as JSON ``null``, which newer models
# (e.g. gpt-5.5) reject with ``400 Invalid type for 'max_tokens' ... got null``. We
# therefore give the provider a concrete integer completion cap. 16384 is the safe
# universal ceiling (it is gpt-4o's max output and well within gpt-5.x's range);
# override with ``OPENAI_MAX_TOKENS`` if a model truncates long, diagram-rich
# segments. It is a cap, not a target — the model stops at end-of-turn — and the
# per-segment cost guard remains the real bound.
_OPENAI_DEFAULT_MAX_TOKENS = 16384


def _openai_max_tokens() -> int:
    """Integer ``max_tokens`` for the OpenAI provider (``OPENAI_MAX_TOKENS`` override)."""
    raw = os.environ.get("OPENAI_MAX_TOKENS", "").strip()
    if raw.isdigit() and int(raw) > 0:
        return int(raw)
    return _OPENAI_DEFAULT_MAX_TOKENS


def _is_anthropic_model(model: str) -> bool:
    """True when *model* names an Anthropic model (claude-* / anthropic/*)."""
    lowered = model.lower()
    return any(lowered.startswith(prefix) for prefix in _ANTHROPIC_MODEL_PREFIXES)


def _is_openai_model(model: str) -> bool:
    """True when *model* names an OpenAI model (gpt-* / o1/o3/o4 / openai/* / chatgpt)."""
    lowered = model.lower()
    return any(lowered.startswith(prefix) for prefix in _OPENAI_MODEL_PREFIXES)


def _strip_openai_prefix(model: str) -> str:
    """Drop a leading ``openai/`` routing prefix for the native OpenAIProvider.

    The native provider passes the model id straight to the OpenAI SDK, which wants
    the bare id (``gpt-5.5``), not LiteLLM's provider-qualified ``openai/gpt-5.5``.
    """
    return model[len("openai/") :] if model.lower().startswith("openai/") else model


def _build_openai(model: str, api_key: str | None, base_url: str | None) -> "ModelConfig":
    from harnessx.core.model_config import ModelConfig
    from harnessx.providers.openai_provider import OpenAIProvider

    # Always pass a concrete integer max_tokens: the provider sends it unconditionally,
    # and a null is rejected by OpenAI and OpenAI-compatible endpoints (MiMo, etc.).
    kwargs: dict[str, object] = {"max_tokens": _openai_max_tokens()}
    if api_key:
        kwargs["api_key"] = api_key
    if base_url:
        kwargs["base_url"] = base_url
    return ModelConfig(main=OpenAIProvider(model, **kwargs))


def _build_anthropic(model: str, api_key: str | None) -> "ModelConfig":
    from harnessx.core.model_config import ModelConfig
    from harnessx.providers.anthropic_provider import AnthropicProvider

    kwargs: dict[str, object] = {}
    if api_key:
        kwargs["api_key"] = api_key
    base_url = os.environ.get("ANTHROPIC_API_BASE") or os.environ.get("ANTHROPIC_BASE_URL")
    if base_url:
        kwargs["base_url"] = base_url
    return ModelConfig(main=AnthropicProvider(model, **kwargs))


def _build_litellm(model: str, api_key: str | None, api_base: str | None) -> "ModelConfig":
    from harnessx.core.model_config import ModelConfig
    from harnessx.providers.litellm_provider import LiteLLMProvider

    kwargs: dict[str, object] = {}
    if api_key:
        kwargs["api_key"] = api_key
    if api_base:
        kwargs["api_base"] = api_base
    return ModelConfig(main=LiteLLMProvider(model, **kwargs))


def _as_openai_route(model: str) -> str:
    """Route an OpenAI-key model through LiteLLM's ``openai/`` provider prefix.

    When the model was resolved from ``OPENAI_API_KEY`` it is, by definition, an
    OpenAI model — but LiteLLM cannot infer the provider for ids it does not yet
    recognise (e.g. a newly released ``gpt-5.5``) and errors with "LLM Provider NOT
    provided". Prefix ``openai/`` so any OpenAI model routes correctly, unless the
    operator already gave a provider-qualified id (``openai/...``, ``azure/...``).
    """
    return model if "/" in model else f"openai/{model}"


def _resolve_from_config(model_id: str) -> "ModelConfig":
    """Build a ``ModelConfig`` for an explicitly configured model id (Req 3.2).

    The provider is chosen by the model id itself; the matching provider's API
    key / base URL are still read from the environment so the config file need
    only name the model, not carry secrets.
    """
    if _is_anthropic_model(model_id):
        return _build_anthropic(model_id, os.environ.get("ANTHROPIC_API_KEY"))
    # Native OpenAIProvider (agentic tool-calling safe; see the module docstring) when
    # an OpenAI key is present AND either the id is an OpenAI model OR an OpenAI-
    # compatible endpoint is configured via ``OPENAI_API_BASE`` (e.g. MiMo, vLLM, a
    # proxy) — the latter covers non-OpenAI-shaped ids like ``mimo-v2.5-pro``. The bare
    # id goes to the OpenAI SDK against that base URL.
    openai_key = os.environ.get("OPENAI_API_KEY")
    openai_base = os.environ.get("OPENAI_API_BASE")
    if openai_key and (_is_openai_model(model_id) or openai_base):
        return _build_openai(_strip_openai_prefix(model_id), openai_key, openai_base)
    # Otherwise LiteLLM (genuine LiteLLM providers, or an OpenAI id with only a
    # LiteLLM key). Prefix a bare OpenAI id so LiteLLM can infer the provider.
    api_key = openai_key or os.environ.get("LITELLM_API_KEY")
    api_base = openai_base or os.environ.get("LITELLM_API_BASE")
    routed = _as_openai_route(model_id) if _is_openai_model(model_id) else model_id
    return _build_litellm(routed, api_key, api_base)


def _resolve_from_env() -> "ModelConfig | None":
    """Build a ``ModelConfig`` from provider env vars (Req 3.3), or ``None``.

    Anthropic → OpenAI → LiteLLM, matching HarnessX ``_build_model`` order.
    Returns ``None`` when no provider environment variable is set so the caller
    can fail fast (Req 3.4).
    """
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    anthropic_model = os.environ.get("ANTHROPIC_DEFAULT_MAIN_MODEL")
    if anthropic_key or anthropic_model:
        return _build_anthropic(anthropic_model or _ANTHROPIC_DEFAULT_MODEL, anthropic_key)

    openai_key = os.environ.get("OPENAI_API_KEY")
    openai_model = os.environ.get("OPENAI_DEFAULT_MAIN_MODEL")
    if openai_key or openai_model:
        # Native OpenAIProvider (not LiteLLM): the agentic writer's multi-turn tool
        # loop needs OpenAI's tool-call pairing + null-content coercion. The bare
        # model id goes straight to the OpenAI SDK (strip any ``openai/`` prefix).
        return _build_openai(
            _strip_openai_prefix(openai_model or _OPENAI_DEFAULT_MODEL),
            openai_key,
            os.environ.get("OPENAI_API_BASE"),
        )

    litellm_key = os.environ.get("LITELLM_API_KEY")
    litellm_model = os.environ.get("LITELLM_DEFAULT_MAIN_MODEL")
    if litellm_key or litellm_model:
        return _build_litellm(
            litellm_model or _LITELLM_DEFAULT_MODEL,
            litellm_key,
            os.environ.get("LITELLM_API_BASE"),
        )

    return None


def resolve_model(model_id: str | None) -> "ModelConfig":
    """Resolve a HarnessX ``ModelConfig`` from config first, then environment.

    Args:
        model_id: The model identifier from the configuration surface
            (``DocgenConfig.model`` / ``--model``), or ``None``/blank when the
            operator did not configure one. A blank or whitespace-only string is
            treated as "no model configured" so an empty YAML value falls through
            to the environment.

    Returns:
        A ``ModelConfig`` whose ``main`` provider is ready to be bound via
        ``ModelConfig(main=...).agentic(make_docgen(...))``. The model is never
        placed into a ``HarnessConfig`` (Req 3.1).

    Raises:
        ModelResolutionError: When neither a configured model id nor any provider
            environment variable yields a model (Req 3.4). The message names the
            env-var convention so the operator can fix it.
    """
    if model_id is not None and model_id.strip():
        return _resolve_from_config(model_id.strip())

    resolved = _resolve_from_env()
    if resolved is not None:
        return resolved

    raise ModelResolutionError(
        "No model is configured. Specify a model in the config file "
        "(or via --model), or set one of the provider environment variables: "
        "ANTHROPIC_API_KEY (with optional ANTHROPIC_DEFAULT_MAIN_MODEL), "
        "OPENAI_API_KEY (with optional OPENAI_DEFAULT_MAIN_MODEL), or "
        "LITELLM_API_KEY (with optional LITELLM_DEFAULT_MAIN_MODEL)."
    )
