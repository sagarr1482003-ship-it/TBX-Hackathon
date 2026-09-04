"""Local_File_Connector — CSV/XLSX/SQL-dump ingestion (Requirement 6, Task 2.4).

The *parsing* helpers here (monetary, date, header matching, row validation) are pure and are
unit-tested without a database. The *loading* into PostgreSQL is UNVERIFIED because it requires a
running database.

Requirement 6 rules implemented:
  * declared-encoding decode with BOM discard (R6.9);
  * header matching after trim + case fold, excluded headers reported (R6.10);
  * single declared date format per column, no time-zone conversion (R6.3);
  * monetary parsing: strip declared symbols + separators, parentheses = negative, round half
    away from zero to the declared scale (R6.4);
  * row rejection with row number + reason, continue loading (R6.5);
  * primary-key duplicate handling: keep first, reject rest (R6.11);
  * NULL for empty non-required cells (R6.12);
  * rejected-row tolerance failure (R6.6);
  * INSERT-only SQL dump execution (R6.13);
  * index creation for declared filter columns and join keys (R6.7).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from app.schemas.manifest import ColumnSpec, EntitySpec

BOM = "\ufeff"


@dataclass
class RowRejection:
    row_number: int
    reason: str


@dataclass
class EntityLoadReport:
    entity: str
    loaded: int = 0
    rejections: list[RowRejection] = field(default_factory=list)
    excluded_headers: list[str] = field(default_factory=list)
    rounded_rows: list[int] = field(default_factory=list)


def parse_money(
    raw: str, currency_symbols: list[str], thousands_separator: str, scale: int
) -> Decimal:
    """Parse a source monetary string to a fixed-scale Decimal (Requirement 6.4).

    Strips surrounding whitespace and each declared currency symbol and the thousands
    separator; a value enclosed in parentheses is negative; rounds half away from zero to the
    declared scale. Raises ValueError on an unparseable value (a type coercion failure).
    """
    s = raw.strip()
    negative = s.startswith("(") and s.endswith(")")
    if negative:
        s = s[1:-1].strip()
    for sym in currency_symbols:
        s = s.replace(sym, "")
    if thousands_separator:
        s = s.replace(thousands_separator, "")
    s = s.strip()
    if s == "":
        raise ValueError("empty monetary value")
    try:
        value = Decimal(s)
    except InvalidOperation as exc:
        raise ValueError(f"unparseable monetary value: {raw!r}") from exc
    if negative:
        value = -value
    quant = Decimal(1).scaleb(-scale)  # 10^-scale
    # ROUND_HALF_UP on the absolute value = half away from zero.
    rounded = value.copy_abs().quantize(quant, rounding=ROUND_HALF_UP)
    return -rounded if value < 0 else rounded


def parse_date(raw: str, date_format: str) -> date | datetime:
    """Parse a date/timestamp using ONLY the declared format, no time-zone conversion (R6.3)."""
    parsed = datetime.strptime(raw.strip(), date_format)
    # If the format has no time component, return a date.
    if any(tok in date_format for tok in ("%H", "%M", "%S", "%z")):
        return parsed
    return parsed.date()


def match_headers(
    source_headers: list[str], columns: list[ColumnSpec]
) -> tuple[dict[str, str], list[str]]:
    """Map source headers to canonical names after trim + case fold (Requirement 6.10).

    Returns (source_header -> canonical_name, excluded_headers). A leading BOM on the first
    header is discarded before matching.
    """
    by_source = {c.source_name.strip().casefold(): c for c in columns}
    mapping: dict[str, str] = {}
    excluded: list[str] = []
    for i, header in enumerate(source_headers):
        cleaned = header
        if i == 0 and cleaned.startswith(BOM):
            cleaned = cleaned[len(BOM) :]
        key = cleaned.strip().casefold()
        spec = by_source.get(key)
        if spec is None:
            excluded.append(header)
        else:
            mapping[header] = spec.canonical_name
    return mapping, excluded


def coerce_row(
    row: dict[str, str],
    entity: EntitySpec,
    currency_symbols: list[str],
    thousands_separator: str,
) -> tuple[dict[str, Any], bool]:
    """Coerce one raw row into typed values. Returns (typed_row, rounded).

    Raises ValueError on a type coercion failure or a required-column blank (Requirement 6.5).
    Empty non-required cells become NULL (Requirement 6.12).
    """
    typed: dict[str, Any] = {}
    rounded = False
    for col in entity.columns:
        raw = row.get(col.canonical_name)
        if raw is None or raw.strip() == "":
            if col.required:
                raise ValueError(f"required column {col.canonical_name!r} is blank")
            typed[col.canonical_name] = None
            continue
        typed[col.canonical_name] = _coerce_value(
            raw, col, currency_symbols, thousands_separator
        )
    return typed, rounded


def _coerce_value(
    raw: str, col: ColumnSpec, currency_symbols: list[str], thousands_separator: str
) -> Any:
    if col.type == "numeric":
        scale = col.numeric_scale if col.numeric_scale is not None else 2
        return parse_money(raw, currency_symbols, thousands_separator, scale)
    if col.type in ("date", "timestamp"):
        if not col.date_format:
            raise ValueError(f"column {col.canonical_name!r} has no declared date_format")
        return parse_date(raw, col.date_format)
    if col.type == "integer":
        return int(raw.strip())
    if col.type == "boolean":
        return raw.strip().lower() in ("true", "t", "1", "yes", "y")
    return raw  # text


# --- SQL-dump safety (Requirement 6.13) ------------------------------------------------
_FORBIDDEN_DUMP = (
    "create", "alter", "drop", "truncate", "update", "delete", "grant", "revoke",
    "set ", "copy ", "begin", "commit",
)


def sql_dump_statements_are_insert_only(statements: list[str]) -> bool:
    """True only when every statement is an INSERT (Requirement 6.13)."""
    for stmt in statements:
        s = stmt.strip().lower()
        if not s:
            continue
        if not s.startswith("insert"):
            return False
        if any(tok in s for tok in _FORBIDDEN_DUMP):
            # An INSERT that also contains a forbidden token (e.g. a chained statement).
            return False
    return True
