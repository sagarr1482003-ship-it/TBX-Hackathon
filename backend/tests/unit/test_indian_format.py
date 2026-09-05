"""Indian number/currency formatting verification."""

from __future__ import annotations

from app.services.pipeline.indian_format import indian_group, indian_words, inr


def test_indian_grouping() -> None:
    assert indian_group("77597697.30") == "7,75,97,697.30"
    assert indian_group("100000") == "1,00,000.00"
    assert indian_group("999.5") == "999.50"
    assert indian_group("1234567.89") == "12,34,567.89"


def test_inr_prefix() -> None:
    assert inr("77597697.30") == "INR 7,75,97,697.30"


def test_indian_words() -> None:
    assert indian_words("775976978.30") == "77.60 crore"
    assert indian_words("520000") == "5.20 lakh"
    assert indian_words("900") == "900.00"


def test_negative() -> None:
    assert indian_group("-2500000") == "-25,00,000.00"
