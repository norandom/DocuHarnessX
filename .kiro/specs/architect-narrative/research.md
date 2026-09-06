# Research — architect-narrative

Gap analysis against Visual Paradigm and neighbouring architecture tools, plus
the writing/cognition gap in the current harness. This file is the discovery
record for the spec. It is not a product claim that DocuHarnessX will become
those tools.

## Summary

- **Feature**: architect-narrative
- **Discovery scope**: Follow-up to `comprehension-visuals`; adjacent to
  explore-first writing and the retired `cobesy-writer` page unit.
- **Key findings**:
  1. VP/Sparx/Archi win on **standards catalogs and a single model**. IcePanel
     and Structurizr win on **C4 zoom and storytelling**. DocuHarnessX wins on
     **repo-grounded, fail-closed generation**. The missing middle is a model
     with abstraction levels, not more disconnected Mermaid fences.
  2. VP “textual analysis → glossary → model element → requirement” is the
     analog we already started. The next step is **abstraction detection**
     (which grain is this node / this page?) and **trace** from existing
     `shall` sentences into architecture bands.
  3. The explore-first writer produces **inspection dumps**. COBESY already
     exists as an internal skill (`cobesy` cognitive + composition back-ends)
     and as a historical write-stage spec. It is **not** wired into
     `build_question_task`. That is the highest-leverage writing change.
  4. Cloning UML/BPMN/TOGAF catalogs would violate fail-closed and the
     existing out-of-scope list. Borrow **viewpoints and density**, not
     notation completeness.

## Research log

### Visual Paradigm (desktop + online)

- **Context**: User asked for a gap vs popular VP features and an architect
  mindset. `comprehension-visuals` already took glossary highlight + related
  nodes as a VP textual-analysis analog, and forbade the product, SysML, and
  ReqIF.
- **Sources**: visual-paradigm.com feature list and editions PDF; Archimetric
  TOGAF/ArchiMate/BPMN/UML guide (2025); Cybermedian desktop/online feature
  guide (2026).
- **Findings**:
  - **Modeling catalog**: UML 2.5 (14 types), BPMN 2.0, ArchiMate 3.x +
    viewpoints, SysML, SoaML, CMMN, DFD, ERD, C4, mind maps, org charts,
    cloud vendor diagrams.
  - **EA / process**: TOGAF ADM guide-through, Zachman, DoDAF/NAF/MODAF,
    BMM, gap/impact analysis, BPMN simulation.
  - **Requirements**: requirement diagrams, textual analysis (highlight
    candidates → glossary grid → model elements → generated requirements),
    decision tables, business-rule grids.
  - **Model discipline**: reusable elements, transform between diagrams,
    syntax validation, XMI/BPMN/ArchiMate import-export.
  - **Docs-adjacent**: project glossary, C4 editors, AI diagram generation
    (2025–2026), Agile 3Cs user stories.
- **Implications**: Do not implement the catalog. Implement the **loop** VP
  is good at: text → terms → structure → views at more than one grain.
  Keep glossary. Add abstraction levels and a single architecture model.

### Sparx Enterprise Architect, Archi

- **Context**: Broadest standards coverage vs free ArchiMate.
- **Sources**: Catio 2026 architecture-tools roundup; IcePanel “top 9”
  modeling tools.
- **Findings**: Sparx is model-first with round-trip code/DB, UAF, heavy
  governance. Archi is ArchiMate 3.x + Git-friendly, no code generation.
  Both assume a human modeller.
- **Implications**: DocuHarnessX must not become an EA suite. Optional
  later export (e.g. a Structurizr-ish JSON or Mermaid pack) can wait.
  Traceability **from repo `shall` to a band** is in-scope; ReqIF is not.

### Structurizr, IcePanel, C4-PlantUML, Mermaid

- **Context**: Where architects actually document software systems in 2026.
- **Sources**: IcePanel C4 tooling list; Optimal Relations C4 comparison;
  Repowise architecture-docs comparison (2026).
- **Findings**:
  - **Structurizr**: one DSL model, many views, C4 hierarchy enforced,
    ADRs beside the model. Source of truth is the model file.
  - **IcePanel**: collaborative C4, zoom between levels, shared object
    graph, presentation/storytelling. Source of truth is the visual model.
  - **PlantUML C4 / Mermaid**: diagrams-as-code in Git; weak model
    (pictures can contradict each other).
  - **DocuHarnessX today**: Mermaid pictures assembled from analysis.
    Context, layered bands, sequence, lineage exist, but they are **separate
    emitters**. There is no shared node identity across views. Depth slider
    is not C4 zoom.
- **Implications**: Steal Structurizr’s “one model, many views” and
  IcePanel’s “zoom is the story.” Keep Mermaid as the publish format.
  Do not require a DSL the operator must write. The repo scan **is** the
  model source.

### Draw.io, Lucidchart, Visio, Excalidraw

- **Findings**: Canvas tools. No model, no fail-closed, no repo grounding.
- **Implications**: Out of scope as a backend. Operators who want a canvas
  already have those tools.

### Current harness writing path

- **Context**: “Text density is very artificial.” User invested in COBESY
  and technical-writing skills (Minto, Dirksen, Knowles, Cron, Belcher,
  Klinkenborg, Williams & Bizup, Graff & Birkenstein, humanizer).
- **Sources**: `docuharnessx/composition/question_task.py` (explore-first
  prompt); `explore-first-simplification` Req (no SCQA labels on the page);
  `cobesy-writer` brief (Role × Intent blueprint, retired page unit);
  `~/.claude/skills/cobesy/references/03-cognitive-layer.md` and
  `composition.md`.
- **Findings**:
  - The writer is told: read evidence, cite `path:line` in at least two
    files, name symbols, final message **is** the Markdown body.
  - There is **no** governing-idea sentence, no opening grain, no working-
    memory chunk count, no “move citations to grounding.”
  - Depth 1 is supposed to be a summary; living-page summaries are often
    the first paragraph of the inspection dump.
  - Home was reshaped as a reading path (good). Inner pages were not.
  - Naming SCQA on the page is explicitly out of scope for explore-first.
    Using SCQA **inside the prompt and blueprint** is not.
- **Implications**: Wire COBESY as a **deterministic blueprint + prompt
  adapter + density gate**. Do not print “Situation / Complication.” Do not
  revive Role × Intent pages.

## Gap matrix

Legend: **Have** = shipped in DocuHarnessX; **Partial** = analog exists;
**Skip** = out of scope on purpose; **Take** = this spec should add.

| Capability | VP / Sparx | Structurizr / IcePanel | DocuHarnessX now | Decision |
|---|---|---|---|---|
| C4 context | Have | Native | Partial (flowchart analog) | Take: bind to model |
| C4 container | Have | Native | Partial (star or layered) | Take: view of model |
| C4 component / code | Have | Native zoom | File graphs at depth 5 | Take: level on the node |
| Single model, many views | Have | Native | Separate emitters | **Take** |
| Layered / services / hexagonal | Weak / manual | Manual | Name-path detector | Keep + attach to model |
| UML class of public surface | Have | Weak | classDiagram of CLI | Keep, cap density |
| Sequence of a typical run | Have | Dynamic view | Sequence from CLI | Keep, order from model |
| Use case | Have | Rare | None | Take only if actors+goals evidenced |
| Activity / BPMN | Have | Rare | None | Skip BPMN; activity only if workflow jobs evidenced |
| State machine | Have | Rare | None | Skip unless explicit state types in code |
| ERD / schema | Have | Rare | None | Take if schema/SQL/prisma evidenced |
| Deployment / cloud | Have | C4 deployment | CI DAG only | Take coarse: CI + artifacts |
| ArchiMate / TOGAF ADM | Have | Archi / none | None | **Skip** |
| SysML / ReqIF | Have | None | None | **Skip** (already forbidden) |
| Glossary + highlight | VP textual analysis | Weak | Have | Keep |
| Requirements from text | VP generate | ADRs | `shall` cards | Take: link cards → bands |
| Impact / gap analysis (as-is vs to-be) | Have | Weak | None | Skip (no to-be model) |
| Round-trip code gen | Sparx | None | None | **Skip** |
| Collaborative canvas | IcePanel | Native | MkDocs site | Skip as editor |
| Story / zoom narrative | IcePanel | Strong | Home reading path only | **Take** for pages |
| Repo as source of truth | Weak | Weak | **Have** | Keep as the differentiator |
| Fail-closed omit | Weak | Weak | **Have** | Keep |
| Working-memory writing | None | Weak | Not wired | **Take** |

## Architecture pattern evaluation

| Option | Description | Strengths | Risks | Notes |
|---|---|---|---|---|
| Clone VP catalog | Emit every UML/BPMN/ArchiMate kind | Familiar to EA buyers | Un grounded pictures, huge spec, fights fail-closed | Reject |
| Structurizr DSL export | Operator maintains a DSL | Real C4 model | New language, not generated from repo | Reject for now |
| Model-from-scan + Mermaid views | Frozen architecture model in signals; views are pure functions | Matches harness; no product lock-in | Detection will be coarse | **Choose** |
| Prompt-only COBESY | Tell the model “write SCQA” | Cheap | Labels leak; density still high | Reject as sole fix |
| Blueprint + density gate + prompt | Deterministic skeleton, then model, then grain check | Uses existing cobesy skill; testable without prose | Must not fight substance citations | **Choose** |

## Design decisions

1. **One architecture model**, stored as an additive frozen value on
   `ComprehensionSignals` (or a sibling frozen type). Nodes carry
   `abstraction` in `{context, container, component, code}`. Edges are
   only evidenced (entrypoint→component, compose service, CI needs,
   layered band adjacency). Views (context, container, layered, sequence)
   read the model; they do not invent extra nodes.
2. **Abstraction detection is name/path/role/kind heuristics**, same
   family as today’s architecture-style detector. No embeddings.
3. **COBESY is authoring infrastructure.** Blueprint fields: governing
   idea, Kolin keys (audience from depth, purpose = answer the question,
   message, tone), Cron opening cues, MECE skeleton (≤5 heads), density
   budget (summary ≤ 2 sentences / ≤ 280 chars; body sections ≤ 7±2
   chunks). Reader-facing Markdown must not contain the words SCQA,
   Minto, COBESY, andragogy.
4. **Density gate is separate from substance gate.** Substance still
   requires citations and real symbols. Density checks the **summary
   grain** and whether the depth-1 layer is citation-free. Fail density
   → rewrite once or omit the summary and keep body (decide in design:
   prefer trim-to-first-two-sentences deterministically rather than a
   second model call).
5. **Requirements stay harvest, not authoring.** Link existing
   RequirementHit term_ids to architecture band ids when names overlap.
6. **New diagram kinds are allow-listed and evidenced.** Use-case:
   Operator + named CLI commands as goals. Activity: CI/Make DAG already
   have. ERD: schema artifacts. Deployment: CI + docker artifacts.
   Everything else omit.
7. **Do not reopen `cobesy-writer` as the page unit.** That spec’s
   blueprint idea is reused; its Role × Intent segment contract is not.

## Writing grain applied to generated pages

Map COBESY grains onto the existing depth layers:

| Grain | Depth band | Job |
|---|---|---|
| Opening (Cron) | 1 | Who is acting, what is happening, what breaks if they are wrong |
| Macro (Belcher/Minto) | 1–3 | One governing idea; the architecture view that supports it |
| Meso (Graff) | 5 | Each `##` is a move: claim, they-say, evidence |
| Micro (Klinkenborg) | 5 | Short sentences, character=subject, action=verb |
| Grounding | 7 | `path:line` list — knowledge in the world, not in working memory |

The current prompt inverts this: it asks for citations **in the prose
first**, so the model leads with inspection. The spec must invert the
prompt order: answer, then structure, then citations in grounding.

## Competitive position (honest)

DocuHarnessX should not say it replaces Visual Paradigm. It should say:

> From a repository, produce a small architecture story: a model, a few
> views at different zoom levels, and pages that an architect can read
> without a dump of `file:line` in the first screen.

That is closer to Structurizr-from-scan plus IcePanel storytelling than
to an EA suite. The gap analysis exists to stop us from boiling the
ocean of UML types.

## References

- Visual Paradigm features / editions, visual-paradigm.com
- Archimetric, “Comprehensive Guide to Visual Paradigm for TOGAF ADM,
  ArchiMate, BPMN and UML” (2025)
- IcePanel, “Top 9 tools for C4 model diagrams”
- Catio, “Best Software Architecture Tools in 2026”
- Simon Brown, C4 model; Structurizr DSL
- COBESY skill: `03-cognitive-layer.md`, `composition.md`
- In-repo: `comprehension-visuals`, `explore-first-simplification`,
  `cobesy-writer` (historical)
