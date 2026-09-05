"""Property-test configuration.

Registers a Hypothesis profile of >=100 examples with no deadline (property tests here
compose Decimal arithmetic and Pydantic validation, which can be slow enough to trip the
default deadline). The DB-backed fixtures live in the top-level ``tests/conftest.py``;
these property modules that need no database import nothing from it.
"""

from __future__ import annotations

from hypothesis import HealthCheck, settings

settings.register_profile(
    "tbx",
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
settings.load_profile("tbx")
