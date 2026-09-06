# Requirements Document

## Introduction

Architects and adopters who read a DocuHarnessX site need a **story at a
chosen zoom**, not a catalog of local graphs and not an inspection dump.
This specification adds a repo-grounded **architecture model** with
abstraction levels, derives views from that model, and applies COBESY
cognitive and composition rules to explore-first page writing so density
matches the grain. It is a follow-up to `comprehension-visuals`. It does
not clone Visual Paradigm, Sparx, or ArchiMate, and it does not print
methodology names on the page.

## Boundary Context

- **In scope**: frozen architecture model and abstraction detection;
  view emitters that read the model; COBESY composition blueprint and
  writer-prompt adapter for explore-first questions; density/grain gate
  on summaries; linking harvested requirement sentences to architecture
  bands; evidenced extra views (use-case, activity-from-DAG, ERD-from-
  schema, deployment-from-CI/artifacts).
- **Out of scope**: Visual Paradigm, Sparx, Archi, or Structurizr product
  integration; SysML or ReqIF; TOGAF ADM guide-through; BPMN simulation;
  ArchiMate certification; embedding search; Role × Intent pages;
  reader-facing SCQA/Minto/COBESY labels; round-trip code generation;
  as-is vs to-be gap analysis (no to-be model).
- **Adjacent expectations**: `comprehension-visuals` glossary, depth
  slider, and fail-closed pictures remain. Explore-first questions remain
  the page unit. Living pages remain the prose source of truth. Assemble
  still owns highlighting. `cobesy-writer` is historical; this spec
  reuses its blueprint *idea*, not its segment contract.

## Requirements

### Requirement 1: Architecture model from the repository

**Objective:** As an architect, I want one model of people, the system,
and its parts, so that every picture of this project is talking about the
same nodes.

#### Acceptance Criteria

1. When analysis and comprehension signals are available, DocuHarnessX
   shall build a frozen architecture model whose nodes include evidenced
   actors, the named system, containers or modules, and optional
   externals (source repository, CI, documentation site, compose
   services).
2. When an edge cannot be grounded in an entrypoint, a detected
   dependency, a compose/CI/Make relationship, or an architecture-band
   adjacency, DocuHarnessX shall not add that edge.
3. When the same repository is modelled twice, DocuHarnessX shall emit
   a byte-identical model.
4. If analysis is missing, DocuHarnessX shall omit the model and shall
   not emit a placeholder architecture page.

### Requirement 2: Abstraction levels

**Objective:** As a reader, I want each part of the system labelled by
how far I am from running code, so that zoom means something.

#### Acceptance Criteria

1. When a model node is created, DocuHarnessX shall assign it an
   abstraction level from the closed set `context`, `container`,
   `component`, `code`.
2. When a question page is assembled, DocuHarnessX shall assign that
   page the abstraction level of its primary subject (startup and
   package pages at context or container; module pages at component;
   file-grounding at code).
3. When the reader’s depth slider is at 1, the site shall prefer
   context-level pictures and openings, and shall not lead with
   file-level flowcharts.
4. The generator shall not invent a C4 “code” diagram of every class;
   code-level pictures remain the existing file graphs at depth 5–7.

### Requirement 3: Views are projections of the model

**Objective:** As a reader, I want context, container, layered, and
service pictures to agree, so that I am not looking at three different
systems.

#### Acceptance Criteria

1. When the architecture model exists, DocuHarnessX shall derive the
   system-context, container, and (when detected) layered or services
   pictures from that model rather than from independent ad-hoc graphs.
2. When a node appears in two views, DocuHarnessX shall use the same
   label and identity in both.
3. If a style (layered, services, hexagonal, client/server, pipeline)
   is not detected, DocuHarnessX shall omit that view rather than
   drawing an empty template.
4. The diagrams catalog shall list model views first, then per-question
   file graphs.

### Requirement 4: Evidenced extra viewpoints only

**Objective:** As an architect, I want a use-case, activity, ERD, or
deployment picture only when the repository actually contains that
shape, so that the catalog does not fill with decorative UML.

#### Acceptance Criteria

1. When a CLI or HTTP actor and named commands or routes are detected,
   DocuHarnessX may publish a use-case picture of those goals; otherwise
   it shall omit use-case.
2. When a CI or Make DAG exists, DocuHarnessX shall treat that DAG as
   the activity/process view and shall not invent BPMN.
3. When schema or ORM artifacts are detected (for example OpenAPI,
   prisma, SQL DDL, protobuf), DocuHarnessX may publish an ERD or
   schema picture of named entities; otherwise it shall omit ERD.
4. When Docker or CI deploy jobs are detected, DocuHarnessX may publish
   a coarse deployment picture; otherwise it shall omit deployment.
5. DocuHarnessX shall not emit ArchiMate, SysML, TOGAF ADM, or BPMN
   notation.

### Requirement 5: COBESY blueprint for explore-first pages

**Objective:** As a writer of a question page, I want a composition
skeleton before prose, so that the page argues one idea instead of
dumping the files I opened.

#### Acceptance Criteria

1. When the explore-first writer builds a task for a question,
   DocuHarnessX shall first build a deterministic composition blueprint
   that includes: one governing idea, audience (from default depth and
   question kind), purpose (answer the question), opening cues (who is
   acting, what is happening, what is at stake), a MECE skeleton of at
   most five section heads, and a density budget.
2. The writer task description shall include that blueprint and the
   page’s abstraction level, and shall instruct the model to put
   `path:line` citations in a grounding section rather than in the
   opening.
3. The published Markdown shall not contain the strings `SCQA`,
   `Minto`, `COBESY`, or `andragogy` (case-insensitive).
4. Equal question plus analysis plus architecture model shall yield a
   byte-identical blueprint without a model call.

### Requirement 6: Density and grain

**Objective:** As an adopter, I want the first screen of a page to be
short and consequential, so that I can decide whether to zoom.

#### Acceptance Criteria

1. When a page is accepted, its `summary` shall be at most two
   sentences and at most 280 characters, with no `path:line` citation.
2. If the writer returns a longer summary, DocuHarnessX shall
   deterministically trim to the first two sentences within that cap
   before store, and shall not keep the dump as the depth-1 layer.
3. The depth-1 layer of an assembled question page shall be that
   summary (and, on the system page, the context picture), not the
   full inspection body.
4. The substance gate shall continue to require real citations and
   symbols in the body; density shall not be used as an excuse to drop
   grounding.
5. DocuHarnessX shall not treat a wall of autolinked glossary terms as
   a substitute for a governing idea.

### Requirement 7: Narrative follows abstraction

**Objective:** As a reader moving the depth slider, I want the prose
grain to match the picture grain, so that depth 1 is a story and depth
7 is the file list.

#### Acceptance Criteria

1. When assembling a page at minimum depth 1, DocuHarnessX shall show
   the Cron-shaped opening (actor, situation, stake) without labelling
   those parts.
2. When assembling at depth 3, DocuHarnessX shall show the architecture
   or sequence view for that page’s abstraction level when the model
   has one.
3. When assembling at depth 5, DocuHarnessX shall show the body
   sections from the blueprint skeleton.
4. When assembling at depth 7, DocuHarnessX shall show cited files and
   shall not require the adopter to have read them to understand depth 1.

### Requirement 8: Requirements stay harvested and linked

**Objective:** As a requirements reader, I want existing `shall`
sentences tied to architecture bands, so that control language is not
stranded from the pictures.

#### Acceptance Criteria

1. When requirement-shaped sentences are already harvested,
   DocuHarnessX shall keep listing them as cards and shall not invent
   new requirements.
2. When a card’s text or term ids overlap an architecture band or node
   name, DocuHarnessX shall link that card to that band or node.
3. If no overlap exists, DocuHarnessX shall leave the card unlinked
   rather than guessing.
4. DocuHarnessX shall not provide a requirements editor or ReqIF
   export.

### Requirement 9: Fail-closed, deterministic, assemble-honest

**Objective:** As an operator, I want this follow-up to stay as honest
as explore-first, so that CI does not publish an architecture fiction.

#### Acceptance Criteria

1. When the same repository is assembled twice, DocuHarnessX shall emit
   byte-identical architecture views and byte-identical blueprints.
2. The generator shall not call a language model to invent architecture
   nodes, edges, or glossary definitions.
3. Living pages under `.docuharnessx/pages/` shall not be rewritten by
   highlighting or diagram injection; those remain assemble-time.
4. If density trim would make a summary empty, DocuHarnessX shall omit
   the summary layer and keep the body, and shall record that in the
   run report.

### Requirement 10: Catalog and nav stay a story, not a dump

**Objective:** As a reader of the diagrams index, I want model views
first and file graphs last, so that I do not land in a table of forty
near-identical flowcharts.

#### Acceptance Criteria

1. When `diagrams.md` is assembled, DocuHarnessX shall group entries as
   Architecture, then Reading path, then Coverage, then per-question
   file graphs, then glossary graphs.
2. The contents list for Architecture shall name the detected style
   (for example “Layered architecture”) and the abstraction of the
   view (context, container).
3. DocuHarnessX shall not duplicate the same model view once per
   component page in the catalog; each model view appears once, with
   links to the pages that also show it.
