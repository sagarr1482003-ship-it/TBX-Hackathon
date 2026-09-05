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
    computed_metrics: dict = field(default_factory=dict)  # GST/cashflow/anomaly tool outputs
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
        max_plan_cost: float | None = None,
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
        self._max_plan_cost = max_plan_cost
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

    async def run_stream(self, question: str, history: list | None = None):
        """Async generator yielding per-stage trace events for SSE (realtime FE traces).

        Each event is a dict: {"event": <stage>, "data": {...}}. Stages fire in order —
        intake, sql_generation, (clarification | static_validation, reviewer_verdict, execution,
        answer_composition), completion — so the frontend can render the pipeline live and drive
        filler speech. The synchronous model/DB calls run in a worker thread so events flush
        between stages instead of blocking the event loop.
        """
        import asyncio

        result = PipelineResult(question=question)
        t_start = time.monotonic()

        def _elapsed() -> int:
            return int((time.monotonic() - t_start) * 1000)

        def ev(stage, status, kind, detail, ms=None):
            """One trace event. kind: 'llm_tool_call' | 'deterministic_guardrail' | 'db' | 'io'.
            The FE renders the pipeline from (stage, status, kind, duration_ms, elapsed_ms, detail).
            ``elapsed_ms`` = time since request start; the first event's elapsed_ms is the TTFT."""
            e = int((time.monotonic() - t_start) * 1000)
            if timing["ttft_ms"] is None:
                timing["ttft_ms"] = e  # first event emitted = time to first token/event
            if (
                stage == "answer_composition"
                and status == "ok"
                and timing["first_answer_ms"] is None
            ):
                timing["first_answer_ms"] = e
            return {
                "event": stage,
                "data": {
                    "stage": stage,
                    "status": status,       # start | ok | error | skipped | rejected
                    "kind": kind,
                    "duration_ms": ms,
                    "elapsed_ms": e,
                    "detail": detail,
                },
            }

        timing = {"ttft_ms": None, "first_answer_ms": None}

        tokens = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "llm_calls": 0}

        def add_usage(u: dict) -> dict:
            """Accumulate an LLM call's usage into the running total; return the call's usage."""
            u = u or {}
            tokens["input_tokens"] += int(u.get("input_tokens", 0) or 0)
            tokens["output_tokens"] += int(u.get("output_tokens", 0) or 0)
            tokens["total_tokens"] += int(u.get("total_tokens", 0) or 0)
            tokens["llm_calls"] += 1
            return u

        yield ev("intake", "ok", "io", {"question": question, "chars": len(question)})

        # 1) generate (or clarify) — LLM tool call: SQL_Generator (Strands agent on Groq).
        yield ev("sql_generation", "start", "llm_tool_call",
                 {"role": "sql_generator", "model": self._model_id("sql_generator")})
        t = time.monotonic()
        try:
            candidate = await asyncio.to_thread(self._generator.generate, question, history)
        except Exception as exc:
            result.validation_reason = f"generation error: {exc}"
            result.total_ms = _elapsed()
            yield ev("sql_generation", "error", "llm_tool_call", {"error": str(exc)[:200]})
            yield {"event": "completion", "data": _stream_payload(question, result, tokens, timing)}
            return
        gen_ms = int((time.monotonic() - t) * 1000)
        result.candidate = candidate
        gen_usage = add_usage(getattr(self._generator, "last_usage", None))

        if candidate.clarification:
            result.clarification = candidate.clarification
            result.total_ms = _elapsed()
            yield ev("clarification", "ok", "deterministic_guardrail",
                     {"guardrail": "ambiguity_check", "question": candidate.clarification,
                      "usage": gen_usage}, gen_ms)
            yield {"event": "completion", "data": _stream_payload(question, result, tokens, timing)}
            return
        yield ev("sql_generation", "ok", "llm_tool_call",
                 {"sql": candidate.sql, "usage": gen_usage}, gen_ms)

        # 2) SQL_Validator — deterministic security guardrail (the boundary).
        yield ev("static_validation", "start", "deterministic_guardrail",
                 {"guardrail": "sql_ast_validator"})
        t = time.monotonic()
        verdict = self._validator.validate(candidate.sql, self._schema, self._intent)  # type: ignore[arg-type]
        val_ms = int((time.monotonic() - t) * 1000)
        canonical = getattr(verdict, "canonical_sql", None)
        if canonical is None:
            result.validation_ok = False
            result.validation_reason = getattr(verdict, "reason", "rejected")
            result.total_ms = _elapsed()
            yield ev("static_validation", "rejected", "deterministic_guardrail",
                     {"guardrail": "sql_ast_validator", "reason": result.validation_reason,
                      "category": getattr(verdict, "category", None)}, val_ms)
            yield {"event": "completion", "data": _stream_payload(question, result, tokens, timing)}
            return
        result.validation_ok = True
        result.canonical_sql = canonical
        # The concrete guardrail checks that passed — for the FE to show each gate green.
        yield ev("static_validation", "ok", "deterministic_guardrail", {
            "guardrail": "sql_ast_validator",
            "canonical_sql": canonical,
            "checks_passed": [
                "read_only_select", "schema_conformant", "no_ddl_dml",
                "no_forbidden_functions", "row_limit_applied",
            ],
            "referenced_tables": getattr(verdict, "tables", None),
        }, val_ms)

        # 3) Reviewer_Agent — independent LLM tool call.
        yield ev("reviewer_verdict", "start", "llm_tool_call",
                 {"role": "reviewer", "model": self._model_id("reviewer")})
        t = time.monotonic()
        try:
            review = await asyncio.to_thread(self._reviewer.review, question, canonical)
        except Exception as exc:
            result.validation_reason = f"reviewer error: {exc}"
            result.total_ms = _elapsed()
            yield ev("reviewer_verdict", "error", "llm_tool_call", {"error": str(exc)[:200]})
            yield {"event": "completion", "data": _stream_payload(question, result, tokens, timing)}
            return
        rev_ms = int((time.monotonic() - t) * 1000)
        result.verdict = review
        rev_usage = add_usage(getattr(self._reviewer, "last_usage", None))
        yield ev("reviewer_verdict", "ok", "llm_tool_call",
                 {"verdict": review.verdict, "reason": review.reason, "usage": rev_usage}, rev_ms)

        # 4) execute + compose
        if self._executor is not None and review.verdict == "approve":
            # 4a) EXPLAIN cost gate — deterministic guardrail: reject a runaway plan pre-execution.
            explain_cost = getattr(self._executor, "explain_cost", None)
            if explain_cost is not None and self._max_plan_cost is not None:
                yield ev("plan_inspection", "start", "deterministic_guardrail",
                         {"guardrail": "explain_cost_gate", "max_plan_cost": self._max_plan_cost})
                t = time.monotonic()
                try:
                    cost = await asyncio.to_thread(explain_cost, canonical)
                except Exception as exc:
                    cost = None
                    plan_detail = {"guardrail": "explain_cost_gate", "error": str(exc)[:150]}
                    yield ev("plan_inspection", "error", "deterministic_guardrail", plan_detail,
                             int((time.monotonic() - t) * 1000))
                if cost is not None:
                    plan_ms = int((time.monotonic() - t) * 1000)
                    if cost > self._max_plan_cost:
                        result.validation_ok = False
                        result.validation_reason = (
                            f"query plan cost {cost:.0f} exceeds limit {self._max_plan_cost:.0f}"
                        )
                        result.total_ms = _elapsed()
                        yield ev("plan_inspection", "rejected", "deterministic_guardrail",
                                 {"guardrail": "explain_cost_gate", "cost": cost,
                                  "max_plan_cost": self._max_plan_cost}, plan_ms)
                        yield {
                            "event": "completion",
                            "data": _stream_payload(question, result, tokens, timing),
                        }
                        return
                    yield ev("plan_inspection", "ok", "deterministic_guardrail",
                             {"guardrail": "explain_cost_gate", "cost": cost,
                              "max_plan_cost": self._max_plan_cost}, plan_ms)

            # Query_Executor — read-only DB guardrail (tbx_reader, statement timeout, row cap).
            yield ev("execution", "start", "db",
                     {"guardrail": "read_only_executor", "sql": canonical})
            t = time.monotonic()
            try:
                result_tuple = await asyncio.to_thread(self._executor, canonical)
            except Exception as exc:
                result.validation_reason = f"execution error: {exc}"
                result.total_ms = _elapsed()
                yield ev("execution", "error", "db", {"error": str(exc)[:200]})
                yield {
                    "event": "completion",
                    "data": _stream_payload(question, result, tokens, timing),
                }
                return
            exec_ms = int((time.monotonic() - t) * 1000)
            if len(result_tuple) == 3:
                columns, rows, total = result_tuple
            else:
                columns, rows = result_tuple
                total = len(rows)
            # PII decrypt-on-read + masking guardrail.
            masked = mask_rows(rows, self._sensitive)
            result.columns = columns
            result.total_row_count = total
            result.rows = masked[:100]
            spec = build_chart_spec(columns, rows)
            result.chart = spec.to_dict() if spec else None
            yield ev("execution", "ok", "db", {
                "row_count": total,
                "preview_rows": len(masked[:100]),
                "chart": result.chart,
                "guardrails_applied": ["read_only", "bounded_fetch", "pii_mask"],
                "masked_columns": sorted(self._sensitive),
            }, exec_ms)

            # Deterministic calculator tools (GST / cash-flow / anomaly) — run in Python over the
            # full result rows, ALWAYS (independent of the LLM), so the figures are grounded and
            # present even if the composer call fails. The LLM only phrases them afterwards.
            from app.services.model.answer_composer import AnswerComposer

            t = time.monotonic()
            result.computed_metrics = AnswerComposer._run_calculators(question, columns, masked)
            if result.computed_metrics:
                yield ev("computation", "ok", "deterministic_guardrail",
                         {"tools": list(result.computed_metrics.keys()),
                          "computed_metrics": result.computed_metrics},
                         int((time.monotonic() - t) * 1000))

            # Answer_Composer — LLM tool call, grounded by the checker.
            yield ev("answer_composition", "start", "llm_tool_call",
                     {"role": "composer", "model": self._model_id("composer")})
            t = time.monotonic()
            if self._answer_composer is not None:
                try:
                    result.answer = await asyncio.to_thread(
                        self._answer_composer.compose, question, columns, masked, total
                    )
                    result.answer_source = "llm"
                except Exception:
                    result.answer = _compose_answer(question, columns, masked, total_rows=total)
                    result.answer_source = "template_fallback"
            else:
                result.answer = _compose_answer(question, columns, masked, total_rows=total)
                result.answer_source = "template"
            comp_ms = int((time.monotonic() - t) * 1000)
            comp_usage = add_usage(getattr(self._answer_composer, "last_usage", None)) \
                if (self._answer_composer and result.answer_source == "llm") else {}
            yield ev("answer_composition", "ok", "llm_tool_call",
                     {"answer": result.answer, "answer_source": result.answer_source,
                      "usage": comp_usage, "computed_metrics": result.computed_metrics}, comp_ms)

        result.total_ms = _elapsed()
        yield {"event": "completion", "data": _stream_payload(question, result, tokens, timing)}

    def _model_id(self, role: str) -> str | None:
        """Best-effort model id for a role, for the trace (None if not resolvable)."""
        try:
            from app.config import get_settings

            s = get_settings()
            return {
                "sql_generator": s.sql_generator_model,
                "reviewer": s.reviewer_model,
                "composer": s.composer_model,
            }.get(role)
        except Exception:
            return None


def _stream_payload(
    question: str, r: "PipelineResult", tokens: dict | None = None, timing: dict | None = None
) -> dict:
    """The terminal SSE payload — the same shape the JSON CLI/endpoint returns."""
    timing = timing or {}
    return {
        "question": question,
        "outcome": r.outcome,
        "clarification": r.clarification,
        "resolved_sql": r.canonical_sql,
        "answer_text": r.answer,
        "answer_source": r.answer_source,
        "chart": r.chart,
        "computed_metrics": r.computed_metrics,
        "ttft_ms": timing.get("ttft_ms"),
        "first_answer_ms": timing.get("first_answer_ms"),
        "token_usage": tokens or {
            "input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "llm_calls": 0
        },
        "verdict": (
            {"verdict": r.verdict.verdict, "reason": r.verdict.reason} if r.verdict else None
        ),
        "breakdown": {
            "columns": r.columns,
            "rows": r.rows,
            "total_row_count": r.total_row_count,
        },
        "validation_ok": r.validation_ok,
        "validation_reason": r.validation_reason,
        "total_ms": r.total_ms,
    }


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
