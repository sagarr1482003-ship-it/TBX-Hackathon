"""Pipeline factory — builds a SimplePipeline (generator + reviewer + composer + executor).

Shared by the SSE chat route and the CLI so the wiring lives in one place: Strands agents on
Groq, a pre-warmed read-only Postgres pool with PII decrypt-on-read, and sensitive-column masking.
Returns (pipeline, pool); the caller closes the pool.
"""

from __future__ import annotations

import logging

from app.config import get_settings
from app.services.ingestion.contract import SEED_CONTRACTS
from app.services.model.answer_composer import _SYSTEM as COMPOSER_SYSTEM
from app.services.model.answer_composer import AnswerComposer
from app.services.model.groq_client import agent_for
from app.services.model.reviewer import _SYSTEM as REVIEWER_SYSTEM
from app.services.model.reviewer import ReviewerAgent
from app.services.model.sql_generator import _SYSTEM as GENERATOR_SYSTEM
from app.services.model.sql_generator import SqlGenerator
from app.services.pipeline.masking import sensitive_columns
from app.services.pipeline.simple_pipeline import SimplePipeline

logger = logging.getLogger(__name__)


def _decrypt_encrypted(rows, cipher) -> None:
    """Decrypt any encrypted cells in place, warning once if the configured key can't decrypt them.

    Marker-driven: only values carrying the ``enc:v1:`` prefix (i.e. produced by this app's cipher)
    are decrypted, so it works no matter which columns the connected database encrypted. A non-zero
    failure count almost always means the connected database was encrypted with a different AES key
    than the one configured (the judges' connect-your-own-DB path). We keep the query alive and let
    the masking layer hide the undecryptable cells rather than failing the turn.
    """
    from app.services.pipeline.pii_crypto import decrypt_encrypted_inplace

    failures = decrypt_encrypted_inplace(rows, cipher)
    if failures:
        logger.warning(
            "PII decrypt: %d encrypted cell(s) could not be decrypted with the configured "
            "PII_ENCRYPTION_KEY — likely a key mismatch for the connected database. "
            "Those values are shown redacted.",
            failures,
        )


def make_executor(reader_dsn: str, cipher=None, sensitive=frozenset(), preview_cap: int = 100):
    """Pre-warmed read-only pool executor: bounded fetch (preview + COUNT), decrypt-on-read."""
    from psycopg_pool import ConnectionPool

    sync_dsn = reader_dsn.replace("+asyncpg", "")

    def _configure(conn):
        conn.execute("SET search_path TO finance, public")
        conn.execute("SET statement_timeout = 10000")
        conn.execute("SET default_transaction_read_only = on")
        conn.commit()

    pool = ConnectionPool(sync_dsn, min_size=2, max_size=8, configure=_configure, open=False)
    pool.open(wait=True, timeout=10)

    def execute(sql: str):
        with pool.connection() as conn, conn.cursor() as cur:
            cur.execute(sql)
            columns = [d.name for d in cur.description] if cur.description else []
            rows = [dict(zip(columns, r)) for r in cur.fetchmany(preview_cap)]
            try:
                cur.execute(f"SELECT count(*) FROM ({sql}) AS _sub")
                total = int(cur.fetchone()[0])
            except Exception:
                total = len(rows)
        if cipher is not None:
            _decrypt_encrypted(rows, cipher)
        return columns, rows, total

    def explain_cost(sql: str) -> float:
        """Return the planner's estimated total cost via EXPLAIN (no execution).

        A cheap deterministic guardrail: the pipeline rejects a query whose estimated cost is
        far above what any demo query should need, catching a runaway plan before it runs.
        """
        with pool.connection() as conn, conn.cursor() as cur:
            cur.execute(f"EXPLAIN (FORMAT JSON) {sql}")
            plan = cur.fetchone()[0]
        # plan is a list[dict] with a top-level "Plan" carrying "Total Cost".
        try:
            return float(plan[0]["Plan"]["Total Cost"])
        except (KeyError, IndexError, TypeError):
            return 0.0

    execute.explain_cost = explain_cost  # attach so the pipeline can call it
    return execute, pool


def build_pipeline():
    """Construct the full pipeline. Returns (pipeline, pool)."""
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
            reasoning_effort=s.reviewer_reasoning_effort, max_tokens=s.reviewer_max_tokens,
        )

    def comp_agent():
        return agent_for(
            key, s.composer_model, COMPOSER_SYSTEM, base_url=s.groq_base_url,
            reasoning_effort=s.composer_reasoning_effort, max_tokens=s.composer_max_tokens,
        )

    cipher = None
    if s.pii_encryption_key:
        from app.services.pipeline.pii_crypto import PiiCipher

        cipher = PiiCipher(s.pii_encryption_key)
    sensitive = sensitive_columns(SEED_CONTRACTS)
    executor, pool = make_executor(
        s.postgres_reader_dsn or s.postgres_dsn, cipher=cipher, sensitive=sensitive
    )
    pipeline = SimplePipeline(
        SqlGenerator(gen_agent),
        ReviewerAgent(rev_agent),
        executor=executor,
        answer_composer=AnswerComposer(comp_agent),
        max_plan_cost=s.max_plan_cost,
    )
    return pipeline, pool
