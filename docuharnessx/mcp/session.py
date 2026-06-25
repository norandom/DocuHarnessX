"""The per-target refine session and its resolver (task 1.2; ``docuharnessx-mcp-refine``).

A ``dhx mcp`` process refines exactly one target's documentation. :class:`RefineSession`
holds the per-target state the eight tool handlers read; :func:`resolve_session` resolves that
state from a target repo + output dir, composing the existing DocuHarnessX core **without**
building a second generation engine (Req 1.4):

* it **validates the target first** — an existing directory — before any other work, raising
  the same :class:`~docuharnessx.errors.TargetRepoError` the ``run`` path raises (Req 2.2);
* it resolves the output dir, defaulting to the documented per-target path
  ``<target>/.docuharnessx/out`` when ``--out`` is omitted (mirroring ``dhx run``; Req 2.1);
* it loads the project :class:`Vocabulary` via :func:`load_project_vocabulary` (default profile
  when no ``.docuharnessx/ontology.yaml`` is present; Req 2.7);
* it provisions a :class:`FilesystemSegmentStore` rooted at ``<out>/segments`` — the **single
  on-disk source of truth** the batch run produced and that refine reads/writes (Req 2.3, 4.5);
* it resolves the per-target :class:`SiteIdentity` from the target's ``origin`` remote via
  :func:`resolve_site_identity` over :func:`read_origin_remote` — **never** DocuHarnessX's own
  identity (Req 2.4); and
* it resolves the model, but a no-model :class:`ModelResolutionError` is **swallowed to
  ``None``** so the server can still start and the model-touching tools degrade explicitly
  (Req 2.6); an injected ``model_config`` (tests) is used as-is (Req 10.5).

The optional persisted :class:`RepoAnalysis` is carried as ``analysis`` and defaults to
``None`` (no canonical on-disk analysis artifact exists today); the overview / reassemble
paths tolerate ``None``.

This module imports only the reused core (the ontology loader, the segment store, the
site-identity resolver, the model resolver, and the writer budgets) plus the boundary error
type. It performs no network access and binds no model itself.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from docuharnessx.assembler import read_origin_remote, resolve_site_identity
from docuharnessx.composition import MIN_CITED_FILES
from docuharnessx.config import load_config
from docuharnessx.errors import ModelResolutionError
from docuharnessx.model_resolver import resolve_model
from docuharnessx.ontology import FilesystemSegmentStore
from docuharnessx.ontology_loader import load_project_vocabulary

# The CLI ``run`` path owns the target-validation semantics (existing directory -> absolute
# path, else ``TargetRepoError``). The launcher reuses that exact contract before launching
# the server (Req 2.2), so the resolver imports it rather than re-implementing the check.
from docuharnessx.cli import _validate_target_repo

if TYPE_CHECKING:  # pragma: no cover - typing only
    from harnessx.core.model_config import ModelConfig

    from docuharnessx.analysis.model import RepoAnalysis
    from docuharnessx.assembler import SiteIdentity
    from docuharnessx.ontology.vocabulary import Vocabulary

__all__ = ["RefineSession", "resolve_session"]

#: The output directory used when ``--out`` is omitted, mirroring the ``dhx run`` documented
#: default (``docuharnessx.cli._DEFAULT_OUT_RELPATH``). Resolved relative to the target repo so
#: a refine session reads the same artifacts the batch run produced there (Req 2.1).
_DEFAULT_OUT_RELPATH = os.path.join(".docuharnessx", "out")


@dataclass
class RefineSession:
    """Per-target refine state shared by the eight tool handlers (design "RefineSession").

    Carries the output dir, the target repo, the loaded :class:`Vocabulary`, the
    :class:`FilesystemSegmentStore` rooted at ``<out>/segments`` (the on-disk source of truth),
    the resolved :class:`ModelConfig` (or ``None`` when no model resolves), the per-target
    :class:`SiteIdentity` (never DocuHarnessX's), the optional :class:`RepoAnalysis`, and the
    minimum-citations bar the rewrite / validate paths enforce (Req 2.3, 2.4, 2.6, 4.5, 6.4).
    """

    out_dir: str
    target_repo: str
    vocab: "Vocabulary"
    store: FilesystemSegmentStore
    model_config: "ModelConfig | None"
    identity: "SiteIdentity"
    analysis: "RepoAnalysis | None" = None
    min_citations: int = field(default=MIN_CITED_FILES)

    def model(self) -> Any | None:
        """The bound agentic model — ``model_config.main`` — or ``None`` when no model.

        This is the only value the rewrite / overview handlers pass to
        ``AgenticProseRunner.run(..., model=session.model())``; a ``None`` model is the signal
        the model-touching tools surface as an explicit "no model configured" result rather
        than producing content (Req 2.6, 5.6, 7.7).
        """
        if self.model_config is None:
            return None
        return self.model_config.main


def resolve_session(
    target_repo: str,
    out_dir: str | None,
    *,
    model_config: "ModelConfig | None" = None,
    config_path: "str | os.PathLike[str] | None" = None,
) -> RefineSession:
    """Resolve the per-target :class:`RefineSession` (design "resolve_session").

    Args:
        target_repo: The target repository path. Validated first as an existing directory; an
            invalid target raises :class:`~docuharnessx.errors.TargetRepoError` **before any
            other work** (Req 2.2).
        out_dir: The output directory, or ``None`` to use the documented per-target default
            ``<target>/.docuharnessx/out`` (Req 2.1).
        model_config: An injected :class:`ModelConfig` (tests / explicit selection) used as-is;
            when ``None``, the model is resolved config-then-env (mirroring ``dhx run``) and a
            no-model :class:`ModelResolutionError` is swallowed to ``None`` so the server still
            starts (Req 2.6, 10.5).
        config_path: An optional ``--config`` YAML path. When given, a ``model:`` declared in
            it is honoured (exactly as ``dhx run`` does) before falling back to the provider
            environment; a named-but-missing/malformed file fails fast (``ConfigError``). Ignored
            when ``model_config`` is injected.

    Returns:
        A fully-populated :class:`RefineSession`. ``model()`` is the resolved provider or
        ``None``; the store is rooted at ``<out>/segments``; the identity is per-target.
    """
    # 1. Validate the target FIRST — before any vocab / store / identity / model work, exactly
    #    as the ``run`` path validates its target (Req 2.2). Returns the absolute path.
    target = _validate_target_repo(target_repo)

    # 2. Resolve the output directory (documented default when omitted; Req 2.1).
    resolved_out = (
        os.path.abspath(out_dir)
        if out_dir
        else os.path.join(target, _DEFAULT_OUT_RELPATH)
    )

    # 3. Load the project vocabulary (default profile when no ontology.yaml is present; Req 2.7).
    #    A present-but-invalid config raises OntologyConfigError from the loader (propagated).
    vocab, _used_default = load_project_vocabulary(target)

    # 4. Provision the FilesystemSegmentStore rooted at <out>/segments — the single on-disk
    #    source of truth the batch run produced and that refine reads/writes (Req 2.3, 4.5).
    store = FilesystemSegmentStore(os.path.join(resolved_out, "segments"), vocab)

    # 5. Resolve the per-target site identity from the target's origin remote — never
    #    DocuHarnessX's own identity (Req 2.4). The remote read is read-only and degrades to
    #    the no-remote fallback (target-derived name) when no usable remote is found.
    identity = resolve_site_identity(target, read_origin_remote(target), {})

    # 6. Resolve the model unless one was injected. A no-model ModelResolutionError is swallowed
    #    to None so the server can still start (Req 2.6); the model-touching tools then degrade
    #    explicitly rather than aborting server startup.
    resolved_model = model_config
    if resolved_model is None:
        # Honour a model declared in --config (config-then-env, like ``dhx run``); a
        # named-but-bad config fails fast (ConfigError from load_config propagates). A
        # no-model resolution is swallowed to None so the server still starts (Req 2.6).
        configured_model = load_config(config_path=config_path, vocabulary=vocab).model
        try:
            resolved_model = resolve_model(configured_model)
        except ModelResolutionError:
            resolved_model = None

    # 7. The optional persisted RepoAnalysis: no canonical on-disk analysis artifact exists
    #    today, so the session carries None (tolerated by the overview / reassemble paths).
    analysis: "RepoAnalysis | None" = None

    return RefineSession(
        out_dir=resolved_out,
        target_repo=target,
        vocab=vocab,
        store=store,
        model_config=resolved_model,
        identity=identity,
        analysis=analysis,
    )
