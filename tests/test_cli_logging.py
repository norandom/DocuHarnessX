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
