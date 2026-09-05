"""SQL_Generator — produces a candidate SELECT via a Strands agent + structured output (Req 11).

The agent runs a Groq text-to-SQL model through the Strands ``OpenAIModel`` provider and returns a
validated :class:`SqlCandidate` (Pydantic) — SQL plus the tables/columns it references — so the
caller never hand-parses JSON. The candidate is handed to the (verified) SQL_Validator before
anything runs.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field
from strands import Agent

from app.services.model.groq_client import agent_text

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
- Output ONLY the SQL statement. No prose, no explanation, no markdown fences.

Examples (question -> SQL):
Q: How many debit transactions are there?
SQL: SELECT count(*) FROM transaction WHERE transaction_type = 'debit'
Q: What is the total credit amount across all transactions?
SQL: SELECT sum(transaction_amount) FROM transaction WHERE transaction_type = 'credit'
Q: How many accounts does each bank have?
SQL: SELECT b.bank_name, count(*) AS account_count FROM account a JOIN bank b ON a.bank_code = b.bank_code GROUP BY b.bank_name ORDER BY account_count DESC
Q: Which account has the highest available balance?
SQL: SELECT account_id, available_balance FROM account ORDER BY available_balance DESC LIMIT 1
Q: Show the number of transactions per account.
SQL: SELECT account_id, count(*) AS txn_count FROM transaction GROUP BY account_id ORDER BY txn_count DESC
Q: What is the total transaction amount per bank?
SQL: SELECT b.bank_name, sum(t.transaction_amount) AS total FROM transaction t JOIN account a ON t.account_id = a.account_id JOIN bank b ON a.bank_code = b.bank_code GROUP BY b.bank_name ORDER BY total DESC
Q: Find the transaction with reference id S69244711.
SQL: SELECT transaction_id, transaction_date, transaction_type, transaction_amount, description FROM transaction WHERE transaction_reference_id = 'S69244711'
Q: How many transactions happened in each month?
SQL: SELECT date_trunc('month', transaction_date) AS month, count(*) AS txn_count FROM transaction GROUP BY month ORDER BY month
"""


class SqlCandidate(BaseModel):
    """The generator's parsed candidate (SQL only; tables/columns derived by the validator)."""

    sql: str = Field(description="One read-only PostgreSQL SELECT statement")
    tables: list[str] = Field(default_factory=list)
    columns: list[str] = Field(default_factory=list)


def extract_sql(text: str) -> str:
    """Pull a single SQL statement out of a model's text response.

    Handles bare SQL, ```sql fenced blocks, and a leading "SQL:" label. Returns the text from
    the first SELECT/WITH to the end (trailing semicolon and prose stripped).
    """
    t = text.strip()
    # strip markdown code fences if present
    fence = re.search(r"```(?:sql)?\s*(.+?)```", t, re.IGNORECASE | re.DOTALL)
    if fence:
        t = fence.group(1).strip()
    # drop a leading "SQL:" label
    t = re.sub(r"^\s*SQL:\s*", "", t, flags=re.IGNORECASE)
    # take from the first SELECT or WITH keyword; if neither is present, there is no SQL
    m = re.search(r"\b(SELECT|WITH)\b", t, re.IGNORECASE)
    if not m:
        return ""
    t = t[m.start() :]
    return t.strip().rstrip(";").strip()


class SqlGenerator:
    def __init__(self, agent_factory) -> None:
        # agent_factory() -> a fresh Strands Agent configured with the generator model + prompt.
        self._agent_factory = agent_factory

    @property
    def system_prompt(self) -> str:
        return _SYSTEM

    def generate(self, resolved_question: str) -> SqlCandidate:
        agent: Agent = self._agent_factory()
        prompt = f"Question: {resolved_question}\nSQL:"
        text = agent_text(agent, prompt)
        sql = extract_sql(text)
        if not sql:
            raise ValueError(f"SQL_Generator: no SQL in model output: {text[:200]!r}")
        return SqlCandidate(sql=sql)
