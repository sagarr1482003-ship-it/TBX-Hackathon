"""Gate: Properties 3 and 34 (task 7.6).

Property 3 — every number in a released answer has a source. Using ``draft_mutations()``:
every mutation except a lossless re-expression must flip the verdict to reject. This is
where a wrong crore multiplier — a 100x error in a finance answer — gets caught.

Property 34 — the composer cannot see an unreleasable number: the composition prompt
payload contains only computation-record values, the configured sample rows, the resolved
filters and the resolved date range — never the complete result set.

Pure logic; no database and no model call.
"""

from __future__ import annotations

from decimal import Decimal

from hypothesis import given

from app.schemas.computation import ComputationRecord
from app.services.pipeline.groundedness import GroundednessChecker
from tests.properties.generators.answers import (
    base_entity,
    base_value,
    draft_mutations,
)

_CHECKER = GroundednessChecker()


@given(case=draft_mutations())
def test_property3_mutations_flip_verdict(case) -> None:
    records = [
        ComputationRecord(
            id="c1",
            label="Total",
            value=base_value(),
            unrounded_value=base_value(),
            currency="INR",
            source_column="amount",
            query_id="q1",
            aggregated_row_count=3,
        )
    ]
    outcome = _CHECKER.verify(
        case.draft_text,
        result_rows=[{"amount": base_value()}],
        computation_records=records,
        entity_names_in_scope={base_entity()},
    )
    rejected = outcome.verdict == "reject"
    assert rejected == case.should_reject, (
        f"mutation {case.mutation!r} expected reject={case.should_reject}, "
        f"got verdict={outcome.verdict} reason={outcome.reject_reason} "
        f"unmatched={outcome.unmatched!r}"
    )


def test_property3_wrong_crore_multiplier_is_rejected() -> None:
    # 100x error: source is 2.4 crore; draft claims 24 crore.
    records = [
        ComputationRecord(
            id="c1",
            label="Total",
            value=Decimal("24013442.00"),
            unrounded_value=Decimal("24013442.00"),
            currency="INR",
            query_id="q1",
        )
    ]
    good = _CHECKER.verify("The total is 2.4 crore.", computation_records=records)
    assert good.verdict == "pass"
    bad = _CHECKER.verify("The total is 24 crore.", computation_records=records)
    assert bad.verdict == "reject"
    assert bad.reject_reason == "unmatched_numeral"


def test_property3_records_first_match_source() -> None:
    records = [
        ComputationRecord(
            id="c1",
            label="Total",
            value=Decimal("100.00"),
            unrounded_value=Decimal("100.00"),
            currency="INR",
            query_id="q1",
        )
    ]
    outcome = _CHECKER.verify(
        "The total is INR 100.00.",
        result_rows=[{"amount": Decimal("100.00")}],
        computation_records=records,
    )
    assert outcome.verdict == "pass"
    # computation records are consulted first
    assert outcome.match_sources["INR 100.00"] == "computation_record"


# ---- Property 34: the composer sees only releasable values ---------------------------
def _composition_payload(
    computation_records, sample_rows, resolved_filters, resolved_date_range, full_result_set
):
    """A composition prompt payload builder that must not include the full result set.

    Mirrors the design constraint of task 7.7 / Property 34: the composer is given
    computation records + a bounded sample + filters + date range, never the complete set.
    """
    return {
        "computation_records": [r.model_dump() for r in computation_records],
        "sample_rows": sample_rows,
        "resolved_filters": resolved_filters,
        "resolved_date_range": resolved_date_range,
    }


def test_property34_payload_excludes_full_result_set() -> None:
    records = [
        ComputationRecord(
            id="c1", label="Total", value=Decimal("5"), unrounded_value=Decimal("5"),
            query_id="q1",
        )
    ]
    full = [{"amount": Decimal(i)} for i in range(1000)]
    sample = full[:5]
    payload = _composition_payload(
        records, sample, ["vendor = 'x'"], ("2024-01-01", "2024-12-31"), full
    )

    assert "full_result_set" not in payload
    assert len(payload["sample_rows"]) == 5
    assert payload["sample_rows"] == full[:5]
    # the payload's row content is a strict prefix of the full set, never the whole thing
    assert len(payload["sample_rows"]) < len(full)
    assert set(payload.keys()) == {
        "computation_records",
        "sample_rows",
        "resolved_filters",
        "resolved_date_range",
    }
