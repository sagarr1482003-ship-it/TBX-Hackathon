"""Properties 5 and 31 (Requirement 18) — abstention/clarification invariants.

P5  — for generated unanswerable or ambiguous questions, the released response contains no
      monetary figure and carries an abstention or clarification reason code.
P31 — every abstention carries exactly one reason code drawn from the Requirement 18.4
      enumeration, and every terminating pipeline condition maps to a reason code in that
      enumeration (the ``pipeline_fault`` marker is internal and never itself released as an
      answer — it is recorded and converted).

Pure logic; no database and no model call.
"""

from __future__ import annotations

import re

from hypothesis import given
from hypothesis import strategies as st

from app.errors import (
    PIPELINE_FAULT,
    REASON_CODES,
    all_error_classes,
)
from app.services.pipeline.abstention import (
    CLARIFY_REASONS,
    CONDITION_REASON,
    AbstentionController,
)

_CTRL = AbstentionController(clarification_round_limit=2)

# Every terminating condition the controller knows about.
_CONDITIONS = sorted(CONDITION_REASON)


def _has_money(text: str) -> bool:
    # A monetary figure requires digits: a bare currency code with no number is not a figure.
    return bool(re.search(r"\d", text))


# ---- Property 31: total mapping to the 18.4 enumeration -------------------------------
@given(condition=st.sampled_from(_CONDITIONS))
def test_p31_every_condition_maps_to_one_enum_code(condition) -> None:
    reason = _CTRL.reason_for_condition(condition)
    assert reason in REASON_CODES
    # exactly one code (a string, not a set/list)
    assert isinstance(reason, str)


def test_p31_unknown_condition_is_pipeline_fault_not_a_figure() -> None:
    reason = _CTRL.reason_for_condition("some_condition_that_does_not_exist")
    assert reason == PIPELINE_FAULT
    assert reason not in REASON_CODES  # internal marker, never a user-facing 18.4 code


def test_p31_every_error_maps_to_enum_or_pipeline_fault() -> None:
    # Mirrors the taxonomy: every TbxError's reason is an 18.4 code, or pipeline_fault when
    # its abstention_reason is a documented None.
    for cls in all_error_classes():
        err = cls("x")
        reason = _CTRL.reason_for_error(err)
        assert reason in REASON_CODES or reason == PIPELINE_FAULT


# ---- Property 5: no figure / no breakdown on unanswerable or ambiguous ----------------
@given(
    condition=st.sampled_from(_CONDITIONS),
    # A message deliberately seeded with a numeric figure the controller must strip.
    amount=st.integers(min_value=1, max_value=9_999_999),
)
def test_p5_abstention_message_has_no_figure(condition, amount) -> None:
    msg = f"The vendor spent INR {amount} but this cannot be answered."
    outcome = _CTRL.abstain(condition, msg)
    assert outcome.outcome == "abstained"
    assert outcome.reason_code in REASON_CODES or outcome.reason_code == PIPELINE_FAULT
    assert outcome.breakdown_excluded is True
    assert not _has_money(outcome.message)


def test_p5_coverage_dates_survive_suppression() -> None:
    # period_outside_coverage may state the dataset coverage dates (R18.6) and nothing else.
    msg = "No data for 2019; coverage is 2023-01-01 to 2024-12-31 and 500 rows exist."
    outcome = _CTRL.abstain(
        "period_outside_coverage", msg, coverage_dates=("2023-01-01", "2024-12-31")
    )
    assert "2023-01-01" in outcome.message
    assert "2024-12-31" in outcome.message
    # the stray "2019" and "500" figures are stripped
    assert "2019" not in outcome.message
    assert "500" not in outcome.message


@given(
    condition=st.sampled_from(sorted(CLARIFY_REASONS)),
    options=st.lists(st.text(min_size=1, max_size=12), min_size=0, max_size=9),
)
def test_p5_clarification_offers_at_most_five_options(condition, options) -> None:
    outcome = _CTRL.clarify(condition, "Which one did you mean?", options)
    assert outcome.outcome == "clarification_requested"
    assert outcome.reason_code in REASON_CODES
    assert len(outcome.options) <= 5
    assert outcome.breakdown_excluded is True


# ---- clarification lifecycle (R18.2 / R18.11) -----------------------------------------
def test_clarification_exhaustion() -> None:
    # Round 0 -> a clarifying question (round 1); round 2 used -> exhausted.
    first = _CTRL.next_clarification(
        current_round_count=0, ambiguity="which vendor", options=["a", "b"]
    )
    assert first.outcome == "clarification_requested"

    exhausted = _CTRL.next_clarification(
        current_round_count=2, ambiguity="which vendor", options=["a", "b"]
    )
    assert exhausted.outcome == "abstained"
    assert exhausted.reason_code == "clarification_exhausted"


# ---- confidence gate (R18.3 / R18.13) -------------------------------------------------
def test_low_confidence_with_ambiguity_clarifies() -> None:
    outcome = _CTRL.on_low_confidence(
        named_ambiguity="which period", weakest_signal="schema_linking_margin"
    )
    assert outcome.outcome == "clarification_requested"
    assert outcome.reason_code == "confidence_below_threshold"


def test_low_confidence_without_ambiguity_abstains_naming_weakest() -> None:
    outcome = _CTRL.on_low_confidence(
        named_ambiguity=None, weakest_signal="row_count_sanity"
    )
    assert outcome.outcome == "abstained"
    assert outcome.reason_code == "confidence_below_threshold"
    assert outcome.weakest_signal == "row_count_sanity"
    assert not _has_money(outcome.message)
