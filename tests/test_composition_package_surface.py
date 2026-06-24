"""Tests for the finalized ``docuharnessx.composition`` public namespace (task 3.1).

Task 3.1 finalizes ``docuharnessx/composition/__init__.py`` so that — now that the
core modules (2.1-2.5) exist — the single public namespace re-exports every
deterministic-core entry point alongside the model types from task 1.1:

* the model types (task 1.1): ``CompositionBlueprint`` + nested records, ``ProseResult``,
  ``WriteFlag``, ``WrittenSegments``, ``WriterError``/``WriterInputError``;
* the core entry points: ``build_blueprint`` (2.1), ``build_request`` (2.2),
  ``segment_id`` / ``wire_segment`` (2.3), ``render_fallback_body`` /
  ``render_fallback_summary`` (2.4), ``generate_prose`` + ``DEFAULT_PROSE_TIMEOUT_S``
  (2.5).

Each re-export must be **identity-equal** to its submodule definition (no shadow
copies), and ``__all__`` must be the authoritative, self-consistent contract for the
package — mirroring ``docuharnessx.planning.__init__``.
"""

from __future__ import annotations

import importlib


def test_namespace_reexports_model_types_identity_equal() -> None:
    pkg = importlib.import_module("docuharnessx.composition")
    model = importlib.import_module("docuharnessx.composition.model")
    for name in (
        "SCQAOpener",
        "Chunk",
        "EvidenceAnchor",
        "CompositionBlueprint",
        "ProseResult",
        "WriteFlag",
        "WrittenSegments",
        "WriterError",
        "WriterInputError",
    ):
        assert getattr(pkg, name) is getattr(model, name), name


def test_namespace_reexports_core_entry_points_identity_equal() -> None:
    pkg = importlib.import_module("docuharnessx.composition")
    blueprint = importlib.import_module("docuharnessx.composition.blueprint")
    prompt = importlib.import_module("docuharnessx.composition.prompt")
    wiring = importlib.import_module("docuharnessx.composition.wiring")
    fallback = importlib.import_module("docuharnessx.composition.fallback")
    prose = importlib.import_module("docuharnessx.composition.prose")

    assert pkg.build_blueprint is blueprint.build_blueprint
    assert pkg.build_request is prompt.build_request
    assert pkg.segment_id is wiring.segment_id
    assert pkg.wire_segment is wiring.wire_segment
    assert pkg.render_fallback_body is fallback.render_fallback_body
    assert pkg.render_fallback_summary is fallback.render_fallback_summary
    assert pkg.generate_prose is prose.generate_prose
    assert pkg.DEFAULT_PROSE_TIMEOUT_S is prose.DEFAULT_PROSE_TIMEOUT_S


def test_namespace_reexports_agentic_entry_points_identity_equal() -> None:
    """Task 2.5: the new agentic entry points are surfaced from the single namespace,
    each identity-equal to its submodule definition (no shadow copies)."""
    pkg = importlib.import_module("docuharnessx.composition")
    agent = importlib.import_module("docuharnessx.composition.agent")
    task_prompt = importlib.import_module("docuharnessx.composition.task_prompt")
    harness_factory = importlib.import_module(
        "docuharnessx.composition.harness_factory"
    )
    structure_gate = importlib.import_module("docuharnessx.composition.structure_gate")

    assert pkg.AgenticProseRunner is agent.AgenticProseRunner
    assert pkg.AgentRunStats is agent.AgentRunStats
    assert pkg.build_agent_task is task_prompt.build_agent_task
    assert pkg.build_writer_harness is harness_factory.build_writer_harness
    assert pkg.validate_agent_body is structure_gate.validate_agent_body


def test_all_lists_every_public_name_and_is_importable() -> None:
    pkg = importlib.import_module("docuharnessx.composition")
    expected = {
        # model types (task 1.1)
        "SCQAOpener",
        "Chunk",
        "EvidenceAnchor",
        "CompositionBlueprint",
        "ProseResult",
        "WriteFlag",
        "WrittenSegments",
        "WriterError",
        "WriterInputError",
        # core entry points (tasks 2.1-2.5)
        "build_blueprint",
        "build_request",
        "segment_id",
        "wire_segment",
        "render_fallback_body",
        "render_fallback_summary",
        "generate_prose",
        "DEFAULT_PROSE_TIMEOUT_S",
        # writer budget defaults + structure-gate threshold (task 1.1)
        "WRITER_MAX_STEPS",
        "WRITER_MAX_COST_USD",
        "WRITER_TOKEN_BUDGET",
        "WRITER_TOKEN_THRESHOLD",
        "WRITER_LOOP_THRESHOLD",
        "MIN_CITED_FILES",
        # agentic entry points (task 2.5)
        "build_agent_task",
        "validate_agent_body",
        "build_writer_harness",
        "AgenticProseRunner",
        "AgentRunStats",
    }
    assert set(pkg.__all__) == expected
    # __all__ is self-consistent: every advertised name is actually importable.
    for name in pkg.__all__:
        assert hasattr(pkg, name), f"__all__ advertises {name} but it is not present"
    # No duplicates in the contract.
    assert len(pkg.__all__) == len(set(pkg.__all__))
