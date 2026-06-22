# Research & Design Decisions — quality-review-gate

## Summary
- **Feature**: `quality-review-gate`
- **Discovery Scope**: Extension (replace one no-op stage stub in a merged Wave 0+1
  foundation; integration-focused discovery against real, frozen seams).
- **Key Findings**:
  - The merged `PlanStage` (`docuharnessx/stages/plan.py`) and the planner's
    `relevance.py` define the exact, reusable pattern: a thin `NoOpStage` subclass that
    captures `State` in `on_task_start`, does its work in `on_step_end`, runs a pure
    deterministic core, optionally consults a duck-typed model off the run loop via
    `asyncio.to_thread`, publishes into a slot, and journals a bounded summary. This spec
    mirrors it exactly (writer's design does the same).
  - HarnessX's `LLMJudgeEvaluator` (`harnessx.processors.evaluation`) is shaped for
    whole-task evaluation on a `TaskEndEvent` via a registered `evaluator` sub-harness and
    a single pass/fail+score JSON. It is NOT a clean per-segment, multi-criterion judge,
    and wiring a sub-harness into `make_docgen` is out of this stage's boundary. We adopt
    its **prompt/parse contract** (a strict JSON `{score, passed, reason}` shape, fenced-
    code stripping, defensive parse, score clamped to `[0,1]`, `passed` defaulting to
    `score >= threshold`) and its judge philosophy, but apply it per segment through the
    same duck-typed-provider bridge the writer's `prose.py` uses, rather than registering
    `LLMJudgeProcessor`/`LLMJudgeEvaluator`.
  - The upstream seam is `WrittenSegments` at `SLOT_WRITTEN_SEGMENTS` (cobesy-writer):
    `segments: tuple[Segment, ...]` (plan order, same identities as in the `SegmentStore`),
    `flags: tuple[WriteFlag, ...]`, `total_planned: int`. Every planned segment is in
    `segments` or `flags`. We judge `segments` (the valid written ones); flagged segments
    were never written, so they are reported as not-judged context, not gated here.
  - `CoveragePlan` v1 / `PlannedSegment` / `EvidenceRef` are frozen tuples; `Segment` is a
    mutable dataclass but we treat it read-only. `validate_segment`/`emit_tags`/
    `SegmentStore` are reused verbatim. `types.py`/`context.py` extend append-only (the
    analyzer, planner, and writer each added exactly one slot + accessor pair this way).

## Research Log

### Existing stage-adapter + gated-model pattern
- **Context**: The gate must be a single-stage in-place swap with a deterministic core and
  one gated model step, credential-free testable.
- **Sources Consulted**: `docuharnessx/stages/plan.py`, `docuharnessx/stages/base.py`,
  `docuharnessx/planning/relevance.py`, `docuharnessx/context.py`, `docuharnessx/types.py`,
  `tests/_fakes.py`, cobesy-writer `design.md`.
- **Findings**:
  - `NoOpStage` binds the runtime (`_bind_runtime`), resolves the tracer, and attaches to
    `step_end`. `PlanStage` overrides `on_task_start` (capture `State`) and `on_step_end`
    (do work, journal, yield event unchanged). Outside a harness (no captured `State`) it
    forwards the event and does nothing — it only raises on a missing required slot when a
    `State` *is* bound.
  - The bound model is reached via `getattr(self, "_model_config", None)` then `.main`
    (`PlanStage._relevance_model`); any failure to reach it degrades to `None`.
  - `relevance._complete_with_timeout` drives the provider's awaitable `complete` under
    `asyncio.wait_for(..., timeout)` on a private loop via `asyncio.run`; the stage offloads
    that synchronous bridge with `asyncio.to_thread` so loops never nest. All judge failures
    are absorbed and logged at WARNING; the deterministic path continues.
  - `FakeProvider.complete` returns a fixed `.content` string with `finish_reason="end_turn"`
    and never hits the network. A judge built on the duck-typed `.content` contract works
    against it credential-free; tests assert gating/report shape, not prose.
- **Implications**: The review gate is a near-isomorph of the writer stage with the
  model role inverted toward *judging* instead of *generating*. A new pure package
  `docuharnessx/review/` holds the deterministic core (criteria, prompt, parse, aggregate,
  report model); `docuharnessx/judge.py`-equivalent (`review/judge.py`) is the only
  model-touching module; `stages/review.py` is the thin adapter.

### HarnessX evaluation dimension reuse
- **Context**: The brief asks to reuse HarnessX's evaluation (e.g. `LLMJudgeEvaluator`)
  "where it fits, rather than reinventing a judge."
- **Sources Consulted**:
  `.venv/.../harnessx/processors/evaluation/__init__.py`,
  `.../strategies/evaluators/llm_judge.py`.
- **Findings**: `LLMJudgeEvaluator.evaluate(TaskEndEvent)` resolves a judge model from
  `self._sub_harnesses[provider_key]` and runs a `BaseTask(description=prompt, max_steps=1)`,
  parsing `{"score","passed","reason"}` with fenced-code stripping and defensive clamping.
  It is per-task, not per-segment, and depends on sub-harness registration that this stage
  does not own. Its prompt-and-parse contract, however, is exactly the judge interaction
  this gate needs per criterion/segment.
- **Implications**: Reuse the *contract and parsing discipline* (strict JSON verdict,
  fenced-code stripping, score clamp, `passed` fallback to a threshold) and document the
  lineage; do not wire `LLMJudgeProcessor`/sub-harnesses (out of boundary). This keeps the
  judge per-segment, deterministic in its gating, and fake-testable.

## Architecture Pattern Evaluation

| Option | Description | Strengths | Risks / Limitations | Notes |
|--------|-------------|-----------|---------------------|-------|
| Pure review core + thin gated stage adapter | Deterministic `review` package (criteria/prompt/parse/aggregate/report) + single gated `judge` module + `ReviewStage` adapter | Mirrors merged `planning`/`PlanStage`; deterministic + unit-testable without a model; one gated call/segment | Two modules touch the same `Segment` read-only — no shared write ownership | **Chosen** |
| Reuse `LLMJudgeProcessor` + `evaluator` sub-harness | Register HarnessX's judge processor into `make_docgen` | Maximal HarnessX reuse | Per-task not per-segment; requires editing `make_docgen` + sub-harness registry (out of boundary); harder to gate deterministically | Rejected — boundary + granularity mismatch |
| Bounded write→review remediation loop | Review re-invokes the writer's composition for failed segments, N rounds | Could auto-improve failing prose | Crosses the single-stage boundary into writer internals + the bound generation loop; harder determinism; couples two stages | Rejected — see decision below |

## Design Decisions

### Decision: Single-pass gate, not a write→review remediation loop
- **Context**: The brief leaves the remediation-loop choice open: a bounded write→review
  loop (re-invoke the writer for failed segments) vs. a single-pass gate that emits
  verdicts + actionable feedback.
- **Alternatives Considered**:
  1. Bounded loop — review calls back into the writer's composition core + bound model for
     each failed segment, up to N rounds.
  2. Single pass — judge each written segment once, gate accept/reject, surface findings.
- **Selected Approach**: **Single pass.** Judge each written segment exactly once; compute
  a deterministic verdict; accept the passes; for fails, record actionable findings and
  per-criterion scores in the report. No re-invocation of the writer from this stage.
- **Rationale**:
  - The writer and reviewer are *separate pipeline stages* (`write` runs before `review`);
    a loop would require the review stage to import and drive the writer's composition core
    and the bound generation model, breaking the single-stage-swap boundary the whole
    architecture rests on (each wave replaces exactly one stub).
  - It keeps the deterministic-core / gated-model split clean: one judge call per segment +
    deterministic aggregation, no nested generation loop, easier to bound under Control.
  - The frozen `ReviewReport` carries findings + per-criterion scores, which is precisely
    the feedback channel a *future* iteration (a re-run or a later orchestration wave) needs
    to remediate — without changing this seam. The report is designed to remain stable
    whether or not a loop is added later.
- **Trade-offs**: No automatic in-run improvement of failing prose; failing segments are
  excluded from the accepted set and must be addressed by a re-run or a future loop. This is
  acceptable for Wave 2: the gate's job is to gate, and the report makes the gap actionable.
- **Follow-up**: Keep `ReviewReport` additive-only; a future remediation loop must consume
  the existing findings, not reshape the report.

### Decision: Per-segment duck-typed judge, reusing HarnessX's verdict contract
- **Context**: Need a model judge that is per-segment, multi-criterion, deterministic in its
  gating, and fake-testable.
- **Selected Approach**: A single `judge_segment(request, *, model, timeout_s)` over a
  duck-typed provider (awaitable `complete(messages, tools, stream_callback=None)` →
  `.content` string), mirroring `planning.relevance` and the writer's `prose.py`. It parses
  a strict JSON verdict per the `LLMJudgeEvaluator` contract (`{criteria scores}`, overall
  `passed`, `reason`), stripping fenced code and clamping scores. On any
  failure/timeout/empty/unparseable response it returns `None`; the deterministic core then
  applies the documented default verdict.
- **Rationale**: Reuses HarnessX's judge philosophy and parse discipline without its
  sub-harness coupling; one bounded `complete` per segment; degrades deterministically so a
  `FakeProvider` run produces a well-formed report.
- **Trade-offs**: The default-verdict policy must be chosen and documented (see below).

### Decision: Default verdict when the judge is unavailable
- **Context**: A model-less run, a `FakeProvider`, or a failed judge must still yield a
  deterministic, reproducible report.
- **Selected Approach**: Treat an unavailable judge as a documented **default reject** for
  the COBESY gate (a quality firewall fails closed — unjudged content is not asserted to
  meet the gate), recorded with an explicit `judge_source = "unavailable"` marker and a
  finding explaining the segment was not judged. The default policy is a single named
  constant so it is reviewable and reproducible.
- **Rationale**: A firewall should fail closed; surfacing the marker keeps a credential-free
  run honest (it produces a well-formed report and an empty/partial accepted set, clearly
  labelled) rather than silently passing unjudged content downstream. Determinism is
  preserved because the default is a fixed rule applied identically to every unavailable
  segment.
- **Trade-offs**: A fully model-less run accepts nothing — intentional for a quality gate;
  the report still records every segment with its criteria placeholders and the marker, and
  the aggregate makes the model-less state obvious. Tests inject a fake judge returning a
  parseable passing verdict to exercise the accept path credential-free.

### Decision: Frozen, versioned `ReviewReport` as the assembler seam
- **Context**: The assembler (Wave 3) consumes exactly the accepted segments and needs a
  stable contract.
- **Selected Approach**: A `@dataclass(frozen=True)` `ReviewReport` with `schema_version`,
  ordered `entries: tuple[SegmentReview, ...]`, `accepted: tuple[Segment, ...]` (same
  identities as in the store), and an `aggregate: ReviewAggregate`. Each `SegmentReview`
  carries `segment_id`, `verdict`, `scores: tuple[CriterionScore, ...]`, `findings:
  tuple[str, ...]`, and `judge_source`. All tuples for deep immutability + structural
  equality (mirrors `CoveragePlan`/`WrittenSegments`).
- **Rationale**: Matches the project's frozen-seam convention; deterministic equality makes
  reproducibility testable; a single version authority lets the assembler pin it; additive
  evolution only.
- **Trade-offs**: Any field-set change is a recorded revalidation trigger for
  `mkdocs-site-assembler`.

## Risks & Mitigations
- **Nesting `asyncio.run` inside the run loop** — drive the judge via `asyncio.to_thread`
  exactly as `PlanStage._maybe_apply_relevance` does.
- **Over-coupling to default-profile role ids** — derive role-fit context from the loaded
  `Vocabulary` term labels/descriptions, never literals (Req 10).
- **A flaky judge corrupting the run** — every judge failure is absorbed to the default
  verdict; the run never aborts on a judge error; only fatal *input* errors (missing slot /
  unsupported plan version) halt the run.
- **Report drift breaking the assembler** — `ReviewReport.schema_version` + a documented
  frozen field set; any change is a revalidation trigger.

## References
- `docuharnessx/stages/plan.py`, `docuharnessx/planning/relevance.py`,
  `docuharnessx/stages/base.py`, `docuharnessx/context.py`, `docuharnessx/types.py` —
  the merged stage-adapter + gated-model + append-only-seam patterns reused here.
- `.venv/.../harnessx/processors/evaluation/strategies/evaluators/llm_judge.py` — the
  judge prompt/parse/verdict contract reused at the per-segment level.
- `.kiro/specs/cobesy-writer/design.md` — `WrittenSegments`/`WriteFlag` shape and the
  `SLOT_WRITTEN_SEGMENTS` seam consumed verbatim.
- `~/.claude/skills/cobesy/SKILL.md` — the Phase 5 anti-cringe validation gate (MECE,
  working-memory fit, point-of-action, falsifiability, AI-slop) this gate enforces.
