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

`dhx init` is the onboarding path. Interactive setup asks for an API key, base URL, and model. Press Enter to accept DeepSeek (`https://api.deepseek.com`, `deepseek-v4-flash`). If a key is already set, the prompt shows `***`; Enter or `***` keeps it.

Then the harness writes the files CI and the hook need, and installs the hook:

```bash
dhx init                  # credentials, ontology, pre-commit hook, CI workflow
# commit (never .env):
#   .docuharnessx/ontology.yaml
#   .docuharnessx/adoption.yaml
#   .pre-commit-config.yaml
#   .github/workflows/dhx.yml
pre-commit install        # if you use the pre-commit framework
dhx run .                 # add missing living pages
dhx mcp .                 # multi-step refine on living pages
dhx evolve                # adapt the harness from journals
dhx status                # coverage + sufficiency
dhx sufficient            # declare the document sufficient
```

`dhx ci` uses `.docuharnessx/ontology.yaml` only when `.docuharnessx/adoption.yaml` is also present. Commit both. Journals and living pages under `.docuharnessx/` are meant to be committed too. `.env` stays gitignored.

## Pre-commit hook (GitHub package)

The hook is fail-open: no API key, docs-only changes, or `[dhx]` commits skip generation so agent/docs loops do not block you. It never runs `dhx evolve`.

From a release tag:

```yaml
# .pre-commit-config.yaml — or: dhx install-hooks --pre-commit
repos:
  - repo: https://github.com/norandom/DocuHarnessX
    rev: v2.0.0
    hooks:
      - id: dhx
```

```bash
dhx install-hooks --pre-commit   # writes the file above
dhx install-hooks --git          # .git/hooks/pre-commit via local dhx or uvx
pre-commit install
```

## CI from the GitHub repo

```bash
dhx install-ci                   # writes .github/workflows/dhx.yml
```

GitHub Settings → Secrets and variables → Actions:

| Name | Where | Example |
|---|---|---|
| `OPENAI_API_KEY` | **Secret** (not a variable) | DeepSeek key |
| `OPENAI_API_BASE` | Variable | `https://api.deepseek.com` |
| `OPENAI_DEFAULT_MAIN_MODEL` | Variable | `deepseek-v4-flash` |

If the variables are unset, CI defaults to DeepSeek. Do not put the API key in Variables — it is not masked.

The reusable workflow is `norandom/DocuHarnessX/.github/workflows/adopt.yml@v2.0.0`. This repository dogfoods it via `.github/workflows/dhx.yml` (same-commit checkout). On each source push it runs incremental `dhx ci` and commits MkDocs / living pages with a `[dhx]` message. GitHub Pages still builds from `docs.yml`.

### Evolution when agents commit code

Do **not** evolve in the same commit or on the same branch as a coding agent.

| Plane | Who writes | When | Where it lands |
|---|---|---|---|
| App code | human or coding agent | every push | `main` / feature branch |
| Living docs + MkDocs | docs bot | source changed, key present, not a `[dhx]` commit | `[dhx]` commit on the same branch |
| Harness snapshot | evolve job | `.docuharnessx/journals/` changed | PR on `dhx/evolve` |

Rules baked into `dhx` / `adopt.yml`:

1. Journals are the only evolve input. A code-only agent push does not evolve.
2. `[dhx]` commits skip generate and evolve (loop breaker).
3. Evolve opens a PR; it never force-pushes `main`.
4. An open `dhx/evolve` PR blocks another evolve run.
5. The substance gate cannot be dropped; humans merge the snapshot.

Site: https://norandom.github.io/DocuHarnessX/
