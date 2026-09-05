"""Dataset contract checker verification (Task 2.3, Requirement 8.4/8.5/8.8/8.9/8.10).

- The seed dataset validates with 0 blocking deviations (Requirement 8.8).
- A blocking deviation aborts the load (load_permitted is False, Requirement 8.9).
- A dataset whose every deviation is tolerable proceeds and records them (Requirement 8.10).
- The four Requirement 8.4 tolerable rules are classified tolerable.

Pure logic; no database and no model call.
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
    """Seed rows with amounts as Decimal (post-connector representation)."""
    data = generate(seed=20240901)
    # amounts are already Decimal in generate() output; keep as-is.
    return data


def test_req_8_8_seed_has_zero_blocking_deviations() -> None:
    report = validate_dataset(SEED_CONTRACTS, _seed_dataset())
    assert report.blocking == [], report.blocking[:5]
    assert report.load_permitted is True


def test_req_8_10_seed_has_tolerable_deviations_recorded() -> None:
    report = validate_dataset(SEED_CONTRACTS, _seed_dataset())
    kinds = {d.rule for d in report.tolerable}
    # The seed deliberately contains all four tolerable-rule types (Requirement 8.7 rows).
    assert "null in a non-key column" in kinds
    assert "amount exactly 0" in kinds
    assert "amount below 0" in kinds
    assert "duplicate vendor-name spelling" in kinds


def test_req_8_9_blocking_aborts_load() -> None:
    dataset = _seed_dataset()
    # Inject a missing required value (blank transaction_id) -> blocking.
    dataset["transactions"][0] = {**dataset["transactions"][0], "transaction_id": ""}
    report = validate_dataset(SEED_CONTRACTS, dataset)
    assert len(report.blocking) >= 1
    assert report.load_permitted is False


def test_unknown_reconciliation_status_is_blocking() -> None:
    dataset = _seed_dataset()
    dataset["reconciliation"][0] = {
        **dataset["reconciliation"][0],
        "status": "totally_unknown_status",
    }
    report = validate_dataset(SEED_CONTRACTS, dataset)
    assert any(
        d.rule == "unknown reconciliation status value" and d.severity == "blocking"
        for d in report.blocking
    )
    assert report.load_permitted is False


def test_unresolved_foreign_key_is_blocking() -> None:
    dataset = _seed_dataset()
    dataset["vendor_payouts"][0] = {
        **dataset["vendor_payouts"][0],
        "vendor_id": "V_DOES_NOT_EXIST",
    }
    report = validate_dataset(SEED_CONTRACTS, dataset)
    assert any(
        d.rule == "unresolved non-null foreign key" for d in report.blocking
    )


def test_duplicate_primary_key_is_blocking() -> None:
    dataset = _seed_dataset()
    dup = dict(dataset["vendors"][0])
    dataset["vendors"] = dataset["vendors"] + [dup]
    report = validate_dataset(SEED_CONTRACTS, dataset)
    assert any(d.rule == "duplicate primary key" for d in report.blocking)


def test_only_tolerable_permits_load() -> None:
    # A tiny dataset with only tolerable deviations (a zero amount + a null category).
    contracts = [c for c in SEED_CONTRACTS if c.name in ("vendors", "accounts", "transactions")]
    dataset = {
        "vendors": [{"vendor_id": "V1", "vendor_name": "Acme", "vendor_category": "software"}],
        "accounts": [
            {"account_code": "AC1", "account_name": "Expense", "account_type": "expense"}
        ],
        "transactions": [
            {
                "transaction_id": "T1",
                "transaction_date": "2023-01-01",
                "amount": Decimal("0.00"),  # tolerable: exactly 0
                "currency": "INR",
                "vendor_id": "V1",
                "account_code": "AC1",
                "category": None,  # tolerable: null non-key
                "description": "x",
                "reconciliation_status": "reconciled",
            }
        ],
    }
    report: ContractReport = validate_dataset(contracts, dataset)
    assert report.blocking == []
    assert report.load_permitted is True
    assert len(report.tolerable) >= 2


def test_missing_required_column_blocking() -> None:
    contract = next(c for c in SEED_CONTRACTS if c.name == "accounts")
    rows = [{"account_code": "AC1", "account_type": "expense"}]  # missing account_name
    devs = validate_entity(contract, rows)
    assert any(
        d.rule == "missing required column" and d.severity == "blocking" for d in devs
    )
