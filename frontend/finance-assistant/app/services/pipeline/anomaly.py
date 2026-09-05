"""Anomaly_Detector — a documented deterministic outlier rule over an entity's own history
(Requirement 20), following the design's ``evaluate()`` pseudocode.

The rule has two branches:

* **modified z-score** — ``z = 0.6745 * (value - median) / MAD``; flag when ``z`` exceeds the
  configured threshold (default 3.5). Median and MAD are both homogeneous of degree 1, so
  flags are invariant under multiplying every amount by a positive constant (Property 16).
* **zero-dispersion** — when ``MAD == 0`` the z-score is undefined, so a value is flagged only
  when ``value - median`` exceeds *both* ``zero_dispersion_relative_threshold * |median|`` and
  ``zero_dispersion_absolute_floor``. Scale invariance holds here only if the absolute floor is
  scaled with the amounts — exactly what Property 16's test does.

Ordering (Requirement 20.4): modified-z flags first, ordered by ``z`` descending; then
zero-dispersion flags, ordered by ``value - median`` descending; ties broken by ascending
entity identifier; at most three callouts released.

All arithmetic is ``Decimal`` (Requirement 20.5). The *rule* here is a pure function of an
entity's numeric history; the entity-history *retrieval* through the Query_Executor and the
budget/time-limit skip (Requirement 20.8/20.10) are the database-backed wrapper that the
orchestrator supplies — kept out of this pure core so Property 16 runs with no database.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

_Q = Decimal("0.6745")

FlagKind = Literal["modified_z", "zero_dispersion"]
SkipReason = Literal[
    "insufficient_history",
    "zero_dispersion_within_threshold",
    "budget_or_time_limit_reached",
]


@dataclass(frozen=True)
class AnomalyFlag:
    entity_id: str
    value: Decimal
    median: Decimal
    kind: FlagKind
    z_score: Decimal | None = None  # set for modified_z
    relative_difference: Decimal | None = None  # set for zero_dispersion


def median(values: list[Decimal]) -> Decimal:
    """Median of a non-empty list of Decimals (average of the two middle values if even)."""
    if not values:
        raise ValueError("median of empty sequence")
    s = sorted(values)
    n = len(s)
    mid = n // 2
    if n % 2 == 1:
        return s[mid]
    return (s[mid - 1] + s[mid]) / Decimal(2)


def median_absolute_deviation(values: list[Decimal], med: Decimal) -> Decimal:
    """MAD = median(|x - median|)."""
    return median([abs(x - med) for x in values])


def modified_z_score(value: Decimal, med: Decimal, mad: Decimal) -> Decimal:
    """0.6745 * (value - median) / MAD. Caller must ensure MAD != 0."""
    return _Q * (value - med) / mad


@dataclass(frozen=True)
class AnomalyConfig:
    z_threshold: Decimal = Decimal("3.5")
    min_history_count: int = 6
    zero_dispersion_relative_threshold: Decimal = Decimal("0.20")
    zero_dispersion_absolute_floor: Decimal = Decimal("1000")
    max_callouts: int = 3


def evaluate_entity(
    entity_id: str,
    value: Decimal,
    history: list[Decimal],
    config: AnomalyConfig,
) -> AnomalyFlag | SkipReason:
    """Apply the deterministic rule to one entity. Pure function.

    ``history`` must already exclude the value under evaluation (Requirement 20.8). Returns an
    :class:`AnomalyFlag` when flagged, else the machine-readable skip reason.
    """
    if len(history) < config.min_history_count:
        return "insufficient_history"

    med = median(history)
    mad = median_absolute_deviation(history, med)

    if mad == 0:
        diff = value - med
        rel_ok = diff > config.zero_dispersion_relative_threshold * abs(med)
        abs_ok = diff > config.zero_dispersion_absolute_floor
        if rel_ok and abs_ok:
            rel = (diff / abs(med)) if med != 0 else None
            return AnomalyFlag(
                entity_id=entity_id,
                value=value,
                median=med,
                kind="zero_dispersion",
                relative_difference=rel,
            )
        return "zero_dispersion_within_threshold"

    z = modified_z_score(value, med, mad)
    if z > config.z_threshold:
        return AnomalyFlag(
            entity_id=entity_id, value=value, median=med, kind="modified_z", z_score=z
        )
    # Evaluated with non-zero dispersion but not flagged.
    return "zero_dispersion_within_threshold"


def order_and_cap(flags: list[AnomalyFlag], config: AnomalyConfig) -> list[AnomalyFlag]:
    """Order flags per Requirement 20.4 and cap at ``max_callouts``.

    modified_z first by z desc; then zero_dispersion by (value - median) desc; ties within
    each group broken by ascending entity identifier.
    """
    modified = [f for f in flags if f.kind == "modified_z"]
    zero_disp = [f for f in flags if f.kind == "zero_dispersion"]

    modified.sort(key=lambda f: (-(f.z_score or Decimal(0)), f.entity_id))
    zero_disp.sort(key=lambda f: (-(f.value - f.median), f.entity_id))

    return (modified + zero_disp)[: config.max_callouts]


@dataclass
class AnomalyOutcome:
    evaluated: bool
    flags: list[AnomalyFlag]
    skips: dict[str, SkipReason]


def evaluate(
    entity_values: dict[str, Decimal],
    entity_histories: dict[str, list[Decimal]],
    config: AnomalyConfig,
    *,
    budget_ok: bool = True,
) -> AnomalyOutcome:
    """Evaluate a set of entities against their histories. Pure core of ``evaluate()``.

    ``budget_ok`` False models the Requirement 20.10 skip (budget/time limit reached): the
    whole Turn is skipped and zero flags returned.
    """
    if not budget_ok:
        return AnomalyOutcome(evaluated=False, flags=[], skips={})

    flags: list[AnomalyFlag] = []
    skips: dict[str, SkipReason] = {}
    for entity_id in sorted(entity_values):
        value = entity_values[entity_id]
        history = entity_histories.get(entity_id, [])
        result = evaluate_entity(entity_id, value, history, config)
        if isinstance(result, AnomalyFlag):
            flags.append(result)
        else:
            skips[entity_id] = result

    return AnomalyOutcome(evaluated=True, flags=order_and_cap(flags, config), skips=skips)
