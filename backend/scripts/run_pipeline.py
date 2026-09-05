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
from app.services.model.clarifier import _SYSTEM as CLARIFIER_SYSTEM
from app.services.model.clarifier import Clarifier
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

    def clarify_agent():
        return agent_for(
            key, s.sql_generator_model, CLARIFIER_SYSTEM, base_url=s.groq_base_url,
            reasoning_effort="low", max_tokens=256,
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
        clarifier=Clarifier(clarify_agent),
    )
    return pipeline, pool


def _result_to_dict(question: str, r) -> dict:
    """The full structured response for one turn — the object a frontend/consumer would use,
    including the chart spec, the breakdown rows and a per-stage trace."""
    trace = [
        {"stage": stage, "duration_ms": ms}
        for stage, ms in r.stage_ms.items()
    ]
    return {
        "question": question,
        "outcome": r.outcome,
        "clarification": r.clarification,
        "resolved_sql": r.canonical_sql,
        "answer_text": r.answer,
        "answer_source": r.answer_source,
        "chart": r.chart,  # {type, label_field, value_field, points:[{label,value}]}
        "verdict": (
            {"verdict": r.verdict.verdict, "reason": r.verdict.reason} if r.verdict else None
        ),
        "breakdown": {
            "columns": r.columns,
            "rows": r.rows,  # sensitive columns already masked; capped preview
            "total_row_count": r.total_row_count,
        },
        "validation_ok": r.validation_ok,
        "validation_reason": r.validation_reason,
        "total_ms": r.total_ms,
        "trace": trace,
    }


def _persist(payload: dict) -> str:
    """Write the full turn payload (with trace) to runs/<timestamp>.json and return the path."""
    import datetime
    import json
    import pathlib

    runs = pathlib.Path("runs")
    runs.mkdir(exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    path = runs / f"turn-{ts}.json"
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return str(path)


def _run_one(pipeline: SimplePipeline, question: str, *, as_json: bool = False) -> None:
    r = pipeline.run(question)
    payload = _result_to_dict(question, r)
    saved = _persist(payload)

    if as_json:
        import json

        print(json.dumps(payload, indent=2, default=str))
        print(f"\n[saved full output + trace to {saved}]")
        return

    print("=" * 72)
    print(f"Q: {question}")
    print(f"outcome: {r.outcome}   total: {r.total_ms} ms")
    if r.clarification is not None:
        print(f"CLARIFY: {r.clarification}")
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
    print(f"[full output + trace saved to {saved}]")


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
    args = sys.argv[1:]
    as_json = "--json" in args
    args = [a for a in args if a != "--json"]
    pipeline, pool = _build()
    questions = [" ".join(args)] if args else _DEFAULT_QUESTIONS
    try:
        for q in questions:
            _run_one(pipeline, q, as_json=as_json)
    finally:
        pool.close()  # graceful pool shutdown
        _silence_async_teardown_noise()


if __name__ == "__main__":
    main()
