"""Entry point of the crafted agentic fixture repository.

This module is read by the scripted fake-agent provider so its produced
``file:line`` citations resolve to real, stable lines. Keep the line numbers
of ``run`` and ``Application`` stable: the scripted body cites them.
"""

from engine import Engine


class Application:
    """Wires the engine to the command-line entry point."""

    def __init__(self) -> None:
        self.engine = Engine()

    def run(self) -> int:
        """Start the engine and return its exit status."""
        return self.engine.start()


def main() -> int:
    return Application().run()
