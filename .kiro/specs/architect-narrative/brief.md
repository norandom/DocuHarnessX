# Brief: architect-narrative

Follow-up to `comprehension-visuals`. Make the harness think like an architect
and write like a technical narrator: one abstraction ladder, many views, short
prose that carries a governing idea.

## Problem

Operators and architects who open a generated site still get two failures at
once. Pictures are a catalog of local graphs, not a model with zoom levels.
Prose is a dense inspection dump: long summaries, file:line in the first
screen, no governing idea. Visual Paradigm, Structurizr, IcePanel, and Sparx
are built around **abstraction + narrative**. DocuHarnessX already scans the
repo and writes grounded pages. That is the place it can win, and currently
does not.

Who hurts: an adopter at depth 1, an architect explaining the system, a
requirements reader looking for “shall” tied to a container. The pain is
cognitive load and missing zoom, not missing UML coverage.

## Current State

- Explore-first pages answer software questions, fail-closed, cite source.
- Depth slider hides bands; it is not an architecture zoom.
- Diagrams: C4-shaped context, detected layered/services views, sequence,
  pie, lineage, class surface, per-question file graphs, glossary.
- Writer task (`build_question_task`) asks for grounded Markdown. It does
  not pass a composition blueprint, abstraction level, or density cap.
- `explore-first-simplification` forbids printing SCQA labels on the page.
- `cobesy-writer` still describes the retired Role × Intent write stage.
- `comprehension-visuals` forbids VP product, SysML/ReqIF, embedding search.

## Desired Outcome

1. One frozen **architecture model** (people, system, containers, components,
   evidenced edges, abstraction level). Views are projections of that model.
2. **Abstraction detection** assigns each node and each page a level
   (context / container / component / code). Depth slider can follow it.
3. **COBESY cognitive + composition** shapes the writer: SCQA and Minto in
   the blueprint and prompt, never as reader-facing headings. Working-memory
   chunks. Cron opening (who, what is happening, what is at stake).
4. A **density gate** rejects or trims inspection-dump prose at the summary
   grain. Citations stay; they move to grounding / depth 7.
5. Requirements already in the repo remain cards, now linked to architecture
   bands. No requirements IDE.
6. New diagram kinds only when the model has evidence (use-case, activity,
   ERD, deployment). Omit otherwise.

## Approach

Repo-grounded model + COBESY writer, not a modeling-tool clone.

Detect an architecture model next to today’s `ArchitectureStyle` bands.
Derive C4 / layered / service views from the model so they cannot drift.
Feed the explore-first writer a deterministic `composition_blueprint`
(audience, governing idea, opening, skeleton, density budget) plus the
abstraction level of the question. Keep living pages as source of truth;
assemble still owns pictures and autolink.

## Scope

- **In**: architecture model + abstraction levels; view emitters from the
  model; COBESY blueprint + prompt for explore-first pages; density/grain
  gate; requirement-card links into architecture; optional evidenced
  use-case / activity / ERD / deployment views; gap analysis captured in
  this spec’s research.
- **Out**: Visual Paradigm / Sparx / Archi product integration; SysML or
  ReqIF round-trip; TOGAF ADM guide-through; BPMN simulation; ArchiMate
  certification; embedding search; Role × Intent page revival; naming
  SCQA/Minto/COBESY on the published page.
- **Extends**: `comprehension-visuals` (model and views), explore-first
  writer (`question_task`, substance/density).
- **Adjacent**: `cobesy-writer` (historical Role × Intent; do not reopen
  that page unit), `ontology-engine` (glossary seed only).

## Constraints

- Deterministic detection and blueprints; model-gated prose only.
- Fail-closed pictures and fail-closed architecture claims.
- Living pages unchanged by highlighting; assemble-only rewrite.
- Python 3.12; MkDocs Material mermaid that already builds `--strict`.
