"""Cross-feature regression boundary for docuharnessx-mcp-refine (task 6.2).

Task 6.2 (boundary: *cross-feature regression*) does not add behaviour; it **pins**
that the MCP-refine feature stayed inside its declared blast radius. Per the spec
(Requirements 1.1, 1.2, 1.4; design "This Spec Also Owns" / "Frozen seams"), the ONLY
code the feature is allowed to add or change outside the new ``docuharnessx/mcp/``
package is:

  * the one ``dhx mcp`` subcommand in ``docuharnessx/cli.py``;
  * the additive, backward-compatible ``guidance: str = ""`` keyword on the bounded
    writer (``docuharnessx/composition/agent.py`` + ``docuharnessx/composition/task_prompt.py``);
  * the ``mcp>=1.28`` direct dependency in ``pyproject.toml``.

Everything else must be untouched: the frozen **data** seams (``Segment`` /
``WrittenSegments`` / the ``SegmentStore`` Protocol / ``ReviewReport`` /
``AssembledSite``), the pipeline stages, the assembler renderers, the model resolver,
and the ``dhx run`` / ``dhx init`` / bare-form CLI paths.

These tests assert that boundary three ways:

  (A) **Diff boundary** — the set of tracked files modified versus ``HEAD`` is a subset
      of the four allowed files, and in particular no frozen-seam / stage / assembler /
      model-resolver module appears in the diff (Req 1.1, 1.2).
  (B) **Structural seam pins** — the frozen data-seam types still carry exactly their
      field names, order, and schema-version constants (Req 1.2). A field rename/reorder
      anywhere would break a downstream consumer; this fails loudly first.
  (C) **Byte-identical writer** — with ``guidance=""`` the rendered task is reconstructed
      from the pristine ``HEAD`` ``task_prompt`` blob and compared byte-for-byte with the
      current renderer, proving the writer extension is behaviour-preserving by default
      (Req 1.2, 1.4) — independent of the same-process check in ``test_writer_guidance``.

No model is consulted; nothing touches the network. The diff checks degrade to skips
(never false failures) when the test tree is not a git checkout of this repo.
"""

from __future__ import annotations

import dataclasses
import importlib
import subprocess
import types
import typing

import pytest

REPO_ROOT = "/home/mc/Source/DocuHarnessX"

# The exhaustive allow-list of files the feature may add/modify OUTSIDE the new
# ``docuharnessx/mcp/`` package and its sibling test files (Req 1.1).
ALLOWED_NON_MCP_CHANGES = frozenset(
    {
        "docuharnessx/cli.py",  # the one `dhx mcp` subcommand
        "docuharnessx/composition/agent.py",  # additive guidance kw
        "docuharnessx/composition/task_prompt.py",  # additive guidance kw (renderer)
        "pyproject.toml",  # mcp>=1.28 direct dependency
    }
)

# Modules that MUST stay byte-untouched by this feature (Req 1.2). A frozen data
# seam, a pipeline stage, the assembler renderers, or the model resolver appearing
# in the working-tree diff is an immediate boundary violation.
FROZEN_OFF_LIMITS_MODULES = frozenset(
    {
        # frozen data seams + their owners
        "docuharnessx/ontology/schema.py",  # Segment
        "docuharnessx/ontology/store.py",  # SegmentStore Protocol + adapters
        "docuharnessx/composition/model.py",  # WrittenSegments
        "docuharnessx/review/model.py",  # ReviewReport / ReviewAggregate
        "docuharnessx/assembler/model.py",  # AssembledSite / SiteIdentity
        # the pipeline stages (none may be edited)
        "docuharnessx/stages/ingest.py",
        "docuharnessx/stages/analyze.py",
        "docuharnessx/stages/classify.py",
        "docuharnessx/stages/plan.py",
        "docuharnessx/stages/write.py",
        "docuharnessx/stages/review.py",
        "docuharnessx/stages/assemble.py",
        "docuharnessx/stages/deploy.py",
        # the assembler renderers
        "docuharnessx/assembler/writer.py",
        "docuharnessx/assembler/pages.py",
        "docuharnessx/assembler/roles.py",
        "docuharnessx/assembler/home.py",
        "docuharnessx/assembler/theme.py",
        "docuharnessx/assembler/identity.py",
        "docuharnessx/assembler/mkdocs_config.py",
        # the model resolver
        "docuharnessx/model_resolver.py",
    }
)


# --------------------------------------------------------------------------- #
# git helpers — degrade to skip (never fail) when not a git checkout           #
# --------------------------------------------------------------------------- #


def _git(*args: str) -> str:
    return subprocess.check_output(
        ["git", *args],
        cwd=REPO_ROOT,
        stderr=subprocess.DEVNULL,
    ).decode()


def _is_git_repo() -> bool:
    try:
        out = _git("rev-parse", "--is-inside-work-tree").strip()
    except (OSError, subprocess.CalledProcessError):
        return False
    return out == "true"


def _tracked_modified_paths() -> set[str]:
    """Tracked files that differ from ``HEAD`` (staged + unstaged), repo-relative."""
    # `git diff HEAD --name-only` reports both staged and unstaged changes to tracked
    # files; newly-added untracked files (the mcp package + tests) are intentionally
    # NOT reported here — they are validated separately.
    return {line for line in _git("diff", "HEAD", "--name-only").splitlines() if line}


# --------------------------------------------------------------------------- #
# (A) Diff boundary: only the four allowed files changed; seams untouched      #
# --------------------------------------------------------------------------- #


def test_no_unexpected_files_modified_outside_mcp_package() -> None:
    """Every tracked modification is either inside the allow-list or new mcp code.

    The feature's blast radius is the new ``docuharnessx/mcp/`` package plus exactly
    four pre-existing files (Req 1.1). Any other tracked file showing up as modified
    against ``HEAD`` is a boundary breach.
    """
    if not _is_git_repo():
        pytest.skip("not a git checkout; diff-boundary check is not applicable")
    modified = _tracked_modified_paths()
    # New mcp source/test files are untracked, so they never appear in `diff HEAD`.
    # A modification is allowed only if it is one of the four named files.
    offenders = {
        path
        for path in modified
        if path not in ALLOWED_NON_MCP_CHANGES
        and not path.startswith("docuharnessx/mcp/")
        and not path.startswith("tests/")
    }
    assert offenders == set(), (
        "MCP-refine modified files outside its declared boundary: "
        f"{sorted(offenders)} (allowed: {sorted(ALLOWED_NON_MCP_CHANGES)})"
    )


def test_frozen_seams_stages_assembler_resolver_not_in_diff() -> None:
    """No frozen-seam / stage / assembler-renderer / model-resolver module changed.

    Strongest negative pin: none of the off-limits modules may appear in the
    working-tree diff against ``HEAD`` (Req 1.2). This catches an accidental edit to a
    frozen data type or a reused stage even if it were somehow whitelisted elsewhere.
    """
    if not _is_git_repo():
        pytest.skip("not a git checkout; diff-boundary check is not applicable")
    modified = _tracked_modified_paths()
    touched_off_limits = modified & FROZEN_OFF_LIMITS_MODULES
    assert touched_off_limits == set(), (
        "MCP-refine touched off-limits frozen/stage/assembler/resolver modules: "
        f"{sorted(touched_off_limits)}"
    )


def test_allowed_writer_files_are_the_only_composition_changes() -> None:
    """Inside ``composition/``, only the two writer files may have changed.

    The writer extension is confined to ``agent.py`` + ``task_prompt.py``; no other
    composition module (``blueprint``, ``wiring``, ``fallback``, ``structure_gate``,
    ``budgets``, ``model``, ``prompt``, ``prose``, ``harness_factory``) may move.
    """
    if not _is_git_repo():
        pytest.skip("not a git checkout; diff-boundary check is not applicable")
    modified = _tracked_modified_paths()
    composition_changes = {
        path for path in modified if path.startswith("docuharnessx/composition/")
    }
    assert composition_changes <= {
        "docuharnessx/composition/agent.py",
        "docuharnessx/composition/task_prompt.py",
    }, f"unexpected composition changes: {sorted(composition_changes)}"


def test_cli_is_the_only_top_level_module_changed() -> None:
    """The only top-level ``docuharnessx/*.py`` change is the ``cli.py`` subcommand."""
    if not _is_git_repo():
        pytest.skip("not a git checkout; diff-boundary check is not applicable")
    modified = _tracked_modified_paths()
    top_level = {
        path
        for path in modified
        if path.startswith("docuharnessx/")
        and "/" not in path[len("docuharnessx/") :]
        and path.endswith(".py")
    }
    assert top_level <= {"docuharnessx/cli.py"}, (
        f"unexpected top-level docuharnessx module changes: {sorted(top_level)}"
    )


def test_mcp_package_exists_as_the_new_surface() -> None:
    """The feature's new code lives in an importable ``docuharnessx.mcp`` package."""
    mod = importlib.import_module("docuharnessx.mcp")
    assert mod is not None
    # The package re-exports its public surface from one namespace (Req 1.5); the
    # detailed surface is pinned by the package-surface test — here we only confirm
    # the new code is a real package, distinct from the reused engine.
    assert getattr(mod, "__path__", None) is not None


# --------------------------------------------------------------------------- #
# (B) Structural seam pins: field names/order + schema-version constants       #
# --------------------------------------------------------------------------- #


def test_segment_seam_fields_unchanged() -> None:
    """``Segment`` still carries exactly its frontmatter fields in order (Req 1.2)."""
    from docuharnessx.ontology.schema import Segment

    fields = tuple(f.name for f in dataclasses.fields(Segment))
    assert fields == (
        "id",
        "title",
        "roles",
        "subjects",
        "intent",
        "summary",
        "related",
        "body",
        "schema_version",
    )


def test_written_segments_seam_fields_unchanged() -> None:
    """``WrittenSegments`` is the frozen writer output seam, fields unchanged."""
    from docuharnessx.composition.model import WrittenSegments

    params = dataclasses.fields(WrittenSegments)
    assert tuple(f.name for f in params) == ("segments", "flags", "total_planned")
    # The seam is frozen (deeply immutable contract the review gate consumes verbatim).
    assert WrittenSegments.__dataclass_params__.frozen is True


def test_segment_store_protocol_methods_unchanged() -> None:
    """The ``SegmentStore`` Protocol still declares exactly its four port methods."""
    from docuharnessx.ontology.store import SegmentStore

    # The runtime-checkable Protocol's member set is the frozen port contract that
    # every adapter (in-memory + filesystem) implements (Req 9.1).
    members = {
        name
        for name in getattr(SegmentStore, "__protocol_attrs__", ())
        if not name.startswith("_")
    }
    assert members == {
        "put",
        "query",
        "list_segments",
        "resolve_cross_links",
    }
    assert typing.runtime_checkable is not None  # it is a runtime_checkable Protocol
    assert getattr(SegmentStore, "_is_runtime_protocol", False) is True


def test_review_report_seam_fields_and_version_unchanged() -> None:
    """``ReviewReport`` / ``ReviewAggregate`` fields + schema version are pinned."""
    from docuharnessx.review.model import (
        REVIEW_REPORT_SCHEMA_VERSION,
        ReviewAggregate,
        ReviewReport,
    )

    assert tuple(f.name for f in dataclasses.fields(ReviewReport)) == (
        "schema_version",
        "entries",
        "accepted",
        "aggregate",
    )
    assert tuple(f.name for f in dataclasses.fields(ReviewAggregate)) == (
        "judged",
        "accepted",
        "rejected",
        "unavailable",
        "criterion_tally",
    )
    assert REVIEW_REPORT_SCHEMA_VERSION == 1
    assert ReviewReport.__dataclass_params__.frozen is True


def test_assembled_site_seam_fields_and_version_unchanged() -> None:
    """``AssembledSite`` / ``SiteIdentity`` fields + schema version are pinned."""
    from docuharnessx.assembler.model import (
        ASSEMBLED_SITE_SCHEMA_VERSION,
        AssembledSite,
        SiteIdentity,
    )

    assert tuple(f.name for f in dataclasses.fields(AssembledSite)) == (
        "schema_version",
        "site_dir",
        "docs_dir",
        "mkdocs_yml_path",
        "identity",
        "page_count",
        "role_page_count",
    )
    assert tuple(f.name for f in dataclasses.fields(SiteIdentity)) == (
        "site_name",
        "repo_name",
        "repo_url",
        "site_url",
        "base_path",
        "edit_uri",
    )
    assert ASSEMBLED_SITE_SCHEMA_VERSION == 1
    assert AssembledSite.__dataclass_params__.frozen is True


def test_model_resolver_public_api_unchanged() -> None:
    """The reused model resolver still exposes exactly ``resolve_model`` + its error."""
    mod = importlib.import_module("docuharnessx.model_resolver")
    assert tuple(mod.__all__) == ("resolve_model", "ModelResolutionError")
    assert callable(mod.resolve_model)
    assert isinstance(mod.ModelResolutionError, type)


# --------------------------------------------------------------------------- #
# (C) Byte-identical writer: guidance="" reproduces the pristine HEAD task      #
# --------------------------------------------------------------------------- #


def _load_head_task_prompt() -> types.ModuleType:
    """Execute the pristine ``HEAD`` ``task_prompt.py`` as a throwaway module.

    Sharing the live package's dependencies (budgets, the harness BaseTask), this
    rebuilds "today's" renderer — the one with NO ``guidance`` keyword — so the
    current renderer's ``guidance=""`` output can be compared against the genuine
    pre-feature bytes (not merely the current module called two ways).
    """
    blob = _git("show", "HEAD:docuharnessx/composition/task_prompt.py")
    head_mod = types.ModuleType("_head_task_prompt_6_2")
    head_mod.__dict__["__name__"] = "_head_task_prompt_6_2"
    exec(compile(blob, "<head:task_prompt.py>", "exec"), head_mod.__dict__)
    return head_mod


def _description_text(task: object) -> str:
    """Flatten a ``BaseTask.description`` (str or content blocks) to one string."""
    description = getattr(task, "description", task)
    if isinstance(description, str):
        return description
    parts: list[str] = []
    for block in description:  # type: ignore[union-attr]
        if isinstance(block, dict):
            parts.append(str(block.get("text", "")))
        else:
            parts.append(str(getattr(block, "text", "")))
    return "\n".join(parts)


def _sample_blueprint():
    """A representative blueprint mirroring the existing task_prompt test fixtures."""
    from docuharnessx.composition.model import (
        Chunk,
        CompositionBlueprint,
        EvidenceAnchor,
        SCQAOpener,
    )
    from docuharnessx.ontology import Subject

    prefixes = frozenset({"component", "tech", "artifact", "topic"})
    key_message = "Extend: the fastest path is the short sequence below."
    return CompositionBlueprint(
        segment_key="platform-dev__extend__abc123",
        roles=("platform-dev",),
        intent="extend",
        subjects=(Subject.parse("component:cli", prefixes),),
        title="Extend: the CLI",
        scqa=SCQAOpener(
            situation="You are Platform Developer working with the CLI.",
            complication="Reaching the Extend goal for the CLI is unclear.",
            question="How do you Extend the CLI on the shortest path?",
            answer=key_message,
        ),
        key_message=key_message,
        chunks=(
            Chunk(
                heading="Orientation",
                points=("Who this is for: Platform Developer.", "Goal: Extend the CLI."),
            ),
            Chunk(
                heading="Extend: the core path",
                points=("Start with the CLI.", "Follow the fast path to Extend."),
            ),
        ),
        fast_path=(
            "Locate the CLI.",
            "Run the smallest action that makes progress toward Extend.",
            "Verify you reached first success, then stop.",
        ),
        andragogy=True,
        evidence_anchors=(
            EvidenceAnchor(
                kind="entrypoint", detail="cmd/main.go", note="entrypoint: main (app)"
            ),
            EvidenceAnchor(kind="component", detail="internal/auth", note="component: auth"),
        ),
        role_labels=("Platform Developer",),
        intent_label="Extend",
    )


def test_empty_guidance_is_byte_identical_to_pristine_head_task() -> None:
    """``guidance=""`` reproduces the genuine pre-feature task bytes (Req 1.2, 1.4).

    The strongest backward-compat proof for the writer extension: rebuild today's
    renderer from the ``HEAD`` blob (no ``guidance`` keyword at all), render the same
    blueprint with it, and assert the current renderer's ``guidance=""`` output is
    byte-for-byte equal. If the default path ever drifts, this fails.
    """
    if not _is_git_repo():
        pytest.skip("not a git checkout; HEAD-blob reconstruction not applicable")

    from docuharnessx.composition.task_prompt import build_agent_task

    head = _load_head_task_prompt()
    blueprint = _sample_blueprint()

    head_text = _description_text(head.build_agent_task(blueprint, repo_path="/repo"))
    current_default = _description_text(build_agent_task(blueprint, repo_path="/repo"))
    current_empty = _description_text(
        build_agent_task(blueprint, repo_path="/repo", guidance="")
    )

    assert current_default == head_text, (
        "the writer's default (no guidance) drifted from the pristine HEAD task"
    )
    assert current_empty == head_text, (
        'guidance="" is not byte-identical to today\'s pre-feature task'
    )


def test_render_guidance_keyword_is_additive_and_defaulted() -> None:
    """The writer's only allowed widening: an additive, defaulted, keyword-only ``guidance``.

    Verified intrinsically (no git baseline — the byte-identical-to-pristine-HEAD proof above
    already pins backward-compat against the pre-feature task): ``build_agent_task`` and
    ``_render_description`` accept ``guidance`` as a keyword-only parameter defaulting to ``""``,
    so existing callers are unaffected and ``guidance=""`` reproduces today's task (Req 1.2).
    """
    import inspect

    from docuharnessx.composition.task_prompt import (
        _render_description,
        build_agent_task,
    )

    for fn in (build_agent_task, _render_description):
        sig = inspect.signature(fn)
        assert "guidance" in sig.parameters, fn.__name__
        assert sig.parameters["guidance"].default == "", fn.__name__
        assert (
            sig.parameters["guidance"].kind == inspect.Parameter.KEYWORD_ONLY
        ), fn.__name__


def test_agent_run_guidance_keyword_is_additive_and_defaulted() -> None:
    """``AgenticProseRunner.run`` accepts ``guidance`` as a defaulted, keyword-only param.

    Intrinsic backward-compat check (no git baseline): the model surface gained ``guidance``
    with a default of ``""`` and keyword-only binding, so every existing call site that omits
    it is unchanged (Req 1.2, 5.2).
    """
    import inspect

    from docuharnessx.composition.agent import AgenticProseRunner

    sig = inspect.signature(AgenticProseRunner.run)
    assert "guidance" in sig.parameters
    assert sig.parameters["guidance"].default == ""
    assert sig.parameters["guidance"].kind == inspect.Parameter.KEYWORD_ONLY
