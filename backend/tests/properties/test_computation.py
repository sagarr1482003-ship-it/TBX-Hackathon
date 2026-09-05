"""Properties 4 and 18 (task 7.2).

Property 4 — every released aggregate, ratio, difference and percentage change equals an
independent reference computation over the same rows, with NULL rows excluded and counted.
Property 18 — breakdown rows sum to the reported total at the recorded precision, with no
binary float anywhere in the path.

Pure Decimal arithmetic; no database.
"""

from __future__ import annotations

from decimal import Decimal
from fractions import Fraction

from hypothesis import given
from hypothesis import strategies as st

from app.services.pipeline.computation import (
    aggregate_sum,
    difference,
    percentage_change,
    ratio,
    round_half_away,
)


def _round_fraction(frac: Fraction, places: int) -> Decimal:
    """Round an exact Fraction to ``places`` places, half away from zero, as Decimal."""
    scale = 10**places
    scaled = frac * scale  # exact
    sign = 1 if scaled >= 0 else -1
    magnitude = scaled if scaled >= 0 else -scaled
    floor = magnitude.numerator // magnitude.denominator
    frac_part = magnitude - floor
    if frac_part >= Fraction(1, 2):
        floor += 1
    rounded = sign * floor
    return Decimal(rounded) / Decimal(scale)

# Decimals with up to 2 fractional places, bounded so sums stay exact and readable.
_money = st.decimals(
    min_value=Decimal("-1000000"),
    max_value=Decimal("1000000"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)

# A row list where some cells are NULL (None) on the aggregated column.
@st.composite
def rows_with_nulls(draw) -> list[dict]:
    n = draw(st.integers(min_value=0, max_value=40))
    rows = []
    for _ in range(n):
        if draw(st.booleans()):
            rows.append({"amount": None})
        else:
            rows.append({"amount": draw(_money)})
    return rows


@given(rows=rows_with_nulls())
def test_property4_sum_matches_reference_with_null_counts(rows: list[dict]) -> None:
    rec = aggregate_sum(rows, "amount", record_id="c1", query_id="q1", label="Total")

    # Independent reference using exact Fraction arithmetic (no float, no Decimal reuse).
    non_null = [r["amount"] for r in rows if r["amount"] is not None]
    ref_total = sum((Fraction(str(v)) for v in non_null), Fraction(0))
    ref_aggregated = len(non_null)
    ref_null = len(rows) - ref_aggregated

    assert rec.null_excluded_row_count == ref_null
    if ref_aggregated == 0:
        # Zero-row outcome is distinct from a computed zero.
        assert rec.value is None
        assert rec.undefined_reason == "zero_row_aggregate"
        assert rec.aggregated_row_count == 0
    else:
        assert rec.aggregated_row_count == ref_aggregated
        assert rec.value is not None
        assert Fraction(str(rec.value)) == ref_total
        # unrounded value is preserved
        assert rec.unrounded_value == rec.value


@given(num=_money, den=_money)
def test_property4_ratio_matches_reference_or_withholds(num: Decimal, den: Decimal) -> None:
    rec = ratio(num, den, record_id="c1", query_id="q1", label="Ratio")
    if den == 0:
        assert rec.value is None
        assert rec.undefined_reason == "zero_denominator"
        assert rec.operands == {"numerator": num, "denominator": den}
    else:
        assert rec.value is not None
        # Decimal division is finite-precision by design (the layer rounds only at
        # formatting). Compare the released figure to the exact reference rounded to the
        # display precision.
        ref = Fraction(str(num)) / Fraction(str(den))
        assert round_half_away(rec.value, 2) == _round_fraction(ref, 2)


@given(base=_money, comp=_money)
def test_property4_percentage_change_rules(base: Decimal, comp: Decimal) -> None:
    rec = percentage_change(base, comp, record_id="c1", query_id="q1", label="Change")
    if base == 0 and comp == 0:
        assert rec.value == Decimal(0)
    elif base <= 0:
        assert rec.value is None
        assert rec.undefined_reason == "zero_or_negative_base"
    else:
        assert rec.value is not None
        ref = (Fraction(str(comp)) - Fraction(str(base))) / Fraction(str(base)) * 100
        assert round_half_away(rec.value, 2) == _round_fraction(ref, 2)


@given(base=_money, comp=_money)
def test_property4_difference_matches_reference(base: Decimal, comp: Decimal) -> None:
    rec = difference(base, comp, record_id="c1", query_id="q1", label="Diff")
    assert Fraction(str(rec.value)) == Fraction(str(comp)) - Fraction(str(base))


# ---- Property 18: breakdown rows sum to the reported total in exact decimals ---------
@st.composite
def grouped_rows(draw) -> list[dict]:
    n = draw(st.integers(min_value=1, max_value=30))
    return [{"group": draw(st.integers(0, 5)), "amount": draw(_money)} for _ in range(n)]


@given(rows=grouped_rows())
def test_property18_breakdown_rows_sum_to_total(rows: list[dict]) -> None:
    # Build a per-group breakdown, each group's total a computation record.
    groups: dict[int, list[dict]] = {}
    for r in rows:
        groups.setdefault(r["group"], []).append(r)

    group_records = [
        aggregate_sum(g_rows, "amount", record_id=f"c{i}", query_id="q1", label=f"g{gid}")
        for i, (gid, g_rows) in enumerate(sorted(groups.items()), start=1)
    ]
    grand = aggregate_sum(rows, "amount", record_id="ctot", query_id="q1", label="Total")

    # Sum of group totals equals the grand total exactly (Decimal, never float).
    breakdown_sum = sum(
        (r.value for r in group_records if r.value is not None), Decimal(0)
    )
    assert breakdown_sum == (grand.value if grand.value is not None else Decimal(0))

    # Recorded-precision rounding of the sum matches rounding the total.
    assert round_half_away(breakdown_sum, 2) == round_half_away(
        grand.value if grand.value is not None else Decimal(0), 2
    )
    # No float ever appears in a value.
    for r in group_records + [grand]:
        assert r.value is None or isinstance(r.value, Decimal)


def test_round_half_away_from_zero() -> None:
    assert round_half_away(Decimal("2.005"), 2) == Decimal("2.01")
    assert round_half_away(Decimal("-2.005"), 2) == Decimal("-2.01")
    assert round_half_away(Decimal("2.5"), 0) == Decimal("3")
    assert round_half_away(Decimal("-2.5"), 0) == Decimal("-3")
