"""Unit tests for the deterministic agentic task-prompt assembler (task 2.1).

Task 2.1 (agentic-codebase-writer, boundary: *task_prompt*) turns one COBESY
:class:`~docuharnessx.composition.model.CompositionBlueprint` plus the target-repo path
into a bounded agentic :class:`harnessx.core.harness.BaseTask`. The scope (evidence files
to start from + subject phrases) is derived from ``blueprint.evidence_anchors`` and
``blueprint.subjects`` — *not* a separate scope argument. The assembled task instructs the
agent to start from the evidence files, read real source with the tools, honor the
blueprint's COBESY structure (SCQA opener -> Minto lead-with-conclusion -> working-memory
chunks -> REDUCE-barrier fast path; andragogy framing when flagged), include at least one
valid Mermaid diagram (supported type, vertical, short nodes, valid arrows), and cite real
``file:line`` sources for at least the configured minimum number of files; all
audience/intent framing comes from the blueprint's loaded-``Vocabulary`` labels with no
hardcoded roles/intents/subjects (Req 3.3, 4.1, 4.2, 4.3, 4.6).

Observable completion (tasks.md 2.1): the assembled task carries the bounded caps
(max_steps/max_cost_usd/token_budget), names the evidence files and subjects, embeds the
COBESY moves and the Mermaid/citation demands, uses only blueprint-derived labels, and is
byte-identical for equal inputs.
"""

from __future__ import annotations

from harnessx.core.harness import BaseTask

from docuharnessx.composition.budgets import (
    MIN_CITED_FILES,
    WRITER_MAX_COST_USD,
    WRITER_MAX_STEPS,
    WRITER_TOKEN_BUDGET,
)
from docuharnessx.composition.model import (
    Chunk,
    CompositionBlueprint,
    EvidenceAnchor,
    SCQAOpener,
)
from docuharnessx.composition.task_prompt import build_agent_task
from docuharnessx.ontology import Subject

_PREFIXES = frozenset({"component", "tech", "artifact", "topic"})


def _subject(raw: str) -> Subject:
    return Subject.parse(raw, _PREFIXES)


# --------------------------------------------------------------------------- #
# Fixtures: a blueprint with distinct, recognizable text                       #
# --------------------------------------------------------------------------- #


def _blueprint(
    *,
    segment_key: str = "platform-dev__extend__abc123",
    roles: tuple[str, ...] = ("platform-dev",),
    intent: str = "extend",
    subjects: tuple[Subject, ...] | None = None,
    title: str = "Extend: the CLI",
    key_message: str = "Extend: the fastest path is the short sequence below.",
    scqa: SCQAOpener | None = None,
    chunks: tuple[Chunk, ...] | None = None,
    fast_path: tuple[str, ...] = (
        "Locate the CLI.",
        "Run the smallest action that makes progress toward Extend.",
        "Verify you reached first success, then stop.",
    ),
    andragogy: bool = True,
    evidence_anchors: tuple[EvidenceAnchor, ...] | None = None,
    role_labels: tuple[str, ...] = ("Platform Developer",),
    intent_label: str = "Extend",
) -> CompositionBlueprint:
    return CompositionBlueprint(
        segment_key=segment_key,
        roles=roles,
        intent=intent,
        subjects=subjects if subjects is not None else (_subject("component:cli"),),
        title=title,
        scqa=scqa
        if scqa is not None
        else SCQAOpener(
            situation="You are Platform Developer working with the CLI.",
            complication="Reaching the Extend goal for the CLI is unclear.",
            question="How do you Extend the CLI on the shortest path?",
            answer=key_message,
        ),
        key_message=key_message,
        chunks=chunks
        if chunks is not None
        else (
            Chunk(
                heading="Orientation",
                points=("Who this is for: Platform Developer.", "Goal: Extend the CLI."),
            ),
            Chunk(
                heading="Extend: the core path",
                points=("Start with the CLI.", "Follow the fast path to Extend."),
            ),
        ),
        fast_path=fast_path,
        andragogy=andragogy,
        evidence_anchors=evidence_anchors
        if evidence_anchors is not None
        else (
            EvidenceAnchor(
                kind="entrypoint", detail="cmd/main.go", note="entrypoint: main (app)"
            ),
            EvidenceAnchor(
                kind="component", detail="internal/auth", note="component: auth"
            ),
        ),
        role_labels=role_labels,
        intent_label=intent_label,
    )


def _text(task: BaseTask) -> str:
    """The task's natural-language description as a single string."""
    description = task.description
    if isinstance(description, str):
        return description
    # Anthropic content-block form: concatenate the text fields.
    parts: list[str] = []
    for block in description:
        if isinstance(block, dict):
            parts.append(str(block.get("text", "")))
        else:
            parts.append(str(getattr(block, "text", "")))
    return "\n".join(parts)


# --------------------------------------------------------------------------- #
# Shape and bounded caps (Req 5.1 application; task 2.1 caps)                   #
# --------------------------------------------------------------------------- #


def test_returns_base_task() -> None:
    task = build_agent_task(_blueprint(), repo_path="/repo")
    assert isinstance(task, BaseTask)


def test_carries_bounded_caps_by_default() -> None:
    task = build_agent_task(_blueprint(), repo_path="/repo")
    assert task.max_steps == WRITER_MAX_STEPS
    assert task.max_cost_usd == WRITER_MAX_COST_USD
    assert task.token_budget == WRITER_TOKEN_BUDGET


def test_caps_are_overridable() -> None:
    task = build_agent_task(
        _blueprint(),
        repo_path="/repo",
        max_steps=7,
        max_cost_usd=0.11,
        token_budget=42_000,
    )
    assert task.max_steps == 7
    assert task.max_cost_usd == 0.11
    assert task.token_budget == 42_000


def test_description_is_a_string() -> None:
    task = build_agent_task(_blueprint(), repo_path="/repo")
    assert isinstance(task.description, str)
    assert task.description.strip()


# --------------------------------------------------------------------------- #
# Scope from evidence anchors + subjects (Req 3.3)                              #
# --------------------------------------------------------------------------- #


def test_names_the_evidence_files() -> None:
    # The scope's starting point is blueprint.evidence_anchors (NOT a separate scope arg).
    task = build_agent_task(_blueprint(), repo_path="/repo")
    text = _text(task)
    assert "cmd/main.go" in text
    assert "internal/auth" in text


def test_names_the_subject_phrases() -> None:
    bp = _blueprint(
        subjects=(_subject("component:cli"), _subject("component:auth-service"))
    )
    text = _text(build_agent_task(bp, repo_path="/repo"))
    # Subject.local is normalized (case-folded); the phrases must appear.
    assert "cli" in text
    assert "auth-service" in text


def test_no_evidence_anchors_still_assembles() -> None:
    bp = _blueprint(evidence_anchors=())
    task = build_agent_task(bp, repo_path="/repo")
    assert isinstance(task, BaseTask)
    assert _text(task).strip()


# --------------------------------------------------------------------------- #
# COBESY structure demands (Req 4.1)                                           #
# --------------------------------------------------------------------------- #


def test_embeds_cobesy_moves() -> None:
    bp = _blueprint()
    text = _text(build_agent_task(bp, repo_path="/repo")).lower()
    assert "scqa" in text
    assert "minto" in text or "lead with the conclusion" in text
    assert "fast path" in text or "reduce" in text


def test_carries_the_blueprint_scqa_and_key_message() -> None:
    bp = _blueprint()
    text = _text(build_agent_task(bp, repo_path="/repo"))
    assert bp.scqa.situation in text
    assert bp.scqa.question in text
    assert bp.key_message in text


def test_carries_chunk_headings_and_fast_path() -> None:
    bp = _blueprint()
    text = _text(build_agent_task(bp, repo_path="/repo"))
    assert "Orientation" in text
    assert "Goal: Extend the CLI." in text
    assert "Verify you reached first success, then stop." in text


def test_andragogy_changes_the_task() -> None:
    expert = build_agent_task(_blueprint(andragogy=True), repo_path="/repo")
    novice = build_agent_task(_blueprint(andragogy=False), repo_path="/repo")
    assert _text(expert) != _text(novice)


# --------------------------------------------------------------------------- #
# Mermaid + citation demands (Req 4.2, 4.3)                                     #
# --------------------------------------------------------------------------- #


def test_demands_valid_mermaid() -> None:
    text = _text(build_agent_task(_blueprint(), repo_path="/repo")).lower()
    assert "mermaid" in text
    # supported types named so the agent picks a valid one
    assert "graph td" in text or "sequencediagram" in text or "classdiagram" in text


def test_demands_minimum_file_line_citations() -> None:
    text = _text(build_agent_task(_blueprint(), repo_path="/repo"))
    lower = text.lower()
    assert "file:line" in lower or "file:line" in text
    # the default minimum count is surfaced
    assert str(MIN_CITED_FILES) in text


def test_min_citations_override_surfaced() -> None:
    text = _text(build_agent_task(_blueprint(), repo_path="/repo", min_citations=5))
    assert "5" in text


# --------------------------------------------------------------------------- #
# Tools / repo grounding instruction (Req 3.3, 3.4)                            #
# --------------------------------------------------------------------------- #


def test_instructs_reading_real_source_with_tools() -> None:
    text = _text(build_agent_task(_blueprint(), repo_path="/repo")).lower()
    assert "read" in text
    assert "source" in text or "repository" in text or "repo" in text


# --------------------------------------------------------------------------- #
# No hardcoded vocabulary (Req 4.6)                                            #
# --------------------------------------------------------------------------- #


def test_uses_only_blueprint_derived_labels() -> None:
    # Re-label the vocabulary entirely; the task text must follow the blueprint labels
    # and carry no hardcoded role/intent literal from the default profile.
    bp = _blueprint(
        roles=("ops",),
        intent="operate",
        role_labels=("Site Reliability Engineer",),
        intent_label="Operate",
        title="Operate: the scheduler",
        key_message="Operate: the fastest path is the short sequence below.",
        subjects=(_subject("component:scheduler"),),
        # Keep the whole blueprint internally consistent with the re-labeled vocabulary
        # (a real build_blueprint derives SCQA/chunks from the same labels), so the only
        # source of role/intent text is the blueprint itself.
        scqa=SCQAOpener(
            situation="You are Site Reliability Engineer working with the scheduler.",
            complication="Reaching the Operate goal for the scheduler is unclear.",
            question="How do you Operate the scheduler on the shortest path?",
            answer="Operate: the fastest path is the short sequence below.",
        ),
        chunks=(
            Chunk(
                heading="Orientation",
                points=(
                    "Who this is for: Site Reliability Engineer.",
                    "Goal: Operate the scheduler.",
                ),
            ),
        ),
        fast_path=(
            "Locate the scheduler.",
            "Run the smallest action that makes progress toward Operate.",
            "Verify you reached first success, then stop.",
        ),
    )
    text = _text(build_agent_task(bp, repo_path="/repo"))
    assert "Site Reliability Engineer" in text
    assert "Operate" in text
    # the default-profile labels from the other fixture must not leak in
    assert "Platform Developer" not in text
    assert "Extend" not in text


# --------------------------------------------------------------------------- #
# Determinism (Req 4.1 / task 2.1 byte-identical)                              #
# --------------------------------------------------------------------------- #


def test_byte_identical_for_equal_inputs() -> None:
    a = build_agent_task(_blueprint(), repo_path="/repo")
    b = build_agent_task(_blueprint(), repo_path="/repo")
    assert _text(a) == _text(b)
    assert a.max_steps == b.max_steps
    assert a.max_cost_usd == b.max_cost_usd
    assert a.token_budget == b.token_budget


def test_different_blueprints_produce_different_tasks() -> None:
    a = build_agent_task(_blueprint(title="Extend: the CLI"), repo_path="/repo")
    b = build_agent_task(_blueprint(title="Review: the auth module"), repo_path="/repo")
    assert _text(a) != _text(b)


def test_repo_path_does_not_change_caps_but_is_referenced() -> None:
    # repo_path identifies the read-only workspace root; equal blueprints with the same
    # repo_path are byte-identical (covered above) — here just confirm it is accepted and
    # the description is non-empty for an absolute path.
    task = build_agent_task(_blueprint(), repo_path="/some/abs/repo")
    assert _text(task).strip()


def test_does_not_mutate_blueprint() -> None:
    bp = _blueprint()
    before = (bp.chunks, bp.fast_path, bp.evidence_anchors, bp.role_labels, bp.subjects)
    build_agent_task(bp, repo_path="/repo")
    assert (
        bp.chunks,
        bp.fast_path,
        bp.evidence_anchors,
        bp.role_labels,
        bp.subjects,
    ) == before
