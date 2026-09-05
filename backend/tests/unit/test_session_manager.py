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



def test_adopt_unknown_session_lets_memory_resume() -> None:
    # Simulates a client-persisted session_id after a backend restart / TTL expiry: adopting it
    # means follow-up turns accumulate memory again instead of being silently dropped every turn.
    m = InMemorySessionManager()
    persisted_id = "client-persisted-uuid"
    assert not m.exists(persisted_id)
    m.adopt(persisted_id)
    assert m.exists(persisted_id)
    m.record_turn(persisted_id, "my account id: e89f", "SELECT ...", "balance is X", "answered")
    h = m.history(persisted_id)
    assert len(h) == 1
    assert h[0].question == "my account id: e89f"


def test_adopt_does_not_clobber_existing_session() -> None:
    m = InMemorySessionManager()
    sid = m.create()
    m.record_turn(sid, "q0", "SELECT 0", "a0", "answered")
    m.adopt(sid)  # already exists -> must keep its turns
    assert [t.question for t in m.history(sid)] == ["q0"]


def test_adopt_empty_id_is_noop() -> None:
    m = InMemorySessionManager()
    m.adopt("")  # must not raise or create a phantom session
    assert not m.exists("")
