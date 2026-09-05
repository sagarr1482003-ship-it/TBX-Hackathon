"""Dataset contract checker (Task 2.3, Requirement 8.4/8.5/8.8/8.9/8.10).

Validates a candidate dataset against the rules declared in ``docs/dataset_contract.md`` before
any row is loaded. Every detected deviation is reported with the deviating entity, the violated
rule and that rule's declared severity. One or more ``blocking`` deviations aborts the load
(Requirement 8.9); a dataset whose every deviation is ``tolerable`` proceeds and every tolerable
deviation is recorded in the ingestion report (Requirement 8.10).

The four severities that Requirement 8.4 fixes as ``tolerable`` are encoded here: a null value in
a non-key column, a duplicate vendor-name spelling, an amount of exactly 0, and an amount below 0.

The rule engine here is a *pure* function of in-memory rows plus a contract definition, so it runs
and is tested with no database. The Ingestion_Service supplies the rows (from the connector) and
acts on the :class:`ContractReport` this returns.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

Severity = Literal["blocking", "tolerable"]

ALLOWED_TRANSACTION_TYPES: frozenset[str] = frozenset({"credit", "debit"})


@dataclass(frozen=True)
class ColumnRule:
    name: str
    required: bool = False
    is_key: bool = False
    is_monetary: bool = False
    sensitive: bool = False  # must be masked, never shown raw in answers


@dataclass(frozen=True)
class ForeignKey:
    column: str
    parent_entity: str
    parent_column: str
    # A null FK value in a non-key column is tolerable (an unlinked row is permitted).
    null_tolerable: bool = True


@dataclass(frozen=True)
class EntityContract:
    name: str
    primary_key: str
    columns: tuple[ColumnRule, ...]
    foreign_keys: tuple[ForeignKey, ...] = ()
    # A column constrained to a fixed set of values; an out-of-set value is blocking.
    enum_column: str | None = None
    enum_values: frozenset[str] = frozenset()
    vendor_name_column: str | None = None  # column checked for duplicate spellings


@dataclass(frozen=True)
class Deviation:
    entity: str
    rule: str
    severity: Severity
    detail: str


@dataclass
class ContractReport:
    deviations: list[Deviation] = field(default_factory=list)

    @property
    def blocking(self) -> list[Deviation]:
        return [d for d in self.deviations if d.severity == "blocking"]

    @property
    def tolerable(self) -> list[Deviation]:
        return [d for d in self.deviations if d.severity == "tolerable"]

    @property
    def load_permitted(self) -> bool:
        """The load proceeds only when there is no blocking deviation (Requirement 8.9)."""
        return not self.blocking


def _is_blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and value.strip() == "")


def _to_decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    if isinstance(value, str):
        try:
            return Decimal(value.replace(",", "").strip())
        except InvalidOperation:
            return None
    return None


def _normalise_name(name: str) -> str:
    """Normalise a vendor name for spelling-duplicate detection (alnum, upper)."""
    return re.sub(r"[^A-Za-z0-9]", "", name).upper()


def validate_entity(
    contract: EntityContract,
    rows: list[dict[str, Any]],
    *,
    parents: dict[str, set[Any]] | None = None,
) -> list[Deviation]:
    """Validate one entity's rows against its contract. Pure function.

    ``parents`` maps ``parent_entity`` -> the set of existing key values, used for foreign-key
    resolution. When absent, foreign-key resolution is skipped (the caller validates parents
    first and passes them in).
    """
    parents = parents or {}
    deviations: list[Deviation] = []
    declared_cols = {c.name for c in contract.columns}
    key_cols = {c.name for c in contract.columns if c.is_key}

    # Missing required columns (checked against the header of the first row).
    header = set(rows[0].keys()) if rows else set()
    for col in contract.columns:
        if col.required and rows and col.name not in header:
            deviations.append(
                Deviation(contract.name, "missing required column", "blocking", col.name)
            )

    # Extra (undeclared) columns present in the data -> tolerable.
    for extra in sorted(header - declared_cols):
        deviations.append(
            Deviation(contract.name, "unknown extra column", "tolerable", extra)
        )

    seen_keys: set[Any] = set()
    seen_norm_names: dict[str, int] = {}

    for i, row in enumerate(rows):
        # Required-column null/empty -> blocking.
        for col in contract.columns:
            if col.required and _is_blank(row.get(col.name)):
                deviations.append(
                    Deviation(
                        contract.name,
                        "required-column value null/empty",
                        "blocking",
                        f"row {i}: {col.name}",
                    )
                )

        # Null in a non-key column -> tolerable.
        for col in contract.columns:
            if not col.is_key and not col.required and _is_blank(row.get(col.name)):
                deviations.append(
                    Deviation(
                        contract.name,
                        "null in a non-key column",
                        "tolerable",
                        f"row {i}: {col.name}",
                    )
                )

        # Primary-key duplicate -> blocking.
        pk_val = row.get(contract.primary_key)
        if pk_val in seen_keys:
            deviations.append(
                Deviation(contract.name, "duplicate primary key", "blocking", f"row {i}: {pk_val}")
            )
        else:
            seen_keys.add(pk_val)

        # Monetary amount rules: exactly 0 and below 0 -> tolerable.
        for col in contract.columns:
            if col.is_monetary:
                dec = _to_decimal(row.get(col.name))
                if dec is not None:
                    if dec == 0:
                        deviations.append(
                            Deviation(
                                contract.name, "amount exactly 0", "tolerable", f"row {i}"
                            )
                        )
                    elif dec < 0:
                        deviations.append(
                            Deviation(
                                contract.name, "amount below 0", "tolerable", f"row {i}"
                            )
                        )

        # An enum-constrained column value must be in the allowed set -> unknown is blocking.
        if contract.enum_column is not None:
            sval = row.get(contract.enum_column)
            if not _is_blank(sval) and str(sval) not in contract.enum_values:
                deviations.append(
                    Deviation(
                        contract.name,
                        f"unknown {contract.enum_column} value",
                        "blocking",
                        f"row {i}: {sval}",
                    )
                )

        # Foreign keys.
        for fk in contract.foreign_keys:
            val = row.get(fk.column)
            if _is_blank(val):
                if not fk.null_tolerable and fk.column not in key_cols:
                    deviations.append(
                        Deviation(
                            contract.name,
                            "unresolved non-null foreign key",
                            "blocking",
                            f"row {i}: {fk.column} is null",
                        )
                    )
                continue
            parent_keys = parents.get(fk.parent_entity)
            if parent_keys is not None and val not in parent_keys:
                deviations.append(
                    Deviation(
                        contract.name,
                        "unresolved non-null foreign key",
                        "blocking",
                        f"row {i}: {fk.column}={val}",
                    )
                )

        # Duplicate vendor-name spelling -> tolerable.
        if contract.vendor_name_column is not None:
            nm = row.get(contract.vendor_name_column)
            if not _is_blank(nm):
                norm = _normalise_name(str(nm))
                seen_norm_names[norm] = seen_norm_names.get(norm, 0) + 1
                if seen_norm_names[norm] == 2:
                    deviations.append(
                        Deviation(
                            contract.name,
                            "duplicate vendor-name spelling",
                            "tolerable",
                            f"normalised {norm}",
                        )
                    )

    return deviations


def validate_dataset(
    contracts: list[EntityContract], dataset: dict[str, list[dict[str, Any]]]
) -> ContractReport:
    """Validate a whole candidate dataset. Pure function.

    Parents are collected from each entity's primary-key column first so foreign keys resolve.
    """
    parents: dict[str, set[Any]] = {}
    for contract in contracts:
        rows = dataset.get(contract.name, [])
        parents[contract.name] = {r.get(contract.primary_key) for r in rows}

    report = ContractReport()
    for contract in contracts:
        rows = dataset.get(contract.name, [])
        report.deviations.extend(validate_entity(contract, rows, parents=parents))
    return report


# The seed dataset's contract, matching docs/dataset_contract.md (organiser schema).
SEED_CONTRACTS: list[EntityContract] = [
    EntityContract(
        name="bank",
        primary_key="bank_code",
        columns=(
            ColumnRule("bank_code", required=True, is_key=True),
            ColumnRule("bank_name", required=True),
        ),
    ),
    EntityContract(
        name="account",
        primary_key="account_id",
        columns=(
            ColumnRule("account_id", required=True, is_key=True),
            ColumnRule("entity_id", required=True),
            ColumnRule("account_number", required=True, sensitive=True),
            ColumnRule("program_id", required=True),
            ColumnRule("available_balance", required=True, is_monetary=True),
            ColumnRule("bank_code", required=True),
        ),
        foreign_keys=(ForeignKey("bank_code", "bank", "bank_code", null_tolerable=False),),
    ),
    EntityContract(
        name="transaction",
        primary_key="transaction_id",
        columns=(
            ColumnRule("transaction_id", required=True, is_key=True),
            ColumnRule("account_id", required=True),
            ColumnRule("transaction_date", required=True),
            ColumnRule("transaction_type", required=True),
            ColumnRule("description"),
            ColumnRule("transaction_amount", required=True, is_monetary=True),
            ColumnRule("transaction_reference_id"),
            ColumnRule("utr_number", sensitive=True),
        ),
        foreign_keys=(
            ForeignKey("account_id", "account", "account_id", null_tolerable=False),
        ),
        enum_column="transaction_type",
        enum_values=ALLOWED_TRANSACTION_TYPES,
    ),
]
