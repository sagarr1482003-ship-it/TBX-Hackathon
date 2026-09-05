"""Sensitive-data masking verification (RBI / DPDP posture).

Uses the real seed contract so the sensitive-column set is the one the system actually enforces.
Pure logic; no database and no model.
"""

from __future__ import annotations

from app.services.ingestion.contract import SEED_CONTRACTS
from app.services.pipeline.masking import (
    FULL_MASK,
    mask_account_number,
    mask_row,
    mask_value,
    sensitive_columns,
)


def test_sensitive_columns_from_contract() -> None:
    sensitive = sensitive_columns(SEED_CONTRACTS)
    assert "account_number" in sensitive
    assert "utr_number" in sensitive
    # non-sensitive columns are not included
    assert "transaction_amount" not in sensitive
    assert "bank_code" not in sensitive


def test_account_number_keeps_last_four() -> None:
    masked = mask_account_number("50200013729069")
    assert masked.endswith("9069")
    assert masked[:-4].strip("\u2022") == ""  # everything before is the mask glyph
    assert "5020001372" not in masked


def test_short_account_number_fully_masked() -> None:
    assert mask_account_number("1234") == "\u2022\u2022\u2022\u2022"


def test_utr_fully_masked() -> None:
    assert mask_value("utr_number", "jhI5nAdyb1qOEjmcB3JvWjC6tTO") == FULL_MASK


def test_non_sensitive_value_unchanged() -> None:
    assert mask_value("transaction_amount", "14866.00") == "14866.00"


def test_none_passes_through() -> None:
    assert mask_value("utr_number", None) is None
    assert mask_value("account_number", None) is None


def test_mask_row_only_touches_sensitive() -> None:
    sensitive = sensitive_columns(SEED_CONTRACTS)
    row = {
        "account_id": "a1",
        "account_number": "50200013729069",
        "available_balance": "91993.88",
        "bank_code": "HDFC",
    }
    masked = mask_row(row, sensitive)
    assert masked["account_number"].endswith("9069")
    assert "50200013729069" != masked["account_number"]
    # non-sensitive untouched
    assert masked["available_balance"] == "91993.88"
    assert masked["bank_code"] == "HDFC"
    assert masked["account_id"] == "a1"
