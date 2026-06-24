"""Configuration loader for the fixture application.

Read by the scripted fake-agent provider; the ``load_config`` line is cited by
the scripted grounded body. Keep this content stable.
"""

DEFAULTS = {"cycles": 3, "verbose": False}


def load_config() -> dict:
    """Return the effective configuration for a run."""
    return dict(DEFAULTS)
