"""Assembled sites ship local JavaScript copies; extra_javascript never points at a CDN."""

from __future__ import annotations

import hashlib
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from docuharnessx.assembler.mermaid import (
    MERMAID_BOOT_PATH,
    MERMAID_JS_PATH,
    load_mermaid_javascript,
    render_mermaid_boot_js,
    write_mermaid_javascript,
)
from docuharnessx.assembler.mkdocs_config import (
    build_mkdocs_yaml,
    build_question_mkdocs_yaml,
)
from docuharnessx.assembler.model import SiteIdentity
from docuharnessx.assembler.question_site import assemble_question_site
from docuharnessx.assembler.writer import assemble_site
from docuharnessx.ontology import default_profile
from docuharnessx.pages.model import Page
from docuharnessx.planning.question_model import QuestionKind, make_question_id
from docuharnessx.review.model import ReviewAggregate, ReviewReport

pytest.importorskip("mkdocs")


def _identity() -> SiteIdentity:
    return SiteIdentity(
        site_name="malware_hashes",
        repo_name="acme/malware_hashes",
        repo_url="https://github.com/acme/malware_hashes",
        site_url="https://acme.github.io/malware_hashes/",
        base_path="/malware_hashes/",
        edit_uri="edit/main/docs/",
    )


def _load(yaml_text: str) -> dict:
    from mkdocs.utils.yaml import get_yaml_loader

    data = yaml.load(yaml_text, Loader=get_yaml_loader())
    assert isinstance(data, dict)
    return data


def _scripts(yaml_text: str) -> list[str]:
    return [str(item) for item in _load(yaml_text)["extra_javascript"]]


def test_extra_javascript_is_local_only() -> None:
    role = _scripts(
        build_mkdocs_yaml(
            _identity(), (("Developer", "developer/index.md"),), default_profile()
        )
    )
    question = _scripts(
        build_question_mkdocs_yaml(_identity(), (("How?", "how.md"),))
    )
    for scripts in (role, question):
        assert scripts[0] == MERMAID_JS_PATH
        assert scripts[1] == MERMAID_BOOT_PATH
        assert all("://" not in path for path in scripts)
        assert all(not path.startswith("/") for path in scripts)
        assert all(path.startswith("javascripts/") for path in scripts)
    assert "javascripts/jit.js" in question
    assert "javascripts/conceptual.js" in question
    assert "javascripts/jit.js" not in role


def test_vendored_mermaid_is_the_umd_build() -> None:
    blob = load_mermaid_javascript()
    assert hashlib.sha256(blob).hexdigest() == (
        "581ed7d74bd9048d0e3a91363927d72ef22942d7722546b27f7cc29e35390eb8"
    )
    text = blob.decode("utf-8")
    assert "11.17.2" in text
    assert 'globalThis["mermaid"]' in text
    assert "unpkg.com" not in text
    assert "jsdelivr" not in text
    assert "startOnLoad: false" in render_mermaid_boot_js()


def test_question_assemble_copies_local_mermaid(tmp_path: Path) -> None:
    pages = (
        Page(
            id=make_question_id(QuestionKind.STARTUP, "cli.py"),
            title="How does this program start?",
            summary="s",
            body="b",
            subjects=("cli.py",),
            related=(),
            cited_files=("app.py",),
        ),
    )
    site = assemble_question_site(pages, _identity(), str(tmp_path))
    assert site is not None
    docs = Path(site.docs_dir)
    mermaid = docs / MERMAID_JS_PATH
    assert mermaid.is_file()
    assert mermaid.read_bytes() == load_mermaid_javascript()
    boot = (docs / MERMAID_BOOT_PATH).read_text(encoding="utf-8")
    assert "startOnLoad: false" in boot
    yml = Path(site.mkdocs_yml_path).read_text(encoding="utf-8")
    assert MERMAID_JS_PATH in yml
    assert MERMAID_BOOT_PATH in yml
    assert "unpkg" not in yml
    assert "jsdelivr" not in yml


def test_role_assemble_copies_local_mermaid(tmp_path: Path) -> None:
    report = ReviewReport(
        schema_version=1,
        entries=(),
        accepted=(),
        aggregate=ReviewAggregate(
            judged=0, accepted=0, rejected=0, unavailable=0, criterion_tally=()
        ),
    )
    site = assemble_site(report, default_profile(), None, str(tmp_path), _identity())
    docs = Path(site.docs_dir)
    assert (docs / MERMAID_JS_PATH).is_file()
    assert (docs / MERMAID_BOOT_PATH).is_file()
    yml = Path(site.mkdocs_yml_path).read_text(encoding="utf-8")
    assert MERMAID_JS_PATH in yml
    assert "javascripts/jit.js" not in yml


def test_write_mermaid_javascript_is_byte_stable(tmp_path: Path) -> None:
    write_mermaid_javascript(tmp_path)
    first = (tmp_path / MERMAID_JS_PATH).read_bytes()
    write_mermaid_javascript(tmp_path)
    assert (tmp_path / MERMAID_JS_PATH).read_bytes() == first


def test_strict_build_html_does_not_src_cdn_scripts(tmp_path: Path) -> None:
    pytest.importorskip("material")
    pages = (
        Page(
            id=make_question_id(QuestionKind.STARTUP, "cli.py"),
            title="How does this program start?",
            summary="s",
            body=(
                "The program starts in `cli.py:1`.\n\n"
                "```mermaid\ngraph TD\n  A[Plan] --> B[Write]\n```\n"
            ),
            subjects=("cli.py",),
            related=(),
            cited_files=("cli.py",),
        ),
    )
    site = assemble_question_site(pages, _identity(), str(tmp_path / "run"))
    assert site is not None
    built = tmp_path / "built"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "mkdocs",
            "build",
            "--strict",
            "-f",
            site.mkdocs_yml_path,
            "-d",
            str(built),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    html_files = list(built.rglob("*.html"))
    assert html_files
    src_cdn = re.compile(r"""<script[^>]+src=["']https?://""", re.IGNORECASE)
    for html_path in html_files:
        html = html_path.read_text(encoding="utf-8")
        assert not src_cdn.search(html), html_path
        assert "javascripts/mermaid.min.js" in html
        assert "javascripts/mermaid-boot.js" in html
    assert (built / MERMAID_JS_PATH).is_file()
    assert (built / MERMAID_BOOT_PATH).is_file()
