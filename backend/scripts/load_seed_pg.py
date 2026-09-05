"""Load the seed CSVs into the live PostgreSQL finance tables.

Reads datasets/seed/{bank,account,transaction}.csv, parses the monetary columns with the same
pure parser the Local_File_Connector uses, and inserts the rows via psycopg. dataset_version is
set to 1. Sensitive columns are stored as-is here (encryption-at-rest wiring is exercised
separately); the answer layer masks them on output.

Usage:
    python -m scripts.load_seed_pg
"""

from __future__ import annotations

import csv
from pathlib import Path

import psycopg

from app.config import get_settings
from app.services.ingestion.local_files import parse_money
from app.services.pipeline.pii_crypto import PiiCipher

SEED = Path("datasets/seed")
SYMBOLS = ["\u20b9", "Rs.", "INR"]
DSV = 1


def _sync_dsn() -> str:
    # psycopg (sync) DSN from the async app DSN.
    return get_settings().postgres_dsn.replace("+asyncpg", "").replace(
        "postgresql://", "postgresql://"
    )


def _rows(name: str) -> list[dict]:
    with (SEED / f"{name}.csv").open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def main() -> None:
    settings = get_settings()
    dsn = _sync_dsn()
    # Encrypt sensitive columns at rest when a key is configured (RBI / DPDP data-at-rest).
    cipher = PiiCipher(settings.pii_encryption_key) if settings.pii_encryption_key else None

    def enc(value):
        return cipher.encrypt(value) if (cipher and value) else value

    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        # Clean load (idempotent) — children first for FKs.
        cur.execute("TRUNCATE finance.transaction, finance.account, finance.bank CASCADE")

        banks = _rows("bank")
        cur.executemany(
            "INSERT INTO finance.bank (bank_code, bank_name, dataset_version) VALUES (%s,%s,%s)",
            [(b["bank_code"], b["bank_name"], DSV) for b in banks],
        )

        accounts = _rows("account")
        cur.executemany(
            "INSERT INTO finance.account (account_id, entity_id, account_number, program_id, "
            "available_balance, bank_code, dataset_version) VALUES (%s,%s,%s,%s,%s,%s,%s)",
            [
                (
                    a["account_id"], a["entity_id"], enc(a["account_number"]),
                    int(a["program_id"]),
                    parse_money(a["available_balance"], SYMBOLS, ",", 2), a["bank_code"], DSV,
                )
                for a in accounts
            ],
        )

        txns = _rows("transaction")
        cur.executemany(
            "INSERT INTO finance.transaction (transaction_id, account_id, transaction_date, "
            "transaction_type, description, transaction_amount, transaction_reference_id, "
            "utr_number, dataset_version) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            [
                (
                    t["transaction_id"], t["account_id"], t["transaction_date"],
                    t["transaction_type"], t["description"] or None,
                    parse_money(t["transaction_amount"], SYMBOLS, ",", 2),
                    t["transaction_reference_id"] or None, enc(t["utr_number"] or None), DSV,
                )
                for t in txns
            ],
        )
        conn.commit()
        mode = "ENCRYPTED at rest" if cipher else "PLAINTEXT (no PII_ENCRYPTION_KEY set)"
        print(
            f"loaded: {len(banks)} banks, {len(accounts)} accounts, {len(txns)} transactions "
            f"| sensitive columns: {mode}"
        )


if __name__ == "__main__":
    main()
