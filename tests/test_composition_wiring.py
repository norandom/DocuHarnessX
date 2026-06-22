"""Unit tests for the deterministic segment wiring (cobesy-writer task 2.3).

These tests pin the *Segment Wiring* boundary: ``segment_id(planned) -> str`` and
``wire_segment(planned, blueprint, prose) -> Segment``. The wiring is the deterministic
bridge from a planner ``PlannedSegment`` + a COBESY ``CompositionBlueprint`` + a
``ProseResult`` into an ontology ``Segment``:

* ``segment_id`` derives a deterministic, **filesystem-safe** (no ``/``, ``\\``, ``.``/
  ``..``), unique id from the ``PlannedSegment`` (a sanitized ``segment_key`` plus a short
  stable hash) so equal plans yield equal ids — and the id is valid for
  ``FilesystemSegmentStore`` (it is the matching key the Wave 2 review gate uses).
* ``wire_segment`` maps the **non-body** fields (``id``/``roles``/``subjects``/``intent``/
  ``related``/``title``/``schema_version``) from the planned segment and blueprint, while
  ``body``/``summary`` come **only** from the prose result — the prose source never affects
  any non-body field (Req 4.3, 4.4, 4.5, 5.5).

Observable completion (tasks.md 2.3): deterministic safe ids, non-body fields mapped from
the planned segment, ``schema_version == SCHEMA_VERSION``, and identical non-body fields
across ``model``/``fallback``/``fake`` prose sources.

These tests construct the ``CompositionBlueprint`` and ``ProseResult`` directly (the
blueprint builder is a sibling module built concurrently) so the wiring boundary is pinned
in isolation.
"""

from __future__ import annotations

import re

from docuharnessx.composition.model import (
    Chunk,
    CompositionBlueprint,
    EvidenceAnchor,
    ProseResult,
    SCQAOpener,
)
from docuharnessx.composition.wiring import segment_id, wire_segment
from docuharnessx.ontology import (
    SCHEMA_VERSION,
    AxisTerm,
    FilesystemSegmentStore,
    Segment,
    Subject,
    Vocabulary,
)
from docuharnessx.planning.model import EvidenceRef, PlannedSegment

_PREFIXES = frozenset({"component", "tech", "artifact", "topic"})


def _subject(raw: str) -> Subject:
    return Subject.parse(raw, _PREFIXES)


def _vocab() -> Vocabulary:
    return Vocabulary(
        roles=(
            AxisTerm("platform-dev", "Platform Developer", "Builds on the platform."),
            AxisTerm("auditor", "Compliance Auditor", "Assesses compliance."),
        ),
        intents=(
            AxisTerm("extend", "Extend", "Add capabilities."),
            AxisTerm("review", "Review", "Judge quality."),
        ),
        subject_prefixes=("component:", "tech:", "artifact:", "topic:"),
    )


# --------------------------------------------------------------------------- #
# Fixtures: planned segments, blueprints, prose results                       #
# --------------------------------------------------------------------------- #


def _planned(
    *,
    roles: tuple[str, ...] = ("platform-dev",),
    intent: str = "extend",
    subjects: tuple[Subject, ...] | None = None,
    evidence: tuple[EvidenceRef, ...] | None = None,
    segment_key: str = "platform-dev__extend__abc123def456",
) -> PlannedSegment:
    return PlannedSegment(
        segment_key=segment_key,
        roles=roles,
        intent=intent,
        subjects=subjects if subjects is not None else (_subject("component:cli"),),
        priority=7,
        evidence=evidence
        if evidence is not None
        else (EvidenceRef(kind="entrypoint", detail="cmd/main.go"),),
    )


def _blueprint(
    planned: PlannedSegment,
    *,
    title: str = "Extend: the CLI",
) -> CompositionBlueprint:
    return CompositionBlueprint(
        segment_key=planned.segment_key,
        roles=planned.roles,
        intent=planned.intent,
        subjects=planned.subjects,
        title=title,
        scqa=SCQAOpener(
            situation="You are a Platform Developer working with the CLI.",
            complication="Reaching Extend for the CLI is unclear.",
            question="How do you Extend the CLI on the shortest path?",
            answer="Extend: follow the short sequence below.",
        ),
        key_message="Extend: follow the short sequence below.",
        chunks=(Chunk(heading="Orient", points=("Find the CLI entrypoint.",)),),
        fast_path=("Locate the CLI.", "Run the smallest action.", "Verify success."),
        andragogy=True,
        evidence_anchors=(
            EvidenceAnchor(kind="entrypoint", detail="cmd/main.go", note=""),
        ),
        role_labels=("Platform Developer",),
        intent_label="Extend",
    )


def _prose(source: str = "model") -> ProseResult:
    return ProseResult(
        body="# Extend: the CLI\n\nExtend: follow the short sequence below.\n",
        summary="Follow the short sequence to extend the CLI.",
        source=source,
    )


# --------------------------------------------------------------------------- #
# segment_id: deterministic, filesystem-safe, unique (Req 4.4)                  #
# --------------------------------------------------------------------------- #


def test_segment_id_is_a_nonempty_str() -> None:
    sid = segment_id(_planned())
    assert isinstance(sid, str)
    assert sid != ""


def test_segment_id_is_deterministic_for_equal_plans() -> None:
    # Two distinct-but-equal PlannedSegment instances yield equal ids (Req 4.4).
    assert segment_id(_planned()) == segment_id(_planned())


def test_segment_id_is_filesystem_safe() -> None:
    sid = segment_id(
        _planned(
            roles=("platform-dev", "auditor"),
            intent="review",
            segment_key="platform-dev,auditor__review__deadbeefcafe",
        )
    )
    assert "/" not in sid
    assert "\\" not in sid
    assert sid not in (".", "..")
    # No filesystem path-traversal dots at all and no commas/underscored junk:
    # only lowercase alphanumerics and hyphens survive sanitization.
    assert re.fullmatch(r"[a-z0-9-]+", sid)


def test_segment_id_accepted_by_filesystem_store(tmp_path) -> None:
    # The id must be a valid single-segment filename for FilesystemSegmentStore.
    store = FilesystemSegmentStore(tmp_path, _vocab())
    planned = _planned(
        roles=("platform-dev", "auditor"),
        segment_key="platform-dev,auditor__review__deadbeefcafe",
    )
    sid = segment_id(planned)
    seg = Segment(
        id=sid,
        title="t",
        roles=["platform-dev"],
        subjects=[_subject("component:cli")],
        intent="extend",
        summary="s",
        body="# t\n\nb",
        schema_version=SCHEMA_VERSION,
    )
    # Storing must not raise a MalformedFrontmatterError for an unsafe id.
    store.put(seg)
    assert any(s.id == sid for s in store.list_segments())


def test_segment_id_unique_for_distinct_segment_keys() -> None:
    a = segment_id(_planned(segment_key="role-a__setup__1111"))
    b = segment_id(_planned(segment_key="role-b__setup__2222"))
    assert a != b


def test_segment_id_distinguishes_keys_that_sanitize_to_same_prefix() -> None:
    # Two segment_keys whose sanitized forms could collide must still differ
    # because a stable hash of the raw key is appended.
    a = segment_id(_planned(segment_key="a,b__x__1"))
    b = segment_id(_planned(segment_key="a-b__x__1"))
    assert a != b


def test_segment_id_independent_of_blueprint_and_prose() -> None:
    # segment_id is derived from the PlannedSegment alone (the gate matching key).
    planned = _planned()
    assert segment_id(planned) == segment_id(planned)


def test_segment_id_does_not_mutate_planned() -> None:
    planned = _planned()
    before = (planned.segment_key, planned.roles, planned.intent, planned.subjects)
    segment_id(planned)
    after = (planned.segment_key, planned.roles, planned.intent, planned.subjects)
    assert before == after


# --------------------------------------------------------------------------- #
# wire_segment: maps non-body fields (Req 4.3, 4.5)                             #
# --------------------------------------------------------------------------- #


def test_wire_segment_returns_ontology_segment() -> None:
    planned = _planned()
    seg = wire_segment(planned, _blueprint(planned), _prose())
    assert isinstance(seg, Segment)


def test_wire_segment_id_matches_segment_id() -> None:
    planned = _planned()
    seg = wire_segment(planned, _blueprint(planned), _prose())
    assert seg.id == segment_id(planned)


def test_wire_segment_maps_roles_intent_subjects_from_planned() -> None:
    planned = _planned(
        roles=("platform-dev", "auditor"),
        intent="review",
        subjects=(_subject("component:cli"), _subject("tech:go")),
    )
    seg = wire_segment(planned, _blueprint(planned), _prose())
    assert seg.roles == list(planned.roles)
    assert seg.intent == planned.intent
    assert seg.subjects == list(planned.subjects)


def test_wire_segment_title_from_blueprint() -> None:
    planned = _planned()
    bp = _blueprint(planned, title="A Distinct Title")
    seg = wire_segment(planned, bp, _prose())
    assert seg.title == "A Distinct Title"


def test_wire_segment_related_defaults_empty() -> None:
    planned = _planned()
    seg = wire_segment(planned, _blueprint(planned), _prose())
    assert seg.related == []


def test_wire_segment_schema_version_is_current() -> None:
    planned = _planned()
    seg = wire_segment(planned, _blueprint(planned), _prose())
    assert seg.schema_version == SCHEMA_VERSION


def test_wire_segment_body_and_summary_from_prose_only() -> None:
    planned = _planned()
    prose = ProseResult(body="BODY-TEXT", summary="SUMMARY-TEXT", source="model")
    seg = wire_segment(planned, _blueprint(planned), prose)
    assert seg.body == "BODY-TEXT"
    assert seg.summary == "SUMMARY-TEXT"


# --------------------------------------------------------------------------- #
# Prose source never affects non-body fields (Req 5.5)                         #
# --------------------------------------------------------------------------- #


def test_non_body_fields_identical_across_prose_sources() -> None:
    planned = _planned()
    bp = _blueprint(planned)
    model_seg = wire_segment(planned, bp, _prose(source="model"))
    fallback_seg = wire_segment(planned, bp, _prose(source="fallback"))
    fake_seg = wire_segment(planned, bp, _prose(source="fake"))

    def _non_body(seg: Segment) -> tuple:
        return (
            seg.id,
            seg.title,
            tuple(seg.roles),
            tuple(seg.subjects),
            seg.intent,
            tuple(seg.related),
            seg.schema_version,
        )

    assert _non_body(model_seg) == _non_body(fallback_seg)
    assert _non_body(model_seg) == _non_body(fake_seg)


def test_different_prose_bodies_do_not_change_id_or_title() -> None:
    planned = _planned()
    bp = _blueprint(planned)
    a = wire_segment(planned, bp, ProseResult(body="x", summary="y", source="model"))
    b = wire_segment(
        planned, bp, ProseResult(body="completely different", summary="z", source="fake")
    )
    assert a.id == b.id
    assert a.title == b.title


# --------------------------------------------------------------------------- #
# Read-only inputs + determinism (Req 2.6, 4.5)                                 #
# --------------------------------------------------------------------------- #


def test_wire_segment_does_not_mutate_planned_or_blueprint() -> None:
    planned = _planned(subjects=(_subject("component:cli"),))
    bp = _blueprint(planned)
    before_planned = (planned.roles, planned.intent, planned.subjects, planned.evidence)
    before_bp_subjects = bp.subjects
    wire_segment(planned, bp, _prose())
    assert (
        planned.roles,
        planned.intent,
        planned.subjects,
        planned.evidence,
    ) == before_planned
    assert bp.subjects == before_bp_subjects


def test_wire_segment_subjects_is_a_fresh_list_not_aliasing_planned() -> None:
    # Segment.subjects is a mutable list; mutating it must not touch the frozen
    # planned tuple (the inputs are treated read-only).
    planned = _planned(subjects=(_subject("component:cli"),))
    seg = wire_segment(planned, _blueprint(planned), _prose())
    seg.subjects.append(_subject("tech:go"))
    assert planned.subjects == (_subject("component:cli"),)


def test_wire_segment_roles_is_a_fresh_list_not_aliasing_planned() -> None:
    planned = _planned(roles=("platform-dev",))
    seg = wire_segment(planned, _blueprint(planned), _prose())
    seg.roles.append("auditor")
    assert planned.roles == ("platform-dev",)


def test_equal_inputs_produce_equal_non_body_fields() -> None:
    p1 = _planned()
    p2 = _planned()
    s1 = wire_segment(p1, _blueprint(p1), _prose())
    s2 = wire_segment(p2, _blueprint(p2), _prose())
    assert s1.id == s2.id
    assert s1.title == s2.title
    assert s1.roles == s2.roles
    assert s1.subjects == s2.subjects
    assert s1.intent == s2.intent
    assert s1.related == s2.related
    assert s1.schema_version == s2.schema_version
