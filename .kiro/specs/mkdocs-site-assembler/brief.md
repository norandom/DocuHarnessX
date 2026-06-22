# Brief — mkdocs-site-assembler

## Feature

Make the **Assemble** pipeline stage real: turn the gate-accepted `Segment`s into a
**Material for MkDocs** site source tree (`docs/*.md` + `mkdocs.yml`), with per-role
landing pages, tags-driven nav, and cross-links — and crucially, **site identity
derived from the target project** so the same generator works for any repo. Wave 3,
spec #1.

## Why It Exists

Replaces the `assemble` no-op stub. The pipeline has produced quality-gated content
segments; this stage arranges them into a navigable, aesthetic site that the deploy
stage publishes. It is the bridge from "segments in a store" to "a website".

## In Scope

- Replace `docuharnessx/stages/assemble.py` no-op stub IN PLACE (stable
  STAGE_NAME='assemble', AssembleStage, factory, module path — registry/bundle untouched).
- Consume the `ReviewReport` from `SLOT_REVIEW_REPORT` (use `accepted` — the passed
  segments), the loaded `Vocabulary`, and the `RepoAnalysis` (for site identity
  context). Reuse ontology `build_role_view` (per-role, intent-ordered) and
  `emit_tags` (`role:`/`subject:`/`intent:`). Treat `Segment`s read-only.
- Emit a **Material for MkDocs** source tree under the output dir:
  - one `docs/*.md` page per accepted segment (body + frontmatter → page + tags),
  - **per-role landing pages + guided agendas** (COBESY: SCQA-style intro, ordered by
    `Vocabulary.intent_order()` via `build_role_view`),
  - tags-driven nav (Material `tags` plugin), cross-links (`related`), admonitions /
    content-tabs for role switching,
  - a `mkdocs.yml` with the Material theme + tags plugin + generated nav.
- **MULTI-PROJECT site identity (locked requirement):** `site_name`, `repo_url`,
  `repo_name`, `edit_uri`, and **`site_url` + the `/<repo>/` Pages base-path** are
  derived from the TARGET repo's `git remote origin` (parse `owner/repo`), overridable
  via `.docuharnessx/` config or `dhx` flags. Set `site_url`/`use_directory_urls` so
  links + assets resolve under the project's Pages subpath. Graceful fallback when no
  remote / non-GitHub. NEVER hardcode DocuHarnessX's own identity.
- Declare `mkdocs` + `mkdocs-material` as dependencies. Deterministic assembly (no
  model call); unit-testable.
- **Output seam:** an `AssembledSite` value object (site source dir + `mkdocs.yml`
  path + site metadata) on a new `SLOT_ASSEMBLED_SITE` (append-only `types.py` +
  `RunContext` accessor) for the deploy stage.

## Out of Scope

- Publishing / GitHub Pages (github-pages-deploy). Repo scan/plan/write/review.

## Dependencies

- `quality-review-gate` — `ReviewReport.accepted` (consume verbatim).
- `ontology-engine` — `Segment`, `build_role_view`, `emit_tags`, `Vocabulary`.
- `repo-ingestion-analysis` — `RepoAnalysis` (site identity context).
- `harness-bundle-skeleton` — `RunContext`, slots, stage base/registry.

## Key Constraints

- Python 3.12. Deterministic assembly (byte-stable site source for fixed inputs),
  unit-testable; the generated `mkdocs.yml` must build cleanly under `mkdocs-material`
  with the per-target base-path. `AssembledSite` is the seam the deploy stage consumes
  — design for stability. Configurable vocabulary; per-project isolation.

## Acceptance Signal

Given an accepted-segment set + a target with a GitHub remote, the Assemble stage
writes a Material for MkDocs source tree (per-role nav, tags, cross-links) with a
`mkdocs.yml` whose `site_url`/base-path match the target's `/<repo>/` Pages URL,
surfaced via `SLOT_ASSEMBLED_SITE`; `mkdocs build` succeeds on it; deterministic;
covered by unit tests across default + custom vocabularies and varying target remotes.
