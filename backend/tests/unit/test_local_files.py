"""Local_File_Connector pure-parsing verification (Task 2.4, Requirement 6.4/6.9/6.10/6.13).

Only the pure parsing helpers are exercised here; the database-writing load path is unverified
(needs PostgreSQL). The monetary parser is the load-bearing one: it must strip declared symbols
and separators, read parentheses as negative, and round half away from zero to the declared scale.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from app.schemas.manifest import ColumnSpec
from app.services.ingestion.local_files import (
    BOM,
    match_headers,
    parse_date,
    parse_money,
    sql_dump_statements_are_insert_only,
)

_SYMBOLS = ["\u20b9", "Rs.", "INR"]


def test_parse_money_basic() -> None:
    assert parse_money("\u20b91,234.50", _SYMBOLS, ",", 2) == Decimal("1234.50")
    assert parse_money("INR 1,000", _SYMBOLS, ",", 2) == Decimal("1000.00")


def test_parse_money_parentheses_negative() -> None:
    assert parse_money("(\u20b92,500.00)", _SYMBOLS, ",", 2) == Decimal("-2500.00")


def test_parse_money_half_away_from_zero() -> None:
    # 1.005 rounds to 1.01 (half away from zero), not banker's 1.00.
    assert parse_money("1.005", _SYMBOLS, ",", 2) == Decimal("1.01")
    assert parse_money("-1.005", _SYMBOLS, ",", 2) == Decimal("-1.01")


def test_parse_money_rejects_garbage() -> None:
    import pytest

    with pytest.raises(ValueError):
        parse_money("not-a-number", _SYMBOLS, ",", 2)


def test_parse_date_no_time_returns_date() -> None:
    assert parse_date("2024-03-15", "%Y-%m-%d") == date(2024, 3, 15)


def test_parse_date_with_time_returns_datetime() -> None:
    result = parse_date("2024-03-15T12:00:00", "%Y-%m-%dT%H:%M:%S")
    assert isinstance(result, datetime)
    assert result.year == 2024 and result.hour == 12


def test_match_headers_trims_casefolds_and_discards_bom() -> None:
    cols = [
        ColumnSpec(source_name="Vendor ID", canonical_name="vendor_id", type="text"),
        ColumnSpec(source_name="Amount", canonical_name="amount", type="numeric"),
    ]
    headers = [f"{BOM}  vendor id ", "AMOUNT", "extra_col"]
    mapping, excluded = match_headers(headers, cols)
    assert mapping[f"{BOM}  vendor id "] == "vendor_id"
    assert mapping["AMOUNT"] == "amount"
    assert excluded == ["extra_col"]


def test_sql_dump_insert_only() -> None:
    assert sql_dump_statements_are_insert_only(
        ["INSERT INTO finance.vendors VALUES ('V1','Acme');", ""]
    )
    assert not sql_dump_statements_are_insert_only(
        ["INSERT INTO x VALUES (1);", "DROP TABLE finance.vendors;"]
    )
    assert not sql_dump_statements_are_insert_only(["UPDATE finance.vendors SET x=1;"])
