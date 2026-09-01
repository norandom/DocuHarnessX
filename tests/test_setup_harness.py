"""Setup harness ontology proposals (task 2.5, boundary: SetupHarness).

Credential-free: a scripted provider returns a proposal. The harness does not
commit ontology.yaml. Writes outside ``.docuharnessx/`` are rejected.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from harnessx.core.model_config import ModelConfig
from harnessx.workspace.workspace import Workspace, WorkspaceEscapeError

from docuharnessx._ontology import Vocabulary, load_vocabulary, vocabulary_to_config
from docuharnessx.setup_harness import build_setup_harness, propose_ontology
from _fakes import FakeProvider

_PROPOSAL = (
    "roles:\n"
    "  - id: developer\n"
    "    label: Developer\n"
    "    description: Writes code.\n"
    "intents:\n"
    "  - id: explain\n"
    "    label: Explain\n"
    "    description: Explain the system.\n"
    "subjects:\n"
    '  - "component:"\n'
)


def test_setup_workspace_is_jailed_to_docuharnessx(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    config = build_setup_harness(str(project))
    ws = config.workspace
    assert ws is not None
    jail = (project / ".docuharnessx").resolve()
    assert Path(ws.root).resolve() == jail
    live = Workspace(agent_id=ws.agent_id, root=Path(ws.root), mode=ws.mode)
    with pytest.raises(WorkspaceEscapeError):
        live.resolve(str(project / "outside.txt"))


def test_scripted_harness_returns_loadable_proposal_without_writing(
    tmp_path: Path,
) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    model = ModelConfig(main=FakeProvider(content=_PROPOSAL)).main
    vocab = propose_ontology(str(project), model=model)
    assert isinstance(vocab, Vocabulary)
    assert [r.id for r in vocab.roles] == ["developer"]
    assert [i.id for i in vocab.intents] == ["explain"]
    assert list(vocab.subject_prefixes) == ["component:"]
    loaded = load_vocabulary(vocabulary_to_config(vocab))
    assert loaded == vocab
    assert not (project / ".docuharnessx" / "ontology.yaml").exists()


def test_invalid_proposal_is_not_committed(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    model = ModelConfig(main=FakeProvider(content="not_a_known_key: true\n")).main
    with pytest.raises(ValueError):
        propose_ontology(str(project), model=model)
    assert not (project / ".docuharnessx" / "ontology.yaml").exists()
