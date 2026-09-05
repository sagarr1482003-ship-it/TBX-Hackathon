"""Evaluation_Harness result-set comparator (Requirement 26.3).

The comparator is the correctness heart of the harness: a bug here would silently invalidate
every number in the deck. It is a *pure* function of ``(expected, actual, declarations)`` so it
is exhaustively property-testable with no database. Requirement 26.3's match rule:

- a match requires a row count identical to the expected row count;
- comparison is restricted to the declared expected column names;
- numeric values match when they differ by at most 0.01;
- text values match after case folding and after removal of leading and trailing whitespace;
- a null value is matched only by a null value;
- row sequence must be identical to the expected sequence for entries declaring row order
  significant, and is ignored for every other entry;
- an entry of class ``answer`` for which the backend returns a clarifying question or an
  abstention scores as a non-match (handled by the harness, which calls
  :func:`compare_result_sets` only when the backend returned an answer).

The rest of the harness (running the golden set, scoring aggregate metrics, persisting runs)
is database- and provider-backed and lives outside this pure module.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

NUMERIC_TOLERANCE = Decimal("0.01")


def _to_decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, str):
        try:
            return Decimal(value.replace(",", "").strip())
        except InvalidOperation:
            return None
    return None


def cells_match(expected: Any, actual: Any) -> bool:
    """Compare two cells under the Requirement 26.3 rule.

    NULL matches only NULL. Numerics match within 0.01. Text matches after trim + case fold.
    Two values that are both numeric-looking are compared numerically; otherwise as text.
    """
    exp_null = expected is None
    act_null = actual is None
    if exp_null or act_null:
        return exp_null and act_null  # null matched only by null

    exp_dec = _to_decimal(expected)
    act_dec = _to_decimal(actual)
    if exp_dec is not None and act_dec is not None:
        return abs(exp_dec - act_dec) <= NUMERIC_TOLERANCE

    # text comparison
    return _fold(expected) == _fold(actual)


def _fold(value: Any) -> str:
    return str(value).strip().casefold()


def compare_result_sets(
    expected_rows: list[dict[str, Any]],
    actual_rows: list[dict[str, Any]],
    expected_columns: list[str],
    *,
    row_order_significant: bool = False,
) -> bool:
    """Return True when ``actual_rows`` matches ``expected_rows`` per Requirement 26.3."""
    # Row count must be identical.
    if len(expected_rows) != len(actual_rows):
        return False

    columns = expected_columns
    if not columns:
        # No declared columns: compare over the union of expected keys (defensive default).
        columns = sorted({k for row in expected_rows for k in row})

    if row_order_significant:
        for exp, act in zip(expected_rows, actual_rows):
            for col in columns:
                if not cells_match(exp.get(col), act.get(col)):
                    return False
        return True

    # Order-insensitive: find a bijection between expected and actual rows where each pair
    # matches cell-wise within tolerance (Requirement 26.3). A quantised multiset would split
    # values sitting either side of a tolerance-grid boundary, so we match greedily against the
    # true per-cell rule instead. Result sets here are small (golden-set scale).
    unmatched_actual = list(range(len(actual_rows)))
    for exp in expected_rows:
        found = -1
        for pos, act_idx in enumerate(unmatched_actual):
            act = actual_rows[act_idx]
            if all(cells_match(exp.get(col), act.get(col)) for col in columns):
                found = pos
                break
        if found < 0:
            return False
        unmatched_actual.pop(found)
    return not unmatched_actual


def figure_matches(expected: Decimal, actual: Any) -> bool:
    """Scalar-figure match under the 0.01 numeric tolerance (Requirement 26.3)."""
    act = _to_decimal(actual)
    if act is None:
        return False
    return abs(expected - act) <= NUMERIC_TOLERANCE
