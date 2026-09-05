"""Sarvam voice client — speech-to-text (Saarika) and text-to-speech (Bulbul).

Thin httpx client over the Sarvam REST API (confirmed against the docs):

  * STT  : POST https://api.sarvam.ai/speech-to-text  (multipart ``file``; model saaras:v3;
           optional ``language_code``, ``mode``). Response: {transcript, language_code,
           language_probability}. ``language_probability`` is the only confidence Sarvam returns,
           and only when the language is auto-detected — otherwise there is no per-utterance
           confidence (recorded deviation).
  * TTS  : POST https://api.sarvam.ai/text-to-speech  (JSON {text, language_code, speaker, model,
           pace}). Response: {audios: [base64 wav]}. For bulbul:v3, pitch/loudness are NOT sent
           (unsupported); pace range 0.5–2.0; max 2500 chars per request.

Auth header: ``api-subscription-key``. This client is used behind the Voice_Service; the pipeline
and grounding are unchanged — a transcript is fed to the same text pipeline, and the answer text is
synthesised.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass

import httpx

STT_URL = "https://api.sarvam.ai/speech-to-text"
TTS_URL = "https://api.sarvam.ai/text-to-speech"
TTS_MAX_CHARS = 2500  # bulbul:v3 limit


class SarvamError(Exception):
    """Raised on a Sarvam API error or unparseable response."""


@dataclass
class Transcript:
    text: str
    language_code: str | None
    confidence: float | None  # language_probability when auto-detected, else None


class SarvamVoiceClient:
    def __init__(
        self,
        api_key: str,
        *,
        stt_model: str = "saaras:v3",
        stt_mode: str = "codemix",
        tts_model: str = "bulbul:v3",
        speaker: str = "shubh",
        pace: float = 1.0,
        timeout_s: float = 20.0,
    ) -> None:
        if not api_key:
            raise SarvamError("SARVAM_API_KEY is not configured")
        self._headers = {"api-subscription-key": api_key}
        self._stt_model = stt_model
        self._stt_mode = stt_mode
        self._tts_model = tts_model
        self._speaker = speaker
        self._pace = pace
        self._timeout_s = timeout_s

    # ---- STT -------------------------------------------------------------------------
    def transcribe(
        self, audio: bytes, filename: str = "audio.wav", language_code: str | None = None
    ) -> Transcript:
        data: dict = {"model": self._stt_model}
        if self._stt_model.startswith("saaras:v3"):
            data["mode"] = self._stt_mode
        # Omit language_code to request auto-detection (returns language_probability).
        if language_code:
            data["language_code"] = language_code
        files = {"file": (filename, audio, "audio/wav")}
        try:
            resp = httpx.post(
                STT_URL, headers=self._headers, data=data, files=files, timeout=self._timeout_s
            )
        except httpx.HTTPError as exc:
            raise SarvamError(f"Sarvam STT transport error: {exc}") from exc
        if resp.status_code != 200:
            raise SarvamError(f"Sarvam STT HTTP {resp.status_code}: {resp.text[:300]}")
        body = resp.json()
        return Transcript(
            text=body.get("transcript", ""),
            language_code=body.get("language_code"),
            confidence=body.get("language_probability"),
        )

    # ---- TTS -------------------------------------------------------------------------
    def synthesize(self, text: str, language_code: str = "en-IN") -> bytes:
        """Synthesise up to TTS_MAX_CHARS of text to WAV bytes (first audio segment)."""
        payload: dict = {
            "text": text[:TTS_MAX_CHARS],
            "language_code": language_code,
            "speaker": self._speaker,
            "model": self._tts_model,
            "pace": self._pace,
        }
        # bulbul:v3 does not accept pitch/loudness — deliberately omitted.
        try:
            resp = httpx.post(
                TTS_URL, headers=self._headers, json=payload, timeout=self._timeout_s
            )
        except httpx.HTTPError as exc:
            raise SarvamError(f"Sarvam TTS transport error: {exc}") from exc
        if resp.status_code != 200:
            raise SarvamError(f"Sarvam TTS HTTP {resp.status_code}: {resp.text[:300]}")
        audios = resp.json().get("audios") or []
        if not audios:
            raise SarvamError("Sarvam TTS returned no audio")
        return base64.b64decode(audios[0])
