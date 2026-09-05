"""SQL_Generator — produces a candidate SELECT via a Strands agent + structured output (Req 11).

The agent runs a Groq text-to-SQL model through the Strands ``OpenAIModel`` provider and returns a
validated :class:`SqlCandidate` (Pydantic) — SQL plus the tables/columns it references — so the
caller never hand-parses JSON. The candidate is handed to the (verified) SQL_Validator before
anything runs.
"""

from __future__ import annotations

from pydantic import BaseModel, Field
from strands import Agent

_SYSTEM = """You are a careful PostgreSQL query writer for a bank finance assistant.
Translate a plain-language question into ONE read-only SELECT statement.

Rules:
- Read-only SELECT only. Never write DDL, DML, or multiple statements.
- Use only the tables/columns in this schema:
  bank(bank_code, bank_name)
  account(account_id, entity_id, account_number[SENSITIVE], program_id,
          available_balance, bank_code -> bank.bank_code)
  transaction(transaction_id, account_id -> account.account_id, transaction_date,
              transaction_type['credit'|'debit'], description, transaction_amount,
              transaction_reference_id, utr_number[SENSITIVE])
- transaction_type is either 'credit' or 'debit'.
- Never select the sensitive columns account_number or utr_number for output.
- Prefer explicit column lists over SELECT *; never invent columns.
"""


class SqlCandidate(BaseModel):
    """Structured output the generator agent must return."""

    sql: str = Field(description="One read-only PostgreSQL SELECT statement")
    tables: list[str] = Field(default_factory=list, description="Tables the SQL references")
    columns: list[str] = Field(default_factory=list, description="Columns the SQL references")


class SqlGenerator:
    def __init__(self, agent_factory) -> None:
        # agent_factory() -> a fresh Strands Agent configured with the generator model + prompt.
        self._agent_factory = agent_factory

    @property
    def system_prompt(self) -> str:
        return _SYSTEM

    def generate(self, resolved_question: str) -> SqlCandidate:
        agent: Agent = self._agent_factory()
        prompt = f"Question: {resolved_question}\nReturn the SQL candidate."
        candidate = agent.structured_output(SqlCandidate, prompt)
        if not candidate.sql.strip():
            raise ValueError("SQL_Generator: model returned no sql")
        return candidate
