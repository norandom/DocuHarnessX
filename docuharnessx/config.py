"""The DocuHarnessX configuration surface and its precedence (task 2.1 boundary).

This module owns :class:`DocgenConfig` — the single value object holding every
operator-tunable run setting — and :func:`load_config`, which materializes it
from a ``--config`` YAML file overlaid with command-line argument overrides
(design "DocgenConfig"; Req 7.1–7.4, 7.6).

Settings (Req 7.1)
------------------
The surface accepts exactly five things plus two budgets:

* ``target_repo`` — the target-repository path,
* ``out_dir`` — the output directory,
* ``roles`` — the role selection,
* ``model`` — the model selection,
* ``max_cost_usd`` / ``max_steps`` — the cost and step budgets.

Roles come from the loaded ``Vocabulary`` — never a hardcoded list (Req 7.2)
-----------------------------------------------------------------------------
The set of *valid* roles is derived from the loaded ``Vocabulary`` (owned by
``ontology-engine`` and re-exported through ``docuharnessx._ontology``). When the
operator selects no roles, the selection defaults to *all* role ids present in
that ``Vocabulary``. There is deliberately no ten-role constant here: the harness
stays reusable across projects because role validity follows the project's own
vocabulary (design "NO RoleId alias — roles come from the loaded Vocabulary").

Precedence (Req 7.4)
--------------------
``load_config`` reads the YAML file first (when a path is given), then applies the
CLI overrides on top, so a command-line argument wins over the file for any
overlapping setting. A CLI override whose value is ``None`` (the flag was not
supplied) does not clobber a value already set by the file.

Fail fast at the boundary (Req 7.3, 7.6)
----------------------------------------
Every malformed input surfaces a :class:`ConfigError` (mapped to a non-zero CLI
exit by the CLI layer) with an explicit, cause-naming message:

* an unknown YAML key, a non-mapping YAML root, or unparseable YAML (Req 7.6);
* a missing ``--config`` file the operator explicitly named;
* a role selection naming a role absent from the loaded ``Vocabulary`` — the
  message lists the valid roles (Req 7.3);
* a malformed budget value.

This module performs no model resolution, no harness composition, and no run
orchestration: it only produces a validated ``DocgenConfig``.
"""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import yaml

from .errors import ConfigError

if TYPE_CHECKING:  # pragma: no cover - typing only
    from docuharnessx._ontology import Vocabulary

__all__ = ["DocgenConfig", "load_config"]

# The settings the surface understands. Any other top-level key in a --config
# file is an unknown setting and fails fast (Req 7.6). This is the single source
# of truth for "what the config file may contain".
_KNOWN_KEYS: frozenset[str] = frozenset(
    {
        "target_repo",
        "out_dir",
        "roles",
        "model",
        "max_cost_usd",
        "max_steps",
        # github-pages-deploy seam extension (task 4.3, append-only): the deploy
        # mode the Deploy stage runs in. Validated downstream by the deploy-mode
        # resolver, not here (see DocgenConfig.deploy_mode).
        "deploy_mode",
    }
)

#: The default deploy mode used when no mode is configured (github-pages-deploy
#: Req 3.2): write ``mkdocs.yml`` + ``docs/`` + a ``.github/workflows/docs.yml``
#: Pages build-and-deploy workflow into the *target* working tree, with no
#: push/commit. Kept as a module constant so the surface's default tracks the
#: deployer's :func:`~docuharnessx.deployer.resolve_deploy_mode` default name in
#: one place rather than a bare literal scattered through the dataclass.
_DEFAULT_DEPLOY_MODE: str = "emit-ci-workflow"


@dataclass(frozen=True)
class DocgenConfig:
    """The validated run configuration: target/output, roles, model, budgets.

    Immutable so a resolved configuration cannot drift after validation. ``roles``
    is the *validated* selection — every id is guaranteed present in the loaded
    ``Vocabulary`` (Req 7.2, 7.3). ``model`` is left as ``None`` when unset so the
    model resolver can fall back to provider environment variables (Req 3.3).
    Budgets are ``None`` when unset, meaning "no limit" at the Control layer.
    """

    target_repo: str | None
    out_dir: str | None
    roles: tuple[str, ...]
    model: str | None
    max_cost_usd: float | None
    max_steps: int | None
    # github-pages-deploy seam extension (task 4.3, append-only). The deploy mode
    # the Deploy stage runs in, populated from the ``deploy_mode`` config-file key
    # and the ``--deploy-mode`` CLI override (Req 3.3). Defaults to
    # ``"emit-ci-workflow"`` when unconfigured (Req 3.2) so a bare ``dhx <repo>``
    # run deploys in the default mode. The *value* is validated downstream by
    # :func:`~docuharnessx.deployer.resolve_deploy_mode` at the stage boundary — a
    # bad mode surfaces there as a ``DeployInputError`` consistent with the other
    # fatal-input paths — so this surface only carries the configured string. Has a
    # default so every existing ``DocgenConfig(...)`` construction stays valid
    # (append-only: the field is last and defaulted).
    deploy_mode: str = _DEFAULT_DEPLOY_MODE


def _load_yaml(config_path: str) -> dict[str, Any]:
    """Read and parse a ``--config`` YAML file into a mapping (Req 7.4, 7.6).

    Raises :class:`ConfigError` when the path the operator named does not exist,
    when the YAML is unparseable, or when its root is not a mapping. An empty file
    is treated as an empty configuration.
    """
    if not os.path.exists(config_path):
        raise ConfigError(f"Config file not found: {config_path}")

    try:
        with open(config_path, "r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle)
    except yaml.YAMLError as exc:
        raise ConfigError(f"Malformed YAML in config file {config_path}: {exc}") from exc
    except OSError as exc:  # pragma: no cover - filesystem edge
        raise ConfigError(f"Unreadable config file {config_path}: {exc}") from exc

    if data is None:
        return {}
    if not isinstance(data, Mapping):
        raise ConfigError(
            f"Config file {config_path} must contain a mapping of settings, "
            f"got {type(data).__name__}."
        )

    unknown = sorted(set(data) - _KNOWN_KEYS)
    if unknown:
        raise ConfigError(
            f"Unknown setting(s) {unknown} in config file {config_path}. "
            f"Valid settings: {sorted(_KNOWN_KEYS)}."
        )
    return dict(data)


def _merged_value(key: str, file_data: Mapping[str, Any], cli: Mapping[str, Any]) -> Any:
    """CLI override wins over the file value when the CLI value is not ``None``.

    A CLI value of ``None`` means the flag was not supplied, so the file value (or
    its absence) is kept (Req 7.4).
    """
    if key in cli and cli[key] is not None:
        return cli[key]
    return file_data.get(key)


def _coerce_str(value: Any, key: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ConfigError(f"Setting '{key}' must be a string, got {type(value).__name__}.")
    return value


def _coerce_roles(value: Any) -> tuple[str, ...] | None:
    """Coerce a raw ``roles`` value into a tuple of ids, or ``None`` when unset.

    A list/tuple of strings is accepted; anything else (a bare scalar, or a list
    with non-string members) is malformed and fails fast (Req 7.6).
    """
    if value is None:
        return None
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ConfigError(
            f"Setting 'roles' must be a list of role ids, got {type(value).__name__}."
        )
    roles: list[str] = []
    for entry in value:
        if not isinstance(entry, str) or not entry.strip():
            raise ConfigError("Each entry in 'roles' must be a non-empty string.")
        roles.append(entry)
    return tuple(roles)


def _coerce_cost(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(
            f"Setting 'max_cost_usd' must be a number, got {type(value).__name__}."
        )
    cost = float(value)
    if cost < 0:
        raise ConfigError("Setting 'max_cost_usd' must be non-negative.")
    return cost


def _coerce_steps(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(
            f"Setting 'max_steps' must be an integer, got {type(value).__name__}."
        )
    if value < 0:
        raise ConfigError("Setting 'max_steps' must be non-negative.")
    return value


def _validate_roles(roles: tuple[str, ...], vocabulary: "Vocabulary") -> tuple[str, ...]:
    """Validate a role selection against the loaded ``Vocabulary`` (Req 7.3).

    Returns the selection unchanged when every id is a member; otherwise raises
    :class:`ConfigError` whose message names the offending role(s) and lists the
    valid roles drawn from the vocabulary.
    """
    valid = tuple(r.id for r in vocabulary.roles)
    unknown = [rid for rid in roles if not vocabulary.has_role(rid)]
    if unknown:
        raise ConfigError(
            f"Unknown role(s) {unknown}. Valid roles for this project: "
            f"{list(valid)}."
        )
    return roles


def load_config(
    *,
    config_path: str | os.PathLike[str] | None = None,
    cli_overrides: Mapping[str, Any] | None = None,
    vocabulary: "Vocabulary",
) -> DocgenConfig:
    """Build a validated :class:`DocgenConfig` from a YAML file and CLI overrides.

    Args:
        config_path: Path to a ``--config`` YAML file, or ``None`` for no file.
            When given but absent on disk, a :class:`ConfigError` is raised (the
            operator named a file that does not exist).
        cli_overrides: A mapping of command-line argument values keyed by the same
            setting names as the file. A value of ``None`` means the flag was not
            supplied and does not override the file value. CLI values win over the
            file for any overlapping setting (Req 7.4).
        vocabulary: The loaded project ``Vocabulary`` (from ``ontology-engine``).
            Valid roles are derived from it; an omitted role selection defaults to
            *all* of its role ids (Req 7.2). Passed in by keyword so the surface
            never imports the loader or a hardcoded role list.

    Returns:
        A frozen, validated :class:`DocgenConfig`.

    Raises:
        ConfigError: On a missing/malformed/unknown-key config file (Req 7.6) or
            a role selection not present in ``vocabulary`` (Req 7.3, message lists
            the valid roles).
    """
    file_data: Mapping[str, Any] = (
        _load_yaml(os.fspath(config_path)) if config_path is not None else {}
    )
    cli: Mapping[str, Any] = cli_overrides or {}

    target_repo = _coerce_str(_merged_value("target_repo", file_data, cli), "target_repo")
    out_dir = _coerce_str(_merged_value("out_dir", file_data, cli), "out_dir")
    model = _coerce_str(_merged_value("model", file_data, cli), "model")
    max_cost_usd = _coerce_cost(_merged_value("max_cost_usd", file_data, cli))
    max_steps = _coerce_steps(_merged_value("max_steps", file_data, cli))

    # github-pages-deploy task 4.3: the deploy mode, from the config file overlaid
    # with the CLI override (Req 3.3). A non-string value is malformed input and
    # fails fast (Req 7.6); an absent value falls back to the emit-ci-workflow
    # default (Req 3.2). The string is carried verbatim — its validity against the
    # three supported modes is checked downstream by the deploy-mode resolver.
    deploy_mode = (
        _coerce_str(_merged_value("deploy_mode", file_data, cli), "deploy_mode")
        or _DEFAULT_DEPLOY_MODE
    )

    selected = _coerce_roles(_merged_value("roles", file_data, cli))
    if selected is None:
        # Req 7.2: default to all roles in the loaded Vocabulary — never hardcoded.
        roles = tuple(r.id for r in vocabulary.roles)
    else:
        roles = _validate_roles(selected, vocabulary)

    return DocgenConfig(
        target_repo=target_repo,
        out_dir=out_dir,
        roles=roles,
        model=model,
        max_cost_usd=max_cost_usd,
        max_steps=max_steps,
        deploy_mode=deploy_mode,
    )
