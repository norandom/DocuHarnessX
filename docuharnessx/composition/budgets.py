"""Writer budget defaults and the agentic structure-gate threshold (task 1.1).

``docuharnessx.composition.budgets`` is the **composition-core defaults** module of the
Wave 2.5 ``agentic-codebase-writer``: it pins the per-segment agentic-run budget and the
structure-gate minimum-citations threshold as named, auditable, module-level constants so
every per-segment run is bounded by *shared* values rather than literals scattered across
the task-prompt assembler, the harness factory, and the structure gate (Req 5.1, 4.3, 4.4).

The agentic writer runs one bounded HarnessX agent per planned segment over a read-only
``Workspace`` rooted at the target repository. Each run must be strictly bounded so one
expensive segment cannot starve the rest (Req 5.1, 5.3): the run is capped by
``BaseTask(max_steps, max_cost_usd, token_budget)`` and by the ``make_control`` bundle's
loop detection and token-compaction guard. The agent's body is then accepted only when it
clears the deterministic structure gate, which requires at least :data:`MIN_CITED_FILES`
distinct ``file:line`` citations (Req 4.4) — the same threshold the task prompt demands of
the agent (Req 4.3).

This module is **model-free** by construction: it imports nothing from HarnessX. Each budget
is a module-level constant whose default can be raised or lowered at run time via a
``DHX_WRITER_*`` environment variable (read once at import) — so an operator can tune a
particular model/endpoint (e.g. a token-plan provider) without editing code, while the
defaults stay sane. Later tasks consume these names:

* :func:`docuharnessx.composition.task_prompt.build_agent_task` (2.1) seeds the
  ``BaseTask`` caps and the citation demand;
* :func:`docuharnessx.composition.harness_factory.build_writer_harness` (2.3) feeds the
  loop/cost/token thresholds into ``make_control``;
* :func:`docuharnessx.composition.structure_gate.validate_agent_body` (2.2) defaults its
  ``min_citations`` to :data:`MIN_CITED_FILES`.

Each constant is exposed identity-equal from the single ``docuharnessx.composition``
public namespace (mirroring :data:`~docuharnessx.composition.prose.DEFAULT_PROSE_TIMEOUT_S`),
so the stage adapter and the tests import one set of defaults from one place.
"""

from __future__ import annotations

import os

__all__ = [
    "WRITER_MAX_STEPS",
    "WRITER_MAX_COST_USD",
    "WRITER_TOKEN_BUDGET",
    "WRITER_TOKEN_THRESHOLD",
    "WRITER_LOOP_THRESHOLD",
    "MIN_CITED_FILES",
]


# --------------------------------------------------------------------------- #
# Environment overrides (resolved once at import; no override -> the default)   #
# --------------------------------------------------------------------------- #


def _env_int(name: str, default: int) -> int:
    """Positive integer from environment variable *name*, else *default*."""
    raw = os.environ.get(name, "").strip()
    if raw.isdigit() and int(raw) > 0:
        return int(raw)
    return default


def _env_float(name: str, default: float) -> float:
    """Positive float from environment variable *name*, else *default*."""
    raw = os.environ.get(name, "").strip()
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


# --------------------------------------------------------------------------- #
# Per-segment agentic-run budget (Req 5.1, 5.3) — BaseTask + make_control caps #
# --------------------------------------------------------------------------- #

#: Maximum number of agentic steps for one per-segment run, bound onto
#: ``BaseTask.max_steps`` (Req 5.1). A documentation segment is an explore-then-write task:
#: read the planner's evidence files plus a few neighbours, then write the final answer.
#: Override with ``DHX_WRITER_MAX_STEPS``. Below the HarnessX default of 50.
WRITER_MAX_STEPS: int = _env_int("DHX_WRITER_MAX_STEPS", 24)

#: Maximum US-dollar cost for one per-segment run, bound onto ``BaseTask.max_cost_usd`` and
#: fed to ``make_control(max_cost_usd=...)`` so the cost guard halts a run that crosses it
#: (Req 5.1). This is the real outer bound on a single segment's spend — keep it generous
#: enough that an explore-then-write loop finishes, but bounded so one segment cannot
#: consume the budget intended for the others (Req 5.3). Override ``DHX_WRITER_MAX_COST_USD``.
WRITER_MAX_COST_USD: float = _env_float("DHX_WRITER_MAX_COST_USD", 5.00)

#: Token budget for one per-segment run, bound onto ``BaseTask.token_budget`` (Req 5.1).
#: HarnessX counts this as *cumulative* tokens summed across every turn (prompt+completion),
#: not the live context size — an explore-then-write loop that re-sends a growing context
#: accumulates fast, so this must be well above a single context window or the run is killed
#: (``exit_reason=budget_exceeded``) *before* it writes the grounded answer. Sized for a few
#: read turns plus a substantial final body over a 25-40k LOC repo. Override
#: ``DHX_WRITER_TOKEN_BUDGET``. Kept at or above :data:`WRITER_TOKEN_THRESHOLD`.
WRITER_TOKEN_BUDGET: int = _env_int("DHX_WRITER_TOKEN_BUDGET", 1_000_000)

#: Token-compaction threshold for the run's *live context*, fed to
#: ``make_control(token_threshold=...)`` (Req 5.1). When the working context grows past this
#: many tokens the control bundle compacts it. Set high enough to retain the file contents
#: (and their exact line numbers) the agent needs to cite, while staying under the HarnessX
#: default of 140k... — raised here so compaction does not summarise away citation detail
#: mid-run. Override ``DHX_WRITER_TOKEN_THRESHOLD``.
WRITER_TOKEN_THRESHOLD: int = _env_int("DHX_WRITER_TOKEN_THRESHOLD", 150_000)

#: Loop-detection halt threshold, fed to ``make_control(loop_threshold=...)`` (Req 5.1).
#: When the same tool-call fingerprint repeats this many times the run is halted, so a
#: repeating read/grep pattern cannot spin out the step or cost budget. Override
#: ``DHX_WRITER_LOOP_THRESHOLD``.
WRITER_LOOP_THRESHOLD: int = _env_int("DHX_WRITER_LOOP_THRESHOLD", 6)


# --------------------------------------------------------------------------- #
# Structure-gate threshold (Req 4.3, 4.4) — minimum distinct cited files       #
# --------------------------------------------------------------------------- #

#: Minimum number of *distinct* ``file:line`` source files an accepted agent body must cite
#: (Req 4.4), and the same minimum the task prompt demands of the agent (Req 4.3). The
#: deterministic structure gate rejects a body that cites fewer than this many files (and
#: the caller then renders the deterministic fallback), keeping a published segment grounded
#: in more than a single file. Override ``DHX_WRITER_MIN_CITED_FILES``. Used as the default
#: ``min_citations`` of :func:`docuharnessx.composition.structure_gate.validate_agent_body`.
MIN_CITED_FILES: int = _env_int("DHX_WRITER_MIN_CITED_FILES", 3)
