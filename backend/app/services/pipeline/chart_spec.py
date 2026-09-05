"""Chart spec builder — a deterministic visualization hint for the answer response.

When an executed result set is a simple grouping (one label column + one numeric column), we emit a
``ChartSpec`` the frontend can render as a pie / bar / line chart alongside the plain-text answer.
No LLM call and no extra latency: the chart data is exactly the executed rows, so every charted
value is as grounded as the answer itself.

Type selection (deterministic):
  * a date/month/time label  -> ``line`` (a trend);
  * <= 6 distinct labels      -> ``pie`` (a share-of-total);
  * otherwise                 -> ``bar``.

Returns ``None`` when the result is not chartable (no single label+value shape, e.g. a scalar
count or a wide record listing).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from decimal import Decimal
from typing import Any

_MAX_POINTS = 20
_PIE_MAX_SLICES = 6
_DATE_HINTS = ("date", "month", "day", "week", "year", "period", "quarter")


@dataclass
class ChartPoint:
    label: str
    value: float


@dataclass
class ChartSpec:
    type: str  # "pie" | "bar" | "line"
    label_field: str
    value_field: str
    points: list[ChartPoint] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _is_numeric(v: Any) -> bool:
    return isinstance(v, (int, float, Decimal)) and not isinstance(v, bool)


def build_chart_spec(columns: list[str], rows: list[dict]) -> ChartSpec | None:
    """Return a ChartSpec when the result is a single label+value grouping, else None."""
    if not rows or len(columns) != 2 or len(rows) < 2:
        return None

    # Identify which column is the numeric value and which is the label.
    c0, c1 = columns
    first = rows[0]
    if _is_numeric(first.get(c1)) and not _is_numeric(first.get(c0)):
        label_field, value_field = c0, c1
    elif _is_numeric(first.get(c0)) and not _is_numeric(first.get(c1)):
        label_field, value_field = c1, c0
    else:
        return None  # not a clean label+value shape

    points: list[ChartPoint] = []
    for r in rows[:_MAX_POINTS]:
        val = r.get(value_field)
        if not _is_numeric(val):
            return None
        points.append(ChartPoint(label=str(r.get(label_field)), value=float(val)))

    lower = label_field.lower()
    if any(h in lower for h in _DATE_HINTS):
        chart_type = "line"
    elif len(points) <= _PIE_MAX_SLICES:
        chart_type = "pie"
    else:
        chart_type = "bar"

    return ChartSpec(
        type=chart_type, label_field=label_field, value_field=value_field, points=points
    )
