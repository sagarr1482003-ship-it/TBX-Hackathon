"""Golden question entry contract (design §4.3, Requirement 26.2).

One entry declares a question, optional preceding conversation turns (submitted in order,
only the last scored), the expected behaviour class, and — for ``answer`` entries — the
expected result set or figure, expected columns, and whether row order is significant.

Pure Pydantic contract; no database and no model call.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, model_validator

from app.schemas.enums import AbstentionReason


class GoldenEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    question: str
    context_turns: list[str] = []  # submitted in order, only the last is scored (R26.10)
    expected_behaviour: Literal["answer", "clarify", "abstain"]
    expected_reason_code: AbstentionReason | None = None
    expected_columns: list[str] = []
    expected_rows: list[dict[str, Any]] | None = None
    expected_figure: Decimal | None = None
    row_order_significant: bool = False
    acceptable_date_range: tuple[date, date] | None = None
    tagged_metric: str | None = None
    dataset_version: str

    @model_validator(mode="after")
    def _check_shape(self) -> GoldenEntry:
        if self.expected_behaviour == "answer":
            # An answer entry must declare its expected columns so the comparator can restrict
            # comparison to them (Requirement 26.3).
            if not self.expected_columns and self.expected_figure is None:
                raise ValueError(
                    f"golden entry {self.id!r} of class 'answer' must declare "
                    "expected_columns or an expected_figure"
                )
        else:
            # clarify / abstain entries must declare the expected reason code.
            if self.expected_reason_code is None:
                raise ValueError(
                    f"golden entry {self.id!r} of class {self.expected_behaviour!r} "
                    "must declare expected_reason_code"
                )
        if self.acceptable_date_range is not None:
            start, end = self.acceptable_date_range
            if start > end:
                raise ValueError(
                    f"golden entry {self.id!r} acceptable_date_range has start > end"
                )
        return self
