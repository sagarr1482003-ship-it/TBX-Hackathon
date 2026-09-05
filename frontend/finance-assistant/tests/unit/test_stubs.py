"""Stub provider verification (Task 1.6) — the no-network stubs are deterministic.

The full test harness (tests/conftest.py DB fixtures, organiser HTTP app) is unverified because it
needs PostgreSQL; these pure stubs are exercised directly.
"""

from __future__ import annotations

from tests.stubs.model_provider import StubEmbedder, StubModelProvider, StubResponse
from tests.stubs.voice import StubTranscript, StubVoiceProvider


def test_embedder_deterministic_and_dimensioned() -> None:
    emb = StubEmbedder(dimension=384)
    a = emb.embed(["vendor spend"])
    b = emb.embed(["vendor spend"])
    assert a == b  # deterministic
    assert len(a[0]) == 384
    # L2 norm ~ 1
    norm = sum(v * v for v in a[0]) ** 0.5
    assert abs(norm - 1.0) < 1e-9


def test_model_provider_counts_calls_and_tokens() -> None:
    provider = StubModelProvider(
        scripts={
            "sql_generator": [
                StubResponse(content={"sql": "SELECT 1"}, input_tokens=5, output_tokens=7)
            ]
        }
    )
    resp = provider.call("sql_generator", "prompt")
    assert resp.content == {"sql": "SELECT 1"}
    assert provider.call_count == 1
    assert provider.total_input_tokens == 5
    assert provider.total_output_tokens == 7


def test_model_provider_raises_scripted_error() -> None:
    import pytest

    provider = StubModelProvider(
        scripts={"reviewer": [StubResponse(content=None, raise_error=RuntimeError("boom"))]}
    )
    with pytest.raises(RuntimeError):
        provider.call("reviewer", "p")


def test_voice_stub_no_confidence_case() -> None:
    provider = StubVoiceProvider(
        transcripts=[StubTranscript(text="hi", confidence=None)]
    )
    t = provider.transcribe(b"\x00\x00")
    assert t.confidence is None  # models a provider omitting confidence (R28.11)
    audio = provider.synthesize("hello", "en-IN")
    assert len(audio) == len("hello")
