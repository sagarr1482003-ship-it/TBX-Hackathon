"""Stub voice provider (Task 1.6) — fixed transcripts, silent audio, scripted failures.

Covers the no-confidence-field case (Requirement 28.11) so the voice confirmation threshold path
is testable without Sarvam.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class StubTranscript:
    text: str
    language_code: str = "en-IN"
    confidence: float | None = 0.9  # None models a provider that omits confidence (R28.11)
    duration_s: float = 3.0


@dataclass
class StubVoiceProvider:
    transcripts: list[StubTranscript] = field(default_factory=list)
    fail_transcription: bool = False
    _cursor: int = 0

    def transcribe(self, audio: bytes, language_code: str | None = None) -> StubTranscript:
        if self.fail_transcription:
            raise RuntimeError("stub transcription failure")
        if not self.transcripts:
            return StubTranscript(text="what did acme spend last month")
        t = self.transcripts[min(self._cursor, len(self.transcripts) - 1)]
        self._cursor += 1
        return t

    def synthesize(self, text: str, language_code: str) -> bytes:
        # Silent audio payload sized to the text length (deterministic).
        return b"\x00" * max(1, len(text))
