"""Text-to-SQL accuracy harness (Groq / Qwen).

Runs a labelled set of natural-language questions over the bank/account/transaction schema
through the SQL_Generator, then scores each result on three checks that need no live database:

  1. generated      — the model returned a non-empty SQL candidate;
  2. valid          — the candidate passes the SQL_Validator (safe, read-only, schema-conformant);
  3. tables_ok      — the validated SQL references exactly the expected table set.

The score reported is the fraction of questions that are valid AND reference the expected tables —
a strong proxy for execution accuracy without a database. Latency per question is also reported.

Usage (needs GROQ_API_KEY in backend/.env or the environment):
    python -m scripts.eval_text2sql
    python -m scripts.eval_text2sql --effort low     # override reasoning_effort for A/B
"""

from __future__ import annotations

import argparse
import time

import sqlglot
from sqlglot import exp

from app.config import get_settings
from app.services.knowledge.schema_lookup import InMemorySchemaKB
from app.services.model.groq_client import agent_for
from app.services.model.sql_generator import _SYSTEM as GENERATOR_SYSTEM
from app.services.model.sql_generator import SqlGenerator
from app.services.pipeline.simple_pipeline import SEED_SCHEMA
from app.services.pipeline.sql_validator import SqlValidator

# (question, expected table set) — the accuracy label is "did it use the right tables safely".
CASES: list[tuple[str, set[str]]] = [
    ("How many debit transactions are there?", {"transaction"}),
    ("What is the total credit amount across all transactions?", {"transaction"}),
    ("List the 10 largest transactions by amount.", {"transaction"}),
    ("How many accounts does each bank have?", {"account", "bank"}),
    ("What is the total available balance per bank?", {"account", "bank"}),
    ("Show the number of transactions per account.", {"transaction"}),
    ("Which account has the highest available balance?", {"account"}),
    ("What is the average transaction amount for credits?", {"transaction"}),
    ("List all banks.", {"bank"}),
    ("How many transactions happened in each month?", {"transaction"}),
    ("What is the total debit amount for each account?", {"transaction"}),
    ("Show accounts belonging to HDFC bank.", {"account"}),
    ("Count the transactions for each transaction type.", {"transaction"}),
    ("What is the sum of all transaction amounts per bank?", {"transaction", "account", "bank"}),
    ("Find the transaction with reference id S69244711.", {"transaction"}),
]


def _tables_referenced(sql: str) -> set[str]:
    try:
        tree = sqlglot.parse_one(sql, dialect="postgres")
    except Exception:
        return set()
    return {t.name.lower() for t in tree.find_all(exp.Table)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--effort", default=None, help="override reasoning_effort (low|medium|xhigh)"
    )
    args = parser.parse_args()

    s = get_settings()
    key = s.groq_api_key or ""
    effort = args.effort or s.sql_generator_reasoning_effort

    def gen_agent():
        return agent_for(
            key, s.sql_generator_model, GENERATOR_SYSTEM, base_url=s.groq_base_url,
            reasoning_effort=effort, max_tokens=s.sql_generator_max_tokens,
        )

    generator = SqlGenerator(gen_agent)
    validator = SqlValidator()
    schema = InMemorySchemaKB(SEED_SCHEMA)

    print(f"model={s.sql_generator_model}  reasoning_effort={effort}\n" + "=" * 72)
    generated = valid = tables_ok = 0
    total_ms = 0
    for i, (question, expected) in enumerate(CASES, 1):
        t0 = time.monotonic()
        try:
            candidate = generator.generate(question)
            sql = candidate.sql
            generated += 1
        except Exception as exc:
            print(f"{i:2}. GEN-FAIL  {question}\n     error: {exc}")
            continue
        ms = int((time.monotonic() - t0) * 1000)
        total_ms += ms

        verdict = validator.validate(sql, schema, "transaction_lookup")  # type: ignore[arg-type]
        canonical = getattr(verdict, "canonical_sql", None)
        is_valid = canonical is not None
        refs = _tables_referenced(canonical or sql)
        refs_ok = is_valid and refs == expected
        valid += int(is_valid)
        tables_ok += int(refs_ok)

        flag = "OK " if refs_ok else ("VAL" if is_valid else "REJ")
        print(f"{i:2}. [{flag}] {ms:5}ms  {question}")
        print(f"     sql: {sql}")
        if is_valid and not refs_ok:
            print(f"     tables got={sorted(refs)} expected={sorted(expected)}")
        if not is_valid:
            print(f"     rejected: {getattr(verdict, 'reason', '')}")

    n = len(CASES)
    print("=" * 72)
    print(f"generated: {generated}/{n}   valid: {valid}/{n}   tables-correct: {tables_ok}/{n}")
    print(f"accuracy (valid & correct tables): {tables_ok / n:.0%}")
    if generated:
        print(f"avg latency/question: {total_ms // generated} ms")


if __name__ == "__main__":
    main()
