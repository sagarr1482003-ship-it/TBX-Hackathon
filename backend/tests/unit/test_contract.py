"""Dataset contract checker verification (Requirement 8.4/8.5/8.8/8.9/8.10) — new schema.

- The seed dataset validates with 0 blocking deviations (Requirement 8.8).
- A blocking deviation aborts the load (Requirement 8.9).
- A dataset whose every deviation is tolerable proceeds and records them (Requirement 8.10).
"""

from __future__ import annotations

from decimal import Decimal

from app.services.ingestion.contract import (
    SEED_CONTRACTS,
    ContractReport,
    validate_dataset,
    validate_entity,
)
from scripts.seed_data import generate


def _seed_dataset() -> dict[str, list[dict]]:
    return generate(seed=20240901)


def test_req_8_8_seed_has_zero_blocking_deviations() -> None:
    report = validate_dataset(SEED_CONTRACTS, _seed_dataset())
    assert report.blocking == [], report.blocking[:5]
    assert report.load_permitted is True


def test_req_8_10_seed_has_tolerable_deviations_recorded() -> None:
    report = validate_dataset(SEED_CONTRACTS, _seed_dataset())
    kinds = {d.rule for d in report.tolerable}
    assert "null in a non-key column" in kinds
    assert "amount exactly 0" in kinds
    assert "amount below 0" in kinds


def test_req_8_9_blocking_aborts_load() -> None:
    dataset = _seed_dataset()
    dataset["transaction"][0] = {**dataset["transaction"][0], "transaction_id": ""}
    report = validate_dataset(SEED_CONTRACTS, dataset)
    assert len(report.blocking) >= 1
    assert report.load_permitted is False


def test_unknown_transaction_type_is_blocking() -> None:
    dataset = _seed_dataset()
    dataset["transaction"][0] = {
        **dataset["transaction"][0],
        "transaction_type": "reversal",  # not credit/debit
    }
    report = validate_dataset(SEED_CONTRACTS, dataset)
    assert any(
        d.rule == "unknown transaction_type value" and d.severity == "blocking"
        for d in report.blocking
    )
    assert report.load_permitted is False


def test_unresolved_foreign_key_is_blocking() -> None:
    dataset = _seed_dataset()
    dataset["account"][0] = {**dataset["account"][0], "bank_code": "ZZZZ"}
    report = validate_dataset(SEED_CONTRACTS, dataset)
    assert any(d.rule == "unresolved non-null foreign key" for d in report.blocking)


def test_duplicate_primary_key_is_blocking() -> None:
    dataset = _seed_dataset()
    dup = dict(dataset["bank"][0])
    dataset["bank"] = dataset["bank"] + [dup]
    report = validate_dataset(SEED_CONTRACTS, dataset)
    assert any(d.rule == "duplicate primary key" for d in report.blocking)


def test_sensitive_columns_declared() -> None:
    # account_number and utr_number must be marked sensitive in the contract.
    account = next(c for c in SEED_CONTRACTS if c.name == "account")
    txn = next(c for c in SEED_CONTRACTS if c.name == "transaction")
    assert any(col.name == "account_number" and col.sensitive for col in account.columns)
    assert any(col.name == "utr_number" and col.sensitive for col in txn.columns)


def test_only_tolerable_permits_load() -> None:
    contracts = SEED_CONTRACTS
    dataset = {
        "bank": [{"bank_code": "HDFC", "bank_name": "HDFC BANK LIMITED"}],
        "account": [
            {
                "account_id": "a1",
                "entity_id": "e1",
                "account_number": "50200013729069",
                "program_id": 21,
                "available_balance": Decimal("100.00"),
                "bank_code": "HDFC",
            }
        ],
        "transaction": [
            {
                "transaction_id": "t1",
                "account_id": "a1",
                "transaction_date": "2025-01-01 10:00:00.000000",
                "transaction_type": "credit",
                "description": None,  # tolerable null non-key
                "transaction_amount": Decimal("0.00"),  # tolerable: exactly 0
                "transaction_reference_id": "S123",
                "utr_number": None,  # tolerable null non-key
            }
        ],
    }
    report: ContractReport = validate_dataset(contracts, dataset)
    assert report.blocking == []
    assert report.load_permitted is True
    assert len(report.tolerable) >= 2


def test_missing_required_column_blocking() -> None:
    contract = next(c for c in SEED_CONTRACTS if c.name == "bank")
    rows = [{"bank_code": "HDFC"}]  # missing bank_name
    devs = validate_entity(contract, rows)
    assert any(
        d.rule == "missing required column" and d.severity == "blocking" for d in devs
    )
