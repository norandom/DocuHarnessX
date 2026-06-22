# Brief — github-pages-deploy

## Feature

Make the **Deploy** pipeline stage real: publish the assembled Material for MkDocs
site to the **TARGET project's** GitHub Pages, multi-mode, defaulting to emitting a
GitHub Actions workflow into the target repo so it self-publishes. Wave 3, spec #2 —
the finale that makes DocuHarnessX a reusable, publishing doc generator.

## Why It Exists

Replaces the `deploy` no-op stub. The assembler produced a per-target MkDocs site
source; this stage gets it published to the right project's Pages — without coupling
to DocuHarnessX's own repo, and reusable across arbitrary target projects.

## In Scope

- Replace `docuharnessx/stages/deploy.py` no-op stub IN PLACE (stable
  STAGE_NAME='deploy', DeployStage, factory, module path — registry/bundle untouched).
- Consume the `AssembledSite` from `SLOT_ASSEMBLED_SITE` (site source dir + mkdocs.yml).
- **Multi-mode deploy (configurable via `.docuharnessx/` config or `dhx` flags;
  DEFAULT = emit-ci-workflow):**
  - **emit-ci-workflow (DEFAULT):** write `mkdocs.yml` + `docs/` + a
    `.github/workflows/docs.yml` (build + deploy-pages job) INTO the TARGET repo working
    tree, so the target's own GitHub Actions publishes Pages on push. DocuHarnessX
    writes files for the user to review/commit — **no auto-push**.
  - **gh-deploy:** run `mkdocs gh-deploy` to push the built site to the target repo's
    `gh-pages` branch (needs target remote + push access at run time).
  - **build-only:** produce the static site (`mkdocs build`) in the output dir; no publish.
- **MULTI-PROJECT (locked requirement):** derive the target `owner/repo`, remote, and
  default branch from the target's `git remote origin`; compute the Pages URL +
  `/<repo>/` base-path; thread them to the emitted workflow / gh-deploy. NEVER deploy
  to DocuHarnessX's own repo. Per-project isolation. Graceful, explicit error when a
  mode's prerequisites are missing (no remote, no push access, non-GitHub).
- **Build validation:** run `mkdocs build` on the assembled site to confirm it builds
  with the per-target base-path before declaring success (requires `mkdocs` +
  `mkdocs-material` installed). The push (gh-deploy) is the ONLY network action and is
  never exercised in tests.
- **Output seam:** a `DeployResult` (mode, written/built paths or target branch, target
  Pages URL, status) recorded in the journal (+ a slot if downstream needs it).

## Out of Scope

- Assembling the site (mkdocs-site-assembler). The rest of the pipeline.

## Dependencies

- `mkdocs-site-assembler` — `AssembledSite` + `SLOT_ASSEMBLED_SITE` (consume verbatim).
- `harness-bundle-skeleton` — `RunContext`, slots, stage base/registry.

## Key Constraints

- Python 3.12. emit-ci-workflow + build-only are deterministic + credential-free
  testable (assert emitted files/workflow content + that `mkdocs build` succeeds with
  the per-target base-path); gh-deploy's push is not exercised in tests (no network/
  credentials). Configurable, multi-project, per-target isolation. Never touch
  DocuHarnessX's own repo/Pages.

## Acceptance Signal

Given an `AssembledSite` + a target repo with a GitHub remote, the Deploy stage in the
default mode writes a valid `.github/workflows/docs.yml` + `mkdocs.yml` + `docs/` into
the target tree (Pages base-path = `/<repo>/`), runs `mkdocs build` successfully, and
records a `DeployResult` with the target Pages URL — credential-free, no auto-push,
never touching DocuHarnessX's own repo; covered by unit tests across modes + varying
target remotes.
