"""Property 16 (Requirement 20) — anomaly flag invariance.

- Flags are unchanged under reordering an entity's history (median/MAD are order-insensitive).
- Flags are unchanged under multiplying every amount by a positive constant, for both the
  modified z-score branch and the zero-dispersion branch, when the zero-dispersion absolute
  floor is scaled by the same constant.

Pure logic; no database and no model call.
"""

from __future__ import annotations

from decimal import Decimal

from hypothesis import assume, given
from hypothesis import strategies as st

from app.services.pipeline.anomaly import (
    AnomalyConfig,
    evaluate_entity,
)

_CONFIG = AnomalyConfig()


def _dec(x) -> Decimal:
    return Decimal(str(x))


@st.composite
def entity_history(draw):
    """A history (>= min_history_count values) plus a value under evaluation.

    Includes near-constant series to exercise the zero-dispersion branch.
    """
    n = draw(st.integers(min_value=6, max_value=30))
    if draw(st.booleans()):
        # constant / near-constant history -> zero-dispersion branch
        base = draw(st.integers(min_value=1, max_value=10_000))
        history = [_dec(base)] * n
    else:
        history = [
            _dec(draw(st.integers(min_value=1, max_value=100_000))) for _ in range(n)
        ]
    value = _dec(draw(st.integers(min_value=1, max_value=10_000_000)))
    return history, value


@given(data=entity_history())
def test_p16_flag_invariant_under_history_reordering(data) -> None:
    history, value = data
    forward = evaluate_entity("e1", value, history, _CONFIG)
    reversed_ = evaluate_entity("e1", value, list(reversed(history)), _CONFIG)
    shuffled = evaluate_entity("e1", value, sorted(history), _CONFIG)
    assert _flag_key(forward) == _flag_key(reversed_) == _flag_key(shuffled)


@given(
    data=entity_history(),
    scale=st.integers(min_value=1, max_value=1000),
)
def test_p16_flag_invariant_under_positive_scaling(data, scale) -> None:
    history, value = data
    k = _dec(scale)
    assume(k > 0)

    base_config = _CONFIG
    scaled_config = AnomalyConfig(
        z_threshold=base_config.z_threshold,
        min_history_count=base_config.min_history_count,
        zero_dispersion_relative_threshold=base_config.zero_dispersion_relative_threshold,
        # Property 16: the absolute floor must scale with the amounts.
        zero_dispersion_absolute_floor=base_config.zero_dispersion_absolute_floor * k,
        max_callouts=base_config.max_callouts,
    )

    base = evaluate_entity("e1", value, history, base_config)
    scaled = evaluate_entity(
        "e1", value * k, [h * k for h in history], scaled_config
    )
    assert _flag_key(base) == _flag_key(scaled)


def _flag_key(result):
    """Whether a result is a flag and, if so, its kind — the invariant we compare."""
    from app.services.pipeline.anomaly import AnomalyFlag

    if isinstance(result, AnomalyFlag):
        return ("flag", result.kind)
    return ("skip", result)


def test_p16_known_modified_z_outlier() -> None:
    history = [_dec(100)] * 3 + [_dec(101), _dec(99), _dec(100), _dec(102), _dec(98)]
    outlier = evaluate_entity("v1", _dec(100_000), history, _CONFIG)
    from app.services.pipeline.anomaly import AnomalyFlag

    assert isinstance(outlier, AnomalyFlag)
    assert outlier.kind == "modified_z"


def test_p16_zero_dispersion_branch() -> None:
    history = [_dec(1000)] * 8  # MAD == 0
    # diff = 5000 - 1000 = 4000 > 0.20*1000=200 and > absolute floor 1000 -> flag
    flagged = evaluate_entity("v1", _dec(5000), history, _CONFIG)
    from app.services.pipeline.anomaly import AnomalyFlag

    assert isinstance(flagged, AnomalyFlag)
    assert flagged.kind == "zero_dispersion"

    # A small bump within the floor is not flagged.
    within = evaluate_entity("v1", _dec(1100), history, _CONFIG)
    assert within == "zero_dispersion_within_threshold"
