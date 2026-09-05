"""Groundedness_Checker — verify a draft answer against the executed evidence (Req 17).

This is the check that makes it structurally impossible to state a number the data did not
produce. Every numeric literal, currency amount, percentage, date and number-written-in-
words is extracted from the draft and matched against:

  * computation-record values (consulted **first**, so the match source is recorded);
  * executed result-set cells;
  * row/group/enumerated counts and ordinals (Requirement 17.9);
  * bounds and covered calendar periods of the resolved date range (Requirement 17.10).

Matching is at the *place value of the least significant digit written* (Requirement 17.2),
so "2.4 crore" matches 24,013,442 but "24,013,443" does not match 24,013,442. Entity names
are matched after trimming, whitespace collapse and case folding (Requirement 17.5).

Pure logic; no database and no model call.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from app.schemas.computation import ComputationRecord

# Scale words and their multipliers (Indian + international).
SCALE_WORDS: dict[str, int] = {
    "thousand": 1_000,
    "lakh": 100_000,
    "lakhs": 100_000,
    "crore": 10_000_000,
    "crores": 10_000_000,
    "million": 1_000_000,
    "million s": 1_000_000,
    "billion": 1_000_000_000,
}

_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
}

# number words for words_to_number
_UNITS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
    "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17,
    "eighteen": 18, "nineteen": 19,
}
_TENS = {
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
    "eighty": 80, "ninety": 90,
}
_MULTIPLIERS = {
    "hundred": 100, "thousand": 1_000, "lakh": 100_000, "crore": 10_000_000,
    "million": 1_000_000, "billion": 1_000_000_000,
}

Verdict = Literal["pass", "reject"]
RejectReason = Literal["unmatched_numeral", "unmatched_entity", "unconvertible_words"]


@dataclass
class GroundednessOutcome:
    verdict: Verdict
    verified_figure_count: int = 0
    reject_reason: RejectReason | None = None
    unmatched: str | None = None
    match_sources: dict[str, str] = field(default_factory=dict)


@dataclass
class NumericSpan:
    text: str
    value: Decimal
    least_significant_place: int  # e.g. -2 for two decimals, 0 for integer, 7 for crore
    kind: Literal["number", "currency", "percent", "words"] = "number"


def words_to_number(text: str) -> Decimal | None:
    """Convert an English number phrase to a single value, else None.

    Leading non-number words are ignored; only the maximal trailing run of recognised
    number words is converted. Returns None when no number words are present, so a phrase
    with no convertible tail is treated as unconvertible by the caller.
    """
    tokens = re.findall(r"[a-z]+", text.lower())
    number_tokens = set(_UNITS) | set(_TENS) | {"hundred"} | set(_MULTIPLIERS) | {"and"}
    # take the maximal trailing run of number tokens
    tail: list[str] = []
    for tok in reversed(tokens):
        if tok in number_tokens:
            tail.append(tok)
        else:
            break
    tail.reverse()
    tail = [t for t in tail if t != "and"]
    if not tail:
        return None
    total = 0
    current = 0
    matched_any = False
    for tok in tail:
        if tok in _UNITS:
            current += _UNITS[tok]
            matched_any = True
        elif tok in _TENS:
            current += _TENS[tok]
            matched_any = True
        elif tok == "hundred":
            current = (current or 1) * 100
            matched_any = True
        elif tok in _MULTIPLIERS:
            total += (current or 1) * _MULTIPLIERS[tok]
            current = 0
            matched_any = True
    if not matched_any:
        return None
    return Decimal(total + current)


def _least_significant_place(numeric_text: str) -> int:
    """Return the place value (power of ten) of the least significant written digit.

    Examples: "123" -> 0; "12.34" -> -2; "2.4 crore" is handled by the caller which adds
    the scale exponent.
    """
    cleaned = numeric_text.replace(",", "").strip()
    if "." in cleaned:
        return -len(cleaned.split(".", 1)[1])
    return 0


_CURRENCY_RE = re.compile(
    r"(?P<sym>[₹$€£]|Rs\.?|INR|USD|EUR|GBP)?\s*"
    r"(?P<num>\d{1,3}(?:,\d{2,3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
    r"\s*(?P<scale>thousand|lakhs?|crores?|million|billion)?",
    re.IGNORECASE,
)
_PERCENT_RE = re.compile(r"(?P<num>-?\d+(?:\.\d+)?)\s*(?:%|percent)", re.IGNORECASE)
_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")
_WORDS_SCALE_RE = re.compile(
    r"\b((?:[a-z]+[\s-]+){0,6}?[a-z]+)\s+(thousand|lakhs?|crores?|million|billion)\b",
    re.IGNORECASE,
)


def extract_numeric_spans(text: str) -> tuple[list[NumericSpan], str | None]:
    """Extract numeric spans from the draft. Returns (spans, unconvertible_words_span).

    If a words+scale phrase cannot be converted, the second element names it so the caller
    can reject with ``unconvertible_words``.
    """
    spans: list[NumericSpan] = []
    consumed: list[tuple[int, int]] = []

    # 1) percentages first (so "12.5%" is not double-counted as a bare number)
    for m in _PERCENT_RE.finditer(text):
        num = m.group("num")
        spans.append(
            NumericSpan(
                text=m.group(0),
                value=Decimal(num),
                least_significant_place=_least_significant_place(num),
                kind="percent",
            )
        )
        consumed.append(m.span())

    # 2) words + scale (e.g. "two crore", "twenty five lakh")
    for m in _WORDS_SCALE_RE.finditer(text):
        phrase, scale = m.group(1), m.group(2).lower()
        base = words_to_number(phrase)
        if base is None:
            # cannot convert the words -> caller must reject
            return spans, m.group(0)
        mult = SCALE_WORDS.get(scale, SCALE_WORDS.get(scale.rstrip("s"), 1))
        value = base * Decimal(mult)
        # least significant place of a scale phrase is the scale exponent
        lsp = len(str(mult)) - 1
        spans.append(
            NumericSpan(text=m.group(0), value=value, least_significant_place=lsp, kind="words")
        )
        consumed.append(m.span())

    # 3) currency amounts and bare numbers with optional numeric scale word
    for m in _CURRENCY_RE.finditer(text):
        if not m.group("num"):
            continue
        if any(s <= m.start() < e or s < m.end() <= e for s, e in consumed):
            continue
        num_txt = m.group("num")
        try:
            base = Decimal(num_txt.replace(",", ""))
        except InvalidOperation:
            continue
        scale = (m.group("scale") or "").lower()
        if scale:
            mult = SCALE_WORDS.get(scale, SCALE_WORDS.get(scale.rstrip("s"), 1))
            value = base * Decimal(mult)
            lsp = _least_significant_place(num_txt) + (len(str(mult)) - 1)
        else:
            value = base
            lsp = _least_significant_place(num_txt)
        kind = "currency" if m.group("sym") else "number"
        spans.append(
            NumericSpan(text=m.group(0), value=value, least_significant_place=lsp, kind=kind)
        )
        consumed.append(m.span())

    return spans, None


class NumericSourceIndex:
    """The set of values a draft numeral may legitimately match."""

    def __init__(
        self,
        result_values: list[Decimal],
        record_values: list[Decimal],
        counts: set[int],
        date_values: set[Decimal],
    ) -> None:
        self.result_values = result_values
        self.record_values = record_values
        self.counts = counts
        self.date_values = date_values

    def match_source(self, value: Decimal, place: int, tolerance: Decimal) -> str | None:
        """Return the match source name, or None if unmatched.

        ``place`` is the power-of-ten position of the least significant written digit
        (0 for integers, -2 for two decimals, +6 for "x.y crore"). A source candidate
        matches when it, rounded to that written place, equals the written value within
        ``tolerance`` (Requirement 17.2). Computation records are consulted first (Open
        Question 8) so the match source is recorded.
        """
        from app.services.pipeline.computation import round_half_away

        target = value
        # places argument to round_half_away is decimal places; = -place.
        places = -place

        def rounds_to(candidate: Decimal) -> bool:
            rounded = round_half_away(candidate, places)
            return abs(rounded - target) <= tolerance

        # 1) computation records (derived values)
        for cand in self.record_values:
            if rounds_to(cand):
                return "computation_record"
        # 2) result-set cells
        for cand in self.result_values:
            if rounds_to(cand):
                return "result_set"
        # 3) counts / ordinals
        try:
            as_int = int(target)
            if Decimal(as_int) == target and as_int in self.counts:
                return "count_or_ordinal"
        except (ValueError, OverflowError):
            pass
        # 4) dates (year / period bounds represented numerically)
        for cand in self.date_values:
            if abs(cand - target) <= tolerance:
                return "date_range"
        return None


def _fold(name: str) -> str:
    return re.sub(r"\s+", " ", name.strip()).casefold()


class GroundednessChecker:
    """Deterministic verification of a draft answer (Requirement 17)."""

    def __init__(
        self,
        match_tolerance: Decimal = Decimal("0.01"),
        require_computation_record: bool = False,
    ) -> None:
        self.match_tolerance = match_tolerance
        self.require_computation_record = require_computation_record

    def verify(
        self,
        draft_text: str,
        *,
        result_rows: list[dict[str, Any]] | None = None,
        computation_records: list[ComputationRecord] | None = None,
        resolved_date_range: tuple[Any, Any] | None = None,
        group_count: int | None = None,
        entity_names_in_scope: set[str] | None = None,
    ) -> GroundednessOutcome:
        result_rows = result_rows or []
        computation_records = computation_records or []
        entity_names_in_scope = entity_names_in_scope or set()

        spans, unconvertible = extract_numeric_spans(draft_text)
        if unconvertible is not None:
            return GroundednessOutcome(
                verdict="reject",
                reject_reason="unconvertible_words",
                unmatched=unconvertible,
            )

        index = self._build_index(
            result_rows, computation_records, resolved_date_range, group_count
        )

        match_sources: dict[str, str] = {}
        for span in spans:
            source = index.match_source(
                span.value, span.least_significant_place, self.match_tolerance
            )
            if source is None or (
                self.require_computation_record and source != "computation_record"
            ):
                return GroundednessOutcome(
                    verdict="reject",
                    reject_reason="unmatched_numeral",
                    unmatched=span.text,
                    verified_figure_count=len(match_sources),
                )
            match_sources[span.text] = source

        # Entity-name verification (Requirement 17.5 / 17.11).
        folded_scope = {_fold(n) for n in entity_names_in_scope}
        for name in self._extract_entity_names(draft_text, entity_names_in_scope):
            if _fold(name) not in folded_scope:
                return GroundednessOutcome(
                    verdict="reject",
                    reject_reason="unmatched_entity",
                    unmatched=name,
                    verified_figure_count=len(match_sources),
                )

        return GroundednessOutcome(
            verdict="pass",
            verified_figure_count=len(spans),
            match_sources=match_sources,
        )

    # ---------------------------------------------------------------------------------
    def _build_index(
        self,
        result_rows: list[dict[str, Any]],
        records: list[ComputationRecord],
        date_range: tuple[Any, Any] | None,
        group_count: int | None,
    ) -> NumericSourceIndex:
        result_values: list[Decimal] = []
        for row in result_rows:
            for cell in row.values():
                dec = _cell_to_decimal(cell)
                if dec is not None:
                    result_values.append(dec)

        record_values: list[Decimal] = []
        for rec in records:
            if rec.value is not None:
                record_values.append(rec.value)
            if rec.unrounded_value is not None:
                record_values.append(rec.unrounded_value)
            if rec.operands:
                record_values.extend(rec.operands.values())

        counts: set[int] = set()
        row_count = len(result_rows)
        counts.add(row_count)
        counts.update(range(1, row_count + 1))  # ordinals (Requirement 17.9)
        if group_count is not None:
            counts.add(group_count)

        date_values: set[Decimal] = set()
        if date_range is not None:
            for bound in date_range:
                year = getattr(bound, "year", None)
                if year is not None:
                    date_values.add(Decimal(year))
                elif isinstance(bound, (int,)):
                    date_values.add(Decimal(bound))

        return NumericSourceIndex(result_values, record_values, counts, date_values)

    @staticmethod
    def _extract_entity_names(text: str, scope: set[str]) -> list[str]:
        """Find scope entity names mentioned in the draft (case-insensitively).

        Only names that are in scope are checked positively; we surface any capitalised
        token sequences that look like entity names but are not in scope so a hallucinated
        entity is caught. To stay deterministic and avoid false positives on ordinary
        words, we only flag multi-word Title-Case spans or all-caps tokens not in scope.
        """
        folded_scope = {_fold(n) for n in scope}
        candidates = re.findall(r"\b[A-Z][A-Za-z0-9&.\-]*(?:\s+[A-Z][A-Za-z0-9&.\-]*)+\b", text)
        flagged: list[str] = []
        for c in candidates:
            if _fold(c) not in folded_scope:
                # A capitalised multi-word span not in scope: treat as an entity claim.
                flagged.append(c)
        return flagged


def _cell_to_decimal(cell: Any) -> Decimal | None:
    if cell is None or isinstance(cell, bool):
        return None
    if isinstance(cell, Decimal):
        return cell
    if isinstance(cell, int):
        return Decimal(cell)
    if isinstance(cell, float):
        return Decimal(str(cell))
    if isinstance(cell, str):
        try:
            return Decimal(cell.replace(",", ""))
        except InvalidOperation:
            return None
    return None
