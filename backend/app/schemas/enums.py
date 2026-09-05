"""Shared literal enumerations used across schema modules."""

from __future__ import annotations

from typing import Literal

# The ten supported intent families (Requirement 1.2), scoped to the organiser
# bank/account/transaction schema (no vendor, payout or reconciliation tables exist).
IntentFamily = Literal[
    "bank_summary",
    "account_balance",
    "account_spend",
    "transaction_lookup",
    "reference_lookup",
    "credit_summary",
    "period_comparison",
    "metric_definition",
    "analytics_question",
    "unsupported",
]

# The 21-value abstention reason enumeration (Requirement 18.4).
AbstentionReason = Literal[
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
]

ColumnType = Literal["text", "integer", "numeric", "date", "timestamp", "boolean"]
