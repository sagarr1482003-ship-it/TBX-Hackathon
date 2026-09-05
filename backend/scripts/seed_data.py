"""Seed_Data_Generator (Task 2.2, Requirement 8).

Generates a deterministic synthetic finance dataset as CSV files under ``datasets/seed/``:
vendors, accounts, transactions, vendor_payouts and reconciliation, plus a data dictionary.

Determinism (Requirement 8.3): all randomness comes from a single ``random.Random(seed)`` and
the output is written with a fixed column order, fixed row order and ``\n`` line terminators, so
a given seed yields byte-identical files.

Thresholds guaranteed:

Requirement 8.2
  * >= 5000 transactions
  * >= 200 vendor payouts
  * >= 40 vendors
  * >= 12 consecutive calendar months of history
  * >= 500 transactions whose reconciliation status is ``unreconciled``
  * >= 20 transactions in each other allowed reconciliation status
  * >= 3 payouts the documented anomaly rule flags

Requirement 8.7
  * >= 50 transactions carrying a null in at least one non-key column
  * >= 5 vendors appearing under 2+ distinct name spellings
  * >= 20 transactions with an amount of exactly 0
  * >= 20 transactions with an amount below 0

Monetary columns are written with the currency symbol and thousands separators, and negatives
are written in parentheses, so the Local_File_Connector's Requirement 6.4 parsing is exercised
by the seed data itself.

Run: ``python -m scripts.seed_data`` (defaults to seed 20240901 into ``datasets/seed``).
"""

from __future__ import annotations

import argparse
import csv
import io
import random
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

SEED_DEFAULT = 20240901
CURRENCY = "INR"
CURRENCY_SYMBOL = "\u20b9"  # ₹
THOUSANDS = ","

# Coverage window: 24 consecutive months (>= 12 required) ending 2024-12-31.
COVERAGE_FIRST = date(2023, 1, 1)
COVERAGE_LAST = date(2024, 12, 31)

RECON_STATUSES = ["unreconciled", "reconciled", "pending", "disputed"]
ACCOUNT_TYPES = ["expense", "asset", "liability", "revenue"]
VENDOR_CATEGORIES = ["software", "logistics", "marketing", "facilities", "consulting", "hardware"]

# Counts (all comfortably above the Requirement 8.2 minimums).
N_VENDORS_BASE = 45  # >= 40 distinct vendors
N_ACCOUNTS = 12
N_TRANSACTIONS = 5200  # >= 5000
N_PAYOUTS = 240  # >= 200

# Requirement 8.7 edge-row targets.
N_NULL_NONKEY = 60  # >= 50 transactions with a null non-key column
N_ZERO_AMOUNT = 25  # >= 20 transactions with amount exactly 0
N_NEG_AMOUNT = 25  # >= 20 transactions with amount below 0
N_DUP_SPELLING_VENDORS = 6  # >= 5 vendors under 2+ spellings

# Requirement 8.2: at least this many unreconciled transactions.
N_UNRECONCILED_MIN = 520
# and at least this many in each of the other allowed statuses.
N_OTHER_STATUS_MIN = 25


def _fmt_money(value: Decimal) -> str:
    """Format a Decimal as a source monetary string: symbol + thousands sep; () for negatives."""
    negative = value < 0
    absval = abs(value).quantize(Decimal("0.01"))
    int_part, frac_part = f"{absval:.2f}".split(".")
    # group thousands
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
            m = 1
            y += 1
    return months


def _random_date_in_month(rng: random.Random, y: int, m: int) -> date:
    if m == 12:
        nxt = date(y + 1, 1, 1)
    else:
        nxt = date(y, m + 1, 1)
    days = (nxt - date(y, m, 1)).days
    return date(y, m, 1) + timedelta(days=rng.randint(0, days - 1))


def generate(seed: int = SEED_DEFAULT) -> dict[str, list[dict]]:
    """Generate all entities as ordered lists of row dicts. Pure and deterministic."""
    rng = random.Random(seed)

    # ---- vendors -------------------------------------------------------------------
    vendors: list[dict] = []
    vendor_ids: list[str] = []
    for i in range(N_VENDORS_BASE):
        vid = f"V{i + 1:04d}"
        vendor_ids.append(vid)
        base_name = f"{rng.choice(_VENDOR_STEMS)} {rng.choice(_VENDOR_SUFFIXES)}"
        vendors.append(
            {
                "vendor_id": vid,
                "vendor_name": base_name,
                "vendor_category": rng.choice(VENDOR_CATEGORIES),
            }
        )

    # >= 5 vendors under 2+ distinct spellings: add duplicate-spelling rows with NEW ids
    # but a name that is a spelling variant of an existing vendor (Requirement 8.7).
    for i in range(N_DUP_SPELLING_VENDORS):
        src = vendors[i]
        vid = f"V9{i + 1:03d}"
        vendor_ids.append(vid)
        vendors.append(
            {
                "vendor_id": vid,
                "vendor_name": _spelling_variant(src["vendor_name"], rng),
                "vendor_category": src["vendor_category"],
            }
        )

    # ---- accounts ------------------------------------------------------------------
    accounts: list[dict] = []
    account_codes: list[str] = []
    for i in range(N_ACCOUNTS):
        code = f"AC{i + 1:03d}"
        account_codes.append(code)
        accounts.append(
            {
                "account_code": code,
                "account_name": f"{rng.choice(ACCOUNT_TYPES).title()} Account {i + 1}",
                "account_type": rng.choice(ACCOUNT_TYPES),
            }
        )

    months = _months_between(COVERAGE_FIRST, COVERAGE_LAST)

    # ---- transactions --------------------------------------------------------------
    transactions: list[dict] = []
    # Pre-assign statuses so the minimums are guaranteed, then fill the rest randomly.
    statuses: list[str] = []
    statuses += ["unreconciled"] * N_UNRECONCILED_MIN
    for s in RECON_STATUSES:
        if s != "unreconciled":
            statuses += [s] * N_OTHER_STATUS_MIN
    while len(statuses) < N_TRANSACTIONS:
        statuses.append(rng.choice(RECON_STATUSES))
    statuses = statuses[:N_TRANSACTIONS]
    rng.shuffle(statuses)

    # Indices that will carry edge amounts / nulls (disjoint, deterministic).
    zero_idx = set(range(0, N_ZERO_AMOUNT))
    neg_idx = set(range(N_ZERO_AMOUNT, N_ZERO_AMOUNT + N_NEG_AMOUNT))
    _null_start = N_ZERO_AMOUNT + N_NEG_AMOUNT
    null_idx = set(range(_null_start, _null_start + N_NULL_NONKEY))

    for i in range(N_TRANSACTIONS):
        y, m = months[i % len(months)]
        tdate = _random_date_in_month(rng, y, m)
        if i in zero_idx:
            amount = Decimal("0.00")
        elif i in neg_idx:
            amount = Decimal(-rng.randint(100, 50_000)) - Decimal("0.50")
        else:
            amount = Decimal(rng.randint(500, 500_000)) + Decimal(f"0.{rng.randint(0, 99):02d}")

        category = rng.choice(VENDOR_CATEGORIES)
        description = f"Invoice {rng.randint(1000, 9999)}"
        vendor_id = rng.choice(vendor_ids)
        account_code = rng.choice(account_codes)

        # Null in a non-key column for the null_idx set (category or description).
        if i in null_idx:
            if i % 2 == 0:
                category = None
            else:
                description = None

        transactions.append(
            {
                "transaction_id": f"T{i + 1:06d}",
                "transaction_date": tdate.isoformat(),
                "amount": amount,
                "currency": CURRENCY,
                "vendor_id": vendor_id,
                "account_code": account_code,
                "category": category,
                "description": description,
                "reconciliation_status": statuses[i],
            }
        )

    # ---- vendor payouts (with >= 3 anomalies) --------------------------------------
    payouts: list[dict] = []
    # Give a handful of vendors a stable payout history, then spike >= 3 of them so the
    # modified z-score rule (0.6745*(v-med)/mad > 3.5) flags them.
    anomaly_vendors = vendor_ids[:3]
    pidx = 0
    for vid in anomaly_vendors:
        # 8 stable payouts around 10,000 then one large spike.
        for _ in range(8):
            pidx += 1
            payouts.append(_payout(pidx, vid, Decimal(rng.randint(9800, 10200)), rng, months))
        pidx += 1
        payouts.append(_payout(pidx, vid, Decimal("500000.00"), rng, months))  # anomaly spike

    # Remaining payouts spread across vendors.
    while len(payouts) < N_PAYOUTS:
        pidx += 1
        vid = rng.choice(vendor_ids)
        payouts.append(_payout(pidx, vid, Decimal(rng.randint(1000, 80_000)), rng, months))

    # ---- reconciliation ------------------------------------------------------------
    reconciliation: list[dict] = []
    ridx = 0
    for txn in transactions:
        # Reconciliation rows only for non-unreconciled transactions.
        if txn["reconciliation_status"] == "unreconciled":
            continue
        ridx += 1
        reconciliation.append(
            {
                "reconciliation_id": f"R{ridx:06d}",
                "transaction_id": txn["transaction_id"],
                "status": txn["reconciliation_status"],
                "matched_at": f"{txn['transaction_date']}T12:00:00+00:00",
                "note": None if ridx % 3 == 0 else "auto-matched",
            }
        )

    return {
        "vendors": vendors,
        "accounts": accounts,
        "transactions": transactions,
        "vendor_payouts": payouts,
        "reconciliation": reconciliation,
    }


def _payout(idx: int, vid: str, amount: Decimal, rng: random.Random, months) -> dict:
    y, m = months[idx % len(months)]
    pdate = _random_date_in_month(rng, y, m)
    return {
        "payout_id": f"P{idx:06d}",
        "payout_date": pdate.isoformat(),
        "amount": amount if amount == amount.to_integral_value() else amount,
        "currency": CURRENCY,
        "vendor_id": vid,
        "payout_status": rng.choice(["paid", "pending", "failed"]),
        "reference": f"REF{rng.randint(100000, 999999)}",
    }


_VENDOR_STEMS = [
    "Acme", "Globex", "Initech", "Umbrella", "Soylent", "Hooli", "Vandelay", "Wonka",
    "Stark", "Wayne", "Cyberdyne", "Tyrell", "Gekko", "Bluth", "Prestige", "Massive",
    "Pied", "Aviato", "Sterling", "Dunder", "Vehement", "Konex", "Zenith", "Meridian",
]
_VENDOR_SUFFIXES = ["Supplies", "Corp", "Industries", "Systems", "Partners", "Ltd", "LLC", "Group"]


def _spelling_variant(name: str, rng: random.Random) -> str:
    """Produce a plausible alternate spelling of a vendor name.

    Every variant folds to the same alphanumeric-uppercase normal form as the source (case,
    extra spaces, or a trailing period only), so the pair is a genuine 2-spelling group for
    the same vendor (Requirement 8.7) that entity resolution must fuzzy-match, while remaining
    a distinct literal string in the source.
    """
    variants = [
        name.upper(),
        name.lower(),
        name.replace(" ", "  "),
        name + ".",
        " " + name + " ",
    ]
    # Deterministic choice driven by the shared rng.
    return variants[rng.randrange(len(variants))]


# ---- CSV writing (deterministic bytes) ---------------------------------------------
_COLUMNS: dict[str, list[str]] = {
    "vendors": ["vendor_id", "vendor_name", "vendor_category"],
    "accounts": ["account_code", "account_name", "account_type"],
    "transactions": [
        "transaction_id", "transaction_date", "amount", "currency", "vendor_id",
        "account_code", "category", "description", "reconciliation_status",
    ],
    "vendor_payouts": [
        "payout_id", "payout_date", "amount", "currency", "vendor_id", "payout_status",
        "reference",
    ],
    "reconciliation": [
        "reconciliation_id", "transaction_id", "status", "matched_at", "note",
    ],
}
_MONEY_COLUMNS = {"amount"}


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
        text = _render_csv(entity, rows)
        (out_dir / f"{entity}.csv").write_text(text, encoding="utf-8", newline="")
        counts[entity] = len(rows)
    _write_data_dictionary(out_dir)
    return counts


def _write_data_dictionary(out_dir: Path) -> None:
    rows = [
        ("transactions", "transaction_id", "Unique transaction identifier."),
        ("transactions", "transaction_date", "Date the transaction was recorded."),
        ("transactions", "amount", "Transaction amount in the dataset currency."),
        ("transactions", "vendor_id", "Vendor the transaction was paid to."),
        ("transactions", "account_code", "Chart-of-accounts code the transaction posts to."),
        ("transactions", "category", "Spend category of the transaction."),
        ("transactions", "reconciliation_status", "Reconciliation state of the transaction."),
        ("vendor_payouts", "payout_id", "Unique payout identifier."),
        ("vendor_payouts", "amount", "Payout amount in the dataset currency."),
        ("vendor_payouts", "vendor_id", "Vendor the payout was made to."),
        ("vendors", "vendor_id", "Unique vendor identifier."),
        ("vendors", "vendor_name", "Vendor display name."),
        ("accounts", "account_code", "Unique chart-of-accounts code."),
        ("reconciliation", "reconciliation_id", "Unique reconciliation record identifier."),
        ("reconciliation", "status", "Reconciliation outcome status."),
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
