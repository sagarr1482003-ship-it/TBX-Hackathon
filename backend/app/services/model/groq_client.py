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
    max_tokens: int | None = None,
    reasoning_effort: str | None = None,
    max_retries: int = 2,
) -> OpenAIModel:
    """Construct a Strands ``OpenAIModel`` bound to Groq for one role's model id.

    ``reasoning_effort`` (Qwen 3.x: ``low`` | ``medium`` | ``xhigh``) is passed through when set;
    ``low`` is recommended for text-to-SQL. ``max_tokens`` is omitted when ``None`` (uncapped).
    ``max_retries=0`` makes a 429 (rate limit) raise immediately instead of the OpenAI client
    silently retrying with backoff — so the caller's fallback (OpenRouter) engages fast.
    """
    if not api_key:
        raise ModelLayerError("GROQ_API_KEY is not configured")
    params: dict = {"temperature": temperature}
    if max_tokens is not None:
        params["max_tokens"] = max_tokens
    if reasoning_effort:
        params["reasoning_effort"] = reasoning_effort
    return OpenAIModel(
        client_args={"api_key": api_key, "base_url": base_url, "max_retries": max_retries},
        model_id=model_id,
        params=params,
    )


def agent_for(
    api_key: str,
    model_id: str,
    system_prompt: str,
    *,
    base_url: str = GROQ_DEFAULT_BASE_URL,
    temperature: float = 0.0,
    max_tokens: int | None = None,
    reasoning_effort: str | None = None,
    max_retries: int = 2,
) -> Agent:
    """Construct a fresh Strands ``Agent`` for a role.

    ``callback_handler=None`` disables console streaming so the agent is quiet inside the pipeline.
    Trace/budget instrumentation attaches via Strands hooks (added with the orchestrator).
    """
    model = build_groq_model(
        api_key,
        model_id,
        base_url=base_url,
        temperature=temperature,
        max_tokens=max_tokens,
        reasoning_effort=reasoning_effort,
        max_retries=max_retries,
    )
    return Agent(model=model, system_prompt=system_prompt, callback_handler=None)


def _extract_usage(result) -> dict:
    """Best-effort token usage from a Strands AgentResult (shape varies by version)."""
    usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    try:
        summary = result.metrics.get_summary()
        acc = summary.get("accumulated_usage", {}) if isinstance(summary, dict) else {}
        usage["input_tokens"] = int(acc.get("inputTokens", 0) or 0)
        usage["output_tokens"] = int(acc.get("outputTokens", 0) or 0)
        usage["total_tokens"] = int(
            acc.get("totalTokens", usage["input_tokens"] + usage["output_tokens"]) or 0
        )
    except Exception:
        pass
    return usage


def _extract_text(result) -> str:
    """Best-effort final assistant text from a Strands AgentResult.

    ``str(result)`` works for most providers, but some (e.g. Gemini via the OpenAI-compat layer,
    whose message carries a thought_signature) can render empty. Fall back to walking the
    AgentResult's message content blocks for the text.
    """
    text = str(result).strip()
    if text:
        return text
    # Walk result.message["content"] -> list of blocks with a "text" field.
    try:
        msg = getattr(result, "message", None)
        content = msg.get("content") if isinstance(msg, dict) else getattr(msg, "content", None)
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            parts = []
            for block in content:
                if isinstance(block, dict) and block.get("text"):
                    parts.append(str(block["text"]))
                elif hasattr(block, "text") and getattr(block, "text"):
                    parts.append(str(block.text))
            return "".join(parts).strip()
    except Exception:
        pass
    return ""


def agent_text_with_usage(agent: Agent, prompt: str) -> tuple[str, dict]:
    """Invoke a Strands agent; return (final text, token-usage dict)."""
    result = agent(prompt)
    return _extract_text(result), _extract_usage(result)


def call_with_fallback(primary_factory, fallback_factory, prompt: str) -> tuple[str, dict]:
    """Call the primary agent; on failure OR empty output, retry once with the fallback agent.

    Both factories are zero-arg callables returning a fresh Strands Agent. ``fallback_factory``
    may be None (no fallback configured) — then the primary error/empty result stands. Used so a
    rate-limit, outage, or empty response transparently fails over to the backup provider.
    """
    try:
        text, usage = agent_text_with_usage(primary_factory(), prompt)
        if text:
            return text, usage
    except Exception:
        if fallback_factory is None:
            raise
        return agent_text_with_usage(fallback_factory(), prompt)
    # Primary returned empty (no exception): use fallback if available, else return the empty.
    if fallback_factory is None:
        return "", usage
    return agent_text_with_usage(fallback_factory(), prompt)


def agent_text(agent: Agent, prompt: str) -> str:
    """Invoke a Strands agent and return its final text response (token usage discarded).

    Plain-text invocation avoids the function-calling wrapping of ``structured_output``, which
    some reasoning models on OpenAI-compatible endpoints fail to complete. Callers parse the
    text themselves (e.g. extract one SELECT).
    """
    text, _ = agent_text_with_usage(agent, prompt)
    return text
