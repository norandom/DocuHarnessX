"""Tests for the ``dhx`` CLI (task 4.1 boundary: dhx CLI).

Task 4.1 fleshes out :mod:`docuharnessx.cli` to:

* parse the ``run`` subcommand (``<target-repo>``, ``--out``, ``--config``,
  ``--roles``) and the ``init`` subcommand (``[project-dir]``, ``--default``,
  ``--force``);
* validate the target path is an existing directory **before any run**, raising
  / mapping :class:`TargetRepoError` to a non-zero exit (Req 4.7);
* load the project vocabulary via ``load_project_vocabulary`` (default-profile
  fallback + ``dhx init`` hint when absent; ``OntologyConfigError`` exit on an
  invalid file; Req 10.1, 10.3, 10.4);
* load :class:`DocgenConfig` (YAML then CLI overrides) and validate roles against
  the loaded ``Vocabulary`` (``ConfigError`` listing valid roles; Req 7.3, 7.5);
* resolve the model and bind it via ``ModelConfig(main=...).agentic(make_docgen(...))``
  — model NOT in ``HarnessConfig`` (Req 3.1) — applying cost/step budgets through
  the baseline Control capability.

These tests inject the test-scoped :class:`tests._fakes.FakeProvider` wherever a
model is needed, so no network call and no real credentials are required. The
production model resolver is never exercised here.
"""

from __future__ import annotations

import os

import pytest

from harnessx.core.harness import Harness, HarnessConfig
from harnessx.core.model_config import ModelConfig

from docuharnessx import cli
from docuharnessx.errors import ConfigError, OntologyConfigError, TargetRepoError

from _fakes import FakeProvider


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #


def _fake_model() -> ModelConfig:
    """A ModelConfig bound to the no-network fake provider."""
    return ModelConfig(main=FakeProvider())


def _write_invalid_ontology(project_dir: str) -> str:
    """Write a present-but-invalid ``.docuharnessx/ontology.yaml`` and return it."""
    cfg_dir = os.path.join(project_dir, ".docuharnessx")
    os.makedirs(cfg_dir, exist_ok=True)
    path = os.path.join(cfg_dir, "ontology.yaml")
    with open(path, "w", encoding="utf-8") as handle:
        # A bare scalar is not a valid vocabulary mapping → loader rejects it.
        handle.write("not-a-vocabulary-mapping\n")
    return path


# --------------------------------------------------------------------------- #
# Parser surface                                                               #
# --------------------------------------------------------------------------- #


def test_parser_exposes_run_and_init_subcommands() -> None:
    parser = cli.build_parser()
    # run: target + --out/--config/--roles
    ns = parser.parse_args(
        ["run", "/some/path", "--out", "/o", "--config", "c.yaml", "--roles", "developer"]
    )
    assert ns.command == "run"
    assert ns.target_repo == "/some/path"
    assert ns.out == "/o"
    assert ns.config == "c.yaml"
    assert ns.roles == "developer"
    # init: [project-dir] + --default/--force
    ns2 = parser.parse_args(["init", "/proj", "--default", "--force"])
    assert ns2.command == "init"
    assert ns2.project_dir == "/proj"
    assert ns2.default is True
    assert ns2.force is True


# --------------------------------------------------------------------------- #
# Target validation BEFORE any run (Req 4.7)                                   #
# --------------------------------------------------------------------------- #


def test_bad_target_path_exits_nonzero_with_target_repo_error(tmp_path, capsys) -> None:
    missing = str(tmp_path / "does-not-exist")
    code = cli.main(["run", missing], model_config=_fake_model())
    assert code != 0
    err = capsys.readouterr().err
    assert "TargetRepoError" in err
    assert missing in err


def test_target_file_not_directory_exits_nonzero(tmp_path, capsys) -> None:
    f = tmp_path / "afile.txt"
    f.write_text("x", encoding="utf-8")
    code = cli.main(["run", str(f)], model_config=_fake_model())
    assert code != 0
    assert "TargetRepoError" in capsys.readouterr().err


def test_target_validated_before_any_model_resolution(tmp_path) -> None:
    # A bad target must abort before the model is even resolved/bound: passing no
    # model_config (so the real resolver would be used) must still fail with the
    # target error, not a ModelResolutionError, proving ordering (Req 4.7).
    missing = str(tmp_path / "nope")
    # Ensure no provider env leaks a model into the resolver.
    code = cli.main(["run", missing])
    assert code != 0


def test_prepare_run_raises_target_repo_error_before_run(tmp_path) -> None:
    missing = str(tmp_path / "absent")
    args = cli.build_parser().parse_args(["run", missing])
    with pytest.raises(TargetRepoError) as exc:
        cli.prepare_run(args, model_config=_fake_model())
    assert missing in str(exc.value)


# --------------------------------------------------------------------------- #
# Model bound via .agentic, never in HarnessConfig (Req 3.1)                   #
# --------------------------------------------------------------------------- #


def test_model_bound_via_agentic_not_in_harness_config(tmp_path) -> None:
    target = tmp_path / "repo"
    target.mkdir()
    out = tmp_path / "out"
    args = cli.build_parser().parse_args(["run", str(target), "--out", str(out)])
    prepared = cli.prepare_run(args, model_config=_fake_model())

    # The model is bound on the Harness, not on the HarnessConfig.
    assert isinstance(prepared.harness, Harness)
    assert isinstance(prepared.harness.config, HarnessConfig)
    assert not hasattr(prepared.harness.config, "model")
    assert not hasattr(prepared.harness.config, "model_config")
    # The bound provider is the injected fake (model lives on the model_config).
    assert isinstance(prepared.harness.model_config.main, FakeProvider)


def test_prepare_run_applies_cost_budget_through_control(tmp_path) -> None:
    target = tmp_path / "repo"
    target.mkdir()
    config_yaml = tmp_path / "c.yaml"
    config_yaml.write_text("max_cost_usd: 7.5\n", encoding="utf-8")
    args = cli.build_parser().parse_args(
        ["run", str(target), "--out", str(tmp_path / "out"), "--config", str(config_yaml)]
    )
    prepared = cli.prepare_run(args, model_config=_fake_model())
    # The cost budget is applied through the baseline Control capability: a
    # CostGuardProcessor appears in the composed HarnessConfig.
    targets = [
        p.get("_target_", "")
        for p in prepared.harness.config.processors
        if isinstance(p, dict)
    ]
    assert any(t.endswith("CostGuardProcessor") for t in targets)


# --------------------------------------------------------------------------- #
# Unknown role exits non-zero listing valid roles (Req 7.3, 7.5)              #
# --------------------------------------------------------------------------- #


def test_unknown_role_exits_nonzero_listing_valid_roles(tmp_path, capsys) -> None:
    target = tmp_path / "repo"
    target.mkdir()
    code = cli.main(
        ["run", str(target), "--out", str(tmp_path / "out"), "--roles", "wizard"],
        model_config=_fake_model(),
    )
    assert code != 0
    err = capsys.readouterr().err
    assert "ConfigError" in err
    # The error lists the valid roles drawn from the (default-profile) vocabulary.
    assert "developer" in err
    assert "wizard" in err


def test_known_role_subset_is_accepted(tmp_path) -> None:
    target = tmp_path / "repo"
    target.mkdir()
    args = cli.build_parser().parse_args(
        ["run", str(target), "--out", str(tmp_path / "out"), "--roles", "developer,manager"]
    )
    prepared = cli.prepare_run(args, model_config=_fake_model())
    assert prepared.config.roles == ("developer", "manager")


# --------------------------------------------------------------------------- #
# Invalid ontology exits non-zero with OntologyConfigError (Req 10.4)         #
# --------------------------------------------------------------------------- #


def test_invalid_ontology_file_exits_nonzero_ontology_config_error(tmp_path, capsys) -> None:
    target = tmp_path / "repo"
    target.mkdir()
    _write_invalid_ontology(str(target))
    code = cli.main(
        ["run", str(target), "--out", str(tmp_path / "out")],
        model_config=_fake_model(),
    )
    assert code != 0
    assert "OntologyConfigError" in capsys.readouterr().err


def test_prepare_run_raises_ontology_config_error_for_invalid_file(tmp_path) -> None:
    target = tmp_path / "repo"
    target.mkdir()
    _write_invalid_ontology(str(target))
    args = cli.build_parser().parse_args(["run", str(target), "--out", str(tmp_path / "out")])
    with pytest.raises(OntologyConfigError):
        cli.prepare_run(args, model_config=_fake_model())


# --------------------------------------------------------------------------- #
# Absent ontology → default-profile fallback + dhx init hint (Req 10.3)       #
# --------------------------------------------------------------------------- #


def test_absent_ontology_falls_back_to_default_profile_with_hint(tmp_path, capsys) -> None:
    target = tmp_path / "repo"
    target.mkdir()
    args = cli.build_parser().parse_args(["run", str(target), "--out", str(tmp_path / "out")])
    prepared = cli.prepare_run(args, model_config=_fake_model())
    assert prepared.used_default is True
    # Default-profile roles are the selection when --roles is omitted.
    assert "developer" in prepared.config.roles
    # The CLI surfaces a `dhx init` hint when the default profile is used.
    out = capsys.readouterr().out
    assert "dhx init" in out


# --------------------------------------------------------------------------- #
# Bad config file exits non-zero with ConfigError (Req 7.6)                    #
# --------------------------------------------------------------------------- #


def test_unknown_config_key_exits_nonzero_config_error(tmp_path, capsys) -> None:
    target = tmp_path / "repo"
    target.mkdir()
    bad = tmp_path / "bad.yaml"
    bad.write_text("not_a_setting: 1\n", encoding="utf-8")
    code = cli.main(
        ["run", str(target), "--out", str(tmp_path / "out"), "--config", str(bad)],
        model_config=_fake_model(),
    )
    assert code != 0
    assert "ConfigError" in capsys.readouterr().err


# --------------------------------------------------------------------------- #
# No subcommand prints help (scaffold behaviour preserved)                     #
# --------------------------------------------------------------------------- #


def test_no_command_returns_nonzero() -> None:
    assert cli.main([]) != 0


# --------------------------------------------------------------------------- #
# Bare CLI form: `dhx <target> --out DIR [--config YAML]` (Req 4.1, 4.8)       #
# --------------------------------------------------------------------------- #


def test_bare_form_without_run_subcommand_runs_pipeline(tmp_path, capsys) -> None:
    # The spec's reference form `dhx <target> --out DIR` (no explicit `run`) must
    # route to the run pipeline and exit 0 (Req 4.1, 4.8).
    target = tmp_path / "repo"
    target.mkdir()
    out = tmp_path / "out"
    code = cli.main([str(target), "--out", str(out)], model_config=_fake_model())
    assert code == 0
    # A journal trace was written under --out (the pipeline actually ran).
    journals = [
        os.path.join(root, name)
        for root, _dirs, files in os.walk(str(out))
        for name in files
        if name.endswith(".jsonl") and not name.endswith("_trace.jsonl")
    ]
    assert journals, "the bare-form run must journal under --out DIR"


def test_bare_form_bad_target_exits_nonzero(tmp_path, capsys) -> None:
    # The bare form still validates the target before any run (Req 4.7).
    missing = str(tmp_path / "nope")
    code = cli.main([missing], model_config=_fake_model())
    assert code != 0
    assert "TargetRepoError" in capsys.readouterr().err


def test_bare_form_does_not_shadow_init(tmp_path, capsys) -> None:
    # `dhx init ...` must NOT be reinterpreted as a bare run target.
    project = tmp_path / "proj"
    project.mkdir()
    code = cli.main(["init", str(project), "--default"])
    assert code == 0
    assert os.path.isfile(os.path.join(str(project), ".docuharnessx", "ontology.yaml"))


# --------------------------------------------------------------------------- #
# Configured step budget is applied to the run (Req 7.5, 8.4)                  #
# --------------------------------------------------------------------------- #


def test_configured_step_budget_is_applied_and_exits_nonzero(tmp_path, capsys) -> None:
    # A configured `max_steps: 0` makes the run exceed its step budget before any
    # model call, so it terminates with budget_exceeded → non-zero exit (Req 7.5,
    # 8.4). This proves the configured step budget actually reaches the run (it was
    # previously ignored in favour of a hardcoded ceiling).
    target = tmp_path / "repo"
    target.mkdir()
    out = tmp_path / "out"
    cfg = tmp_path / "c.yaml"
    cfg.write_text("max_steps: 0\n", encoding="utf-8")
    code = cli.main(
        [str(target), "--out", str(out), "--config", str(cfg)],
        model_config=_fake_model(),
    )
    assert code != 0
    err = capsys.readouterr().err
    assert "budget_exceeded" in err, err


# --------------------------------------------------------------------------- #
# Missing-dependency check raises the typed DependencyError (Req 1.4)          #
# --------------------------------------------------------------------------- #


def test_require_harnessx_raises_dependency_error(monkeypatch) -> None:
    # Req 1.4: when harnessx is not importable, the CLI raises the typed
    # DependencyError (a DocuHarnessXError) rather than a bare RuntimeError, so
    # main() maps it to the standard non-zero exit.
    import builtins

    from docuharnessx.errors import DependencyError, DocuHarnessXError

    real_import = builtins.__import__

    def _fake_import(name, *a, **kw):
        if name == "harnessx":
            raise ImportError("simulated missing harnessx")
        return real_import(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", _fake_import)
    with pytest.raises(DependencyError) as exc:
        cli._require_harnessx()
    assert isinstance(exc.value, DocuHarnessXError)
    assert "harnessx" in str(exc.value)


# --------------------------------------------------------------------------- #
# --deploy-mode flag + threading into DocgenConfig (github-pages-deploy 4.3)   #
# Req 3.2, 3.3                                                                 #
# --------------------------------------------------------------------------- #


def test_run_parser_exposes_deploy_mode_flag() -> None:
    """The run subparser accepts --deploy-mode and parses it onto the namespace."""
    parser = cli.build_parser()
    ns = parser.parse_args(
        ["run", "/some/path", "--out", "/o", "--deploy-mode", "build-only"]
    )
    assert ns.deploy_mode == "build-only"


def test_run_parser_deploy_mode_defaults_to_none_when_absent() -> None:
    """Omitting --deploy-mode leaves the namespace value None (flag not supplied).

    A None CLI override does not clobber the config-file value, and the config
    surface then applies the emit-ci-workflow default.
    """
    parser = cli.build_parser()
    ns = parser.parse_args(["run", "/some/path", "--out", "/o"])
    assert ns.deploy_mode is None


def test_prepare_run_threads_deploy_mode_flag_into_config(tmp_path) -> None:
    """A --deploy-mode flag reaches the bound DocgenConfig.deploy_mode."""
    target = tmp_path / "repo"
    target.mkdir()
    out = tmp_path / "out"
    args = cli.build_parser().parse_args(
        ["run", str(target), "--out", str(out), "--deploy-mode", "gh-deploy"]
    )
    prepared = cli.prepare_run(args, model_config=_fake_model())
    assert prepared.config.deploy_mode == "gh-deploy"


def test_prepare_run_defaults_deploy_mode_when_flag_absent(tmp_path) -> None:
    """No --deploy-mode flag → the bound config carries the emit-ci-workflow default."""
    target = tmp_path / "repo"
    target.mkdir()
    out = tmp_path / "out"
    args = cli.build_parser().parse_args(["run", str(target), "--out", str(out)])
    prepared = cli.prepare_run(args, model_config=_fake_model())
    assert prepared.config.deploy_mode == "emit-ci-workflow"
