---
id: component:assembler
title: What does assembler do?
subjects:
- assembler
summary: '`docuharnessx.assembler` is the **pure, model-free MkDocs site-assembly
  core** of DocuHarnessX — the deterministic transform that turns quality-gated documentation
  content into a publishable **Material for MkDocs** source tree, with no model call
  and no network access (`docuharnessx/assembler/__init__.py:1-13`). It sits behind
  the thin `AssembleStage` adapter, and its docstring pins the contract precisely:
  it consumes the accepted `Segment` set from the frozen `ReviewReport` (verbatim,
  read-only), the loaded project `Vocabulary`, and the optional `RepoAnalysis`, and
  emits "one `docs/*.md` page per accepted segment, per-role landing pages with COBESY-structured
  intent-ordered agendas, a tags index, and a `mkdocs.yml` configuring the Material
  theme and the tags plugin" (`docuharnessx/assembler/__init__.py:5-13`).'
related: []
---
# What does assembler do?

# What `assembler` does

`docuharnessx.assembler` is the **pure, model-free MkDocs site-assembly core** of DocuHarnessX — the deterministic transform that turns quality-gated documentation content into a publishable **Material for MkDocs** source tree, with no model call and no network access (`docuharnessx/assembler/__init__.py:1-13`). It sits behind the thin `AssembleStage` adapter, and its docstring pins the contract precisely: it consumes the accepted `Segment` set from the frozen `ReviewReport` (verbatim, read-only), the loaded project `Vocabulary`, and the optional `RepoAnalysis`, and emits "one `docs/*.md` page per accepted segment, per-role landing pages with COBESY-structured intent-ordered agendas, a tags index, and a `mkdocs.yml` configuring the Material theme and the tags plugin" (`docuharnessx/assembler/__init__.py:5-13`).

## The per-target identity resolver

Before any rendering, the site's identity is computed **per-target** — never DocuHarnessX's own. `resolve_site_identity(target_repo, remote_url, overrides)` (`docuharnessx/assembler/identity.py:237-284`) is a pure, total function: it parses GitHub HTTPS/SSH/`ssh://` remotes into `owner/repo` via the `_GITHUB_HTTPS`, `_GITHUB_SSH`, and `_GITHUB_SSH_URL` patterns (`docuharnessx/assembler/identity.py:108-124`), derives the project-Pages `site_url` `https://<owner>.github.io/<repo>/` and `/<repo>/` `base_path` (`_github_identity`, `docuharnessx/assembler/identity.py:154-172`), falls back to a non-GitHub or no-remote identity (`_non_github_identity`, `docuharnessx/assembler/identity.py:175-208`), and then applies only the whitelisted override keys `site_name`/`site_url`/`repo_url`/`edit_uri` (`_OVERRIDABLE`, `docuharnessx/assembler/identity.py:103`). The single process-touching surface — the read-only, mockable `read_origin_remote` — runs `git -C <target_repo> remote get-url origin` as a time-bounded subprocess and degrades every failure mode to `None` (`docuharnessx/assembler/identity.py:49-91`).

## The renderers

The package is split into deterministic, byte-stable renderers, all imported through the single public namespace in `__init__.py:40-54`:

- **Per-segment pages** — `render_segment_page(segment, vocab, accepted_ids)` returns `(relative_docs_path, page_markdown)`: a YAML frontmatter block whose `tags:` equals `emit_tags(segment, vocab)` exactly, the title as an H1, the body verbatim, and a "Related" section filtered to accepted ids (`docuharnessx/assembler/pages.py:126-160`). `page_filename` slugs the segment id and appends an 8-hex SHA-256 digest so distinct ids never collide (`docuharnessx/assembler/pages.py:70-83`).
- **Role landing pages** — `render_role_landing_page(role, accepted_store, vocab, all_role_pages)` builds each `docs/<role>/index.md` from three parts: a COBESY **SCQA opener** framed only from the role's vocabulary `label`/`description` (`_render_opener`, `docuharnessx/assembler/roles.py:142-178`), an **intent-ordered guided agenda** rendered from `build_role_view` as numbered links (no body duplication — `_render_agenda`, `docuharnessx/assembler/roles.py:186-210`), and a **role-switch affordance** as a Material `!!! info` admonition listing the other roles (`_render_role_switch`, `docuharnessx/assembler/roles.py:218-243`).
- **Home page** — `render_home_page(identity, role_pages)` renders `docs/index.md` naming the *target* project (never DocuHarnessX), a "choose your path" index over the role pages, and a pointer to the tags index (`docuharnessx/assembler/home.py:32-73`).
- **`mkdocs.yml` builder** — `build_mkdocs_yaml(identity, role_pages, vocab, segments_by_role)` emits `site_name`, the per-target `site_url` and `use_directory_urls: true`, `repo_url`/`edit_uri` only when non-empty, the Material theme with the feature list in `_THEME_FEATURES`, plugins `["search", {"tags": {}}]`, a deterministic nav, and a `pymdownx.superfences` custom fence for `mermaid` (`docuharnessx/assembler/mkdocs_config.py:231-305`). Because the fence `format` is a Python function, it serializes via `_MkDocsYamlDumper`, a `SafeDumper` subclass emitting the `!!python/name:` tag MkDocs' full loader recognizes (`docuharnessx/assembler/mkdocs_config.py:120-144`).
- **Theme skin** — `render_extra_css()` returns a deepwiki-open-inspired stylesheet at `stylesheets/extra.css` that overrides Material's CSS custom properties for the light (`default`) and dark (`slate`) schemes plus a washi-paper texture (`docuharnessx/assembler/theme.py:37-45`, `docuharnessx/assembler/theme.py:48-120`).

## The writer that orchestrates it all

`assemble_site(report, vocab, analysis, out_dir, identity)` is the orchestration boundary (`docuharnessx/assembler/writer.py:143-250`). It builds a fresh accepted-only `InMemorySegmentStore` (`_build_accepted_store`, `docuharnessx/assembler/writer.py:96-111`), renders and writes one page per accepted segment, one landing page per non-empty vocabulary role in vocabulary order, the `docs/tags.md` index carrying the `<!-- material/tags -->` directive the `tags` plugin discovers (`_TAGS_INDEX_CONTENT`, `docuharnessx/assembler/writer.py:93`), the home page, the extra CSS, and `mkdocs.yml` — all under the single write target `<out_dir>/site` — then returns the frozen `AssembledSite` seam with absolute paths and page counts (`docuharnessx/assembler/writer.py:242-250`). `_write_text` writes UTF-8 with `newline=""` so on-disk bytes match the renderers' byte-stable output (`docuharnessx/assembler/writer.py:130-140`).

## The frozen output seam

The package's data boundary is `model.py`: the `@dataclass(frozen=True)` `SiteIdentity` (six immutable `str` fields; `docuharnessx/assembler/model.py:67-91`) and `AssembledSite` (schema version, `site_dir`, `docs_dir`, `mkdocs_yml_path`, identity, page counts; `docuharnessx/assembler/model.py:99-127`), the single `ASSEMBLED_SITE_SCHEMA_VERSION: int = 1` authority (`docuharnessx/assembler/model.py:59`), and the self-contained `AssemblerError` / `AssemblerInputError` hierarchy (`docuharnessx/assembler/model.py:135-156`).

## A second, explore-first path

`assemble_question_site(pages, identity, out_dir)` is a separate entry point that assembles a question-organised site from accepted `Page` values only — no role landings, no tags index — and returns `None` (writing nothing under `site/`) when zero pages are accepted so callers skip deploy (`docuharnessx/assembler/question_site.py:44-89`).

In short: the assembler resolves who the site is about, renders every accepted segment into a tagged page, groups those pages into role-oriented agendas and a role-based home, configures Material/MkDocs to serve and tag them, writes the whole tree deterministically to `<out_dir>/site`, and returns a frozen `AssembledSite` for the deploy stage — all without invoking a model.
