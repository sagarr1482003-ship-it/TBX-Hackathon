"""Typed error taxonomy (design "Typed error taxonomy" table).

Every error carries a ``code``, a human ``message``, an optional ``abstention_reason`` and
a ``retryable`` flag. The rule that makes the taxonomy useful: **an error with
``abstention_reason = None`` is a bug, not a user-facing outcome** — the orchestrator's
outermost handler records it as ``pipeline_fault`` and converts it to the closest reason
code. There is no path from an internal error to a stated figure.

The ``abstention_reason`` column is *total* over the exception hierarchy. Some errors map
to ``None`` deliberately (they are handled before Turn creation, or via a non-abstention
path such as the voice repeat-request response or an ingestion report). Those are recorded
in :data:`DOCUMENTED_NONE_REASON` so ``test_error_taxonomy`` can distinguish a deliberate
``None`` from a missing mapping. This is the implementation half of Property 31.
"""

from __future__ import annotations

from typing import ClassVar

# The 21-value abstention reason-code enumeration (Requirement 18.4), plus the internal
# ``pipeline_fault`` marker the orchestrator uses for an unmapped internal error.
REASON_CODES: frozenset[str] = frozenset(
    {
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
)

# Internal-only reason marker (not part of the user-facing 18.4 enumeration).
PIPELINE_FAULT = "pipeline_fault"


class TbxError(Exception):
    """Base class for every typed error in the system.

    Subclasses set :attr:`code`, :attr:`abstention_reason` and :attr:`retryable` as class
    attributes. ``abstention_reason`` is either a member of :data:`REASON_CODES` or ``None``
    (a deliberate, documented non-abstention path — see :data:`DOCUMENTED_NONE_REASON`).
    """

    code: ClassVar[str] = "tbx_error"
    abstention_reason: ClassVar[str | None] = None
    retryable: ClassVar[bool] = False

    def __init__(self, message: str = "", **context: object) -> None:
        super().__init__(message)
        self.message = message
        self.context = context


# --- Chat_API / intake -----------------------------------------------------------------
class QuestionLengthError(TbxError):
    """Raised by Chat_API: 400 before Turn creation (question length out of 1..1000)."""

    code = "question_length"
    abstention_reason = None  # rejected with 400 before a Turn exists
    retryable = False


# --- Query_Planner ---------------------------------------------------------------------
class IntentUnsupportedError(TbxError):
    code = "intent_unsupported"
    abstention_reason = "intent_unsupported"
    retryable = False


class EntityUnresolvedError(TbxError):
    code = "entity_unresolved"
    abstention_reason = "entity_not_found"
    retryable = False


class EntityAmbiguousError(TbxError):
    code = "entity_ambiguous"
    abstention_reason = "ambiguous_entity"
    retryable = False  # clarify path


class DateRangeAmbiguousError(TbxError):
    code = "date_range_ambiguous"
    abstention_reason = "ambiguous_date_range"
    retryable = False  # clarify path


class GroupingAmbiguousError(TbxError):
    code = "grouping_ambiguous"
    abstention_reason = "ambiguous_grouping"
    retryable = False  # clarify path


class PeriodOutsideCoverageError(TbxError):
    code = "period_outside_coverage"
    abstention_reason = "period_outside_coverage"
    retryable = False


class DataAbsentError(TbxError):
    code = "data_absent"
    abstention_reason = "data_absent"
    retryable = False


# --- Metric_Layer ----------------------------------------------------------------------
class MetricAmbiguousError(TbxError):
    code = "metric_ambiguous"
    abstention_reason = "ambiguous_metric"
    retryable = False  # clarify path


# --- Context_Resolver ------------------------------------------------------------------
class ReferenceUnresolvedError(TbxError):
    code = "reference_unresolved"
    abstention_reason = "reference_unresolved"
    retryable = False  # clarify path


# --- Abstention_Controller -------------------------------------------------------------
class ClarificationExhaustedError(TbxError):
    code = "clarification_exhausted"
    abstention_reason = "clarification_exhausted"
    retryable = False


# --- Schema_Linker ---------------------------------------------------------------------
class SchemaLinkingFailedError(TbxError):
    code = "schema_linking_failed"
    abstention_reason = "schema_linking_failed"
    retryable = False


# --- SQL_Generator ---------------------------------------------------------------------
class GenerationFailedError(TbxError):
    code = "generation_failed"
    abstention_reason = "generation_failed"
    retryable = True  # <=2 generation retries first


# --- SQL_Validator ---------------------------------------------------------------------
class ValidationRejectedError(TbxError):
    """No direct abstention reason: becomes a repair reason inside the orchestrator."""

    code = "validation_rejected"
    abstention_reason = None  # documented: converted into a repair reason
    retryable = True


# --- orchestrator ----------------------------------------------------------------------
class RepairLimitReachedError(TbxError):
    code = "repair_limit_reached"
    abstention_reason = "repair_limit_reached"
    retryable = False


# --- Reviewer_Agent --------------------------------------------------------------------
class ReviewerUnavailableError(TbxError):
    code = "reviewer_unavailable"
    abstention_reason = "reviewer_unavailable"
    retryable = True  # <=1 verdict re-request first


# --- Query_Executor --------------------------------------------------------------------
class MetricExecutionFailedError(TbxError):
    """A bound template failed to execute; no fallback to generated SQL (Requirement 4)."""

    code = "metric_execution_failed"
    abstention_reason = "metric_execution_failed"
    retryable = False


class QueryTimeoutError(TbxError):
    """Timeout maps to ``data_absent`` if the plan is sound, else ``pipeline_fault``.

    The default mapping recorded here is ``data_absent`` (plan-sound case); the
    orchestrator downgrades to ``generation_failed`` via ``pipeline_fault`` when the plan
    is unsound. Both are valid reason codes.
    """

    code = "query_timeout"
    abstention_reason = "data_absent"
    retryable = True  # repair once


class RowCapExceededError(TbxError):
    code = "row_cap_exceeded"
    abstention_reason = "generation_failed"
    retryable = True  # repair once (add a limit / tighten filters)


class ExecutionCapacityError(TbxError):
    code = "execution_capacity"
    abstention_reason = "budget_exhausted"
    retryable = False


class DatasetVersionChangedError(TbxError):
    code = "dataset_version_changed"
    abstention_reason = "dataset_version_changed"
    retryable = False


# --- Budget_Guard ----------------------------------------------------------------------
class BudgetExhaustedError(TbxError):
    code = "budget_exhausted"
    abstention_reason = "budget_exhausted"
    retryable = False


# --- Model_Router ----------------------------------------------------------------------
class ProviderUnavailableError(TbxError):
    code = "provider_unavailable"
    abstention_reason = "provider_unavailable"
    retryable = True  # <=2 per provider, <=6 total first


class StructuredOutputError(TbxError):
    code = "structured_output"
    abstention_reason = "provider_unavailable"
    retryable = True  # 1 retry, then fallback provider


class EmbeddingDimensionMismatchError(TbxError):
    code = "embedding_dimension_mismatch"
    abstention_reason = "embedding_dimension_mismatch"
    retryable = False


# --- Confidence_Scorer -----------------------------------------------------------------
class ConfidenceBelowThresholdError(TbxError):
    code = "confidence_below_threshold"
    abstention_reason = "confidence_below_threshold"
    retryable = False


# --- Buddy_Agent -----------------------------------------------------------------------
class TermUndefinedError(TbxError):
    code = "term_undefined"
    abstention_reason = "term_undefined"
    retryable = False


# --- Speech_Transcriber ----------------------------------------------------------------
class TranscriptionFailedError(TbxError):
    """Non-abstention: surfaced to the client as a repeat-request response."""

    code = "transcription_failed"
    abstention_reason = None  # documented: repeat-request response, not an abstention
    retryable = True  # <=2 attempts first


# --- Speech_Synthesizer ----------------------------------------------------------------
class SynthesisFailedError(TbxError):
    """Non-abstention: the written answer is returned with a flag."""

    code = "synthesis_failed"
    abstention_reason = None  # documented: written answer + flag, not an abstention
    retryable = True  # <=2 attempts per segment


# --- Ingestion_Service -----------------------------------------------------------------
class ManifestInvalidError(TbxError):
    """Non-abstention: 400, no load performed."""

    code = "manifest_invalid"
    abstention_reason = None  # documented: 400 before any load, not a Turn outcome
    retryable = False


class IngestionFailedError(TbxError):
    """Non-abstention: recorded in the ingestion report; active version kept."""

    code = "ingestion_failed"
    abstention_reason = None  # documented: report path, active version retained
    retryable = False


# --- contract.py -----------------------------------------------------------------------
class ContractBlockingDeviationError(TbxError):
    """Non-abstention: abort the load; nothing changed."""

    code = "contract_blocking_deviation"
    abstention_reason = None  # documented: abort, nothing changed
    retryable = False


# --- startup_checks --------------------------------------------------------------------
class StartupCheckError(TbxError):
    """Non-abstention: process exits non-zero; the listener never binds."""

    code = "startup_check"
    abstention_reason = None  # documented: exit non-zero, no listener
    retryable = False


# --------------------------------------------------------------------------------------
# The set of TbxError subclasses whose ``abstention_reason`` is deliberately ``None``.
# ``test_error_taxonomy`` uses this to distinguish a documented non-abstention path from a
# missing mapping — adding a new subclass with reason ``None`` must be recorded here.
# --------------------------------------------------------------------------------------
DOCUMENTED_NONE_REASON: frozenset[str] = frozenset(
    {
        "QuestionLengthError",
        "ValidationRejectedError",
        "TranscriptionFailedError",
        "SynthesisFailedError",
        "ManifestInvalidError",
        "IngestionFailedError",
        "ContractBlockingDeviationError",
        "StartupCheckError",
    }
)


def all_error_classes() -> list[type[TbxError]]:
    """Return every concrete ``TbxError`` subclass in the hierarchy (recursively)."""
    seen: set[type[TbxError]] = set()
    stack: list[type[TbxError]] = list(TbxError.__subclasses__())
    result: list[type[TbxError]] = []
    while stack:
        cls = stack.pop()
        if cls in seen:
            continue
        seen.add(cls)
        result.append(cls)
        stack.extend(cls.__subclasses__())
    return result
