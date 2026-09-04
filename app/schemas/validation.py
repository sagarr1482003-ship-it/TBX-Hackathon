"""SQL validation verdict contracts (design §4.3).

``AcceptVerdict.canonical_sql`` is the *only* text the ``Query_Executor`` will ever run
(Requirement 13.9 / Property 33). It is regenerated from the parsed AST, so the executor
never sees a model-authored string.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from app.schemas.enums import IntentFamily

RejectCategory = Literal[
    "parse_error",
    "statement_type",
    "multiple_statements",
    "unknown_identifier",
    "ambiguous_identifier",
    "function_not_allowlisted",
    "row_locking",
    "result_target",
    "node_type_not_allowlisted",
    "row_limit_too_large",
    "validation_timeout",
]


class AcceptVerdict(BaseModel):
    model_config = ConfigDict(frozen=True)

    canonical_sql: str
    parameters: dict[str, Any]
    referenced_tables: list[str]
    referenced_columns: list[str]
    applied_row_limit: int | None
    intent_family: IntentFamily
    validation_ms: float


class RejectVerdict(BaseModel):
    model_config = ConfigDict(frozen=True)

    reason: str
    category: RejectCategory
    guardrail_violation: bool = False


Verdict = AcceptVerdict | RejectVerdict
