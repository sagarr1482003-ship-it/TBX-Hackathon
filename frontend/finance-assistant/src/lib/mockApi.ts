/**
 * Mock API — static fixtures matching exact BE response shapes from docs/api.md.
 *
 * Monetary values are STRINGS (never numbers). Fixtures cover all 4 outcomes.
 * Simulates network latency with configurable delays.
 */

import type {
  SessionCreated,
  TurnResponse,
  TraceEvent,
  Page,
  SessionSummary,
  HealthPayload,
  StageName,
  StageStatus,
} from './types'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function delay<T>(value: T, ms = 800 + Math.random() * 1200): Promise<T> {
  return new Promise((resolve) => setTimeout(() => resolve(value), ms))
}

function uuid(): string {
  return crypto.randomUUID?.() ?? `${Date.now()}-${Math.floor(Math.random() * 100000)}`
}

// ---------------------------------------------------------------------------
// Fixture: Answered turn (happy path)
// ---------------------------------------------------------------------------

export function getAnsweredTurn(sid?: string, question?: string): TurnResponse {
  const turnId = uuid()
  const sessionId = sid ?? uuid()
  return {
    turn_id: turnId,
    session_id: sessionId,
    outcome: 'answered',
    answer_text: `Credit transactions totalled ₹14,823,150.00 between 1 June 2024 and 30 June 2024 across 42 credits [c1]. The largest share went to HDFC Bank Limited accounts at ₹5,812,400.00 [c2].`,
    resolved_question: question ?? 'What was the total volume of credit transactions between 2024-06-01 and 2024-06-30?',
    resolved_date_range: ['2024-06-01', '2024-06-30'],
    executed_sql: `SELECT b.bank_name, SUM(t.transaction_amount) AS total_credits\nFROM finance.transaction t\nJOIN finance.account a ON t.account_id = a.account_id\nJOIN finance.bank b ON a.bank_code = b.bank_code\nWHERE t.transaction_type = 'credit'\n  AND t.transaction_date >= '2024-06-01'\n  AND t.transaction_date <= '2024-06-30'\nGROUP BY b.bank_name\nORDER BY total_credits DESC`,
    applied_filters: [
      { dimension: 'transaction_date', expression: '2024-06-01 to 2024-06-30 inclusive', excluded_record_count: null },
      { dimension: 'transaction_type', expression: "='credit'", excluded_record_count: null },
    ],
    excluded_record_count: null,
    metric_name: 'total_credit_volume',
    resolution_path: 'metric_layer',
    breakdown_columns: [
      { label: 'bank_name', value_type: 'text', currency: null },
      { label: 'total_credits', value_type: 'monetary', currency: 'INR' },
    ],
    breakdown_preview: [
      { bank_name: 'HDFC BANK LIMITED', total_credits: '5812400.00' },
      { bank_name: 'ICICI BANK LIMITED', total_credits: '4654210.50' },
      { bank_name: 'STATE BANK OF INDIA', total_credits: '2498375.00' },
      { bank_name: 'AXIS BANK', total_credits: '1423190.75' },
      { bank_name: 'KOTAK MAHINDRA BANK', total_credits: '434973.75' },
    ],
    total_row_count: 38,
    computation_records: [
      {
        id: 'c1',
        label: 'Total credit volume',
        value: '14823150.00',
        unrounded_value: '14823150.000000',
        unit: null,
        currency: 'INR',
        source_column: 'transaction.transaction_amount',
        query_id: 'q1',
        aggregated_row_count: 42,
        null_excluded_row_count: 0,
        undefined_reason: null,
        operands: null,
      },
      {
        id: 'c2',
        label: 'Largest bank credit total',
        value: '5812400.00',
        unrounded_value: '5812400.000000',
        unit: null,
        currency: 'INR',
        source_column: 'transaction.transaction_amount',
        query_id: 'q1',
        aggregated_row_count: 12,
        null_excluded_row_count: 0,
        undefined_reason: null,
        operands: null,
      },
    ],
    figure_provenance: [
      { computation_record_id: 'c1', source_record_count: 42, source_record_ids: ['a275e0eb', '392ba871'], truncated: true },
      { computation_record_id: 'c2', source_record_count: 12, source_record_ids: ['f312c90a'], truncated: false },
    ],
    anomaly_callouts: [],
    confidence_score: 0.86,
    confidence_band: 'high',
    confidence_signals: [
      { name: 'reviewer_verdict', applicable: true, normalised_value: 1.0, weight: 0.35, weighted_contribution: 0.35 },
      { name: 'groundedness', applicable: true, normalised_value: 1.0, weight: 0.30, weighted_contribution: 0.30 },
      { name: 'candidate_agreement', applicable: false, normalised_value: null, weight: 0.0, weighted_contribution: null },
      { name: 'retrieval_score', applicable: true, normalised_value: 0.62, weight: 0.20, weighted_contribution: 0.124 },
      { name: 'repair_free', applicable: true, normalised_value: 1.0, weight: 0.15, weighted_contribution: 0.15 },
    ],
    caution: null,
    abstention_reason_code: null,
    clarifying_question: null,
    transcript: null,
    synthetic_data: true,
    dataset_version: 1,
    schema_kb_version: 1,
  }
}

// ---------------------------------------------------------------------------
// Fixture: Abstained turn
// ---------------------------------------------------------------------------

function getAbstainedTurn(sid: string, question: string): TurnResponse {
  return {
    turn_id: uuid(),
    session_id: sid,
    outcome: 'abstained',
    answer_text: "I don't have data for 2019. This dataset covers 1 January 2023 to 31 December 2024.",
    resolved_question: question,
    resolved_date_range: null,
    executed_sql: null,
    applied_filters: [],
    excluded_record_count: null,
    metric_name: null,
    resolution_path: null,
    breakdown_columns: [],
    breakdown_preview: [],
    total_row_count: null,
    computation_records: [],
    figure_provenance: [],
    anomaly_callouts: [],
    confidence_score: null,
    confidence_band: null,
    confidence_signals: [],
    caution: null,
    abstention_reason_code: 'period_outside_coverage',
    clarifying_question: null,
    transcript: null,
    synthetic_data: true,
    dataset_version: 1,
    schema_kb_version: 1,
  }
}

// ---------------------------------------------------------------------------
// Fixture: Clarification requested
// ---------------------------------------------------------------------------

function getClarificationTurn(sid: string): TurnResponse {
  return {
    turn_id: uuid(),
    session_id: sid,
    outcome: 'clarification_requested',
    answer_text: null,
    resolved_question: null,
    resolved_date_range: null,
    executed_sql: null,
    applied_filters: [],
    excluded_record_count: null,
    metric_name: null,
    resolution_path: null,
    breakdown_columns: [],
    breakdown_preview: [],
    total_row_count: null,
    computation_records: [],
    figure_provenance: [],
    anomaly_callouts: [],
    confidence_score: null,
    confidence_band: null,
    confidence_signals: [],
    caution: null,
    abstention_reason_code: null,
    clarifying_question: {
      question: 'Which bank did you mean — HDFC BANK LIMITED or HDFC SECURITIES?',
      options: ['HDFC BANK LIMITED', 'HDFC SECURITIES'],
      ambiguity: 'entity',
    },
    transcript: null,
    synthetic_data: true,
    dataset_version: 1,
    schema_kb_version: 1,
  }
}

// ---------------------------------------------------------------------------
// Fixture: Answered with anomaly + medium confidence
// ---------------------------------------------------------------------------

function getAnomalyTurn(sid: string, question: string): TurnResponse {
  const base = getAnsweredTurn(sid, question)
  return {
    ...base,
    confidence_score: 0.72,
    confidence_band: 'medium',
    caution: 'Retrieval score was the weakest applicable signal.',
    anomaly_callouts: [
      {
        entity: 'IMPS/P2A/.../GAUTAM SINGH',
        value: '342100.50',
        median: '8400.00',
        kind: 'modified_z',
        z: 4.1,
        relative: null,
      },
    ],
  }
}

// ---------------------------------------------------------------------------
// Route mock questions to the appropriate fixture
// ---------------------------------------------------------------------------

const ABSTAIN_PATTERNS = /(2019|2020|salary|payroll|headcount|tax|forecast|prediction|valuation|stock price)/i
const CLARIFY_PATTERNS = /(hdfc|icici|which bank|which account)/i
const ANOMALY_PATTERNS = /(unusual|anomaly|anomalies|outlier|spike|flag)/i

export async function submitTurn(sessionId: string, question: string): Promise<TurnResponse> {
  if (ABSTAIN_PATTERNS.test(question)) {
    return delay(getAbstainedTurn(sessionId, question))
  }
  if (CLARIFY_PATTERNS.test(question)) {
    return delay(getClarificationTurn(sessionId))
  }
  if (ANOMALY_PATTERNS.test(question)) {
    return delay(getAnomalyTurn(sessionId, question))
  }
  return delay(getAnsweredTurn(sessionId, question))
}

// ---------------------------------------------------------------------------
// Session mocks
// ---------------------------------------------------------------------------

export async function createSession(_surface?: string): Promise<SessionCreated> {
  return delay({
    session_id: uuid(),
    surface: 'finance' as const,
    starter_questions: [
      'What was the total volume of credit transactions last month?',
      'Which account has the highest available balance?',
      'How many IMPS transactions were recorded?',
      'What was our total debit amount by bank last month?',
    ],
    dataset_version: 1,
    synthetic_data: true,
  }, 300)
}

export async function listSessions(): Promise<Page<SessionSummary>> {
  return delay({ items: [], cursor: null }, 200)
}

// ---------------------------------------------------------------------------
// Buddy mocks
// ---------------------------------------------------------------------------

export async function getStarterQuestions(): Promise<string[]> {
  return delay([
    'What was the total volume of credit transactions last month?',
    'Which account has the highest available balance?',
    'How many IMPS transactions were recorded?',
    'What was our total debit amount by bank last month?',
  ], 300)
}

export async function getNextQuestions(): Promise<string[]> {
  return delay([
    'How does that compare to the previous month?',
    'Which vendor had the largest increase?',
    'Are there any anomalies in this data?',
  ], 400)
}

// ---------------------------------------------------------------------------
// Trace stream mock — replays a recorded sequence with small delays
// ---------------------------------------------------------------------------

const PIPELINE_STAGES: Array<{ stage: StageName; status: StageStatus; skip_reason: string | null; duration_ms: number }> = [
  { stage: 'intake', status: 'ok', skip_reason: null, duration_ms: 5 },
  { stage: 'context_resolution', status: 'ok', skip_reason: null, duration_ms: 18 },
  { stage: 'intent_classification', status: 'ok', skip_reason: null, duration_ms: 45 },
  { stage: 'entity_resolution', status: 'ok', skip_reason: null, duration_ms: 32 },
  { stage: 'metric_routing', status: 'ok', skip_reason: null, duration_ms: 12 },
  { stage: 'schema_retrieval', status: 'skipped', skip_reason: 'metric_layer_path', duration_ms: 0 },
  { stage: 'schema_linking', status: 'skipped', skip_reason: 'metric_layer_path', duration_ms: 0 },
  { stage: 'exemplar_retrieval', status: 'skipped', skip_reason: 'metric_layer_path', duration_ms: 0 },
  { stage: 'sql_generation', status: 'skipped', skip_reason: 'metric_layer_path', duration_ms: 0 },
  { stage: 'static_validation', status: 'ok', skip_reason: null, duration_ms: 8 },
  { stage: 'plan_inspection', status: 'ok', skip_reason: null, duration_ms: 15 },
  { stage: 'reviewer_verdict', status: 'ok', skip_reason: null, duration_ms: 320 },
  { stage: 'execution', status: 'ok', skip_reason: null, duration_ms: 84 },
  { stage: 'computation', status: 'ok', skip_reason: null, duration_ms: 6 },
  { stage: 'anomaly_check', status: 'ok', skip_reason: null, duration_ms: 22 },
  { stage: 'answer_composition', status: 'ok', skip_reason: null, duration_ms: 180 },
  { stage: 'groundedness_check', status: 'ok', skip_reason: null, duration_ms: 35 },
  { stage: 'confidence_scoring', status: 'ok', skip_reason: null, duration_ms: 4 },
  { stage: 'completion', status: 'completed', skip_reason: null, duration_ms: 2 },
]

export function openTraceStream(
  onEvent: (event: TraceEvent) => void,
  onDone?: () => void,
): { close: () => void } {
  const turnId = uuid()
  let cancelled = false
  let seq = 1

  const baseTime = new Date().toISOString()

  function emitNext(index: number) {
    if (cancelled || index >= PIPELINE_STAGES.length) {
      onDone?.()
      return
    }
    const s = PIPELINE_STAGES[index]
    const event: TraceEvent = {
      turn_id: turnId,
      sequence: seq++,
      stage: s.stage,
      stage_attempt: 1,
      status: s.status,
      skip_reason: s.skip_reason,
      started_at: baseTime,
      duration_ms: s.duration_ms,
      input_summary: {},
      output_summary: s.stage === 'metric_routing' ? { metric: 'total_credit_volume', score: 0.91 } : {},
      truncated: false,
      untruncated_row_count: null,
      untruncated_char_count: null,
      model_call: null,
      error_type: null,
      error_message: null,
    }
    onEvent(event)

    // Small delays between stages, skipped stages arrive instantly
    const nextDelay = s.status === 'skipped' ? 30 : 80 + Math.random() * 120
    setTimeout(() => emitNext(index + 1), nextDelay)
  }

  setTimeout(() => emitNext(0), 200)

  return { close: () => { cancelled = true } }
}

// ---------------------------------------------------------------------------
// Health mock
// ---------------------------------------------------------------------------

export async function checkHealth(): Promise<HealthPayload> {
  return delay({
    status: 'healthy',
    ready: true,
    database: 'connected',
    dataset_version: 1,
    schema_kb_version: 1,
    synthetic_data: true,
  }, 200)
}
