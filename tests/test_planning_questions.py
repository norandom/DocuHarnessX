"""Unit tests for signal-derived software-question planning (task 2.1).

Pins ``plan_questions`` (design "Planning — QuestionPlanner"): entrypoints →
one startup question; named components → component questions up to the
component cap; public surface → one extend/use question; build or CI → one
build/verify question; tests present → one test-layout question. Caps are
``MAX_QUESTIONS`` / ``MAX_COMPONENT_QUESTIONS``. Empty or signal-free
analysis yields an empty plan. Default reader-role lists do not activate
questions. Equal analyses yield equal plans (Req 11.3).

Observable completion (tasks.md 2.1 / Req 2.1, 2.3, 2.4, 3.1–3.6, 4.1–4.3,
11.3): the shipped sample’s analysis produces stable ids in a stable order
with the expected kinds; caps drop extra component questions; empty-in is
empty-out; no planned id is a role-intent pair; two runs match.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

from docuharnessx.analysis import analyze, scan
from docuharnessx.analysis.model import (
    Artifact,
    BuildFile,
    CIWorkflow,
    Component,
    Dependency,
    DocPresence,
    Entrypoint,
    LanguageStat,
    PublicSymbol,
    RepoAnalysis,
    ScanStats,
)
from docuharnessx.analysis.model import TestLayout as _TestLayout
from docuharnessx.planning.question_model import (
    MAX_COMPONENT_QUESTIONS,
    MAX_QUESTIONS,
    Question,
    QuestionKind,
    make_question_id,
)
from docuharnessx.planning.questions import plan_questions

_FIXTURE_REPO = Path(__file__).parent / "fixtures" / "agentic_repo"

_ROLE_INTENT_ID = "developer__extend__abc"


# --------------------------------------------------------------------------- #
# Analysis builders                                                            #
# --------------------------------------------------------------------------- #


def _scan_stats() -> ScanStats:
    return ScanStats(
        files_scanned=0,
        files_skipped=0,
        bytes_scanned=0,
        limit_reached=False,
        notes=(),
    )


def _analysis(**overrides: object) -> RepoAnalysis:
    """A signal-free analysis with every detection category empty."""
    fields: dict[str, object] = {
        "schema_version": 1,
        "repo_path": "/repo",
        "languages": (),
        "primary_languages": (),
        "total_loc": 0,
        "total_files": 0,
        "structure": (),
        "entrypoints": (),
        "build_files": (),
        "ci_workflows": (),
        "tests": _TestLayout(present=False, frameworks=(), paths=()),
        "dependencies": (),
        "components": (),
        "public_surface": (),
        "docs": DocPresence(
            has_readme=False, readme_paths=(), doc_dirs=(), other_docs=()
        ),
        "artifacts": (),
        "scan_stats": _scan_stats(),
    }
    fields.update(overrides)
    return RepoAnalysis(**fields)  # type: ignore[arg-type]


def _component(
    name: str,
    path: str,
    *files: str,
) -> Component:
    return Component(name=name, path=path, representative_files=files)


def _analyze_fixture() -> RepoAnalysis:
    return analyze(scan(str(_FIXTURE_REPO)))


def _ids(questions: tuple[Question, ...]) -> tuple[str, ...]:
    return tuple(question.id for question in questions)


def _is_role_intent_pair(question_id: str) -> bool:
    """True when the slug (or whole id) is the retired ``{role}__{intent}`` shape."""
    slug = question_id.split(":", 1)[-1]
    for value in (question_id, slug):
        parts = Path(value).name.split("__")
        if 2 <= len(parts) <= 3 and all(parts):
            return True
    return False


# --------------------------------------------------------------------------- #
# Shipped sample (Req 2.1, 3.2, 3.4, 11.3)                                     #
# --------------------------------------------------------------------------- #


def test_sample_analysis_plans_stable_ids_kinds_and_order() -> None:
    analysis = _analyze_fixture()
    plan = plan_questions(analysis)

    assert plan.repo_path == analysis.repo_path
    assert _ids(plan.questions) == (
        "component:root",
        "build:pyproject.toml",
    )
    assert [question.kind for question in plan.questions] == [
        QuestionKind.COMPONENT,
        QuestionKind.BUILD,
    ]
    root, build = plan.questions
    assert root.title == "What does root do?"
    assert root.subject_name == "root"
    assert root.evidence_paths == ("app.py", "config.py", "engine.py")
    assert root.id == make_question_id(QuestionKind.COMPONENT, root.subject_name)
    assert build.title == "How is this project built and verified?"
    assert build.subject_name == "pyproject.toml"
    assert build.evidence_paths == ("pyproject.toml",)
    assert build.id == make_question_id(QuestionKind.BUILD, build.subject_name)
    assert analysis.entrypoints == ()
    assert analysis.public_surface == ()
    assert analysis.tests.present is False


def test_two_planning_runs_on_unchanged_sample_match() -> None:
    first = plan_questions(_analyze_fixture())
    second = plan_questions(_analyze_fixture())
    assert first == second
    assert _ids(first.questions) == _ids(second.questions)
    assert [question.kind for question in first.questions] == [
        question.kind for question in second.questions
    ]


def test_equal_analyses_yield_equal_plans() -> None:
    analysis = _analyze_fixture()
    assert plan_questions(analysis) == plan_questions(analysis)


# --------------------------------------------------------------------------- #
# Empty / signal-free → empty plan (Req 3.5, 3.6, 4.3)                         #
# --------------------------------------------------------------------------- #


def test_empty_analysis_yields_empty_plan() -> None:
    analysis = _analysis(repo_path="/repo/empty")
    plan = plan_questions(analysis)
    assert plan.questions == ()
    assert plan.repo_path == "/repo/empty"


def test_signal_free_analysis_with_docs_and_roles_noise_yields_empty_plan() -> None:
    """Languages, docs, artifacts, and dependencies are not question signals.

    A default reader-role list is not an analysis field and must not be
    consulted; leftover non-activating findings also must not invent pages.
    """
    analysis = _analysis(
        repo_path="/repo/readme-only",
        languages=(LanguageStat(language="Markdown", files=1, loc=12),),
        primary_languages=("Markdown",),
        total_loc=12,
        total_files=1,
        docs=DocPresence(
            has_readme=True,
            readme_paths=("README.md",),
            doc_dirs=(),
            other_docs=(),
        ),
        artifacts=(Artifact(path="LICENSE", kind="license"),),
        dependencies=(
            Dependency(
                name="pytest",
                version_spec=">=8",
                source="pyproject.toml",
                scope="dev",
            ),
        ),
    )
    plan = plan_questions(analysis)
    assert plan.questions == ()
    assert plan.repo_path == "/repo/readme-only"


def test_plan_questions_takes_only_the_analysis() -> None:
    parameters = inspect.signature(plan_questions).parameters
    assert list(parameters) == ["analysis"]


def test_planner_module_does_not_import_a_role_vocabulary() -> None:
    source_path = (
        Path(__file__).resolve().parents[1]
        / "docuharnessx"
        / "planning"
        / "questions.py"
    )
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.append(node.module or "")
            imported.extend(alias.name for alias in node.names)
    joined = " ".join(imported)
    assert "ontology" not in joined
    assert "vocabulary" not in joined.lower()
    assert "default_profile" not in joined
    assert "classifier" not in joined
    assert "matrix" not in joined


# --------------------------------------------------------------------------- #
# Per-signal kinds (Req 3.1–3.4)                                               #
# --------------------------------------------------------------------------- #


def test_entrypoints_plan_one_startup_question() -> None:
    analysis = _analysis(
        entrypoints=(
            Entrypoint(path="src/cli/app.py", kind="cli", name=""),
            Entrypoint(path="pkg/__main__.py", kind="main", name=""),
        )
    )
    plan = plan_questions(analysis)
    assert len(plan.questions) == 1
    question = plan.questions[0]
    assert question.kind is QuestionKind.STARTUP
    assert question.id == "startup:app.py"
    assert question.title == "How does this program start?"
    assert question.subject_name == "app.py"
    assert question.evidence_paths == ("src/cli/app.py", "pkg/__main__.py")
    assert question.id == make_question_id(question.kind, question.subject_name)


def test_startup_keeps_dunder_main_slug() -> None:
    analysis = _analysis(
        entrypoints=(Entrypoint(path="pkg/__main__.py", kind="main", name=""),)
    )
    question = plan_questions(analysis).questions[0]
    assert question.id == "startup:__main__.py"
    assert question.subject_name == "__main__.py"


def test_named_component_plans_what_does_name_do() -> None:
    analysis = _analysis(
        components=(
            _component("engine", "engine", "engine.py", "engine_support.py"),
        )
    )
    question = plan_questions(analysis).questions[0]
    assert question.kind is QuestionKind.COMPONENT
    assert question.id == "component:engine"
    assert question.title == "What does engine do?"
    assert question.subject_name == "engine"
    assert question.evidence_paths == ("engine.py", "engine_support.py")


def test_public_surface_plans_one_extend_or_use_question() -> None:
    analysis = _analysis(
        public_surface=(
            PublicSymbol(
                name="scan", kind="cli_subcommand", source="cmd/mh/main.go"
            ),
            PublicSymbol(
                name="Hash", kind="exported_symbol", source="internal/hashing/hash.go"
            ),
            PublicSymbol(
                name="scan", kind="exported_symbol", source="cmd/mh/main.go"
            ),
        )
    )
    plan = plan_questions(analysis)
    assert len(plan.questions) == 1
    question = plan.questions[0]
    assert question.kind is QuestionKind.PUBLIC_SURFACE
    assert question.id == "public_surface:main.go"
    assert question.title == "How is the public surface used or extended?"
    assert question.subject_name == "main.go"
    assert question.evidence_paths == (
        "cmd/mh/main.go",
        "internal/hashing/hash.go",
    )


def test_build_files_plan_one_build_question() -> None:
    analysis = _analysis(
        build_files=(BuildFile(path="go.mod", kind="go_mod"),),
        ci_workflows=(
            CIWorkflow(path=".github/workflows/ci.yml", provider="github_actions"),
        ),
    )
    question = plan_questions(analysis).questions[0]
    assert question.kind is QuestionKind.BUILD
    assert question.id == "build:go.mod"
    assert question.title == "How is this project built and verified?"
    assert question.subject_name == "go.mod"
    assert question.evidence_paths == ("go.mod", ".github/workflows/ci.yml")


def test_ci_without_build_files_still_plans_build_question() -> None:
    analysis = _analysis(
        ci_workflows=(
            CIWorkflow(path=".github/workflows/ci.yml", provider="github_actions"),
        )
    )
    question = plan_questions(analysis).questions[0]
    assert question.kind is QuestionKind.BUILD
    assert question.id == "build:ci.yml"
    assert question.evidence_paths == (".github/workflows/ci.yml",)


def test_tests_present_plans_one_test_layout_question() -> None:
    analysis = _analysis(
        tests=_TestLayout(
            present=True,
            frameworks=("pytest",),
            paths=("tests/test_engine.py", "tests/test_app.py"),
        )
    )
    question = plan_questions(analysis).questions[0]
    assert question.kind is QuestionKind.TESTS
    assert question.id == "tests:test_engine.py"
    assert question.title == "How are tests organized?"
    assert question.subject_name == "test_engine.py"
    assert question.evidence_paths == ("tests/test_engine.py", "tests/test_app.py")


def test_tests_present_with_no_paths_still_plans_tests_question() -> None:
    analysis = _analysis(
        tests=_TestLayout(present=True, frameworks=("go_testing",), paths=())
    )
    question = plan_questions(analysis).questions[0]
    assert question.kind is QuestionKind.TESTS
    assert question.id == "tests:tests"
    assert question.subject_name == "tests"
    assert question.evidence_paths == ()


# --------------------------------------------------------------------------- #
# Order, caps, no invented questions (Req 4.1, 4.2, 4.3)                       #
# --------------------------------------------------------------------------- #


def test_question_order_is_startup_components_surface_build_tests() -> None:
    analysis = _analysis(
        entrypoints=(Entrypoint(path="main.go", kind="main", name=""),),
        components=(
            _component("hashing", "internal/hashing", "internal/hashing/hash.go"),
            _component("scanner", "internal/scanner", "internal/scanner/scan.go"),
        ),
        public_surface=(
            PublicSymbol(name="scan", kind="cli_subcommand", source="main.go"),
        ),
        build_files=(BuildFile(path="go.mod", kind="go_mod"),),
        tests=_TestLayout(
            present=True,
            frameworks=("go_testing",),
            paths=("internal/hashing/hash_test.go",),
        ),
    )
    plan = plan_questions(analysis)
    assert _ids(plan.questions) == (
        "startup:main.go",
        "component:hashing",
        "component:scanner",
        "public_surface:main.go",
        "build:go.mod",
        "tests:hash_test.go",
    )
    assert [question.kind for question in plan.questions] == [
        QuestionKind.STARTUP,
        QuestionKind.COMPONENT,
        QuestionKind.COMPONENT,
        QuestionKind.PUBLIC_SURFACE,
        QuestionKind.BUILD,
        QuestionKind.TESTS,
    ]


def test_component_cap_drops_extra_component_questions() -> None:
    components = tuple(
        _component(f"c{index:02d}", f"pkg/c{index:02d}", f"pkg/c{index:02d}/mod.py")
        for index in range(MAX_COMPONENT_QUESTIONS + 2)
    )
    analysis = _analysis(
        entrypoints=(Entrypoint(path="app.py", kind="main", name=""),),
        components=components,
        public_surface=(
            PublicSymbol(name="run", kind="exported_symbol", source="app.py"),
        ),
        build_files=(BuildFile(path="pyproject.toml", kind="pyproject"),),
        tests=_TestLayout(
            present=True, frameworks=("pytest",), paths=("tests/test_app.py",)
        ),
    )
    plan = plan_questions(analysis)
    component_questions = [
        question
        for question in plan.questions
        if question.kind is QuestionKind.COMPONENT
    ]
    assert len(component_questions) == MAX_COMPONENT_QUESTIONS
    assert _ids(tuple(component_questions)) == tuple(
        f"component:c{index:02d}" for index in range(MAX_COMPONENT_QUESTIONS)
    )
    assert "component:c06" not in _ids(plan.questions)
    assert "component:c07" not in _ids(plan.questions)
    assert [question.kind for question in plan.questions] == [
        QuestionKind.STARTUP,
        *[QuestionKind.COMPONENT] * MAX_COMPONENT_QUESTIONS,
        QuestionKind.PUBLIC_SURFACE,
        QuestionKind.BUILD,
        QuestionKind.TESTS,
    ]
    assert len(plan.questions) <= MAX_QUESTIONS
    assert len(plan.questions) == 4 + MAX_COMPONENT_QUESTIONS


def test_max_questions_is_the_hard_cap() -> None:
    components = tuple(
        _component(f"c{index:02d}", f"pkg/c{index:02d}", f"pkg/c{index:02d}/mod.py")
        for index in range(MAX_QUESTIONS + 4)
    )
    analysis = _analysis(components=components)
    plan = plan_questions(analysis)
    assert len(plan.questions) == MAX_COMPONENT_QUESTIONS
    assert len(plan.questions) <= MAX_QUESTIONS
    assert all(question.kind is QuestionKind.COMPONENT for question in plan.questions)


def test_planned_ids_are_not_a_role_intent_pair() -> None:
    analysis = _analyze_fixture()
    plan = plan_questions(analysis)
    assert plan.questions
    for question in plan.questions:
        assert not _is_role_intent_pair(question.id), question.id
        assert _ROLE_INTENT_ID not in question.id
        assert question.id == make_question_id(question.kind, question.subject_name)
