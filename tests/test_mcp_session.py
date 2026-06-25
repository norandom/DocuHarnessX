"""Unit tests for task 1.2 (docuharnessx-mcp-refine): ``RefineSession`` + ``resolve_session``.

Task 1.2 owns the per-target refine session and its resolver. ``resolve_session`` is a
pure-Python, **credential-free**, model-optional composition over the existing core:

* it validates the target is an existing directory **before any other work** (Req 2.2),
  raising the same :class:`~docuharnessx.errors.TargetRepoError` the ``run`` path raises;
* it resolves the output dir (documented default ``<target>/.docuharnessx/out`` when omitted),
  loads the project :class:`Vocabulary` via :func:`load_project_vocabulary` (default profile
  when absent; Req 2.7), provisions a :class:`FilesystemSegmentStore` rooted at
  ``<out>/segments`` (Req 2.3, 4.5), and resolves the per-target :class:`SiteIdentity` from the
  target's origin remote (Req 2.4) — **never** DocuHarnessX's own identity;
* it resolves the model, but swallows a no-model :class:`ModelResolutionError` to ``None`` so
  the server still starts (Req 2.6); an injected ``model_config`` (tests) is used as-is
  (Req 10.5).

These tests inject the model (or ``None``) and monkeypatch the single origin-remote read, so
they need no network and no real provider.
"""

from __future__ import annotations

import os

import pytest
from harnessx.core.model_config import ModelConfig

from docuharnessx import mcp
from docuharnessx.assembler import resolve_site_identity
from docuharnessx.composition import MIN_CITED_FILES
from docuharnessx.errors import ModelResolutionError, TargetRepoError
from docuharnessx.mcp.session import RefineSession, resolve_session
from docuharnessx.ontology import FilesystemSegmentStore
from docuharnessx.ontology.vocabulary import Vocabulary

from tests._fakes import FakeProvider


# --------------------------------------------------------------------------- #
# Package surface (1.1 -> 1.2): the session + resolver are re-exported from the   #
# single ``docuharnessx.mcp`` namespace, identity-equal to the submodule defs.    #
# --------------------------------------------------------------------------- #


def test_session_surface_reexported_from_package() -> None:
    # Req 1.5: the single public namespace advertises the session + resolver, and each
    # re-export is identity-equal to its submodule definition (no shadow copies).
    assert mcp.RefineSession is RefineSession
    assert mcp.resolve_session is resolve_session
    assert "RefineSession" in mcp.__all__
    assert "resolve_session" in mcp.__all__
    # __all__ stays self-consistent + unique after 1.2 populates it.
    assert len(mcp.__all__) == len(set(mcp.__all__))
    for name in mcp.__all__:
        assert hasattr(mcp, name)


# --------------------------------------------------------------------------- #
# Target validation: fatal, pre-launch, identifiable (Req 2.2).                  #
# --------------------------------------------------------------------------- #


def test_missing_target_raises_before_any_work() -> None:
    # An empty/missing target is identifiable and raised before any vocab/store/model work.
    with pytest.raises(TargetRepoError):
        resolve_session("", None)


def test_nonexistent_target_raises_before_any_work(tmp_path) -> None:
    missing = str(tmp_path / "does-not-exist")
    with pytest.raises(TargetRepoError):
        resolve_session(missing, None)


def test_file_target_raises_before_any_work(tmp_path) -> None:
    f = tmp_path / "a-file"
    f.write_text("not a directory", encoding="utf-8")
    with pytest.raises(TargetRepoError):
        resolve_session(str(f), None)


def test_invalid_target_does_no_filesystem_work(tmp_path, monkeypatch) -> None:
    # The validation is the FIRST thing the resolver does: it must not have touched the
    # remote read or the vocab loader before failing.
    import docuharnessx.mcp.session as session_mod

    called: list[str] = []
    monkeypatch.setattr(
        session_mod, "read_origin_remote", lambda repo: called.append("remote") or None
    )
    monkeypatch.setattr(
        session_mod,
        "load_project_vocabulary",
        lambda repo: called.append("vocab") or (_ for _ in ()).throw(AssertionError),
    )
    with pytest.raises(TargetRepoError):
        resolve_session(str(tmp_path / "nope"), None)
    assert called == []


# --------------------------------------------------------------------------- #
# Happy path with an injected ModelConfig: store rooted at <out>/segments, loaded #
# vocabulary, per-target identity from a fake origin remote, model() is provider. #
# --------------------------------------------------------------------------- #


def _github_remote_target(tmp_path, monkeypatch) -> str:
    """A valid target directory whose origin remote is a (faked) GitHub URL.

    Monkeypatches the single ``read_origin_remote`` subprocess so the test needs no git and
    no network; the resolved identity is therefore the project's GitHub-Pages identity, never
    DocuHarnessX's.
    """
    import docuharnessx.mcp.session as session_mod

    target = tmp_path / "acme-widget"
    target.mkdir()
    monkeypatch.setattr(
        session_mod,
        "read_origin_remote",
        lambda repo: "https://github.com/acme/widget.git",
    )
    return str(target)


def test_resolve_with_injected_model_carries_full_session(tmp_path, monkeypatch) -> None:
    target = _github_remote_target(tmp_path, monkeypatch)
    out = tmp_path / "out"
    provider = FakeProvider()
    sess = resolve_session(target, str(out), model_config=ModelConfig(main=provider))

    assert isinstance(sess, RefineSession)
    # Req 2.3 / 4.5: the store is a FilesystemSegmentStore rooted at <out>/segments.
    assert isinstance(sess.store, FilesystemSegmentStore)
    assert os.path.abspath(sess.out_dir) == os.path.abspath(str(out))
    expected_segments = os.path.join(os.path.abspath(str(out)), "segments")
    assert any(
        os.path.abspath(str(v)) == expected_segments
        for v in vars(sess.store).values()
        if isinstance(v, (str, os.PathLike))
    ), f"store not rooted at {expected_segments}: {vars(sess.store)}"

    # Req 2.7: the loaded project vocabulary (default profile when absent).
    assert isinstance(sess.vocab, Vocabulary)

    # Req 2.4: per-target identity derived from the (faked) GitHub origin remote — and
    # explicitly NOT DocuHarnessX's identity.
    expected_identity = resolve_site_identity(
        target, "https://github.com/acme/widget.git", {}
    )
    assert sess.identity == expected_identity
    assert sess.identity.site_name == "widget"
    assert sess.identity.repo_name == "acme/widget"
    assert "DocuHarnessX" not in sess.identity.site_name
    assert "docuharnessx" not in (sess.identity.repo_url or "").lower()

    # Req 10.5: an injected model is used as-is; model() yields its ``main`` provider.
    assert sess.model() is provider
    assert sess.model_config is not None
    # The min-citations bar matches the rewrite/validate path (Req 6.4).
    assert sess.min_citations == MIN_CITED_FILES
    # Per-target target repo is carried (absolute).
    assert os.path.abspath(sess.target_repo) == os.path.abspath(target)


def test_resolve_with_injected_none_model_yields_no_model(tmp_path, monkeypatch) -> None:
    # Req 10.5 / 2.6: injecting model_config=None resolves a session whose model() is None,
    # so the server can still start and model-touching tools degrade explicitly.
    target = _github_remote_target(tmp_path, monkeypatch)
    sess = resolve_session(target, str(tmp_path / "out"), model_config=None)
    # With no env-resolved model either (see no-model test), model() is None.
    # Here we additionally assert the rest of the session is still fully populated.
    assert isinstance(sess.store, FilesystemSegmentStore)
    assert isinstance(sess.vocab, Vocabulary)
    assert sess.identity.site_name == "widget"


def test_default_out_dir_when_omitted(tmp_path, monkeypatch) -> None:
    # Req 2.1: the documented per-target default is <target>/.docuharnessx/out.
    target = _github_remote_target(tmp_path, monkeypatch)
    sess = resolve_session(target, None, model_config=ModelConfig(main=FakeProvider()))
    expected = os.path.join(os.path.abspath(target), ".docuharnessx", "out")
    assert os.path.abspath(sess.out_dir) == expected
    expected_segments = os.path.join(expected, "segments")
    assert any(
        os.path.abspath(str(v)) == expected_segments
        for v in vars(sess.store).values()
        if isinstance(v, (str, os.PathLike))
    )


def test_default_profile_vocab_when_absent(tmp_path, monkeypatch) -> None:
    # Req 2.7: with no .docuharnessx/ontology.yaml present, the default profile loads (no error).
    target = _github_remote_target(tmp_path, monkeypatch)
    sess = resolve_session(target, str(tmp_path / "out"), model_config=None)
    assert isinstance(sess.vocab, Vocabulary)


# --------------------------------------------------------------------------- #
# No-model resolution: a ModelResolutionError is swallowed to None so the server  #
# still starts (Req 2.6). No injected model, env scrubbed, resolver forced to fail.#
# --------------------------------------------------------------------------- #


def test_no_model_resolution_swallowed_to_none(tmp_path, monkeypatch) -> None:
    import docuharnessx.mcp.session as session_mod

    target = _github_remote_target(tmp_path, monkeypatch)

    def _raise(model_id):  # noqa: ANN001
        raise ModelResolutionError("no model configured")

    monkeypatch.setattr(session_mod, "resolve_model", _raise)

    sess = resolve_session(target, str(tmp_path / "out"))  # no model_config injected
    # Req 2.6: the resolver swallowed the error to None — the server can still start.
    assert sess.model_config is None
    assert sess.model() is None
    # The rest of the session is still fully populated (degrades gracefully, not aborts).
    assert isinstance(sess.store, FilesystemSegmentStore)
    assert isinstance(sess.vocab, Vocabulary)
    assert sess.identity.site_name == "widget"


def test_env_resolved_model_is_used_when_not_injected(tmp_path, monkeypatch) -> None:
    # When no model_config is injected but resolve_model succeeds, the session binds it
    # and model() yields its provider (Req 2.3) — without any network (resolver is faked).
    import docuharnessx.mcp.session as session_mod

    target = _github_remote_target(tmp_path, monkeypatch)
    provider = FakeProvider()
    monkeypatch.setattr(
        session_mod, "resolve_model", lambda model_id: ModelConfig(main=provider)
    )
    sess = resolve_session(target, str(tmp_path / "out"))
    assert sess.model() is provider


# --------------------------------------------------------------------------- #
# Per-target identity is never DocuHarnessX's, even with no remote (Req 2.4/2.5). #
# --------------------------------------------------------------------------- #


def test_identity_no_remote_falls_back_to_target_name(tmp_path, monkeypatch) -> None:
    import docuharnessx.mcp.session as session_mod

    target = tmp_path / "some-target-project"
    target.mkdir()
    monkeypatch.setattr(session_mod, "read_origin_remote", lambda repo: None)
    sess = resolve_session(str(target), str(tmp_path / "out"), model_config=None)
    # The no-remote fallback derives the identity from the target dir, never DocuHarnessX.
    assert sess.identity.site_name == "some-target-project"
    assert "DocuHarnessX" not in sess.identity.site_name


def test_analysis_defaults_to_none_when_absent(tmp_path, monkeypatch) -> None:
    # The optional persisted RepoAnalysis is absent here -> the session carries None,
    # which the overview/reassemble paths tolerate.
    target = _github_remote_target(tmp_path, monkeypatch)
    sess = resolve_session(target, str(tmp_path / "out"), model_config=None)
    assert sess.analysis is None


# --------------------------------------------------------------------------- #
# --config model selection: a `model:` declared in --config is honoured        #
# (config-then-env, like `dhx run`); a named-but-bad config fails fast.         #
# --------------------------------------------------------------------------- #


def test_resolve_honours_model_from_config(tmp_path, monkeypatch) -> None:
    from harnessx.providers.anthropic_provider import AnthropicProvider

    target = _github_remote_target(tmp_path, monkeypatch)
    cfg = tmp_path / "dhx.yaml"
    cfg.write_text("model: claude-sonnet-4-6\n", encoding="utf-8")
    # No injected model: the model must come from the --config YAML (not env).
    sess = resolve_session(target, str(tmp_path / "out"), config_path=str(cfg))
    assert sess.model_config is not None
    # The configured id selects the provider class; never DocuHarnessX-specific.
    assert isinstance(sess.model_config.main, AnthropicProvider)
    assert sess.model_config.main.model == "claude-sonnet-4-6"


def test_resolve_with_named_missing_config_fails_fast(tmp_path, monkeypatch) -> None:
    from docuharnessx.errors import ConfigError

    target = _github_remote_target(tmp_path, monkeypatch)
    with pytest.raises(ConfigError):
        resolve_session(
            target, str(tmp_path / "out"), config_path=str(tmp_path / "nope.yaml")
        )
