"""Hook and CI policy (no model, no network)."""

from __future__ import annotations

from docuharnessx.ci_policy import (
    has_model_credentials,
    is_bot_commit,
    should_evolve_in_ci,
    should_run_hook,
)


def test_has_model_credentials() -> None:
    assert has_model_credentials({}) is False
    assert has_model_credentials({"OPENAI_API_KEY": "sk-test"}) is True
    assert has_model_credentials({"ANTHROPIC_API_KEY": "sk-ant"}) is True


def test_hook_skips_without_key() -> None:
    decision = should_run_hook(["app.py"], environ={})
    assert decision.run is False
    assert "no API key" in decision.reason


def test_hook_skips_docs_only_and_bot_commits() -> None:
    env = {"OPENAI_API_KEY": "sk"}
    assert should_run_hook(["docs/index.md"], environ=env).run is False
    assert should_run_hook([".docuharnessx/pages/a.md"], environ=env).run is False
    assert should_run_hook(
        ["app.py"], environ=env, commit_message="[dhx] update living docs"
    ).run is False
    assert is_bot_commit("", "github-actions[bot]") is True


def test_hook_runs_on_source_with_key() -> None:
    decision = should_run_hook(["src/main.go", "README.md"], environ={"OPENAI_API_KEY": "sk"})
    assert decision.run is True


def test_evolve_skips_agent_code_commits_without_journal_change() -> None:
    decision = should_evolve_in_ci(
        evolve_mode="pr",
        journals_changed=False,
        actor="coder-agent[bot]",
        commit_message="feat: add handler",
    )
    assert decision.run is False
    assert "journals" in decision.reason


def test_evolve_opens_pr_when_journals_changed() -> None:
    decision = should_evolve_in_ci(
        evolve_mode="pr",
        journals_changed=True,
        actor="human",
        commit_message="refine session notes",
    )
    assert decision.run is True


def test_evolve_blocked_when_pr_open_or_mode_off() -> None:
    assert (
        should_evolve_in_ci(
            evolve_mode="off", journals_changed=True
        ).run
        is False
    )
    assert (
        should_evolve_in_ci(
            evolve_mode="pr",
            journals_changed=True,
            evolve_pr_open=True,
        ).run
        is False
    )
    assert (
        should_evolve_in_ci(
            evolve_mode="pr",
            journals_changed=True,
            commit_message="[dhx] evolve harness snapshot",
        ).run
        is False
    )
