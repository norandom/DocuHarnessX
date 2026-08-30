"""Accepted documentation pages and fail-closed omissions.

``docuharnessx.pages`` is the slim page seam for explore-first authoring: an
accepted :class:`Page` answers one software question and carries no reader
roles or intent. An :class:`Omission` is a planned question id plus a
closed-set :class:`OmissionReason`.
"""

from __future__ import annotations

from docuharnessx.pages.model import Omission, OmissionReason, Page, QuestionId

__all__ = [
    "Omission",
    "OmissionReason",
    "Page",
    "QuestionId",
]
