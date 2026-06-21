"""Unit tests for task 2.2 (model resolution with config-then-env precedence).

Task 2.2 owns exactly one module — ``docuharnessx.model_resolver`` — and pins
its observable contract (design "ModelResolver"; Req 3.2, 3.3, 3.4):

* Resolve a :class:`harnessx.core.model_config.ModelConfig` from the configured
  model identifier **first** (Req 3.2).
* When no model id is configured, fall back to the provider **environment
  variables** following HarnessX conventions (Req 3.3): ``ANTHROPIC_API_KEY`` /
  ``ANTHROPIC_DEFAULT_MAIN_MODEL`` → AnthropicProvider; ``OPENAI_API_KEY`` /
  ``OPENAI_DEFAULT_MAIN_MODEL`` → LiteLLMProvider; ``LITELLM_API_KEY`` /
  ``LITELLM_DEFAULT_MAIN_MODEL`` → LiteLLMProvider.
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


def test_env_openai_fallback_builds_litellm(monkeypatch: pytest.MonkeyPatch) -> None:
    from harnessx.providers.litellm_provider import LiteLLMProvider

    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
    monkeypatch.setenv("OPENAI_DEFAULT_MAIN_MODEL", "gpt-4o")

    mc = _resolver().resolve_model(None)
    assert isinstance(mc.main, LiteLLMProvider)
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
