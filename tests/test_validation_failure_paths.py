"""Validation: failure paths and single-stage replaceability (task 5.2).

This is the spec's failure-path / replaceability validation gate (Req 3.4, 5.6,
7.3, 7.6, 8.4, 8.5, 10.3, 10.4). Where ``test_cli_e2e`` proves the *happy* path
end to end, this module proves the skeleton fails **safely and explicitly** on
every boundary error, falls back **with a hint** when the ontology is absent, and
that a single pipeline stage can be swapped **without editing the bundle entry
point** ``make_docgen``.

Boundary (task 5.2): dhx CLI, StageRegistry, ModelResolver, DocgenConfig,
OntologyLoader. Each test drives the real public surface
(:func:`docuharnessx.cli.main` / :func:`docuharnessx.cli.prepare_run` /
:func:`docuharnessx.stages.register_stages`), asserting the observable contract a
caller / CI relies on: a non-zero exit code plus an explicit, cause-naming
message, or the documented fallback behaviour.

Credential-free
---------------
Every test that reaches model binding injects the test-scoped
:class:`tests._fakes.FakeProvider`, so no network call and no real credentials
are required. The single test that exercises the *production* model resolver
(unresolved-model) does so with a deliberately **empty** provider environment so
the resolver fails fast *before* any provider is ever constructed — still no
network. The production resolver is otherwise never exercised here.
"""

from __future__ import annotations

import os

import pytest

from harnessx.core.builder import HarnessBuilder, _topological_sort_entries
from harnessx.core.model_config import ModelConfig
from harnessx.core.processor import Processor

import docuharnessx.stages as stages_pkg
from docuharnessx import cli
from docuharnessx.errors import (
    ModelResolutionError,
    OntologyConfigError,
    TargetRepoError,
)
from docuharnessx.stages.base import PIPELINE_HOOK

from _fakes import FakeProvider, make_replacement_stage


# The provider env vars the production resolver consults (HarnessX convention).
# The unresolved-model test clears all of them so resolution fails fast (Req 3.4).
_PROVIDER_ENV_VARS = (
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


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #


def _fake_model() -> ModelConfig:
    """A ``ModelConfig`` bound to the no-network fake provider (credential-free)."""
    return ModelConfig(main=FakeProvider())


def _target(tmp_path) -> str:
    """A genuine, existing target-repository directory under *tmp_path*."""
    target = tmp_path / "repo"
    target.mkdir()
    return str(target)


def _write_invalid_ontology(target: str) -> str:
    """Write a present-but-invalid ``.docuharnessx/ontology.yaml`` and return it.

    A bare scalar is not a valid vocabulary mapping, so the ``ontology-engine``
    loader rejects it and :func:`load_project_vocabulary` raises
    :class:`OntologyConfigError` (Req 10.4).
    """
    cfg_dir = os.path.join(target, ".docuharnessx")
    os.makedirs(cfg_dir, exist_ok=True)
    path = os.path.join(cfg_dir, "ontology.yaml")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("not-a-vocabulary-mapping\n")
    return path


def _hook_order(builder: HarnessBuilder) -> list[object]:
    """Processors on :data:`PIPELINE_HOOK` in their resolved execution order."""
    entries = [e for e in builder._entries if e.hook == PIPELINE_HOOK]
    return [e.processor for e in _topological_sort_entries(entries)]


def _stage_name(proc: object) -> str | None:
    """Best-effort stage identity: the no-op stub carries a ``stage_name``."""
    return getattr(proc, "stage_name", None)


# --------------------------------------------------------------------------- #
# Bad target path exits non-zero BEFORE any run (Req 4.7)                      #
# --------------------------------------------------------------------------- #


def test_bad_target_path_exits_nonzero_before_any_run(tmp_path, capsys) -> None:
    """A missing target aborts with a non-zero exit and an explicit message.

    The failure must happen *before* any run is driven, so no journal directory is
    created under the would-be output path (Req 4.7, 8.5).
    """
    missing = str(tmp_path / "does-not-exist")
    out = tmp_path / "out"

    code = cli.main(["run", missing, "--out", str(out)], model_config=_fake_model())

    assert code != 0
    err = capsys.readouterr().err
    assert "TargetRepoError" in err
    assert missing in err
    # Nothing ran: no output/journal directory was created for the aborted run.
    assert not os.path.exists(str(out))


def test_bad_target_aborts_before_model_resolution(tmp_path, monkeypatch) -> None:
    """A bad target aborts before the model is even resolved (ordering, Req 4.7).

    With no ``model_config`` injected and an empty provider environment, the real
    resolver *would* raise :class:`ModelResolutionError` — but the target is
    validated first, so the surfaced failure is the target error, proving the
    target check runs before any model work and before any run.
    """
    for var in _PROVIDER_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    missing = str(tmp_path / "nope")

    args = cli.build_parser().parse_args(["run", missing])
    with pytest.raises(TargetRepoError):
        cli.prepare_run(args)  # no model_config → real resolver would run later


def test_target_that_is_a_file_exits_nonzero(tmp_path, capsys) -> None:
    """A target that exists but is a file (not a directory) fails explicitly."""
    f = tmp_path / "a-file.txt"
    f.write_text("x", encoding="utf-8")

    code = cli.main(["run", str(f)], model_config=_fake_model())

    assert code != 0
    assert "TargetRepoError" in capsys.readouterr().err


# --------------------------------------------------------------------------- #
# Unresolved model exits non-zero with an explicit message (Req 3.4)          #
# --------------------------------------------------------------------------- #


def test_unresolved_model_exits_nonzero_with_explicit_message(
    tmp_path, capsys, monkeypatch
) -> None:
    """With a valid target but no model in config or env, the run fails fast.

    No ``model_config`` is injected, so the production resolver runs against an
    **empty** provider environment and raises :class:`ModelResolutionError` before
    any provider is constructed (still no network). The CLI maps that to a non-zero
    exit and an explicit, env-var-naming message (Req 3.4).
    """
    for var in _PROVIDER_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    target = _target(tmp_path)

    code = cli.main(["run", target, "--out", str(tmp_path / "out")])

    assert code != 0
    err = capsys.readouterr().err
    assert "ModelResolutionError" in err
    # The message guides the operator to the env-var convention (Req 3.4).
    assert "ANTHROPIC_API_KEY" in err or "OPENAI_API_KEY" in err


def test_unresolved_model_raises_before_run(tmp_path, monkeypatch) -> None:
    """prepare_run raises ``ModelResolutionError`` (not a run failure) when unresolved."""
    for var in _PROVIDER_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    target = _target(tmp_path)
    args = cli.build_parser().parse_args(["run", target, "--out", str(tmp_path / "out")])

    with pytest.raises(ModelResolutionError):
        cli.prepare_run(args)  # no model_config → real resolver, empty env


# --------------------------------------------------------------------------- #
# Malformed config exits non-zero with an explicit message (Req 7.6)          #
# --------------------------------------------------------------------------- #


def test_malformed_config_unparseable_yaml_exits_nonzero(tmp_path, capsys) -> None:
    """Unparseable YAML in ``--config`` fails with an explicit ConfigError."""
    target = _target(tmp_path)
    bad = tmp_path / "bad.yaml"
    # Unbalanced brackets → a YAML parse error, surfaced as ConfigError (Req 7.6).
    bad.write_text("model: [unclosed\n", encoding="utf-8")

    code = cli.main(
        ["run", target, "--out", str(tmp_path / "out"), "--config", str(bad)],
        model_config=_fake_model(),
    )

    assert code != 0
    err = capsys.readouterr().err
    assert "ConfigError" in err
    assert str(bad) in err


def test_unknown_config_key_exits_nonzero_listing_valid_settings(
    tmp_path, capsys
) -> None:
    """An unknown top-level config key fails and the message lists valid settings."""
    target = _target(tmp_path)
    bad = tmp_path / "bad.yaml"
    bad.write_text("not_a_setting: 1\n", encoding="utf-8")

    code = cli.main(
        ["run", target, "--out", str(tmp_path / "out"), "--config", str(bad)],
        model_config=_fake_model(),
    )

    assert code != 0
    err = capsys.readouterr().err
    assert "ConfigError" in err
    assert "not_a_setting" in err


def test_named_config_file_missing_exits_nonzero(tmp_path, capsys) -> None:
    """A ``--config`` path the operator named but that does not exist fails fast."""
    target = _target(tmp_path)
    missing_cfg = str(tmp_path / "no-such-config.yaml")

    code = cli.main(
        ["run", target, "--out", str(tmp_path / "out"), "--config", missing_cfg],
        model_config=_fake_model(),
    )

    assert code != 0
    err = capsys.readouterr().err
    assert "ConfigError" in err
    assert missing_cfg in err


# --------------------------------------------------------------------------- #
# Unknown role exits non-zero, listing the valid roles (Req 7.3)              #
# --------------------------------------------------------------------------- #


def test_unknown_role_exits_nonzero_listing_valid_roles(tmp_path, capsys) -> None:
    """A ``--roles`` value not in the loaded vocabulary fails, listing valid roles."""
    target = _target(tmp_path)

    code = cli.main(
        ["run", target, "--out", str(tmp_path / "out"), "--roles", "wizard"],
        model_config=_fake_model(),
    )

    assert code != 0
    err = capsys.readouterr().err
    assert "ConfigError" in err
    # The offending role is named and at least one valid (default-profile) role is
    # listed so the operator can correct the selection (Req 7.3, 7.5).
    assert "wizard" in err
    assert "developer" in err


def test_unknown_role_in_config_file_exits_nonzero(tmp_path, capsys) -> None:
    """An unknown role supplied via the config file (not --roles) also fails."""
    target = _target(tmp_path)
    cfg = tmp_path / "c.yaml"
    cfg.write_text("roles:\n  - sorcerer\n", encoding="utf-8")

    code = cli.main(
        ["run", target, "--out", str(tmp_path / "out"), "--config", str(cfg)],
        model_config=_fake_model(),
    )

    assert code != 0
    err = capsys.readouterr().err
    assert "ConfigError" in err
    assert "sorcerer" in err


# --------------------------------------------------------------------------- #
# Invalid ontology exits non-zero with OntologyConfigError (Req 10.4)         #
# --------------------------------------------------------------------------- #


def test_invalid_ontology_exits_nonzero_with_ontology_config_error(
    tmp_path, capsys
) -> None:
    """A present-but-invalid ontology file fails with an explicit OntologyConfigError."""
    target = _target(tmp_path)
    _write_invalid_ontology(target)

    code = cli.main(
        ["run", target, "--out", str(tmp_path / "out")],
        model_config=_fake_model(),
    )

    assert code != 0
    assert "OntologyConfigError" in capsys.readouterr().err


def test_invalid_ontology_raises_before_run(tmp_path) -> None:
    """prepare_run raises ``OntologyConfigError`` (does not fall through to a run)."""
    target = _target(tmp_path)
    _write_invalid_ontology(target)
    args = cli.build_parser().parse_args(["run", target, "--out", str(tmp_path / "out")])

    with pytest.raises(OntologyConfigError):
        cli.prepare_run(args, model_config=_fake_model())


# --------------------------------------------------------------------------- #
# Absent ontology → default-profile fallback WITH a `dhx init` hint (Req 10.3) #
# --------------------------------------------------------------------------- #


def test_absent_ontology_falls_back_to_default_profile_with_hint(
    tmp_path, capsys
) -> None:
    """An absent ontology file falls back to the default profile and prints a hint.

    The run still completes (exit 0) on the default profile, AND a ``dhx init``
    hint is surfaced so the operator knows the project is uncustomised (Req 10.3).
    """
    target = _target(tmp_path)
    out = tmp_path / "out"

    code = cli.main(["run", target, "--out", str(out)], model_config=_fake_model())

    assert code == 0
    stdout = capsys.readouterr().out
    # The fallback is announced AND the customisation hint names `dhx init` (Req 10.3).
    assert "default ontology profile" in stdout
    assert "dhx init" in stdout


def test_absent_ontology_uses_default_profile_vocabulary(tmp_path, capsys) -> None:
    """prepare_run flags ``used_default`` and selects the default-profile roles."""
    from docuharnessx._ontology import default_profile

    target = _target(tmp_path)
    args = cli.build_parser().parse_args(["run", target, "--out", str(tmp_path / "out")])

    prepared = cli.prepare_run(args, model_config=_fake_model())

    assert prepared.used_default is True
    # The fallback vocabulary is the ontology-engine default profile, and the role
    # selection defaults to all of its roles (Req 10.3, 7.2).
    assert prepared.vocabulary == default_profile()
    assert set(prepared.config.roles) == {r.id for r in default_profile().roles}
    # The hint was printed during preparation.
    assert "dhx init" in capsys.readouterr().out


# --------------------------------------------------------------------------- #
# Single-stage replaceability: swapping ONE stage factory changes ONLY that    #
# stage in the registry, WITHOUT editing make_docgen (Req 5.6)                 #
# --------------------------------------------------------------------------- #


#: The distinguishable replacement stage factory used to model a Wave 1+ swap. It
#: is defined at module scope in ``tests/_fakes.py`` so HarnessX can serialize it to
#: a real ``_target_`` (a class defined inside a test function cannot be), which the
#: ``make_docgen`` replaceability test relies on.
_replacement_stage_factory = make_replacement_stage


def test_swapping_one_stage_factory_changes_only_that_stage(monkeypatch) -> None:
    """Replacing ONE entry in STAGES changes only that stage in register_stages.

    This proves single-stage replaceability (Req 5.6): a Wave 1+ spec swaps a
    single ``(name, factory)`` entry in :data:`docuharnessx.stages.STAGES` and the
    stage registry reflects exactly that one change — every other stage is
    unchanged, the canonical order is preserved, and the count is unchanged.
    """
    original = list(stages_pkg.STAGES)
    baseline_names = [name for name, _ in original]
    swap_index = baseline_names.index("classify")

    # Swap ONLY the classify factory; keep its name and position.
    swapped = list(original)
    swapped[swap_index] = ("classify", _replacement_stage_factory)
    monkeypatch.setattr(stages_pkg, "STAGES", swapped, raising=True)

    procs = _hook_order(stages_pkg.register_stages(HarnessBuilder()))
    resolved = [_stage_name(p) for p in procs]

    # Exactly the swapped stage is the replacement; every other stage is the
    # original canonical stage, and the count/order is otherwise unchanged.
    assert len(procs) == len(original)
    assert resolved[swap_index] == "classify-REPLACED"
    for i, (name, _factory) in enumerate(original):
        if i == swap_index:
            continue
        assert resolved[i] == name, (
            f"stage at index {i} changed unexpectedly: {resolved[i]} != {name}"
        )


def test_single_stage_swap_does_not_edit_make_docgen(monkeypatch) -> None:
    """The swap flows through ``make_docgen`` unchanged — no bundle edit needed.

    ``make_docgen`` composes the pipeline by *calling* ``register_stages`` over the
    live :data:`STAGES` list; it hard-codes no stage. So replacing one factory in
    ``STAGES`` is reflected in the composed ``HarnessConfig`` without any edit to
    ``bundle.py``. We assert that by composing through the public ``make_docgen``
    after the swap and reading back the serialized stage targets: the swapped stage
    has a *different* importable ``_target_`` while the other seven are still their
    own canonical per-module no-ops, in order.

    The replacement here is a genuine, importable production-module stage class — a
    different per-stage class than the slot's original — so HarnessX serializes it to
    a real ``{_target_: ...}`` dict, exactly how a real Wave 1+ stage in a production
    module would appear. (A class living in the underscore-prefixed ``_fakes`` test
    module is treated as runtime-only by ``_serialize_processor`` and would be
    dropped from the serialized config, so it is unsuitable for *this* assertion;
    the registry-instance test above uses one because it inspects live instances.)

    Each stage now serializes to its OWN module path
    (``docuharnessx.stages.<name>.<X>Stage``) — a real, importable, module-level
    class. That is the fix for the prior defect where every stage serialized to the
    unimportable ``docuharnessx.stages.base.<X>Stage`` and was silently dropped at
    run time.
    """
    from docuharnessx.bundle import make_docgen
    from docuharnessx.stages.deploy import DeployStage, make_deploy_stage

    def _rewritten_classify_factory():
        # A real, importable, distinguishable alternative stage (the Wave 1+ swap):
        # a different per-module stage class, so it serializes to a real _target_
        # under its own module path — exactly how a production Wave 1+ stage appears.
        return make_deploy_stage()

    original = list(stages_pkg.STAGES)
    baseline_names = [name for name, _ in original]
    swap_index = baseline_names.index("classify")

    swapped = list(original)
    swapped[swap_index] = ("classify", _rewritten_classify_factory)
    monkeypatch.setattr(stages_pkg, "STAGES", swapped, raising=True)

    config = make_docgen(journal_dir="/tmp/dhx-5_2-probe")

    # The composed stage processors, in composition order, by serialized _target_.
    # A stage is anything whose class name ends in ``Stage`` (the no-op stubs
    # IngestStage…DeployStage plus the rewritten one); control processors do not.
    stage_targets: list[str] = [
        p["_target_"]
        for p in config.processors
        if isinstance(p, dict) and p.get("_target_", "").rsplit(".", 1)[-1].endswith("Stage")
    ]

    # Eight stages composed, in canonical order, exactly one replaced.
    assert len(stage_targets) == 8, stage_targets
    # The swapped slot is the rewritten (DeployStage) stage, NOT the original
    # ClassifyStage — proving the single-stage swap reached the composed config.
    assert stage_targets[swap_index] == "docuharnessx.stages.deploy.DeployStage"
    assert stage_targets[swap_index] != "docuharnessx.stages.classify.ClassifyStage"
    # Every other composed stage is still the original no-op stub for its canonical
    # stage, serialized to its own importable per-module path — unchanged by the
    # single-stage swap. (The deploy slot legitimately stays DeployStage.)
    for i, (name, _factory) in enumerate(original):
        if i == swap_index:
            continue
        title = "".join(part.capitalize() for part in name.split("_"))
        assert stage_targets[i] == f"docuharnessx.stages.{name}.{title}Stage"


def test_stages_factories_are_per_module_so_swaps_are_local() -> None:
    """Each STAGES factory IS the per-stage module's factory (swap locality, Req 5.6).

    A swap is genuinely single-stage only if each registry entry references its own
    module's ``make_<stage>_stage``; otherwise editing one module could ripple.
    This pins that the registry's indirection is per-module so replacing one
    module's factory (the Wave 1+ mechanism) changes only that stage.
    """
    import importlib

    for name, factory in stages_pkg.STAGES:
        module = importlib.import_module(f"docuharnessx.stages.{name}")
        assert factory is getattr(module, f"make_{name}_stage")
        # Each factory builds a fresh Processor instance (no shared state to leak
        # across a swap).
        proc = factory()
        assert isinstance(proc, Processor)
        assert factory() is not factory()
