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
