"""Default-quiet console logging + the -v/--verbose flag (dhx CLI).

By default a `dhx` run prints only warnings, errors, and the run summary; the
HarnessX pipeline-event logs (via structlog) and LiteLLM's debug output are
suppressed. ``-v``/``--verbose`` restores the detailed logs.
"""

import logging

from docuharnessx import cli


def test_run_parser_accepts_verbose() -> None:
    parser = cli.build_parser()
    assert parser.parse_args(["run", "t", "--verbose"]).verbose is True
    assert parser.parse_args(["run", "t", "-v"]).verbose is True
    assert parser.parse_args(["run", "t"]).verbose is False


def test_init_parser_accepts_verbose() -> None:
    parser = cli.build_parser()
    assert parser.parse_args(["init", ".", "--verbose"]).verbose is True
    assert parser.parse_args(["init", "."]).verbose is False


def test_default_silences_litellm() -> None:
    saved = logging.getLogger("LiteLLM").level
    try:
        cli._configure_run_logging(verbose=False)
        assert logging.getLogger("LiteLLM").level == logging.CRITICAL
        try:
            import litellm

            assert litellm.suppress_debug_info is True
        except ImportError:
            pass
    finally:
        logging.getLogger("LiteLLM").setLevel(saved)


def test_verbose_does_not_silence_litellm() -> None:
    saved = logging.getLogger("LiteLLM").level
    try:
        logging.getLogger("LiteLLM").setLevel(logging.DEBUG)
        cli._configure_run_logging(verbose=True)
        # Verbose must NOT force the LiteLLM logger to CRITICAL.
        assert logging.getLogger("LiteLLM").level != logging.CRITICAL
    finally:
        logging.getLogger("LiteLLM").setLevel(saved)


def _harness_record(message: str) -> logging.LogRecord:
    log = logging.getLogger("harnessx.core.harness")
    return log.makeRecord(log.name, logging.WARNING, __file__, 0, message, None, None)


def _drop_added_harness_filters() -> None:
    log = logging.getLogger("harnessx.core.harness")
    for f in list(log.filters):
        if isinstance(f, cli._DropHarnessSerializationNoise):
            log.removeFilter(f)


def test_suppresses_todo_write_serialization_warning() -> None:
    try:
        cli._configure_run_logging(verbose=False)
        log = logging.getLogger("harnessx.core.harness")
        benign = _harness_record(
            "tool_registry: tool 'todo_write' has no recorded __hx_target__ and its "
            "function lives in a non-importable module"
        )
        other = _harness_record("a genuine harness warning worth seeing")
        # Logger.filter() is falsy when a filter drops the record, truthy when kept.
        assert not log.filter(benign)
        assert log.filter(other)
    finally:
        _drop_added_harness_filters()


def test_todo_write_warning_suppressed_even_in_verbose() -> None:
    try:
        cli._configure_run_logging(verbose=True)
        log = logging.getLogger("harnessx.core.harness")
        benign = _harness_record("tool 'todo_write' has no recorded __hx_target__")
        assert not log.filter(benign)
    finally:
        _drop_added_harness_filters()


def test_serialization_filter_is_installed_once() -> None:
    try:
        log = logging.getLogger("harnessx.core.harness")
        cli._configure_run_logging(verbose=False)
        cli._configure_run_logging(verbose=False)
        installed = [
            f for f in log.filters if isinstance(f, cli._DropHarnessSerializationNoise)
        ]
        assert len(installed) == 1
    finally:
        _drop_added_harness_filters()


def _drop_added_asyncio_filters() -> None:
    log = logging.getLogger("asyncio")
    for f in list(log.filters):
        if isinstance(f, cli._DropEventLoopClosedNoise):
            log.removeFilter(f)


def _asyncio_record(message: str, exc: BaseException | None) -> logging.LogRecord:
    log = logging.getLogger("asyncio")
    exc_info = (type(exc), exc, None) if exc is not None else None
    return log.makeRecord(log.name, logging.ERROR, __file__, 0, message, None, exc_info)


def test_suppresses_event_loop_closed_teardown_noise() -> None:
    try:
        cli._configure_run_logging(verbose=False)
        log = logging.getLogger("asyncio")
        benign = _asyncio_record(
            "Task exception was never retrieved", RuntimeError("Event loop is closed")
        )
        real = _asyncio_record(
            "Task exception was never retrieved", ValueError("a genuine bug")
        )
        unrelated = _asyncio_record("some other asyncio diagnostic", None)
        assert not log.filter(benign)  # dropped — benign teardown noise
        assert log.filter(real)  # a different exception is kept
        assert log.filter(unrelated)  # unrelated asyncio logs are kept
    finally:
        _drop_added_asyncio_filters()


def test_event_loop_filter_installed_once() -> None:
    try:
        log = logging.getLogger("asyncio")
        cli._configure_run_logging(verbose=False)
        cli._configure_run_logging(verbose=False)
        installed = [
            f for f in log.filters if isinstance(f, cli._DropEventLoopClosedNoise)
        ]
        assert len(installed) == 1
    finally:
        _drop_added_asyncio_filters()
