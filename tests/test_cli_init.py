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
from docuharnessx.adoption import ADOPTION_RELPATH, load_adoption
from docuharnessx.blueprint import BLUEPRINT_NAME, BLUEPRINT_VERSION

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


def test_init_missing_project_dir_exits_nonzero_and_writes_nothing(
    tmp_path, capsys
) -> None:
    missing = tmp_path / "no" / "such" / "dir"
    assert not missing.exists()

    code = cli.main(["init", str(missing), "--default"])

    assert code != 0
    combined = capsys.readouterr()
    message = combined.out + combined.err
    assert str(missing) in message
    assert not missing.exists()
    assert not (missing / ".docuharnessx").exists()


def test_init_project_path_that_is_a_file_exits_nonzero(tmp_path, capsys) -> None:
    target = tmp_path / "not-a-dir"
    target.write_text("x", encoding="utf-8")

    code = cli.main(["init", str(target), "--default"])

    assert code != 0
    assert not (target.parent / ".docuharnessx").exists()
    assert target.is_file()


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


def test_init_interactive_gathers_roles_intents_subjects(
    tmp_path, capsys, monkeypatch
) -> None:
    # Req 9.2: run interactively (an injected line-reader scripts the answers), so
    # `dhx init` asks which roles exist, what the intents are, and which
    # tags/subjects apply, assembles them into a Vocabulary via the ontology-engine
    # API, and writes a loadable .docuharnessx/ontology.yaml.
    project = tmp_path / "proj"
    project.mkdir()
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    answers = iter(
        [
            "",                      # API key (none present → no-model)
            "",                      # base URL → DeepSeek default
            "",                      # model → DeepSeek default
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
    env_path = project / ".env"
    assert env_path.is_file()
    env_text = env_path.read_text(encoding="utf-8")
    assert "OPENAI_API_BASE=https://api.deepseek.com" in env_text
    assert "OPENAI_DEFAULT_MAIN_MODEL=deepseek-v4-flash" in env_text
    assert "OPENAI_API_KEY=" not in env_text


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


# --------------------------------------------------------------------------- #
# Task 2.1 — --default also seeds adoption.yaml (Req 1.2, 1.4, 1.6, 12.7)      #
# --------------------------------------------------------------------------- #


def _adoption_path(project_dir: str) -> str:
    return os.path.join(project_dir, ADOPTION_RELPATH)


def test_init_default_writes_adoption_and_reports_paths_and_version(tmp_path, capsys) -> None:
    project = tmp_path / "proj"
    project.mkdir()

    code = cli.main(["init", str(project), "--default"])

    assert code == 0
    ontology = _config_path(str(project))
    adoption = _adoption_path(str(project))
    assert os.path.isfile(ontology)
    assert os.path.isfile(adoption)
    assert load_vocabulary(ontology) == default_profile()

    record = load_adoption(str(project))
    assert record is not None
    assert record.blueprint_name == BLUEPRINT_NAME
    assert record.blueprint_version == BLUEPRINT_VERSION
    assert record.sufficient is False

    out = capsys.readouterr().out
    assert ontology in out, out
    assert adoption in out, out
    assert BLUEPRINT_VERSION in out, out
    assert "not agent-managed" in out, out


def test_init_default_second_run_without_force_leaves_files_unchanged(tmp_path, capsys) -> None:
    project = tmp_path / "proj"
    project.mkdir()

    assert cli.main(["init", str(project), "--default"]) == 0
    ontology = _config_path(str(project))
    adoption = _adoption_path(str(project))
    with open(ontology, "rb") as handle:
        ontology_bytes = handle.read()
    with open(adoption, "rb") as handle:
        adoption_bytes = handle.read()
    capsys.readouterr()

    second = cli.main(["init", str(project), "--default"])

    assert second != 0
    err = capsys.readouterr().err
    assert ontology in err, err
    assert "adopted blueprint" in err, err
    with open(ontology, "rb") as handle:
        assert handle.read() == ontology_bytes
    with open(adoption, "rb") as handle:
        assert handle.read() == adoption_bytes


def test_init_default_force_overwrites_ontology_and_adoption(tmp_path) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    assert cli.main(["init", str(project), "--default"]) == 0
    adoption = _adoption_path(str(project))
    with open(adoption, "w", encoding="utf-8") as handle:
        handle.write("blueprint_name: tampered\nblueprint_version: 0.0.0\n")

    assert cli.main(["init", str(project), "--default", "--force"]) == 0

    record = load_adoption(str(project))
    assert record is not None
    assert record.blueprint_name == BLUEPRINT_NAME
    assert record.blueprint_version == BLUEPRINT_VERSION
    assert record.sufficient is False
    assert load_vocabulary(_config_path(str(project))) == default_profile()


def test_init_default_does_not_prompt_for_credentials_or_print_secrets(
    tmp_path, capsys, monkeypatch
) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    monkeypatch.setenv("OPENAI_API_KEY", "sk-super-secret-value")
    prompted: list[str] = []

    def _reader(prompt: str = "") -> str:
        prompted.append(prompt)
        raise AssertionError(f"dhx init --default must not prompt: {prompt!r}")

    code = cli.main(["init", str(project), "--default"], init_input=_reader)

    assert code == 0
    assert prompted == []
    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert "sk-super-secret-value" not in combined
    assert "API key" not in combined
    assert "api key" not in combined.lower()
    assert "OPENAI_API_KEY" not in combined
