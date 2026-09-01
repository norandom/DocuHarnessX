"""Package-shipped blueprint identity (blueprint-adoption-loop task 1.1).

These constants are the named contract an operator adopts at setup. They are
bumped only when the default vocabulary or page contract changes — not when
the git tag or package version happens to move.

Distinct from :mod:`docuharnessx.composition.blueprint` (COBESY composition
blueprint). Recording the values into local project configuration is a later
adoption-service task.
"""

from __future__ import annotations

BLUEPRINT_NAME: str = "docuharnessx-default"
BLUEPRINT_VERSION: str = "2.0.0"
