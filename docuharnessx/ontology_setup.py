"""``dhx init`` ontology setup helpers (task 2.7 boundary).

This module owns the ``OntologySetup`` service: a single function,
:func:`run_init`, that the ``dhx init`` subcommand calls to create a per-project
``.docuharnessx/ontology.yaml`` (design "OntologySetup (dhx init)"; Req 9.1-9.6).

What this module owns vs. delegates
-----------------------------------
The skeleton owns **only the file write** (Req 9.4). Everything ontology-schema-
shaped is delegated to ``ontology-engine``:

* the :class:`Vocabulary` value object and the shipped ``default_profile()``
  preset (Req 9.3) — imported, never redefined;
* the schema serialization ``vocabulary_to_config(vocab) -> dict`` (Req 9.4) —
  the skeleton never assembles the ``ontology.yaml`` schema itself;
* the loader ``load_vocabulary`` used to round-trip-validate the written file
  (Req 9.5).

Flow (design "dhx init ontology setup")
---------------------------------------
1. Resolve the target ``<project_dir>/.docuharnessx/ontology.yaml`` path (Req 9.1)
   and refuse to overwrite a present file unless ``force=True`` (Req 9.6).
2. Build a :class:`Vocabulary` — from the shipped default profile when
   ``use_default`` is set or no ``answers`` are supplied (Req 9.3), or from the
   interactive ``answers`` (roles, intents, tags/subjects) otherwise (Req 9.2).
3. Convert it to a config dict via the engine's ``vocabulary_to_config`` and dump
   that dict to YAML at the resolved path (Req 9.4).
4. Round-trip-load the written file via the engine's ``load_vocabulary`` to prove
   it is a valid vocabulary file (Req 9.5), then return its path.

Revalidation trigger (recorded risk): a change to the ``Vocabulary`` model, the
``vocabulary_to_config`` / ``default_profile`` / ``load_vocabulary`` signatures,
or the ``.docuharnessx/ontology.yaml`` schema must be re-validated here.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

import yaml

from docuharnessx._ontology import (
    Vocabulary,
    default_profile,
    load_vocabulary,
    vocabulary_to_config,
)
from docuharnessx.ontology import AxisTerm

__all__ = ["run_init", "VocabularyAnswers", "ONTOLOGY_CONFIG_RELPATH"]

# The canonical per-project ontology config location, relative to a project dir.
# ``dhx init`` writes here and run-start loading (``ontology_loader``) reads from
# here (Req 9.1, 10.1). Kept in lockstep with ``ontology_loader.ONTOLOGY_CONFIG_RELPATH``.
ONTOLOGY_CONFIG_RELPATH = os.path.join(".docuharnessx", "ontology.yaml")


@dataclass(frozen=True)
class VocabularyAnswers:
    """The operator's interactive ``dhx init`` answers (Req 9.2).

    A lightweight transport DTO carrying the three axes the operator is asked
    about — roles, intents, and tags/subjects — which :func:`run_init` assembles
    into an ``ontology-engine`` :class:`Vocabulary`. This is the ONLY type this
    module defines; it deliberately reuses the engine's :class:`AxisTerm` for the
    role/intent terms rather than introducing a parallel schema.

    ``subject_prefixes`` carries the written colon form (e.g. ``"component:"``),
    matching the form the engine serializes and loads.
    """

    roles: tuple[AxisTerm, ...] = field(default_factory=tuple)
    intents: tuple[AxisTerm, ...] = field(default_factory=tuple)
    subject_prefixes: tuple[str, ...] = field(default_factory=tuple)


def _terms_from_raw(raw: Any) -> tuple[AxisTerm, ...]:
    """Coerce an answer axis (``AxisTerm``s or plain ``id``/``label`` dicts)."""
    terms: list[AxisTerm] = []
    for entry in raw:
        if isinstance(entry, AxisTerm):
            terms.append(entry)
        elif isinstance(entry, Mapping):
            term_id = str(entry["id"])
            terms.append(
                AxisTerm(
                    id=term_id,
                    label=str(entry.get("label", term_id)),
                    description=str(entry.get("description", "") or ""),
                )
            )
        else:  # pragma: no cover - defensive
            raise TypeError(
                f"each role/intent answer must be an AxisTerm or mapping, got {entry!r}"
            )
    return tuple(terms)


def _vocabulary_from_answers(answers: VocabularyAnswers | Mapping[str, Any]) -> Vocabulary:
    """Assemble an ``ontology-engine`` :class:`Vocabulary` from operator answers.

    Accepts either a :class:`VocabularyAnswers` DTO or a plain mapping with
    ``roles``/``intents``/``subjects`` keys (Req 9.2). The skeleton only marshals
    the answers into the engine's ``Vocabulary`` — it does not assemble the config
    schema (that is ``vocabulary_to_config``'s job).
    """
    if isinstance(answers, VocabularyAnswers):
        return Vocabulary(
            roles=tuple(answers.roles),
            intents=tuple(answers.intents),
            subject_prefixes=tuple(answers.subject_prefixes),
        )
    if isinstance(answers, Mapping):
        subjects = answers.get("subjects", answers.get("subject_prefixes", ()))
        if isinstance(subjects, (str, bytes)) or not isinstance(subjects, Sequence):
            raise TypeError("'subjects' answers must be a list of prefix strings")
        return Vocabulary(
            roles=_terms_from_raw(answers.get("roles", ())),
            intents=_terms_from_raw(answers.get("intents", ())),
            subject_prefixes=tuple(str(s) for s in subjects),
        )
    raise TypeError(
        f"answers must be a VocabularyAnswers or mapping, got {type(answers)!r}"
    )


def run_init(
    project_dir: str,
    *,
    use_default: bool = False,
    force: bool = False,
    answers: VocabularyAnswers | Mapping[str, Any] | None = None,
) -> str:
    """Create ``<project_dir>/.docuharnessx/ontology.yaml`` and return its path.

    Builds a :class:`Vocabulary` from the shipped default profile (when
    ``use_default`` is set or no ``answers`` are given; Req 9.3) or from the
    interactive ``answers`` (Req 9.2), serializes it via the ``ontology-engine``
    ``vocabulary_to_config`` API, writes the resulting dict as YAML (Req 9.4),
    round-trip-validates it via ``load_vocabulary`` (Req 9.5), and returns the
    written path.

    Refuses to overwrite an existing config unless ``force=True``, raising
    :class:`FileExistsError` naming the file (Req 9.6).

    Raises :class:`ValueError` when neither ``use_default`` nor ``answers`` is
    supplied (there is nothing to build).
    """
    config_path = os.path.join(project_dir, ONTOLOGY_CONFIG_RELPATH)

    # Req 9.6 — never overwrite silently; require an explicit --force.
    if os.path.exists(config_path) and not force:
        raise FileExistsError(
            f"ontology config already exists: '{config_path}' "
            "(pass force=True / --force to overwrite)"
        )

    # Build the Vocabulary. Default profile when the operator requests it (Req
    # 9.3); otherwise assemble from the interactive answers (Req 9.2). Requiring
    # an explicit signal keeps the caller honest: forgetting to gather answers
    # must not silently fall through to the default profile.
    if use_default:
        vocab = default_profile()
    elif answers is not None:
        vocab = _vocabulary_from_answers(answers)
    else:
        raise ValueError(
            "run_init requires either use_default=True or interactive answers "
            "to build a vocabulary"
        )

    # Req 9.4 — delegate schema serialization to the engine; the skeleton only
    # dumps the returned dict to disk. We never assemble the schema ourselves.
    config_dict = vocabulary_to_config(vocab)

    os.makedirs(os.path.dirname(config_path), exist_ok=True)
    with open(config_path, "w", encoding="utf-8") as handle:
        yaml.safe_dump(config_dict, handle, sort_keys=False, allow_unicode=True)

    # Req 9.5 — prove validity by round-trip-loading via the engine loader.
    load_vocabulary(config_path)

    return config_path
