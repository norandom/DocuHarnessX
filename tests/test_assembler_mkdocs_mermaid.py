"""Unit tests for the Mermaid superfence addition to the mkdocs.yml builder.

These tests pin task 4.1 of the ``agentic-codebase-writer`` spec: the assembler's
:func:`docuharnessx.assembler.mkdocs_config.build_mkdocs_yaml` gains a minimal, idempotent
``markdown_extensions`` block enabling the Material ``pymdownx.superfences`` custom fence for
Mermaid, so fenced ``mermaid`` blocks render as diagrams (Req 10.1, 10.2).

Boundary (task 4.1): ``build_mkdocs_yaml`` only. The signature is unchanged
(``build_mkdocs_yaml(identity, role_pages, vocab) -> str``); the emitted YAML gains the
Mermaid custom-fence extension while every previously emitted key
(``site_name``/``site_url``/``repo_url``/``edit_uri``/``use_directory_urls``/``theme``/
``plugins``/``nav``) is unchanged and byte-stable for equal inputs.

The custom-fence ``format`` value is a Python object reference
(``pymdownx.superfences.fence_code_format``), so the emitter must produce the
``!!python/name:`` YAML tag (not a quoted string) — the same form MkDocs' full YAML loader
constructs back into the function object. These tests parse the emitted YAML with the MkDocs
loader to confirm the tag resolves to the real function.

The strict ``mkdocs build`` of a Mermaid-bearing page is covered by task 5.1
(``test_assembler_mkdocs_mermaid``-adjacent build integration); these tests focus on the
builder's own emitted configuration.
"""

from __future__ import annotations

import pytest
import yaml

from docuharnessx.assembler.mkdocs_config import build_mkdocs_yaml
from docuharnessx.assembler.model import SiteIdentity
from docuharnessx.ontology import default_profile


# --------------------------------------------------------------------------- #
# Builders / fixtures                                                          #
# --------------------------------------------------------------------------- #


def _github_identity() -> SiteIdentity:
    """A GitHub project-Pages identity (the reference shape)."""
    return SiteIdentity(
        site_name="malware_hashes",
        repo_name="norandom/malware_hashes",
        repo_url="https://github.com/norandom/malware_hashes",
        site_url="https://norandom.github.io/malware_hashes/",
        base_path="/malware_hashes/",
        edit_uri="edit/main/docs/",
    )


_DEFAULT_ROLE_PAGES = (
    ("Developer", "developer/index.md"),
    ("DevOps/Admin", "devops-admin/index.md"),
)


def _build() -> str:
    return build_mkdocs_yaml(_github_identity(), _DEFAULT_ROLE_PAGES, default_profile())


def _load_with_mkdocs_loader(yaml_text: str) -> dict:
    """Parse with the same full loader MkDocs uses, so the ``!!python/name:`` tag resolves
    to the real function object rather than failing as the safe loader would."""
    from mkdocs.utils.yaml import get_yaml_loader

    data = yaml.load(yaml_text, Loader=get_yaml_loader())
    assert isinstance(data, dict)
    return data


def _custom_fences(data: dict) -> list:
    """Return the custom_fences list from the emitted markdown_extensions block."""
    exts = data["markdown_extensions"]
    assert isinstance(exts, list)
    for entry in exts:
        if isinstance(entry, dict) and "pymdownx.superfences" in entry:
            cfg = entry["pymdownx.superfences"]
            assert isinstance(cfg, dict)
            fences = cfg["custom_fences"]
            assert isinstance(fences, list)
            return fences
    raise AssertionError("pymdownx.superfences markdown extension not found")


# --------------------------------------------------------------------------- #
# Req 10.1: the Mermaid custom fence is present with the correct format ref     #
# --------------------------------------------------------------------------- #


def test_markdown_extensions_block_emitted() -> None:
    data = _load_with_mkdocs_loader(_build())
    assert "markdown_extensions" in data


def test_superfences_mermaid_fence_present() -> None:
    fences = _custom_fences(_load_with_mkdocs_loader(_build()))
    mermaid = [f for f in fences if isinstance(f, dict) and f.get("name") == "mermaid"]
    assert len(mermaid) == 1, "exactly one mermaid custom fence expected"
    fence = mermaid[0]
    assert fence["name"] == "mermaid"
    assert fence["class"] == "mermaid"


def test_fence_format_is_the_superfences_function() -> None:
    # The format value must round-trip (through the full loader MkDocs uses) to the real
    # pymdownx.superfences.fence_code_format function, i.e. it was emitted as the
    # !!python/name: tag, not a quoted string.
    import pymdownx.superfences as superfences

    fences = _custom_fences(_load_with_mkdocs_loader(_build()))
    fence = next(f for f in fences if f.get("name") == "mermaid")
    assert fence["format"] is superfences.fence_code_format


def test_format_emitted_as_python_name_tag_not_quoted() -> None:
    # The raw emitted text carries the YAML python-name tag for the format reference; it is
    # not a quoted string (a quoted string would not be recognized as the fence formatter).
    out = _build()
    assert "!!python/name:pymdownx.superfences.fence_code_format" in out
    assert "'pymdownx.superfences.fence_code_format'" not in out


# --------------------------------------------------------------------------- #
# Req 10.2: minimal + idempotent — no other key changed, byte-stable           #
# --------------------------------------------------------------------------- #


def _strip_markdown_extensions(yaml_text: str) -> dict:
    """Parse and drop the markdown_extensions block, leaving the rest to compare."""
    data = _load_with_mkdocs_loader(yaml_text)
    data.pop("markdown_extensions", None)
    return data


def test_all_previously_emitted_keys_unchanged() -> None:
    # Every key the builder emitted before (everything except the new markdown_extensions
    # block) must be byte-for-byte unchanged in value.
    data = _strip_markdown_extensions(_build())
    ident = _github_identity()
    assert data["site_name"] == ident.site_name
    assert data["site_url"] == ident.site_url
    assert data["repo_url"] == ident.repo_url
    assert data["edit_uri"] == ident.edit_uri
    assert data["use_directory_urls"] is True
    assert data["theme"]["name"] == "material"
    assert "plugins" in data
    assert "nav" in data
    # No stray keys beyond the known set + markdown_extensions.
    expected_keys = {
        "site_name",
        "site_url",
        "repo_url",
        "edit_uri",
        "use_directory_urls",
        "theme",
        "plugins",
        "nav",
    }
    assert set(data.keys()) == expected_keys


def test_byte_stable_for_equal_inputs() -> None:
    assert _build() == _build()


def test_ends_with_single_trailing_newline() -> None:
    out = _build()
    assert out.endswith("\n")
    assert not out.endswith("\n\n")


def test_emitted_yaml_is_loadable_by_mkdocs_loader() -> None:
    # Sanity: the whole emitted document parses under the MkDocs loader (the safe loader
    # would choke on the python-name tag, which is exactly why the builder must stay
    # mkdocs-loadable, not safe-loadable).
    data = _load_with_mkdocs_loader(_build())
    assert data["site_name"] == "malware_hashes"


def test_safe_loader_rejects_the_python_name_tag() -> None:
    # Confirms the format really is the python-name tag (the safe loader cannot construct it),
    # which is what makes pymdownx recognize the fence formatter.
    with pytest.raises(yaml.YAMLError):
        yaml.safe_load(_build())
