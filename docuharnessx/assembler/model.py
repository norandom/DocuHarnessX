"""The frozen assembled-site value objects and the assembler error hierarchy.

This module is the **data boundary** (design "AssembledSite model") of the Wave 3
``mkdocs-site-assembler`` (task 1.2). It defines the deterministic, model-free value
objects the assembler core computes and the
:class:`~docuharnessx.stages.assemble.AssembleStage` adapter publishes, plus the error
family raised at the stage boundary. It contains pure data and errors only — the
deterministic transforms live in ``identity`` / ``pages`` / ``roles`` /
``mkdocs_config`` / ``writer``, and the harness adapter lives in ``stages/assemble.py``.

It defines the value objects of the assembled-site seam:

* The resolved per-target identity — :class:`SiteIdentity`: the display ``site_name``, the
  ``owner/repo`` ``repo_name``, the remote ``repo_url``, the GitHub project-Pages
  ``site_url``, the ``/<repo>/`` Pages ``base_path``, and the Material ``edit_uri``.
  Computed per-target by ``identity.resolve_site_identity`` from the target git remote +
  overrides; never DocuHarnessX's own identity.
* The **output seam** the Wave 3 ``github-pages-deploy`` consumes verbatim —
  :class:`AssembledSite`: the emitted site source directory, the ``docs/`` directory, the
  ``mkdocs.yml`` path, the resolved :class:`SiteIdentity`, the per-segment page count, the
  per-role landing-page count, and the single :data:`ASSEMBLED_SITE_SCHEMA_VERSION` version
  authority.

Design constraints pinned here (design "AssembledSite model" + "Data Models")
-----------------------------------------------------------------------------
* Both value objects are ``@dataclass(frozen=True)`` so instances are immutable value
  objects that compare by value — deterministic and unit-testable, mirroring
  :mod:`docuharnessx.review.model` and :mod:`docuharnessx.planning.model`.
* Every member is an immutable scalar (``str`` / ``int``) or a frozen value object
  (:class:`AssembledSite` embeds a :class:`SiteIdentity`), so both types are *deeply*
  immutable and therefore hashable; equal inputs yield equal — and equally hashable —
  instances.
* :data:`ASSEMBLED_SITE_SCHEMA_VERSION` is the single version authority for the seam
  (Req 7.3); evolution is additive (new optional fields with defaults), and any change to
  the frozen field set bumps the version and is a revalidation trigger for the
  ``github-pages-deploy`` spec.
* The :class:`AssemblerError` family is kept **independent** of the other specs' error
  families (:class:`~docuharnessx.review.model.ReviewError`,
  :class:`~docuharnessx.composition.model.WriterError`,
  :class:`~docuharnessx.planning.model.PlanningError`), matching how each keeps its error
  family self-contained (design "Error Handling").
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = [
    "ASSEMBLED_SITE_SCHEMA_VERSION",
    "SiteIdentity",
    "AssembledSite",
    "AssemblerError",
    "AssemblerInputError",
]

#: The single schema-version authority for the :class:`AssembledSite` seam. Carried on
#: :attr:`AssembledSite.schema_version`; bumped only when the frozen field set changes
#: (Req 7.3). Any change is a revalidation trigger for the ``github-pages-deploy`` spec.
ASSEMBLED_SITE_SCHEMA_VERSION: int = 1


# --------------------------------------------------------------------------- #
# The resolved per-target site identity                                        #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class SiteIdentity:
    """The resolved per-target site identity (Req 3.1, 3.2, 7.2).

    Computed per-target by ``identity.resolve_site_identity`` from the target's ``origin``
    git remote, the config/flag overrides, and the target directory — never DocuHarnessX's
    own identity (Req 3.8). Every member is an immutable ``str`` (empty string marks an
    absent value, e.g. no remote → empty ``repo_url``/``edit_uri``), so the value object is
    deeply immutable, compares by value, and is hashable.

    * :attr:`site_name` — the display name (override > repo > target-dir basename).
    * :attr:`repo_name` — ``"owner/repo"`` for a GitHub remote, else remote-derived or ``""``.
    * :attr:`repo_url` — the remote URL (``""`` when the target has no remote).
    * :attr:`site_url` — ``"https://<owner>.github.io/<repo>/"`` for a GitHub project Pages
      site, else ``""`` (or an override).
    * :attr:`base_path` — ``"/<repo>/"`` for a GitHub project Pages site, else ``"/"``.
    * :attr:`edit_uri` — the Material ``edit_uri`` (e.g. ``"edit/main/docs/"``) or ``""``.
    """

    site_name: str  # display name (override > repo > target-dir basename)
    repo_name: str  # "owner/repo" for GitHub, else remote-derived or ""
    repo_url: str  # remote URL ("" when no remote)
    site_url: str  # "https://<owner>.github.io/<repo>/" for GitHub project Pages, else ""
    base_path: str  # "/<repo>/" for GitHub project Pages, else "/"
    edit_uri: str  # Material edit_uri (e.g. "edit/main/docs/") or "" when unknown


# --------------------------------------------------------------------------- #
# The output seam (the deploy stage consumes this)                             #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class AssembledSite:
    """The frozen output seam published to ``SLOT_ASSEMBLED_SITE`` (Req 7.1, 7.2, 7.3).

    The stabilized contract the Wave 3 ``github-pages-deploy`` consumes verbatim — built
    by ``writer.assemble_site`` once the deterministic Material for MkDocs source tree is
    written under the run's output directory:

    * :attr:`schema_version` — equals :data:`ASSEMBLED_SITE_SCHEMA_VERSION` (Req 7.3).
    * :attr:`site_dir` — the absolute path to the emitted site root (``<out>/site``).
    * :attr:`docs_dir` — the absolute path to ``<site>/docs``.
    * :attr:`mkdocs_yml_path` — the absolute path to ``<site>/mkdocs.yml``.
    * :attr:`identity` — the resolved per-target :class:`SiteIdentity` (Req 7.2).
    * :attr:`page_count` — the number of per-segment pages emitted.
    * :attr:`role_page_count` — the number of per-role landing pages emitted.

    Invariants (design "Data Models"): ``schema_version == ASSEMBLED_SITE_SCHEMA_VERSION``;
    the paths are absolute. The type is frozen, compares by value, and — embedding only a
    frozen :class:`SiteIdentity` plus ``str``/``int`` scalars — is deeply immutable and
    hashable; equal inputs yield equal instances.
    """

    schema_version: int  # == ASSEMBLED_SITE_SCHEMA_VERSION
    site_dir: str  # absolute path to the emitted site root (<out>/site)
    docs_dir: str  # absolute path to <site>/docs
    mkdocs_yml_path: str  # absolute path to <site>/mkdocs.yml
    identity: SiteIdentity  # the resolved per-target identity
    page_count: int  # number of per-segment pages emitted
    role_page_count: int  # number of per-role landing pages emitted


# --------------------------------------------------------------------------- #
# Assembler error hierarchy                                                    #
# --------------------------------------------------------------------------- #


class AssemblerError(Exception):
    """Base class for every explicit error raised by the assembler core.

    Provides a single catch-all type at the stage boundary while letting each failure path
    raise a specific subclass with an explicit, cause-naming message. Kept independent of
    the other specs' error families (:class:`~docuharnessx.review.model.ReviewError`,
    :class:`~docuharnessx.composition.model.WriterError`,
    :class:`~docuharnessx.planning.model.PlanningError`) so the assembler core stays
    self-contained and harness-free (design "Error Handling").
    """


class AssemblerInputError(AssemblerError):
    """A required assembler input is missing or carries an unsupported contract version.

    Raised at the stage boundary when the ``SLOT_REVIEW_REPORT``, ``SLOT_VOCABULARY``, or
    ``SLOT_OUTPUT_DIR`` slot is unset with a bound run state, or when the consumed
    ``ReviewReport`` declares a ``schema_version`` this build does not support. The message
    names the offending slot/version so the run halts with an identifiable cause and
    produces no partial site (Req 2.3, 2.4, 2.6). Mirrors
    :class:`~docuharnessx.review.model.ReviewInputError`.
    """
