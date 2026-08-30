"""End-to-end acceptance tests for the dhx CLI.

Credential-free: every run injects :class:`tests._fakes.FakeProvider`. The
explore-first pipeline writes a run report; dummy outer-harness journal traces
and eight-stage participation markers are not the product.
"""

from __future__ import annotations

import os
import sys

from harnessx.core.model_config import ModelConfig

from docuharnessx import cli
from docuharnessx._ontology import Vocabulary, default_profile, load_vocabulary

from _fakes import FakeProvider

_ONTOLOGY_RELPATH = os.path.join(".docuharnessx", "ontology.yaml")


def _fake_model() -> ModelConfig:
    """A ``ModelConfig`` bound to the no-network fake provider (credential-free)."""
    return ModelConfig(main=FakeProvider())


def test_e2e_run_exits_zero_with_report(tmp_path, capsys) -> None:
    """`dhx run <target> --out DIR` completes and writes a run report."""
    target = tmp_path / "repo"
    target.mkdir()
    (target / "README.md").write_text("# sample repo\n", encoding="utf-8")
    (target / "main.py").write_text("print('hello')\n", encoding="utf-8")
    out = tmp_path / "out"

    code = cli.main(
        ["run", str(target), "--out", str(out)],
        model_config=_fake_model(),
    )

    assert code == 0
    report = out / "report.json"
    assert report.is_file(), "a run report must be written under --out DIR"
    stdout = capsys.readouterr().out
    assert str(report) in stdout or "Report:" in stdout, stdout


def test_e2e_bare_form_via_production_argv_none_path(tmp_path, monkeypatch, capsys) -> None:
    """The bare form works at the production entry point (argv=None -> sys.argv)."""
    target = tmp_path / "repo"
    target.mkdir()
    (target / "README.md").write_text("# sample repo\n", encoding="utf-8")
    out = tmp_path / "out"

    monkeypatch.setattr(sys, "argv", ["dhx", str(target), "--out", str(out)])
    code = cli.main(model_config=_fake_model())

    assert code == 0, "bare form at the argv=None production path must run and exit 0"
    assert (out / "report.json").is_file(), (
        "the bare-form production run must write a run report"
    )


def test_e2e_reference_form_against_real_repo(tmp_path, capsys) -> None:
    """Mirror `dhx <real-repo> --out DIR` when the reference repo is available."""
    reference_repo = "/home/mc/Source/malware_hashes"
    if not os.path.isdir(reference_repo):  # pragma: no cover - environment-dependent
        import pytest

        pytest.skip(f"reference repo not available: {reference_repo}")

    out = tmp_path / "out"

    code = cli.main(
        ["run", reference_repo, "--out", str(out)],
        model_config=_fake_model(),
    )

    assert code == 0
    assert (out / "report.json").is_file(), (
        "the reference run must write a report under the temp output dir"
    )
    assert not os.path.exists(os.path.join(reference_repo, ".docuharnessx", "out"))


def test_e2e_init_writes_loadable_ontology(tmp_path, capsys) -> None:
    """`dhx init --default` writes a `.docuharnessx/ontology.yaml` the engine loads."""
    project = tmp_path / "fresh-project"
    project.mkdir()

    code = cli.main(["init", str(project), "--default"])

    assert code == 0
    written = os.path.join(str(project), _ONTOLOGY_RELPATH)
    assert os.path.isfile(written), "dhx init must write .docuharnessx/ontology.yaml"
    assert written in capsys.readouterr().out

    vocab = load_vocabulary(written)
    assert isinstance(vocab, Vocabulary)
    assert vocab == default_profile()


def test_e2e_init_then_run_uses_the_written_ontology(tmp_path, capsys) -> None:
    """After ``dhx init``, a subsequent run loads the written vocabulary."""
    target = tmp_path / "repo"
    target.mkdir()
    out = tmp_path / "out"

    init_code = cli.main(["init", str(target), "--default"])
    assert init_code == 0
    capsys.readouterr()

    run_code = cli.main(
        ["run", str(target), "--out", str(out)],
        model_config=_fake_model(),
    )

    assert run_code == 0
    assert (out / "report.json").is_file(), "the run must write a report under --out DIR"
    stdout = capsys.readouterr().out
    assert "using the default ontology profile" not in stdout, stdout
