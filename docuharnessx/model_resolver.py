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
   :class:`AnthropicProvider`; everything else uses :class:`LiteLLMProvider`
   (the Anthropic SDK round-trips extended-thinking signatures that LiteLLM
   cannot — this mirrors HarnessX's own routing). The matching provider API key
   / base URL are still read from the environment so a configured model id does
   not also force the key into the config file.

2. **Provider environment variables next** (Req 3.3), following HarnessX
   conventions verbatim (see ``harnessx/cli.py`` ``_build_model``):

   ===========================  ==========================  =================
   API-key var                  model var                   provider
   ===========================  ==========================  =================
   ``ANTHROPIC_API_KEY``        ``ANTHROPIC_DEFAULT_MAIN_MODEL``  AnthropicProvider
   ``OPENAI_API_KEY``           ``OPENAI_DEFAULT_MAIN_MODEL``     LiteLLMProvider
   ``LITELLM_API_KEY``          ``LITELLM_DEFAULT_MAIN_MODEL``    LiteLLMProvider
   ===========================  ==========================  =================

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

# Default models used when a provider env key is present but its model var is not
# (taken verbatim from HarnessX ``cli.py`` ``_build_model`` so behavior matches).
_ANTHROPIC_DEFAULT_MODEL = "claude-sonnet-4-6"
_OPENAI_DEFAULT_MODEL = "gpt-4o"
_LITELLM_DEFAULT_MODEL = "claude-sonnet-4-6"


def _is_anthropic_model(model: str) -> bool:
    """True when *model* names an Anthropic model (claude-* / anthropic/*)."""
    lowered = model.lower()
    return any(lowered.startswith(prefix) for prefix in _ANTHROPIC_MODEL_PREFIXES)


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
    # Non-Anthropic model id → LiteLLM. Prefer an OpenAI key/base, then a generic
    # LiteLLM key/base, so a configured "openai/..." model picks up OPENAI_API_KEY.
    api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("LITELLM_API_KEY")
    api_base = os.environ.get("OPENAI_API_BASE") or os.environ.get("LITELLM_API_BASE")
    return _build_litellm(model_id, api_key, api_base)


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
        return _build_litellm(
            _as_openai_route(openai_model or _OPENAI_DEFAULT_MODEL),
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
