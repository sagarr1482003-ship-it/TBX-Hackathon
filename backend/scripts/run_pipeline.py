"""Run the agent pipeline against Groq (via Strands) for one question; report latency + verdict.

Usage:
    export GROQ_API_KEY=...            # or set it in .env
    python -m scripts.run_pipeline "how many debit transactions are there?"
    python -m scripts.run_pipeline           # runs a small default question set
"""

from __future__ import annotations

import sys

from app.config import get_settings
from app.services.model.answer_composer import _SYSTEM as COMPOSER_SYSTEM
from app.services.model.answer_composer import AnswerComposer
from app.services.model.groq_client import agent_for
from app.services.model.reviewer import _SYSTEM as REVIEWER_SYSTEM
from app.services.model.reviewer import ReviewerAgent
from app.services.model.sql_generator import _SYSTEM as GENERATOR_SYSTEM
from app.services.model.sql_generator import SqlGenerator
from app.services.pipeline.simple_pipeline import SimplePipeline

_DEFAULT_QUESTIONS = [
    "how many debit transactions are there?",
    "what is the total credit amount across all accounts?",
    "which bank has the most accounts?",
]


def _make_executor(reader_dsn: str, cipher=None, sensitive=frozenset()):
    """Return (executor, pool). A pre-warmed read-only pool keeps latency low: connections are
    opened once (not per query) and each is pre-configured read-only with search_path=finance and
    a 10s statement timeout, so a checkout is immediately ready to run.

    When a ``cipher`` is supplied, sensitive columns are decrypted on read (data-at-rest): the DB
    stores ciphertext, the pipeline sees plaintext, and the masking layer then masks it for output.
    """
    from psycopg_pool import ConnectionPool

    sync_dsn = reader_dsn.replace("+asyncpg", "")

    def _configure(conn):
        conn.execute("SET search_path TO finance, public")
        conn.execute("SET statement_timeout = 10000")
        conn.execute("SET default_transaction_read_only = on")
        conn.commit()

    pool = ConnectionPool(
        sync_dsn, min_size=2, max_size=8, configure=_configure, open=False
    )
    pool.open(wait=True, timeout=10)

    def execute(sql: str):
        with pool.connection() as conn, conn.cursor() as cur:
            cur.execute(sql)
            columns = [d.name for d in cur.description] if cur.description else []
            rows = [dict(zip(columns, r)) for r in cur.fetchall()]
        if cipher is not None and sensitive:
            for row in rows:
                for col in sensitive:
                    if col in row and isinstance(row[col], str):
                        row[col] = cipher.decrypt(row[col])
        return columns, rows

    return execute, pool


def _build():
    s = get_settings()
    key = s.groq_api_key or ""

    def gen_agent():
        return agent_for(
            key, s.sql_generator_model, GENERATOR_SYSTEM, base_url=s.groq_base_url,
            reasoning_effort=s.sql_generator_reasoning_effort,
            max_tokens=s.sql_generator_max_tokens,
        )

    def rev_agent():
        return agent_for(
            key, s.reviewer_model, REVIEWER_SYSTEM, base_url=s.groq_base_url,
            reasoning_effort=s.reviewer_reasoning_effort,
            max_tokens=s.reviewer_max_tokens,
        )

    def comp_agent():
        return agent_for(
            key, s.composer_model, COMPOSER_SYSTEM, base_url=s.groq_base_url,
            reasoning_effort=s.composer_reasoning_effort,
            max_tokens=s.composer_max_tokens,
        )

    reader_dsn = s.postgres_reader_dsn or s.postgres_dsn
    cipher = None
    if s.pii_encryption_key:
        from app.services.pipeline.pii_crypto import PiiCipher

        cipher = PiiCipher(s.pii_encryption_key)
    from app.services.ingestion.contract import SEED_CONTRACTS
    from app.services.pipeline.masking import sensitive_columns

    sensitive = sensitive_columns(SEED_CONTRACTS)
    executor, pool = _make_executor(reader_dsn, cipher=cipher, sensitive=sensitive)
    pipeline = SimplePipeline(
        SqlGenerator(gen_agent),
        ReviewerAgent(rev_agent),
        executor=executor,
        answer_composer=AnswerComposer(comp_agent),
    )
    return pipeline, pool


def _run_one(pipeline: SimplePipeline, question: str) -> None:
    r = pipeline.run(question)
    print("=" * 72)
    print(f"Q: {question}")
    print(f"outcome: {r.outcome}   total: {r.total_ms} ms")
    if r.canonical_sql:
        print(f"SQL: {r.canonical_sql}")
    if r.verdict:
        print(f"verdict: {r.verdict.verdict} — {r.verdict.reason}")
    if r.answer is not None:
        print(f"ANSWER ({r.answer_source}): {r.answer}")
    if r.chart is not None:
        pts = ", ".join(f"{p['label']}={p['value']:g}" for p in r.chart["points"][:8])
        print(
            f"CHART [{r.chart['type']}] "
            f"{r.chart['label_field']} x {r.chart['value_field']}: {pts}"
        )
    if not r.validation_ok and r.validation_reason:
        print(f"validation: REJECTED — {r.validation_reason}")
    print(f"stages: {r.stage_ms}")
    print(f"latency budget (<=10s): {'OK' if r.total_ms <= 10_000 else 'OVER 10s'}")


def _silence_async_teardown_noise() -> None:
    """Suppress the harmless GeneratorExit / 'generator didn't stop after athrow()' noise that
    Strands' httpx/httpcore async client emits during interpreter shutdown (it runs async under a
    sync agent() call). This is cosmetic — it always occurs after a correct answer — and there is
    no public handle on Strands' internal client to close it gracefully. We filter only these
    specific shutdown lines and leave all other stderr intact."""
    import io
    import sys

    real_stderr = sys.stderr
    needles = (
        "GeneratorExit",
        "athrow()",
        "connection_pool.py",
        "generator didn't stop",
        "httpcore",
    )

    class _Filter(io.TextIOBase):
        def write(self, s: str) -> int:
            if any(n in s for n in needles):
                return len(s)
            return real_stderr.write(s)

        def flush(self) -> None:
            real_stderr.flush()

    sys.stderr = _Filter()


def main() -> None:
    pipeline, pool = _build()
    questions = [" ".join(sys.argv[1:])] if len(sys.argv) > 1 else _DEFAULT_QUESTIONS
    try:
        for q in questions:
            _run_one(pipeline, q)
    finally:
        pool.close()  # graceful pool shutdown
        _silence_async_teardown_noise()


if __name__ == "__main__":
    main()
