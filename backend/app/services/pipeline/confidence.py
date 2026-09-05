"""Confidence_Scorer — a published, reproducible weighted sum over pipeline signals (Req 19).

Design §4.3 ``score()``:

    applicable = [s for s in signals if s.applicable]
    assert {"reviewer_verdict", "groundedness"} <= {s.name for s in applicable}   # R19.11
    total_w  = sum(s.weight for s in applicable)
    rescaled = {s.name: s.weight / total_w for s in applicable}                   # R19.10
    value    = sum(s.normalised_value * rescaled[s.name] for s in applicable)     # in [0, 1]
    if path == "metric_layer" and first_attempt_approve and grounded:
        value = max(value, high_band_lower_boundary)                              # R19.6
    band = band_of(value, confidence_band_boundaries)
    if voice_turn: value = min(value, transcription_confidence)                   # R28.13
    caution = weakest_applicable_signal(...) if band != "high" else None

Monotonicity (P14 / R19.12) holds because the score is a convex combination with non-negative
weights over an identical applicable signal set: raising any single normalised value cannot
lower the sum. The voice clamp is applied after banding on the raw score and re-banded, so the
clamp can never raise a band.

Pure logic; no database and no model call.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Band = Literal["low", "medium", "high"]

# The documented eight-signal set (Requirement 19.1). Order is significant: the caution
# tie-break resolves in favour of the signal appearing first here (Requirement 19.4).
SIGNAL_ORDER: tuple[str, ...] = (
    "template_match",
    "schema_linking_margin",
    "candidate_agreement",
    "reviewer_verdict",
    "repair_iterations",
    "row_count_sanity",
    "entity_resolution",
    "groundedness",
)

# The two signals that are applicable to every answered Turn (Requirement 19.11), so at
# least two signals always carry non-zero weight for a scored Turn.
MANDATORY_SIGNALS: frozenset[str] = frozenset({"reviewer_verdict", "groundedness"})


@dataclass(frozen=True)
class SignalInput:
    """One raw signal for a Turn.

    ``normalised_value`` is in the closed interval [0, 1] with 1 the strongest evidence of
    correctness. ``applicable`` is False when the pipeline stage that produces the signal did
    not run for the Turn (Requirement 19.10).
    """

    name: str
    applicable: bool
    normalised_value: float | None
    weight: float


@dataclass(frozen=True)
class SignalBreakdown:
    name: str
    applicable: bool
    normalised_value: float | None
    weight: float  # rescaled weight actually applied (R19.10)
    weighted_contribution: float | None


@dataclass
class ConfidenceOutcome:
    value: float
    band: Band
    signals: list[SignalBreakdown] = field(default_factory=list)
    caution_signal: str | None = None  # lowest weighted contribution when band != high


def band_of(value: float, boundaries: dict[str, float]) -> Band:
    """Map a score to a band using the configured lower boundaries.

    Boundaries default to ``{"medium": 0.50, "high": 0.80}``: ``low`` is [0, medium),
    ``medium`` is [medium, high), ``high`` is [high, 1] (Requirement 19.3).
    """
    if value >= boundaries["high"]:
        return "high"
    if value >= boundaries["medium"]:
        return "medium"
    return "low"


class ConfidenceScorer:
    def __init__(
        self,
        signal_weights: dict[str, float],
        band_boundaries: dict[str, float],
        acceptance_threshold: float = 0.60,
    ) -> None:
        self.signal_weights = signal_weights
        self.band_boundaries = band_boundaries
        self.acceptance_threshold = acceptance_threshold

    def score(
        self,
        signals: list[SignalInput],
        *,
        path: Literal["metric_layer", "generated_sql"] | None = None,
        first_attempt_approve: bool = False,
        grounded: bool = False,
        voice_turn: bool = False,
        transcription_confidence: float | None = None,
    ) -> ConfidenceOutcome:
        applicable = [s for s in signals if s.applicable and s.normalised_value is not None]

        # R19.11: reviewer_verdict and groundedness are applicable to every answered Turn.
        names = {s.name for s in applicable}
        missing = MANDATORY_SIGNALS - names
        if missing:
            raise ValueError(
                f"mandatory confidence signals not applicable: {sorted(missing)}"
            )

        total_w = sum(s.weight for s in applicable)
        if total_w <= 0:
            raise ValueError("applicable confidence signal weights sum to a non-positive value")

        # R19.10: rescale the weights of the applicable signals to sum to 1.
        rescaled: dict[str, float] = {s.name: s.weight / total_w for s in applicable}

        value = 0.0
        breakdown_by_name: dict[str, SignalBreakdown] = {}
        for s in applicable:
            w = rescaled[s.name]
            contribution = float(s.normalised_value) * w  # type: ignore[arg-type]
            value += contribution
            breakdown_by_name[s.name] = SignalBreakdown(
                name=s.name,
                applicable=True,
                normalised_value=s.normalised_value,
                weight=w,
                weighted_contribution=contribution,
            )

        # R19.6: Metric_Layer + first-attempt approve + grounded floors the score at high.
        if path == "metric_layer" and first_attempt_approve and grounded:
            value = max(value, self.band_boundaries["high"])

        # Clamp into [0, 1] against float error.
        value = max(0.0, min(1.0, value))

        band = band_of(value, self.band_boundaries)

        # R28.13: a voice Turn's transcription confidence is an upper bound; applied after
        # banding on the raw score and re-banded so the clamp can never raise a band.
        if voice_turn and transcription_confidence is not None:
            value = min(value, transcription_confidence)
            band = band_of(value, self.band_boundaries)

        # Assemble the full per-signal breakdown, including inapplicable signals (R19.5).
        breakdown: list[SignalBreakdown] = []
        for s in signals:
            if s.name in breakdown_by_name:
                breakdown.append(breakdown_by_name[s.name])
            else:
                breakdown.append(
                    SignalBreakdown(
                        name=s.name,
                        applicable=False,
                        normalised_value=s.normalised_value,
                        weight=0.0,
                        weighted_contribution=None,
                    )
                )

        # R19.4: caution names the applicable signal with the lowest weighted contribution,
        # ties resolved to the signal appearing first in the configured signal order.
        caution: str | None = None
        if band != "high":
            caution = self._weakest_signal(breakdown_by_name)

        return ConfidenceOutcome(
            value=value, band=band, signals=breakdown, caution_signal=caution
        )

    @staticmethod
    def _weakest_signal(applicable: dict[str, SignalBreakdown]) -> str | None:
        if not applicable:
            return None

        def order_index(name: str) -> int:
            return SIGNAL_ORDER.index(name) if name in SIGNAL_ORDER else len(SIGNAL_ORDER)

        # Lowest weighted contribution wins; ties -> first in SIGNAL_ORDER.
        best: SignalBreakdown | None = None
        for name in sorted(applicable, key=order_index):
            sb = applicable[name]
            if sb.weighted_contribution is None:
                continue
            if best is None or sb.weighted_contribution < best.weighted_contribution:  # type: ignore[operator]
                best = sb
        return best.name if best is not None else None
