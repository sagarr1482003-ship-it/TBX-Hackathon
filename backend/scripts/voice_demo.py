"""Test Sarvam voice: TTS, STT round-trip, and a full voice->pipeline->spoken-answer flow.

Usage (needs SARVAM_API_KEY in backend/.env; the pipeline flow also needs GROQ_API_KEY + DB):

    # 1) TTS only: synthesise text to runs/tts_out.wav
    python -m scripts.voice_demo tts "There are 2538 debit transactions."

    # 2) STT round-trip: TTS a phrase, then transcribe it back
    python -m scripts.voice_demo roundtrip "how many debit transactions are there"

    # 3) Full voice flow: TTS a question -> STT -> pipeline -> spoken answer (runs/answer.wav)
    python -m scripts.voice_demo ask "how many debit transactions are there"
"""

from __future__ import annotations

import pathlib
import sys

from app.config import get_settings
from app.services.model.sarvam_voice import SarvamVoiceClient

RUNS = pathlib.Path("runs")


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


def _save(name: str, audio: bytes) -> str:
    RUNS.mkdir(exist_ok=True)
    p = RUNS / name
    p.write_bytes(audio)
    return str(p)


def cmd_tts(text: str) -> None:
    audio = _client().synthesize(text, language_code="en-IN")
    print(f"TTS ok: {len(audio)} bytes -> {_save('tts_out.wav', audio)}")


def cmd_roundtrip(text: str) -> None:
    c = _client()
    audio = c.synthesize(text, language_code="en-IN")
    path = _save("roundtrip.wav", audio)
    t = c.transcribe(audio, filename="roundtrip.wav")
    print(f"synthesised {len(audio)} bytes -> {path}")
    print(f"transcript: {t.text!r}  lang={t.language_code}  conf={t.confidence}")


def cmd_ask(question_text: str) -> None:
    c = _client()
    # Simulate a mic utterance: synthesise the question, then transcribe it (STT).
    utterance = c.synthesize(question_text, language_code="en-IN")
    t = c.transcribe(utterance, filename="utterance.wav")
    print(f"heard (STT): {t.text!r}  lang={t.language_code}  conf={t.confidence}")

    # Run the transcript through the SAME text pipeline.
    from scripts.run_pipeline import _build

    pipeline, pool = _build()
    try:
        r = pipeline.run(t.text)
    finally:
        pool.close()
    print(f"outcome: {r.outcome}   answer: {r.answer}")
    if r.answer:
        # Speak the 1-2 sentence answer back.
        audio = c.synthesize(r.answer, language_code="en-IN")
        print(f"spoken answer: {len(audio)} bytes -> {_save('answer.wav', audio)}")
    if r.chart:
        print(f"chart: {r.chart['type']} ({len(r.chart['points'])} points) — FE renders this")


def main() -> None:
    if len(sys.argv) < 3:
        print(__doc__)
        return
    cmd, text = sys.argv[1], " ".join(sys.argv[2:])
    {"tts": cmd_tts, "roundtrip": cmd_roundtrip, "ask": cmd_ask}.get(cmd, lambda _: print(__doc__))(
        text
    )


if __name__ == "__main__":
    main()
