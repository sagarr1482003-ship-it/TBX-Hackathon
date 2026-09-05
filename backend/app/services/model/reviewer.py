"""Reviewer_Agent — an independent Strands agent returns a structured verdict (Req 14).

Runs a DIFFERENT Groq model from the generator (``REVIEWER_MODEL``) — satisfying the
reviewer-independence intent of Requirement 14.15 — and returns a validated
:class:`ReviewVerdict` (approve / repair / reject with a reason and defect category) via Strands
structured output.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field
from strands import Agent

_SYSTEM = """You are a meticulous reviewer of PostgreSQL queries for a bank finance assistant.
Given a question and a candidate SELECT, decide whether it correctly and safely answers the
question. Check tables/columns, aggregation and grouping, filters and date range, join
cardinality, read-only, and that sensitive columns (account_number, utr_number) are not selected.

Schema:
  bank(bank_code, bank_name)
  account(account_id, entity_id, account_number[SENSITIVE], program_id,
          available_balance, bank_code)
  transaction(transaction_id, account_id, transaction_date, transaction_type['credit'|'debit'],
              description, transaction_amount, transaction_reference_id, utr_number[SENSITIVE])

Return the verdict object. Use 'approve' only when the query is correct and safe.
"""


class ReviewVerdict(BaseModel):
    """Structured output the reviewer agent must return."""

    verdict: Literal["approve", "repair", "reject"]
    reason: str = Field(description="Short justification, <= 500 chars")
    defect_category: str | None = Field(
        default=None, description="Defect category when verdict is repair or reject"
    )


class ReviewerAgent:
    def __init__(self, agent_factory) -> None:
        self._agent_factory = agent_factory

    @property
    def system_prompt(self) -> str:
        return _SYSTEM

    def review(self, resolved_question: str, candidate_sql: str) -> ReviewVerdict:
        agent: Agent = self._agent_factory()
        prompt = (
            f"Question: {resolved_question}\nCandidate SQL:\n{candidate_sql}\n"
            "Return the verdict object."
        )
        verdict = agent.structured_output(ReviewVerdict, prompt)
        # Trim an over-long reason defensively.
        if len(verdict.reason) > 500:
            verdict = verdict.model_copy(update={"reason": verdict.reason[:500]})
        return verdict
