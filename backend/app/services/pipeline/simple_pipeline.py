"""Minimal agent pipeline: generate -> validate -> review (first testable slice, on Strands).

Composes the Strands-backed SQL_Generator and Reviewer_Agent with the ALREADY-VERIFIED
SQL_Validator as the gate between them: nothing that is not a safe, schema-conformant SELECT ever
reaches the reviewer or execution. Execution, computation, grounding-on-live-results, trace
streaming and the session store are added next, once the Groq round-trip and latency are confirmed.

Per-stage wall-clock is measured so the whole-pipeline budget (< 10 s) is directly observable.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from app.services.ingestion.contract import SEED_CONTRACTS
from app.services.knowledge.schema_lookup import InMemorySchemaKB
from app.services.model.reviewer import ReviewerAgent, ReviewVerdict
from app.services.model.sql_generator import SqlCandidate, SqlGenerator
from app.services.pipeline.chart_spec import build_chart_spec
from app.services.pipeline.masking import mask_rows, sensitive_columns
from app.services.pipeline.sql_validator import SqlValidator

# The 3-table bank/account/transaction schema, for validator conformance checks (no DB needed).
SEED_SCHEMA: dict[str, list[str]] = {
    "bank": ["bank_code", "bank_name"],
    "account": [
        "account_id", "entity_id", "account_number", "program_id",
        "available_balance", "bank_code",
    ],
    "transaction": [
        "transaction_id", "account_id", "transaction_date", "transaction_type",
        "description", "transaction_amount", "transaction_reference_id", "utr_number",
    ],
}


@dataclass
class PipelineResult:
    question: str
    candidate: SqlCandidate | None = None
    validation_ok: bool = False
    validation_reason: str | None = None
    canonical_sql: str | None = None
    verdict: ReviewVerdict | None = None
    rows: list[dict] | None = None
    columns: list[str] | None = None
    total_row_count: int | None = None
    answer: str | None = None
    answer_source: str | None = None  # "llm" | "template" | "template_fallback"
    chart: dict | None = None  # ChartSpec.to_dict() when the result is chartable
    clarification: str | None = None  # follow-up question when the turn needs more info
    total_ms: int = 0
    stage_ms: dict[str, int] = field(default_factory=dict)

    @property
    def outcome(self) -> str:
        if self.clarification is not None:
            return "clarification_requested"
        if self.candidate is None:
            return "generation_failed"
        if not self.validation_ok:
            return "validation_rejected"
        if self.verdict is None:
            return "review_failed"
        if self.verdict.verdict != "approve":
            return self.verdict.verdict
        if self.answer is not None:
            return "answered"
        return "approve"


class SimplePipeline:
    def __init__(
        self,
        generator: SqlGenerator,
        reviewer: ReviewerAgent,
        *,
        intent_family: str = "transaction_lookup",
        executor=None,
        answer_composer=None,
    ) -> None:
        # The generator itself asks a follow-up when a question is under-specified (no separate
        # clarifier agent/call). executor(sql) -> (columns, rows) runs approved SQL read-only.
        self._generator = generator
        self._reviewer = reviewer
        self._validator = SqlValidator()
        self._schema = InMemorySchemaKB(SEED_SCHEMA)
        self._intent = intent_family
        self._executor = executor
        self._answer_composer = answer_composer
        self._sensitive = sensitive_columns(SEED_CONTRACTS)

    def run(self, question: str) -> PipelineResult:
        result = PipelineResult(question=question)
        t_start = time.monotonic()

        # 1) generate — the generator either returns SQL or asks ONE follow-up (same call).
        t0 = time.monotonic()
        try:
            candidate = self._generator.generate(question)
        except Exception as exc:  # generation failure -> no figure ever produced
            result.validation_reason = f"generation error: {exc}"
            result.total_ms = int((time.monotonic() - t_start) * 1000)
            return result
        result.candidate = candidate
        result.stage_ms["sql_generation"] = int((time.monotonic() - t0) * 1000)

        # Under-specified/out-of-scope -> the generator asked a follow-up; end the turn here.
        if candidate.clarification:
            result.clarification = candidate.clarification
            result.total_ms = int((time.monotonic() - t_start) * 1000)
            return result

        # 2) validate (security boundary — must pass before the reviewer sees it)
        t0 = time.monotonic()
        verdict = self._validator.validate(candidate.sql, self._schema, self._intent)  # type: ignore[arg-type]
        result.stage_ms["static_validation"] = int((time.monotonic() - t0) * 1000)
        canonical = getattr(verdict, "canonical_sql", None)
        if canonical is None:
            result.validation_ok = False
            result.validation_reason = getattr(verdict, "reason", "rejected")
            result.total_ms = int((time.monotonic() - t_start) * 1000)
            return result
        result.validation_ok = True
        result.canonical_sql = canonical

        # 3) review (independent model)
        t0 = time.monotonic()
        try:
            review = self._reviewer.review(question, canonical)
        except Exception as exc:
            result.validation_reason = f"reviewer error: {exc}"
            result.total_ms = int((time.monotonic() - t_start) * 1000)
            return result
        result.verdict = review
        result.stage_ms["reviewer_verdict"] = int((time.monotonic() - t0) * 1000)

        # 4) execute (read-only) + compose a simple grounded, masked answer
        if self._executor is not None and review.verdict == "approve":
            t0 = time.monotonic()
            try:
                result_tuple = self._executor(canonical)
            except Exception as exc:
                result.validation_reason = f"execution error: {exc}"
                result.total_ms = int((time.monotonic() - t_start) * 1000)
                return result
            # Executor returns (columns, rows) or (columns, rows, total_row_count). The rows are
            # already a bounded preview; total_row_count is the true count from the DB.
            if len(result_tuple) == 3:
                columns, rows, total = result_tuple
            else:
                columns, rows = result_tuple
                total = len(rows)
            masked = mask_rows(rows, self._sensitive)
            result.columns = columns
            result.total_row_count = total
            result.rows = masked[:100]  # rows are already a bounded preview from the executor
            # Chart spec from the preview rows (numeric values; labels are non-sensitive).
            spec = build_chart_spec(columns, rows)
            result.chart = spec.to_dict() if spec else None
            # LLM answer composer (Option A) with the deterministic template as grounded fallback.
            if self._answer_composer is not None:
                t1 = time.monotonic()
                try:
                    result.answer = self._answer_composer.compose(
                        question, columns, masked, total_rows=total
                    )
                    result.answer_source = "llm"
                except Exception:
                    result.answer = _compose_answer(question, columns, masked, total_rows=total)
                    result.answer_source = "template_fallback"
                result.stage_ms["answer_composition"] = int((time.monotonic() - t1) * 1000)
            else:
                result.answer = _compose_answer(question, columns, masked, total_rows=total)
                result.answer_source = "template"
            result.stage_ms["execution"] = int((time.monotonic() - t0) * 1000)

        result.total_ms = int((time.monotonic() - t_start) * 1000)
        return result


def _compose_answer(
    question: str, columns: list[str], rows: list[dict], total_rows: int | None = None
) -> str:
    """A minimal deterministic answer from executed rows (LLM does not touch numbers).

    Single scalar -> state it directly; otherwise summarise the TRUE total row count (from the
    DB) and show the top preview rows.
    """
    if not rows:
        return "No records match your question."
    if len(rows) == 1 and len(columns) == 1:
        col = columns[0]
        return f"{rows[0][col]}"
    if len(rows) == 1:
        pairs = ", ".join(f"{c} = {rows[0][c]}" for c in columns)
        return pairs
    total = total_rows if total_rows is not None else len(rows)
    head = rows[:5]
    lines = [", ".join(f"{c}={r[c]}" for c in columns) for r in head]
    more = f" (showing 5 of {total})" if total > 5 else ""
    return f"{total} rows{more}:\n" + "\n".join(lines)
