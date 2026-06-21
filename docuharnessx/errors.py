"""Explicit, typed error hierarchy for the DocuHarnessX skeleton.

The skeleton's error strategy is *fail fast at boundaries with explicit, typed
errors mapped to non-zero CLI exit codes*; every failure path surfaces a message
naming the cause (design "Error Handling"). Each error below is raised at a
specific boundary and later mapped to a non-zero exit code by the CLI:

* :class:`ConfigError` — malformed/unknown ``--config`` setting, or a role
  selection not present in the loaded ``Vocabulary`` (Req 7.3, 7.6).
* :class:`ModelResolutionError` — no model resolvable from config or environment
  (Req 3.4).
* :class:`TargetRepoError` — target-repository path missing or not a directory,
  raised *before* any run starts (Req 4.7).
* :class:`DependencyError` — a required runtime dependency is unavailable at
  import time, named explicitly rather than failing silently (Req 1.4).
* :class:`OntologyConfigError` — a present ``.docuharnessx/ontology.yaml`` fails
  to load against the ``ontology-engine`` loader (Req 10.4). A *missing* file is
  not an error: the run falls back to the default profile (Req 10.3).

All of these derive from :class:`DocuHarnessXError` so callers can catch the
whole family at the CLI boundary while still distinguishing causes. This module
defines errors only — it owns no behavior, configuration, or ontology logic
(task 1.2 boundary: types, errors).
"""

from __future__ import annotations

__all__ = [
    "DocuHarnessXError",
    "ConfigError",
    "ModelResolutionError",
    "TargetRepoError",
    "DependencyError",
    "OntologyConfigError",
]


class DocuHarnessXError(Exception):
    """Base class for all explicit DocuHarnessX skeleton errors.

    Provides a single catch-all type at the CLI boundary while letting each
    failure path raise a specific subclass with an explicit, cause-naming
    message.
    """


class ConfigError(DocuHarnessXError):
    """Configuration is malformed, has an unknown setting, or names an invalid role.

    Raised when a ``--config`` file is malformed or contains an unknown key
    (Req 7.6), or when a role selection (via ``--roles`` or the config file)
    names a role not present in the loaded ``Vocabulary``; in the latter case the
    message lists the valid roles (Req 7.3).
    """


class ModelResolutionError(DocuHarnessXError):
    """No model could be resolved from configuration or environment.

    Raised by the model resolver when neither the configured model identifier nor
    the provider environment variables yield a usable model (Req 3.4).
    """


class TargetRepoError(DocuHarnessXError):
    """The target-repository path is missing or is not a directory.

    Raised before any run starts so an invalid target aborts cleanly with an
    explicit message identifying the bad path (Req 4.7).
    """


class DependencyError(DocuHarnessXError):
    """A required runtime dependency is unavailable at import time.

    Raised (rather than failing silently with an opaque ``ImportError``) with a
    message naming the missing dependency and how to install it (Req 1.4).
    """


class OntologyConfigError(DocuHarnessXError):
    """A present ``.docuharnessx/ontology.yaml`` failed to load.

    Raised when the per-project ontology file exists but the ``ontology-engine``
    loader rejects it; the message identifies the invalid vocabulary file
    (Req 10.4). An *absent* file is not an error — the run falls back to the
    default profile (Req 10.3).
    """
