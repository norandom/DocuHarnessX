# Technology Stack

## Architecture

DocuHarnessX is a **Python documentation pipeline** with a **HarnessX writer**.
The CLI (`dhx`) validates the target, resolves a model, and runs:

**analyze → questions → write → gate → assemble → (optional) deploy**

HarnessX is **not** the pipeline bus. It is used only for the per-page writer:
a bounded agent with a read-only workspace on the target repo and the built-in
read/grep/glob/bash tools. Model binding stays `ModelConfig(main=...).agentic(...)`
on that writer harness — never embedded in a dummy outer `HarnessConfig`.

Analyze remains the existing deterministic `RepoAnalysis` (no model required).
The question planner is deterministic over that analysis. The substance gate is
deterministic over the written body. Assemble/deploy stay MkDocs-based.

## Core Technologies

- **Language**: Python 3.12 (matches HarnessX)
- **Writer runtime**: HarnessX (github.com/Darwin-Agent/HarnessX) as a library
- **Doc framework**: Material for MkDocs (output target)
- **Packaging/env**: `uv`
- **Publish**: `mkdocs build` / optional `mkdocs gh-deploy` / GitHub Actions

## Key Libraries

- `harnessx` — per-page agent loop, workspace, control budgets, journal
- `mkdocs` + `mkdocs-material` — site build
- `pyyaml` — config and MkDocs emit

## Development Standards

### Type Safety
Follow HarnessX conventions. Do not add type annotations/docstrings to unchanged code.

### Composition Rules (from HarnessX) — writer only
- Model goes in `ModelConfig`, never `HarnessConfig`.
- Compose the writer harness with `|`; rely on conflict detection.
- Core pipeline modules do not import HarnessX except at the writer adapter.

### Testing
- Question planner and substance gate: deterministic unit tests, no model.
- Writer: credential-free scripted fake that **reads fixture files**, then
  returns a grounded body — or returns an ungrounded body that must be omitted.
- Never pin template-dump text (`Locate X`, `Run the smallest action`) as a
  successful page body.
- E2E: accepted pages name real fixture symbols; a no-explore run emits zero
  pages and a report.

## Development Environment

### Common Commands
```bash
# Env:    uv venv --python 3.12 .venv && source .venv/bin/activate && uv pip install -e .
# Run:    dhx <path-to-target-repo> --out DIR --deploy-mode build-only
# Serve:  cd <out>/site && python -m mkdocs serve
```

## Key Technical Decisions

1. **Python pipeline, HarnessX writer** — the dummy `DONE` outer agent is retired.
   Analyze/plan/gate/assemble do not need an agent loop.
2. **No publishable fallback** — writer failure is an omitted page, not a
   rendered blueprint.
3. **Native OpenAI provider for OpenAI-compatible tool-calling** — LiteLLM's
   `content: null` path killed the multi-turn writer (see `model_resolver.py`).
4. **Material for MkDocs** — Markdown-native, polyglot, already shipped.
5. **Page metadata is slim** — id, title, summary, body, subjects, related,
   citations. Reader roles and intents are not required to emit a page.

---
_Document standards and patterns, not every dependency_
