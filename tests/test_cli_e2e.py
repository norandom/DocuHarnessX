"""End-to-end acceptance tests for the dhx CLI (task 5.1 boundary: dhx CLI,
make_docgen, StageRegistry, OntologySetup).

This is the spec's top-level acceptance gate (Req 4.8, 8.1, 8.2, 9.1, 9.5). It
exercises the whole skeleton through its public ``dhx`` entry point
(:func:`docuharnessx.cli.main`) end to end, against the same boundaries a real
user touches — the CLI, the ``make_docgen`` bundle, the ``StageRegistry``, and
``OntologySetup`` — proving the empty pipeline runs clean and produces an
observable journal trace.

Two acceptance cases:

1. **Clean run on the real pipeline.** ``dhx run <target-repo> --out DIR`` against
   a directory target runs the composed pipeline start to finish: a HarnessJournal
   JSONL trace is written under ``DIR`` recording run start *and* end, all eight
   pipeline stages actually FIRE in canonical order (asserted on the run's own
   ``_trace.jsonl`` — each stage records a ``processor_trigger`` participation
   marker as it executes, without modifying generated content), the Write stage
   publishes a written set to ``SLOT_WRITTEN_SEGMENTS`` and the Review stage
   publishes a well-formed report to ``SLOT_REVIEW_REPORT``, and the process exits
   ``0`` (Req 4.8, 8.1, 8.2). The CLI provisions a ``FilesystemSegmentStore`` rooted
   at ``<DIR>/segments`` before the run, so write/review/assemble see it.
2. **``dhx init`` produces a loadable ontology.** ``dhx init --default`` in a fresh
   temp project writes a ``.docuharnessx/ontology.yaml`` that the ``ontology-engine``
   ``load_vocabulary`` loader accepts without error (Req 9.1, 9.5).

Reference invocation form
-------------------------
The spec's reference acceptance form is::

    dhx /home/mc/Source/malware_hashes --out /tmp/out

The implemented CLI routes the run through the ``run`` subcommand, so the
equivalent driven here is ``dhx run <target> --out <dir>``. The first test mirrors
that form against a hermetic temp directory; :func:`test_e2e_reference_form_against_real_repo`
mirrors it against the real reference repo when present (read-only), and skips when
it is unavailable (e.g. CI) so the suite stays hermetic.

Credential-free
---------------
Every run injects the test-scoped :class:`tests._fakes.FakeProvider`, so the empty
pipeline reaches ``exit_reason='done'`` in one model turn with **no** network call
and **no** real credentials. The production model resolver is never exercised here.
"""

from __future__ import annotations

import json
import os
import sys

from harnessx.core.model_config import ModelConfig

from docuharnessx import cli
from docuharnessx._ontology import (
    SegmentStore,
    Vocabulary,
    default_profile,
    load_vocabulary,
)
from docuharnessx.bundle import make_docgen
from docuharnessx.composition import WrittenSegments
from docuharnessx.review.model import REVIEW_REPORT_SCHEMA_VERSION, ReviewReport

from _fakes import FakeProvider


# Canonical stage names, in pipeline order ingest → analyze → classify → plan →
# write → review → assemble → deploy. Each stage records this name in its
# ``processor_trigger`` journal marker (``detail.stage``) when it fires at run time.
CANONICAL_STAGE_ORDER: tuple[str, ...] = (
    "ingest",
    "analyze",
    "classify",
    "plan",
    "write",
    "review",
    "assemble",
    "deploy",
)

_ONTOLOGY_RELPATH = os.path.join(".docuharnessx", "ontology.yaml")


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #


def _fake_model() -> ModelConfig:
    """A ``ModelConfig`` bound to the no-network fake provider (credential-free)."""
    return ModelConfig(main=FakeProvider())


def _find_journal_jsonl(out_dir: str) -> list[str]:
    """Every conversation ``.jsonl`` trace HarnessJournal wrote under *out_dir*.

    The ``_trace.jsonl`` sibling (the structured event trace) is excluded; this
    returns the conversation-record JSONL files (``session_start`` … ``episode_end``).
    """
    found: list[str] = []
    for root, _dirs, files in os.walk(out_dir):
        for name in files:
            if name.endswith(".jsonl") and not name.endswith("_trace.jsonl"):
                found.append(os.path.join(root, name))
    return found


def _find_trace_jsonl(out_dir: str) -> list[str]:
    """Every structured-event ``_trace.jsonl`` HarnessJournal wrote under *out_dir*."""
    found: list[str] = []
    for root, _dirs, files in os.walk(out_dir):
        for name in files:
            if name.endswith("_trace.jsonl"):
                found.append(os.path.join(root, name))
    return found


def _stages_that_fired(out_dir: str) -> list[str]:
    """The stage names that actually FIRED during the run, in firing order.

    Reads the run's ``_trace.jsonl`` and extracts the ``processor_trigger`` records
    each no-op stage emits on execution (``action='stage_participated'``), returning
    their ``detail.stage`` values in recorded order. This reflects the *runtime*
    pipeline — which stages were instantiated and driven — not a static config shape.
    """
    fired: list[str] = []
    for trace in _find_trace_jsonl(out_dir):
        for record in _read_jsonl(trace):
            if (
                record.get("event_type") == "processor_trigger"
                and record.get("action") == "stage_participated"
            ):
                stage = record.get("detail", {}).get("stage")
                if stage is not None:
                    fired.append(stage)
    return fired


def _read_jsonl(path: str) -> list[dict]:
    """Parse a JSONL file into a list of record dicts (blank lines skipped)."""
    with open(path, "r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


# --------------------------------------------------------------------------- #
# Acceptance case 1: clean end-to-end run on the empty pipeline                #
# (Req 4.8, 8.1, 8.2) — mirrors `dhx run <target> --out DIR`                   #
# --------------------------------------------------------------------------- #


def test_e2e_run_empty_pipeline_exits_zero_with_journal(tmp_path, capsys) -> None:
    """`dhx run <target> --out DIR` runs start→finish, journals, and exits 0."""
    target = tmp_path / "repo"
    target.mkdir()
    # A couple of files so the target is a realistic directory (still no real work
    # happens — the stages are no-ops — but the target is a genuine repo dir).
    (target / "README.md").write_text("# sample repo\n", encoding="utf-8")
    (target / "main.py").write_text("print('hello')\n", encoding="utf-8")
    out = tmp_path / "out"

    code = cli.main(
        ["run", str(target), "--out", str(out)],
        model_config=_fake_model(),
    )

    # The whole pipeline ran start to finish and the process exited cleanly.
    assert code == 0

    # A HarnessJournal JSONL trace was written under the resolved output directory.
    journals = _find_journal_jsonl(str(out))
    assert journals, "a HarnessJournal JSONL trace must be written under --out DIR"
    for journal in journals:
        assert os.path.abspath(journal).startswith(os.path.abspath(str(out)))

    # The journal path (or its session directory) is reported on success.
    stdout = capsys.readouterr().out
    assert any(
        journal in stdout or os.path.dirname(journal) in stdout for journal in journals
    ), stdout


def test_e2e_bare_form_via_production_argv_none_path(tmp_path, monkeypatch, capsys) -> None:
    """The bare form works at the PRODUCTION entry point (argv=None -> sys.argv).

    Regression for the remediation-1 blocker: the implicit-``run`` normalization
    only ran for the explicit list form ``main([...])``; the console script and
    ``python -m`` call ``main()`` with ``argv=None``, which read ``sys.argv``
    without the ``run`` prepend and crashed with "invalid choice". This drives the
    real ``argv=None`` path (sys.argv patched to the bare form, no ``run`` token)
    and asserts the pipeline runs and exits 0 (Req 4.1, 4.8).
    """
    target = tmp_path / "repo"
    target.mkdir()
    (target / "README.md").write_text("# sample repo\n", encoding="utf-8")
    out = tmp_path / "out"

    # Production invocation shape: argv defaults to None, so main() must resolve
    # sys.argv[1:] itself. No explicit "run" subcommand — the bare form.
    monkeypatch.setattr(sys, "argv", ["dhx", str(target), "--out", str(out)])
    code = cli.main(model_config=_fake_model())

    assert code == 0, "bare form at the argv=None production path must run and exit 0"
    journals = _find_journal_jsonl(str(out))
    assert journals, "the bare-form production run must write a HarnessJournal trace"
    # And the run is real: all eight stages fire in canonical order. The CLI provisions
    # the segment store before the run, so ``write`` and ``review`` fire too.
    assert _stages_that_fired(str(out)) == list(CANONICAL_STAGE_ORDER)


def test_e2e_journal_records_run_start_and_end(tmp_path) -> None:
    """The journal records both run start and run end (Req 8.1, 8.2)."""
    target = tmp_path / "repo"
    target.mkdir()
    out = tmp_path / "out"

    code = cli.main(
        ["run", str(target), "--out", str(out)],
        model_config=_fake_model(),
    )
    assert code == 0

    journals = _find_journal_jsonl(str(out))
    assert journals
    records = _read_jsonl(journals[0])
    types = [r.get("type") for r in records]

    # Run start and run end are both recorded in the journal (Req 8.1).
    assert "session_start" in types, types
    assert "episode_end" in types, types
    # The single user turn and the model's end-turn response are recorded too,
    # demonstrating the run actually drove a turn (not an empty/aborted run).
    assert "raw_user" in types, types
    assert "raw_assistant" in types, types
    # The run reached the clean terminal state in the recorded end event.
    end = next(r for r in records if r.get("type") == "episode_end")
    assert end.get("exit_reason") == "done", end


def test_e2e_journal_records_all_eight_stages_in_canonical_order(tmp_path) -> None:
    """All eight stages actually FIRE in canonical order during the run (Req 8.2, 5.4).

    This asserts the *runtime* behaviour, not a static-config shape. Each no-op stage
    is a real, importable, module-level processor that the harness instantiates and
    drives on the ``step_end`` hook; on execution it records its participation by
    emitting a ``processor_trigger`` event (``action='stage_participated'``) to the
    run journal — without modifying any generated content. We read the journal's
    ``_trace.jsonl`` the run wrote and assert all eight stages appear in canonical
    order. The CLI provisions a ``FilesystemSegmentStore`` before the run, so the
    now-real Write and Review stages fire alongside the rest of the chain.

    Regression guard: the prior implementation defined the stage classes locally to
    a factory, so each serialized to the unimportable ``stages.base.<X>Stage`` path
    and was silently dropped at run time (zero ``process()`` calls). A static-config
    assertion masked that; this run-driven assertion catches it.
    """
    target = tmp_path / "repo"
    target.mkdir()
    # A couple of real files so the upstream chain (ingest -> analyze -> classify ->
    # plan) activates cells and the Write stage has planned segments to write.
    (target / "README.md").write_text("# sample repo\n", encoding="utf-8")
    (target / "main.py").write_text("print('hello')\n", encoding="utf-8")
    out = tmp_path / "out"

    code = cli.main(
        ["run", str(target), "--out", str(out)],
        model_config=_fake_model(),
    )
    assert code == 0
    # The run produced a journal (it actually executed the composed pipeline).
    assert _find_journal_jsonl(str(out))

    # Read the actual run's trace and collect the per-stage participation markers
    # the stages emitted as they FIRED, in the order they fired. With the CLI-provisioned
    # segment store, all eight canonical stages fire.
    fired = _stages_that_fired(str(out))
    assert fired == list(CANONICAL_STAGE_ORDER), fired


def test_e2e_run_populates_written_segments_and_review_report(tmp_path) -> None:
    """A real run publishes SLOT_WRITTEN_SEGMENTS and a well-formed SLOT_REVIEW_REPORT.

    With the CLI-provisioned ``FilesystemSegmentStore`` the now-real Write stage fires
    and publishes a :class:`~docuharnessx.composition.WrittenSegments` to
    ``SLOT_WRITTEN_SEGMENTS`` (write ran and produced segments), and the now-real Review
    stage fires and publishes a :class:`~docuharnessx.review.model.ReviewReport` to
    ``SLOT_REVIEW_REPORT`` (review ran and produced a report). Plain ``FakeProvider``
    content is not valid judge JSON, so the review gate correctly fail-closed-rejects
    every segment (default-reject on an unparseable verdict, Req fail-closed) — so we
    assert the report EXISTS and is well-formed (not that any segment was accepted).
    Drives the prepared-run -> orchestrate-run path so we can read the run context's
    slots directly. Credential-free (the no-network fake provider).
    """
    target = tmp_path / "repo"
    target.mkdir()
    (target / "README.md").write_text("# sample repo\n", encoding="utf-8")
    (target / "main.py").write_text("print('hello')\n", encoding="utf-8")
    out = tmp_path / "out"

    parser = cli.build_parser()
    args = parser.parse_args(["run", str(target), "--out", str(out)])
    prepared = cli.prepare_run(args, model_config=_fake_model())
    outcome = cli.orchestrate_run(prepared)

    assert outcome.exit_code == 0
    run_context = outcome.run_context

    # Write ran and produced segments: SLOT_WRITTEN_SEGMENTS is populated with a
    # well-formed WrittenSegments carrying at least one written segment.
    written = run_context.written_segments()
    assert isinstance(written, WrittenSegments), written
    assert len(written.segments) >= 1, written
    # Each written segment is also persisted as an inspectable <id>.md artifact under
    # the CLI-provisioned <out>/segments store directory.
    segments_dir = out / "segments"
    assert segments_dir.is_dir()
    for segment in written.segments:
        assert (segments_dir / f"{segment.id}.md").is_file()

    # Review ran and produced a well-formed report: SLOT_REVIEW_REPORT is populated.
    report = run_context.review_report()
    assert isinstance(report, ReviewReport), report
    assert report.schema_version == REVIEW_REPORT_SCHEMA_VERSION
    # One entry per written segment; the aggregate counts agree with the entries.
    assert len(report.entries) == len(written.segments)
    assert report.aggregate.judged == len(written.segments)
    assert report.aggregate.accepted + report.aggregate.rejected == report.aggregate.judged
    # FakeProvider content is not valid judge JSON, so the gate fail-closed-rejects
    # every segment: the report is well-formed and the accepted set is empty (the
    # correct fail-closed outcome, NOT a sign the report is missing).
    assert report.accepted == ()
    assert report.aggregate.accepted == 0


def test_orchestrate_run_provisions_a_segment_store(tmp_path) -> None:
    """``orchestrate_run`` provisions a non-None SegmentStore on the run context.

    Focused regression for the CLI orchestration fix: before the run, the CLI must
    place a concrete ``SegmentStore`` handle in the run context (rooted under the
    output dir) so the Write/Review/Assemble stages can read it. Asserts the handle is
    present, conforms to the frozen ``SegmentStore`` port, and is the filesystem store
    rooted at ``<out>/segments`` (the intended inspectable artifact location).
    """
    target = tmp_path / "repo"
    target.mkdir()
    out = tmp_path / "out"

    parser = cli.build_parser()
    args = parser.parse_args(["run", str(target), "--out", str(out)])
    prepared = cli.prepare_run(args, model_config=_fake_model())
    outcome = cli.orchestrate_run(prepared)

    store = outcome.run_context.segment_store()
    assert store is not None, "orchestrate_run must provision a segment store"
    assert isinstance(store, SegmentStore), type(store)
    # The frozen store port surface is present on the provisioned handle.
    for method in ("put", "query", "list_segments", "resolve_cross_links"):
        assert callable(getattr(store, method, None)), method
    # The store is rooted at <out>/segments — the inspectable per-segment artifact dir.
    assert (out / "segments").is_dir()


def test_e2e_each_stage_processor_is_a_real_importable_target(tmp_path) -> None:
    """Each stage serializes to its own importable module-level ``_target_`` (BLOCKING 1).

    The defect that dropped every stage at run time was that the stage classes were
    defined *local* to a factory and serialized to ``docuharnessx.stages.base.<X>Stage``
    — a path with no such module-level attribute, so HarnessX's ``getattr`` import
    failed and the processor was silently discarded. This pins that every stage's
    serialized ``_target_`` is a real, importable class at its own per-stage module.
    """
    import importlib

    config = make_docgen(journal_dir=str(tmp_path / "probe"))
    stage_targets = [
        p["_target_"]
        for p in config.processors
        if isinstance(p, dict)
        and p.get("_target_", "").startswith("docuharnessx.stages.")
        and p["_target_"].rsplit(".", 1)[-1].endswith("Stage")
    ]
    assert len(stage_targets) == 8, stage_targets
    for target in stage_targets:
        module_path, _, class_name = target.rpartition(".")
        # NOT the old, unimportable stages.base.* path that silently dropped stages.
        assert module_path != "docuharnessx.stages.base", target
        module = importlib.import_module(module_path)
        cls = getattr(module, class_name)  # would raise if it were not real
        assert isinstance(cls, type)


def test_e2e_reference_form_against_real_repo(tmp_path, capsys) -> None:
    """Mirror the spec's reference form `dhx <real-repo> --out DIR` when available.

    The spec names ``dhx /home/mc/Source/malware_hashes --out /tmp/out`` as the
    reference acceptance invocation. When that real repo is present we drive the
    equivalent ``dhx run <repo> --out DIR`` against it **read-only** (the output dir
    is a hermetic temp dir, never inside the reference repo). When it is absent
    (e.g. CI) the test is skipped so the suite stays hermetic.
    """
    reference_repo = "/home/mc/Source/malware_hashes"
    if not os.path.isdir(reference_repo):  # pragma: no cover - environment-dependent
        import pytest

        pytest.skip(f"reference repo not available: {reference_repo}")

    out = tmp_path / "out"  # hermetic out dir — nothing is written into the repo.

    code = cli.main(
        ["run", reference_repo, "--out", str(out)],
        model_config=_fake_model(),
    )

    assert code == 0
    journals = _find_journal_jsonl(str(out))
    assert journals, "the reference run must journal under the temp output dir"
    # Nothing was written back into the read-only reference repo by this run.
    assert not os.path.exists(os.path.join(reference_repo, ".docuharnessx", "out"))


# --------------------------------------------------------------------------- #
# Acceptance case 2: `dhx init` writes a loadable ontology.yaml                 #
# (Req 9.1, 9.5)                                                               #
# --------------------------------------------------------------------------- #


def test_e2e_init_writes_loadable_ontology(tmp_path, capsys) -> None:
    """`dhx init --default` writes a `.docuharnessx/ontology.yaml` the engine loads."""
    project = tmp_path / "fresh-project"
    project.mkdir()

    code = cli.main(["init", str(project), "--default"])

    assert code == 0
    written = os.path.join(str(project), _ONTOLOGY_RELPATH)
    assert os.path.isfile(written), "dhx init must write .docuharnessx/ontology.yaml"

    # The written path is reported on success.
    assert written in capsys.readouterr().out

    # Acceptance: the ontology-engine load_vocabulary loader accepts it (Req 9.5).
    vocab = load_vocabulary(written)
    assert isinstance(vocab, Vocabulary)
    # --default seeds the engine default profile, so it round-trips to that profile.
    assert vocab == default_profile()


def test_e2e_init_then_run_uses_the_written_ontology(tmp_path, capsys) -> None:
    """A project initialized by `dhx init` then runs without the default-profile hint.

    Ties the two acceptance cases together: after ``dhx init`` writes the ontology
    into the target repo, a subsequent ``dhx run`` against that repo loads the
    *written* vocabulary (not the default-profile fallback), so the absent-file
    ``dhx init`` hint is NOT printed and the run still exits 0 with a journal.
    """
    target = tmp_path / "repo"
    target.mkdir()
    out = tmp_path / "out"

    init_code = cli.main(["init", str(target), "--default"])
    assert init_code == 0
    capsys.readouterr()  # drain the init success output

    run_code = cli.main(
        ["run", str(target), "--out", str(out)],
        model_config=_fake_model(),
    )

    assert run_code == 0
    assert _find_journal_jsonl(str(out)), "the run must journal under --out DIR"
    # The ontology file is present, so the absent-file default-profile hint must NOT
    # be printed (the run consumed the written vocabulary, not the fallback).
    stdout = capsys.readouterr().out
    assert "using the default ontology profile" not in stdout, stdout
