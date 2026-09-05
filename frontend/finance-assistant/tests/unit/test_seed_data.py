"""Seed_Data_Generator verification (Task 2.2, Requirement 8.2/8.3/8.7).

Verifies:
- byte-identical output for a fixed seed (Requirement 8.3);
- every Requirement 8.2 threshold met by counting generated rows;
- every Requirement 8.7 edge-row threshold met.

Pure logic; no database and no model call. The anomaly-flag threshold (>= 3 flagged payouts)
is checked against the same deterministic Anomaly_Detector rule the system uses.
"""

from __future__ import annotations

from collections import Counter
from decimal import Decimal

from app.services.pipeline.anomaly import AnomalyConfig, evaluate_entity
from scripts.seed_data import (
    N_VENDORS_BASE,
    RECON_STATUSES,
    _render_csv,
    generate,
)


def _data():
    return generate(seed=20240901)


def test_byte_identical_for_fixed_seed() -> None:
    a = generate(seed=20240901)
    b = generate(seed=20240901)
    for entity in a:
        assert _render_csv(entity, a[entity]) == _render_csv(entity, b[entity]), entity


def test_different_seed_changes_output() -> None:
    a = generate(seed=1)
    b = generate(seed=2)
    # At least one entity's rendered CSV differs.
    assert any(
        _render_csv(e, a[e]) != _render_csv(e, b[e]) for e in a
    )


def test_req_8_2_counts() -> None:
    d = _data()
    assert len(d["transactions"]) >= 5000
    assert len(d["vendor_payouts"]) >= 200
    # >= 40 distinct vendors
    assert len({v["vendor_id"] for v in d["vendors"]}) >= 40
    assert N_VENDORS_BASE >= 40

    # >= 12 consecutive months of history.
    months = {tuple(t["transaction_date"].split("-")[:2]) for t in d["transactions"]}
    assert len(months) >= 12

    # >= 500 unreconciled transactions.
    status_counts = Counter(t["reconciliation_status"] for t in d["transactions"])
    assert status_counts["unreconciled"] >= 500

    # >= 20 transactions in each other allowed status.
    for s in RECON_STATUSES:
        if s != "unreconciled":
            assert status_counts[s] >= 20, (s, status_counts[s])


def test_req_8_2_at_least_three_anomalous_payouts() -> None:
    d = _data()
    config = AnomalyConfig()
    # Build per-vendor payout history and count how many payouts the rule flags.
    by_vendor: dict[str, list[Decimal]] = {}
    for p in d["vendor_payouts"]:
        by_vendor.setdefault(p["vendor_id"], []).append(Decimal(p["amount"]))

    flagged = 0
    for _vid, amounts in by_vendor.items():
        # Evaluate each payout against the history of the others.
        for i, value in enumerate(amounts):
            history = amounts[:i] + amounts[i + 1 :]
            result = evaluate_entity(_vid, value, history, config)
            from app.services.pipeline.anomaly import AnomalyFlag

            if isinstance(result, AnomalyFlag):
                flagged += 1
    assert flagged >= 3, flagged


def test_req_8_7_edge_rows() -> None:
    d = _data()
    txns = d["transactions"]

    # >= 50 transactions with a null in a non-key column (category or description).
    null_nonkey = sum(1 for t in txns if t["category"] is None or t["description"] is None)
    assert null_nonkey >= 50, null_nonkey

    # >= 20 transactions with amount exactly 0.
    zero = sum(1 for t in txns if Decimal(t["amount"]) == 0)
    assert zero >= 20, zero

    # >= 20 transactions with amount below 0.
    neg = sum(1 for t in txns if Decimal(t["amount"]) < 0)
    assert neg >= 20, neg

    # >= 5 vendors appearing under 2+ distinct name spellings.
    # A "spelling group" = names that fold to the same normalised form after upper/space/punct.
    def _norm(name: str) -> str:
        return "".join(ch for ch in name.upper() if ch.isalnum())

    norm_counts = Counter(_norm(v["vendor_name"]) for v in d["vendors"])
    multi_spelling = sum(1 for _n, c in norm_counts.items() if c >= 2)
    assert multi_spelling >= 5, (multi_spelling, dict(norm_counts))


def test_primary_keys_unique() -> None:
    d = _data()
    for entity, key in [
        ("vendors", "vendor_id"),
        ("accounts", "account_code"),
        ("transactions", "transaction_id"),
        ("vendor_payouts", "payout_id"),
        ("reconciliation", "reconciliation_id"),
    ]:
        ids = [r[key] for r in d[entity]]
        assert len(ids) == len(set(ids)), entity


def test_seed_manifest_validates() -> None:
    import pathlib

    import yaml

    from app.schemas.manifest import DatasetManifest

    path = pathlib.Path("datasets/seed/manifest.yaml")
    if not path.exists():
        return  # generator can run without the checked-in manifest
    raw = yaml.safe_load(path.read_text())
    manifest = DatasetManifest.model_validate(raw)
    names = {e.name for e in manifest.entities}
    assert names == {
        "vendors",
        "accounts",
        "transactions",
        "vendor_payouts",
        "reconciliation",
    }
    # Round-trip: dump and re-load reproduces an equivalent manifest.
    again = DatasetManifest.model_validate(manifest.model_dump(mode="json"))
    assert again == manifest
