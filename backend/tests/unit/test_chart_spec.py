"""Chart-spec builder verification (pure, no DB/model)."""

from __future__ import annotations

from decimal import Decimal

from app.services.pipeline.chart_spec import build_chart_spec


def test_pie_for_few_categories() -> None:
    cols = ["transaction_type", "total"]
    rows = [{"transaction_type": "credit", "total": Decimal("100")},
            {"transaction_type": "debit", "total": Decimal("200")}]
    spec = build_chart_spec(cols, rows)
    assert spec is not None
    assert spec.type == "pie"
    assert spec.label_field == "transaction_type"
    assert spec.value_field == "total"
    assert [p.value for p in spec.points] == [100.0, 200.0]


def test_line_for_date_label() -> None:
    cols = ["month", "txn_count"]
    rows = [{"month": f"2025-{m:02d}", "txn_count": m * 10} for m in range(1, 8)]
    spec = build_chart_spec(cols, rows)
    assert spec is not None
    assert spec.type == "line"


def test_bar_for_many_categories() -> None:
    cols = ["bank_name", "total"]
    rows = [{"bank_name": f"BANK{i}", "total": i} for i in range(10)]
    spec = build_chart_spec(cols, rows)
    assert spec is not None
    assert spec.type == "bar"


def test_none_for_scalar() -> None:
    assert build_chart_spec(["count"], [{"count": 2538}]) is None


def test_none_for_wide_listing() -> None:
    cols = ["a", "b", "c"]
    rows = [{"a": 1, "b": 2, "c": 3}, {"a": 4, "b": 5, "c": 6}]
    assert build_chart_spec(cols, rows) is None


def test_label_value_order_agnostic() -> None:
    # value first, label second still detected
    spec = build_chart_spec(["total", "bank_name"],
                            [{"total": 5, "bank_name": "X"}, {"total": 6, "bank_name": "Y"}])
    assert spec is not None
    assert spec.label_field == "bank_name"
    assert spec.value_field == "total"
