# TBX API image. uv-based build.
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

# Install uv (pinned) from the official image.
COPY --from=ghcr.io/astral-sh/uv:0.12.9 /uv /uvx /bin/

WORKDIR /app

# Dependency layer: copy only manifests first for cache reuse.
COPY pyproject.toml ./
RUN uv sync --no-install-project --extra dev || uv sync --no-install-project

# Application source.
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./alembic.ini
COPY datasets ./datasets
COPY golden ./golden
COPY scripts ./scripts
COPY docs ./docs

RUN uv sync --extra dev || uv sync

EXPOSE 8000

# bind_host defaults to loopback; compose overrides to 0.0.0.0 inside the container network.
CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
