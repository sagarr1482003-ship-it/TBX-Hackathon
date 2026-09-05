"""SQL_Generator — produces a candidate SELECT via a Strands agent + structured output (Req 11).

The agent runs a Groq text-to-SQL model through the Strands ``OpenAIModel`` provider and returns a
validated :class:`SqlCandidate` (Pydantic) — SQL plus the tables/columns it references — so the
caller never hand-parses JSON. The candidate is handed to the (verified) SQL_Validator before
anything runs.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

from app.services.model.groq_client import call_with_fallback

_SYSTEM = """You are an expert PostgreSQL analyst for an Indian bank finance assistant. Translate
a plain-language question into ONE correct, read-only SELECT statement.

SCHEMA:
  bank(bank_code, bank_name)
  account(account_id, entity_id, account_number[SENSITIVE], program_id,
          available_balance, bank_code -> bank.bank_code)
  transaction(transaction_id, account_id -> account.account_id, transaction_date,
              transaction_type['credit'|'debit'], description, transaction_amount,
              transaction_reference_id, utr_number[SENSITIVE])

FINANCE VOCABULARY (map the user's words to the data):
- "spend" / "spent" / "spending" / "expense" / "outgoing" / "paid" = debit transactions
  (transaction_type = 'debit').
- "income" / "received" / "credited" / "incoming" / "deposits" = credit transactions
  (transaction_type = 'credit').
- "my" / "this account" / a given account_id (UUID) => filter WHERE account_id = '<the id>'.
- "balance" = account.available_balance.
- "transactions" / "txns" = rows in the transaction table.
- "GST"/"tax", "cash flow"/"net", "anomaly"/"outlier"/"unusual" => return the RAW aggregate only
  (a downstream tool computes GST / net flow / z-scores). Do NOT compute those in SQL.

INTENT SHAPE — pick the right query shape for the question:
- "what/how much is my/total spend|income|GST|balance", "total", "sum of" => return a single
  aggregate with SUM(transaction_amount) (or the balance). NOT a row listing.
- "how many", "count of" => COUNT(*).
- "average/highest/lowest/max/min" => AVG/MAX/MIN, or ORDER BY ... LIMIT 1.
- "per bank / per month / by type / each account" => GROUP BY that dimension with the aggregate.
- "list / show me / which transactions / details of" => a row listing of the relevant columns.
- Only produce a bare row listing when the user explicitly wants individual records; otherwise
  prefer the aggregate that directly answers the question.

RULES:
- Read-only SELECT only. Never DDL, DML, or multiple statements.
- Use only the tables/columns above; never invent columns. Prefer explicit column lists.
- Never select the sensitive columns account_number or utr_number in the output.
- When a specific account_id/bank/period/type is named, ALWAYS include it as a WHERE filter.
- Output ONLY the SQL statement — no prose, no explanation, no markdown fences.

PERFORMANCE (the transaction table is very large — millions of rows; avoid full scans):
- Indexed columns on transaction: account_id, transaction_type, transaction_date, transaction_amount.
- Whenever an account_id is given, ALWAYS filter WHERE account_id = '<id>' — this is fast (indexed).
- For a plain row listing, ALWAYS add LIMIT (default 100) so it never scans the whole table.
- Prefer narrow WHERE filters (account_id, transaction_type, a date range) over unfiltered
  aggregates. Only omit filters when the user explicitly asks for an all-accounts total.

If the question truly cannot be turned into one correct query (missing an essential detail, or
references data not in this schema), do NOT guess. Output exactly one line:
CLARIFY: <one short, specific follow-up question>
But questions answerable over all data (e.g. "total credit amount", "transactions per bank") are
answerable — write SQL, do not clarify.

Examples (question -> SQL):
Q: What are my spends? (account_id e89fa331-...)
SQL: SELECT SUM(transaction_amount) AS total_spend FROM transaction WHERE account_id = 'e89fa331-...' AND transaction_type = 'debit'
Q: How much did I spend? (account 123)
SQL: SELECT SUM(transaction_amount) AS total_spend FROM transaction WHERE account_id = '123' AND transaction_type = 'debit'
Q: What is my total income? (account 123)
SQL: SELECT SUM(transaction_amount) AS total_income FROM transaction WHERE account_id = '123' AND transaction_type = 'credit'
Q: What is my balance? (account 123)
SQL: SELECT available_balance FROM account WHERE account_id = '123'
Q: How many debit transactions are there?
SQL: SELECT COUNT(*) FROM transaction WHERE transaction_type = 'debit'
Q: What is the total credit amount across all transactions?
SQL: SELECT SUM(transaction_amount) FROM transaction WHERE transaction_type = 'credit'
Q: My spending per month (account 123)
SQL: SELECT date_trunc('month', transaction_date) AS month, SUM(transaction_amount) AS spend FROM transaction WHERE account_id = '123' AND transaction_type = 'debit' GROUP BY month ORDER BY month
Q: How many accounts does each bank have?
SQL: SELECT b.bank_name, COUNT(*) AS account_count FROM account a JOIN bank b ON a.bank_code = b.bank_code GROUP BY b.bank_name ORDER BY account_count DESC
Q: Which account has the highest available balance?
SQL: SELECT account_id, available_balance FROM account ORDER BY available_balance DESC LIMIT 1
Q: What is the total transaction amount per bank?
SQL: SELECT b.bank_name, SUM(t.transaction_amount) AS total FROM transaction t JOIN account a ON t.account_id = a.account_id JOIN bank b ON a.bank_code = b.bank_code GROUP BY b.bank_name ORDER BY total DESC
Q: Show me the transactions for account 123
SQL: SELECT transaction_id, transaction_date, transaction_type, transaction_amount, description FROM transaction WHERE account_id = '123' ORDER BY transaction_date DESC
Q: Find the transaction with reference id S69244711.
SQL: SELECT transaction_id, transaction_date, transaction_type, transaction_amount, description FROM transaction WHERE transaction_reference_id = 'S69244711'
Q: How many transactions happened in each month?
SQL: SELECT date_trunc('month', transaction_date) AS month, COUNT(*) AS txn_count FROM transaction GROUP BY month ORDER BY month
"""


class SqlCandidate(BaseModel):
    """The generator's parsed output: either a SQL candidate or a clarification request."""

    sql: str = Field(default="", description="One read-only PostgreSQL SELECT statement")
    tables: list[str] = Field(default_factory=list)
    columns: list[str] = Field(default_factory=list)
    clarification: str | None = None  # set when the generator asks a follow-up instead of SQL


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
    def __init__(self, agent_factory, fallback_factory=None) -> None:
        # agent_factory() -> a fresh Strands Agent; fallback_factory() -> OpenRouter agent.
        self._agent_factory = agent_factory
        self._fallback_factory = fallback_factory
        self.last_usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}

    @property
    def system_prompt(self) -> str:
        return _SYSTEM

    def generate(self, resolved_question: str, history: list | None = None) -> SqlCandidate:
        prompt = self._with_history(resolved_question, history)
        text, self.last_usage = call_with_fallback(
            self._agent_factory, self._fallback_factory, prompt
        )
        # The generator may ask a follow-up instead of writing SQL (one call, no extra agent).
        m = re.search(r"CLARIFY:\s*(.+)", text, re.IGNORECASE | re.DOTALL)
        if m and "select" not in text.lower()[: m.start()]:
            question = m.group(1).strip().split("\n")[0].strip()
            if question:
                return SqlCandidate(clarification=question)
        sql = extract_sql(text)
        if not sql:
            raise ValueError(f"SQL_Generator: no SQL in model output: {text[:200]!r}")
        return SqlCandidate(sql=sql)

    @staticmethod
    def _with_history(question: str, history: list | None) -> str:
        """Prepend recent turns so a follow-up resolves against prior context.

        ``history`` is a list of Turn-like objects with ``.question``, ``.resolved_sql`` and
        ``.answer``. We include the last few turns and, for each, the prior SQL *and* the prior
        answer text. Carrying the answer matters when the user established an identifier in plain
        language earlier (e.g. "my account id: e89f…" -> a balance answer naming that account):
        a later "what are my transactions" must bind "my" to that same account rather than
        re-asking. Only the last few turns are included to keep the prompt bounded.
        """
        if not history:
            return f"Question: {question}\nSQL:"
        lines = [
            "Conversation so far. Resolve follow-ups (pronouns like \"my\"/\"that\" and phrases "
            "like \"my account\") against the identifiers and SQL already established below; do "
            "not ask again for something the user already provided.",
        ]
        for t in history[-3:]:
            q = getattr(t, "question", None)
            sql = getattr(t, "resolved_sql", None)
            answer = getattr(t, "answer", None)
            if not q:
                continue
            block = [f"- Q: {q}"]
            if sql:
                block.append(f"  SQL: {sql}")
            if answer:
                # A one-line snippet of the prior answer carries resolved identifiers/facts.
                snippet = " ".join(str(answer).split())[:240]
                block.append(f"  A: {snippet}")
            lines.append("\n".join(block))
        lines.append(f"\nQuestion: {question}\nSQL:")
        return "\n".join(lines)
