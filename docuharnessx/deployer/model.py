"""The frozen deploy value object and the deploy error hierarchy.

This module is the **data boundary** (design "DeployResult model") of the Wave 3
``github-pages-deploy`` (task 1.1). It defines the deterministic, model-free value object
the deploy core (the orchestrator in ``deploy``) builds and the
:class:`~docuharnessx.stages.deploy.DeployStage` adapter publishes to
``SLOT_DEPLOY_RESULT`` and journals, plus the error family raised at the stage boundary.
It contains pure data and errors only — the deterministic transforms live in ``mode`` /
``workflow`` / ``tree`` / ``commands`` / ``deploy`` (later tasks), and the harness adapter
lives in ``stages/deploy.py``.

It defines the value objects of the deploy seam:

* The supported deploy modes — :data:`DeployMode`: ``"emit-ci-workflow"`` (the default;
  write ``mkdocs.yml`` + ``docs/`` + ``.github/workflows/docs.yml`` into the target tree,
  no push), ``"gh-deploy"`` (push the built site to the target ``gh-pages`` branch — the
  only network action), and ``"build-only"`` (build the static site, no publish).
* The deploy outcome — :data:`DeployStatus`: ``"emitted"`` (emit-ci-workflow), ``"built"``
  (build-only), ``"published"`` (gh-deploy), and ``"failed"`` (a failed build/push).
* The **output seam** recorded in the journal / ``SLOT_DEPLOY_RESULT`` —
  :class:`DeployResult`: the resolved deploy mode, the deploy status, the per-target Pages
  URL (``AssembledSite.identity.site_url``), the files written into the target tree (emit
  mode), the static-site dir produced by ``mkdocs build``, a one-line human-readable
  detail, and the single :data:`DEPLOY_RESULT_SCHEMA_VERSION` version authority.

Design constraints pinned here (design "DeployResult model" + "Data Models")
----------------------------------------------------------------------------
* :class:`DeployResult` is a ``@dataclass(frozen=True)`` so instances are immutable value
  objects that compare by value — deterministic and unit-testable, mirroring
  :mod:`docuharnessx.assembler.model` and :mod:`docuharnessx.review.model`.
* Every member is an immutable scalar (``str`` / ``int``) or a ``tuple`` of strings
  (``written_paths``), never a ``list``, so the type is *deeply* immutable and therefore
  hashable; equal inputs yield equal — and equally hashable — instances. The detail is a
  one-line summary and never carries page bodies (Req 8.2).
* :data:`DEPLOY_RESULT_SCHEMA_VERSION` is the single version authority for the seam
  (Req 8.3); evolution is additive (new optional fields with defaults), and any change to
  the frozen field set bumps the version and is a revalidation trigger for any downstream
  consumer.
* The :class:`DeployError` family is kept **independent** of the other specs' error
  families (:class:`~docuharnessx.assembler.model.AssemblerError`,
  :class:`~docuharnessx.review.model.ReviewError`,
  :class:`~docuharnessx.composition.model.WriterError`,
  :class:`~docuharnessx.planning.model.PlanningError`), matching how each keeps its error
  family self-contained (design "Error Handling").
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

__all__ = [
    "DEPLOY_RESULT_SCHEMA_VERSION",
    "DeployMode",
    "DeployStatus",
    "DeployResult",
    "DeployError",
    "DeployInputError",
]

#: The single schema-version authority for the :class:`DeployResult` seam. Carried on
#: :attr:`DeployResult.schema_version`; bumped only when the frozen field set changes
#: (Req 8.3). Any change is a revalidation trigger for any downstream consumer.
DEPLOY_RESULT_SCHEMA_VERSION: int = 1

#: The three supported deploy modes (Req 3.1). ``"emit-ci-workflow"`` is the default
#: (Req 3.2): write the assembled ``mkdocs.yml`` + ``docs/`` + a
#: ``.github/workflows/docs.yml`` build-and-deploy-pages workflow into the *target*
#: working tree, with no push/commit (Req 4). ``"gh-deploy"`` runs ``mkdocs gh-deploy`` to
#: push the built site to the target ``gh-pages`` branch — the only network action
#: (Req 5). ``"build-only"`` runs ``mkdocs build`` to produce the static site with no
#: publish (Req 6).
DeployMode = Literal["emit-ci-workflow", "gh-deploy", "build-only"]

#: The deploy outcome carried on :attr:`DeployResult.status`: ``"emitted"`` for the
#: emit-ci-workflow mode, ``"built"`` for build-only, ``"published"`` for gh-deploy, and
#: ``"failed"`` when a build/push failed (the orchestrator records the cause in
#: :attr:`DeployResult.detail`).
DeployStatus = Literal["emitted", "built", "published", "failed"]


# --------------------------------------------------------------------------- #
# The output seam (the deploy stage publishes / journals this)                 #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class DeployResult:
    """The frozen output seam published to ``SLOT_DEPLOY_RESULT`` and journaled (Req 8.1).

    Built solely by the deploy orchestrator (``deployer.deploy.deploy_site``, a later task)
    from validated inputs, and published verbatim by the
    :class:`~docuharnessx.stages.deploy.DeployStage` adapter:

    * :attr:`schema_version` — equals :data:`DEPLOY_RESULT_SCHEMA_VERSION` (Req 8.3).
    * :attr:`mode` — the resolved :data:`DeployMode` for this run.
    * :attr:`status` — the :data:`DeployStatus` outcome.
    * :attr:`target_pages_url` — the per-target Pages URL (``AssembledSite.identity.site_url``;
      ``""`` when unknown), never DocuHarnessX's own (Req 9.2).
    * :attr:`written_paths` — the absolute paths written into the target tree in
      emit-ci-workflow mode (``mkdocs.yml`` + ``docs/`` + the workflow file); ``()`` for the
      build-only / gh-deploy modes.
    * :attr:`built_path` — the absolute static-site dir produced by ``mkdocs build``
      (``""`` when not built).
    * :attr:`detail` — a one-line human-readable outcome/cause; never page bodies (Req 8.2).

    Invariants (design "Data Models"): ``schema_version == DEPLOY_RESULT_SCHEMA_VERSION``;
    paths are absolute when present; ``status == "failed"`` ⇒ the orchestrator recorded the
    :class:`DeployError` cause in :attr:`detail`, and a non-failed status means the mode's
    action completed. The type is frozen, compares by value, and — carrying only ``str`` /
    ``int`` scalars plus a ``tuple`` of strings — is deeply immutable and hashable; equal
    inputs yield equal instances.
    """

    schema_version: int  # == DEPLOY_RESULT_SCHEMA_VERSION
    mode: DeployMode  # the resolved deploy mode
    status: DeployStatus  # outcome of this run
    target_pages_url: str  # AssembledSite.identity.site_url ("" when unknown)
    written_paths: tuple[str, ...]  # files written into the target tree (emit mode); () otherwise
    built_path: str  # static-site dir produced by mkdocs build ("" when not built)
    detail: str  # one-line human-readable outcome/cause (no page bodies)


# --------------------------------------------------------------------------- #
# Deploy error hierarchy                                                       #
# --------------------------------------------------------------------------- #


class DeployError(Exception):
    """Base class for every explicit error raised by the deploy core.

    Provides a single catch-all type at the stage boundary while letting each failure path
    raise a specific subclass with an explicit, cause-naming message (a failed
    ``mkdocs build`` / ``mkdocs gh-deploy``, or a missing gh-deploy prerequisite — Req 5.3,
    7.3). Kept independent of the other specs' error families
    (:class:`~docuharnessx.assembler.model.AssemblerError`,
    :class:`~docuharnessx.review.model.ReviewError`,
    :class:`~docuharnessx.composition.model.WriterError`,
    :class:`~docuharnessx.planning.model.PlanningError`) so the deploy core stays
    self-contained and harness-free (design "Error Handling").
    """


class DeployInputError(DeployError):
    """A required deploy input is missing, unsupported, or the configured mode is invalid.

    Raised at the stage boundary when the ``SLOT_ASSEMBLED_SITE``, ``SLOT_OUTPUT_DIR``, or
    ``SLOT_TARGET_REPO`` slot is unset with a bound run state, when the consumed
    ``AssembledSite`` declares a ``schema_version`` this build does not support, or when the
    configured deploy mode is not one of the three supported modes. The message names the
    offending slot/version/mode (and, for a bad mode, the valid modes) so the run halts with
    an identifiable cause and performs no deploy action (Req 2.3, 2.4, 2.5, 3.4). Mirrors
    :class:`~docuharnessx.assembler.model.AssemblerInputError`.
    """
