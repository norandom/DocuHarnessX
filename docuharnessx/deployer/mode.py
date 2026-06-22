"""The deterministic deploy-mode resolver (github-pages-deploy task 2.1).

This module is the *Deploy-mode resolver* (design "Deploy-mode resolver") of the Wave 3
``github-pages-deploy`` pure core. It maps the operator-selected mode value
(``DocgenConfig.deploy_mode`` / the ``--deploy-mode`` flag, threaded through to the
:class:`~docuharnessx.stages.deploy.DeployStage`, or ``None``/blank when unset) onto one of
the three supported :data:`~docuharnessx.deployer.model.DeployMode` literals, applying the
default and validating the configured value:

* absent / empty / whitespace-only → ``"emit-ci-workflow"`` (the default — Req 3.2);
* a recognised value → that value, trimmed of surrounding whitespace (Req 3.3);
* any other value → :class:`~docuharnessx.deployer.model.DeployInputError` naming the bad
  value and the three valid modes, performing no deploy action (Req 3.4).

It is pure, total, and deterministic — model-free and process-free — so the mode selection
is unit-testable in isolation. It depends only on the frozen
:mod:`docuharnessx.deployer.model` (the :data:`DeployMode` literal set and the
:class:`DeployInputError` family), never on the harness, ``subprocess``, or the consumed
:class:`~docuharnessx.assembler.model.AssembledSite`. The valid-mode set is derived from
the :data:`DeployMode` literal itself (a single source of truth) so adding a mode upstream
flows through here without an edit.
"""

from __future__ import annotations

import typing

from docuharnessx.deployer.model import DeployInputError, DeployMode

__all__ = [
    "resolve_deploy_mode",
]

#: The default deploy mode used when no mode is configured (Req 3.2): write the assembled
#: ``mkdocs.yml`` + ``docs/`` + a ``.github/workflows/docs.yml`` build-and-deploy-pages
#: workflow into the *target* working tree, with no push/commit (Req 4).
_DEFAULT_MODE: DeployMode = "emit-ci-workflow"

#: The supported deploy modes (Req 3.1), derived from the :data:`DeployMode` literal so the
#: resolver and the model share one source of truth. A ``frozenset`` for O(1) membership;
#: the deterministic, source-ordered tuple :data:`_VALID_MODES` backs the error message.
_VALID_MODES: tuple[str, ...] = typing.get_args(DeployMode)
_VALID_MODE_SET: frozenset[str] = frozenset(_VALID_MODES)


def resolve_deploy_mode(configured: "str | None") -> DeployMode:
    """Resolve the operator-selected deploy mode to a supported :data:`DeployMode`.

    Args:
        configured: The configured mode value from the configuration surface
            (``DocgenConfig.deploy_mode`` / ``--deploy-mode``), or ``None``/blank when the
            operator did not configure one. A blank or whitespace-only string is treated as
            "no mode configured" (mirroring :func:`docuharnessx.model_resolver.resolve_model`),
            so an empty YAML/flag value falls through to the default. Surrounding whitespace
            on a real value is trimmed before matching.

    Returns:
        The resolved :data:`DeployMode`: :data:`_DEFAULT_MODE` (``"emit-ci-workflow"``) when
        ``configured`` is absent/empty (Req 3.2), otherwise the recognised configured value
        unchanged (Req 3.3). Pure, total, deterministic.

    Raises:
        DeployInputError: When ``configured`` is a non-empty value that is not one of the
            three supported modes (Req 3.4). The message names the offending value and the
            valid modes so the run halts with an identifiable cause and performs no deploy
            action; this surfaces at the stage boundary like the other fatal-input paths.
    """
    if configured is None:
        return _DEFAULT_MODE

    candidate = configured.strip()
    if not candidate:
        return _DEFAULT_MODE

    if candidate in _VALID_MODE_SET:
        return typing.cast(DeployMode, candidate)

    valid = ", ".join(_VALID_MODES)
    raise DeployInputError(
        f"Unsupported deploy mode {candidate!r}. "
        f"Valid deploy modes are: {valid}."
    )
