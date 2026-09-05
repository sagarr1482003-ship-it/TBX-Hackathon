"""Stub model provider (Task 1.6) — scripted per-role structured outputs, no network.

Supports valid, adversarial, non-conforming, truncated, slow and failing scripts, and counts
calls and tokens so budget property tests can assert enforcement without a real provider.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class StubResponse:
    content: Any
    input_tokens: int = 10
    output_tokens: int = 20
    stop_reason: str = "end_turn"  # or "max_tokens" for truncation
    raise_error: Exception | None = None


@dataclass
class StubModelProvider:
    """Returns scripted responses keyed by role; records call and token counts."""

    scripts: dict[str, list[StubResponse]] = field(default_factory=dict)
    calls: list[tuple[str, str]] = field(default_factory=list)  # (role, prompt)
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    _cursor: dict[str, int] = field(default_factory=dict)

    def call(self, role: str, prompt: str) -> StubResponse:
        self.calls.append((role, prompt))
        idx = self._cursor.get(role, 0)
        script = self.scripts.get(role, [])
        if not script:
            resp = StubResponse(content={"ok": True})
        else:
            resp = script[min(idx, len(script) - 1)]
            self._cursor[role] = idx + 1
        if resp.raise_error is not None:
            raise resp.raise_error
        self.total_input_tokens += resp.input_tokens
        self.total_output_tokens += resp.output_tokens
        return resp

    @property
    def call_count(self) -> int:
        return len(self.calls)


@dataclass
class StubEmbedder:
    """Deterministic hash-based embeddings at a configured dimension (no network)."""

    dimension: int = 384

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(t) for t in texts]

    def _embed_one(self, text: str) -> list[float]:
        import hashlib

        digest = hashlib.sha256(text.encode("utf-8")).digest()
        # Expand the digest deterministically to the requested dimension.
        vals: list[float] = []
        i = 0
        while len(vals) < self.dimension:
            b = digest[i % len(digest)]
            vals.append((b / 255.0) * 2.0 - 1.0)
            i += 1
        # L2-normalise.
        norm = sum(v * v for v in vals) ** 0.5 or 1.0
        return [v / norm for v in vals]
