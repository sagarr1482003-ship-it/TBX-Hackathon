"""Typed application settings.

A single ``Settings`` object (pydantic-settings) is the only source of configuration.
Every value stated in the requirements.md Configuration Inventory and every value in the
design's "New configuration introduced by design" table is represented here with the
stated default, held as a named module-level constant.

Blank-environment-variable coercion: a ``field_validator(mode="before")`` maps an empty
string (a set-but-empty environment variable) back to the field default rather than
letting Pydantic raise a validation error at startup. This mirrors the convention
inherited from the reference project (RN-8).
"""

from __future__ import annotations

from decimal import Decimal
from functools import lru_cache
from typing import Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# --------------------------------------------------------------------------------------
# Defaults as named module constants (requirements.md Configuration Inventory).
# Where a criterion and this module disagree, the criterion is authoritative.
# --------------------------------------------------------------------------------------

# Question intake and conversation
DEFAULT_REFERENCE_DATE: str | None = None  # None => latest transaction date in active dataset
DEFAULT_MIN_FUZZY_MATCH_SCORE = 0.85
DEFAULT_DISAMBIGUATION_MARGIN = 0.05
DEFAULT_CONVERSATION_STATE_TURN_COUNT = 10
DEFAULT_SESSION_CONTEXT_TIMEOUT = 30 * 60  # seconds

# Schema KB and metric layer
DEFAULT_SCHEMA_KB_SAMPLE_VALUE_COUNT = 20
DEFAULT_SCHEMA_LINK_PROMPT_TOKEN_BUDGET = 1500
DEFAULT_MIN_COMBINED_RETRIEVAL_SCORE = 0.350
DEFAULT_MAX_JOIN_PATH_LENGTH = 2
DEFAULT_SCHEMA_LINK_TABLE_RECALL_TARGET = 0.95
DEFAULT_TEMPLATE_MATCH_THRESHOLD = 0.80
DEFAULT_TEMPLATE_TIE_MARGIN = 0.05

# Dataset ingestion
DEFAULT_RETAINED_DATASET_VERSION_COUNT = 2
DEFAULT_REJECTED_ROW_TOLERANCE = 0.01  # 1% of source rows
DEFAULT_SOURCE_FILE_ENCODING = "utf-8"
DEFAULT_API_REQUEST_TIMEOUT = 30  # seconds
DEFAULT_API_INGESTION_DEADLINE = 1800  # seconds
DEFAULT_MAX_PAGES_PER_ENTITY = 1000

# Model provider and budgets
DEFAULT_MODEL_REQUEST_TIMEOUT = 30  # seconds
DEFAULT_MODEL_PARAMETER_CEILING = 8_000_000_000  # 8 billion parameters
DEFAULT_MAX_LLM_CALLS_PER_QUESTION = 6
DEFAULT_MAX_TOKENS_PER_QUESTION = 12000
DEFAULT_QUESTION_WALLCLOCK_DEADLINE = 30  # seconds
DEFAULT_METRIC_LAYER_CALL_LIMIT = 3
DEFAULT_BUDGET_HARD_CEILING_CALLS = 10
DEFAULT_BUDGET_HARD_CEILING_TOKENS = 32000
DEFAULT_BUDGET_HARD_CEILING_SECONDS = 60
DEFAULT_TARGET_SQL_DIALECT = "postgres"
DEFAULT_EXEMPLAR_COUNT = 4
DEFAULT_MAX_CANDIDATES_PER_QUESTION = 3
DEFAULT_CANDIDATE_GENERATION_RETRY_LIMIT = 2

# SQL validation and execution
DEFAULT_DEFAULT_ROW_LIMIT = 1000
DEFAULT_MAX_DECLARED_ROW_LIMIT = 100000
DEFAULT_STATEMENT_TIMEOUT = 10  # seconds
DEFAULT_EXECUTION_ROW_CAP = 100000
DEFAULT_MAX_CONCURRENT_QUERIES = 8
DEFAULT_EXECUTION_QUEUE_WAIT_TIMEOUT = 5  # seconds
DEFAULT_MAX_EXECUTIONS_PER_TURN = 12

# Reviewer
DEFAULT_REPAIR_ITERATION_LIMIT = 2
DEFAULT_REVIEWER_DEADLINE = 8  # seconds
DEFAULT_REVIEWER_OUTPUT_RETRY_LIMIT = 1
DEFAULT_DRY_RUN_LIMIT_PER_TURN = 5
DEFAULT_DRY_RUN_DEADLINE = 3  # seconds
DEFAULT_REVIEWER_PHASE_DEADLINE = 20  # seconds

# Computation and answers
DEFAULT_DISPLAY_PRECISION = 2
DEFAULT_ANSWER_PREVIEW_ROW_LIMIT = 100
DEFAULT_MAX_ANSWER_LENGTH = 120
DEFAULT_MAX_ANSWER_LENGTH_DETAILED = 400
DEFAULT_MAX_DRILLDOWN_SIZE = 500

# Groundedness and abstention
DEFAULT_GROUNDEDNESS_MATCH_TOLERANCE = 0.01
DEFAULT_CLARIFICATION_ROUND_LIMIT = 2
DEFAULT_UNHELPFUL_REFUSAL_CEILING = 0.05  # 5% of `answer`-class golden entries

# Confidence
DEFAULT_CONFIDENCE_SIGNAL_WEIGHTS: dict[str, float] = {
    "template_match": 0.15,
    "candidate_agreement": 0.15,
    "reviewer_verdict": 0.20,
    "schema_linking_margin": 0.10,
    "row_count_sanity": 0.10,
    "groundedness": 0.20,
    "repair_iterations": 0.05,
    "execution_success": 0.05,
}
DEFAULT_CONFIDENCE_BAND_BOUNDARIES: dict[str, float] = {"medium": 0.50, "high": 0.80}
DEFAULT_ACCEPTANCE_THRESHOLD = 0.60
DEFAULT_CALIBRATION_MIN_BAND_SIZE = 10
DEFAULT_BAND_MIN_ACCURACY: dict[str, float] = {"high": 0.90, "medium": 0.60, "low": 0.0}

# Anomaly
DEFAULT_ANOMALY_Z_THRESHOLD = 3.5
DEFAULT_ANOMALY_MIN_HISTORY_COUNT = 6
DEFAULT_ANOMALY_MAX_ENTITIES_PER_TURN = 20
DEFAULT_ANOMALY_HISTORY_WINDOW = 24  # months
DEFAULT_ANOMALY_MAX_HISTORY_ROWS = 500
DEFAULT_ZERO_DISPERSION_RELATIVE_THRESHOLD = 0.20
DEFAULT_ZERO_DISPERSION_ABSOLUTE_FLOOR = Decimal("1000")
DEFAULT_ANOMALY_EVALUATION_RESERVE = 1
DEFAULT_ANOMALY_EVALUATION_TIME_LIMIT = 1500  # milliseconds

# Trace
DEFAULT_TRACE_REPLAY_RETENTION = 15 * 60  # seconds after terminal event
DEFAULT_TRACE_KEEPALIVE_INTERVAL = 10  # seconds
DEFAULT_MAX_TRACE_EVENT_SIZE = 32 * 1024  # bytes
DEFAULT_MAX_INLINE_SAMPLE_ROWS = 20
DEFAULT_TRACE_PERSISTENCE_WINDOW = 1000  # milliseconds after emission
DEFAULT_TRACE_SUMMARY_PAGE_SIZE = 50
DEFAULT_TRACE_SUMMARY_PAGE_SIZE_MAX = 200
DEFAULT_TRACE_RETENTION_PERIOD = 30  # days after turn creation
DEFAULT_TURN_ABANDONMENT_WINDOW = 300  # seconds after last emitted event
DEFAULT_MAX_PERSISTED_FIELD_LENGTH = 16384
DEFAULT_TRACE_BUFFER_MAX_EVENTS = 2000  # design-added

# Export
DEFAULT_RESULT_SNAPSHOT_RETENTION = 30  # days
DEFAULT_MAX_EXPORT_ROWS = 100000
DEFAULT_EXPORT_DEADLINE = 60  # seconds

# Failure store and improvement
DEFAULT_FAILURE_CASE_ROW_COUNT = 100
DEFAULT_MAX_FAILURE_CASES = 10000
DEFAULT_MAX_PROPOSALS_PER_RUN = 20
DEFAULT_IMPROVEMENT_EVALUATION_TIMEOUT = 1800  # seconds
DEFAULT_ARTEFACT_VERSION_RETENTION_COUNT = 10

# Evaluation
DEFAULT_EVALUATION_REPEAT_COUNT = 3
DEFAULT_EVALUATION_RUN_TOKEN_BUDGET = 2_000_000
DEFAULT_EVALUATION_RUN_WALLCLOCK_LIMIT = 3600  # seconds

# Metrics API
DEFAULT_MAX_HOURLY_SPAN = 31  # days
DEFAULT_DRILLDOWN_PAGE_SIZE = 50
DEFAULT_DRILLDOWN_PAGE_SIZE_MAX = 500
DEFAULT_MAX_METRICS_RANGE = 366  # days

# Voice
DEFAULT_ACCEPTED_AUDIO_FORMATS: list[str] = ["wav", "mp3", "webm"]
# DEVIATION (design F-2): inventory default is 60 s; shipped default is 30 s because the
# Sarvam synchronous REST transcription path maxes at 30 s. Longer audio is refused via
# the Requirement 28.10 error path naming the limit. Configurable back to 60.
DEFAULT_MAX_UTTERANCE_DURATION = 30  # seconds (deviation from inventory 60)
DEFAULT_MAX_AUDIO_UPLOAD_SIZE = 10 * 1024 * 1024  # bytes
DEFAULT_MAX_TRANSCRIPTION_ATTEMPTS = 2
DEFAULT_TRANSCRIPTION_TIMEOUT = 15  # seconds per attempt
DEFAULT_DEFAULT_TRANSCRIPTION_CONFIDENCE = 0.75
DEFAULT_VOICE_CONFIRMATION_THRESHOLD = 0.70
DEFAULT_AUDIO_RETENTION_PERIOD = 0  # seconds
DEFAULT_MAX_SYNTHESIS_CHARACTERS = 2000
DEFAULT_SYNTHESIS_TIMEOUT = 10  # seconds
DEFAULT_MAX_SYNTHESIS_ATTEMPTS = 2
DEFAULT_TURN_SYNTHESIS_TIME_BUDGET = 30  # seconds
DEFAULT_AUDIO_CACHE_RETENTION = 3600  # seconds

# Buddy
DEFAULT_BUDDY_SUGGESTION_LATENCY_BUDGET = 2000  # milliseconds

# Runtime
DEFAULT_SESSION_PAGE_SIZE = 20
DEFAULT_SESSION_PAGE_SIZE_MAX = 100
DEFAULT_COLD_START_BUDGET = 180  # seconds
DEFAULT_VOICE_REACHABILITY_CACHE_PERIOD = 300  # seconds
DEFAULT_MAX_REQUEST_BODY_SIZE = 12 * 1024 * 1024  # bytes

# --- design-added configuration (New configuration introduced by design) --------------
DEFAULT_EMBEDDING_MODEL = "nomic-embed-text"
DEFAULT_EMBEDDING_DIM = 768
DEFAULT_SCHEMA_LINK_KEYWORD_WEIGHT = 0.5
DEFAULT_SCHEMA_LINK_VECTOR_WEIGHT = 0.5
DEFAULT_GROUNDEDNESS_REQUIRE_COMPUTATION_RECORD = False
DEFAULT_ANSWER_COMPOSER_SAMPLE_ROW_COUNT = 5
DEFAULT_REVIEWER_EVIDENCE_SAMPLE_ROWS = 5
DEFAULT_ANOMALY_CALLOUTS_ENABLED = True
DEFAULT_BIND_HOST = "127.0.0.1"
DEFAULT_POSTGRES_READER_USER = "tbx_reader"
DEFAULT_READER_POOL_SIZE = 10

# Sarvam voice group (design-added names)
DEFAULT_SARVAM_STT_MODEL = "saaras:v3"
DEFAULT_SARVAM_STT_MODE = "codemix"
DEFAULT_SARVAM_TTS_MODEL = "bulbul:v3"
DEFAULT_SARVAM_SPEAKER: str | None = None  # provider default
DEFAULT_SARVAM_PACE = 1.0
# DEVIATION (design F-3): pitch is read from config per Requirement 29.3 but omitted
# from the request body when the TTS model is bulbul:v3 (which does not accept it).
DEFAULT_SARVAM_PITCH = 1.0

# General model provider config
DEFAULT_PROVIDERS: tuple[str, ...] = (
    "bedrock",
    "anthropic",
    "openai",
    "gemini",
    "ollama",
    "litellm",
)


class Settings(BaseSettings):
    """Application settings singleton."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Question intake and conversation ---
    reference_date: str | None = Field(default=DEFAULT_REFERENCE_DATE)
    min_fuzzy_match_score: float = Field(default=DEFAULT_MIN_FUZZY_MATCH_SCORE)
    disambiguation_margin: float = Field(default=DEFAULT_DISAMBIGUATION_MARGIN)
    conversation_state_turn_count: int = Field(default=DEFAULT_CONVERSATION_STATE_TURN_COUNT)
    session_context_timeout: int = Field(default=DEFAULT_SESSION_CONTEXT_TIMEOUT)

    # --- Schema KB and metric layer ---
    schema_kb_sample_value_count: int = Field(default=DEFAULT_SCHEMA_KB_SAMPLE_VALUE_COUNT)
    schema_link_prompt_token_budget: int = Field(default=DEFAULT_SCHEMA_LINK_PROMPT_TOKEN_BUDGET)
    min_combined_retrieval_score: float = Field(default=DEFAULT_MIN_COMBINED_RETRIEVAL_SCORE)
    max_join_path_length: int = Field(default=DEFAULT_MAX_JOIN_PATH_LENGTH)
    schema_link_table_recall_target: float = Field(default=DEFAULT_SCHEMA_LINK_TABLE_RECALL_TARGET)
    template_match_threshold: float = Field(default=DEFAULT_TEMPLATE_MATCH_THRESHOLD)
    template_tie_margin: float = Field(default=DEFAULT_TEMPLATE_TIE_MARGIN)

    # --- Dataset ingestion ---
    retained_dataset_version_count: int = Field(default=DEFAULT_RETAINED_DATASET_VERSION_COUNT)
    rejected_row_tolerance: float = Field(default=DEFAULT_REJECTED_ROW_TOLERANCE)
    source_file_encoding: str = Field(default=DEFAULT_SOURCE_FILE_ENCODING)
    api_request_timeout: int = Field(default=DEFAULT_API_REQUEST_TIMEOUT)
    api_ingestion_deadline: int = Field(default=DEFAULT_API_INGESTION_DEADLINE)
    max_pages_per_entity: int = Field(default=DEFAULT_MAX_PAGES_PER_ENTITY)

    # --- Model provider and budgets ---
    model_request_timeout: int = Field(default=DEFAULT_MODEL_REQUEST_TIMEOUT)
    model_parameter_ceiling: int = Field(default=DEFAULT_MODEL_PARAMETER_CEILING)
    max_llm_calls_per_question: int = Field(default=DEFAULT_MAX_LLM_CALLS_PER_QUESTION)
    max_tokens_per_question: int = Field(default=DEFAULT_MAX_TOKENS_PER_QUESTION)
    question_wallclock_deadline: int = Field(default=DEFAULT_QUESTION_WALLCLOCK_DEADLINE)
    metric_layer_call_limit: int = Field(default=DEFAULT_METRIC_LAYER_CALL_LIMIT)
    budget_hard_ceiling_calls: int = Field(default=DEFAULT_BUDGET_HARD_CEILING_CALLS)
    budget_hard_ceiling_tokens: int = Field(default=DEFAULT_BUDGET_HARD_CEILING_TOKENS)
    budget_hard_ceiling_seconds: int = Field(default=DEFAULT_BUDGET_HARD_CEILING_SECONDS)
    target_sql_dialect: str = Field(default=DEFAULT_TARGET_SQL_DIALECT)
    exemplar_count: int = Field(default=DEFAULT_EXEMPLAR_COUNT)
    max_candidates_per_question: int = Field(default=DEFAULT_MAX_CANDIDATES_PER_QUESTION)
    candidate_generation_retry_limit: int = Field(default=DEFAULT_CANDIDATE_GENERATION_RETRY_LIMIT)

    # --- SQL validation and execution ---
    default_row_limit: int = Field(default=DEFAULT_DEFAULT_ROW_LIMIT)
    max_declared_row_limit: int = Field(default=DEFAULT_MAX_DECLARED_ROW_LIMIT)
    statement_timeout: int = Field(default=DEFAULT_STATEMENT_TIMEOUT)
    execution_row_cap: int = Field(default=DEFAULT_EXECUTION_ROW_CAP)
    max_concurrent_queries: int = Field(default=DEFAULT_MAX_CONCURRENT_QUERIES)
    execution_queue_wait_timeout: int = Field(default=DEFAULT_EXECUTION_QUEUE_WAIT_TIMEOUT)
    max_executions_per_turn: int = Field(default=DEFAULT_MAX_EXECUTIONS_PER_TURN)

    # --- Reviewer ---
    repair_iteration_limit: int = Field(default=DEFAULT_REPAIR_ITERATION_LIMIT)
    reviewer_deadline: int = Field(default=DEFAULT_REVIEWER_DEADLINE)
    reviewer_output_retry_limit: int = Field(default=DEFAULT_REVIEWER_OUTPUT_RETRY_LIMIT)
    dry_run_limit_per_turn: int = Field(default=DEFAULT_DRY_RUN_LIMIT_PER_TURN)
    dry_run_deadline: int = Field(default=DEFAULT_DRY_RUN_DEADLINE)
    reviewer_phase_deadline: int = Field(default=DEFAULT_REVIEWER_PHASE_DEADLINE)
    reviewer_evidence_sample_rows: int = Field(default=DEFAULT_REVIEWER_EVIDENCE_SAMPLE_ROWS)

    # --- Computation and answers ---
    display_precision: int = Field(default=DEFAULT_DISPLAY_PRECISION)
    answer_preview_row_limit: int = Field(default=DEFAULT_ANSWER_PREVIEW_ROW_LIMIT)
    max_answer_length: int = Field(default=DEFAULT_MAX_ANSWER_LENGTH)
    max_answer_length_detailed: int = Field(default=DEFAULT_MAX_ANSWER_LENGTH_DETAILED)
    max_drilldown_size: int = Field(default=DEFAULT_MAX_DRILLDOWN_SIZE)
    answer_composer_sample_row_count: int = Field(default=DEFAULT_ANSWER_COMPOSER_SAMPLE_ROW_COUNT)

    # --- Groundedness and abstention ---
    groundedness_match_tolerance: float = Field(default=DEFAULT_GROUNDEDNESS_MATCH_TOLERANCE)
    groundedness_require_computation_record: bool = Field(
        default=DEFAULT_GROUNDEDNESS_REQUIRE_COMPUTATION_RECORD
    )
    clarification_round_limit: int = Field(default=DEFAULT_CLARIFICATION_ROUND_LIMIT)
    unhelpful_refusal_ceiling: float = Field(default=DEFAULT_UNHELPFUL_REFUSAL_CEILING)

    # --- Confidence ---
    confidence_signal_weights: dict[str, float] = Field(
        default_factory=lambda: dict(DEFAULT_CONFIDENCE_SIGNAL_WEIGHTS)
    )
    confidence_band_boundaries: dict[str, float] = Field(
        default_factory=lambda: dict(DEFAULT_CONFIDENCE_BAND_BOUNDARIES)
    )
    acceptance_threshold: float = Field(default=DEFAULT_ACCEPTANCE_THRESHOLD)
    calibration_min_band_size: int = Field(default=DEFAULT_CALIBRATION_MIN_BAND_SIZE)
    band_min_accuracy: dict[str, float] = Field(
        default_factory=lambda: dict(DEFAULT_BAND_MIN_ACCURACY)
    )

    # --- Anomaly ---
    anomaly_z_threshold: float = Field(default=DEFAULT_ANOMALY_Z_THRESHOLD)
    anomaly_min_history_count: int = Field(default=DEFAULT_ANOMALY_MIN_HISTORY_COUNT)
    anomaly_max_entities_per_turn: int = Field(default=DEFAULT_ANOMALY_MAX_ENTITIES_PER_TURN)
    anomaly_history_window: int = Field(default=DEFAULT_ANOMALY_HISTORY_WINDOW)
    anomaly_max_history_rows: int = Field(default=DEFAULT_ANOMALY_MAX_HISTORY_ROWS)
    zero_dispersion_relative_threshold: float = Field(
        default=DEFAULT_ZERO_DISPERSION_RELATIVE_THRESHOLD
    )
    zero_dispersion_absolute_floor: Decimal = Field(default=DEFAULT_ZERO_DISPERSION_ABSOLUTE_FLOOR)
    anomaly_evaluation_reserve: int = Field(default=DEFAULT_ANOMALY_EVALUATION_RESERVE)
    anomaly_evaluation_time_limit: int = Field(default=DEFAULT_ANOMALY_EVALUATION_TIME_LIMIT)
    anomaly_callouts_enabled: bool = Field(default=DEFAULT_ANOMALY_CALLOUTS_ENABLED)

    # --- Trace ---
    trace_replay_retention: int = Field(default=DEFAULT_TRACE_REPLAY_RETENTION)
    trace_keepalive_interval: int = Field(default=DEFAULT_TRACE_KEEPALIVE_INTERVAL)
    max_trace_event_size: int = Field(default=DEFAULT_MAX_TRACE_EVENT_SIZE)
    max_inline_sample_rows: int = Field(default=DEFAULT_MAX_INLINE_SAMPLE_ROWS)
    trace_persistence_window: int = Field(default=DEFAULT_TRACE_PERSISTENCE_WINDOW)
    trace_summary_page_size: int = Field(default=DEFAULT_TRACE_SUMMARY_PAGE_SIZE)
    trace_summary_page_size_max: int = Field(default=DEFAULT_TRACE_SUMMARY_PAGE_SIZE_MAX)
    trace_retention_period: int = Field(default=DEFAULT_TRACE_RETENTION_PERIOD)
    turn_abandonment_window: int = Field(default=DEFAULT_TURN_ABANDONMENT_WINDOW)
    max_persisted_field_length: int = Field(default=DEFAULT_MAX_PERSISTED_FIELD_LENGTH)
    trace_buffer_max_events: int = Field(default=DEFAULT_TRACE_BUFFER_MAX_EVENTS)

    # --- Export ---
    result_snapshot_retention: int = Field(default=DEFAULT_RESULT_SNAPSHOT_RETENTION)
    max_export_rows: int = Field(default=DEFAULT_MAX_EXPORT_ROWS)
    export_deadline: int = Field(default=DEFAULT_EXPORT_DEADLINE)

    # --- Failure store and improvement ---
    failure_case_row_count: int = Field(default=DEFAULT_FAILURE_CASE_ROW_COUNT)
    max_failure_cases: int = Field(default=DEFAULT_MAX_FAILURE_CASES)
    max_proposals_per_run: int = Field(default=DEFAULT_MAX_PROPOSALS_PER_RUN)
    improvement_evaluation_timeout: int = Field(default=DEFAULT_IMPROVEMENT_EVALUATION_TIMEOUT)
    artefact_version_retention_count: int = Field(default=DEFAULT_ARTEFACT_VERSION_RETENTION_COUNT)

    # --- Evaluation ---
    evaluation_repeat_count: int = Field(default=DEFAULT_EVALUATION_REPEAT_COUNT)
    evaluation_run_token_budget: int = Field(default=DEFAULT_EVALUATION_RUN_TOKEN_BUDGET)
    evaluation_run_wallclock_limit: int = Field(default=DEFAULT_EVALUATION_RUN_WALLCLOCK_LIMIT)

    # --- Metrics API ---
    max_hourly_span: int = Field(default=DEFAULT_MAX_HOURLY_SPAN)
    drilldown_page_size: int = Field(default=DEFAULT_DRILLDOWN_PAGE_SIZE)
    drilldown_page_size_max: int = Field(default=DEFAULT_DRILLDOWN_PAGE_SIZE_MAX)
    max_metrics_range: int = Field(default=DEFAULT_MAX_METRICS_RANGE)

    # --- Voice ---
    accepted_audio_formats: list[str] = Field(
        default_factory=lambda: list(DEFAULT_ACCEPTED_AUDIO_FORMATS)
    )
    max_utterance_duration: int = Field(default=DEFAULT_MAX_UTTERANCE_DURATION)
    max_audio_upload_size: int = Field(default=DEFAULT_MAX_AUDIO_UPLOAD_SIZE)
    max_transcription_attempts: int = Field(default=DEFAULT_MAX_TRANSCRIPTION_ATTEMPTS)
    transcription_timeout: int = Field(default=DEFAULT_TRANSCRIPTION_TIMEOUT)
    default_transcription_confidence: float = Field(
        default=DEFAULT_DEFAULT_TRANSCRIPTION_CONFIDENCE
    )
    voice_confirmation_threshold: float = Field(default=DEFAULT_VOICE_CONFIRMATION_THRESHOLD)
    audio_retention_period: int = Field(default=DEFAULT_AUDIO_RETENTION_PERIOD)
    max_synthesis_characters: int = Field(default=DEFAULT_MAX_SYNTHESIS_CHARACTERS)
    synthesis_timeout: int = Field(default=DEFAULT_SYNTHESIS_TIMEOUT)
    max_synthesis_attempts: int = Field(default=DEFAULT_MAX_SYNTHESIS_ATTEMPTS)
    turn_synthesis_time_budget: int = Field(default=DEFAULT_TURN_SYNTHESIS_TIME_BUDGET)
    audio_cache_retention: int = Field(default=DEFAULT_AUDIO_CACHE_RETENTION)

    # --- Sarvam voice provider group (design-added) ---
    sarvam_stt_model: str = Field(default=DEFAULT_SARVAM_STT_MODEL)
    sarvam_stt_mode: str = Field(default=DEFAULT_SARVAM_STT_MODE)
    sarvam_tts_model: str = Field(default=DEFAULT_SARVAM_TTS_MODEL)
    sarvam_speaker: str | None = Field(default=DEFAULT_SARVAM_SPEAKER)
    sarvam_pace: float = Field(default=DEFAULT_SARVAM_PACE)
    sarvam_pitch: float = Field(default=DEFAULT_SARVAM_PITCH)
    sarvam_api_key: str | None = Field(default=None)

    # --- Buddy ---
    buddy_suggestion_latency_budget: int = Field(default=DEFAULT_BUDDY_SUGGESTION_LATENCY_BUDGET)

    # --- Runtime ---
    session_page_size: int = Field(default=DEFAULT_SESSION_PAGE_SIZE)
    session_page_size_max: int = Field(default=DEFAULT_SESSION_PAGE_SIZE_MAX)
    cold_start_budget: int = Field(default=DEFAULT_COLD_START_BUDGET)
    voice_reachability_cache_period: int = Field(default=DEFAULT_VOICE_REACHABILITY_CACHE_PERIOD)
    max_request_body_size: int = Field(default=DEFAULT_MAX_REQUEST_BODY_SIZE)
    bind_host: str = Field(default=DEFAULT_BIND_HOST)
    internal_api_token: str | None = Field(default=None)

    # --- Embedding / schema link (design-added) ---
    embedding_model: str = Field(default=DEFAULT_EMBEDDING_MODEL)
    embedding_dim: int = Field(default=DEFAULT_EMBEDDING_DIM)
    schema_link_keyword_weight: float = Field(default=DEFAULT_SCHEMA_LINK_KEYWORD_WEIGHT)
    schema_link_vector_weight: float = Field(default=DEFAULT_SCHEMA_LINK_VECTOR_WEIGHT)

    # --- Database ---
    postgres_dsn: str = Field(
        default="postgresql+asyncpg://tbx_app:tbx_app@localhost:5432/tbx"
    )
    postgres_reader_user: str = Field(default=DEFAULT_POSTGRES_READER_USER)
    postgres_reader_password: str | None = Field(default=None)
    postgres_reader_dsn: str | None = Field(default=None)
    reader_pool_size: int = Field(default=DEFAULT_READER_POOL_SIZE)

    # --- Model routing (design-added) ---
    model_prices: dict[str, Any] = Field(default_factory=dict)
    role_prompt_versions: dict[str, str] = Field(default_factory=dict)

    # ----------------------------------------------------------------------------------
    # Blank-environment-variable coercion: a set-but-empty variable falls back to the
    # field default rather than failing startup.
    # ----------------------------------------------------------------------------------
    @field_validator("*", mode="before")
    @classmethod
    def _blank_to_default(cls, value: Any, info: Any) -> Any:
        if isinstance(value, str) and value.strip() == "":
            field = cls.model_fields.get(info.field_name)
            if field is None:
                return value
            if field.default is not None and field.default is not ...:
                return field.default
            if field.default_factory is not None:  # type: ignore[truthy-function]
                return field.default_factory()  # type: ignore[misc]
            return None
        return value

    @property
    def is_seed_dataset(self) -> bool:
        """Placeholder; real provenance is resolved from the active dataset row."""
        return True


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings singleton."""
    return Settings()
