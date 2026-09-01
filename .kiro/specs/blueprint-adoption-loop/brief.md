# Brief — blueprint-adoption-loop

## Feature

A first-class **adoption loop** for DocuHarnessX on a target repository:

1. Default **`dhx init` is an interactive interview**: credentials first (API key, base URL, model — DeepSeek defaults on Enter; an existing key is shown as `***` and Enter or `***` keeps it), then the setup harness **displays ontology proposals** for the operator to accept or change.
2. Setup writes the shipped blueprint version plus the agreed ontology under `.docuharnessx/`. Secrets go only to `.env` (gitignored). **Journals, ontology, living pages, and the adoption record are project files and must not be gitignored** — evolution reads the journals.
3. They **grow a sufficient document over time** with incremental grounded writes plus **multi-step** interactive refine (not one rewrite call).
4. The **refine/setup harness evolves from session traces** so later similar work takes fewer steps. Living pages stay fail-closed. This is harness adaptation (`MetaAgent.evolve` on tools / processors / templates), not model RL training.

Refine is wired to the explore-first **page** store, not the retired `<out>/segments` store.

## Why It Exists

One-shot `dhx run` and one-shot `rewrite_segment` are the wrong product story. Ontology setup is more than dumping a YAML file. Operators need several refine turns per page; those traces should make the *harness* cheaper next time, not only replace one markdown file.

## In Scope

- Interactive setup interview: ontology proposals, API key + base URL (DeepSeek default on Enter, existing key masked).
- Setup harness: init + manage ontology from the shipped blueprint and the target repo.
- Journals stored in the project and **not** gitignored; `.env` remains gitignored.
- Adoption record (blueprint version) plus local vocabulary the harness and the operator can both edit.
- Incremental generation that does not silently wipe refined pages.
- Multi-step refine sessions over living pages (several explore/write/gate cycles per page until accept or stop).
- Harness evolution from those traces aimed at **reducing steps-to-accept**; candidate harnesses are gated and must not weaken the substance gate.
- Operator-visible coverage, step counts, and sufficiency.

## Out of Scope

- Training or replacing the underlying LLM (`harnessx.rl` weight training).
- Changing question-planning rules or substance-gate accept criteria.
- Hosted SaaS, multi-repo aggregation, a new theme, Role × Intent pages.
- Evolving the substance gate itself away.

## Dependencies

- `explore-first-simplification` (pages, pipeline, substance gate, question site).
- `ontology-engine` (vocabulary schema; harness writes files the engine already validates).
- `docuharnessx-mcp-refine` (retarget store; extend from one-shot tools to a session).
- HarnessX `meta_harness.MetaAgent` (evolve writer/setup configs from journals).
- `github-pages-deploy` (publish modes after a non-empty assemble).
