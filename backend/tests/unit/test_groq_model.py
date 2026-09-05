"""Groq model layer config verification (no network).

Confirms reasoning_effort is passed through to the Strands OpenAIModel params when set (Qwen 3.x
'medium' for text-to-SQL) and omitted when None, and that a missing API key is rejected.
"""

from __future__ import annotations

import pytest

from app.services.model.groq_client import ModelLayerError, build_groq_model


def _params(model) -> dict:
    # Strands OpenAIModel stores config (incl. params) accessible via get_config().
    cfg = model.get_config()
    return dict(cfg.get("params") or {})


def test_reasoning_effort_included_when_set() -> None:
    model = build_groq_model("k", "qwen-2.5-coder-32b", reasoning_effort="medium")
    assert _params(model).get("reasoning_effort") == "medium"


def test_reasoning_effort_omitted_when_none() -> None:
    model = build_groq_model("k", "llama-3.3-70b-versatile", reasoning_effort=None)
    assert "reasoning_effort" not in _params(model)


def test_missing_api_key_rejected() -> None:
    with pytest.raises(ModelLayerError):
        build_groq_model("", "qwen-2.5-coder-32b")
