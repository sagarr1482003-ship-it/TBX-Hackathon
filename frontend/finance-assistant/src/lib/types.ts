export interface Vendor {
  id: string
  name: string
  category: string
}

export interface Account {
  code: string
  name: string
}

export type ReconciliationStatus = 'reconciled' | 'unreconciled'

export interface Transaction {
  id: string
  date: string // YYYY-MM-DD
  vendorId: string
  accountCode: string
  description: string
  amount: number // negative = outflow, in USD
  status: ReconciliationStatus
  isPayout: boolean
}

export type TraceKind = 'parse' | 'filter' | 'compute' | 'flag' | 'guardrail'

/** One expandable detail row inside a trace step. */
export interface TraceDetail {
  label: string
  value: string
  /** Controls rendering: `sql` and `json` render in a mono pre block. */
  format?: 'text' | 'sql' | 'json'
}

/** Tabular payload for a trace step (e.g. the executed result rows). */
export interface TraceTable {
  columns: string[]
  rows: Array<Record<string, unknown>>
  /** True total from the DB when `rows` is only a preview. */
  totalRowCount?: number
}

export interface TraceStep {
  kind: TraceKind
  label: string
  /** Expandable key/value detail for this stage. */
  details?: TraceDetail[]
  /** Expandable tabular data for this stage. */
  table?: TraceTable
  /** Client-measured stage elapsed time (the stream carries no per-stage timing). */
  durationMs?: number
}

export interface ChartSeries {
  name: string
  data: number[]
  kind?: 'bar' | 'line' | 'area'       // per-series override for combo charts
  style?: 'solid' | 'dashed'           // line style
  axis?: 'left' | 'right'              // dual-axis support
}

export interface ChartData {
  kind: 'bar' | 'line' | 'area' | 'pie' | 'doughnut' | 'combo'
  labels: string[]
  series: ChartSeries[]
  xLabel?: string
  yLabel?: string
  y2Label?: string                      // right-axis title for combo/dual-axis
}

export interface QueryResult {
  id: string
  answer: string
  confidence: 'high' | 'medium' | 'low'
  confidenceNote: string
  filters: { label: string; value: string }[]
  steps: TraceStep[]
  records: Transaction[]
  totalLabel?: string
  totalValue?: number
  groupBy?: { label: string; value: number; count: number }[]
  anomaly?: { text: string; transactionId: string }
  chart?: ChartData
  sourceRef: string
  noData?: boolean
}

export type Turn = { id: string; role: 'user'; text: string } | { id: string; role: 'assistant'; result: QueryResult }

export interface QueryContext {
  vendorId?: string
  accountCode?: string
  status?: ReconciliationStatus
  year?: number
  month?: number
}

export interface ChatSession {
  id: string
  title: string
  createdAt: number
  turns: Turn[]
  context: QueryContext
  activeResultId?: string
}

// =============================================================================
// Backend API contract types (from docs/api.md)
// Monetary values are STRINGS — never parse to number.
// =============================================================================

export type Surface = 'finance' | 'insights'

export type TurnOutcome = 'answered' | 'clarification_requested' | 'abstained' | 'failed'

export type ResolutionPath = 'metric_layer' | 'generated_sql'

export type ConfidenceBand = 'high' | 'medium' | 'low'

export type ValueType = 'monetary' | 'count' | 'percentage' | 'date' | 'text'

export type TurnOrigin = 'text' | 'voice'

export type AbstentionReason =
  | 'data_absent'
  | 'intent_unsupported'
  | 'ambiguous_entity'
  | 'ambiguous_metric'
  | 'ambiguous_date_range'
  | 'ambiguous_grouping'
  | 'reference_unresolved'
  | 'clarification_exhausted'
  | 'confidence_below_threshold'
  | 'period_outside_coverage'
  | 'entity_not_found'
  | 'repair_limit_reached'
  | 'budget_exhausted'
  | 'provider_unavailable'
  | 'schema_linking_failed'
  | 'generation_failed'
  | 'reviewer_unavailable'
  | 'dataset_version_changed'
  | 'metric_execution_failed'
  | 'term_undefined'
  | 'embedding_dimension_mismatch'

export type StageName =
  | 'intake'
  | 'context_resolution'
  | 'intent_classification'
  | 'entity_resolution'
  | 'metric_routing'
  | 'schema_retrieval'
  | 'schema_linking'
  | 'exemplar_retrieval'
  | 'sql_generation'
  | 'static_validation'
  | 'plan_inspection'
  | 'reviewer_verdict'
  | 'repair_iteration'
  | 'execution'
  | 'computation'
  | 'anomaly_check'
  | 'answer_composition'
  | 'groundedness_check'
  | 'confidence_scoring'
  | 'completion'

export type StageStatus = 'ok' | 'error' | 'skipped' | 'completed' | 'abstained' | 'failed'

// --- Request ---

export interface TurnRequest {
  question: string
  detailed?: boolean
  language_code?: string
}

// --- Main response ---

export interface TurnResponse {
  turn_id: string
  session_id: string
  outcome: TurnOutcome
  answer_text: string | null
  resolved_question: string | null
  resolved_date_range: [string, string] | null
  executed_sql: string | null
  applied_filters: AppliedFilter[]
  excluded_record_count: number | null
  metric_name: string | null
  resolution_path: ResolutionPath | null
  breakdown_columns: BreakdownColumn[]
  breakdown_preview: Array<Record<string, unknown>>
  total_row_count: number | null
  computation_records: ComputationRecord[]
  figure_provenance: FigureProvenance[]
  anomaly_callouts: AnomalyCallout[]
  confidence_score: number | null
  confidence_band: ConfidenceBand | null
  confidence_signals: ConfidenceSignal[]
  caution: string | null
  abstention_reason_code: AbstentionReason | null
  clarifying_question: ClarifyingQuestion | null
  transcript: VoiceTranscript | null
  synthetic_data: boolean
  dataset_version: number
  schema_kb_version: number
}

// --- Provenance and figures ---

export interface ComputationRecord {
  id: string
  label: string
  /** DECIMAL STRING. null when withheld. */
  value: string | null
  unrounded_value: string | null
  unit: string | null
  currency: string | null
  source_column: string | null
  query_id: string
  aggregated_row_count: number
  null_excluded_row_count: number
  undefined_reason: 'zero_denominator' | 'zero_or_negative_base' | 'zero_row_aggregate' | 'mixed_currency' | null
  /** Values are DECIMAL STRINGS. */
  operands: Record<string, string> | null
}

export interface BreakdownColumn {
  label: string
  value_type: ValueType
  currency: string | null
}

export interface AppliedFilter {
  dimension: string
  expression: string
  excluded_record_count: number | null
}

export interface FigureProvenance {
  computation_record_id: string
  source_record_count: number
  source_record_ids: string[]
  truncated: boolean
}

export interface ConfidenceSignal {
  name: string
  applicable: boolean
  normalised_value: number | null
  weight: number
  weighted_contribution: number | null
}

export interface AnomalyCallout {
  entity: string
  /** DECIMAL STRING */
  value: string
  /** DECIMAL STRING */
  median: string
  kind: 'modified_z' | 'zero_dispersion'
  z: number | null
  relative: number | null
}

export interface ClarifyingQuestion {
  question: string
  options?: string[]
  ambiguity?: string
}

export interface VoiceTranscript {
  text: string
  language_code: string | null
  confidence: number
}

// --- Trace ---

export interface ModelCallRecord {
  role: string
  provider: string
  model_id: string
  input_tokens: number | null
  output_tokens: number | null
  tokens_estimated: boolean
  duration_ms: number
  outcome: string
}

export interface TraceEvent {
  turn_id: string
  sequence: number
  stage: StageName
  stage_attempt: number
  status: StageStatus
  skip_reason: string | null
  started_at: string
  duration_ms: number
  input_summary: Record<string, unknown>
  output_summary: Record<string, unknown>
  truncated: boolean
  untruncated_row_count: number | null
  untruncated_char_count: number | null
  model_call: ModelCallRecord | null
  error_type: string | null
  error_message: string | null
}

// --- Sessions ---

export interface SessionCreated {
  session_id: string
  surface: Surface
  starter_questions: string[]
  dataset_version: number
  synthetic_data: boolean
}

export interface SessionSummary {
  session_id: string
  surface: Surface
  created_at: string
  last_turn_at: string | null
  turn_count: number
}

export interface Page<T> {
  items: T[]
  total_count?: number
  cursor?: string | null
}

// --- Health ---

export interface HealthPayload {
  status: string
  ready: boolean
  database: string
  dataset_version: number
  schema_kb_version: number
  synthetic_data: boolean
}

// =============================================================================
// REAL backend response (simple_pipeline). Differs from the docs/api.md
// TurnResponse above — this is what the running agent actually returns.
// =============================================================================
export interface AgentChartPoint { label: string; value: number }
export interface AgentChart {
  type: 'pie' | 'bar' | 'line' | 'doughnut'
  label_field: string
  value_field: string
  points: AgentChartPoint[]
}
export interface AgentVerdict { verdict: 'approve' | 'repair' | 'reject'; reason: string }
export interface AgentBreakdown {
  columns: string[] | null
  rows: Array<Record<string, unknown>> | null
  total_row_count: number | null
}
export interface AgentTraceStage { stage: string; duration_ms: number }
export interface AgentTurnResponse {
  question: string
  outcome: string
  resolved_sql: string | null
  answer_text: string | null
  answer_source: 'llm' | 'template' | 'template_fallback' | null
  chart: AgentChart | null
  verdict: AgentVerdict | null
  breakdown: AgentBreakdown | null
  validation_ok: boolean
  validation_reason: string | null
  total_ms: number
  trace: AgentTraceStage[]
}

// =============================================================================
// REAL backend SSE contract — POST /api/chat/stream (app/routes/chat.py).
// This is what the running pipeline emits. Distinct from the aspirational
// docs/api.md TurnResponse types above.
// =============================================================================

export type AgentOutcome =
  | 'answered' | 'clarification_requested' | 'generation_failed'
  | 'validation_rejected' | 'review_failed' | 'approve' | 'repair' | 'reject'

/** The terminal `completion` SSE payload. Always emitted, including error paths. */
export interface AgentCompletion {
  question: string
  outcome: AgentOutcome | string
  clarification: string | null
  resolved_sql: string | null
  answer_text: string | null
  answer_source: 'llm' | 'template' | 'template_fallback' | null
  chart: AgentChart | null
  verdict: AgentVerdict | null
  breakdown: AgentBreakdown | null
  validation_ok: boolean
  validation_reason: string | null
  total_ms: number
}

export type AgentStageName =
  | 'intake' | 'sql_generation' | 'clarification' | 'static_validation'
  | 'reviewer_verdict' | 'execution' | 'answer_composition' | 'completion'

/** One decoded SSE frame. */
export interface AgentStreamEvent {
  event: AgentStageName | string
  data: Record<string, unknown>
  /** Client-side receipt time (ms epoch), stamped on arrival. Used for stage timing. */
  receivedAt?: number
}
