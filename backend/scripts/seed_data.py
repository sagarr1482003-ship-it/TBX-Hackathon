"""Seed_Data_Generator (Requirement 8) — organiser bank/account/transaction schema.

Generates a deterministic synthetic dataset as CSV files under ``datasets/seed/``: bank, account
and transaction, plus a data dictionary. Modelled on the organiser sample data (IFSC bank codes,
credit/debit transactions, UPI/NEFT/IMPS/FT description formats, running balances).

Determinism (Requirement 8.3): all randomness comes from a single ``random.Random(seed)`` and the
output is written with a fixed column order, fixed row order and ``\n`` terminators, so a given
seed yields byte-identical files.

Thresholds guaranteed:
  * >= 10 banks, >= 40 accounts, >= 5000 transactions;
  * >= 12 consecutive calendar months of transaction history;
  * both transaction types (credit, debit) present in quantity;
  * >= 3 accounts whose largest transaction the anomaly rule flags;
  * edge rows: >= 50 transactions with a null non-key column (description / reference / utr),
    >= 20 transactions with amount exactly 0, >= 20 with amount below 0.

``account_number`` and ``utr_number`` are sensitive (masking is applied downstream in the answer
layer, not in the source data). Monetary columns are written with the ₹ symbol, thousands
separators and parentheses for negatives, exercising the Local_File_Connector's Req 6.4 parsing.

Run: ``python -m scripts.seed_data`` (defaults to seed 20240901 into ``datasets/seed``).
"""

from __future__ import annotations

import argparse
import csv
import io
import random
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

SEED_DEFAULT = 20240901
CURRENCY_SYMBOL = "\u20b9"  # ₹
THOUSANDS = ","

# 24 consecutive months (>= 12 required) ending 2026-06-30, matching the sample data window.
COVERAGE_FIRST = date(2024, 7, 1)
COVERAGE_LAST = date(2026, 6, 30)

TRANSACTION_TYPES = ["credit", "debit"]
PROGRAM_IDS = [21, 4, 46]

# Banks: (bank_code IFSC prefix, canonical all-caps name) — from the organiser sample.
BANKS: list[tuple[str, str]] = [
    ("HDFC", "HDFC BANK LIMITED"),
    ("ICIC", "ICICI BANK LIMITED"),
    ("SBIN", "STATE BANK OF INDIA"),
    ("UTIB", "AXIS BANK LIMITED"),
    ("KKBK", "KOTAK MAHINDRA BANK LIMITED"),
    ("CNRB", "CANARA BANK"),
    ("UBIN", "UNION BANK OF INDIA"),
    ("AUBL", "AU SMALL FINANCE BANK LIMITED"),
    ("TMBL", "TAMILNAD MERCANTILE BANK LIMITED"),
    ("RATN", "RBL BANK LIMITED"),
]

N_ACCOUNTS = 45  # >= 40
N_TRANSACTIONS = 5200  # >= 5000

N_NULL_NONKEY = 60  # >= 50 transactions with a null non-key column
N_ZERO_AMOUNT = 25  # >= 20 transactions with amount exactly 0
N_NEG_AMOUNT = 25  # >= 20 transactions with amount below 0

_DESC_TEMPLATES = [
    "UPI-{name}-XXXXXX{n4}-{code}0002125-{ref}",
    "NEFT  - {code}0001241 - {n8} - 124105002702 - {name}",
    "IMPS/P2A/{ref}/{code}/918020101986700/00/INET/9211/{name}",
    "FT -  {n8} -  50200013729069 - {name}",
    "NEFT/{ref}/{code}/{name}",
]
_MERCHANTS = [
    "SELECTION ELECTRONICS", "NAVYUG SELECTION", "SELECTION MOBILE", "SELECTIONMALIGAI",
    "SELECTRICITY TWO PRIVATE LIMITED", "UMANG SELECTION", "PARESH VIKRANT GHASE",
    "RELIANCEDIGITAL RETAIL LTD", "GAUTAM SINGH", "SELECT CITY SAKET DELHI",
]


def _fmt_money(value: Decimal) -> str:
    negative = value < 0
    absval = abs(value).quantize(Decimal("0.01"))
    int_part, frac_part = f"{absval:.2f}".split(".")
    grouped = ""
    while len(int_part) > 3:
        grouped = THOUSANDS + int_part[-3:] + grouped
        int_part = int_part[:-3]
    grouped = int_part + grouped
    body = f"{CURRENCY_SYMBOL}{grouped}.{frac_part}"
    return f"({body})" if negative else body


def _months_between(first: date, last: date) -> list[tuple[int, int]]:
    months: list[tuple[int, int]] = []
    y, m = first.year, first.month
    while (y, m) <= (last.year, last.month):
        months.append((y, m))
        m += 1
        if m > 12:
            m, y = 1, y + 1
    return months


def _random_timestamp_in_month(rng: random.Random, y: int, m: int) -> datetime:
    nxt = date(y + 1, 1, 1) if m == 12 else date(y, m + 1, 1)
    days = (nxt - date(y, m, 1)).days
    d = date(y, m, 1) + timedelta(days=rng.randint(0, days - 1))
    return datetime(
        d.year, d.month, d.day, rng.randint(0, 23), rng.randint(0, 59), rng.randint(0, 59)
    )


def _uuid(rng: random.Random) -> str:
    hexd = "0123456789abcdef"
    parts = [8, 4, 4, 4, 12]
    return "-".join("".join(rng.choice(hexd) for _ in range(n)) for n in parts)


def _utr(rng: random.Random) -> str:
    # A long opaque token, like the sample data's encrypted-looking UTRs.
    chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
    return "".join(rng.choice(chars) for _ in range(rng.randint(40, 60)))


def generate(seed: int = SEED_DEFAULT) -> dict[str, list[dict]]:
    """Generate all entities as ordered lists of row dicts. Pure and deterministic."""
    rng = random.Random(seed)

    # ---- bank ----------------------------------------------------------------------
    banks = [{"bank_code": code, "bank_name": name} for code, name in BANKS]
    bank_codes = [b["bank_code"] for b in banks]

    # ---- account -------------------------------------------------------------------
    accounts: list[dict] = []
    account_ids: list[str] = []
    for _ in range(N_ACCOUNTS):
        aid = _uuid(rng)
        account_ids.append(aid)
        balance = Decimal(rng.randint(-150_000_000, 250_000_000)) + Decimal(
            f"0.{rng.randint(0, 99):02d}"
        )
        accounts.append(
            {
                "account_id": aid,
                "entity_id": _uuid(rng),
                "account_number": str(rng.randint(10_000_000_000, 99_999_999_999_999)),
                "program_id": rng.choice(PROGRAM_IDS),
                "available_balance": balance,
                "bank_code": rng.choice(bank_codes),
            }
        )

    months = _months_between(COVERAGE_FIRST, COVERAGE_LAST)

    # ---- transaction ---------------------------------------------------------------
    transactions: list[dict] = []
    zero_idx = set(range(0, N_ZERO_AMOUNT))
    neg_idx = set(range(N_ZERO_AMOUNT, N_ZERO_AMOUNT + N_NEG_AMOUNT))
    _null_start = N_ZERO_AMOUNT + N_NEG_AMOUNT
    null_idx = set(range(_null_start, _null_start + N_NULL_NONKEY))

    # Accounts reserved purely as anomaly carriers (excluded from the random pool so their
    # history is a clean small-value baseline with a single large spike).
    anomaly_accounts = account_ids[:3]
    pool_accounts = account_ids[3:] or account_ids

    def _txn(account_id: str, ts: datetime, amount: Decimal, ttype: str, i: int) -> dict:
        merchant = rng.choice(_MERCHANTS)
        code = rng.choice(bank_codes)
        description: str | None = rng.choice(_DESC_TEMPLATES).format(
            name=merchant,
            code=code,
            n4=rng.randint(1000, 9999),
            n8=rng.randint(10_000_000, 99_999_999),
            ref=rng.randint(100_000_000_000, 999_999_999_999),
        )
        reference_id: str | None = f"S{rng.randint(1_000_000, 99_999_999)}"
        utr: str | None = _utr(rng) if rng.random() < 0.5 else None
        if i in null_idx:
            r = i % 3
            if r == 0:
                description = None
            elif r == 1:
                reference_id = None
            else:
                utr = None
        return {
            "transaction_id": _uuid(rng),
            "account_id": account_id,
            "transaction_date": ts.strftime("%Y-%m-%d %H:%M:%S.%f"),
            "transaction_type": ttype,
            "description": description,
            "transaction_amount": amount,
            "transaction_reference_id": reference_id,
            "utr_number": utr,
        }

    # Main body: random pool accounts, credit/debit, with the edge-row amounts.
    n_main = N_TRANSACTIONS - len(anomaly_accounts) * 9  # leave room for the anomaly block
    for i in range(n_main):
        y, m = months[i % len(months)]
        ts = _random_timestamp_in_month(rng, y, m)
        ttype = rng.choice(TRANSACTION_TYPES)
        if i in zero_idx:
            amount = Decimal("0.00")
        elif i in neg_idx:
            amount = Decimal(-rng.randint(100, 50_000)) - Decimal("0.50")
        else:
            amount = Decimal(rng.randint(100, 500_000)) + Decimal(f"0.{rng.randint(0, 99):02d}")
        transactions.append(_txn(rng.choice(pool_accounts), ts, amount, ttype, i))

    # Anomaly block: each carrier gets 8 stable ~10k debits + one 50,000,000 spike so the
    # modified z-score rule flags the spike. Indices past null_idx so no edge override applies.
    idx = n_main
    for aid in anomaly_accounts:
        for _ in range(8):
            y, m = months[idx % len(months)]
            ts = _random_timestamp_in_month(rng, y, m)
            amount = Decimal(rng.randint(9800, 10200)) + Decimal("0.00")
            transactions.append(_txn(aid, ts, amount, "debit", idx))
            idx += 1
        y, m = months[idx % len(months)]
        ts = _random_timestamp_in_month(rng, y, m)
        transactions.append(_txn(aid, ts, Decimal("50000000.00"), "debit", idx))
        idx += 1

    return {"bank": banks, "account": accounts, "transaction": transactions}


# ---- CSV writing (deterministic bytes) ---------------------------------------------
_COLUMNS: dict[str, list[str]] = {
    "bank": ["bank_code", "bank_name"],
    "account": [
        "account_id", "entity_id", "account_number", "program_id",
        "available_balance", "bank_code",
    ],
    "transaction": [
        "transaction_id", "account_id", "transaction_date", "transaction_type",
        "description", "transaction_amount", "transaction_reference_id", "utr_number",
    ],
}
_MONEY_COLUMNS = {"available_balance", "transaction_amount"}


def _render_csv(entity: str, rows: list[dict]) -> str:
    cols = _COLUMNS[entity]
    buf = io.StringIO(newline="")
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(cols)
    for row in rows:
        out: list[str] = []
        for col in cols:
            val = row.get(col)
            if val is None:
                out.append("")
            elif col in _MONEY_COLUMNS and isinstance(val, Decimal):
                out.append(_fmt_money(val))
            else:
                out.append(str(val))
        writer.writerow(out)
    return buf.getvalue()


def write_dataset(out_dir: Path, seed: int = SEED_DEFAULT) -> dict[str, int]:
    out_dir.mkdir(parents=True, exist_ok=True)
    data = generate(seed)
    counts: dict[str, int] = {}
    for entity, rows in data.items():
        (out_dir / f"{entity}.csv").write_text(
            _render_csv(entity, rows), encoding="utf-8", newline=""
        )
        counts[entity] = len(rows)
    _write_data_dictionary(out_dir)
    return counts


def _write_data_dictionary(out_dir: Path) -> None:
    rows = [
        ("bank", "bank_code", "IFSC-prefix bank code, primary key."),
        ("bank", "bank_name", "Canonical all-caps bank name."),
        ("account", "account_id", "Unique account identifier."),
        ("account", "entity_id", "Customer/entity that owns the account."),
        ("account", "account_number", "Account number (sensitive; masked in answers)."),
        ("account", "program_id", "Product/program the account belongs to."),
        ("account", "available_balance", "Current available balance in the account."),
        ("account", "bank_code", "Bank the account belongs to."),
        ("transaction", "transaction_id", "Unique transaction identifier."),
        ("transaction", "account_id", "Account the transaction belongs to."),
        ("transaction", "transaction_date", "Timestamp of the transaction."),
        ("transaction", "transaction_type", "Either credit or debit."),
        ("transaction", "description", "Free-text transaction narration."),
        ("transaction", "transaction_amount", "Transaction amount."),
        ("transaction", "transaction_reference_id", "Plaintext reference/receipt number."),
        ("transaction", "utr_number", "Unique transaction reference (sensitive; masked)."),
    ]
    buf = io.StringIO(newline="")
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(["entity", "column", "description"])
    writer.writerows(rows)
    (out_dir / "data_dictionary.csv").write_text(buf.getvalue(), encoding="utf-8", newline="")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate the deterministic seed dataset.")
    parser.add_argument("--seed", type=int, default=SEED_DEFAULT)
    parser.add_argument("--out", type=Path, default=Path("datasets/seed"))
    args = parser.parse_args()
    counts = write_dataset(args.out, args.seed)
    for entity, n in counts.items():
        print(f"{entity}: {n} rows")


if __name__ == "__main__":
    main()
