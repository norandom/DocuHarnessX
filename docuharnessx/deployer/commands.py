"""The isolated, mockable command runner (design "Command runner"; task 2.4).

This module is the **only process-touching surface** of the Wave 3 ``github-pages-deploy``
core. Every ``git`` / ``mkdocs`` invocation the deployer needs goes through one mockable
:class:`CommandRunner` seam, so the deterministic emit-ci-workflow / build-only paths run
credential-free and unit-testable and the ``mkdocs gh-deploy`` push — the **only** network
action — is isolated behind the same seam and never exercised in tests (Req 5.4, 7.4). It
mirrors the assembler's single mockable :func:`docuharnessx.assembler.identity.read_origin_remote`
process boundary.

It provides:

* :class:`CommandRunner` — a runtime-checkable :class:`~typing.Protocol` with a single
  ``run(args, cwd) -> CompletedResult`` method, the substitutable seam tests inject a fake
  for;
* :class:`CompletedResult` — a frozen value object carrying ``returncode`` / ``stdout`` /
  ``stderr`` (the minimal slice of :class:`subprocess.CompletedProcess` the deployer reads);
* :class:`DefaultCommandRunner` — the production implementation that shells out via
  :func:`subprocess.run` (argument-vector, no shell, text-mode, time-bounded, ``check=False``);
* :func:`read_default_branch` — read the target's default branch with a safe ``"main"``
  fallback when git is unavailable / fails, so a git-less environment still emits a usable
  workflow rather than aborting (Req 4.3);
* :func:`run_mkdocs_build` — run ``mkdocs build`` as build validation against the assembled
  ``mkdocs.yml`` (whose per-target ``site_url`` / ``/<repo>/`` base-path is already baked in,
  Req 7.2), returning the absolute built-site dir and raising :class:`DeployError` on a
  non-zero exit or missing tooling (Req 7.1, 7.3). No network (Req 7.4);
* :func:`run_mkdocs_gh_deploy` — run the ``mkdocs gh-deploy`` push (the one network action,
  Req 5.1), raising :class:`DeployError` naming the missing prerequisite when the remote /
  tooling is unavailable (Req 5.3). Never invoked on the validated modes' paths.

The runner functions take ``site`` / ``target_repo`` as plain inputs and the
:class:`CommandRunner` as an injected dependency; they hold no global state, perform no I/O
beyond the injected runner, and never derive DocuHarnessX's own identity — every parameter
comes from the consumed :class:`~docuharnessx.assembler.model.AssembledSite` and the target
path. The build's static-site output dir is derived deterministically from the assembled
``site_dir`` (a nested ``site`` subdirectory, ``<out>/site/site/`` per the design), so the
build writes only under the run output tree, never into the target repo (Req 9.1).
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from docuharnessx.deployer.model import DeployError

if TYPE_CHECKING:  # pragma: no cover - typing-only import; no runtime dependency
    from docuharnessx.assembler.model import AssembledSite

__all__ = [
    "CompletedResult",
    "CommandRunner",
    "DefaultCommandRunner",
    "read_default_branch",
    "run_mkdocs_build",
    "run_mkdocs_gh_deploy",
]

#: Wall-clock ceiling (seconds) for ``mkdocs build`` / ``mkdocs gh-deploy``, and the default
#: ceiling for any :meth:`CommandRunner.run` call that does not pass an explicit ``timeout``.
#: Generous — a real build may pull/process many pages — while still bounding a wedged
#: invocation. The build and push surfaces are isolated here and always invoked through the
#: injected runner.
_MKDOCS_TIMEOUT_SECONDS: float = 600.0

#: Wall-clock ceiling (seconds) for the read-only default-branch read, threaded into the
#: runner via :meth:`CommandRunner.run`'s ``timeout`` argument by :func:`read_default_branch`.
#: A hung git invocation degrades to the ``"main"`` fallback rather than stalling the run
#: (Req 4.3); the read is a trivial local lookup so a few seconds is generous. Mirrors the
#: assembler's remote-read timeout (``read_origin_remote``), which likewise applies its own
#: short ceiling to the subprocess rather than inheriting the build ceiling.
_GIT_BRANCH_READ_TIMEOUT_SECONDS: float = 5.0

#: The default branch returned when the target's branch cannot be read (Req 4.3). The emitted
#: workflow then triggers on ``main`` — the GitHub default — so a git-less / detached-HEAD
#: target still gets a usable workflow.
_DEFAULT_BRANCH_FALLBACK: str = "main"

#: The static-site output directory name. ``mkdocs build`` writes the rendered site here; it is
#: a ``site`` subdirectory **nested inside** the assembled ``site_dir`` (``<out>/site/site/`` per
#: design line 117), under the run output tree (never the target repo — Req 9.1). Nesting inside
#: ``site_dir`` — rather than a sibling — is required: the assembler writes the source to
#: ``<out>/site``, so a sibling ``<out>/site`` would *be* the source dir and ``mkdocs build
#: --strict`` aborts ("'docs_dir' should not be within the 'site_dir'"). The nested ``site``
#: subdir sits beside the ``docs`` tree without containing it, so the build is clean.
_BUILT_SITE_DIRNAME: str = "site"


@dataclass(frozen=True)
class CompletedResult:
    """The minimal, frozen slice of a finished subprocess the deployer reads.

    Carries only the ``returncode`` and the captured ``stdout`` / ``stderr`` — the deployer
    never needs the full :class:`subprocess.CompletedProcess`. Frozen so it is an immutable
    value object that compares by value, keeping the runner seam easy to fake in tests.
    """

    returncode: int
    stdout: str = ""
    stderr: str = ""


@runtime_checkable
class CommandRunner(Protocol):
    """The substitutable command-execution seam (design "Command runner").

    A single ``run(args, cwd)`` method returning a :class:`CompletedResult`. Production code
    uses :class:`DefaultCommandRunner` (real :mod:`subprocess`); tests inject a fake that
    records the invocation and returns a canned result, so no real ``git`` / ``mkdocs``
    process is spawned and the ``gh-deploy`` push is never exercised (Req 5.4, 7.4).

    Runtime-checkable so a duck-typed fake satisfies :func:`isinstance` checks without
    subclassing. Implementations must not raise for a non-zero exit — they return the result
    with the non-zero ``returncode``; the caller decides whether that is fatal. A missing
    executable surfaces as the underlying :class:`FileNotFoundError` / :class:`OSError`, which
    the runner functions translate into a :class:`DeployError`.

    The optional ``timeout`` is the per-call wall-clock ceiling (seconds): the read-only
    default-branch read passes the short :data:`_GIT_BRANCH_READ_TIMEOUT_SECONDS` so a wedged
    git degrades quickly to the ``"main"`` fallback (Req 4.3), while the build / push surfaces
    leave it unset to inherit the generous :data:`_MKDOCS_TIMEOUT_SECONDS`. Keeping it an
    optional keyword preserves the design-stated ``run(args, cwd)`` contract.
    """

    def run(  # pragma: no cover - protocol
        self, args: "Sequence[str]", cwd: str, timeout: float | None = None
    ) -> CompletedResult:
        ...


class DefaultCommandRunner:
    """The production :class:`CommandRunner` shelling out via :func:`subprocess.run`.

    Every invocation is argument-vector (``shell=False``), text-mode, output-capturing,
    ``check=False`` (the caller inspects ``returncode``), and time-bounded. It performs no
    shell interpolation and uses no credentials of its own — a ``gh-deploy`` push relies on
    the ambient git credentials of the environment it runs in, and is only ever reached on the
    explicit gh-deploy mode.
    """

    def run(
        self, args: "Sequence[str]", cwd: str, timeout: float | None = None
    ) -> CompletedResult:
        """Run ``args`` in ``cwd`` and return the :class:`CompletedResult`.

        ``timeout`` is the per-call wall-clock ceiling (seconds); when ``None`` it falls back
        to the generous :data:`_MKDOCS_TIMEOUT_SECONDS` so the build / push surfaces keep their
        existing ceiling, while the default-branch read passes the short
        :data:`_GIT_BRANCH_READ_TIMEOUT_SECONDS` to degrade a wedged git quickly (Req 4.3).

        Raises whatever :func:`subprocess.run` raises (e.g. :class:`FileNotFoundError` for a
        missing executable, :class:`subprocess.TimeoutExpired`); the runner functions catch
        those and translate them into a :class:`DeployError` or the ``"main"`` fallback.
        """
        completed = subprocess.run(
            list(args),
            cwd=cwd,
            capture_output=True,
            text=True,
            shell=False,
            check=False,
            timeout=_MKDOCS_TIMEOUT_SECONDS if timeout is None else timeout,
        )
        return CompletedResult(
            returncode=completed.returncode,
            stdout=completed.stdout or "",
            stderr=completed.stderr or "",
        )


# --------------------------------------------------------------------------- #
# Default-branch read (Req 4.3)                                                #
# --------------------------------------------------------------------------- #


def read_default_branch(target_repo: str, runner: CommandRunner) -> str:
    """Return the target repo's default branch, falling back to ``"main"`` (Req 4.3).

    Reads the branch the target actually publishes from so the emitted workflow's ``push``
    trigger matches the target's default branch. Tries, in order:

    1. ``git -C <target> symbolic-ref --short HEAD`` — the currently checked-out branch, the
       common case for a normal working tree;
    2. ``git -C <target> remote show origin`` parsed for the ``HEAD branch:`` line — the
       remote's default branch, used when HEAD is detached;

    and degrades to :data:`_DEFAULT_BRANCH_FALLBACK` (``"main"``) when neither succeeds. Every
    failure mode is swallowed so a git-less / remote-less / detached environment still emits a
    usable workflow rather than aborting the run (Req 4.3):

    * a non-zero git exit (no repo / detached HEAD / no remote);
    * a missing ``git`` executable (:class:`FileNotFoundError`);
    * any other failed / timed-out invocation (:class:`OSError`,
      :class:`subprocess.SubprocessError`);
    * a zero exit with empty / unparseable output.

    The invocations are read-only (``symbolic-ref`` / ``remote show``) and scoped to the target
    via ``-C``; this function never pushes, commits, or writes to the target git.

    Args:
        target_repo: The target repository's directory path.
        runner: The :class:`CommandRunner` seam (a fake in tests).

    Returns:
        The trimmed default branch name, or ``"main"`` when it cannot be read.
    """
    symbolic = _safe_run(
        runner,
        ["git", "-C", target_repo, "symbolic-ref", "--short", "HEAD"],
        target_repo,
        timeout=_GIT_BRANCH_READ_TIMEOUT_SECONDS,
    )
    if symbolic is not None and symbolic.returncode == 0:
        branch = (symbolic.stdout or "").strip()
        if branch:
            return branch

    remote = _safe_run(
        runner,
        ["git", "-C", target_repo, "remote", "show", "origin"],
        target_repo,
        timeout=_GIT_BRANCH_READ_TIMEOUT_SECONDS,
    )
    if remote is not None and remote.returncode == 0:
        branch = _parse_remote_head_branch(remote.stdout or "")
        if branch:
            return branch

    return _DEFAULT_BRANCH_FALLBACK


def _safe_run(
    runner: CommandRunner, args: "Sequence[str]", cwd: str, *, timeout: float | None = None
) -> CompletedResult | None:
    """Run ``args`` through ``runner``, swallowing every failure to ``None`` (Req 4.3).

    Used by the graceful default-branch read so a missing git executable, a timeout, or any
    other process failure degrades to the ``"main"`` fallback rather than aborting. Never used
    for the fail-loud build / push paths, which surface their failures as :class:`DeployError`.

    ``timeout`` is forwarded to the runner as the per-call ceiling; the default-branch read
    passes the short :data:`_GIT_BRANCH_READ_TIMEOUT_SECONDS` so a hung git degrades to the
    ``"main"`` fallback quickly (a :class:`subprocess.TimeoutExpired` is a
    :class:`subprocess.SubprocessError`, so it is swallowed here exactly like any other read
    failure).
    """
    try:
        return runner.run(args, cwd, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None


def _parse_remote_head_branch(remote_show_output: str) -> str:
    """Extract the default branch from ``git remote show origin`` output (Req 4.3).

    Looks for the ``HEAD branch: <name>`` line git prints for the remote's default branch.
    Returns the branch name, or ``""`` when the line is absent / the value is ``(unknown)``.
    Pure string parsing; no I/O.
    """
    for line in remote_show_output.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith("head branch:"):
            value = stripped.split(":", 1)[1].strip()
            if value and value != "(unknown)":
                return value
    return ""


# --------------------------------------------------------------------------- #
# Build validation (Req 7.1, 7.2, 7.3, 7.4)                                    #
# --------------------------------------------------------------------------- #


def _built_site_dir(site: "AssembledSite") -> str:
    """Return the absolute ``mkdocs build`` output dir for ``site`` (Req 9.1).

    A ``site`` subdirectory **nested inside** the assembled site source dir
    (``<out>/site/site/`` per design line 117), under the run output tree — never the target
    repo. Nesting inside ``site_dir`` (not a sibling) is mandatory: the assembler writes the
    source to ``<out>/site`` so ``site_dir`` *is* ``<out>/site``; a sibling would resolve to the
    same path as ``site_dir`` and ``mkdocs build --strict`` would abort because the ``docs_dir``
    then sits within the ``site_dir``. The nested subdir sits beside the ``docs`` tree without
    overlapping it, so the build is clean. Deterministic for a given ``site``.
    """
    return os.path.join(os.path.abspath(site.site_dir), _BUILT_SITE_DIRNAME)


def run_mkdocs_build(site: "AssembledSite", runner: CommandRunner) -> str:
    """Run ``mkdocs build`` as build validation, returning the built-site dir (Req 7.1, 7.3).

    Builds the assembled site against its own ``mkdocs.yml`` (``-f <mkdocs_yml_path>``), whose
    per-target ``site_url`` / ``/<repo>/`` base-path is already baked in by the assembler, so
    the produced static site resolves links and assets under the target's Pages subpath
    (Req 7.2) without this function re-parsing the remote. The output is written to a ``site``
    subdirectory nested inside the assembled ``site_dir`` (``<out>/site/site/``) via ``-d``,
    never into the target repo (Req 9.1).

    The build is run with ``--strict`` so broken links / warnings fail the build, making the
    validation meaningful: a site that does not build cleanly under the per-target base-path is
    never reported as deployed.

    Performs no network access (Req 7.4) — ``mkdocs build`` is purely local; only
    :func:`run_mkdocs_gh_deploy` reaches the network.

    Args:
        site: The consumed :class:`~docuharnessx.assembler.model.AssembledSite` (read-only).
        runner: The :class:`CommandRunner` seam (a fake in tests).

    Returns:
        The absolute path to the produced static-site directory.

    Raises:
        DeployError: When ``mkdocs build`` exits non-zero or the build tooling is unavailable
            (Req 7.3). The message names the failed build and the captured cause; success is
            never declared on a failed build.
    """
    built = _built_site_dir(site)
    args = [
        "mkdocs",
        "build",
        "--strict",
        "--config-file",
        site.mkdocs_yml_path,
        "--site-dir",
        built,
    ]
    cwd = os.path.dirname(os.path.abspath(site.mkdocs_yml_path))

    try:
        result = runner.run(args, cwd)
    except FileNotFoundError as exc:
        raise DeployError(
            "mkdocs build failed: the mkdocs build tooling is unavailable "
            f"(could not invoke 'mkdocs'): {exc}"
        ) from exc
    except (OSError, subprocess.SubprocessError) as exc:
        raise DeployError(f"mkdocs build failed to run: {exc}") from exc

    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise DeployError(
            f"mkdocs build failed (exit {result.returncode}) for config "
            f"{site.mkdocs_yml_path!r}: {detail}"
        )
    return built


# --------------------------------------------------------------------------- #
# gh-deploy push — the only network action (Req 5.1, 5.3, 5.4)                 #
# --------------------------------------------------------------------------- #


def run_mkdocs_gh_deploy(site: "AssembledSite", runner: CommandRunner) -> None:
    """Run ``mkdocs gh-deploy`` to push the built site to the target ``gh-pages`` (Req 5.1).

    This is the **only** network action in the whole deploy core; it is invoked solely on the
    explicit gh-deploy mode and always through the injected ``runner``, so under a fake runner
    no real push happens (Req 5.4) and tests never reach a real network call. The push targets
    the repository the assembled ``mkdocs.yml`` / target git remote points at — never
    DocuHarnessX's own repo (Req 5.2; the caller guarantees the per-target site).

    Args:
        site: The consumed :class:`~docuharnessx.assembler.model.AssembledSite` (read-only).
        runner: The :class:`CommandRunner` seam (a fake in tests; the real push is never
            spawned under a fake).

    Raises:
        DeployError: When the ``gh-deploy`` prerequisites are missing — no target git remote,
            or ``mkdocs gh-deploy`` is not runnable / exits non-zero — naming the missing
            prerequisite so the stage never silently succeeds (Req 5.3).
    """
    args = ["mkdocs", "gh-deploy", "--config-file", site.mkdocs_yml_path]
    cwd = os.path.dirname(os.path.abspath(site.mkdocs_yml_path))

    try:
        result = runner.run(args, cwd)
    except FileNotFoundError as exc:
        raise DeployError(
            "mkdocs gh-deploy failed: the mkdocs tooling is unavailable "
            f"(could not invoke 'mkdocs'): {exc}"
        ) from exc
    except (OSError, subprocess.SubprocessError) as exc:
        raise DeployError(f"mkdocs gh-deploy failed to run: {exc}") from exc

    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise DeployError(
            f"mkdocs gh-deploy failed (exit {result.returncode}): {detail}. "
            "Check the target has a git remote and the run environment has push access."
        )
