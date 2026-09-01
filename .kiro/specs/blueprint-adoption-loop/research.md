# Research Log — blueprint-adoption-loop

## Discovery scope

Light / extension discovery. The generation core already exists (explore-first pipeline, ontology init, MCP refine). This spec retargets refine, adds an adoption record, incremental writes, and sufficiency.

## Key findings

1. **Page unit is already explore-first.** `Page` has `id, title, summary, body, subjects, related, cited_files` and lives in `docuharnessx/pages/model.py`. The pipeline persists assembled markdown under `<out>/pages` and `docs/`. There is no first-class page store in the *target* repo.

2. **`dhx init` already writes vocabulary.** `ontology_setup.run_init` writes `.docuharnessx/ontology.yaml` from `default_profile()` or interactive answers. It does **not** record a blueprint version or sufficiency. Overwrite is refused without `--force`.

3. **MCP refine is disconnected.** `RefineSession` uses `FilesystemSegmentStore` at `<out>/segments`. The current `dhx run` does not write that store. Tool names (`rewrite_segment`, …) can stay as operator verbs but must bind to living pages.

4. **HarnessX evolution exists but is unused.** `harnessx.meta_harness.MetaAgent.evolve` takes traces and returns a `HarnessConfig` changeset (tools / processors / templates). `harnessx.rl` is model training — still out. Steering still forbids HarnessX as the *pipeline bus*; setup, write, refine, and evolve are the allowed harness call sites.

5. **Incremental write is missing.** `write_questions` always attempts every planned question. A second run will rewrite pages a human already refined unless we skip existing living pages.

## Decisions

| Decision | Choice | Why |
|---|---|---|
| Blueprint identity | Named constant + version string shipped with the package, written into `.docuharnessx/adoption.yaml` | Avoid changing the frozen ontology.yaml schema (ontology-engine). |
| Living store | Filesystem under `.docuharnessx/pages/` in the **target** repo | Survives throwaway `--out`; versionable with the project. Assemble still emits `docs/` / site. |
| Incremental default | Skip questions that already have a living page; `--regenerate` / per-id regenerate to overwrite | Matches "build over time". |
| Refine | Retarget MCP session to living pages; reuse explore-first writer + `validate_page_body` + `guidance` | No second engine. Do not use `AgenticProseRunner`. |
| Sufficiency | Operator declaration in adoption.yaml; status command lists coverage; declaration goes stale after living pages change | "Sufficient" is a team decision, not a hidden score. |
| Setup | Harness write-scoped to `.docuharnessx/`; `--default` / no-model dumps YAML | Ontology is managed, not only dumped. |
| Refine | Multi-cycle session, same writer + substance gate | One-shot rewrite is not enough. |
| Evolution | `MetaAgent.evolve` on writer/setup configs; fitness = fewer cycles-to-accept; reject gate-weakening | Reduce steps without RL-training the model. |
| `harnessx.rl` | Out | We evolve the harness, not the weights. |

## Risks

- MCP handler names still say "segment" while the store is pages — keep names if tests/clients depend, or alias. Prefer aliases (`list_pages`) with old names as wrappers if needed.
- `docs/` vs `.docuharnessx/pages/` drift if someone hand-edits `docs/` only. Living store is authoritative; assemble overwrites site emit.
- Ontology-engine validation still owns vocabulary shape; adoption.yaml must not duplicate roles.

## Interactive setup and journals (2026-09-01)

Today `dhx init` without `--default` already asks blank role/intent/subject questions. That is not enough: the **harness** must display proposals from the blueprint + repo, and the operator accepts or edits.

Interview order:

1. Credentials (needed before the harness can propose).
2. Setup harness produces ontology proposals.
3. Display proposals; operator accepts or edits.
4. Write ontology + adoption + journal.

Credential UX:

- Base URL prompt shows `https://api.deepseek.com`; Enter uses it.
- Model prompt shows `deepseek-v4-flash`; Enter uses it.
- Existing API key is displayed as `***`. Enter **or** typing `***` keeps the existing key. Never print the raw secret.
- Empty API key with none present → no-model seed (do not write a blank key).
- Secrets only in `<project>/.env` (gitignored). `--default` / non-TTY skip prompts.

Journals:

- Evolution reads **project journals**. Today `.gitignore` ignores all of `.docuharnessx/`, which would hide journals.
- Change: remove the blanket `.docuharnessx/` ignore. Track `journals/`, `pages/`, `ontology.yaml`, `adoption.yaml`, `harnesses/`. Ignore `.env` and `.docuharnessx/out/` only.

## Synthesis

Build on init + pipeline + MCP. Add a setup harness and a MetaAgent evolve wrap whose only advertised win is fewer refine cycles. Do not train the model. Living pages and the substance gate stay above the evolved genome.
