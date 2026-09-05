"""Clarifier decision-parser verification (pure, no model)."""

from __future__ import annotations

from app.services.model.clarifier import parse_decision


def test_proceed() -> None:
    d = parse_decision("PROCEED")
    assert d.proceed is True
    assert d.question is None


def test_clarify_with_question() -> None:
    d = parse_decision("CLARIFY: Which bank or account did you mean?")
    assert d.proceed is False
    assert "which bank" in d.question.lower()


def test_clarify_takes_first_line() -> None:
    d = parse_decision("CLARIFY: For which month?\n(extra reasoning ignored)")
    assert d.proceed is False
    assert d.question == "For which month?"


def test_empty_clarify_falls_back_to_proceed() -> None:
    # A malformed/empty CLARIFY must not produce an empty follow-up.
    d = parse_decision("CLARIFY:")
    assert d.proceed is True


def test_unrecognised_defaults_to_proceed() -> None:
    d = parse_decision("I think this is answerable.")
    assert d.proceed is True
