# Research — comprehension-visuals

## Visual Paradigm analog (not the product)

Visual Paradigm **Textual Analysis** records a problem statement, lets the analyst highlight terms, add them to a **Glossary Grid** (definition + aliases), and then **highlights every occurrence** of those terms across diagrams and text. Ctrl/click jumps to the glossary. Candidates can become model elements. Requirements can be generated from candidate text.

What we adopt:

| VP idea | DocuHarnessX analog |
|---|---|
| Glossary Grid | `.docuharnessx/glossary.yaml` + assembled `glossary.md` index |
| Aliases + definition | term, aliases, definition, related term ids, source pages |
| Highlight in running text | assemble-time wrap of whole-word matches (skip code fences) |
| Ctrl-click to glossary | in-page link + hover definition |
| Related / candidate view | mermaid of related terms + backlinks to pages |
| Requirements from text | optional cards from existing `shall`/EARS sentences in the repo |

What we do **not** adopt: VP desktop, SysML/ReqIF round-trip, color-coded highlighter UI for authors, embedding VP files.

## MkDocs search vs related-node browsing

Material **search** is **lunr.js**: client-side full-text over headings and body. It is **not** semantic. Tags plugin already indexes page tags and can list pages per tag. Neither gives “this keyword is a domain term with aliases and neighbors.”

Plan:

- Keep `search` (lunr). Glossary terms and definitions become searchable because they are real pages/sections.
- Add a **Glossary** nav entry (term index).
- Autolink terms in assembled HTML/Markdown so a reader can jump without using search.
- Related-node browsing is a small graph on each term page + “appears on” list — that *is* the semantic layer, grounded in the glossary, not in embeddings.

Third-party plugins (`mkdocs-ezglossary`, `mkdocs-glossary`) exist but pull extra MkDocs plugin surface into `--strict` builds. Prefer **our own assemble-time rewrite** (deterministic, no plugin) unless a plugin is proven byte-stable. Design owns the choice.

## Mermaid kinds already allowed

`structure_gate` already accepts `flowchart`, `graph`, `sequenceDiagram`, `classDiagram`, `erDiagram`, `stateDiagram`, `mindmap`, `pie`, `timeline`, `C4Context`, `gantt`, `gitGraph`, `journey`, `quadrantChart`, `requirementDiagram`. **Sankey** (`sankey-beta`, Mermaid ≥ 10.3) is **not** yet in the allow-list and must be added when we emit it.

Sankey syntax is CSV `source,target,value`. Cycles are poorly supported; keep lineage acyclic or flatten.

## Sankey for entrypoints (software, quant, ML)

When volumes are unknown, each hop weight = 1 (or file count). Label the figure “structural flow, not measured volume.”

**Software CLI**

```
argv / config → entrypoint → components → stores / stdout
```

**Quant / research**

```
market data / alternative data → clean → features → signals → portfolio / risk → reports
```

**AI / ML**

```
raw data → splits → features → train → model artifact → eval → serve
```

Sources for nodes: detected entrypoints, `data/` dirs, notebooks, config that names paths, pipeline DSL I/O, cited files on the startup/component pages.

## DAG autogen

Detect, do not invent:

| Signal | Typical files |
|---|---|
| Airflow | `dags/*.py` with `DAG(` / `@dag` |
| Prefect | `@flow` / `@task` |
| Dagster | `@asset` / `@job` / `Definitions` |
| Kedro | `pipeline.py`, `catalog.yml` |
| Snakemake | `Snakefile` |
| dbt | `models/**/*.sql`, `dbt_project.yml` |
| Makefile | `Makefile` targets |
| GitHub Actions | job `needs:` |
| Metaflow / Luigi | class `FlowSpec` / `Task` |
| Notebooks | `.ipynb` in `notebooks/` as coarse stages |

If none match: coarse DAG `entrypoint → component → artifact` from existing `RepoAnalysis`. Omit rather than hallucinate edges.

Render as Mermaid `flowchart LR` (DAG) at depth 4–7; a collapsed named-stage version at depth 3.

## Depth assignment (locked)

| Depth | Audience | Pictures |
|---|---|---|
| 1 | Adopter | C4 context **or** mindmap of “what this is”; glossary highlight on |
| 2 | Evaluator | C4 container; coverage pie; glossary related-nodes |
| 3 | Operator | Sequence of a typical run/request; collapsed pipeline DAG; high-level sankey |
| 4 | Integrator | Class/public-surface diagram; DAG with named tasks |
| 5 | Programmer | Current file flowcharts; DAG with files |
| 6 | Maintainer | Sequence with modules; denser DAG |
| 7 | Internals | Sankey with stores/paths; requirement cards; grounding files |

Missing evidence → omit that picture, do not fill with template boxes.

## Compliance self-assessment (reference, not an audit)

Ask at **interactive init** and again at **`--manage` re-init**:

```
Compliance topics, comma-separated [none]:
  iso27001, pci-dss, nis2, cra, gdpr
```

`--default` writes `frameworks: []`. Unselected regimes are **gray columns**, never red.

This is a **self-assessment heatmap**. Green means “repo evidence for this automated check,” not “certified.” Publish that disclaimer on the page.

### Shared pillars (rows)

Cross-walk is indicative (clause numbers are orientation, not a statement of applicability):

| Pillar id | Pillar | ISO 27001 | PCI DSS | NIS2 | CRA | GDPR |
|---|---|---|---|---|---|---|
| inventory | Asset & data inventory | A.5 / A.8 | 9, 12 | Art. 21 | Art. 13 | Art. 30 |
| access | Access control | A.5.15+ | 7, 8 | access | | Art. 32 |
| crypto | Cryptography | A.8.24 | 3, 4 | | | Art. 32 |
| logging | Logging & monitoring | A.8.15+ | 10 | | | Art. 32 |
| vuln | Vulnerability management | A.8.8 | 6, 11 | | Art. 13 | |
| ssdlc | Secure development | A.8.25+ | 6 | | essential reqs | Art. 25 |
| supply | Supply chain / SBOM | A.5.19+ | 12.8 | supply chain | SBOM | Art. 28 |
| incident | Incident response | A.5.24+ | 12.10 | Art. 23 | Art. 11 | Art. 33–34 |
| continuity | Backup & continuity | A.8.13+ | | | | |
| privacy | Privacy & data-subject rights | | | | | Art. 12–22 |
| cde | Cardholder data environment | n/a | 1–3 | n/a | n/a | n/a |
| governance | Policies & governance docs | A.5.1 | 12 | | | Art. 24 |
| training | Awareness / training | A.6.3 | 12.6 | | | |

`n/a` → always **gray** for that regime, even if the regime is selected. `cde` is gray for every regime except PCI DSS.

### Automated evidence → color

Deterministic path/content checks (examples, not exhaustive):

| Pillar | Green-ish signals | Yellow-only signals |
|---|---|---|
| inventory | `CODEOWNERS`, software catalog, data-class docs | README “architecture” only |
| access | SSO/OIDC config, `CODEOWNERS`, secret-scan job | auth code without policy |
| crypto | TLS/secret-mgmt docs plus no secrets in tree | crypto libraries imported |
| logging | structured logging + retention note | log calls in code |
| vuln | Dependabot/Renovate + CI scanner | lockfile only |
| ssdlc | CI tests + SAST/lint on default branch | tests without CI |
| supply | SBOM artifact or generator job | `requirements.txt` only |
| incident | `SECURITY.md` with contact + process | `SECURITY.md` stub |
| continuity | backup/restore runbook | “we take backups” in README |
| privacy | privacy policy / DPA / RoPA | “GDPR” mentioned once |
| cde | (PCI selected) CDE boundary doc | card-brand mention only |
| governance | security policy in-repo | CONTRIBUTING only |
| training | training record or security guidelines for contributors | none |

**Red:** pillar applies, regime in scope, no matching evidence and no override.

**Operator override** in `.docuharnessx/compliance.yaml` wins the cell color; automated evidence still listed.

### Visual

Markdown table with CSS classes `dhx-na` (gray), `dhx-fail` (red), `dhx-partial` (yellow), `dhx-pass` (green). Depth 1–2: table only. Depth 5–7: table + evidence paths per cell.

## Adjacent code

- `docuharnessx/assembler/graphs.py` — flowchart-only emitters; extend or sibling modules per kind.
- `docuharnessx/assembler/depth.py` — `wrap_layer(min_depth, markdown)`.
- `docuharnessx/site_config.py` — theme + default depth.
- `docuharnessx/analysis/detectors.py` — entrypoints, components, public surface, CI; **no** pipeline DSL yet.
- `docuharnessx/ontology` — roles/intents/subjects seed glossary, not a replacement for it.
- Living pages — text that gets term highlighting at assemble (source pages stay unwrapped).
