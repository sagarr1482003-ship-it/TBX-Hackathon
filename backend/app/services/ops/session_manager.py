"""In-memory session manager — short-term conversation memory keyed by session_id.

Single-process demo store: creates sessions, records each turn (question, resolved SQL, answer),
and returns the last N turns as follow-up context so the pipeline can resolve "what about
credits?" / "and per bank?" against the previous query.

Kept behind a small interface so it can be swapped for a PostgreSQL-backed store (the
``ops.sessions`` / ``ops.turns`` tables already exist) without touching the pipeline or routes.
Not multi-worker safe (in-process dict) — fine for the single-process demo; the Postgres swap
removes that limitation.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from threading import Lock

DEFAULT_MAX_TURNS = 10
DEFAULT_TTL_SECONDS = 30 * 60  # 30 minutes idle


@dataclass
class Turn:
    question: str
    resolved_sql: str | None
    answer: str | None
    outcome: str


@dataclass
class Session:
    session_id: str
    created_at: float
    last_seen: float
    turns: list[Turn] = field(default_factory=list)


class InMemorySessionManager:
    def __init__(self, max_turns: int = DEFAULT_MAX_TURNS, ttl_seconds: int = DEFAULT_TTL_SECONDS):
        self._sessions: dict[str, Session] = {}
        self._lock = Lock()
        self._max_turns = max_turns
        self._ttl = ttl_seconds

    def create(self) -> str:
        sid = str(uuid.uuid4())
        now = time.time()
        with self._lock:
            self._sessions[sid] = Session(session_id=sid, created_at=now, last_seen=now)
        return sid

    def _expired(self, s: Session, now: float) -> bool:
        return (now - s.last_seen) > self._ttl

    def get(self, session_id: str) -> Session | None:
        now = time.time()
        with self._lock:
            s = self._sessions.get(session_id)
            if s is None:
                return None
            if self._expired(s, now):
                # Idle timeout: discard stale conversation state (fresh context next turn).
                del self._sessions[session_id]
                return None
            s.last_seen = now
            return s

    def history(self, session_id: str) -> list[Turn]:
        """Return the last N turns for follow-up context (empty if unknown/expired)."""
        s = self.get(session_id)
        return list(s.turns[-self._max_turns :]) if s else []

    def record_turn(
        self, session_id: str, question: str, resolved_sql: str | None,
        answer: str | None, outcome: str,
    ) -> None:
        """Append a completed turn. Only successful turns carry useful follow-up context, but we
        record all outcomes so the FE can show history; the pipeline uses answered turns."""
        now = time.time()
        with self._lock:
            s = self._sessions.get(session_id)
            if s is None or self._expired(s, now):
                return
            s.turns.append(Turn(question, resolved_sql, answer, outcome))
            s.turns = s.turns[-self._max_turns :]
            s.last_seen = now

    def exists(self, session_id: str) -> bool:
        return self.get(session_id) is not None


# Process-wide singleton for the demo.
_MANAGER: InMemorySessionManager | None = None


def get_session_manager() -> InMemorySessionManager:
    global _MANAGER
    if _MANAGER is None:
        _MANAGER = InMemorySessionManager()
    return _MANAGER
