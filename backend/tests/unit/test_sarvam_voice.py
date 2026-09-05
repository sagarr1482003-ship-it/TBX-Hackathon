"""Sarvam voice client verification (no network).

Only construction/config is exercised without a key; live STT/TTS is tested via scripts/voice_demo
with SARVAM_API_KEY (a `live`-style manual check, not in the default suite).
"""

from __future__ import annotations

import pytest

from app.services.model.sarvam_voice import TTS_MAX_CHARS, SarvamError, SarvamVoiceClient


def test_missing_key_rejected() -> None:
    with pytest.raises(SarvamError):
        SarvamVoiceClient(api_key="")


def test_constructs_with_key() -> None:
    c = SarvamVoiceClient(api_key="test-key", speaker="shubh", pace=1.0)
    assert c._stt_model.startswith("saaras")
    assert c._tts_model.startswith("bulbul")


def test_tts_char_limit_constant() -> None:
    assert TTS_MAX_CHARS == 2500
