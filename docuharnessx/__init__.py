"""DocuHarnessX: human-centric, role-based documentation generator built on HarnessX.

Note: this package root and pyproject.toml are owned by the harness-bundle-skeleton
spec. They are bootstrapped minimally here so the ontology-engine spec can be built
first; the skeleton implementation extends this scaffold (CLI entry points,
harnessx dependency, stage sub-packages).

Public API re-export (Req 1.5)
------------------------------
:func:`make_docgen` — the bundle composition seam — is re-exported at the package
root so callers reach it as ``docuharnessx.make_docgen``. It is exposed lazily via
:func:`__getattr__` so merely importing :mod:`docuharnessx` (e.g. for the
pure-ontology sub-package) does not eagerly import the HarnessX composition surface;
the import happens only when ``make_docgen`` is first accessed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

__version__ = "0.0.0"

__all__ = ["__version__", "make_docgen"]

if TYPE_CHECKING:  # pragma: no cover - typing only
    from docuharnessx.bundle import make_docgen


def __getattr__(name: str) -> object:
    """Lazily re-export :func:`docuharnessx.bundle.make_docgen` (Req 1.5).

    PEP 562 module-level ``__getattr__``: keeps the HarnessX-dependent bundle import
    out of the package-import path while still exposing ``docuharnessx.make_docgen``.
    """
    if name == "make_docgen":
        from docuharnessx.bundle import make_docgen

        return make_docgen
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
