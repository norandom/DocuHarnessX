"""Unit tests for task 2.2 (model resolution with config-then-env precedence).

Task 2.2 owns exactly one module — ``docuharnessx.model_resolver`` — and pins
its observable contract (design "ModelResolver"; Req 3.2, 3.3, 3.4):

* Resolve a :class:`harnessx.core.model_config.ModelConfig` from the configured
  model identifier **first** (Req 3.2).
* When no model id is configured, fall back to the provider **environment
  variables** following HarnessX conventions (Req 3.3): ``ANTHROPIC_API_KEY`` /
  ``ANTHROPIC_DEFAULT_MAIN_MODEL`` → AnthropicProvider; ``OPENAI_API_KEY`` /
  ``OPENAI_DEFAULT_MAIN_MODEL`` → native OpenAIProvider (agentic tool-calling
  safe — LiteLLM's path sends null tool-call content that OpenAI rejects);
  ``LITELLM_API_KEY`` / ``LITELLM_DEFAULT_MAIN_MODEL`` → LiteLLMProvider.
* Raise :class:`docuharnessx.errors.ModelResolutionError` with an explicit
  message when neither config nor env yields a model (Req 3.4).

The resolver never binds the model to a HarnessConfig — it only returns a
``ModelConfig`` (model lives in ModelConfig, never in HarnessConfig). These tests
manipulate the environment in-process and assert the returned provider class and
model string rather than making any network call.
"""

from __future__ import annotations

import importlib

import pytest

from docuharnessx.errors import ModelResolutionError

# The exact provider-env-var convention HarnessX itself uses (harnessx/cli.py
# _build_model). The resolver must honour these verbatim so a DocuHarnessX run
# resolves the same model a bare HarnessX run would.
PROVIDER_ENV_VARS = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_DEFAULT_MAIN_MODEL",
    "ANTHROPIC_API_BASE",
    "ANTHROPIC_BASE_URL",
    "OPENAI_API_KEY",
    "OPENAI_DEFAULT_MAIN_MODEL",
    "OPENAI_API_BASE",
    "OPENAI_MAX_TOKENS",
    "LITELLM_API_KEY",
    "LITELLM_DEFAULT_MAIN_MODEL",
    "LITELLM_API_BASE",
)


@pytest.fixture(autouse=True)
def _clean_provider_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Start every test from a known-empty provider environment."""
    for var in PROVIDER_ENV_VARS:
        monkeypatch.delenv(var, raising=False)


def _resolver():
    return importlib.import_module("docuharnessx.model_resolver")


# --------------------------------------------------------------------------- #
# Module surface
# --------------------------------------------------------------------------- #


def test_module_imports_and_exposes_resolve_and_error() -> None:
    mod = _resolver()
    assert hasattr(mod, "resolve_model")
    # The explicit failure type is re-exported / referenced from errors.
    assert mod.ModelResolutionError is ModelResolutionError


def test_returns_a_real_modelconfig() -> None:
    from harnessx.core.model_config import ModelConfig

    mc = _resolver().resolve_model("claude-sonnet-4-6")
    assert isinstance(mc, ModelConfig)


# --------------------------------------------------------------------------- #
# Config-first precedence (Req 3.2)
# --------------------------------------------------------------------------- #


def test_config_model_id_anthropic_builds_anthropic_provider() -> None:
    from harnessx.providers.anthropic_provider import AnthropicProvider

    mc = _resolver().resolve_model("claude-sonnet-4-6")
    assert isinstance(mc.main, AnthropicProvider)
    assert mc.main.model == "claude-sonnet-4-6"


def test_config_model_id_with_anthropic_prefix_routes_to_anthropic() -> None:
    from harnessx.providers.anthropic_provider import AnthropicProvider

    mc = _resolver().resolve_model("anthropic/claude-opus-4-6")
    assert isinstance(mc.main, AnthropicProvider)
    # AnthropicProvider strips the litellm routing prefix.
    assert mc.main.model == "claude-opus-4-6"


def test_config_non_anthropic_model_id_builds_litellm_provider() -> None:
    from harnessx.providers.litellm_provider import LiteLLMProvider

    mc = _resolver().resolve_model("openai/gpt-4o")
    assert isinstance(mc.main, LiteLLMProvider)
    assert mc.main.model == "openai/gpt-4o"


def test_config_wins_over_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """A configured model id takes precedence over any env-var model."""
    from harnessx.providers.anthropic_provider import AnthropicProvider

    monkeypatch.setenv("OPENAI_API_KEY", "sk-env")
    monkeypatch.setenv("OPENAI_DEFAULT_MAIN_MODEL", "gpt-4o")

    mc = _resolver().resolve_model("claude-sonnet-4-6")
    assert isinstance(mc.main, AnthropicProvider)
    assert mc.main.model == "claude-sonnet-4-6"


# --------------------------------------------------------------------------- #
# OpenAI-key models route to the NATIVE OpenAIProvider, not LiteLLM.
#
# Regression (production): the agentic writer fell back to deterministic
# boilerplate on every segment because LiteLLM's provider sends an assistant
# tool-call turn with content=null and has no tool-call/result pairing repair, so
# OpenAI rejects the next turn ("Invalid value for 'content': expected a string,
# got null") and the multi-turn tool loop dies. The native OpenAIProvider coerces
# empty content to "" and runs _fix_tool_call_pairing, so it survives the loop.
# These tests pin the routing decision (no network call is made).
# --------------------------------------------------------------------------- #


def test_openai_env_builds_native_openai_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    from harnessx.providers.litellm_provider import LiteLLMProvider
    from harnessx.providers.openai_provider import OpenAIProvider

    monkeypatch.setenv("OPENAI_API_KEY", "sk-env")
    monkeypatch.setenv("OPENAI_DEFAULT_MAIN_MODEL", "gpt-5.5")

    mc = _resolver().resolve_model(None)
    assert isinstance(mc.main, OpenAIProvider)
    assert not isinstance(mc.main, LiteLLMProvider)
    # Bare id straight to the OpenAI SDK (no litellm "openai/" routing prefix).
    assert mc.main.model == "gpt-5.5"
    assert mc.main.api_key == "sk-env"
    # A concrete integer max_tokens (never null) — newer models reject null.
    assert isinstance(mc.main.max_tokens, int) and mc.main.max_tokens > 0


def test_openai_max_tokens_is_env_overridable(monkeypatch: pytest.MonkeyPatch) -> None:
    from harnessx.providers.openai_provider import OpenAIProvider

    monkeypatch.setenv("OPENAI_API_KEY", "sk-env")
    monkeypatch.setenv("OPENAI_MAX_TOKENS", "32000")

    mc = _resolver().resolve_model(None)
    assert isinstance(mc.main, OpenAIProvider)
    assert mc.main.max_tokens == 32000


def test_openai_compatible_endpoint_routes_native_with_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """A non-OpenAI-shaped id (e.g. MiMo) on an OpenAI-compatible endpoint uses the
    native provider with the custom base URL — so its tool-call loop is handled
    correctly instead of falling back to LiteLLM."""
    from harnessx.providers.openai_provider import OpenAIProvider

    base = "https://token-plan-ams.xiaomimimo.com/v1"
    monkeypatch.setenv("OPENAI_API_KEY", "sk-mimo")
    monkeypatch.setenv("OPENAI_API_BASE", base)

    # Via --model / config.
    mc = _resolver().resolve_model("mimo-v2.5-pro")
    assert isinstance(mc.main, OpenAIProvider)
    assert mc.main.model == "mimo-v2.5-pro"
    assert mc.main.base_url == base

    # And via the env default-model path.
    monkeypatch.setenv("OPENAI_DEFAULT_MAIN_MODEL", "mimo-v2.5-pro")
    mc_env = _resolver().resolve_model(None)
    assert isinstance(mc_env.main, OpenAIProvider)
    assert mc_env.main.model == "mimo-v2.5-pro"
    assert mc_env.main.base_url == base


def test_openai_env_default_model_is_native(monkeypatch: pytest.MonkeyPatch) -> None:
    from harnessx.providers.openai_provider import OpenAIProvider

    monkeypatch.setenv("OPENAI_API_KEY", "sk-env")  # no explicit model -> default

    mc = _resolver().resolve_model(None)
    assert isinstance(mc.main, OpenAIProvider)
    assert mc.main.model == "gpt-4o"


def test_openai_env_provider_qualified_model_is_stripped_for_native(monkeypatch: pytest.MonkeyPatch) -> None:
    from harnessx.providers.openai_provider import OpenAIProvider

    monkeypatch.setenv("OPENAI_API_KEY", "sk-env")
    monkeypatch.setenv("OPENAI_DEFAULT_MAIN_MODEL", "openai/gpt-5.5")

    mc = _resolver().resolve_model(None)
    assert isinstance(mc.main, OpenAIProvider)
    # The native provider wants the bare id; the litellm "openai/" prefix is stripped.
    assert mc.main.model == "gpt-5.5"


def test_config_openai_model_with_key_builds_native_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    """A configured OpenAI id + an OpenAI key uses the native provider too."""
    from harnessx.providers.openai_provider import OpenAIProvider

    monkeypatch.setenv("OPENAI_API_KEY", "sk-cfg")
    mc = _resolver().resolve_model("gpt-5.5")
    assert isinstance(mc.main, OpenAIProvider)
    assert mc.main.model == "gpt-5.5"
    assert mc.main.api_key == "sk-cfg"


def test_as_openai_route_helper() -> None:
    route = _resolver()._as_openai_route
    assert route("gpt-5.5") == "openai/gpt-5.5"
    assert route("gpt-4o") == "openai/gpt-4o"
    assert route("openai/gpt-5.5") == "openai/gpt-5.5"  # already qualified
    assert route("azure/my-deploy") == "azure/my-deploy"  # other provider kept


def test_config_picks_up_matching_env_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """A configured Anthropic id still reads its API key from the environment."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-config")
    mc = _resolver().resolve_model("claude-sonnet-4-6")
    assert mc.main._api_key == "sk-ant-config"


# --------------------------------------------------------------------------- #
# Env fallback when config is empty (Req 3.3)
# --------------------------------------------------------------------------- #


def test_env_anthropic_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    from harnessx.providers.anthropic_provider import AnthropicProvider

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant")
    monkeypatch.setenv("ANTHROPIC_DEFAULT_MAIN_MODEL", "claude-opus-4-6")

    mc = _resolver().resolve_model(None)
    assert isinstance(mc.main, AnthropicProvider)
    assert mc.main.model == "claude-opus-4-6"
    assert mc.main._api_key == "sk-ant"


def test_env_anthropic_key_only_uses_default_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """An Anthropic key with no model still resolves (HarnessX default model)."""
    from harnessx.providers.anthropic_provider import AnthropicProvider

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant")
    mc = _resolver().resolve_model("")  # empty config string == no model
    assert isinstance(mc.main, AnthropicProvider)
    assert mc.main.model  # some non-empty default


def test_env_openai_fallback_builds_native_openai(monkeypatch: pytest.MonkeyPatch) -> None:
    from harnessx.providers.openai_provider import OpenAIProvider

    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
    monkeypatch.setenv("OPENAI_DEFAULT_MAIN_MODEL", "gpt-4o")

    mc = _resolver().resolve_model(None)
    # OpenAI-key models use the native provider (not LiteLLM) so the agentic
    # writer's multi-turn tool loop survives OpenAI's strict content/pairing rules.
    assert isinstance(mc.main, OpenAIProvider)
    assert mc.main.model == "gpt-4o"


def test_env_litellm_fallback_builds_litellm(monkeypatch: pytest.MonkeyPatch) -> None:
    from harnessx.providers.litellm_provider import LiteLLMProvider

    monkeypatch.setenv("LITELLM_API_KEY", "sk-litellm")
    monkeypatch.setenv("LITELLM_DEFAULT_MAIN_MODEL", "openai/gpt-4o-mini")

    mc = _resolver().resolve_model(None)
    assert isinstance(mc.main, LiteLLMProvider)
    assert mc.main.model == "openai/gpt-4o-mini"


def test_env_precedence_anthropic_over_openai(monkeypatch: pytest.MonkeyPatch) -> None:
    """When multiple provider env vars are set, Anthropic wins (HarnessX order)."""
    from harnessx.providers.anthropic_provider import AnthropicProvider

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")

    mc = _resolver().resolve_model(None)
    assert isinstance(mc.main, AnthropicProvider)


# --------------------------------------------------------------------------- #
# Fail-fast when nothing resolves (Req 3.4)
# --------------------------------------------------------------------------- #


def test_raises_when_no_config_and_no_env() -> None:
    with pytest.raises(ModelResolutionError) as exc:
        _resolver().resolve_model(None)
    # Explicit, cause-naming message.
    assert "model" in str(exc.value).lower()


def test_raises_when_empty_config_and_no_env() -> None:
    with pytest.raises(ModelResolutionError):
        _resolver().resolve_model("   ")  # whitespace-only == no model


def test_error_message_mentions_env_vars() -> None:
    """The failure message should guide the operator to the env-var convention."""
    with pytest.raises(ModelResolutionError) as exc:
        _resolver().resolve_model(None)
    msg = str(exc.value)
    assert "ANTHROPIC_API_KEY" in msg or "OPENAI_API_KEY" in msg
