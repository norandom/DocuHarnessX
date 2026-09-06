# Tasks — architect-narrative

Requirements, design, and tasks are approved (`spec.json`). Architecture
overview is tasks 1–2; COBESY writer/density and requirements trace are
later.

## 1. Architecture model

- [x] 1.1 Frozen `ArchitectureNode`, `ArchitectureEdge`, `ArchitectureModel`, `AbstractionLevel` on `comprehension.signals` (defaults so old constructors keep working). _Boundary:_ signals.py. _Depends:_ none.
- [x] 1.2 `build_architecture_model(analysis, identity, styles)` from existing detectors; no ungrounded edges; byte-stable. _Boundary:_ comprehension/architecture.py. _Depends:_ 1.1.
- [x] 1.3 Assign abstraction levels to nodes and to question pages (startup/package → context/container; module → component). _Boundary:_ architecture.py + assemble. _Depends:_ 1.2.
- [x] 1.4 Tests: fixture CLI + three layers → model; two runs equal; missing analysis → no model. _Depends:_ 1.2.

## 2. Views from the model

- [x] 2.1 `view_context` / `view_container` / `view_style` / `view_sequence` read the model; same node labels across views. _Boundary:_ comprehension/graphs.py. _Depends:_ 1.2.
- [x] 2.2 Prefer model views on home, system page, and diagrams catalog; keep file graphs at depth 5 only. _Boundary:_ graphs.py + question_site. _Depends:_ 2.1.
- [x] 2.3 Catalog grouping: Architecture, Reading path, Coverage, per-question, glossary. Each model view once. _Boundary:_ render_diagrams_index. _Depends:_ 2.2.
- [x] 2.4 Optional evidenced views: use-case (CLI commands), ERD (schema artifacts), deployment (docker/CI). Omit if empty. No ArchiMate/BPMN/SysML. _Boundary:_ graphs.py. _Depends:_ 1.2.
- [x] 2.5 `mkdocs build --strict` fixture with context + layered views. _Depends:_ 2.2.

## 3. COBESY writer adapter

- [x] 3.1 Deterministic `build_question_blueprint(question, model)` (governing idea, opening cues, ≤5 heads, density budget, abstraction). No Role × Intent. _Boundary:_ composition/blueprint_question.py. _Depends:_ 1.3.
- [x] 3.2 `build_question_task` includes the blueprint; citations go under Grounding; forbid SCQA/Minto/COBESY strings in published Markdown. _Boundary:_ question_task.py. _Depends:_ 3.1.
- [x] 3.3 Tests: equal inputs → equal blueprint and equal task description; description contains governing idea. _Depends:_ 3.2.

## 4. Density grain

- [ ] 4.1 `trim_summary(page)`: ≤2 sentences, ≤280 chars, strip `path:line`. Apply at assemble for depth 1 even when the living page is older. _Boundary:_ composition or assembler. _Depends:_ none.
- [ ] 4.2 Depth-1 assembled layer is the trimmed summary (plus context picture on the system page), not the body. _Boundary:_ assembler/pages.py. _Depends:_ 4.1, 2.2.
- [ ] 4.3 Substance gate unchanged. Tests: long cited summary trims; empty-after-trim keeps body and records a note. _Depends:_ 4.1.

## 5. Requirements trace

- [ ] 5.1 Link harvested `RequirementHit`s to model nodes/bands by whole-word name overlap (length ≥ 4). Unlinked if no overlap. _Boundary:_ architecture.py. _Depends:_ 1.2.
- [ ] 5.2 Surface links on the architecture catalog or compliance-adjacent list. No editor, no ReqIF. _Depends:_ 5.1, 2.3.

## 6. Validation

- [ ] 6.1 Full pytest; dogfood assemble on this repo; depth 1 home and package page have a story opening and a model view, not a file star. _Depends:_ 2, 3, 4.
- [ ] 6.2 Confirm published pages contain no `SCQA`/`Minto`/`COBESY`. _Depends:_ 3.2.
