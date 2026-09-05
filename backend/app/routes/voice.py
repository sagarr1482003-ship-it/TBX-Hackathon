"""Voice routes — Sarvam STT in, pipeline out (SSE), and TTS for spoken answers.

* POST /api/voice/stream  (multipart: file=<audio>, optional language_code)
    -> transcribes the audio with Sarvam STT, then streams the SAME pipeline trace as the text
       chat endpoint (intake ... completion) as SSE. A leading ``transcript`` event carries the
       recognised text + confidence so the FE can show "you said: ...".

* POST /api/voice/tts   (JSON: {text, language_code?})
    -> returns base64 WAV of the spoken answer (the FE plays it). Kept separate so the FE speaks
       the final 1-2 sentence answer after the stream completes (and can play a filler clip while
       the stream runs).

Both reuse the Sarvam client and the shared pipeline factory.
"""

from __future__ import annotations

import base64
import json

from fastapi import APIRouter, File, Form, UploadFile
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from app.config import get_settings
from app.services.model.sarvam_voice import SarvamVoiceClient
from app.services.pipeline.pipeline_factory import build_pipeline

router = APIRouter(prefix="/api/voice", tags=["voice"])


def _client() -> SarvamVoiceClient:
    s = get_settings()
    return SarvamVoiceClient(
        api_key=s.sarvam_api_key or "",
        stt_model=s.sarvam_stt_model,
        stt_mode=s.sarvam_stt_mode,
        tts_model=s.sarvam_tts_model,
        speaker=s.sarvam_speaker or "shubh",
        pace=s.sarvam_pace,
    )


@router.post("/stream")
async def voice_stream(
    file: UploadFile = File(...),
    language_code: str | None = Form(default=None),
):
    """Transcribe uploaded audio, then stream the pipeline trace as SSE (same events as chat)."""
    audio = await file.read()
    client = _client()
    transcript = client.transcribe(
        audio, filename=file.filename or "audio.wav", language_code=language_code
    )
    pipeline, pool = build_pipeline()

    async def event_generator():
        # Leading event: what we heard (FE shows "you said ...").
        yield {
            "event": "transcript",
            "data": json.dumps(
                {
                    "text": transcript.text,
                    "language_code": transcript.language_code,
                    "confidence": transcript.confidence,
                },
                default=str,
            ),
        }
        try:
            async for evt in pipeline.run_stream(transcript.text):
                yield {"event": evt["event"], "data": json.dumps(evt["data"], default=str)}
        finally:
            pool.close()

    return EventSourceResponse(event_generator())


class TtsRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=2500)
    language_code: str = Field(default="en-IN")


@router.post("/tts")
async def voice_tts(body: TtsRequest):
    """Synthesise ``text`` to speech; returns {audio_base64, format}."""
    client = _client()
    audio = client.synthesize(body.text, language_code=body.language_code)
    return {"audio_base64": base64.b64encode(audio).decode("ascii"), "format": "wav"}
