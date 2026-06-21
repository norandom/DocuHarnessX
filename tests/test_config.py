"""Unit tests for task 2.1 (the configuration surface and precedence).

Task 2.1 owns exactly one module — ``docuharnessx.config`` — and pins the
observable contract for ``DocgenConfig`` (design "DocgenConfig"; Req 7.1–7.4,
7.6):

* The surface accepts the target-repository path, the output directory, a role
  selection, a model selection, and cost and step budgets (Req 7.1).
* Valid roles are derived from the loaded ``Vocabulary`` (imported from
  ``ontology-engine`` via ``docuharnessx._ontology``); when no role selection is
  provided the surface defaults to *all* roles present in that ``Vocabulary``;
  there is NO hardcoded ten-role list (Req 7.2).
* A role selection (from ``--roles`` or the config file) naming a role not in the
  loaded ``Vocabulary`` raises :class:`ConfigError` whose message lists the valid
  roles (Req 7.3).
* A ``--config YAML`` file is loaded and command-line argument overrides win for
  any overlapping setting (Req 7.4).
* A malformed YAML file, or one carrying an unknown setting, raises
  :class:`ConfigError` identifying the problem (Req 7.6).

These tests construct an arbitrary ``Vocabulary`` (NOT the default profile) so the
"roles come from the loaded Vocabulary, not a hardcoded list" contract is exercised
directly; they also confirm the default profile flows through unchanged.
"""

from __future__ import annotations

import importlib

import pytest

from docuharnessx._ontology import Vocabulary, default_profile
from docuharnessx.errors import ConfigError
from docuharnessx.ontology import AxisTerm


def _config():
    return importlib.import_module("docuharnessx.config")


def _vocab(*role_ids: str) -> Vocabulary:
    """A bespoke Vocabulary so role validity is driven by the loaded vocab, not a
    hardcoded list."""
    return Vocabulary(
        roles=tuple(AxisTerm(rid, rid.title()) for rid in role_ids),
        intents=(AxisTerm("use", "Use"),),
        subject_prefixes=("component:",),
    )


def _write_yaml(tmp_path, text: str) -> str:
    path = tmp_path / "docgen.yaml"
    path.write_text(text, encoding="utf-8")
    return str(path)


# --------------------------------------------------------------------------- #
# Module surface
# --------------------------------------------------------------------------- #


def test_module_exposes_docgenconfig_and_loader() -> None:
    mod = _config()
    assert hasattr(mod, "DocgenConfig")
    assert hasattr(mod, "load_config")


def test_docgenconfig_holds_all_settings() -> None:
    """Req 7.1: target repo, output dir, roles, model, cost + step budgets."""
    vocab = _vocab("alpha", "beta")
    cfg = _config().load_config(
        config_path=None,
        cli_overrides={
            "target_repo": "/repo",
            "out_dir": "/out",
            "roles": ["alpha"],
            "model": "claude-sonnet-4-6",
            "max_cost_usd": 12.5,
            "max_steps": 40,
        },
        vocabulary=vocab,
    )
    assert cfg.target_repo == "/repo"
    assert cfg.out_dir == "/out"
    assert cfg.roles == ("alpha",)
    assert cfg.model == "claude-sonnet-4-6"
    assert cfg.max_cost_usd == 12.5
    assert cfg.max_steps == 40


# --------------------------------------------------------------------------- #
# Roles default to ALL loaded-vocabulary roles (Req 7.2) — no hardcoded list
# --------------------------------------------------------------------------- #


def test_roles_default_to_all_vocabulary_roles() -> None:
    vocab = _vocab("alpha", "beta", "gamma")
    cfg = _config().load_config(config_path=None, cli_overrides=None, vocabulary=vocab)
    assert cfg.roles == ("alpha", "beta", "gamma")


def test_roles_default_tracks_default_profile_roles() -> None:
    """The default itself is derived, not hardcoded: it equals the profile's roles."""
    vocab = default_profile()
    cfg = _config().load_config(config_path=None, cli_overrides=None, vocabulary=vocab)
    assert cfg.roles == tuple(r.id for r in vocab.roles)


def test_roles_default_when_yaml_omits_roles(tmp_path) -> None:
    vocab = _vocab("alpha", "beta")
    path = _write_yaml(tmp_path, "model: claude-sonnet-4-6\n")
    cfg = _config().load_config(config_path=path, cli_overrides=None, vocabulary=vocab)
    assert cfg.roles == ("alpha", "beta")


# --------------------------------------------------------------------------- #
# YAML load + CLI override precedence (Req 7.4)
# --------------------------------------------------------------------------- #


def test_yaml_values_are_loaded(tmp_path) -> None:
    vocab = _vocab("alpha", "beta")
    path = _write_yaml(
        tmp_path,
        "target_repo: /from/yaml\n"
        "out_dir: /out/yaml\n"
        "roles: [alpha]\n"
        "model: yaml-model\n"
        "max_cost_usd: 3.0\n"
        "max_steps: 7\n",
    )
    cfg = _config().load_config(config_path=path, cli_overrides=None, vocabulary=vocab)
    assert cfg.target_repo == "/from/yaml"
    assert cfg.out_dir == "/out/yaml"
    assert cfg.roles == ("alpha",)
    assert cfg.model == "yaml-model"
    assert cfg.max_cost_usd == 3.0
    assert cfg.max_steps == 7


def test_cli_override_wins_over_yaml(tmp_path) -> None:
    vocab = _vocab("alpha", "beta")
    path = _write_yaml(tmp_path, "model: yaml-model\nout_dir: /out/yaml\n")
    cfg = _config().load_config(
        config_path=path,
        cli_overrides={"model": "cli-model"},
        vocabulary=vocab,
    )
    # CLI wins for the overlapping setting; the non-overridden YAML value remains.
    assert cfg.model == "cli-model"
    assert cfg.out_dir == "/out/yaml"


def test_cli_override_roles_win_over_yaml(tmp_path) -> None:
    vocab = _vocab("alpha", "beta")
    path = _write_yaml(tmp_path, "roles: [alpha]\n")
    cfg = _config().load_config(
        config_path=path,
        cli_overrides={"roles": ["beta"]},
        vocabulary=vocab,
    )
    assert cfg.roles == ("beta",)


def test_cli_none_value_does_not_override_yaml(tmp_path) -> None:
    """A CLI override of None (flag not supplied) leaves the YAML value intact."""
    vocab = _vocab("alpha", "beta")
    path = _write_yaml(tmp_path, "model: yaml-model\n")
    cfg = _config().load_config(
        config_path=path,
        cli_overrides={"model": None, "roles": None},
        vocabulary=vocab,
    )
    assert cfg.model == "yaml-model"


# --------------------------------------------------------------------------- #
# Unknown role -> ConfigError listing valid roles (Req 7.3)
# --------------------------------------------------------------------------- #


def test_unknown_role_via_cli_raises_configerror_listing_valid_roles() -> None:
    vocab = _vocab("alpha", "beta")
    with pytest.raises(ConfigError) as exc:
        _config().load_config(
            config_path=None,
            cli_overrides={"roles": ["nope"]},
            vocabulary=vocab,
        )
    msg = str(exc.value)
    assert "nope" in msg
    # Lists the valid roles drawn from the loaded vocabulary.
    assert "alpha" in msg and "beta" in msg


def test_unknown_role_via_yaml_raises_configerror(tmp_path) -> None:
    vocab = _vocab("alpha", "beta")
    path = _write_yaml(tmp_path, "roles: [ghost]\n")
    with pytest.raises(ConfigError) as exc:
        _config().load_config(config_path=path, cli_overrides=None, vocabulary=vocab)
    assert "ghost" in str(exc.value)


def test_a_valid_subset_of_roles_is_accepted() -> None:
    vocab = _vocab("alpha", "beta", "gamma")
    cfg = _config().load_config(
        config_path=None,
        cli_overrides={"roles": ["gamma", "alpha"]},
        vocabulary=vocab,
    )
    assert cfg.roles == ("gamma", "alpha")


# --------------------------------------------------------------------------- #
# Malformed / unknown-key YAML -> ConfigError (Req 7.6)
# --------------------------------------------------------------------------- #


def test_unknown_key_in_yaml_raises_configerror(tmp_path) -> None:
    vocab = _vocab("alpha")
    path = _write_yaml(tmp_path, "model: m\nbogus_setting: 1\n")
    with pytest.raises(ConfigError) as exc:
        _config().load_config(config_path=path, cli_overrides=None, vocabulary=vocab)
    assert "bogus_setting" in str(exc.value)


def test_malformed_yaml_raises_configerror(tmp_path) -> None:
    vocab = _vocab("alpha")
    path = _write_yaml(tmp_path, "model: [unbalanced\n")
    with pytest.raises(ConfigError) as exc:
        _config().load_config(config_path=path, cli_overrides=None, vocabulary=vocab)
    assert path in str(exc.value) or "YAML" in str(exc.value) or "yaml" in str(exc.value)


def test_non_mapping_yaml_root_raises_configerror(tmp_path) -> None:
    vocab = _vocab("alpha")
    path = _write_yaml(tmp_path, "- just\n- a\n- list\n")
    with pytest.raises(ConfigError):
        _config().load_config(config_path=path, cli_overrides=None, vocabulary=vocab)


def test_missing_config_file_raises_configerror(tmp_path) -> None:
    """An explicitly supplied --config path that does not exist is an error."""
    vocab = _vocab("alpha")
    missing = str(tmp_path / "does_not_exist.yaml")
    with pytest.raises(ConfigError) as exc:
        _config().load_config(config_path=missing, cli_overrides=None, vocabulary=vocab)
    assert "does_not_exist.yaml" in str(exc.value)


# --------------------------------------------------------------------------- #
# Budget typing in YAML
# --------------------------------------------------------------------------- #


def test_budgets_load_from_yaml_with_correct_types(tmp_path) -> None:
    vocab = _vocab("alpha")
    path = _write_yaml(tmp_path, "max_cost_usd: 5\nmax_steps: 30\n")
    cfg = _config().load_config(config_path=path, cli_overrides=None, vocabulary=vocab)
    assert cfg.max_cost_usd == 5.0
    assert isinstance(cfg.max_cost_usd, float)
    assert cfg.max_steps == 30
    assert isinstance(cfg.max_steps, int)


def test_negative_budget_raises_configerror(tmp_path) -> None:
    vocab = _vocab("alpha")
    path = _write_yaml(tmp_path, "max_cost_usd: -1\n")
    with pytest.raises(ConfigError):
        _config().load_config(config_path=path, cli_overrides=None, vocabulary=vocab)


def test_non_string_roles_value_raises_configerror(tmp_path) -> None:
    vocab = _vocab("alpha")
    path = _write_yaml(tmp_path, "roles: 5\n")
    with pytest.raises(ConfigError):
        _config().load_config(config_path=path, cli_overrides=None, vocabulary=vocab)
