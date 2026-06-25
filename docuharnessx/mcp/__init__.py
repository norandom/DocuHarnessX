"""The stdio MCP refine server (Wave: spec ``docuharnessx-mcp-refine``).

``docuharnessx.mcp`` is the **single public namespace** for the interactive
document-refinement MCP server. After a batch ``dhx`` run produces the role-based
draft — segments persisted as ``<id>.md`` under ``<out>/segments`` by a
:class:`~docuharnessx.ontology.FilesystemSegmentStore` and a built Material site
under ``<out>/site`` — a human opens the output in an MCP client (opencode / Claude
Code / Cursor) and conversationally refines the documentation through the tools this
package exposes. The package is a **thin composition layer** over DocuHarnessX's
existing modular core: it reuses the bounded agentic writer
(:class:`~docuharnessx.composition.AgenticProseRunner`), the deterministic structure
gate (:func:`~docuharnessx.composition.validate_agent_body`), the blueprint builder,
the segment wiring and fallback renderer, the segment store, the assembler
(:func:`assemble_site` + the per-target site-identity resolver), and the model
resolver. It builds **no** second generation engine and no RAG / embedding / vector
index (Req 1.4).

This module mirrors the existing pure-core package layout
(:mod:`docuharnessx.assembler`, :mod:`docuharnessx.composition`,
:mod:`docuharnessx.review`, :mod:`docuharnessx.planning`): downstream consumers — the
``dhx mcp`` CLI launcher and the tests — import the MCP surface from this one
namespace rather than reaching into submodules, so no second generation engine is
introduced (Req 1.1, 1.5).

This task (1.1) establishes only the package scaffold and introduces **no behaviour
beyond importability**: the namespace deliberately imports nothing eagerly (no model,
no network, no MCP SDK on import), and :data:`__all__` is the authoritative,
self-consistent contract for the package. It starts empty; later tasks populate it as
each module lands, each re-export identity-equal to its submodule definition (no shadow
copies):

* task 1.2 — the per-target session and its resolver
  (:class:`RefineSession`, :func:`resolve_session`) from :mod:`docuharnessx.mcp.session`;
* tasks 2.1 / 2.2 — the pure blueprint glue
  (:func:`planned_from_segment` from :mod:`docuharnessx.mcp.planned`,
  :func:`build_overview_blueprint` from :mod:`docuharnessx.mcp.overview`);
* tasks 3.1-3.4 — the eight tool handlers over a session (``list_segments`` /
  ``get_segment`` / ``validate_segment`` / ``rewrite_segment`` / ``reassemble_site``
  / ``get_overview`` / ``draft_overview`` / ``refine_overview``) from
  :mod:`docuharnessx.mcp.handlers`;
* tasks 4.1 / 4.2 — the server factory and the stdio launcher
  (:func:`build_refine_server`, :func:`run_stdio`) from :mod:`docuharnessx.mcp.server`.

:data:`__all__` is the authoritative, self-consistent contract for the package
(mirroring the sibling pure-core packages): every advertised name resolves on the
package, with no duplicates.
"""

from __future__ import annotations

from docuharnessx.mcp.handlers import (
    draft_overview,
    get_overview,
    get_segment,
    list_segments,
    reassemble_site,
    refine_overview,
    rewrite_segment,
    validate_segment,
)
from docuharnessx.mcp.overview import build_overview_blueprint
from docuharnessx.mcp.planned import planned_from_segment
from docuharnessx.mcp.server import build_refine_server, run_stdio
from docuharnessx.mcp.session import RefineSession, resolve_session

# The public surface is populated by later tasks (2.x, 3.x, 4.x). Task 1.2 adds the
# per-target session and its resolver; tasks 2.1 / 2.2 add the pure blueprint glue
# (``planned_from_segment`` from :mod:`docuharnessx.mcp.planned` and
# ``build_overview_blueprint`` from :mod:`docuharnessx.mcp.overview`); task 3.1 adds the
# read-only, model-free tool handlers (``list_segments`` / ``get_segment`` /
# ``validate_segment`` from :mod:`docuharnessx.mcp.handlers`). Each re-export is
# identity-equal to its submodule definition (no shadow copies), advertising a
# self-consistent, single-namespace contract for the package.
__all__: list[str] = [
    "RefineSession",
    "resolve_session",
    "planned_from_segment",
    "build_overview_blueprint",
    "list_segments",
    "get_segment",
    "validate_segment",
    "rewrite_segment",
    "draft_overview",
    "refine_overview",
    "get_overview",
    "reassemble_site",
    "build_refine_server",
    "run_stdio",
]
