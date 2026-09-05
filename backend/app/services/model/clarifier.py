"""Clarifier — decides up front whether a question is answerable or needs a follow-up (Req 18).

A vague or under-specified question ("show me the transactions", "how much did we spend") should
get ONE clarifying question rather than a guessed answer — this is the ambiguity/hallucination
guardrail. A small Strands agent classifies the question against the schema and returns either
PROCEED or CLARIFY with a single follow-up question.

Grounding intent: the clarifier only gates; it never produces figures. If it says PROCEED, the
normal generate -> validate -> review -> execute flow runs. If CLARIFY, the turn ends with a
clarifying question and no SQL is generated.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from strands import Agent

from app.services.model.groq_client import agent_text

_SYSTEM = """You decide whether a user's finance question can be answered from this schema, or
whether a key detail is missing and you must ask ONE short follow-up question first.

Schema:
  bank(bank_code, bank_name)
  account(account_id, entity_id, account_number, program_id, available_balance, bank_code)
  transaction(transaction_id, account_id, transaction_date, transaction_type['credit'|'debit'],
              description, transaction_amount, transaction_reference_id, utr_number)

Ask a follow-up ONLY when the question genuinely cannot be answered without more information —
for example it references data not in the schema, or it is too vague to turn into a single query
(missing which account/bank/period when that is essential). Aggregate questions over all data
(e.g. "total credit amount", "transactions per bank") are answerable — PROCEED.

Answer as exactly one of:
PROCEED
CLARIFY: <one short follow-up question>
"""


@dataclass
class ClarifyDecision:
    proceed: bool
    question: str | None = None  # the follow-up when proceed is False


def parse_decision(text: str) -> ClarifyDecision:
    t = text.strip()
    m = re.search(r"CLARIFY:\s*(.+)", t, re.IGNORECASE | re.DOTALL)
    if m:
        q = m.group(1).strip().split("\n")[0].strip()
        if q:
            return ClarifyDecision(proceed=False, question=q)
    # Default to proceeding unless an explicit, non-empty CLARIFY was given.
    return ClarifyDecision(proceed=True)


class Clarifier:
    def __init__(self, agent_factory) -> None:
        self._agent_factory = agent_factory

    @property
    def system_prompt(self) -> str:
        return _SYSTEM

    def decide(self, question: str) -> ClarifyDecision:
        agent: Agent = self._agent_factory()
        text = agent_text(agent, f"Question: {question}\nPROCEED or CLARIFY?")
        return parse_decision(text)
