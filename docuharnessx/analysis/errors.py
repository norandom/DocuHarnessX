"""The small, stage-scoped error hierarchy for the analysis core (task 1.5).

The analysis error strategy mirrors the skeleton's — *fail fast at boundaries
with explicit, typed errors whose message names the cause* (design "Error
Handling → Error Strategy") — but the hierarchy is **deliberately separate** from
the skeleton-wide :mod:`docuharnessx.errors` family. The pure analysis core is
stdlib-only and must stay unit-testable without the harness, so it owns its own
self-contained base rather than reaching into the skeleton's CLI-boundary errors
(design "pure-core + stage-adapter"; the package's allowed dependencies are the
model, the run context, and the standard library only).

Two error registers live in the analysis package, and only the *fatal* ones are
modelled here:

* **Fatal, stage-scoped** conditions halt the run with an identifiable cause and
  produce **no** partial output (Req 8.4). These are the errors below.
* **Recoverable, in-scan** conditions (an unreadable file, a partially-parseable
  manifest, a tripped scan limit) are *absorbed* by the scanner/detectors:
  recorded in ``ScanStats.notes``/counters and surfaced in the journal, never
  raised (Req 1.5, 2.3, 5.6). They are intentionally **not** error types.

The errors here are raised by the scanner, the two stage adapters
(``stages/ingest.py`` / ``stages/analyze.py``), and ``serde`` in later tasks:

* :class:`AnalysisError` — the single base for the family, so a caller (the
  stage boundary) can catch the whole family while still distinguishing causes.
* :class:`IngestError` — the Ingest stage's target-repository slot is unset, or
  its path is missing / not a directory; the message names the offending
  slot/path (Req 1.2, 8.4).
* :class:`AnalyzeError` — the Analyze stage's file-inventory slot is unset; the
  message names the offending slot (Req 8.4).
* :class:`RepoAnalysisVersionError` — ``serde.from_dict`` received a
  ``schema_version`` it does not understand; the message names the offending
  version (Req 6.3, 6.6).

This module defines errors only — it owns no scanning, serialization, or stage
behavior (task 1.5 boundary: analysis errors).
"""

from __future__ import annotations

__all__ = [
    "AnalysisError",
    "IngestError",
    "AnalyzeError",
    "RepoAnalysisVersionError",
]


class AnalysisError(Exception):
    """Base class for every explicit error raised by the analysis core.

    Provides a single catch-all type at the stage boundary while letting each
    fatal failure path raise a specific subclass with an explicit, cause-naming
    message. Kept independent of the skeleton-wide ``DocuHarnessXError`` so the
    pure analysis core stays self-contained and harness-free.
    """


class IngestError(AnalysisError):
    """The Ingest stage cannot obtain a valid target repository to scan.

    Raised when the target-repository slot is unset, or its path does not exist
    or is not a directory. The Ingest stage raises this *before* producing any
    inventory so an invalid target halts the run with a clear cause naming the
    offending slot/path, rather than emitting a partial inventory (Req 1.2, 8.4).
    """


class AnalyzeError(AnalysisError):
    """The Analyze stage cannot obtain a file inventory to analyze.

    Raised when the file-inventory slot is unset (the Ingest stage did not run or
    did not publish it). The Analyze stage raises this *before* producing any
    analysis so a missing inventory halts the run with a clear cause naming the
    offending slot, rather than emitting a partial ``RepoAnalysis`` (Req 8.4).
    """


class RepoAnalysisVersionError(AnalysisError):
    """A serialized ``RepoAnalysis`` carries an unsupported ``schema_version``.

    Raised by ``serde.from_dict`` when the ``schema_version`` it is handed is not
    one this build understands, so a consumer reading a future/foreign contract
    fails loudly with a message naming the offending version rather than silently
    mis-reconstructing the seam (Req 6.3, 6.6).
    """
