"""Agent pipeline wiring verification (no network, Strands stubbed).

Stubs the Strands agent by faking ``structured_output`` so the generate -> validate -> review
wiring is proven without a key:
  * a valid SELECT flows through validation and is reviewed;
  * a hostile statement is rejected by the SQL_Validator BEFORE the reviewer runs;
  * an unknown column is rejected by schema conformance;
  * an empty SQL yields generation_failed (no figure).
"""

from __future__ import annotations

from app.services.model.reviewer import ReviewerAgent
from app.services.model.sql_generator import SqlGenerator
from app.services.pipeline.simple_pipeline import SimplePipeline


class _FakeAgent:
    """Stands in for a Strands Agent: calling it returns a fixed text response."""

    def __init__(self, text) -> None:
        self._text = text

    def __call__(self, prompt):  # noqa: ARG002 - mirror the real signature
        return self._text


def _pipeline(gen_text: str, review_text: str) -> SimplePipeline:
    generator = SqlGenerator(lambda: _FakeAgent(gen_text))
    reviewer = ReviewerAgent(lambda: _FakeAgent(review_text))
    return SimplePipeline(generator, reviewer)


def test_valid_select_flows_to_review() -> None:
    p = _pipeline(
        "SELECT transaction_type, count(*) FROM transaction GROUP BY transaction_type",
        "VERDICT: approve\nREASON: correct grouping",
    )
    r = p.run("how many credits vs debits?")
    assert r.validation_ok is True
    assert r.canonical_sql is not None
    assert r.outcome == "approve"


def test_hostile_sql_rejected_before_review() -> None:
    p = _pipeline("DROP TABLE transaction", "VERDICT: approve\nREASON: never reached")
    r = p.run("delete everything")
    # A non-SELECT never becomes a runnable candidate and the reviewer is never reached.
    assert r.canonical_sql is None
    assert r.verdict is None
    assert r.outcome in ("validation_rejected", "generation_failed")


def test_unknown_column_rejected() -> None:
    p = _pipeline("SELECT ssn FROM account", "VERDICT: approve\nREASON: x")
    r = p.run("show ssns")
    assert r.validation_ok is False
    assert r.outcome == "validation_rejected"


def test_generation_failure_yields_no_figure() -> None:
    p = _pipeline("sorry I cannot help", "VERDICT: approve\nREASON: x")
    r = p.run("something")
    assert r.outcome == "generation_failed"
    assert r.canonical_sql is None
