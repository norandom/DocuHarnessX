"""Question planner: ``RepoAnalysis`` → :class:`QuestionPlan`.

This module is the **QuestionPlanner** seam (design "Planning — QuestionPlanner").
The pipeline runner always calls :func:`plan_questions` after analysis.

The skeleton returns an empty plan so the runner can exist before signal-derived
planning lands. Equal analyses still yield equal (empty) plans.
"""

from __future__ import annotations

from docuharnessx.analysis.model import RepoAnalysis
from docuharnessx.planning.question_model import QuestionPlan

__all__ = ["plan_questions"]


def plan_questions(analysis: RepoAnalysis) -> QuestionPlan:
    """Return the bounded software-question plan for ``analysis``.

    Empty analysis (and, in this skeleton, every analysis) yields an empty
    plan (Req 3.5). The function never reads a role vocabulary.
    """
    return QuestionPlan(questions=(), repo_path=analysis.repo_path)
