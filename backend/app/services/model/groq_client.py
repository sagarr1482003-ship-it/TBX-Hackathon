"""Strands-backed model layer for Groq (OpenAI-compatible).

Groq exposes an OpenAI-compatible API, so we use the Strands ``OpenAIModel`` provider pointed at
Groq's base URL. This keeps the agent layer on the Strands abstraction (provider-neutral, with the
agent loop, structured output, hooks and metrics that come with it) while running on Groq models.

``agent_for()`` is the single place a Strands ``Agent`` is constructed for a role. Each agent uses
structured output (``agent.structured_output(PydanticModel, prompt)``) so the SQL candidate and the
reviewer verdict come back as validated Pydantic objects rather than hand-parsed JSON.

Model identifiers are configuration (``SQL_GENERATOR_MODEL`` / ``REVIEWER_MODEL``); set the exact
Groq slugs in ``.env``.
"""

from __future__ import annotations

from strands import Agent
from strands.models.openai import OpenAIModel

GROQ_DEFAULT_BASE_URL = "https://api.groq.com/openai/v1"


class ModelLayerError(Exception):
    """Raised when the model layer is misconfigured (e.g. missing API key)."""


def build_groq_model(
    api_key: str,
    model_id: str,
    *,
    base_url: str = GROQ_DEFAULT_BASE_URL,
    temperature: float = 0.0,
    max_tokens: int = 1024,
) -> OpenAIModel:
    """Construct a Strands ``OpenAIModel`` bound to Groq for one role's model id."""
    if not api_key:
        raise ModelLayerError("GROQ_API_KEY is not configured")
    return OpenAIModel(
        client_args={"api_key": api_key, "base_url": base_url},
        model_id=model_id,
        params={"temperature": temperature, "max_tokens": max_tokens},
    )


def agent_for(
    api_key: str,
    model_id: str,
    system_prompt: str,
    *,
    base_url: str = GROQ_DEFAULT_BASE_URL,
    temperature: float = 0.0,
    max_tokens: int = 1024,
) -> Agent:
    """Construct a fresh Strands ``Agent`` for a role.

    ``callback_handler=None`` disables console streaming so the agent is quiet inside the pipeline.
    Trace/budget instrumentation attaches via Strands hooks (added with the orchestrator).
    """
    model = build_groq_model(
        api_key, model_id, base_url=base_url, temperature=temperature, max_tokens=max_tokens
    )
    return Agent(model=model, system_prompt=system_prompt, callback_handler=None)
