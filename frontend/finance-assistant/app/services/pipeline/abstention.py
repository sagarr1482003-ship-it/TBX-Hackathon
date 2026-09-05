"""Abstention_Controller — the finite, exhaustively testable mapping from every terminating
condition to exactly one of the 21 Requirement 18.4 reason codes, plus the outcome shaping
that keeps an abstention free of any stated figure (Requirement 18).

Design rationale (§4.3 component table): "A finite mapping from terminating conditions to 21
reason codes. A lookup table is exhaustively testable; a model is not." This module is that
lookup table and the deterministic decisions around it:

- data-absent abstentions name the missing data and the supported families (R18.1);
- one clarifying question offers at most 5 concrete options and increments the pending
  clarification round count (R18.2), which is capped at ``clarification_round_limit`` and then
  becomes ``clarification_exhausted`` (R18.11);
- an abstention excludes the breakdown table and suppresses every numeric value other than the
  dataset coverage dates permitted by R18.6 (R18.4);
- sub-threshold confidence routes to clarification when an ambiguity was named (R18.3) and to
  ``confidence_below_threshold`` naming the weakest signal when none was (R18.13);
- ``true_empty_result`` completes as an answer, keeping ``data_absent`` reserved for
  schema-level absence (R18.10).

Pure logic; no database and no model call. The database-backed recording of each abstention
(R18.8) is performed by the orchestrator using the :class:`AbstentionOutcome` this returns.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from app.errors import PIPELINE_FAULT, REASON_CODES, TbxError

Outcome = Literal["abstained", "clarification_requested"]

# The terminating conditions the pipeline can raise, mapped to the reason code each one
# carries. This is the *total* mapping half of Property 31: every terminating condition maps
# to exactly one reason code in the Requirement 18.4 enumeration. Conditions are keyed by the
# stable condition name the orchestrator uses (design run_turn pseudocode + Error handling
# table). An internal/unmapped error becomes ``pipeline_fault`` -> data_absent-family handling
# is *not* applied; instead the orchestrator records pipeline_fault and abstains with the
# nearest documented reason, so no condition ever yields a figure.
CONDITION_REASON: dict[str, str] = {
    # intake / query planner
    "intent_unsupported": "intent_unsupported",
    "entity_not_found": "entity_not_found",
    "ambiguous_entity": "ambiguous_entity",
    "ambiguous_metric": "ambiguous_metric",
    "ambiguous_date_range": "ambiguous_date_range",
    "ambiguous_grouping": "ambiguous_grouping",
    "reference_unresolved": "reference_unresolved",
    "period_outside_coverage": "period_outside_coverage",
    "data_absent": "data_absent",
    # clarification lifecycle
    "clarification_exhausted": "clarification_exhausted",
    "confidence_below_threshold": "confidence_below_threshold",
    # schema / generation
    "schema_linking_failed": "schema_linking_failed",
    "generation_failed": "generation_failed",
    # reviewer / repair
    "repair_limit_reached": "repair_limit_reached",
    "reviewer_unavailable": "reviewer_unavailable",
    # execution
    "metric_execution_failed": "metric_execution_failed",
    "dataset_version_changed": "dataset_version_changed",
    # budget / provider / embedding
    "budget_exhausted": "budget_exhausted",
    "provider_unavailable": "provider_unavailable",
    "embedding_dimension_mismatch": "embedding_dimension_mismatch",
    # buddy
    "term_undefined": "term_undefined",
}

# Conditions that are surfaced as a clarifying question rather than a flat abstention.
CLARIFY_REASONS: frozenset[str] = frozenset(
    {
        "ambiguous_entity",
        "ambiguous_metric",
        "ambiguous_date_range",
        "ambiguous_grouping",
        "reference_unresolved",
    }
)


@dataclass
class AbstentionOutcome:
    outcome: Outcome
    reason_code: str
    message: str
    # At most 5 concrete options for a clarifying question (R18.2), ordered by the caller.
    options: list[str] = field(default_factory=list)
    # Coverage dates permitted in the message for period_outside_coverage (R18.6); the only
    # numeric values allowed to survive suppression.
    coverage_dates: tuple[str, str] | None = None
    # The weakest contributing confidence signal for confidence_below_threshold (R18.13).
    weakest_signal: str | None = None
    breakdown_excluded: bool = True  # R18.4: an abstention never carries a breakdown table


class AbstentionController:
    def __init__(self, clarification_round_limit: int = 2) -> None:
        self.clarification_round_limit = clarification_round_limit

    # ---- reason-code mapping (total over terminating conditions) ----------------------
    def reason_for_condition(self, condition: str) -> str:
        """Return the reason code for a terminating condition, or ``pipeline_fault``.

        Total: every condition either maps to a Requirement 18.4 code or is treated as an
        internal fault (``pipeline_fault``), which the orchestrator records and converts —
        it never produces a figure.
        """
        return CONDITION_REASON.get(condition, PIPELINE_FAULT)

    def reason_for_error(self, err: TbxError) -> str:
        """Map a raised :class:`TbxError` to its reason code, or ``pipeline_fault``.

        An error whose ``abstention_reason`` is ``None`` is a deliberate non-abstention
        path (handled elsewhere) or an internal fault; either way it must not become a
        figure, so it is reported as ``pipeline_fault`` here.
        """
        reason = err.abstention_reason
        if reason is None:
            return PIPELINE_FAULT
        return reason

    # ---- outcome construction ---------------------------------------------------------
    def abstain(self, condition: str, message: str, **extra: object) -> AbstentionOutcome:
        reason = self.reason_for_condition(condition)
        return AbstentionOutcome(
            outcome="abstained",
            reason_code=reason,
            message=self._suppress_numerals(
                message, coverage_dates=extra.get("coverage_dates")  # type: ignore[arg-type]
            ),
            coverage_dates=extra.get("coverage_dates"),  # type: ignore[arg-type]
            weakest_signal=extra.get("weakest_signal"),  # type: ignore[arg-type]
        )

    def clarify(
        self, condition: str, message: str, options: list[str]
    ) -> AbstentionOutcome:
        reason = self.reason_for_condition(condition)
        return AbstentionOutcome(
            outcome="clarification_requested",
            reason_code=reason,
            message=message,
            options=options[:5],  # at most 5 concrete options (R18.2)
            breakdown_excluded=True,
        )

    # ---- confidence gate (R18.3 / R18.13) ---------------------------------------------
    def on_low_confidence(
        self,
        *,
        named_ambiguity: str | None,
        weakest_signal: str | None,
        options: list[str] | None = None,
    ) -> AbstentionOutcome:
        """Route a sub-threshold-confidence Turn.

        With a named ambiguity -> one clarifying question naming that ambiguity (R18.3).
        Without one -> abstain with ``confidence_below_threshold`` naming the weakest
        contributing confidence signal (R18.13).
        """
        if named_ambiguity is not None:
            return AbstentionOutcome(
                outcome="clarification_requested",
                reason_code="confidence_below_threshold",
                message=f"Please clarify: {named_ambiguity}.",
                options=(options or [])[:5],
            )
        return AbstentionOutcome(
            outcome="abstained",
            reason_code="confidence_below_threshold",
            message=(
                "I am not confident enough in this answer to state a figure. "
                f"The weakest supporting signal was {weakest_signal}."
            ),
            weakest_signal=weakest_signal,
        )

    # ---- clarification lifecycle (R18.2 / R18.11) -------------------------------------
    def next_clarification(
        self, *, current_round_count: int, ambiguity: str, options: list[str]
    ) -> AbstentionOutcome:
        """Produce the next clarifying question, or exhaust the clarification budget.

        The round count is the count *already* used; a new clarifying question increments it
        by one. Reaching ``clarification_round_limit`` yields ``clarification_exhausted``.
        """
        next_round = current_round_count + 1
        if next_round > self.clarification_round_limit:
            return self.abstain(
                "clarification_exhausted",
                f"I still cannot resolve the ambiguity: {ambiguity}.",
            )
        return self.clarify(
            ambiguity_condition(ambiguity), f"Please clarify: {ambiguity}.", options
        )

    # ---- numeric suppression (R18.4) --------------------------------------------------
    @staticmethod
    def _suppress_numerals(message: str, coverage_dates: tuple[str, str] | None) -> str:
        """Strip every numeric value from an abstention message except the coverage dates.

        Requirement 18.4 forbids an abstention answer from stating any numeric value other
        than the dataset coverage dates permitted by R18.6. We keep the coverage dates by
        placeholder-substituting them out before stripping and restoring them after.
        """
        if not _contains_digit(message):
            return message
        placeholders: dict[str, str] = {}
        protected = message
        if coverage_dates is not None:
            # Digit-free placeholder keys (A/B) so the numeral-stripping regex below cannot
            # corrupt the protected coverage tokens.
            for key_char, token in zip(("A", "B"), coverage_dates):
                key = f"\x00COVERAGE{key_char}\x00"
                placeholders[key] = token
                protected = protected.replace(token, key)
        # Remove any remaining digit runs (and adjacent decimal points / separators).
        stripped = re.sub(r"[0-9][0-9,\.]*", "", protected)
        for key, token in placeholders.items():
            stripped = stripped.replace(key, token)
        return re.sub(r"\s{2,}", " ", stripped).strip()


def ambiguity_condition(ambiguity: str) -> str:
    """Best-effort map an ambiguity label to a clarify condition; default ambiguous_entity."""
    a = ambiguity.lower()
    if "metric" in a:
        return "ambiguous_metric"
    if "date" in a or "period" in a:
        return "ambiguous_date_range"
    if "group" in a:
        return "ambiguous_grouping"
    if "refer" in a:
        return "reference_unresolved"
    return "ambiguous_entity"


def _contains_digit(text: str) -> bool:
    return any(ch.isdigit() for ch in text)


# Sanity: every mapped reason code is a member of the Requirement 18.4 enumeration.
assert set(CONDITION_REASON.values()) <= REASON_CODES
