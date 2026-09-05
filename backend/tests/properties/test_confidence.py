"""Property 14 (Requirement 19) — confidence score invariants.

- The score lies in the closed interval [0, 1].
- The weights of the signals applicable to a Turn are rescaled to sum to 1 (within 0.001).
- The two mandatory signals (reviewer_verdict, groundedness) are always applicable, so at
  least two signals carry non-zero weight for every scored Turn.
- Monotonicity: raising any single normalised signal value never lowers the score.

Pure logic; no database and no model call.
"""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from app.config import (
    DEFAULT_CONFIDENCE_BAND_BOUNDARIES,
    DEFAULT_CONFIDENCE_SIGNAL_WEIGHTS,
)
from app.services.pipeline.confidence import (
    MANDATORY_SIGNALS,
    SIGNAL_ORDER,
    ConfidenceScorer,
    SignalInput,
)

_SCORER = ConfidenceScorer(
    signal_weights=DEFAULT_CONFIDENCE_SIGNAL_WEIGHTS,
    band_boundaries=DEFAULT_CONFIDENCE_BAND_BOUNDARIES,
)

# Weight per signal name: use the configured weight where present, else a small default so
# the generator does not depend on config keys matching the requirement signal set exactly.
_WEIGHTS = {name: DEFAULT_CONFIDENCE_SIGNAL_WEIGHTS.get(name, 0.10) for name in SIGNAL_ORDER}


@st.composite
def signal_vector(draw):
    """A vector of (applicable, normalised_value) over the documented signal set.

    The two mandatory signals are forced applicable so the scorer's precondition holds.
    """
    signals = []
    for name in SIGNAL_ORDER:
        mandatory = name in MANDATORY_SIGNALS
        applicable = True if mandatory else draw(st.booleans())
        value = draw(st.floats(min_value=0.0, max_value=1.0)) if applicable else None
        signals.append(
            SignalInput(
                name=name, applicable=applicable, normalised_value=value, weight=_WEIGHTS[name]
            )
        )
    return signals


@given(signals=signal_vector())
def test_score_in_unit_interval(signals) -> None:
    outcome = _SCORER.score(signals)
    assert 0.0 <= outcome.value <= 1.0


@given(signals=signal_vector())
def test_rescaled_weights_sum_to_one(signals) -> None:
    outcome = _SCORER.score(signals)
    applied = [s.weight for s in outcome.signals if s.applicable]
    assert abs(sum(applied) - 1.0) <= 0.001


@given(signals=signal_vector())
def test_mandatory_signals_always_applicable(signals) -> None:
    outcome = _SCORER.score(signals)
    applicable_names = {s.name for s in outcome.signals if s.applicable}
    assert MANDATORY_SIGNALS <= applicable_names
    assert len(applicable_names) >= 2


@given(signals=signal_vector(), idx=st.integers(min_value=0, max_value=len(SIGNAL_ORDER) - 1))
def test_monotonicity_raise_one_signal(signals, idx) -> None:
    target = signals[idx]
    if not target.applicable or target.normalised_value is None:
        return  # only applicable signals contribute to the score
    if target.normalised_value >= 1.0:
        return

    base = _SCORER.score(signals)

    raised = list(signals)
    raised[idx] = SignalInput(
        name=target.name,
        applicable=True,
        normalised_value=min(1.0, target.normalised_value + 0.25),
        weight=target.weight,
    )
    after = _SCORER.score(raised)

    # Raising a single applicable normalised value never lowers the score (R19.12).
    assert after.value >= base.value - 1e-9


def test_metric_layer_first_attempt_floor() -> None:
    # Weak signals that would otherwise land below the high boundary.
    signals = [
        SignalInput(name=n, applicable=True, normalised_value=0.1, weight=_WEIGHTS[n])
        for n in SIGNAL_ORDER
    ]
    outcome = _SCORER.score(
        signals, path="metric_layer", first_attempt_approve=True, grounded=True
    )
    assert outcome.value >= DEFAULT_CONFIDENCE_BAND_BOUNDARIES["high"]
    assert outcome.band == "high"


def test_voice_clamp_never_raises_band() -> None:
    signals = [
        SignalInput(name=n, applicable=True, normalised_value=1.0, weight=_WEIGHTS[n])
        for n in SIGNAL_ORDER
    ]
    raw = _SCORER.score(signals)
    assert raw.band == "high"
    clamped = _SCORER.score(signals, voice_turn=True, transcription_confidence=0.4)
    assert clamped.value <= 0.4
    assert clamped.band in ("low", "medium")
