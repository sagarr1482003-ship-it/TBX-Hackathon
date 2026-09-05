"""Agent pipeline wiring verification (no network, Strands stubbed).

Stubs the Strands agent by faking ``structured_output`` so the generate -> validate -> review
wiring is proven without a key:
  * a valid SELECT flows through validation and is reviewed;
  * a hostile statement is rejected by the SQL_Validator BEFORE the reviewer runs;
  * an unknown column is rejected by schema conformance;
  * an empty SQL yields generation_failed (no figure).
"""

from __future__ import annotations

from app.services.model.reviewer import ReviewerAgent, ReviewVerdict
from app.services.model.sql_generator import SqlCandidate, SqlGenerator
from app.services.pipeline.simple_pipeline import SimplePipeline


class _FakeAgent:
    """Stands in for a Strands Agent: structured_output returns a pre-set object."""

    def __init__(self, obj) -> None:
        self._obj = obj

    def structured_output(self, model, prompt):  # noqa: ARG002 - mirror the real signature
        return self._obj


def _pipeline(candidate: SqlCandidate, verdict: ReviewVerdict) -> SimplePipeline:
    generator = SqlGenerator(lambda: _FakeAgent(candidate))
    reviewer = ReviewerAgent(lambda: _FakeAgent(verdict))
    return SimplePipeline(generator, reviewer)


def test_valid_select_flows_to_review() -> None:
    p = _pipeline(
        SqlCandidate(
            sql="SELECT transaction_type, count(*) FROM transaction GROUP BY transaction_type",
            tables=["transaction"],
            columns=["transaction_type"],
        ),
        ReviewVerdict(verdict="approve", reason="correct grouping"),
    )
    r = p.run("how many credits vs debits?")
    assert r.validation_ok is True
    assert r.canonical_sql is not None
    assert r.outcome == "approve"


def test_hostile_sql_rejected_before_review() -> None:
    p = _pipeline(
        SqlCandidate(sql="DROP TABLE transaction"),
        ReviewVerdict(verdict="approve", reason="should never be reached"),
    )
    r = p.run("delete everything")
    assert r.validation_ok is False
    assert r.verdict is None  # reviewer not reached
    assert r.outcome == "validation_rejected"


def test_unknown_column_rejected() -> None:
    p = _pipeline(
        SqlCandidate(sql="SELECT ssn FROM account", tables=["account"], columns=["ssn"]),
        ReviewVerdict(verdict="approve", reason="x"),
    )
    r = p.run("show ssns")
    assert r.validation_ok is False
    assert r.outcome == "validation_rejected"


def test_generation_failure_yields_no_figure() -> None:
    p = _pipeline(
        SqlCandidate(sql="   "),
        ReviewVerdict(verdict="approve", reason="x"),
    )
    r = p.run("something")
    assert r.outcome == "generation_failed"
    assert r.canonical_sql is None
