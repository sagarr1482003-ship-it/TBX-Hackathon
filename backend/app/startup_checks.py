"""Startup gates (Task 1.5, Requirement 32.3/32.13/32.14, 19.9, 10.13/10.14, 14.15, 13.13).

The *configuration* gates here are pure and unit-tested. The *database* gates
(applied-revision == head, vector extension present, active dataset populated) are UNVERIFIED
because they require a running PostgreSQL. Each failing gate raises :class:`StartupCheckError`,
which the process turns into a non-zero exit without binding the HTTP listener (Requirement 32.14).
"""

from __future__ import annotations

from app.errors import StartupCheckError


def check_confidence_weights(weights: dict[str, float]) -> None:
    """R19.9: weights are non-negative and sum to 1 within 0.001."""
    if any(w < 0 for w in weights.values()):
        raise StartupCheckError("confidence signal weight below 0", weights=weights)
    total = sum(weights.values())
    if abs(total - 1.0) > 0.001:
        raise StartupCheckError(
            "confidence signal weights do not sum to 1 within 0.001", total=total
        )


def check_band_boundaries(boundaries: dict[str, float]) -> None:
    """R19.9: band boundaries form a strictly ascending sequence covering [0, 1]."""
    medium = boundaries.get("medium")
    high = boundaries.get("high")
    if medium is None or high is None:
        raise StartupCheckError("band boundaries must declare 'medium' and 'high'")
    if not (0.0 < medium < high < 1.0):
        raise StartupCheckError(
            "band boundaries must be strictly ascending within (0, 1)",
            medium=medium,
            high=high,
        )


def check_budget_ceilings(
    calls: int,
    tokens: int,
    wallclock_s: int,
    *,
    ceilings: tuple[int, int, int] = (10, 32_000, 60),
) -> None:
    """R10.14: a per-question budget value may not exceed its hard ceiling."""
    max_calls, max_tokens, max_wall = ceilings
    if calls > max_calls:
        raise StartupCheckError("max_llm_calls exceeds ceiling", value=calls, ceiling=max_calls)
    if tokens > max_tokens:
        raise StartupCheckError("max_tokens exceeds ceiling", value=tokens, ceiling=max_tokens)
    if wallclock_s > max_wall:
        raise StartupCheckError(
            "wallclock deadline exceeds ceiling", value=wallclock_s, ceiling=max_wall
        )


def check_concurrency_within_pool(max_concurrent_queries: int, reader_pool_size: int) -> None:
    """R13.13: max_concurrent_queries must be <= reader_pool_size."""
    if max_concurrent_queries > reader_pool_size:
        raise StartupCheckError(
            "max_concurrent_queries exceeds reader_pool_size",
            max_concurrent_queries=max_concurrent_queries,
            reader_pool_size=reader_pool_size,
        )


def check_reviewer_independence(
    reviewer: tuple[str, str, str], sql_generator: tuple[str, str, str]
) -> None:
    """R14.15: reviewer and sql_generator must differ in provider, model or prompt version."""
    if reviewer == sql_generator:
        raise StartupCheckError(
            "reviewer independence from sql_generator unsatisfied",
            resolved=reviewer,
        )


def check_model_tier(
    role: str,
    parameter_count_billions: float | None,
    hosted_tier: str | None,
    *,
    ceiling_billions: float = 8.0,
) -> None:
    """R10.13: an open-weight model must be within the ceiling; a hosted model must be a
    small/mini/flash tier."""
    if parameter_count_billions is not None:
        if parameter_count_billions > ceiling_billions:
            raise StartupCheckError(
                "open-weight model exceeds parameter ceiling",
                role=role,
                params_b=parameter_count_billions,
                ceiling_b=ceiling_billions,
            )
    elif hosted_tier is not None:
        if hosted_tier.lower() not in ("small", "mini", "flash"):
            raise StartupCheckError(
                "hosted model is not a small/mini/flash tier", role=role, tier=hosted_tier
            )


# --- database gates (UNVERIFIED — require PostgreSQL) ----------------------------------
async def assert_migrations_at_head(conn) -> None:  # pragma: no cover - needs DB
    """R32.3/32.14: applied Alembic revision must equal head."""
    from alembic.config import Config
    from alembic.runtime.migration import MigrationContext
    from alembic.script import ScriptDirectory

    ctx = MigrationContext.configure(await conn.connection())
    current = ctx.get_current_revision()
    head = ScriptDirectory.from_config(Config("alembic.ini")).get_current_head()
    if current != head:
        raise StartupCheckError("applied revision != head", current=current, head=head)


async def assert_vector_extension(conn) -> None:  # pragma: no cover - needs DB
    from sqlalchemy import text

    result = await conn.execute(
        text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
    )
    if result.first() is None:
        raise StartupCheckError("pgvector extension is absent from the active database")


async def assert_active_dataset_populated(conn) -> None:  # pragma: no cover - needs DB
    from sqlalchemy import text

    result = await conn.execute(
        text("SELECT 1 FROM ops.dataset_versions WHERE status = 'active' LIMIT 1")
    )
    if result.first() is None:
        raise StartupCheckError("no active dataset version is populated")
