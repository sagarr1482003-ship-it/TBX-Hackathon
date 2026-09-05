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



class _Turn:
    """Minimal Turn-like object for _with_history (duck-typed: question/resolved_sql/answer)."""

    def __init__(self, question: str, resolved_sql: str | None, answer: str | None) -> None:
        self.question = question
        self.resolved_sql = resolved_sql
        self.answer = answer


def test_with_history_empty() -> None:
    prompt = SqlGenerator._with_history("how many debits?", None)
    assert prompt == "Question: how many debits?\nSQL:"


def test_with_history_carries_prior_answer_and_identifier() -> None:
    # The account id is set in a plain-language turn; a later "my transactions" follow-up must be
    # able to bind to it, so the prior answer (which names the account) is included in the prompt.
    acct = "e89fa331-d623-e859-7424-4cdd48d9aaa4"
    history = [
        _Turn(
            f"my account id: {acct}",
            f"SELECT available_balance FROM account WHERE account_id = '{acct}'",
            f"Your account {acct} has an available balance of INR 95471170.96 "
            "with bank code SBIN.",
        ),
    ]
    prompt = SqlGenerator._with_history("what is my transaction in icici bank", history)
    # The resolved identifier is present via both the prior SQL and the prior answer snippet.
    assert acct in prompt
    assert "A: Your account" in prompt
    assert prompt.strip().endswith("Question: what is my transaction in icici bank\nSQL:")


def test_with_history_skips_turns_without_question() -> None:
    history = [_Turn("", "SELECT 1", "a"), _Turn("real q", "SELECT 2", "answer two")]
    prompt = SqlGenerator._with_history("follow up", history)
    assert "SELECT 2" in prompt
    assert "SELECT 1" not in prompt  # the question-less turn is skipped
