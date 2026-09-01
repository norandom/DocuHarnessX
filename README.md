# DocuHarnessX

Generate grounded MkDocs documentation from a software repository.

Docs: https://norandom.github.io/DocuHarnessX/

Requires [uv](https://docs.astral.sh/uv/) and Python 3.12+.

## Release (`uvx`)

```bash
uvx --python 3.12 --from git+https://github.com/norandom/DocuHarnessX.git@v2.0.0 dhx --help
```

Install onto `PATH`:

```bash
uv tool install --python 3.12 git+https://github.com/norandom/DocuHarnessX.git@v2.0.0
dhx --help
```

## Dev from `HEAD`

Run current `main` without cloning:

```bash
uvx --python 3.12 --from git+https://github.com/norandom/DocuHarnessX.git dhx --help
```

Editable checkout:

```bash
git clone https://github.com/norandom/DocuHarnessX.git
cd DocuHarnessX
uv venv --python 3.12
source .venv/bin/activate
uv pip install -e .
dhx --help
```

## Adopt on a project

Interactive setup asks for an API key, base URL, and model. Press Enter to accept DeepSeek (`https://api.deepseek.com`, `deepseek-v4-flash`). If a key is already set, the prompt shows `***`; Enter or `***` keeps it.

```bash
dhx init                  # interview: credentials, then ontology proposals
dhx run .                 # add missing living pages
dhx mcp .                 # multi-step refine on living pages
dhx evolve                # adapt the harness from journals
dhx status                # coverage + sufficiency
dhx sufficient            # declare the document sufficient
```

Journals, living pages, ontology, and the adoption record live under `.docuharnessx/` and are meant to be committed. `.env` stays gitignored.

Site: https://norandom.github.io/DocuHarnessX/
