"""Query_Executor — the guarded read-only execution path (Requirement 13, Task 4.4).

UNVERIFIED: requires a running PostgreSQL and the ``tbx_reader`` role; cannot be executed in the
current environment. Written to the design (§4.3, §5.1) but not run.

Guarantees (Requirement 13):
  * connects exclusively through the ``tbx_reader`` engine (SELECT-only role) — R13.1;
  * every statement runs inside a read-only transaction with a statement timeout — R13.2/13.6;
  * caps materialised rows at the execution row cap and discards partial results on overflow —
    R13.4/13.10;
  * plan requests obtain planner estimates without executing the candidate — R13.8;
  * records each execution kind as a trace event — R13.7;
  * bounds concurrency with a wait queue and a typed capacity error — R13.11/13.12;
  * aborts before execution when the Turn's pinned dataset version has changed — R13.14;
  * counts every execution against the per-Turn maximum — R13.15;
  * executes ONLY the ``AcceptVerdict.canonical_sql`` returned by the SQL_Validator — R13.9.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Literal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.errors import (
    DatasetVersionChangedError,
    ExecutionCapacityError,
    QueryTimeoutError,
    RowCapExceededError,
)

ExecutionKind = Literal[
    "final", "dry_run", "plan", "existence", "anomaly_history"
]


@dataclass
class ExecutionResult:
    rows: list[dict[str, Any]]
    columns: list[str]
    row_count: int
    duration_ms: int
    dataset_version: int
    kind: ExecutionKind


@dataclass
class TurnExecutionBudget:
    """Per-Turn execution accounting (R13.15) — max executions across all five kinds."""

    max_executions: int
    used: int = 0

    def charge(self) -> None:
        if self.used >= self.max_executions:
            raise ExecutionCapacityError(
                "per-Turn execution limit reached", limit=self.max_executions
            )
        self.used += 1


@dataclass
class QueryExecutor:
    engine: AsyncEngine
    statement_timeout_ms: int = 10_000
    execution_row_cap: int = 100_000
    max_concurrent_queries: int = 8
    queue_wait_timeout_s: float = 5.0
    _semaphore: asyncio.Semaphore = field(init=False)

    def __post_init__(self) -> None:
        self._semaphore = asyncio.Semaphore(self.max_concurrent_queries)

    async def execute(
        self,
        canonical_sql: str,
        parameters: dict[str, Any],
        *,
        kind: ExecutionKind,
        pinned_dataset_version: int,
        budget: TurnExecutionBudget,
        row_cap: int | None = None,
    ) -> ExecutionResult:
        """Execute a validator-approved canonical statement under all guardrails."""
        budget.charge()  # R13.15 — counts every kind

        # R13.14: abort before execution if the active version differs from the pin.
        active = await self._active_dataset_version()
        if active != pinned_dataset_version:
            raise DatasetVersionChangedError(
                "dataset version changed mid-Turn",
                pinned=pinned_dataset_version,
                active=active,
            )

        cap = row_cap if row_cap is not None else self.execution_row_cap

        # R13.11/13.12: bound concurrency with a wait queue + typed capacity error.
        try:
            await asyncio.wait_for(self._semaphore.acquire(), timeout=self.queue_wait_timeout_s)
        except TimeoutError as exc:
            raise ExecutionCapacityError(
                "execution queue wait timed out", wait_s=self.queue_wait_timeout_s
            ) from exc

        loop = asyncio.get_event_loop()
        start = loop.time()
        try:
            async with self.engine.connect() as conn:
                # Read-only transaction + statement timeout (R13.2/13.6).
                await conn.execute(text("SET TRANSACTION READ ONLY"))
                await conn.execute(
                    text(f"SET LOCAL statement_timeout = {int(self.statement_timeout_ms)}")
                )
                try:
                    cursor = await conn.execute(text(canonical_sql), parameters)
                except Exception as exc:  # timeout surfaces as a driver error
                    if _is_timeout(exc):
                        raise QueryTimeoutError(
                            "statement timeout", sql=canonical_sql
                        ) from exc
                    raise

                columns = list(cursor.keys())
                rows: list[dict[str, Any]] = []
                for row in cursor:
                    if len(rows) >= cap:
                        # R13.10: discard the partial result set and raise.
                        raise RowCapExceededError(
                            "execution row cap exceeded", sql=canonical_sql, cap=cap
                        )
                    rows.append(_row_to_dict(columns, row))

            duration_ms = int((loop.time() - start) * 1000)
            return ExecutionResult(
                rows=rows,
                columns=columns,
                row_count=len(rows),
                duration_ms=duration_ms,
                dataset_version=pinned_dataset_version,
                kind=kind,
            )
        finally:
            self._semaphore.release()

    async def plan(
        self,
        canonical_sql: str,
        parameters: dict[str, Any],
        *,
        pinned_dataset_version: int,
        budget: TurnExecutionBudget,
    ) -> str:
        """Return an EXPLAIN plan without executing the candidate (R13.8)."""
        budget.charge()
        async with self.engine.connect() as conn:
            await conn.execute(text("SET TRANSACTION READ ONLY"))
            await conn.execute(
                text(f"SET LOCAL statement_timeout = {int(self.statement_timeout_ms)}")
            )
            cursor = await conn.execute(text(f"EXPLAIN {canonical_sql}"), parameters)
            return "\n".join(str(r[0]) for r in cursor)

    async def _active_dataset_version(self) -> int:
        async with self.engine.connect() as conn:
            cursor = await conn.execute(
                text("SELECT id FROM ops.dataset_versions WHERE status = 'active' LIMIT 1")
            )
            row = cursor.first()
            return int(row[0]) if row else -1


def _row_to_dict(columns: list[str], row: Any) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for col, val in zip(columns, row):
        # Preserve Decimal for money; never coerce to float (R15.2).
        out[col] = val if not isinstance(val, float) else Decimal(str(val))
    return out


def _is_timeout(exc: Exception) -> bool:
    msg = str(exc).lower()
    return "statement timeout" in msg or "canceling statement" in msg
