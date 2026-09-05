"""SQL generator output-parsing verification (pure, no network).

The generator returns either SQL or a CLARIFY follow-up in a single call; a stub agent lets us
verify the branch logic without Groq.
"""

from __future__ import annotations

from app.services.model.sql_generator import SqlGenerator, extract_sql


class _FakeAgent:
    def __init__(self, text: str) -> None:
        self._text = text

    def __call__(self, prompt):  # noqa: ARG002
        return self._text


def _gen(text: str):
    return SqlGenerator(lambda: _FakeAgent(text)).generate("q")


def test_returns_sql() -> None:
    c = _gen("SELECT count(*) FROM transaction WHERE transaction_type = 'debit'")
    assert c.clarification is None
    assert c.sql.lower().startswith("select")


def test_returns_clarification() -> None:
    c = _gen("CLARIFY: Which account or time period do you mean?")
    assert c.clarification is not None
    assert "which account" in c.clarification.lower()
    assert c.sql == ""


def test_extract_sql_strips_fences_and_label() -> None:
    assert extract_sql("```sql\nSELECT 1\n```").upper().startswith("SELECT 1")
    assert extract_sql("SQL: SELECT 1;").upper() == "SELECT 1"
    assert extract_sql("sorry, no idea") == ""
