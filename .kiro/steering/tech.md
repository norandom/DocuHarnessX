# Technology Stack

## Architecture

DocuHarnessX is a **HarnessX bundle + CLI**. The generator is an agentic pipeline
expressed as a composed `HarnessConfig` (`make_docgen()`), bound to a model via
`ModelConfig(main=...).agentic(config)`. It reuses HarnessX's processor dimensions
rather than reinventing them:

- **Tools** — read/scan the target repo (Read/Grep/Glob, structure walk, CI/config parse)
- **Context** — assemble per-role, per-segment writing context
- **Evaluate** — LLM-judge grades each segment = the COBESY anti-cringe gate
- **Control** — cost guard + loop detection for large repos (25–40k LOC)
- **Observe** — HarnessJournal (JSONL) audit trail of what was documented and why
- **Memory** — segment reuse across roles
- **Train** — doc-quality rewards can evolve the generator (future)

Pipeline stages: **Ingest → Analyze → Classify → Plan → Write → Review → Assemble → Deploy.**

## Core Technologies

- **Language**: Python 3.12 (matches HarnessX)
- **Agent framework**: HarnessX (github.com/Darwin-Agent/HarnessX) as a dependency
- **Doc framework**: Material for MkDocs (output target)
- **Packaging/env**: `uv` (HarnessX convention)
- **Publish**: `mkdocs gh-deploy` / GitHub Actions; `mike` for versioning

## Key Libraries

- `harnessx` — harness composition, processors, evaluation, journal
- `mkdocs` + `mkdocs-material` — site build + theme
- MkDocs plugins: `tags` (ontology axis A), `awesome-pages` (dynamic nav),
  `gen-files` + `literate-nav` (generated nav), `mike` (versioning)

## Development Standards

### Type Safety
Follow HarnessX conventions. Do not add type annotations/docstrings to unchanged code.

### Composition Rules (from HarnessX)
- Model goes in `ModelConfig`, never `HarnessConfig`.
- Compose processors with `|`; rely on conflict detection (no silent overwrites).
- Core never imports third-party/benchmark libs; adapters live outside core.
- Append processors via `{**config.processors, hook: [...existing, proc]}`, never replace.

### Testing
Unit-test ontology tagging, segment assembly, and the coverage planner deterministically;
treat LLM-judge output as gated, logged, and reproducible via HarnessJournal traces.

## Development Environment

### Common Commands
```bash
# Env:    uv venv --python 3.12 .venv && source .venv/bin/activate && uv pip install -e .
# Run:    dhx <path-to-target-repo>           # generate docs for a project
# Serve:  mkdocs serve                          # preview the generated site
# Deploy: mkdocs gh-deploy                       # publish to GitHub Pages
```

## Key Technical Decisions

1. Build on HarnessX (real bundle), not standalone — maximize reuse of Evaluate/Control/Observe.
2. Material for MkDocs over Sphinx/Docusaurus — aesthetics + native tags + Markdown-native + polyglot.
3. Content segments are Markdown files with frontmatter `{id, title, roles[], subjects[],
   intent, summary, related[]}`; role views are assembled by filtering, giving reuse +
   interconnection. Tags are namespaced `role:` / `subject:` / `intent:`.
4. The ontology vocabulary (roles, intents, subject prefixes/tags) is **project-configurable**
   via a per-project ontology config file (e.g. `.docuharnessx/ontology.yaml`). The 10
   roles / 13 intents are a shipped **default profile**, not closed enums. `dhx init`
   asks per project or seeds the default; segments validate against the loaded vocabulary.
   This is what keeps the harness reusable across projects.

---
_Document standards and patterns, not every dependency_
