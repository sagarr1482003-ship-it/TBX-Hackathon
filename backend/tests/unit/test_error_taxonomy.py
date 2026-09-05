"""Property 31 (mapping-totality half).

Enumerate every ``TbxError`` subclass and assert each maps either to a reason code drawn
from the Requirement 18.4 enumeration or to a documented ``None``. No exception class can
be added without a mapping — an unrecorded ``None`` fails the test.
"""

from __future__ import annotations

import app.errors as errors
from app.errors import (
    DOCUMENTED_NONE_REASON,
    REASON_CODES,
    TbxError,
    all_error_classes,
)


def test_every_subclass_has_a_total_reason_mapping() -> None:
    classes = all_error_classes()
    assert classes, "expected at least one TbxError subclass"
    for cls in classes:
        reason = cls.abstention_reason
        if reason is None:
            assert cls.__name__ in DOCUMENTED_NONE_REASON, (
                f"{cls.__name__} maps to None but is not recorded in "
                f"DOCUMENTED_NONE_REASON; every deliberate non-abstention path must be "
                f"documented so a missing mapping cannot masquerade as a deliberate one."
            )
        else:
            assert reason in REASON_CODES, (
                f"{cls.__name__} maps to reason code {reason!r} which is not in the "
                f"Requirement 18.4 enumeration."
            )


def test_documented_none_set_has_no_stale_entries() -> None:
    live_names = {c.__name__ for c in all_error_classes()}
    stale = DOCUMENTED_NONE_REASON - live_names
    assert not stale, f"DOCUMENTED_NONE_REASON references nonexistent classes: {stale}"


def test_documented_none_entries_actually_map_to_none() -> None:
    by_name = {c.__name__: c for c in all_error_classes()}
    for name in DOCUMENTED_NONE_REASON:
        assert by_name[name].abstention_reason is None, (
            f"{name} is listed as a documented-None error but has a non-None reason."
        )


def test_every_subclass_has_code_and_retryable() -> None:
    for cls in all_error_classes():
        assert isinstance(cls.code, str) and cls.code, f"{cls.__name__} missing a code"
        assert isinstance(cls.retryable, bool), f"{cls.__name__} retryable not a bool"


def test_reason_codes_match_requirement_enumeration() -> None:
    # The exact 21-value enumeration from Requirement 18.4.
    expected = {
        "data_absent",
        "intent_unsupported",
        "ambiguous_entity",
        "ambiguous_metric",
        "ambiguous_date_range",
        "ambiguous_grouping",
        "reference_unresolved",
        "clarification_exhausted",
        "confidence_below_threshold",
        "period_outside_coverage",
        "entity_not_found",
        "repair_limit_reached",
        "budget_exhausted",
        "provider_unavailable",
        "schema_linking_failed",
        "generation_failed",
        "reviewer_unavailable",
        "dataset_version_changed",
        "metric_execution_failed",
        "term_undefined",
        "embedding_dimension_mismatch",
    }
    assert REASON_CODES == expected
    assert len(REASON_CODES) == 21


def test_every_reason_code_is_reachable_from_some_error() -> None:
    """Total in the other direction: no reason code is orphaned from the hierarchy.

    ``dataset_version_changed`` etc. must each be produced by at least one error class,
    otherwise the enumeration and the taxonomy have silently drifted apart.
    """
    produced = {
        c.abstention_reason for c in all_error_classes() if c.abstention_reason is not None
    }
    unreachable = REASON_CODES - produced
    # Reason codes with no direct error class are produced by controller logic rather than
    # an exception. Only these two are permitted to be controller-only.
    controller_only = {"confidence_below_threshold"} & REASON_CODES
    truly_unreachable = unreachable - controller_only
    # confidence_below_threshold *does* have ConfidenceBelowThresholdError, so expect none.
    assert not truly_unreachable, f"reason codes with no producing error: {truly_unreachable}"


def test_base_class_is_exception() -> None:
    assert issubclass(TbxError, Exception)
    assert errors.PIPELINE_FAULT == "pipeline_fault"
    assert errors.PIPELINE_FAULT not in REASON_CODES
