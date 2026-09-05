"""Deterministic calculator tools verification (pure, no Groq/DB)."""

from __future__ import annotations

from decimal import Decimal

from app.services.pipeline.calculators import (
    anomaly_calculator,
    cashflow_calculator,
    gst_calculator,
)


def test_gst_back_calculation_18pct() -> None:
    rows = [{"transaction_amount": Decimal("1180.00")}]
    r = gst_calculator(rows, ["transaction_amount"], rate=0.18)
    assert r["applicable"]
    assert r["taxable_base"] == "1000.00"   # 1180 / 1.18
    assert r["gst_total"] == "180.00"        # 1180 - 1000
    assert r["cgst"] == "90.00" and r["sgst"] == "90.00"
    assert r["assumed_rate"] == 0.18


def test_gst_no_amount_column() -> None:
    r = gst_calculator([{"bank_name": "HDFC"}], ["bank_name"])
    assert r["applicable"] is False


def test_cashflow_net() -> None:
    rows = [
        {"transaction_type": "credit", "transaction_amount": Decimal("500")},
        {"transaction_type": "credit", "transaction_amount": Decimal("300")},
        {"transaction_type": "debit", "transaction_amount": Decimal("200")},
    ]
    r = cashflow_calculator(rows, ["transaction_type", "transaction_amount"])
    assert r["total_credits"] == "800.00"
    assert r["total_debits"] == "200.00"
    assert r["net_cash_flow"] == "600.00"
    assert r["inflow_outflow_ratio"] == 4.0


def test_cashflow_needs_type_column() -> None:
    r = cashflow_calculator([{"transaction_amount": Decimal("1")}], ["transaction_amount"])
    assert r["applicable"] is False


def test_anomaly_flags_spike() -> None:
    # 8 small values + one 50,000,000 spike (the seed's planted pattern).
    rows = [{"transaction_amount": Decimal(x)} for x in [10000, 10100, 9900, 10050, 9950,
                                                          10020, 9980, 10010]]
    rows.append({"transaction_amount": Decimal("50000000")})
    r = anomaly_calculator(rows, ["transaction_amount"])
    assert r["applicable"]
    assert r["flagged_count"] >= 1
    assert r["flags"][0]["value"] == "50000000"


def test_anomaly_insufficient_history() -> None:
    r = anomaly_calculator([{"transaction_amount": Decimal("1")}], ["transaction_amount"])
    assert r["applicable"] is False
