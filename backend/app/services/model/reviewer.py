"""Reviewer_Agent — an independent Strands agent returns a structured verdict (Req 14).

Runs a DIFFERENT Groq model from the generator (``REVIEWER_MODEL``) — satisfying the
reviewer-independence intent of Requirement 14.15 — and returns a validated
:class:`ReviewVerdict` (approve / repair / reject with a reason and defect category) via Strands
structured output.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field

from app.services.model.groq_client import call_with_fallback

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

For GST/tax, cash-flow, or anomaly questions, the correct query returns the RAW aggregate
(e.g. SUM(transaction_amount)) — a downstream deterministic tool computes GST / net flow /
z-scores from it. Do NOT require the SQL to multiply by a tax rate or compute those itself;
approve a correct raw aggregate for such questions.

Return your answer as exactly two lines:
VERDICT: approve | repair | reject
REASON: <short justification, one line>
"""


class ReviewVerdict(BaseModel):
    """Parsed reviewer verdict."""

    verdict: Literal["approve", "repair", "reject"]
    reason: str = Field(default="")
    defect_category: str | None = None


def parse_verdict(text: str) -> ReviewVerdict:
    """Parse the reviewer's two-line text response into a verdict."""
    verdict = "reject"
    m = re.search(r"VERDICT:\s*(approve|repair|reject)", text, re.IGNORECASE)
    if m:
        verdict = m.group(1).lower()
    reason = ""
    r = re.search(r"REASON:\s*(.+)", text, re.IGNORECASE)
    if r:
        reason = r.group(1).strip()[:500]
    return ReviewVerdict(
        verdict=verdict,  # type: ignore[arg-type]
        reason=reason,
        defect_category=None if verdict == "approve" else (reason[:60] or "unspecified"),
    )


class ReviewerAgent:
    def __init__(self, agent_factory, fallback_factory=None) -> None:
        self._agent_factory = agent_factory
        self._fallback_factory = fallback_factory
        self.last_usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}

    @property
    def system_prompt(self) -> str:
        return _SYSTEM

    def review(self, resolved_question: str, candidate_sql: str) -> ReviewVerdict:
        prompt = (
            f"Question: {resolved_question}\nCandidate SQL:\n{candidate_sql}\n"
            "Give your VERDICT and REASON."
        )
        text, self.last_usage = call_with_fallback(
            self._agent_factory, self._fallback_factory, prompt
        )
        return parse_verdict(text)
