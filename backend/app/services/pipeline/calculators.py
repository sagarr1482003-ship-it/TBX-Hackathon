"""Deterministic financial calculators — pure functions over executed result rows.

These are the Answer_Composer's "tools". The composer LLM decides WHICH calculator applies to the
user's question and phrases the result; the arithmetic is done here in ``Decimal`` (never by the
LLM), so every figure stays grounded in the executed data.

Each calculator takes the executed rows (list of dicts) and returns a small result dict the
composer can state verbatim. Rates/thresholds that are NOT in the data are explicit inputs and are
echoed back so the answer can state the assumption honestly.

Tools:
  * gst_calculator      — back-calculate GST from tax-inclusive amounts (rate is an input).
  * cashflow_calculator — net cash flow = Σcredits − Σdebits (+ inflow/outflow).
  * anomaly_calculator  — modified z-score outliers over per-entity amounts (reuses anomaly rule).
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation


def _dec(v) -> Decimal | None:
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, Decimal):
        return v
    try:
        return Decimal(str(v).replace(",", "").strip())
    except (InvalidOperation, ValueError):
        return None


def _amount_column(columns: list[str]) -> str | None:
    """Pick the monetary column to operate on."""
    for c in columns:
        if c in ("transaction_amount", "amount", "available_balance", "total"):
            return c
    return None


def _numeric_column(rows: list[dict], columns: list[str]) -> str | None:
    """A named amount column, else the single column whose values are numeric (e.g. a SUM alias)."""
    named = _amount_column(columns)
    if named is not None:
        return named
    numeric_cols = [c for c in columns if rows and _dec(rows[0].get(c)) is not None]
    return numeric_cols[0] if len(numeric_cols) == 1 else None


# --------------------------------------------------------------------------------------
def gst_calculator(rows: list[dict], columns: list[str], rate: float = 0.18) -> dict:
    """Back-calculate GST assuming amounts are tax-INCLUSIVE (rate is an explicit assumption).

    base = amount / (1 + rate);  gst = amount − base;  CGST = SGST = gst/2.
    Sums over the amount column across all rows.
    """
    col = _numeric_column(rows, columns)
    if col is None:
        return {"applicable": False, "reason": "no monetary column in result"}
    r = Decimal(str(rate))
    total_amount = Decimal("0")
    n = 0
    for row in rows:
        a = _dec(row.get(col))
        if a is not None:
            total_amount += a
            n += 1
    if n == 0:
        return {"applicable": False, "reason": "no numeric amounts"}
    base = (total_amount / (Decimal("1") + r)).quantize(Decimal("0.01"))
    gst = (total_amount - base).quantize(Decimal("0.01"))
    half = (gst / Decimal("2")).quantize(Decimal("0.01"))
    return {
        "applicable": True,
        "assumed_rate": float(rate),
        "assumption": f"amounts treated as GST-inclusive at {rate * 100:.0f}%",
        "gross_amount": str(total_amount.quantize(Decimal("0.01"))),
        "taxable_base": str(base),
        "gst_total": str(gst),
        "cgst": str(half),
        "sgst": str(half),
        "rows_used": n,
        "source_column": col,
    }


def cashflow_calculator(rows: list[dict], columns: list[str]) -> dict:
    """Net cash flow = Σcredits − Σdebits, using transaction_type + amount columns."""
    amt = _amount_column(columns)
    if amt is None or "transaction_type" not in columns:
        return {"applicable": False, "reason": "need transaction_type + amount columns"}
    credits = Decimal("0")
    debits = Decimal("0")
    for row in rows:
        a = _dec(row.get(amt))
        if a is None:
            continue
        if str(row.get("transaction_type")).lower() == "credit":
            credits += a
        elif str(row.get("transaction_type")).lower() == "debit":
            debits += a
    net = credits - debits
    ratio = float(credits / debits) if debits != 0 else None
    return {
        "applicable": True,
        "total_credits": str(credits.quantize(Decimal("0.01"))),
        "total_debits": str(debits.quantize(Decimal("0.01"))),
        "net_cash_flow": str(net.quantize(Decimal("0.01"))),
        "inflow_outflow_ratio": round(ratio, 4) if ratio is not None else None,
    }


def anomaly_calculator(
    rows: list[dict], columns: list[str], entity_col: str | None = None
) -> dict:
    """Flag outlier amounts via the modified z-score rule (reuses the verified anomaly logic).

    Treats each row's amount as a value in a single series (or per entity when entity_col given).
    """
    from app.services.pipeline.anomaly import AnomalyConfig, evaluate_entity

    amt = _amount_column(columns)
    if amt is None:
        return {"applicable": False, "reason": "no monetary column in result"}
    values = [(_dec(r.get(amt)), r) for r in rows]
    series = [v for v, _ in values if v is not None]
    if len(series) < AnomalyConfig().min_history_count:
        return {"applicable": False, "reason": "insufficient history for anomaly detection"}

    config = AnomalyConfig()
    flags = []
    for v, row in values:
        if v is None:
            continue
        history = [x for x in series if x is not v]
        res = evaluate_entity(str(row.get(entity_col, "series")), v, history, config)
        from app.services.pipeline.anomaly import AnomalyFlag

        if isinstance(res, AnomalyFlag):
            flags.append({
                "value": str(v),
                "median": str(res.median),
                "z_score": str(res.z_score) if res.z_score is not None else None,
                "kind": res.kind,
            })
    flags.sort(key=lambda f: Decimal(f["value"]), reverse=True)
    return {
        "applicable": True,
        "flagged_count": len(flags),
        "flags": flags[:5],
        "source_column": amt,
    }


TOOLS = {
    "gst": gst_calculator,
    "cashflow": cashflow_calculator,
    "anomaly": anomaly_calculator,
}
