"""Computation_Layer — the deterministic, non-LLM arithmetic path (Requirement 15).

Every filter, grouping, aggregation, ratio, difference and percentage change is computed
here in typed Python over executed result rows, using ``Decimal`` throughout. Rounding
happens only at formatting time, half away from zero, and the unrounded value is recorded.

The language model never performs arithmetic; :func:`template_answer` is the deterministic
sentence generator the composer falls back to (Requirement 17.4), and the reason a
grounded answer still exists with no provider configured.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from app.schemas.computation import BreakdownColumn, ComputationRecord

Row = dict[str, Any]


def _to_decimal(value: Any) -> Decimal | None:
    """Coerce a cell to Decimal, or None if it is NULL. Never uses float."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):  # guard: bool is an int subclass
        raise TypeError("boolean is not a monetary value")
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, str):
        return Decimal(value)
    if isinstance(value, float):
        # A float on a monetary path is a bug. Convert via str to avoid binary artefacts,
        # but this should not happen on money — callers pass Decimal/int/str.
        return Decimal(str(value))
    raise TypeError(f"cannot convert {type(value).__name__} to Decimal")


def round_half_away(value: Decimal, places: int) -> Decimal:
    """Round ``value`` to ``places`` decimal places, half away from zero.

    ``ROUND_HALF_UP`` in Python's ``decimal`` rounds halves away from zero (not toward
    positive infinity), which is exactly the requirement.
    """
    quant = Decimal(1).scaleb(-places)  # 10**-places as a Decimal
    return value.quantize(quant, rounding=ROUND_HALF_UP)


def aggregate_sum(
    rows: Iterable[Row],
    column: str,
    *,
    record_id: str,
    query_id: str,
    label: str,
    currency: str | None = None,
    unit: str | None = None,
) -> ComputationRecord:
    """Sum a column over the complete result set, excluding and counting NULL rows.

    A zero-row aggregation releases no figure and records a zero-row outcome distinct from
    a computed value of zero (Requirement 15.11).
    """
    total = Decimal(0)
    aggregated = 0
    null_excluded = 0
    for row in rows:
        cell = row.get(column)
        dec = _to_decimal(cell)
        if dec is None:
            null_excluded += 1
            continue
        total += dec
        aggregated += 1

    if aggregated == 0:
        return ComputationRecord(
            id=record_id,
            label=label,
            value=None,
            unrounded_value=None,
            unit=unit,
            currency=currency,
            source_column=column,
            query_id=query_id,
            aggregated_row_count=0,
            null_excluded_row_count=null_excluded,
            undefined_reason="zero_row_aggregate",
        )

    return ComputationRecord(
        id=record_id,
        label=label,
        value=total,
        unrounded_value=total,
        unit=unit,
        currency=currency,
        source_column=column,
        query_id=query_id,
        aggregated_row_count=aggregated,
        null_excluded_row_count=null_excluded,
    )


def aggregate_sum_by_currency(
    rows: Iterable[Row],
    column: str,
    currency_column: str,
    *,
    record_id_prefix: str,
    query_id: str,
    label: str,
) -> list[ComputationRecord]:
    """Per-currency sum records when an aggregation spans more than one currency.

    When the contributing rows carry more than one distinct currency, the combined figure
    is withheld and one record is emitted per distinct currency (Requirement 15.12). When
    a single currency is present, a single ordinary sum record is returned.
    """
    buckets: dict[str, list[Row]] = {}
    for row in rows:
        cur = row.get(currency_column)
        buckets.setdefault(str(cur), []).append(row)

    currencies = sorted(buckets)
    if len(currencies) <= 1:
        cur = currencies[0] if currencies else None
        return [
            aggregate_sum(
                buckets.get(cur, []) if cur is not None else [],
                column,
                record_id=f"{record_id_prefix}1",
                query_id=query_id,
                label=label,
                currency=cur,
            )
        ]

    records: list[ComputationRecord] = []
    for i, cur in enumerate(currencies, start=1):
        rec = aggregate_sum(
            buckets[cur],
            column,
            record_id=f"{record_id_prefix}{i}",
            query_id=query_id,
            label=f"{label} ({cur})",
            currency=cur,
        )
        # Mark that the combined figure was withheld because of mixed currency.
        records.append(
            rec.model_copy(update={"undefined_reason": rec.undefined_reason or "mixed_currency"})
            if rec.value is None
            else rec.model_copy(update={"undefined_reason": None})
        )
    return records


def ratio(
    numerator: Decimal,
    denominator: Decimal,
    *,
    record_id: str,
    query_id: str,
    label: str,
) -> ComputationRecord:
    """Compute a ratio, withholding it (with operands released) on a zero denominator."""
    if denominator == 0:
        return ComputationRecord(
            id=record_id,
            label=label,
            value=None,
            unrounded_value=None,
            unit="ratio",
            query_id=query_id,
            undefined_reason="zero_denominator",
            operands={"numerator": numerator, "denominator": denominator},
        )
    value = numerator / denominator
    return ComputationRecord(
        id=record_id,
        label=label,
        value=value,
        unrounded_value=value,
        unit="ratio",
        query_id=query_id,
        operands={"numerator": numerator, "denominator": denominator},
    )


def percentage_change(
    base: Decimal,
    comparison: Decimal,
    *,
    record_id: str,
    query_id: str,
    label: str,
) -> ComputationRecord:
    """Percentage change from ``base`` to ``comparison``.

    * both zero -> recorded as 0 percent (Requirement 15.9);
    * base zero or below zero -> withheld with operands released (Requirement 15.8).
    """
    if base == 0 and comparison == 0:
        return ComputationRecord(
            id=record_id,
            label=label,
            value=Decimal(0),
            unrounded_value=Decimal(0),
            unit="percent",
            query_id=query_id,
            operands={"base": base, "comparison": comparison},
        )
    if base <= 0:
        return ComputationRecord(
            id=record_id,
            label=label,
            value=None,
            unrounded_value=None,
            unit="percent",
            query_id=query_id,
            undefined_reason="zero_or_negative_base",
            operands={"base": base, "comparison": comparison},
        )
    value = (comparison - base) / base * Decimal(100)
    return ComputationRecord(
        id=record_id,
        label=label,
        value=value,
        unrounded_value=value,
        unit="percent",
        query_id=query_id,
        operands={"base": base, "comparison": comparison},
    )


def difference(
    base: Decimal,
    comparison: Decimal,
    *,
    record_id: str,
    query_id: str,
    label: str,
    currency: str | None = None,
) -> ComputationRecord:
    """Absolute difference ``comparison - base`` (never withheld)."""
    value = comparison - base
    return ComputationRecord(
        id=record_id,
        label=label,
        value=value,
        unrounded_value=value,
        currency=currency,
        query_id=query_id,
        operands={"base": base, "comparison": comparison},
    )


def total_ordering_key(
    ordering_columns: Sequence[str], grouping_keys: Sequence[str]
) -> list[str]:
    """The single total ordering used by preview, retained snapshot and export.

    Formed from the executed query's ordering columns followed by every grouping key not
    already among those ordering columns, in ascending order (Requirement 15.6).
    """
    order = list(ordering_columns)
    extra = sorted(k for k in grouping_keys if k not in order)
    return order + extra


def order_rows(
    rows: Sequence[Row], ordering_columns: Sequence[str], grouping_keys: Sequence[str]
) -> list[Row]:
    """Return rows in the single total ordering (stable)."""
    keys = total_ordering_key(ordering_columns, grouping_keys)
    if not keys:
        return list(rows)

    def sort_key(row: Row) -> tuple:
        return tuple(_sortable(row.get(k)) for k in keys)

    return sorted(rows, key=sort_key)


def _sortable(value: Any) -> tuple:
    """Type-stable sort key: (type_rank, comparable). None sorts first, then by type."""
    if value is None:
        return (0, "")
    if isinstance(value, bool):
        return (1, int(value))
    if isinstance(value, (int, float, Decimal)):
        return (2, Decimal(str(value)) if not isinstance(value, Decimal) else value)
    return (3, str(value))


def preview(
    ordered_rows: Sequence[Row], preview_row_limit: int
) -> tuple[list[Row], int]:
    """Return (previewed rows up to the limit, total row count).

    Aggregates are computed from the complete result set, not from the preview
    (Requirement 15.7).
    """
    total = len(ordered_rows)
    return list(ordered_rows[:preview_row_limit]), total


def format_monetary(value: Decimal, places: int = 2) -> str:
    """Format a monetary Decimal to a fixed-precision string (never via float)."""
    return str(round_half_away(value, places))


def format_percentage(value: Decimal, places: int) -> str:
    return str(round_half_away(value, places))


def infer_breakdown_columns(
    rows: Sequence[Row],
    monetary_columns: Sequence[str] = (),
    count_columns: Sequence[str] = (),
    percentage_columns: Sequence[str] = (),
    date_columns: Sequence[str] = (),
    currency: str | None = None,
) -> list[BreakdownColumn]:
    """Build breakdown column descriptors for the columns present in the rows."""
    if not rows:
        return []
    cols: list[BreakdownColumn] = []
    for name in rows[0].keys():
        if name in monetary_columns:
            cols.append(BreakdownColumn(label=name, value_type="monetary", currency=currency))
        elif name in count_columns:
            cols.append(BreakdownColumn(label=name, value_type="count"))
        elif name in percentage_columns:
            cols.append(BreakdownColumn(label=name, value_type="percentage"))
        elif name in date_columns:
            cols.append(BreakdownColumn(label=name, value_type="date"))
        else:
            cols.append(BreakdownColumn(label=name, value_type="text"))
    return cols


def template_answer(
    records: Sequence[ComputationRecord],
    *,
    resolved_question: str | None = None,
    date_range: tuple[str, str] | None = None,
    currency: str | None = None,
    display_precision: int = 2,
) -> str:
    """Deterministic sentence generator (Requirement 17.4).

    Builds a plain-language answer from computation records only, citing each record id and
    formatting every figure through the Computation_Layer. No model call. Every numeral in
    the output is drawn from a record's value, so the result is groundedness-clean by
    construction.
    """
    parts: list[str] = []
    for rec in records:
        if rec.value is None:
            parts.append(
                f"{rec.label} could not be computed "
                f"({rec.undefined_reason or 'undefined'}) [{rec.id}]."
            )
            continue
        if rec.unit == "percent":
            figure = f"{format_percentage(rec.value, display_precision)}%"
        elif rec.currency:
            figure = f"{rec.currency} {format_monetary(rec.value, display_precision)}"
        elif rec.unit == "ratio":
            figure = format_percentage(rec.value, display_precision)
        else:
            # count / plain numeric
            figure = str(rec.value)
        parts.append(f"{rec.label} is {figure} [{rec.id}].")

    sentence = " ".join(parts) if parts else "No figure is available for this question."
    if date_range is not None:
        sentence += f" Period: {date_range[0]} to {date_range[1]}."
    return sentence
