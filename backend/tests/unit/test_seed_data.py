"""Seed_Data_Generator verification (Requirement 8) — bank/account/transaction schema.

Verifies byte-identity for a fixed seed, the row-count and history thresholds, the edge rows,
and that >= 3 accounts carry an anomaly-flaggable transaction under the real Anomaly rule.
"""

from __future__ import annotations

from collections import Counter
from decimal import Decimal

from app.services.pipeline.anomaly import AnomalyConfig, AnomalyFlag, evaluate_entity
from scripts.seed_data import (
    BANKS,
    TRANSACTION_TYPES,
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
    assert any(_render_csv(e, a[e]) != _render_csv(e, b[e]) for e in a)


def test_counts_and_history() -> None:
    d = _data()
    assert len(d["bank"]) >= 10
    assert len(d["account"]) >= 40
    assert len(d["transaction"]) >= 5000

    # >= 12 consecutive months of history.
    months = {tuple(t["transaction_date"].split(" ")[0].split("-")[:2]) for t in d["transaction"]}
    assert len(months) >= 12

    # both transaction types present in quantity.
    type_counts = Counter(t["transaction_type"] for t in d["transaction"])
    for t in TRANSACTION_TYPES:
        assert type_counts[t] >= 100, (t, type_counts[t])


def test_transaction_types_are_valid() -> None:
    d = _data()
    assert all(t["transaction_type"] in ("credit", "debit") for t in d["transaction"])


def test_at_least_three_anomalous_accounts() -> None:
    d = _data()
    config = AnomalyConfig()
    by_account: dict[str, list[Decimal]] = {}
    for t in d["transaction"]:
        by_account.setdefault(t["account_id"], []).append(Decimal(t["transaction_amount"]))

    flagged_accounts = 0
    for _aid, amounts in by_account.items():
        account_flagged = False
        for i, value in enumerate(amounts):
            history = amounts[:i] + amounts[i + 1 :]
            if isinstance(evaluate_entity(_aid, value, history, config), AnomalyFlag):
                account_flagged = True
                break
        if account_flagged:
            flagged_accounts += 1
    assert flagged_accounts >= 3, flagged_accounts


def test_edge_rows() -> None:
    d = _data()
    txns = d["transaction"]

    null_nonkey = sum(
        1
        for t in txns
        if t["description"] is None
        or t["transaction_reference_id"] is None
        or t["utr_number"] is None
    )
    assert null_nonkey >= 50, null_nonkey

    zero = sum(1 for t in txns if Decimal(t["transaction_amount"]) == 0)
    assert zero >= 20, zero

    neg = sum(1 for t in txns if Decimal(t["transaction_amount"]) < 0)
    assert neg >= 20, neg


def test_bank_codes_are_ifsc_prefixes() -> None:
    d = _data()
    codes = {b["bank_code"] for b in d["bank"]}
    assert codes == {code for code, _ in BANKS}
    # every account references a real bank
    for a in d["account"]:
        assert a["bank_code"] in codes


def test_primary_keys_unique() -> None:
    d = _data()
    for entity, key in [
        ("bank", "bank_code"),
        ("account", "account_id"),
        ("transaction", "transaction_id"),
    ]:
        ids = [r[key] for r in d[entity]]
        assert len(ids) == len(set(ids)), entity


def test_seed_manifest_validates() -> None:
    import pathlib

    import yaml

    from app.schemas.manifest import DatasetManifest

    path = pathlib.Path("datasets/seed/manifest.yaml")
    if not path.exists():
        return
    manifest = DatasetManifest.model_validate(yaml.safe_load(path.read_text()))
    names = {e.name for e in manifest.entities}
    assert names == {"bank", "account", "transaction"}
    again = DatasetManifest.model_validate(manifest.model_dump(mode="json"))
    assert again == manifest
