# Brief — quality-review-gate

## Feature

Make the **Review** pipeline stage real: evaluate each written `Segment` against the
**COBESY validation gate** using an LLM-judge, and gate which segments proceed to
assembly. This is Wave 2, spec #2 — the quality firewall before publication.

## Why It Exists

Replaces the `review` no-op stub. COBESY's premise is that unclear, non-MECE, or
role-mismatched content fails to drive adoption. This stage enforces the COBESY
anti-cringe gate so only segments that pass quality checks reach the MkDocs site.

## In Scope

- Replace `docuharnessx/stages/review.py` no-op stub IN PLACE (keep STAGE_NAME,
  ReviewStage class, factory, module path stable — registry/bundle untouched).
- Consume the written `Segment` set from `SLOT_WRITTEN_SEGMENTS` (+ the segment
  store), plus the `CoveragePlan`/`Vocabulary` for role/intent context.
- For each segment, apply the **COBESY validation gate** via an LLM-judge: MECE,
  within-working-memory, role-fit (matches the segment's roles/intent), clarity,
  falsifiability/evidence-grounding, and anti-AI-slop. Reuse HarnessX's evaluation
  dimension (e.g. `LLMJudgeEvaluator` in `harnessx.processors.evaluation`) where it
  fits, rather than reinventing a judge.
- Produce a frozen **ReviewReport** (per-segment verdict: pass/fail + findings +
  criterion scores, plus an aggregate) and the **accepted** segment set; surface via
  a new `SLOT_REVIEW_REPORT` (append-only `types.py` + `RunContext` accessor) for the
  Wave 3 assembler. Only passed segments proceed.
- Re-write loop: a **bounded** write→review remediation loop (re-invoke the writer
  for failed segments) is a DESIGN DECISION — prefer it if it fits the stage model
  cleanly and stays bounded; otherwise emit verdicts + actionable feedback for a
  later iteration and gate (accept/reject) in a single pass. Document the choice.
- **Deterministic core / gated model split**: the gate criteria, aggregation,
  accept/reject logic, and report assembly are deterministic and unit-testable
  WITHOUT a model; the judgement is the only model-dependent step. Honor inherited
  Control budgets.

## Out of Scope

- Writing/rewriting prose content beyond a bounded remediation loop (cobesy-writer owns generation).
- MkDocs assembly / deploy.

## Dependencies

- `cobesy-writer` — the written `Segment` set + `SLOT_WRITTEN_SEGMENTS` (consume).
- `ontology-engine` — `Segment` schema, `SegmentStore`, roles/intents.
- `harness-bundle-skeleton` — `RunContext`, slots, stage base/registry, the bound model + HarnessX evaluation.

## Key Constraints

- Python 3.12. Deterministic gate/aggregation core (unit-testable, no model). The
  LLM-judge step must be **credential-free testable** via a fake/recorded judge
  (assert gating logic + report shape, NOT exact judge prose). `ReviewReport` is the
  seam the assembler consumes — design for stability.

## Acceptance Signal

Given a set of written `Segment`s + a fake judge, the Review stage produces a
deterministic `ReviewReport` (per-segment pass/fail + aggregate) into
`SLOT_REVIEW_REPORT`, lets only passed segments proceed, recorded in the journal;
gating/aggregation verified by unit tests; runs credential-free end-to-end.
