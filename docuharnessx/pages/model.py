"""Frozen page and omission values the explore-first pipeline emits.

This module is the **model boundary** of accepted documentation pages (task 1.2).
It defines ``Page``, ``Omission``, and the closed-set ``OmissionReason``. Run
report serialize lives in :mod:`docuharnessx.pipeline.report`.

Design constraints (design "Pages and site — Page" / "Data Models" / "RunReport")
---------------------------------------------------------------------------------
* Every value object is a ``@dataclass(frozen=True)`` so instances compare by
  value and cannot be mutated.
* Collection fields are ``tuple[...]`` (never ``list``) so instances are
  deeply immutable and hashable.
* ``Page`` is a slim accepted document: id, title, summary, body, subjects,
  related, cited files. It carries **no** ``roles`` or ``intent`` (Req 1.4,
  10.3).
* ``Page.id`` is a planned question id (``{kind}:{slug}``).
* ``Omission`` is only a question id plus a closed-set reason (Req 9.2).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

__all__ = [
    "Omission",
    "OmissionReason",
    "Page",
    "QuestionId",
]

#: Planned software-question id, ``{kind}:{slug}``.
QuestionId = str


class OmissionReason(StrEnum):
    """Closed-set reasons a planned question did not become an accepted page."""

    NOT_INSPECTED = "not_inspected"
    EMPTY = "empty"
    GATE_REJECTED = "gate_rejected"
    NO_MODEL = "no_model"
    INSPECTION_IMPOSSIBLE = "inspection_impossible"


@dataclass(frozen=True)
class Page:
    """Accepted answer for one planned software question.

    The record carries no ``roles`` or ``intent`` field. ``cited_files`` are
    repo-relative paths the body grounded in; ``related`` are other question
    ids.
    """

    id: QuestionId
    title: str
    summary: str
    body: str
    subjects: tuple[str, ...]
    related: tuple[str, ...]
    cited_files: tuple[str, ...]


@dataclass(frozen=True)
class Omission:
    """A planned question that was not accepted, with a closed-set reason."""

    question_id: QuestionId
    reason: OmissionReason
