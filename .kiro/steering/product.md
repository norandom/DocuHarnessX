# Product Overview

**DocuHarnessX** generates developer documentation from a software repository: a
bounded set of pages that answer **software questions** grounded in real source.
The operator runs `dhx <repo> --out DIR` and gets a previewable site — or an
honest empty site plus a report when nothing could be grounded.

The product's premise: developers already have the code. Generated docs are worth
keeping only when they teach something the README and a five-minute read of the
cited files do not. Outlines that restate planning prompts are worse than no site.

## Core Capabilities

- **Explore-first writing** — each page is written by a bounded agent that reads
  the target repository. The page is not authored before that read.
- **Question-shaped corpus** — pages answer questions such as how the program
  starts, what a component does, where configuration is loaded, how to extend a
  public surface. Reader job titles are not the page unit.
- **Fail-closed publish** — a page that was not grounded in source is omitted.
  Missing pages plus a run report beat a site full of generic instructions.
- **Substance gate** — accepted pages cite real `file:line` locations, name real
  symbols, and do not consist of template phrases.
- **Wiki-style publish** — accepted pages become a Material for MkDocs site
  organised by those questions. Optional GitHub Pages deploy remains available.

## Target Use Cases

- Auto-document an existing repo for developers who will work in it (reference:
  `/home/mc/Source/malware_hashes`, a ~6.8k LOC Go forensic-hashing CLI).
- Dogfood on DocuHarnessX itself: keep a page only if it teaches something.
- Bounded output for ~25–40k LOC targets — a handful of grounded pages, not a
  combinatorial Role × Intent matrix.

## Value Proposition

Most generators dump reference or fill a template. DocuHarnessX produces a small
set of grounded answers about how *this* repository actually works.

## Prior generation (Waves 0–4)

The first shipped product was a role-based, COBESY-structured adoption site
driven by an 8-stage HarnessX dummy run. That authoring model is retired by
Wave 5 (`explore-first-simplification`). Historical specs remain under
`.kiro/specs/` for the old pipeline; they are not the current source of truth.

---
_Focus on patterns and purpose, not exhaustive feature lists_
