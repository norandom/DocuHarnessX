"""Project glossary: seed, load/merge, persist."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import yaml

from docuharnessx.analysis.model import RepoAnalysis
from docuharnessx.errors import OntologyConfigError
from docuharnessx.ontology import Vocabulary

__all__ = [
    "GLOSSARY_RELPATH",
    "Glossary",
    "GlossaryTerm",
    "load_glossary",
    "merge_glossary",
    "save_glossary",
    "seed_glossary",
]

GLOSSARY_RELPATH = os.path.join(".docuharnessx", "glossary.yaml")

_SLUG = re.compile(r"[^a-z0-9]+")


def _slug(text: str) -> str:
    value = _SLUG.sub("-", text.strip().casefold()).strip("-")
    return value or "term"


@dataclass(frozen=True)
class GlossaryTerm:
    id: str
    label: str
    aliases: tuple[str, ...] = ()
    definition: str = ""
    related: tuple[str, ...] = ()
    sources: tuple[str, ...] = ()


@dataclass(frozen=True)
class Glossary:
    terms: tuple[GlossaryTerm, ...] = ()

    def by_id(self) -> dict[str, GlossaryTerm]:
        return {term.id: term for term in self.terms}


def seed_glossary(
    vocab: Vocabulary | None,
    analysis: RepoAnalysis | None,
) -> Glossary:
    terms: dict[str, GlossaryTerm] = {}

    def add(label: str, source: str, definition: str = "") -> None:
        tid = _slug(label)
        if not tid or len(tid) < 2:
            return
        if source.startswith("surface:") and (
            "_" in label
            or label.isupper()
            or (
                " " not in label
                and any(c.islower() for c in label)
                and any(c.isupper() for c in label)
            )
        ):
            return
        if source.startswith("component:") and (
            "test" in source or "fixture" in source
        ):
            return
        current = terms.get(tid)
        sources = (source,)
        if current is not None:
            sources = tuple(dict.fromkeys((*current.sources, source)))
            definition = current.definition or definition
            label = current.label
        terms[tid] = GlossaryTerm(
            id=tid,
            label=label,
            definition=definition,
            sources=sources,
        )

    if vocab is not None:
        for role in vocab.roles:
            add(role.label or role.id, "ontology:role", role.description)
        for intent in vocab.intents:
            add(intent.label or intent.id, "ontology:intent", intent.description)
        for prefix in vocab.subject_prefixes:
            add(prefix.rstrip(":"), "ontology:subject")
    if analysis is not None:
        for component in analysis.components:
            add(component.name, f"component:{component.path}")
        for symbol in analysis.public_surface:
            add(symbol.name, f"surface:{symbol.source}")
    ordered = tuple(terms[key] for key in sorted(terms))
    return Glossary(terms=ordered)


def load_glossary(project_dir: str) -> Glossary:
    path = os.path.join(project_dir, GLOSSARY_RELPATH)
    if not os.path.isfile(path):
        return Glossary()
    with open(path, "r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if data is None:
        return Glossary()
    if not isinstance(data, Mapping):
        raise OntologyConfigError(
            f"invalid glossary config '{path}': mapping required"
        )
    raw_terms = data.get("terms", ())
    if not isinstance(raw_terms, Sequence) or isinstance(raw_terms, (str, bytes)):
        raise OntologyConfigError(
            f"invalid glossary config '{path}': 'terms' must be a list"
        )
    terms: list[GlossaryTerm] = []
    for entry in raw_terms:
        if not isinstance(entry, Mapping):
            raise OntologyConfigError(
                f"invalid glossary config '{path}': each term must be a mapping"
            )
        tid = str(entry.get("id") or _slug(str(entry.get("label", ""))))
        terms.append(
            GlossaryTerm(
                id=tid,
                label=str(entry.get("label", tid)),
                aliases=tuple(str(a) for a in entry.get("aliases", ()) or ()),
                definition=str(entry.get("definition", "") or ""),
                related=tuple(str(r) for r in entry.get("related", ()) or ()),
                sources=tuple(str(s) for s in entry.get("sources", ()) or ()),
            )
        )
    terms.sort(key=lambda t: t.id)
    return Glossary(terms=tuple(terms))


def merge_glossary(seed: Glossary, operator: Glossary) -> Glossary:
    """Operator wins on definition and aliases; related/sources are unioned."""
    merged: dict[str, GlossaryTerm] = {term.id: term for term in seed.terms}
    for term in operator.terms:
        current = merged.get(term.id)
        if current is None:
            merged[term.id] = term
            continue
        merged[term.id] = GlossaryTerm(
            id=term.id,
            label=term.label or current.label,
            aliases=tuple(dict.fromkeys((*term.aliases, *current.aliases))),
            definition=term.definition if term.definition else current.definition,
            related=tuple(dict.fromkeys((*term.related, *current.related))),
            sources=tuple(dict.fromkeys((*current.sources, *term.sources))),
        )
    return Glossary(terms=tuple(merged[key] for key in sorted(merged)))


def save_glossary(project_dir: str, glossary: Glossary) -> str:
    path = os.path.join(project_dir, GLOSSARY_RELPATH)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    payload: dict[str, Any] = {
        "terms": [
            {
                "id": term.id,
                "label": term.label,
                "aliases": list(term.aliases),
                "definition": term.definition,
                "related": list(term.related),
                "sources": list(term.sources),
            }
            for term in glossary.terms
        ]
    }
    with open(path, "w", encoding="utf-8") as handle:
        yaml.safe_dump(payload, handle, sort_keys=False, allow_unicode=True)
    return path
