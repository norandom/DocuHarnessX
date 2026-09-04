"""Guardrails: no role-intent page ids, no harnessx.rl (task 6.1)."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from docuharnessx.planning.question_model import make_question_id

_README = Path(__file__).resolve().parents[1] / "README.md"


def test_question_ids_reject_role_intent_shape() -> None:
    with pytest.raises(ValueError, match="reader-role"):
        make_question_id("startup", "developer__extend")


def test_docuharnessx_does_not_import_harnessx_rl() -> None:
    root = Path(__file__).resolve().parents[1] / "docuharnessx"
    offenders: list[str] = []
    meta_ok: list[str] = []
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        rel = str(path.relative_to(root.parent))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                names.append(node.module)
            for name in names:
                if name == "harnessx.rl" or name.startswith("harnessx.rl."):
                    offenders.append(rel)
                if name == "harnessx.meta_harness" or name.startswith(
                    "harnessx.meta_harness."
                ):
                    meta_ok.append(rel)
    assert not offenders, f"harnessx.rl imported from {offenders}"
    for rel in meta_ok:
        assert rel.endswith("evolve.py"), f"meta_harness imported outside evolve: {rel}"


def test_readme_documents_adoption_interview() -> None:
    text = _README.read_text(encoding="utf-8")
    for token in (
        "dhx init",
        "dhx run",
        "dhx mcp",
        "dhx evolve",
        "dhx status",
        "***",
        "install-hooks",
        "install-ci",
        "OPENAI_API_KEY",
        "Secret",
        "Variable",
        "pre-commit install",
        "adoption.yaml",
        "ontology.yaml",
    ):
        assert token in text, token
    assert "uvx" in text
    assert "v3.0.0" in text
    assert "not a variable" in text.lower() or "not a variable" in text
