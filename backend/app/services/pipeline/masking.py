"""Sensitive-data masking (RBI / DPDP data-protection posture).

The dataset contract marks certain columns ``sensitive`` (``account_number``, ``utr_number``).
Those values must never appear raw in an answer, a trace payload or an export — they are masked
here. Masking is deterministic and pure, so it is unit-tested with no database and no model.

Rules:
  * an account-number-like value keeps only its last 4 characters, the rest replaced by a mask
    glyph (e.g. ``50200013729069`` -> ``••••••••••3069``);
  * any other sensitive value (e.g. a UTR) is fully masked to a fixed token, because it carries
    no user-facing suffix worth showing;
  * ``None`` stays ``None``.

The set of sensitive column names is derived from the active dataset contract, so a new dataset
that marks different columns sensitive is honoured without code changes.
"""

from __future__ import annotations

from collections.abc import Iterable

MASK_GLYPH = "\u2022"  # •
FULL_MASK = "[REDACTED]"
_VISIBLE_SUFFIX = 4


def sensitive_columns(contracts: Iterable) -> frozenset[str]:
    """Collect the set of column names flagged ``sensitive`` across the contract entities."""
    names: set[str] = set()
    for entity in contracts:
        for col in entity.columns:
            if getattr(col, "sensitive", False):
                names.add(col.name)
    return frozenset(names)


def mask_account_number(value: str) -> str:
    """Keep the last 4 characters; mask the rest. Short values are fully masked."""
    s = str(value)
    if len(s) <= _VISIBLE_SUFFIX:
        return MASK_GLYPH * len(s)
    return MASK_GLYPH * (len(s) - _VISIBLE_SUFFIX) + s[-_VISIBLE_SUFFIX:]


def mask_value(column: str, value: object) -> object:
    """Mask one cell if its column is sensitive. ``None`` passes through unchanged.

    Only the known sensitive columns are masked; every other column is returned unchanged, so
    this is safe to call on any cell.
    """
    if value is None:
        return None
    if column == "account_number":
        return mask_account_number(str(value))
    if column == "utr_number":
        # UTR: fully masked (no searchable suffix worth showing).
        return FULL_MASK
    return value


def mask_row(row: dict[str, object], sensitive: frozenset[str]) -> dict[str, object]:
    """Return a copy of ``row`` with every sensitive column masked.

    ``account_number`` keeps a last-4 suffix; any other sensitive column is fully masked. Driven
    by the ``sensitive`` set (from the contract), so a new dataset marking a different column
    sensitive is honoured without code changes.
    """
    out: dict[str, object] = {}
    for k, v in row.items():
        if k not in sensitive or v is None:
            out[k] = v
        elif k == "account_number":
            out[k] = mask_account_number(str(v))
        else:
            out[k] = FULL_MASK
    return out


def mask_rows(
    rows: list[dict[str, object]], sensitive: frozenset[str]
) -> list[dict[str, object]]:
    return [mask_row(r, sensitive) for r in rows]
