"""The engine the fixture application drives.

Read by the scripted fake-agent provider; the ``start`` method's line is cited
by the scripted grounded body. Keep this content stable.
"""

from config import load_config


class Engine:
    """Runs the work loop after loading configuration."""

    def __init__(self) -> None:
        self.config = load_config()

    def start(self) -> int:
        """Execute one bounded work cycle and report success."""
        cycles = self.config.get("cycles", 1)
        for _ in range(cycles):
            self._tick()
        return 0

    def _tick(self) -> None:
        """Perform a single unit of work."""
        return None
