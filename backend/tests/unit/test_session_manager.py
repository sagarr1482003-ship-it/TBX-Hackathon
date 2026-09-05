"""In-memory session manager verification (pure, no network/DB)."""

from __future__ import annotations

from app.services.ops.session_manager import InMemorySessionManager


def test_create_and_exists() -> None:
    m = InMemorySessionManager()
    sid = m.create()
    assert m.exists(sid)
    assert not m.exists("nope")


def test_record_and_history() -> None:
    m = InMemorySessionManager(max_turns=3)
    sid = m.create()
    for i in range(5):
        m.record_turn(sid, f"q{i}", f"SELECT {i}", f"a{i}", "answered")
    h = m.history(sid)
    assert len(h) == 3  # capped at max_turns
    assert [t.question for t in h] == ["q2", "q3", "q4"]  # most recent
    assert h[-1].resolved_sql == "SELECT 4"


def test_history_unknown_session_empty() -> None:
    m = InMemorySessionManager()
    assert m.history("missing") == []


def test_ttl_expiry() -> None:
    m = InMemorySessionManager(ttl_seconds=0)  # expires immediately
    sid = m.create()
    m.record_turn(sid, "q", "SELECT 1", "a", "answered")
    # ttl=0 -> next access sees it as expired and discards it
    assert m.history(sid) == []
    assert not m.exists(sid)


def test_record_into_missing_session_is_noop() -> None:
    m = InMemorySessionManager()
    m.record_turn("ghost", "q", "SELECT 1", "a", "answered")  # must not raise
    assert m.history("ghost") == []
