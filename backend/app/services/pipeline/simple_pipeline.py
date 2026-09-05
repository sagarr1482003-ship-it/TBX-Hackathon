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

from app.services.knowledge.schema_lookup import InMemorySchemaKB
from app.services.model.reviewer import ReviewerAgent, ReviewVerdict
from app.services.model.sql_generator import SqlCandidate, SqlGenerator
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
    total_ms: int = 0
    stage_ms: dict[str, int] = field(default_factory=dict)

    @property
    def outcome(self) -> str:
        if self.candidate is None:
            return "generation_failed"
        if not self.validation_ok:
            return "validation_rejected"
        if self.verdict is None:
            return "review_failed"
        return self.verdict.verdict


class SimplePipeline:
    def __init__(
        self,
        generator: SqlGenerator,
        reviewer: ReviewerAgent,
        *,
        intent_family: str = "transaction_lookup",
    ) -> None:
        self._generator = generator
        self._reviewer = reviewer
        self._validator = SqlValidator()
        self._schema = InMemorySchemaKB(SEED_SCHEMA)
        self._intent = intent_family

    def run(self, question: str) -> PipelineResult:
        result = PipelineResult(question=question)
        t_start = time.monotonic()

        # 1) generate
        t0 = time.monotonic()
        try:
            candidate = self._generator.generate(question)
        except Exception as exc:  # generation failure -> no figure ever produced
            result.validation_reason = f"generation error: {exc}"
            result.total_ms = int((time.monotonic() - t_start) * 1000)
            return result
        result.candidate = candidate
        result.stage_ms["sql_generation"] = int((time.monotonic() - t0) * 1000)

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

        result.total_ms = int((time.monotonic() - t_start) * 1000)
        return result
