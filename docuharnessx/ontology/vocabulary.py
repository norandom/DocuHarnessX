"""Project-configurable ontology vocabulary (the ``vocabulary`` component).

This module owns four frozen public surfaces (see design.md "Revalidation
Triggers"):

* :class:`Vocabulary` — the loaded value object holding a project's roles,
  intents, and subject prefixes, with deterministic accessors and id-based
  membership checks (Req 2.3, 2.5, 2.6).
* :func:`load_vocabulary` — reads a ``.docuharnessx/ontology.yaml`` config (or an
  already-parsed mapping), resolves an optional ``profile`` base then applies the
  file's explicit overrides, falls back to the default profile when the file is
  absent, and raises :class:`MalformedConfigError` on a present-but-invalid
  config (Req 1.2, 1.3, 1.5, 1.6, 1.7).
* :func:`default_profile` / :func:`default_profile_config` — the shipped preset
  (10 roles, 13 intents, prefixes ``component:``/``tech:``/``artifact:``/
  ``topic:``) as a ``Vocabulary`` and as a serializable seed dict harness-bundle-
  skeleton can write (Req 1.4, 2.1, 2.2). These are *presets*, NOT closed enums.
* :func:`vocabulary_to_config` — the symmetric inverse of :func:`load_vocabulary`:
  serializes any :class:`Vocabulary` to a plain schema dict, deterministically and
  with no file I/O, such that
  ``load_vocabulary(vocabulary_to_config(v)) == v`` (Req 1.9).

This component NEVER prompts the user and NEVER writes the config file (Req 1.8);
the ``dhx init`` ask and persistence belong to harness-bundle-skeleton, which
calls this API.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Mapping, Sequence, Union

import yaml

from docuharnessx.ontology.errors import MalformedConfigError
from docuharnessx.ontology.model import AxisTerm

__all__ = [
    "Vocabulary",
    "load_vocabulary",
    "default_profile",
    "default_profile_config",
    "vocabulary_to_config",
]


# --------------------------------------------------------------------------- #
# Vocabulary value object (Req 2.3, 2.5, 2.6)                                  #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Vocabulary:
    """A project's loaded ontology vocabulary: roles, intents, subject prefixes.

    ``roles`` and ``intents`` are ordered tuples of :class:`AxisTerm` (stable,
    deterministic order derived from the config or default profile; Req 2.3).
    ``subject_prefixes`` is an ordered tuple of the *written* colon form (e.g.
    ``"component:"``) per Req 3.1, kept ordered (not a ``frozenset``) so the
    vocabulary is fully deterministic and round-trips through the config
    serializer (Req 1.9).

    Being a frozen dataclass over hashable tuples gives meaningful structural
    equality, so ``load_vocabulary(vocabulary_to_config(v)) == v`` is testable.
    """

    roles: tuple[AxisTerm, ...]
    intents: tuple[AxisTerm, ...]
    subject_prefixes: tuple[str, ...]

    def has_role(self, role_id: str) -> bool:
        """True when ``role_id`` is a member of this vocabulary (Req 2.5)."""
        return any(r.id == role_id for r in self.roles)

    def has_intent(self, intent_id: str) -> bool:
        """True when ``intent_id`` is a member of this vocabulary (Req 2.5)."""
        return any(i.id == intent_id for i in self.intents)

    def intent_order(self) -> tuple[str, ...]:
        """The documented intent id ordering used for role views (Req 2.6, 10.2)."""
        return tuple(i.id for i in self.intents)


# --------------------------------------------------------------------------- #
# Default profile preset (Req 1.4, 2.1, 2.2)                                   #
# --------------------------------------------------------------------------- #

# The 10 default roles (Req 2.1). Ids are stable machine identifiers distinct
# from the human display labels (Req 2.4); these are a preset seed, not an enum.
_DEFAULT_ROLES: tuple[AxisTerm, ...] = (
    AxisTerm(
        "possible-adopter",
        "Possible Adopter",
        "Evaluating whether to adopt the project.",
    ),
    AxisTerm("developer", "Developer", "Builds on or with the project's code."),
    AxisTerm(
        "tech-savvy-user",
        "Tech-savvy User",
        "Uses the project competently without developing it.",
    ),
    AxisTerm("manager", "Manager", "Owns outcomes, budget, and direction."),
    AxisTerm(
        "devops-admin",
        "DevOps/Admin",
        "Deploys, configures, and administers the project.",
    ),
    AxisTerm(
        "researcher",
        "Researcher",
        "Studies, benchmarks, or extends the project's ideas.",
    ),
    AxisTerm(
        "security-compliance-officer",
        "Security/Compliance Officer",
        "Assesses security, privacy, and compliance posture.",
    ),
    AxisTerm(
        "contributor",
        "Contributor",
        "Contributes changes back to the project.",
    ),
    AxisTerm(
        "integrator",
        "Integrator/API consumer",
        "Integrates the project via its APIs or interfaces.",
    ),
    AxisTerm(
        "support-sre",
        "Support/On-call (SRE)",
        "Operates and supports the project in production.",
    ),
)

# The 13 default intents (Req 2.2), in their canonical default order, which is
# also the role-view ordering (Req 2.6).
_DEFAULT_INTENTS: tuple[AxisTerm, ...] = (
    AxisTerm("install", "Install", "Get the project installed."),
    AxisTerm("configure", "Configure", "Configure the project for a context."),
    AxisTerm("use", "Use", "Use the project for its primary purpose."),
    AxisTerm("troubleshoot", "Troubleshoot", "Diagnose and fix problems."),
    AxisTerm("monitor", "Monitor", "Observe health and behavior."),
    AxisTerm("operate", "Operate", "Run the project day to day."),
    AxisTerm("integrate", "Integrate", "Connect the project to other systems."),
    AxisTerm("extend", "Extend", "Add capabilities or customize behavior."),
    AxisTerm("evaluate", "Evaluate", "Assess fit before adopting."),
    AxisTerm(
        "assess-quality",
        "Assess Quality",
        "Judge quality, security, and compliance.",
    ),
    AxisTerm("understand", "Understand", "Build a mental model of the project."),
    AxisTerm("contribute", "Contribute", "Contribute changes back."),
    AxisTerm("deliver", "Deliver", "Ship outcomes that depend on the project."),
)

# Default subject prefixes (Req 1.4) in the written colon form (Req 3.1).
_DEFAULT_PREFIXES: tuple[str, ...] = ("component:", "tech:", "artifact:", "topic:")


def default_profile() -> Vocabulary:
    """Return the shipped preset :class:`Vocabulary` (Req 1.4, 2.1, 2.2).

    A preset, NOT a closed enumeration: a project may override or extend it via
    its own config. Deterministic — repeated calls compare equal.
    """
    return Vocabulary(
        roles=_DEFAULT_ROLES,
        intents=_DEFAULT_INTENTS,
        subject_prefixes=_DEFAULT_PREFIXES,
    )


def default_profile_config() -> dict:
    """Return the default profile as a serializable seed dict (Req 1.4).

    harness-bundle-skeleton writes this as the initial ``.docuharnessx/
    ontology.yaml``. It matches the config schema and round-trips through
    :func:`load_vocabulary`. This function performs no file I/O or prompting.
    """
    return vocabulary_to_config(default_profile())


# A registry of resolvable named profiles for the ``profile`` reference (Req 1.5).
_PROFILES: dict[str, "Vocabulary"] = {}


def _profiles() -> dict[str, Vocabulary]:
    # Built lazily so ``default_profile()`` is the single source of truth.
    if not _PROFILES:
        _PROFILES["default"] = default_profile()
    return _PROFILES


# --------------------------------------------------------------------------- #
# Config <-> Vocabulary serialization (Req 1.1, 1.9)                           #
# --------------------------------------------------------------------------- #


def _term_to_dict(term: AxisTerm) -> dict:
    return {"id": term.id, "label": term.label, "description": term.description}


def vocabulary_to_config(vocab: Vocabulary) -> dict:
    """Serialize a :class:`Vocabulary` to a plain ``ontology.yaml``-schema dict.

    The symmetric inverse of :func:`load_vocabulary` (Req 1.9): deterministic,
    no file I/O, no prompting. ``load_vocabulary(vocabulary_to_config(v)) == v``
    holds for both the default profile and an arbitrarily-built vocabulary.

    Subject prefixes are emitted in their written colon form (Req 3.1).
    """
    return {
        "roles": [_term_to_dict(r) for r in vocab.roles],
        "intents": [_term_to_dict(i) for i in vocab.intents],
        "subjects": list(vocab.subject_prefixes),
    }


def _coerce_terms(
    raw: Any, axis: str, config_path: str
) -> tuple[AxisTerm, ...]:
    """Coerce a raw ``roles``/``intents`` config list into ``AxisTerm`` tuple."""
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        raise MalformedConfigError(
            config_path, reason=f"'{axis}' must be a list of entries"
        )
    terms: list[AxisTerm] = []
    for entry in raw:
        if not isinstance(entry, Mapping):
            raise MalformedConfigError(
                config_path, reason=f"each '{axis}' entry must be a mapping"
            )
        if "id" not in entry or not entry["id"]:
            raise MalformedConfigError(
                config_path, reason=f"each '{axis}' entry requires an 'id'"
            )
        term_id = str(entry["id"])
        label = str(entry.get("label", term_id))
        description = str(entry.get("description", "") or "")
        terms.append(AxisTerm(id=term_id, label=label, description=description))
    return tuple(terms)


def _coerce_prefixes(raw: Any, config_path: str) -> tuple[str, ...]:
    """Coerce a raw ``subjects`` config list into an ordered prefix tuple."""
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        raise MalformedConfigError(
            config_path, reason="'subjects' must be a list of prefixes"
        )
    prefixes: list[str] = []
    for value in raw:
        if not isinstance(value, str) or not value.strip():
            raise MalformedConfigError(
                config_path, reason="each subject prefix must be a non-empty string"
            )
        prefixes.append(value.strip())
    return tuple(prefixes)


def _merge_terms(
    base: tuple[AxisTerm, ...], overrides: tuple[AxisTerm, ...]
) -> tuple[AxisTerm, ...]:
    """Apply ``overrides`` onto ``base``: same-id replaces in place, new appended.

    Order is deterministic (Req 1.5, 1.7): base order is preserved for inherited
    and overridden terms; genuinely new terms are appended in their config order.
    """
    by_id = {t.id: t for t in base}
    order = [t.id for t in base]
    for term in overrides:
        if term.id not in by_id:
            order.append(term.id)
        by_id[term.id] = term
    return tuple(by_id[tid] for tid in order)


def _vocabulary_from_config(data: Mapping[str, Any], config_path: str) -> Vocabulary:
    """Build a :class:`Vocabulary` from an already-parsed config mapping."""
    if not isinstance(data, Mapping):
        raise MalformedConfigError(
            config_path, reason="config root must be a mapping"
        )

    profile_ref = data.get("profile")
    if profile_ref is not None:
        if not isinstance(profile_ref, str) or profile_ref not in _profiles():
            raise MalformedConfigError(
                config_path, reason=f"unknown profile reference '{profile_ref}'"
            )
        base = _profiles()[profile_ref]
        base_roles, base_intents, base_prefixes = (
            base.roles,
            base.intents,
            base.subject_prefixes,
        )
    else:
        base_roles = base_intents = ()
        base_prefixes = ()

    # Without a profile base, all three sections are required (Req 1.6); with a
    # profile base, any omitted section is inherited from the base.
    if profile_ref is None:
        for key in ("roles", "intents", "subjects"):
            if key not in data:
                raise MalformedConfigError(
                    config_path, reason=f"missing required key '{key}'"
                )

    roles = (
        _merge_terms(base_roles, _coerce_terms(data["roles"], "roles", config_path))
        if "roles" in data
        else base_roles
    )
    intents = (
        _merge_terms(
            base_intents, _coerce_terms(data["intents"], "intents", config_path)
        )
        if "intents" in data
        else base_intents
    )
    prefixes = (
        _coerce_prefixes(data["subjects"], config_path)
        if "subjects" in data
        else base_prefixes
    )

    return Vocabulary(roles=roles, intents=intents, subject_prefixes=prefixes)


def load_vocabulary(
    config_path: Union[str, os.PathLike[str], Mapping[str, Any]],
) -> Vocabulary:
    """Load a :class:`Vocabulary` from a config file path or a parsed mapping.

    * If ``config_path`` is a mapping, it is treated as an already-parsed config
      (this is the path :func:`vocabulary_to_config` round-trips through; Req 1.9).
    * If it is a path to an existing file, the YAML is read via ``yaml.safe_load``
      (Req 1.2). An optional ``profile`` reference resolves a base vocabulary that
      the file's explicit entries extend or override (Req 1.5).
    * If the path does not exist, the shipped default profile is returned rather
      than failing (Req 1.3).
    * A present-but-invalid config (unparseable YAML or missing required keys)
      raises :class:`MalformedConfigError` identifying the offending config
      (Req 1.6).

    Loading is deterministic: identical input always yields an identical
    ``Vocabulary`` (Req 1.7, 11.4).
    """
    # Already-parsed mapping (round-trip path).
    if isinstance(config_path, Mapping):
        return _vocabulary_from_config(config_path, config_path="<dict>")

    path = os.fspath(config_path)

    if not os.path.exists(path):
        # Missing file -> default profile fallback (Req 1.3).
        return default_profile()

    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle)
    except yaml.YAMLError as exc:
        raise MalformedConfigError(path, reason=f"unparseable YAML: {exc}") from exc
    except OSError as exc:  # pragma: no cover - filesystem edge
        raise MalformedConfigError(path, reason=f"unreadable config: {exc}") from exc

    if data is None:
        raise MalformedConfigError(path, reason="config file is empty")

    return _vocabulary_from_config(data, config_path=path)
