# Project Brief — DocuHarnessX

## Idea

A human-centric, **role-based** documentation generator that turns a software
project (target 25–40k LOC) into an aesthetic, published **GitHub Pages** site,
with a **COBESY** adoption flow so time-poor readers reach first success fast.
Built as a real **HarnessX bundle** (`make_docgen`) + a `dhx` CLI.

## Action Path

Greenfield project. Multi-spec build, spec-driven (Kiro). Discovery → this brief +
roadmap → `/kiro-spec-batch` by dependency wave → implement.

## What's Being Built (one line)

`dhx <repo>` reads a codebase, classifies content on a tri-modal ontology
(Role × Subject × Intent), plans coverage with decision intelligence, writes
COBESY-structured segments, quality-gates them with an LLM-judge, and assembles +
deploys a Material for MkDocs site with per-role guided agendas.

## Founding Decisions (locked with user 2026-06-21)

1. **Real HarnessX bundle** (Python 3.12, depends on github.com/Darwin-Agent/HarnessX).
2. **Material for MkDocs** as the output framework.
3. **Multi-spec roadmap** decomposition.
4. **10 roles**: Possible Adopter, Developer, Tech-savvy User, Manager, DevOps/Admin,
   Researcher (core 6) + Security/Compliance Officer, Contributor, Integrator/API
   consumer, Support/On-call (core+4).

## Tri-Modal Ontology

- **Subject** (what/how): `subject:<component|tech|artifact|topic>`
- **Intent** (why-reading): install · configure · use · troubleshoot · monitor ·
  operate · integrate · extend · evaluate · assess-quality · understand · contribute · deliver
- **Role** (who): the 10 roles above.

Atomic unit = a Markdown **segment** with frontmatter `{roles[], subjects[], intent}`.
Role views are assembled by filtering → reuse + interconnection.

## Reference Target

`/home/mc/Source/malware_hashes` — ~6.8k LOC Go forensic-hashing CLI — used as the
end-to-end auto-documentation validation case.

## Out of Scope (for now)

Non-MkDocs output backends; multi-repo aggregation; live/hosted SaaS; model-evolution
(Train dimension) loop; translation/i18n of generated docs.
