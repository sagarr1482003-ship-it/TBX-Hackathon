"""Answer draft mutation generator (task 7.5).

Builds a draft answer *only* from sourced values, then applies exactly one mutation that a
grounded checker must catch: alter a digit, shift a decimal point, attach or change a scale
word, re-express a figure in words, insert an unrelated numeral, round to a different place
value, rename an entity, change a date. A lossless re-expression (same value, different
surface form) must NOT flip the verdict; every other mutation must.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from hypothesis import strategies as st


@dataclass
class MutationCase:
    draft_text: str
    source_value: Decimal
    entity_name: str
    mutation: str  # the mutation applied
    should_reject: bool


# A fixed sourced value and entity the grounded draft is built from.
_BASE_VALUE = Decimal("24013442.00")
_ENTITY = "Acme Supplies"


def _grounded_draft(value: Decimal, entity: str) -> str:
    return f"{entity} received a total of INR {value} across the period."


_MUTATIONS: list[MutationCase] = [
    # lossless re-expressions — must still PASS (verdict unchanged)
    MutationCase(
        draft_text=f"{_ENTITY} received a total of INR 24013442.00 across the period.",
        source_value=_BASE_VALUE,
        entity_name=_ENTITY,
        mutation="identity",
        should_reject=False,
    ),
    MutationCase(
        draft_text=f"{_ENTITY} received a total of INR 24,013,442.00 across the period.",
        source_value=_BASE_VALUE,
        entity_name=_ENTITY,
        mutation="add_grouping_separators",
        should_reject=False,
    ),
    # mutations — must REJECT
    MutationCase(
        draft_text=f"{_ENTITY} received a total of INR 24013443.00 across the period.",
        source_value=_BASE_VALUE,
        entity_name=_ENTITY,
        mutation="alter_a_digit",
        should_reject=True,
    ),
    MutationCase(
        draft_text=f"{_ENTITY} received a total of INR 2401344.20 across the period.",
        source_value=_BASE_VALUE,
        entity_name=_ENTITY,
        mutation="shift_decimal_point",
        should_reject=True,
    ),
    MutationCase(
        draft_text=f"{_ENTITY} received a total of 24 crore across the period.",
        source_value=_BASE_VALUE,
        entity_name=_ENTITY,
        mutation="attach_wrong_scale_word",
        should_reject=True,
    ),
    # Design.md's matcher compares at the place value of the least significant digit
    # written (line 1139). "two crore" writes its least significant digit at the crore
    # place (1e7); 24,013,442 rounded to 1e7 is 20,000,000 = "two crore", so "two crore"
    # would legitimately round-match and must NOT be used as the wrong re-expression.
    # "three crore" (3e7) does not equal 24,013,442 rounded to 1e7 (2e7), so it is the
    # correct genuinely-wrong words re-expression that the checker must reject.
    MutationCase(
        draft_text=f"{_ENTITY} received a total of three crore across the period.",
        source_value=_BASE_VALUE,
        entity_name=_ENTITY,
        mutation="reexpress_in_words_wrong",
        should_reject=True,
    ),
    MutationCase(
        draft_text=f"{_ENTITY} received a total of INR 24013442.00 across 99 periods.",
        source_value=_BASE_VALUE,
        entity_name=_ENTITY,
        mutation="insert_unrelated_numeral",
        should_reject=True,
    ),
    MutationCase(
        draft_text=f"{_ENTITY} received a total of INR 24013000.00 across the period.",
        source_value=_BASE_VALUE,
        entity_name=_ENTITY,
        mutation="round_to_different_place",
        should_reject=True,
    ),
    MutationCase(
        draft_text="Globex Corp received a total of INR 24013442.00 across the period.",
        source_value=_BASE_VALUE,
        entity_name=_ENTITY,
        mutation="rename_entity",
        should_reject=True,
    ),
]


def draft_mutations() -> st.SearchStrategy[MutationCase]:
    return st.sampled_from(_MUTATIONS)


def base_value() -> Decimal:
    return _BASE_VALUE


def base_entity() -> str:
    return _ENTITY
