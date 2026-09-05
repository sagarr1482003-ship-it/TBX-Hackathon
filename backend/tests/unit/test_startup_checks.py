"""Startup config-gate verification (Task 1.5, Requirement 19.9/10.13/10.14/13.13/14.15).

Only the pure configuration gates are exercised; the database gates need PostgreSQL.
"""

from __future__ import annotations

import pytest

from app.errors import StartupCheckError
from app.startup_checks import (
    check_band_boundaries,
    check_budget_ceilings,
    check_concurrency_within_pool,
    check_confidence_weights,
    check_model_tier,
    check_reviewer_independence,
)


def test_confidence_weights_ok() -> None:
    check_confidence_weights({"a": 0.5, "b": 0.5})  # no raise


def test_confidence_weights_negative_rejected() -> None:
    with pytest.raises(StartupCheckError):
        check_confidence_weights({"a": -0.1, "b": 1.1})


def test_confidence_weights_sum_rejected() -> None:
    with pytest.raises(StartupCheckError):
        check_confidence_weights({"a": 0.5, "b": 0.6})


def test_band_boundaries_ascending_ok() -> None:
    check_band_boundaries({"medium": 0.5, "high": 0.8})


def test_band_boundaries_non_ascending_rejected() -> None:
    with pytest.raises(StartupCheckError):
        check_band_boundaries({"medium": 0.8, "high": 0.5})


def test_budget_ceilings_ok() -> None:
    check_budget_ceilings(6, 12_000, 30)


def test_budget_ceilings_exceeded_rejected() -> None:
    with pytest.raises(StartupCheckError):
        check_budget_ceilings(11, 12_000, 30)


def test_concurrency_within_pool() -> None:
    check_concurrency_within_pool(8, 10)
    with pytest.raises(StartupCheckError):
        check_concurrency_within_pool(12, 10)


def test_reviewer_independence() -> None:
    check_reviewer_independence(("ollama", "m1", "v1"), ("ollama", "m1", "v2"))  # differs
    with pytest.raises(StartupCheckError):
        check_reviewer_independence(("ollama", "m1", "v1"), ("ollama", "m1", "v1"))


def test_model_tier_open_weight() -> None:
    check_model_tier("sql_generator", 8.0, None)  # at the ceiling is OK
    with pytest.raises(StartupCheckError):
        check_model_tier("sql_generator", 13.0, None)


def test_model_tier_hosted() -> None:
    check_model_tier("router", None, "mini")
    with pytest.raises(StartupCheckError):
        check_model_tier("router", None, "large")
