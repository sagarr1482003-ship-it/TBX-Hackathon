"""Comparator property test (Task 11.3, Requirement 26.3).

The Evaluation_Harness comparator is the correctness heart of the harness; a bug here would
silently invalidate every number in the deck. Properties:

- reflexive on itself;
- insensitive to row order unless row order is declared significant;
- tolerant at exactly 0.01 and intolerant above it;
- NULL matched only by NULL;
- restricted to the declared expected columns.

Pure logic; no database and no model call.
"""

from __future__ import annotations

from decimal import Decimal

from hypothesis import given
from hypothesis import strategies as st

from app.services.ops.evaluation import (
    NUMERIC_TOLERANCE,
    cells_match,
    compare_result_sets,
    figure_matches,
)

_COLS = ["vendor", "amount"]


@st.composite
def result_set(draw):
    n = draw(st.integers(min_value=0, max_value=8))
    rows = []
    for _ in range(n):
        vendor = draw(st.sampled_from(["Acme", "Globex", "Initech", None]))
        amount = draw(
            st.one_of(
                st.none(),
                st.integers(min_value=0, max_value=1_000_000).map(lambda i: Decimal(i)),
            )
        )
        rows.append({"vendor": vendor, "amount": amount})
    return rows


@given(rows=result_set())
def test_reflexive(rows) -> None:
    assert compare_result_sets(rows, rows, _COLS) is True


@given(rows=result_set())
def test_order_insensitive_by_default(rows) -> None:
    reordered = list(reversed(rows))
    assert compare_result_sets(rows, reordered, _COLS) is True


@given(rows=result_set())
def test_order_sensitive_when_declared(rows) -> None:
    reordered = list(reversed(rows))
    # When order matters and the reversal actually changes the sequence, it must not match.
    if _row_seq(rows) != _row_seq(reordered):
        assert (
            compare_result_sets(rows, reordered, _COLS, row_order_significant=True) is False
        )


def _row_seq(rows):
    return [(r["vendor"], r["amount"]) for r in rows]


def test_tolerance_boundary() -> None:
    exp = [{"vendor": "Acme", "amount": Decimal("100.00")}]
    at = [{"vendor": "Acme", "amount": Decimal("100.00") + NUMERIC_TOLERANCE}]
    above = [{"vendor": "Acme", "amount": Decimal("100.02")}]
    assert compare_result_sets(exp, at, _COLS) is True
    assert compare_result_sets(exp, above, _COLS) is False


def test_null_matched_only_by_null() -> None:
    exp = [{"vendor": "Acme", "amount": None}]
    null_ok = [{"vendor": "Acme", "amount": None}]
    zero = [{"vendor": "Acme", "amount": Decimal(0)}]
    assert compare_result_sets(exp, null_ok, _COLS) is True
    assert compare_result_sets(exp, zero, _COLS) is False
    # and the reverse: a value never matches a NULL
    assert cells_match(Decimal(0), None) is False
    assert cells_match(None, None) is True


def test_restricted_to_declared_columns() -> None:
    # An undeclared column difference must be ignored.
    exp = [{"vendor": "Acme", "amount": Decimal(100), "note": "x"}]
    act = [{"vendor": "Acme", "amount": Decimal(100), "note": "COMPLETELY DIFFERENT"}]
    assert compare_result_sets(exp, act, ["vendor", "amount"]) is True
    # But a declared column difference must be caught.
    assert compare_result_sets(exp, act, ["vendor", "amount", "note"]) is False


def test_text_case_and_whitespace_folding() -> None:
    exp = [{"vendor": "Acme Corp", "amount": Decimal(1)}]
    act = [{"vendor": "  acme corp  ", "amount": Decimal(1)}]
    assert compare_result_sets(exp, act, _COLS) is True


def test_row_count_mismatch_never_matches() -> None:
    exp = [{"vendor": "Acme", "amount": Decimal(1)}]
    act = [
        {"vendor": "Acme", "amount": Decimal(1)},
        {"vendor": "Acme", "amount": Decimal(1)},
    ]
    assert compare_result_sets(exp, act, _COLS) is False


@given(
    base=st.integers(min_value=0, max_value=1_000_000),
    delta=st.decimals(min_value="0", max_value="1", places=3, allow_nan=False),
)
def test_figure_matches_tolerance(base, delta) -> None:
    exp = Decimal(base)
    actual = exp + delta
    expected_match = delta <= NUMERIC_TOLERANCE
    assert figure_matches(exp, actual) == expected_match
