# Project Structure

## Organization Philosophy

Pipeline-first. The codebase mirrors **analyze → questions → write → gate →
assemble → deploy**. The atomic content unit is a **page that answers one
software question**. Everything else exists to propose questions, ground
answers in source, omit ungrounded pages, and emit a site.

HarnessX processors are not the pipeline. Stages that only existed to fire on
a dummy `step_end` are retired.

## Directory Patterns

### Generator package
**Location**: `docuharnessx/`
**Purpose**: CLI, pipeline runner, analysis, question planner, writer adapter,
substance gate, assembler, optional deployer.

### Pipeline
**Location**: `docuharnessx/pipeline/`
**Purpose**: the ordinary-Python run that calls each step in order and writes
the operator report. Not a HarnessX `HarnessConfig`.

### Analysis
**Location**: `docuharnessx/analysis/`
**Purpose**: deterministic repo scan → `RepoAnalysis`. Unchanged as a signal
source; not a page author.

### Questions
**Location**: `docuharnessx/planning/` (question planner; the Role × Intent
matrix is retired)
**Purpose**: `RepoAnalysis` → bounded list of software questions + evidence files.

### Writer
**Location**: `docuharnessx/composition/`
**Purpose**: bounded HarnessX agent per question; task prompt is the question
and evidence, not a filled outline. No publishable fallback renderer.

### Gate
**Location**: `docuharnessx/composition/` (substance gate) — not a COBESY LLM-judge
**Purpose**: accept or omit a body. Never invent replacement prose.

### Assembler / deploy
**Location**: `docuharnessx/assembler/`, `docuharnessx/deployer/`
**Purpose**: MkDocs tree from accepted pages; optional Pages publish.

### CLI
**Location**: `docuharnessx/cli.py` (`dhx`)
**Purpose**: validate target, resolve model, run the pipeline, print the report.

### Specs & steering
**Location**: `.kiro/specs/` and `.kiro/steering/`
**Purpose**: spec-driven development. Wave 5 (`explore-first-simplification`) is
the current authoring spec. Waves 0–4 are historical.

## Naming Conventions

- **Files/modules**: snake_case (Python).
- **Pages**: Markdown with frontmatter `{id, title, subjects[], summary, related[]}`.
- **Citations** in body: repo-relative `path:line`.
- **Questions**: stable ids derived from kind + subject (not role/intent keys).

## Code Organization Principles

- The pipeline runner imports step functions; steps do not import the CLI.
- The writer adapter is the only module that constructs a HarnessX harness.
- Analyze, question planner, and substance gate stay model-free.
- Output is plain Markdown + `mkdocs.yml`; publishing is a thin optional step.
- Do not keep a parallel “fallback page” path “just in case.”

---
_Document patterns, not file trees. New files following patterns shouldn't require updates_
