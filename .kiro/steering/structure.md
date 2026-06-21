# Project Structure

## Organization Philosophy

Pipeline-first and dimension-aligned. The codebase mirrors the generation pipeline
(Ingest → Analyze → Classify → Plan → Write → Review → Assemble → Deploy) and maps
each concern onto a HarnessX dimension. The atomic content unit is a **segment**;
everything else exists to produce, tag, assemble, and quality-gate segments.

## Directory Patterns

### Generator package
**Location**: `docuharnessx/`
**Purpose**: the `make_docgen()` bundle, processors, ontology, planner, writer, assembler.
**Example**: `docuharnessx/bundle.py` (composes `make_docgen`), `docuharnessx/ontology/`.

### Pipeline stages
**Location**: `docuharnessx/<stage>/` (e.g. `ingest/`, `analyze/`, `classify/`, `plan/`, `write/`, `review/`, `assemble/`, `deploy/`)
**Purpose**: one module per pipeline stage, each a processor or processor group.

### Ontology
**Location**: `docuharnessx/ontology/`
**Purpose**: the tri-modal model — Role, Subject tags, Intent — and segment frontmatter schema + validation.

### Templates / theme
**Location**: `templates/` and MkDocs theme config
**Purpose**: Material for MkDocs scaffolding, role landing-page skeletons (SCQA), nav generation.

### CLI
**Location**: `docuharnessx/cli.py` (entry point `dhx`)
**Purpose**: run the generator against a target repo.

### Specs & steering (Kiro)
**Location**: `.kiro/specs/` and `.kiro/steering/`
**Purpose**: spec-driven development artifacts; roadmap.md + per-feature specs.

## Naming Conventions

- **Files/modules**: snake_case (Python).
- **Processors**: `<Concern>Processor` or hook-decorated functions (HarnessX style).
- **Segments**: Markdown with frontmatter `{id, title, roles: [...], subjects: [...], intent: <one>, summary, related: [...]}`.
- **Tags**: `role:<x>`, `subject:<x>`, and `intent:<x>` namespaced for the MkDocs tags plugin.
- **Ontology config**: per-project vocabulary at `.docuharnessx/ontology.yaml` (roles, intents, subjects); a shipped default profile seeds it.

## Code Organization Principles

- Keep `make_docgen` composition declarative; behavior lives in processors.
- Stages communicate through the harness state/slots and the segment store, not globals.
- The coverage planner is deterministic and testable; the LLM-judge is gated and logged.
- Output is plain Markdown + `mkdocs.yml`; publishing is a thin deploy step.

---
_Document patterns, not file trees. New files following patterns shouldn't require updates_
