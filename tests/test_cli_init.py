"""Tests for the ``dhx init`` subcommand dispatch (task 4.3 boundary: dhx CLI).

Task 4.3 wires the ``init`` subcommand in :mod:`docuharnessx.cli` to
:func:`docuharnessx.ontology_setup.run_init`:

* dispatch ``dhx init [project-dir] [--default] [--force]`` to ``run_init``,
  passing the resolved project dir, the ``--default`` choice, and ``--force``
  (Req 9.1, 9.3);
* report the written ``.docuharnessx/ontology.yaml`` path on success → exit 0
  (Req 9.1);
* map a refused overwrite (existing file, no ``--force``) to a non-zero exit with
  an explicit message naming the file (Req 9.6);
* ``--force`` overwrites an existing file (exit 0).

These tests touch no model and no network: ``dhx init`` never runs the harness.
"""

from __future__ import annotations

import os

from docuharnessx import cli
from docuharnessx._ontology import Vocabulary, default_profile, load_vocabulary

_CONFIG_RELPATH = os.path.join(".docuharnessx", "ontology.yaml")


def _config_path(project_dir: str) -> str:
    return os.path.join(project_dir, _CONFIG_RELPATH)


# --------------------------------------------------------------------------- #
# dhx init --default writes a valid ontology.yaml, exit 0, path reported       #
# (Req 9.1, 9.3, 9.5)                                                          #
# --------------------------------------------------------------------------- #


def test_init_default_writes_ontology_exit_zero_and_reports_path(tmp_path, capsys) -> None:
    project = tmp_path / "proj"
    project.mkdir()

    code = cli.main(["init", str(project), "--default"])

    assert code == 0
    written = _config_path(str(project))
    assert os.path.isfile(written), "dhx init --default must write .docuharnessx/ontology.yaml"
    # The written path is reported on success (Req 9.1).
    out = capsys.readouterr().out
    assert written in out, out
    # The written file is a valid vocabulary the engine loader accepts (Req 9.5).
    vocab = load_vocabulary(written)
    assert isinstance(vocab, Vocabulary)
    assert vocab == default_profile()


def test_init_default_in_current_dir_when_project_dir_omitted(tmp_path, capsys, monkeypatch) -> None:
    # ``[project-dir]`` defaults to the current directory.
    project = tmp_path / "cwd-proj"
    project.mkdir()
    monkeypatch.chdir(project)

    code = cli.main(["init", "--default"])

    assert code == 0
    written = _config_path(str(project))
    assert os.path.isfile(written)
    assert _config_path(".") in capsys.readouterr().out or written in capsys.readouterr().out


# --------------------------------------------------------------------------- #
# Refused overwrite: existing file, no --force → non-zero + explicit message   #
# (Req 9.6)                                                                    #
# --------------------------------------------------------------------------- #


def test_init_second_run_without_force_exits_nonzero(tmp_path, capsys) -> None:
    project = tmp_path / "proj"
    project.mkdir()

    first = cli.main(["init", str(project), "--default"])
    assert first == 0
    capsys.readouterr()  # drain the success output

    second = cli.main(["init", str(project), "--default"])

    assert second != 0
    err = capsys.readouterr().err
    # The message explicitly names the offending file (Req 9.6).
    assert _config_path(str(project)) in err, err
    # The existing file is NOT clobbered: it still loads as the default profile.
    assert load_vocabulary(_config_path(str(project))) == default_profile()


# --------------------------------------------------------------------------- #
# --force overwrites an existing file (exit 0)                                  #
# --------------------------------------------------------------------------- #


def test_init_force_overwrites_existing_file(tmp_path) -> None:
    project = tmp_path / "proj"
    project.mkdir()

    assert cli.main(["init", str(project), "--default"]) == 0
    # A second --default run with --force succeeds (overwrites).
    assert cli.main(["init", str(project), "--default", "--force"]) == 0
    assert os.path.isfile(_config_path(str(project)))


# --------------------------------------------------------------------------- #
# Non-default, no interactive answers → graceful non-zero (no crash)           #
# --------------------------------------------------------------------------- #


def test_init_without_default_or_answers_exits_nonzero_gracefully(tmp_path, capsys) -> None:
    # Without --default (and with no interactive answer source: non-TTY, no injected
    # reader), there is nothing to build. The CLI must fail gracefully with a
    # non-zero exit and an explicit message, not crash with a traceback.
    project = tmp_path / "proj"
    project.mkdir()

    code = cli.main(["init", str(project)])

    assert code != 0
    combined = capsys.readouterr()
    message = combined.out + combined.err
    assert "--default" in message, message
    # No file was written.
    assert not os.path.exists(_config_path(str(project)))


# --------------------------------------------------------------------------- #
# Interactive `dhx init` gathers roles/intents/subjects (Req 9.2)              #
# --------------------------------------------------------------------------- #


def test_init_interactive_gathers_roles_intents_subjects(tmp_path, capsys) -> None:
    # Req 9.2: run interactively (an injected line-reader scripts the answers), so
    # `dhx init` asks which roles exist, what the intents are, and which
    # tags/subjects apply, assembles them into a Vocabulary via the ontology-engine
    # API, and writes a loadable .docuharnessx/ontology.yaml.
    project = tmp_path / "proj"
    project.mkdir()

    answers = iter(
        [
            "developer: Developer",  # role 1
            "maintainer",            # role 2 (id doubles as label)
            "",                      # end roles
            "explain: Explain",      # intent 1
            "",                      # end intents
            "component",             # subject 1 (normalised to 'component:')
            "",                      # end subjects
        ]
    )

    def _reader(_prompt: str = "") -> str:
        return next(answers)

    code = cli.main(["init", str(project)], init_input=_reader)

    assert code == 0
    written = _config_path(str(project))
    assert os.path.isfile(written), "interactive dhx init must write ontology.yaml"
    assert written in capsys.readouterr().out

    # The written file is a valid vocabulary the engine loader accepts (Req 9.5),
    # assembled from exactly the operator's answers (Req 9.2).
    vocab = load_vocabulary(written)
    assert isinstance(vocab, Vocabulary)
    assert [r.id for r in vocab.roles] == ["developer", "maintainer"]
    assert [i.id for i in vocab.intents] == ["explain"]
    assert list(vocab.subject_prefixes) == ["component:"]
    # An interactive build is NOT the default profile.
    assert vocab != default_profile()


def test_init_interactive_does_not_overwrite_without_force(tmp_path, capsys) -> None:
    # Even interactively, an existing ontology.yaml is not clobbered without --force
    # (Req 9.6).
    project = tmp_path / "proj"
    project.mkdir()
    assert cli.main(["init", str(project), "--default"]) == 0
    capsys.readouterr()

    answers = iter(["developer", "", "", ""])  # roles: developer; empty intents/subjects

    def _reader(_prompt: str = "") -> str:
        return next(answers)

    code = cli.main(["init", str(project)], init_input=_reader)
    assert code != 0
    assert _config_path(str(project)) in capsys.readouterr().err
    # The existing default-profile file is intact.
    assert load_vocabulary(_config_path(str(project))) == default_profile()
