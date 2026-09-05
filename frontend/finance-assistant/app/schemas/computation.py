"""Computation-layer contracts (design §4.3).

Money is ``Decimal`` end to end; ``float`` never touches a monetary value. A computation
record is emitted for every figure released to the user (Requirement 15.3) and carries the
unrounded value (Requirement 15.5) so the groundedness checker can match at full precision.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict

UndefinedReason = Literal[
    "zero_denominator",
    "zero_or_negative_base",
    "zero_row_aggregate",
    "mixed_currency",
]

ValueType = Literal["monetary", "count", "percentage", "date", "text"]


class ComputationRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str  # "c1", "c2" — cited from answer text (Requirement 16.3)
    label: str
    value: Decimal | None  # None when withheld (Requirement 15.8, 15.11)
    unrounded_value: Decimal | None
    unit: str | None = None
    currency: str | None = None
    source_column: str | None = None
    query_id: str
    aggregated_row_count: int = 0
    null_excluded_row_count: int = 0
    undefined_reason: UndefinedReason | None = None
    operands: dict[str, Decimal] | None = None  # released when a figure is withheld


class BreakdownColumn(BaseModel):
    model_config = ConfigDict(frozen=True)

    label: str
    value_type: ValueType
    currency: str | None = None
