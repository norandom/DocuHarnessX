"""Unit tests for task 4.2 (the optional, gated LLM enrichment hook).

Task 4.2's boundary is the new ``docuharnessx.analysis.enrich`` module. It is the
*only* surface in the analysis package that may touch a model, and it is designed
so a model can never gate or alter the deterministic core
:class:`~docuharnessx.analysis.model.RepoAnalysis` (design "enrich — optional gated
LLM enrichment"; Req 9.3, 9.4, 9.5).

What these tests pin (the enrich contract):

* ``enrich(analysis, *, model=None, enabled=False, timeout_s=30.0) -> RepoAnalysis``
  exists, is re-exported from the package, and is in ``__all__`` (design service
  interface).
* **Off by default** — with no keyword arguments the result is the *same* object
  the analyzer produced, ``enrichment is None``, and that is treated as success,
  not an error (Req 9.4).
* **Gate honored** — ``enabled=False`` (even with a model) and ``enabled=True``
  with ``model=None`` both return the analysis unchanged (``enrichment is None``)
  (Req 9.4).
* **Enabled + model + success** — returns a copy with the enrichment region set
  (a narrative ``architecture_summary`` and the producing ``model_id``); **every
  deterministic core field is byte-for-byte identical** to the input — enrichment
  only adds the separated region (Req 9.3).
* **Failure-tolerant** — a model whose ``complete`` raises, or that times out,
  results in the *unchanged* core analysis (``enrichment is None``); the failure is
  logged, never raised, and the run continues (Req 9.5).
* The core is never mutated in place: the input ``RepoAnalysis`` is returned with
  identity equality when enrichment is absent, and is ``==`` to the enriched
  result minus its enrichment region when enrichment succeeds.

The tests use small in-test fake providers (an async ``complete`` matching the
HarnessX ``BaseModelProvider`` protocol) so no network or credential is needed —
consistent with the credential-free testing principle.
"""

from __future__ import annotations

import asyncio
import dataclasses
import importlib

from docuharnessx.analysis import model as model_mod
from docuharnessx.analysis.model import (
    REPO_ANALYSIS_SCHEMA_VERSION,
    DocPresence,
    Enrichment,
    LanguageStat,
    RepoAnalysis,
    ScanStats,
)

ENRICH_MODULE = "docuharnessx.analysis.enrich"
PACKAGE = "docuharnessx.analysis"


def _enrich_mod():
    return importlib.import_module(ENRICH_MODULE)


# --------------------------------------------------------------------------- #
# Fixture: a small, fully-populated core RepoAnalysis (enrichment absent)
# --------------------------------------------------------------------------- #


def _core_analysis() -> RepoAnalysis:
    """A complete deterministic core analysis with ``enrichment=None`` (Req 9.4)."""
    return RepoAnalysis(
        schema_version=REPO_ANALYSIS_SCHEMA_VERSION,
        repo_path="/repo",
        languages=(LanguageStat(language="Go", files=2, loc=120),),
        primary_languages=("Go",),
        total_loc=120,
        total_files=2,
        structure=(),
        entrypoints=(),
        build_files=(),
        ci_workflows=(),
        tests=model_mod.TestLayout(present=False, frameworks=(), paths=()),
        dependencies=(),
        components=(),
        public_surface=(),
        docs=DocPresence(
            has_readme=False, readme_paths=(), doc_dirs=(), other_docs=()
        ),
        artifacts=(),
        scan_stats=ScanStats(
            files_scanned=2,
            files_skipped=0,
            bytes_scanned=1000,
            limit_reached=False,
            notes=(),
        ),
        enrichment=None,
    )


# --------------------------------------------------------------------------- #
# Fake providers (BaseModelProvider-shaped; no network, no credentials)
# --------------------------------------------------------------------------- #


class _OkProvider:
    """A provider whose async ``complete`` returns a canned summary."""

    model = "fake-model-1"

    def __init__(self, content: str = "A small Go CLI with one package.") -> None:
        self._content = content
        self.calls = 0

    async def complete(self, messages, tools, stream_callback=None):
        self.calls += 1
        # Mimic ModelResponseEvent only in the attribute the hook reads.
        return _Resp(content=self._content, model=self.model)

    def count_tokens(self, messages) -> int:  # pragma: no cover - not used
        return 1


class _Resp:
    """Minimal stand-in for a HarnessX ``ModelResponseEvent`` (``.content``/``.model``)."""

    def __init__(self, content: str, model: str = "") -> None:
        self.content = content
        self.model = model


class _RaisingProvider:
    """A provider whose ``complete`` raises — the hook must absorb it (Req 9.5)."""

    model = "boom-model"

    def __init__(self) -> None:
        self.calls = 0

    async def complete(self, messages, tools, stream_callback=None):
        self.calls += 1
        raise RuntimeError("model exploded")

    def count_tokens(self, messages) -> int:  # pragma: no cover - not used
        return 1


class _HangingProvider:
    """A provider whose ``complete`` sleeps past the timeout (Req 9.5)."""

    model = "slow-model"

    async def complete(self, messages, tools, stream_callback=None):
        await asyncio.sleep(5.0)
        return _Resp(content="too late", model=self.model)

    def count_tokens(self, messages) -> int:  # pragma: no cover - not used
        return 1


# --------------------------------------------------------------------------- #
# Module / symbol surface
# --------------------------------------------------------------------------- #


def test_task42_enrich_symbol_exists() -> None:
    mod = _enrich_mod()
    assert hasattr(mod, "enrich")
    assert callable(mod.enrich)
    assert "enrich" in mod.__all__


def test_task42_enrich_reexported_from_package() -> None:
    pkg = importlib.import_module(PACKAGE)
    assert hasattr(pkg, "enrich")
    assert "enrich" in pkg.__all__


# --------------------------------------------------------------------------- #
# Off by default / gate honored (Req 9.4)
# --------------------------------------------------------------------------- #


def test_enrich_off_by_default_returns_input_unchanged() -> None:
    """No kwargs -> disabled -> same analysis, enrichment absent, treated as success."""
    mod = _enrich_mod()
    core = _core_analysis()
    result = mod.enrich(core)
    assert result is core  # identity: nothing rebuilt
    assert result.enrichment is None


def test_enrich_disabled_even_with_model_returns_unchanged() -> None:
    """enabled=False with a real model still returns the core unchanged (Req 9.4)."""
    mod = _enrich_mod()
    core = _core_analysis()
    provider = _OkProvider()
    result = mod.enrich(core, model=provider, enabled=False)
    assert result is core
    assert result.enrichment is None
    assert provider.calls == 0  # the model was never consulted


def test_enrich_enabled_without_model_returns_unchanged() -> None:
    """enabled=True but model=None is not an error; returns core unchanged (Req 9.4)."""
    mod = _enrich_mod()
    core = _core_analysis()
    result = mod.enrich(core, model=None, enabled=True)
    assert result is core
    assert result.enrichment is None


def test_enrich_disabled_equals_core_analysis() -> None:
    """Observable: disabled result equals the core analysis (Req 9.4)."""
    mod = _enrich_mod()
    core = _core_analysis()
    assert mod.enrich(core, enabled=False) == core


# --------------------------------------------------------------------------- #
# Enabled + model + success: enrichment attached, core untouched (Req 9.3)
# --------------------------------------------------------------------------- #


def test_enrich_enabled_attaches_enrichment_region() -> None:
    mod = _enrich_mod()
    core = _core_analysis()
    provider = _OkProvider(content="A tidy Go CLI.")
    result = mod.enrich(core, model=provider, enabled=True)

    assert result is not core
    assert isinstance(result.enrichment, Enrichment)
    assert result.enrichment.architecture_summary == "A tidy Go CLI."
    assert result.enrichment.model_id  # a non-empty producing-model id
    assert provider.calls == 1


def test_enrich_success_leaves_every_core_field_identical() -> None:
    """Enrichment only adds the separated region; no core field changes (Req 9.3)."""
    mod = _enrich_mod()
    core = _core_analysis()
    provider = _OkProvider()
    result = mod.enrich(core, model=provider, enabled=True)

    # Stripping the enrichment region must reproduce the original core exactly.
    assert dataclasses.replace(result, enrichment=None) == core
    # And the input object itself was not mutated in place.
    assert core.enrichment is None


def test_enrich_records_producing_model_id() -> None:
    """The enrichment carries the id of the model that produced it (design Enrichment)."""
    mod = _enrich_mod()
    core = _core_analysis()
    provider = _OkProvider()
    result = mod.enrich(core, model=provider, enabled=True)
    assert result.enrichment is not None
    assert result.enrichment.model_id == "fake-model-1"


# --------------------------------------------------------------------------- #
# Failure-tolerant: failure / timeout -> core still returned (Req 9.5)
# --------------------------------------------------------------------------- #


def test_enrich_failure_returns_complete_core_analysis() -> None:
    """A raising model is absorbed: core returned unchanged, no exception (Req 9.5)."""
    mod = _enrich_mod()
    core = _core_analysis()
    provider = _RaisingProvider()
    result = mod.enrich(core, model=provider, enabled=True)
    assert result == core
    assert result.enrichment is None
    assert provider.calls == 1  # it tried, then absorbed the failure


def test_enrich_failure_is_logged(caplog) -> None:
    """The failure path logs (Req 9.5) rather than silently swallowing."""
    import logging

    mod = _enrich_mod()
    core = _core_analysis()
    provider = _RaisingProvider()
    with caplog.at_level(logging.WARNING):
        result = mod.enrich(core, model=provider, enabled=True)
    assert result.enrichment is None
    assert caplog.records  # something was logged about the failed enrichment


def test_enrich_timeout_returns_complete_core_analysis() -> None:
    """A model that hangs past timeout_s is absorbed; core still returned (Req 9.5)."""
    mod = _enrich_mod()
    core = _core_analysis()
    provider = _HangingProvider()
    result = mod.enrich(core, model=provider, enabled=True, timeout_s=0.05)
    assert result == core
    assert result.enrichment is None


def test_enrich_empty_summary_is_absorbed_as_no_enrichment() -> None:
    """A blank/whitespace summary yields no enrichment region (nothing to attach)."""
    mod = _enrich_mod()
    core = _core_analysis()
    provider = _OkProvider(content="   ")
    result = mod.enrich(core, model=provider, enabled=True)
    assert result.enrichment is None
    assert result == core
