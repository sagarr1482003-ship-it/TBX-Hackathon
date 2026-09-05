"""Database engines and sessions (design §5.1, Task 1.5).

UNVERIFIED: this module requires a running PostgreSQL and cannot be executed in the current
environment (Docker socket permission-denied). It is written to the design but not run.

Two async engines:
  * ``tbx_app``    — the read/write application role used for ops tables and ingestion;
  * ``tbx_reader`` — a SELECT-only role (``default_transaction_read_only = on``,
    ``statement_timeout = '10s'``) that MUST be injected only into the Query_Executor
    (Requirement 13.1). No other component receives the reader engine.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import get_settings

_app_engine: AsyncEngine | None = None
_reader_engine: AsyncEngine | None = None


def app_engine() -> AsyncEngine:
    global _app_engine
    if _app_engine is None:
        settings = get_settings()
        _app_engine = create_async_engine(settings.postgres_dsn, pool_pre_ping=True)
    return _app_engine


def _reader_dsn(settings) -> str:
    """Reader DSN: explicit ``postgres_reader_dsn`` if set, else derive from the app DSN by
    swapping in the reader user/password (design §5.1)."""
    if settings.postgres_reader_dsn:
        return settings.postgres_reader_dsn
    # Derive from the app DSN userinfo.
    dsn = settings.postgres_dsn
    import re

    pw = settings.postgres_reader_password or settings.postgres_reader_user
    return re.sub(
        r"://[^:/@]+:[^@]+@",
        f"://{settings.postgres_reader_user}:{pw}@",
        dsn,
        count=1,
    )


def reader_engine() -> AsyncEngine:
    """The SELECT-only reader engine. Inject only into the Query_Executor (R13.1)."""
    global _reader_engine
    if _reader_engine is None:
        settings = get_settings()
        _reader_engine = create_async_engine(
            _reader_dsn(settings),
            pool_size=settings.reader_pool_size,
            pool_pre_ping=True,
        )
    return _reader_engine


app_sessionmaker = lambda: async_sessionmaker(app_engine(), expire_on_commit=False)  # noqa: E731


@asynccontextmanager
async def app_session() -> AsyncIterator[AsyncSession]:
    maker = async_sessionmaker(app_engine(), expire_on_commit=False)
    async with maker() as session:
        yield session
