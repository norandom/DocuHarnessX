# Brief — ontology-engine

## Feature

The tri-modal ontology and the content-segment contract that every other DocuHarnessX
stage reads and writes. This is Wave 0 foundation #1 and the most-shared seam in the
project: freeze its schema early.

## Why It Exists

DocuHarnessX assembles role-based docs by **filtering reusable segments**, not by
templating per role. That only works if there is one rigorously defined ontology and
one segment schema that the planner, writer, review gate, and assembler all agree on.

## In Scope

- **Three axes** as first-class, validated vocabularies:
  - **Role** (who): the 10 roles — Possible Adopter, Developer, Tech-savvy User, Manager,
    DevOps/Admin, Researcher, Security/Compliance Officer, Contributor, Integrator/API
    consumer, Support/On-call (SRE).
  - **Intent** (why-reading): install, configure, use, troubleshoot, monitor, operate,
    integrate, extend, evaluate, assess-quality, understand, contribute, deliver.
  - **Subject** (what/how): open namespace with typed prefixes — `component:`, `tech:`,
    `artifact:`, `topic:`.
- **Segment schema**: Markdown file with frontmatter `{id, title, roles[], subjects[],
  intent, summary, related[]}`. Define required vs optional fields, types, allowed values.
- **Validation**: reject unknown roles/intents, malformed frontmatter, missing required
  fields; validate `related[]` cross-links resolve.
- **Tag namespacing**: deterministic mapping segment → MkDocs tags (`subject:*`,
  `intent:*`, `role:*`) for the Material tags plugin.
- **Segment store interface**: the read/write API later stages use (put segment, query
  by axis filter, list, resolve cross-links). Define the interface contract; a simple
  filesystem-backed implementation is acceptable.
- **Reuse model**: a single segment may carry multiple roles/subjects; define how a role
  view is derived (filter by role + intent ordering).

## Out of Scope

- Generating segment *content* (that is `cobesy-writer`).
- Deciding *which* segments a project needs (that is `classification-coverage-planner`).
- MkDocs site assembly/nav (that is `mkdocs-site-assembler`).

## Dependencies

None (Wave 0).

## Key Constraints

- Python 3.12; consumable from a HarnessX processor.
- Schema is the frozen cross-spec contract — design for stability and explicit versioning.
- Deterministic and unit-testable (no LLM calls in this spec).
- Tag names namespaced exactly `subject:` / `intent:` / `role:`.

## Acceptance Signal

Given a set of segment files, the engine validates them, rejects malformed ones with
clear errors, answers axis-filtered queries (e.g. "all segments for role=Manager,
intent=evaluate"), and emits the namespaced tag set — all covered by unit tests.
