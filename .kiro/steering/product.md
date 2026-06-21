# Product Overview

**DocuHarnessX** is a human-centric, role-based documentation generator that turns a
software project (target size 25–40k LOC) into a published, aesthetic GitHub Pages
site. It is built as a **HarnessX bundle** (`make_docgen`) plus a `dhx` CLI: an
agentic pipeline that reads a codebase and emits documentation people actually adopt.

The product's premise: readers have no time, and static docs do not drive adoption.
DocuHarnessX applies a **COBESY** (Cognitive-Behavioral-Systemic) flow so each reader
reaches first success on the shortest path, framed for their role.

## Core Capabilities

- **Role-based assembly** — one corpus, many views. Each project's reader roles get a
  landing page and a guided agenda built by filtering shared content.
- **Tri-modal ontology** — every content segment is tagged on three axes
  (Subject = what/how, Intent = why-reading, Role = who) so segments are reused and
  interconnected rather than duplicated.
- **Project-configurable vocabulary (reusability core)** — the roles, intents, and
  tags are NOT hardcoded. They are loaded from a per-project ontology config file; the
  harness asks at setup (`dhx init`) which roles/intents/tags apply, or accepts a
  shipped default profile. A different project gets a different vocabulary, so the same
  `make_docgen` harness stays reusable everywhere.
- **COBESY adoption flow** — per-role SCQA opener → one key action first (Minto) →
  progressive disclosure → REDUCE-barrier fast path to first success.
- **Decision-intelligence planning** — a planning stage decides *which* segments a
  given project needs (coverage matrix), not a fixed template.
- **Quality-gated generation** — an LLM-judge (HarnessX Evaluate dimension) grades
  every segment for clarity, MECE, working-memory fit, and role-fit before publish.
- **Aesthetic publish** — emits a Material for MkDocs site, deployed to GitHub Pages.

## Default Profile — Reader Roles (10)

These ship as the **default profile**, not as a fixed enum. A project may keep, trim,
or extend them via its ontology config.

Core: Possible Adopter · Developer · Tech-savvy User · Manager · DevOps/Admin ·
Researcher.
Extended: Security/Compliance Officer · Contributor · Integrator/API consumer ·
Support/On-call (SRE).

## Default Profile — Intent Axis

Default intents (also project-configurable): install · configure · use · troubleshoot ·
monitor · operate · integrate · extend · evaluate · assess-quality · understand ·
contribute · deliver.

## Target Use Cases

- Auto-document an existing repo with near-zero authoring time (reference example:
  `/home/mc/Source/malware_hashes`, a ~6.8k LOC Go forensic-hashing CLI).
- Give evaluators/managers a fast "should we adopt this, and how quickly" path.
- Keep docs interconnected and reusable as the project grows.

## Value Proposition

Most generators produce reference dumps. DocuHarnessX produces an **adoption
instrument**: role-targeted, COBESY-structured, quality-gated, and beautiful — built
on a composable, evolvable harness so doc quality improves over time.

---
_Focus on patterns and purpose, not exhaustive feature lists_
