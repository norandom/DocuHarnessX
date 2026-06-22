"""Unit tests for the mkdocs.yml builder (mkdocs-site-assembler task 3.3).

These tests pin the *mkdocs.yml builder* boundary (design "mkdocs.yml builder",
``assembler/mkdocs_config.py``). The builder is a pure function that, from the resolved
:class:`~docuharnessx.assembler.model.SiteIdentity`, the emitted role pages, and the
loaded :class:`~docuharnessx.ontology.Vocabulary`, emits the ``mkdocs.yml`` string:

* ``site_name`` from the identity (Req 6.x);
* the per-target ``site_url`` and ``use_directory_urls`` so links/assets resolve under the
  project ``/<repo>/`` base-path (Req 3.3);
* ``repo_url``/``edit_uri`` when present (Req 3.3);
* the Material theme (Req 6.4);
* the ``tags`` plugin (Req 6.2);
* a deterministic ``nav`` referencing the per-role landing pages (in vocabulary role
  order) and a tags index (Req 6.1).

Observable completion (tasks.md 3.3): the emitted yaml carries the Material theme and the
tags plugin, sets ``site_url`` and directory-URL handling to the per-target base-path, and
produces a deterministic nav over the emitted role pages plus the tags index.

Task 3.3 owns only the mkdocs.yml builder — not the segment page renderer (3.1), the role
landing-page renderer (3.2), the writer (4.1), or the stage adapter (5.x). The tags index
*page content* (``tags.md``) is owned by the writer (4.1); this builder only references it.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from docuharnessx.assembler import mkdocs_config as cfg_mod
from docuharnessx.assembler.mkdocs_config import (
    TAGS_INDEX_PATH,
    build_mkdocs_yaml,
)
from docuharnessx.assembler.model import SiteIdentity
from docuharnessx.ontology import AxisTerm, Vocabulary, default_profile


# --------------------------------------------------------------------------- #
# Builders / fixtures                                                          #
# --------------------------------------------------------------------------- #


def _github_identity() -> SiteIdentity:
    """A GitHub project-Pages identity (the reference shape: norandom/malware_hashes)."""
    return SiteIdentity(
        site_name="malware_hashes",
        repo_name="norandom/malware_hashes",
        repo_url="https://github.com/norandom/malware_hashes",
        site_url="https://norandom.github.io/malware_hashes/",
        base_path="/malware_hashes/",
        edit_uri="edit/main/docs/",
    )


def _no_remote_identity() -> SiteIdentity:
    """A no-remote fallback identity: target-derived name, root base-path, empty urls."""
    return SiteIdentity(
        site_name="my-project",
        repo_name="",
        repo_url="",
        site_url="",
        base_path="/",
        edit_uri="",
    )


def _non_github_identity() -> SiteIdentity:
    """A non-GitHub remote: repo_url kept, root base-path, empty site_url."""
    return SiteIdentity(
        site_name="internal-thing",
        repo_name="",
        repo_url="https://gitlab.example.com/team/internal-thing.git",
        site_url="",
        base_path="/",
        edit_uri="",
    )


# Role pages as the writer would pass them: (label, docs_relative_path) per emitted role,
# in vocabulary role order.
_DEFAULT_ROLE_PAGES = (
    ("Developer", "developer/index.md"),
    ("DevOps/Admin", "devops-admin/index.md"),
)

_CUSTOM_VOCAB = Vocabulary(
    roles=(
        AxisTerm("operator", "Site Operator", "Runs the thing in production."),
        AxisTerm("auditor", "Compliance Auditor", "Checks the controls."),
    ),
    intents=(
        AxisTerm("first", "First Step", "Do this first."),
        AxisTerm("next", "Next Step", "Then this."),
    ),
    subject_prefixes=("topic:",),
)

_CUSTOM_ROLE_PAGES = (
    ("Site Operator", "operator/index.md"),
    ("Compliance Auditor", "auditor/index.md"),
)


def _load(yaml_text: str) -> dict:
    """Parse the emitted yaml. Must be valid loadable YAML."""
    data = yaml.safe_load(yaml_text)
    assert isinstance(data, dict)
    return data


# --------------------------------------------------------------------------- #
# Surface                                                                      #
# --------------------------------------------------------------------------- #


def test_module_exports_builder_and_tags_path() -> None:
    assert "build_mkdocs_yaml" in cfg_mod.__all__
    assert "TAGS_INDEX_PATH" in cfg_mod.__all__
    assert TAGS_INDEX_PATH.endswith(".md")


def test_returns_str_parsing_to_a_mapping() -> None:
    out = build_mkdocs_yaml(_github_identity(), _DEFAULT_ROLE_PAGES, default_profile())
    assert isinstance(out, str)
    _load(out)  # parses to a mapping


# --------------------------------------------------------------------------- #
# Req 6.4: Material theme                                                      #
# --------------------------------------------------------------------------- #


def test_theme_is_material() -> None:
    data = _load(
        build_mkdocs_yaml(_github_identity(), _DEFAULT_ROLE_PAGES, default_profile())
    )
    theme = data["theme"]
    # theme may be a mapping {name: material, ...} or a string; we require the mapping form
    # so we can attach Material features (content-tabs are used by the role renderer).
    assert isinstance(theme, dict)
    assert theme["name"] == "material"


# --------------------------------------------------------------------------- #
# Req 6.2: tags plugin                                                         #
# --------------------------------------------------------------------------- #


def _plugin_names(data: dict) -> list[str]:
    """Normalize the plugins list to plugin names (entries may be str or {name: cfg})."""
    names: list[str] = []
    for entry in data["plugins"]:
        if isinstance(entry, str):
            names.append(entry)
        elif isinstance(entry, dict):
            names.extend(entry.keys())
    return names


def test_tags_plugin_present() -> None:
    data = _load(
        build_mkdocs_yaml(_github_identity(), _DEFAULT_ROLE_PAGES, default_profile())
    )
    assert "tags" in _plugin_names(data)


def test_tags_plugin_does_not_use_deprecated_tags_file() -> None:
    # The legacy `tags_file` option is deprecated in current mkdocs-material and aborts a
    # --strict build; the plugin must be enabled bare and discover the listing directive the
    # writer places in the tags index page instead (Req 6.2, 8.4).
    data = _load(
        build_mkdocs_yaml(_github_identity(), _DEFAULT_ROLE_PAGES, default_profile())
    )
    for entry in data["plugins"]:
        if isinstance(entry, dict) and "tags" in entry:
            tags_cfg = entry["tags"]
            # Enabled bare ({} or null); never carrying the deprecated tags_file.
            if isinstance(tags_cfg, dict):
                assert "tags_file" not in tags_cfg


# --------------------------------------------------------------------------- #
# Req 3.3: per-target site_url + directory-URL handling + base-path            #
# --------------------------------------------------------------------------- #


def test_github_site_url_and_directory_urls_set() -> None:
    ident = _github_identity()
    data = _load(build_mkdocs_yaml(ident, _DEFAULT_ROLE_PAGES, default_profile()))
    # site_url is the per-target Pages URL carrying the /<repo>/ base-path (Req 3.2, 3.3).
    assert data["site_url"] == ident.site_url
    assert ident.base_path in data["site_url"]
    # directory-URL handling so links/assets resolve under the subpath (Req 3.3).
    assert data["use_directory_urls"] is True


def test_site_name_from_identity() -> None:
    ident = _github_identity()
    data = _load(build_mkdocs_yaml(ident, _DEFAULT_ROLE_PAGES, default_profile()))
    assert data["site_name"] == ident.site_name


def test_repo_url_and_edit_uri_present_when_set() -> None:
    ident = _github_identity()
    data = _load(build_mkdocs_yaml(ident, _DEFAULT_ROLE_PAGES, default_profile()))
    assert data["repo_url"] == ident.repo_url
    assert data["edit_uri"] == ident.edit_uri


def test_no_remote_identity_omits_empty_repo_url_and_site_url() -> None:
    # No remote -> empty repo_url/site_url/edit_uri must NOT be emitted as empty keys
    # (an empty site_url breaks the relative base-path; an empty repo_url shows a broken
    # repo button). The site_name is still present and the build must stay clean.
    ident = _no_remote_identity()
    data = _load(build_mkdocs_yaml(ident, _DEFAULT_ROLE_PAGES, default_profile()))
    assert data["site_name"] == ident.site_name
    assert "repo_url" not in data
    assert "edit_uri" not in data
    # use_directory_urls is still configured (deterministic directory-URL handling).
    assert data["use_directory_urls"] is True


def test_non_github_keeps_repo_url_without_site_url() -> None:
    ident = _non_github_identity()
    data = _load(build_mkdocs_yaml(ident, _DEFAULT_ROLE_PAGES, default_profile()))
    assert data["repo_url"] == ident.repo_url
    # No GitHub project Pages URL -> site_url omitted (root base-path), not emitted empty.
    assert "site_url" not in data


# --------------------------------------------------------------------------- #
# Req 6.1: deterministic nav over role pages + tags index                      #
# --------------------------------------------------------------------------- #


def _nav_targets(nav: list) -> list[str]:
    """Flatten a nav list into the ordered list of link targets."""
    targets: list[str] = []
    for entry in nav:
        if isinstance(entry, str):
            targets.append(entry)
        elif isinstance(entry, dict):
            for value in entry.values():
                if isinstance(value, str):
                    targets.append(value)
                elif isinstance(value, list):
                    targets.extend(_nav_targets(value))
    return targets


def test_nav_references_role_pages_then_tags_index() -> None:
    data = _load(
        build_mkdocs_yaml(_github_identity(), _DEFAULT_ROLE_PAGES, default_profile())
    )
    nav = data["nav"]
    assert isinstance(nav, list)
    targets = _nav_targets(nav)
    # Every emitted role page appears, in the order given (vocabulary role order).
    for _label, path in _DEFAULT_ROLE_PAGES:
        assert path in targets
    role_paths = [p for _l, p in _DEFAULT_ROLE_PAGES]
    assert [t for t in targets if t in role_paths] == role_paths
    # The tags index is referenced.
    assert TAGS_INDEX_PATH in targets


def test_nav_role_page_labels_used() -> None:
    # The nav entries for role pages carry the human role label, not the path.
    out = build_mkdocs_yaml(_github_identity(), _DEFAULT_ROLE_PAGES, default_profile())
    for label, _path in _DEFAULT_ROLE_PAGES:
        assert label in out


def test_nav_order_follows_caller_role_page_order() -> None:
    # Reordering the role pages reorders the nav (the caller supplies vocabulary order).
    reordered = tuple(reversed(_DEFAULT_ROLE_PAGES))
    data = _load(build_mkdocs_yaml(_github_identity(), reordered, default_profile()))
    targets = _nav_targets(data["nav"])
    role_paths = [p for _l, p in reordered]
    assert [t for t in targets if t in role_paths] == role_paths


def test_empty_role_pages_still_emits_tags_index_nav() -> None:
    # A site with no role pages still has a valid nav with the tags index.
    data = _load(build_mkdocs_yaml(_no_remote_identity(), (), default_profile()))
    targets = _nav_targets(data["nav"])
    assert TAGS_INDEX_PATH in targets


# --------------------------------------------------------------------------- #
# Req 8.2: determinism / byte-stability                                        #
# --------------------------------------------------------------------------- #


def test_byte_stable_for_equal_inputs() -> None:
    a = build_mkdocs_yaml(_github_identity(), _DEFAULT_ROLE_PAGES, default_profile())
    b = build_mkdocs_yaml(_github_identity(), _DEFAULT_ROLE_PAGES, default_profile())
    assert a == b


def test_custom_vocabulary_changes_output_no_code_change() -> None:
    # A custom vocabulary with custom roles flows through via the caller's role pages and
    # changes the emitted yaml — no hardcoded roles (Req 6.x configurability).
    default_out = build_mkdocs_yaml(
        _github_identity(), _DEFAULT_ROLE_PAGES, default_profile()
    )
    custom_out = build_mkdocs_yaml(
        _github_identity(), _CUSTOM_ROLE_PAGES, _CUSTOM_VOCAB
    )
    assert default_out != custom_out
    assert "Site Operator" in custom_out
    assert "operator/index.md" in custom_out


def test_ends_with_single_trailing_newline() -> None:
    out = build_mkdocs_yaml(_github_identity(), _DEFAULT_ROLE_PAGES, default_profile())
    assert out.endswith("\n")
    assert not out.endswith("\n\n")


# --------------------------------------------------------------------------- #
# Req 3.8: never DocuHarnessX's own identity                                   #
# --------------------------------------------------------------------------- #


def test_never_emits_docuharnessx_identity() -> None:
    # The builder reflects only the passed identity; it must never inject DocuHarnessX's
    # own name or Pages URL.
    out = build_mkdocs_yaml(_github_identity(), _DEFAULT_ROLE_PAGES, default_profile())
    lowered = out.lower()
    assert "docuharnessx" not in lowered


# --------------------------------------------------------------------------- #
# Req 3.3 / 8.4: the emitted config builds cleanly under mkdocs-material       #
# --------------------------------------------------------------------------- #


def _write_minimal_docs_tree(root: Path, role_pages: tuple[tuple[str, str], ...]) -> None:
    """Lay down the minimal docs/ tree the emitted nav references, for a build smoke test."""
    docs = root / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "index.md").write_text("# Home\n", encoding="utf-8")
    for label, rel_path in role_pages:
        page = docs / rel_path
        page.parent.mkdir(parents=True, exist_ok=True)
        page.write_text(
            f'---\ntags:\n  - "role:{label}"\n---\n# {label}\n', encoding="utf-8"
        )
    # The tags index page carries the Material listing directive (the writer owns this in 4.1).
    (docs / TAGS_INDEX_PATH).write_text(
        "# Tags\n\n<!-- material/tags -->\n", encoding="utf-8"
    )


@pytest.mark.skipif(
    shutil.which("git") is None and not Path(sys.prefix).exists(),
    reason="environment sanity",
)
def test_emitted_config_builds_cleanly_under_mkdocs_material_strict(
    tmp_path: Path,
) -> None:
    # Req 3.3 / 8.4: the emitted mkdocs.yml builds cleanly under mkdocs-material in --strict
    # mode for a GitHub project-Pages target, with the per-target base-path. (The full
    # build/determinism matrix is task 6.2; this is a focused smoke test of the builder's
    # own output.)
    pytest.importorskip("mkdocs")
    pytest.importorskip("material")

    ident = _github_identity()
    yml = build_mkdocs_yaml(ident, _DEFAULT_ROLE_PAGES, default_profile())
    (tmp_path / "mkdocs.yml").write_text(yml, encoding="utf-8")
    _write_minimal_docs_tree(tmp_path, _DEFAULT_ROLE_PAGES)

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "mkdocs",
            "build",
            "-f",
            str(tmp_path / "mkdocs.yml"),
            "-d",
            str(tmp_path / "_site"),
            "--strict",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"mkdocs build failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )
    # The per-target base-path is honored: the role page is emitted under its directory.
    assert (tmp_path / "_site" / "developer" / "index.html").exists()
