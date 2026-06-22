# DocuHarnessX Tutorial

This walks you through installing DocuHarnessX, pointing it at a model (OpenAI or
others), and running it against a project — including running it on **itself**.

DocuHarnessX reads any software repository and generates a human-centric, role-based
[Material for MkDocs](https://squidfunk.github.io/mkdocs-material/) site, structured by
a COBESY adoption flow. It works on arbitrary projects; the site identity and GitHub
Pages base path are derived from the *target* repo, never hardcoded.

---

## 1. Prerequisites

- Python 3.12
- [`uv`](https://docs.astral.sh/uv/)
- `git`
- Network access on first install (the HarnessX dependency is pulled from GitHub, plus
  packages from PyPI).

## 2. Install

```bash
git clone https://github.com/norandom/DocuHarnessX.git
cd DocuHarnessX
uv venv --python 3.12 .venv
source .venv/bin/activate
uv pip install -e .
```

This installs the `docuharnessx` package, registers the `dhx` console script, and
brings in HarnessX, `pyyaml`, `mkdocs`, and `mkdocs-material`. The HarnessX dependency
has a large tree (LLM providers, etc.), so the first install takes a few minutes.

Verify:

```bash
dhx --help
```

## 3. Point it at a model

`dhx` needs a model for the writer (generates the docs) and the review gate (judges
them). The resolver checks a configured model id first, then provider environment
variables in this order: **Anthropic → OpenAI → LiteLLM**.

### OpenAI

```bash
export OPENAI_API_KEY=sk-...
export OPENAI_DEFAULT_MAIN_MODEL=gpt-4o-mini   # optional; default is gpt-4o
```

Two things to know:

- If `ANTHROPIC_API_KEY` is also set, Anthropic is chosen first. Unset it to force OpenAI.
- Each planned segment costs roughly two model calls (one to write, one to judge), so a
  small repo is a handful of cents on `gpt-4o-mini`.

### Other providers

| Provider | API key | Optional model override | Routed through |
|---|---|---|---|
| Anthropic | `ANTHROPIC_API_KEY` | `ANTHROPIC_DEFAULT_MAIN_MODEL` | Anthropic SDK |
| OpenAI | `OPENAI_API_KEY` | `OPENAI_DEFAULT_MAIN_MODEL` | LiteLLM |
| LiteLLM | `LITELLM_API_KEY` | `LITELLM_DEFAULT_MAIN_MODEL` | LiteLLM |

Anthropic model ids (`claude-*`, `anthropic/*`) use the Anthropic provider; everything
else goes through LiteLLM. You can also set the model in a `--config` YAML instead of
the environment.

## 4. (Optional) Configure the ontology

The roles, intents, and tags are per-project configuration. You can keep the shipped
default profile or customize it:

```bash
dhx init --default     # seed .docuharnessx/ontology.yaml with the 10 default roles / 13 intents
dhx init               # interactive: choose which roles, intents, and subjects apply
```

If you skip this, `dhx` uses the default profile and prints a hint.

## 5. Generate docs for a project

The general form (a bare path defaults to the `run` pipeline):

```bash
dhx <path-to-repo> --out <output-dir> [--config config.yaml] [--roles developer,manager] [--deploy-mode MODE]
```

The pipeline runs eight stages: `ingest → analyze → classify → plan → write → review →
assemble → deploy`. Output under `<output-dir>`:

- `site/mkdocs.yml` + `site/docs/` — the Material for MkDocs source tree
- `site/site/` — the built HTML (when a build runs)
- `segments/<id>.md` — the individual content segments
- a HarnessJournal `.jsonl` trace of the run

### Deploy modes (`--deploy-mode`)

- `emit-ci-workflow` (default) — writes `mkdocs.yml` + `docs/` + `.github/workflows/docs.yml`
  **into the target repo** so its own GitHub Actions publishes Pages on push. No auto-push.
- `gh-deploy` — pushes the built site to the target repo's `gh-pages` branch.
- `build-only` — builds the static site into `<output-dir>` and publishes nothing.

## 6. Run it on itself (dogfood)

Start with `build-only` so nothing is written into the repo, and send output **outside**
the repo (or to the gitignored `_docs_out/`) so generated files aren't rescanned or
committed:

```bash
dhx /home/mc/Source/DocuHarnessX --out /tmp/dhx-self --deploy-mode build-only
```

Preview the result:

```bash
cd /tmp/dhx-self/site && python -m mkdocs serve
# open http://127.0.0.1:8000/DocuHarnessX/
```

The site identity is derived from this repo's remote: `site_url
https://norandom.github.io/DocuHarnessX/`, base path `/DocuHarnessX/`.

### Publish DocuHarnessX's own docs

Use the default mode to set up GitHub Pages for the repo:

```bash
dhx /home/mc/Source/DocuHarnessX --out /tmp/dhx-self   # default: emit-ci-workflow
```

This writes `mkdocs.yml`, `docs/`, and `.github/workflows/docs.yml` into the working
tree (no push). Review the changes, commit and push them, then set **Settings → Pages →
Source: GitHub Actions**. The workflow builds and publishes on the next push.

## 7. Notes and troubleshooting

- **No model configured / `ModelResolutionError`** — set one of the provider API keys in
  step 3 (or a model in `--config`).
- **`mkdocs` not found** — make sure the venv is activated (`source .venv/bin/activate`)
  so `mkdocs` is on `PATH`; or invoke `dhx` as `.venv/bin/dhx`.
- **Vendor/build directories** — the scanner ignores `.git`, `.venv`, `node_modules`,
  `target`, `build`, `dist`, `__pycache__`, `site`, and similar, so dependency files do
  not pollute the analysis.
- **Primary language on doc-heavy repos** — primary-language detection currently uses
  raw lines-of-code across all file types, so a documentation-heavy repo can report a
  markup language (e.g. Markdown) as primary even though the implementation language is
  detected. The generated site is still correct; this is a known refinement.
- **Credential-free** — the test suite exercises the full pipeline without any API key
  using a fake provider; a real `dhx` run, however, needs a model configured.

## 8. Validated targets

DocuHarnessX 1.0 was validated end to end across Go, Python, JavaScript, and Rust
projects (`malware_hashes`, `pallets/click`, `expressjs/express`, `BurntSushi/ripgrep`)
plus a self-documentation run — each producing a correct per-project site. `malware_hashes`
is just one example; the tool is built to work on any project.
