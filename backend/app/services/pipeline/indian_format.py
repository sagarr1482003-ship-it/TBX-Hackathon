"""Indian number/currency formatting (lakh-crore grouping).

- ``indian_group("77597697.30")`` -> ``"7,75,97,697.30"`` (2-digit groups after the first 3).
- ``inr("77597697.30")`` -> ``"INR 7,75,97,697.30"``.
- ``indian_words(775976978.30)`` -> ``"77.60 crore"`` (compact human scale).

All operate on Decimal/str/number without floats losing paise. Used so answers use the Indian
convention (crore/lakh) instead of Western grouping/dollars.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

CRORE = Decimal("10000000")
LAKH = Decimal("100000")


def _to_dec(v) -> Decimal | None:
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, Decimal):
        return v
    try:
        return Decimal(str(v).replace(",", "").strip())
    except (InvalidOperation, ValueError):
        return None


def indian_group(value) -> str:
    """Group digits in the Indian style: last 3, then 2s. Preserves 2 decimal places."""
    d = _to_dec(value)
    if d is None:
        return str(value)
    neg = d < 0
    d = abs(d).quantize(Decimal("0.01"))
    int_part, _, frac = str(d).partition(".")
    frac = (frac + "00")[:2]
    if len(int_part) <= 3:
        grouped = int_part
    else:
        head, last3 = int_part[:-3], int_part[-3:]
        # group the head in 2s from the right
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        grouped = ",".join(parts) + "," + last3
    out = f"{grouped}.{frac}"
    return f"-{out}" if neg else out


def inr(value) -> str:
    """Format as INR with Indian grouping, e.g. 'INR 7,75,97,697.30'."""
    return f"INR {indian_group(value)}"


def indian_words(value) -> str:
    """Compact Indian-scale phrasing, e.g. '77.60 crore' / '5.20 lakh' / '900.00'."""
    d = _to_dec(value)
    if d is None:
        return str(value)
    neg = d < 0
    a = abs(d)
    if a >= CRORE:
        s = f"{(a / CRORE).quantize(Decimal('0.01'))} crore"
    elif a >= LAKH:
        s = f"{(a / LAKH).quantize(Decimal('0.01'))} lakh"
    else:
        s = str(a.quantize(Decimal("0.01")))
    return f"-{s}" if neg else s
