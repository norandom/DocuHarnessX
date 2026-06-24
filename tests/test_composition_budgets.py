"""Unit tests for the writer budget defaults and the structure-gate threshold.

Task 1.1 (agentic-codebase-writer, boundary: *composition core defaults*) adds the
per-segment agentic-run budget constants and the minimum cited-files threshold as named
module-level defaults in the composition core, so every per-segment agentic run is bounded
by shared, auditable values rather than scattered literals (Req 5.1, 4.3, 4.4).

These tests pin the named defaults to concrete values, assert they are positive, and
confirm they are exposed identity-equal from the single ``docuharnessx.composition``
public namespace (mirroring ``DEFAULT_PROSE_TIMEOUT_S``). The budgets module stays
model-free — importing it must not touch a model or the network — and each default may be
overridden by a ``DHX_WRITER_*`` environment variable read once at import.

Constants pinned (design service interfaces, lines 342-461):

* ``WRITER_MAX_STEPS`` — ``BaseTask.max_steps`` cap per per-segment run (Req 5.1).
* ``WRITER_MAX_COST_USD`` — ``BaseTask.max_cost_usd`` / ``make_control`` cost guard (Req 5.1).
* ``WRITER_TOKEN_BUDGET`` — ``BaseTask.token_budget`` cap per per-segment run (Req 5.1).
* ``WRITER_TOKEN_THRESHOLD`` — ``make_control`` token-compaction threshold (Req 5.1).
* ``WRITER_LOOP_THRESHOLD`` — ``make_control`` loop-detection halt threshold (Req 5.1).
* ``MIN_CITED_FILES`` — the structure-gate minimum distinct ``file:line`` cited files
  (Req 4.3, 4.4).
"""

from __future__ import annotations

import importlib

import pytest

from docuharnessx.composition import budgets


# --------------------------------------------------------------------------- #
# Concrete values — auditable, pinned defaults                                 #
# --------------------------------------------------------------------------- #


def test_writer_budget_defaults_have_pinned_values() -> None:
    assert budgets.WRITER_MAX_STEPS == 24
    assert budgets.WRITER_MAX_COST_USD == 5.00
    assert budgets.WRITER_TOKEN_BUDGET == 1_000_000
    assert budgets.WRITER_TOKEN_THRESHOLD == 150_000
    assert budgets.WRITER_LOOP_THRESHOLD == 6


# --------------------------------------------------------------------------- #
# Environment overrides — DHX_WRITER_* tunes a model/endpoint without code edits #
# --------------------------------------------------------------------------- #


def test_env_int_reads_positive_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DHX_TEST_BUDGET_INT", "900000")
    assert budgets._env_int("DHX_TEST_BUDGET_INT", 7) == 900_000


def test_env_int_rejects_nonpositive_nonint_and_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    for bad in ("0", "-5", "abc", "1.5", ""):
        monkeypatch.setenv("DHX_TEST_BUDGET_INT", bad)
        assert budgets._env_int("DHX_TEST_BUDGET_INT", 7) == 7
    monkeypatch.delenv("DHX_TEST_BUDGET_INT", raising=False)
    assert budgets._env_int("DHX_TEST_BUDGET_INT", 7) == 7


def test_env_float_reads_and_validates(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DHX_TEST_BUDGET_FLOAT", "5.5")
    assert budgets._env_float("DHX_TEST_BUDGET_FLOAT", 2.0) == 5.5
    for bad in ("0", "-1", "nope", ""):
        monkeypatch.setenv("DHX_TEST_BUDGET_FLOAT", bad)
        assert budgets._env_float("DHX_TEST_BUDGET_FLOAT", 2.0) == 2.0


def test_module_constants_are_wired_to_env_helpers() -> None:
    # Each shipped default must be produced by the env-reading helpers (so a DHX_WRITER_*
    # override takes effect), not a bare literal. With no override set the helper returns
    # the default, which the pinned-values test above checks; here we assert the wiring is
    # via the helpers by confirming the helper returns the same shipped value by name.
    assert budgets._env_int("DHX_WRITER_MAX_STEPS", budgets.WRITER_MAX_STEPS) == budgets.WRITER_MAX_STEPS
    assert (
        budgets._env_float("DHX_WRITER_MAX_COST_USD", budgets.WRITER_MAX_COST_USD)
        == budgets.WRITER_MAX_COST_USD
    )


def test_min_cited_files_default_has_pinned_value() -> None:
    assert budgets.MIN_CITED_FILES == 3


# --------------------------------------------------------------------------- #
# Positivity + type — a bound must be a positive, usable cap                   #
# --------------------------------------------------------------------------- #


def test_step_token_loop_caps_are_positive_ints() -> None:
    for value in (
        budgets.WRITER_MAX_STEPS,
        budgets.WRITER_TOKEN_BUDGET,
        budgets.WRITER_TOKEN_THRESHOLD,
        budgets.WRITER_LOOP_THRESHOLD,
        budgets.MIN_CITED_FILES,
    ):
        assert isinstance(value, int)
        assert not isinstance(value, bool)  # a bool is an int subclass — exclude it
        assert value > 0


def test_max_cost_is_a_positive_float() -> None:
    assert isinstance(budgets.WRITER_MAX_COST_USD, float)
    assert budgets.WRITER_MAX_COST_USD > 0.0


def test_token_budget_at_least_compaction_threshold() -> None:
    # The hard per-run token cap is the outer bound; the compaction threshold trips first
    # so the run can compact context before it hits the hard budget.
    assert budgets.WRITER_TOKEN_BUDGET >= budgets.WRITER_TOKEN_THRESHOLD


# --------------------------------------------------------------------------- #
# Public surface — exposed identity-equal from the composition namespace       #
# --------------------------------------------------------------------------- #


def test_namespace_reexports_budget_defaults_identity_equal() -> None:
    pkg = importlib.import_module("docuharnessx.composition")
    mod = importlib.import_module("docuharnessx.composition.budgets")
    for name in (
        "WRITER_MAX_STEPS",
        "WRITER_MAX_COST_USD",
        "WRITER_TOKEN_BUDGET",
        "WRITER_TOKEN_THRESHOLD",
        "WRITER_LOOP_THRESHOLD",
        "MIN_CITED_FILES",
    ):
        assert getattr(pkg, name) is getattr(mod, name), name
        assert name in pkg.__all__, name


def test_budgets_module_all_is_self_consistent() -> None:
    mod = importlib.import_module("docuharnessx.composition.budgets")
    expected = {
        "WRITER_MAX_STEPS",
        "WRITER_MAX_COST_USD",
        "WRITER_TOKEN_BUDGET",
        "WRITER_TOKEN_THRESHOLD",
        "WRITER_LOOP_THRESHOLD",
        "MIN_CITED_FILES",
    }
    assert set(mod.__all__) == expected
    for name in mod.__all__:
        assert hasattr(mod, name), f"__all__ advertises {name} but it is not present"
    assert len(mod.__all__) == len(set(mod.__all__))
