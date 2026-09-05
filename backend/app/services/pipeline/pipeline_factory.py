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


def make_mysql_executor(host, port, db, user, password, preview_cap: int = 100):
    """Read-only MySQL executor via a small pymysql pool. Bounded fetch; MySQL EXPLAIN cost.

    Differs from the Postgres executor: no search_path, MySQL read-only session, and we do NOT run
    a second COUNT(*) wrapper on every query — on a 10M-row table that doubles latency. The exact
    total is only taken when the result set is small (<= preview_cap); otherwise the preview count
    is reported and the EXPLAIN cost gate guards against runaway scans.
    """
    import queue as _queue

    import pymysql

    def _new_conn():
        c = pymysql.connect(
            host=host, port=port, user=user, password=password, database=db,
            connect_timeout=8, read_timeout=30, autocommit=True,
        )
        with c.cursor() as cur:
            cur.execute("SET SESSION TRANSACTION READ ONLY")
            # Server-side cap: abort a runaway SELECT at 25s rather than dropping the connection.
            cur.execute("SET SESSION MAX_EXECUTION_TIME=25000")
        return c

    pool: _queue.Queue = _queue.Queue(maxsize=8)
    for _ in range(2):
        pool.put(_new_conn())

    def _acquire():
        try:
            return pool.get_nowait()
        except _queue.Empty:
            return _new_conn()

    def _release(conn):
        try:
            pool.put_nowait(conn)
        except _queue.Full:
            conn.close()

    def execute(sql: str):
        conn = _acquire()
        try:
            with conn.cursor() as cur:
                cur.execute(sql)
                columns = [d[0] for d in cur.description] if cur.description else []
                fetched = cur.fetchmany(preview_cap)
                rows = [dict(zip(columns, r)) for r in fetched]
            total = len(rows) if len(rows) < preview_cap else preview_cap
            return columns, rows, total
        finally:
            _release(conn)

    def explain_cost(sql: str) -> float:
        conn = _acquire()
        try:
            with conn.cursor() as cur:
                cur.execute(f"EXPLAIN FORMAT=JSON {sql}")
                raw = cur.fetchone()[0]
            import json as _json

            plan = _json.loads(raw) if isinstance(raw, str) else raw
            return float(plan["query_block"]["cost_info"]["query_cost"])
        except (KeyError, TypeError, ValueError):
            return 0.0
        finally:
            _release(conn)

    class _MySqlPool:
        def close(self):
            while True:
                try:
                    self_conn = pool.get_nowait()
                    self_conn.close()
                except _queue.Empty:
                    break

    execute.explain_cost = explain_cost
    return execute, _MySqlPool()


def build_pipeline():
    """Construct the full pipeline. Returns (pipeline, pool)."""
    s = get_settings()
    # Dialect-aware generator prompt: retarget the SQL flavour when connected to MySQL.
    is_mysql = s.db_dialect == "mysql"
    gen_system = (
        GENERATOR_SYSTEM.replace("PostgreSQL", "MySQL").replace("Postgres", "MySQL")
        if is_mysql else GENERATOR_SYSTEM
    )

    groq_key = s.groq_api_key or ""
    gemini_key = s.gemini_api_key or ""
    or_key = s.openrouter_api_key or ""
    use_gemini = bool(gemini_key)

    def _groq(model_id, system, effort, max_tokens):
        return agent_for(
            groq_key, model_id, system, base_url=s.groq_base_url,
            reasoning_effort=effort, max_tokens=max_tokens, max_retries=0,
        )

    def _gemini(system):
        # Text-to-SQL is deterministic — Gemini's extended "thinking" adds many seconds with no
        # accuracy gain (verified: identical output with thinking off). Disable it for low latency.
        return agent_for(
            gemini_key, s.gemini_model, system, base_url=s.gemini_base_url,
            reasoning_effort="none", max_tokens=None, max_retries=2,
        )

    def _openrouter(system):
        return agent_for(
            or_key, s.openrouter_model, system, base_url=s.openrouter_base_url,
            reasoning_effort="low", max_tokens=None,
        )

    # PRIMARY = Gemini when its key is set, else Groq.
    if use_gemini:
        def gen_agent():
            return _gemini(gen_system)

        def rev_agent():
            return _gemini(REVIEWER_SYSTEM)

        def comp_agent():
            return _gemini(COMPOSER_SYSTEM)

        logger.info("Primary LLM: Gemini (%s)", s.gemini_model)
    else:
        def gen_agent():
            return _groq(
                s.sql_generator_model, gen_system,
                s.sql_generator_reasoning_effort, s.sql_generator_max_tokens,
            )

        def rev_agent():
            return _groq(
                s.reviewer_model, REVIEWER_SYSTEM,
                s.reviewer_reasoning_effort, s.reviewer_max_tokens,
            )

        def comp_agent():
            return _groq(
                s.composer_model, COMPOSER_SYSTEM,
                s.composer_reasoning_effort, s.composer_max_tokens,
            )

    # FALLBACK: prefer OpenRouter; if Gemini is primary and OpenRouter is absent, fall back to Groq.
    def _fallback_for(system, groq_model, groq_effort, groq_tokens):
        if or_key:
            return lambda: _openrouter(system)
        if use_gemini and groq_key:
            return lambda: _groq(groq_model, system, groq_effort, groq_tokens)
        return None

    gen_fallback = _fallback_for(
        gen_system, s.sql_generator_model, s.sql_generator_reasoning_effort,
        s.sql_generator_max_tokens,
    )
    rev_fallback = _fallback_for(
        REVIEWER_SYSTEM, s.reviewer_model, s.reviewer_reasoning_effort, s.reviewer_max_tokens,
    )
    comp_fallback = _fallback_for(
        COMPOSER_SYSTEM, s.composer_model, s.composer_reasoning_effort, s.composer_max_tokens,
    )
    if gen_fallback is None:
        logger.info("No LLM fallback configured.")

    cipher = None
    if s.pii_encryption_key and not is_mysql:
        from app.services.pipeline.pii_crypto import PiiCipher

        cipher = PiiCipher(s.pii_encryption_key)
    sensitive = sensitive_columns(SEED_CONTRACTS)
    if is_mysql:
        executor, pool = make_mysql_executor(
            s.mysql_host, s.mysql_port, s.mysql_db, s.mysql_user, s.mysql_password
        )
        logger.info("DB dialect: MySQL (%s:%s/%s)", s.mysql_host, s.mysql_port, s.mysql_db)
    else:
        executor, pool = make_executor(
            s.postgres_reader_dsn or s.postgres_dsn, cipher=cipher, sensitive=sensitive
        )
    pipeline = SimplePipeline(
        SqlGenerator(gen_agent, fallback_factory=gen_fallback),
        ReviewerAgent(rev_agent, fallback_factory=rev_fallback),
        executor=executor,
        answer_composer=AnswerComposer(comp_agent, fallback_factory=comp_fallback),
        max_plan_cost=s.max_plan_cost,
    )
    return pipeline, pool
