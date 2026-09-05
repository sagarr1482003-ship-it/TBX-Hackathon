/**
 * Adapter: maps backend TurnResponse → frontend QueryResult.
 *
 * This lets existing components (MessageBubble, EvidencePanel, etc.) work
 * with BE data without rewriting them. The adapter is a transitional layer —
 * eventually components should consume TurnResponse directly.
 *
 * Monetary values: the BE sends decimal strings. For the existing FE
 * components that expect `number`, we parse them here. New components
 * should work with strings directly.
 */

import type {
  QueryResult,
  TurnResponse,
  TraceStep,
  TraceKind,
  TraceDetail,
  TraceTable,
  ChartData,
  TraceEvent,
  AgentTurnResponse,
  AgentChart,
  AgentCompletion,
  AgentStreamEvent,
} from './types'

// ---------------------------------------------------------------------------
// Monetary formatting — respects the BE's currency field
// ---------------------------------------------------------------------------

function formatMoney(value: string | null, currency?: string | null): string {
  if (value === null) return '—'
  const num = parseFloat(value)
  if (isNaN(num)) return value
  const symbol = currency === 'INR' ? '₹' : currency === 'USD' ? '$' : (currency ?? '')
  const formatted = Math.abs(num).toLocaleString('en-IN', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })
  return `${num < 0 ? '-' : ''}${symbol}${formatted}`
}

// ---------------------------------------------------------------------------
// Map TraceEvents → legacy TraceSteps
// ---------------------------------------------------------------------------

const STAGE_TO_KIND: Record<string, TraceKind> = {
  intake: 'parse',
  context_resolution: 'parse',
  intent_classification: 'parse',
  entity_resolution: 'parse',
  metric_routing: 'parse',
  schema_retrieval: 'filter',
  schema_linking: 'filter',
  exemplar_retrieval: 'filter',
  sql_generation: 'compute',
  static_validation: 'guardrail',
  plan_inspection: 'compute',
  reviewer_verdict: 'guardrail',
  repair_iteration: 'compute',
  execution: 'compute',
  computation: 'compute',
  anomaly_check: 'flag',
  answer_composition: 'compute',
  groundedness_check: 'guardrail',
  confidence_scoring: 'compute',
  completion: 'compute',
}

const STAGE_LABELS: Record<string, string> = {
  intake: 'Received question',
  context_resolution: 'Resolved context and references',
  intent_classification: 'Classified intent',
  entity_resolution: 'Resolved entities',
  metric_routing: 'Checked metric layer',
  schema_retrieval: 'Retrieved schema',
  schema_linking: 'Linked to schema',
  exemplar_retrieval: 'Retrieved examples',
  sql_generation: 'Generated SQL',
  static_validation: 'Validated SQL',
  plan_inspection: 'Inspected query plan',
  reviewer_verdict: 'Reviewer approved',
  repair_iteration: 'Repaired query',
  execution: 'Executed query',
  computation: 'Computed figures',
  anomaly_check: 'Checked for anomalies',
  answer_composition: 'Composed answer',
  groundedness_check: 'Verified groundedness',
  confidence_scoring: 'Scored confidence',
  completion: 'Pipeline complete',
}

export function traceEventsToSteps(events: TraceEvent[]): TraceStep[] {
  return events
    .filter((e) => e.stage !== 'completion' && e.status !== 'skipped')
    .map((e) => ({
      kind: STAGE_TO_KIND[e.stage] ?? 'compute',
      label: e.status === 'error'
        ? `${STAGE_LABELS[e.stage] ?? e.stage} — failed: ${e.error_message ?? 'unknown error'}`
        : STAGE_LABELS[e.stage] ?? e.stage,
    }))
}

// ---------------------------------------------------------------------------
// Build chart data from breakdown_preview
// ---------------------------------------------------------------------------

function buildChartFromBreakdown(turn: TurnResponse): ChartData | undefined {
  if (!turn.breakdown_preview.length || turn.breakdown_columns.length < 2) return undefined

  const textCol = turn.breakdown_columns.find((c) => c.value_type === 'text')
  const numCol = turn.breakdown_columns.find((c) => c.value_type === 'monetary' || c.value_type === 'count' || c.value_type === 'percentage')

  if (!textCol || !numCol) return undefined

  const labels = turn.breakdown_preview.map((row) => String(row[textCol.label] ?? ''))
  const data = turn.breakdown_preview.map((row) => {
    const raw = row[numCol.label]
    return typeof raw === 'string' ? parseFloat(raw) : typeof raw === 'number' ? raw : 0
  })

  return {
    kind: labels.length <= 6 ? 'bar' : 'bar',
    labels,
    series: [{ name: numCol.label, data }],
    xLabel: textCol.label,
    yLabel: numCol.currency ? `Amount (${numCol.currency})` : numCol.label,
  }
}

// ---------------------------------------------------------------------------
// Main adapter
// ---------------------------------------------------------------------------

export function turnResponseToQueryResult(turn: TurnResponse, traceEvents?: TraceEvent[]): QueryResult {
  const id = `q-${turn.turn_id}`

  // Determine confidence from band
  const confidence: 'high' | 'medium' | 'low' = turn.confidence_band ?? 'low'

  // Build confidence note
  let confidenceNote = ''
  if (turn.caution) {
    confidenceNote = turn.caution
  } else if (turn.confidence_band === 'high') {
    confidenceNote = 'High confidence — all verification signals passed.'
  } else if (turn.outcome === 'abstained') {
    confidenceNote = turn.answer_text ?? 'The system declined to answer this question.'
  } else {
    confidenceNote = 'Computed from the pipeline verification signals.'
  }

  // Build filters from applied_filters
  const filters = turn.applied_filters.map((f) => ({
    label: f.dimension,
    value: f.expression,
  }))
  // Add resolution path as a filter
  if (turn.resolution_path) {
    filters.push({ label: 'Resolution', value: turn.resolution_path === 'metric_layer' ? 'Metric Layer' : 'Generated SQL' })
  }

  // Build trace steps from events or from turn metadata
  const steps: TraceStep[] = traceEvents?.length
    ? traceEventsToSteps(traceEvents)
    : turn.computation_records.length > 0
      ? [
          { kind: 'parse' as TraceKind, label: `Resolved: ${turn.resolved_question ?? 'question'}` },
          ...(turn.resolution_path === 'metric_layer'
            ? [{ kind: 'compute' as TraceKind, label: `Used metric template: ${turn.metric_name ?? 'matched'}` }]
            : [{ kind: 'compute' as TraceKind, label: 'Generated and validated SQL' }]),
          { kind: 'compute' as TraceKind, label: `Executed query → ${turn.total_row_count ?? 0} rows` },
          { kind: 'guardrail' as TraceKind, label: 'Verified all figures are grounded in query results' },
        ]
      : []

  // Build records — map breakdown_preview to Transaction-like objects
  const records = turn.breakdown_preview.map((row, i) => {
    const textCol = turn.breakdown_columns.find((c) => c.value_type === 'text')
    const moneyCol = turn.breakdown_columns.find((c) => c.value_type === 'monetary')
    return {
      id: `row-${i}`,
      date: turn.resolved_date_range?.[0] ?? '',
      vendorId: '',
      accountCode: '',
      description: textCol ? String(row[textCol.label] ?? '') : JSON.stringify(row),
      amount: moneyCol ? -(parseFloat(String(row[moneyCol.label] ?? '0'))) : 0,
      status: 'reconciled' as const,
      isPayout: true,
    }
  })

  // Build groupBy from breakdown
  const groupBy = turn.breakdown_preview.length > 0
    ? turn.breakdown_preview.map((row) => {
        const textCol = turn.breakdown_columns.find((c) => c.value_type === 'text')
        const moneyCol = turn.breakdown_columns.find((c) => c.value_type === 'monetary')
        return {
          label: textCol ? String(row[textCol.label] ?? '') : '',
          value: moneyCol ? Math.abs(parseFloat(String(row[moneyCol.label] ?? '0'))) : 0,
          count: 1,
        }
      })
    : undefined

  // Build totals from first computation record
  const firstComp = turn.computation_records[0]
  const totalLabel = firstComp?.label
  const totalValue = firstComp?.value ? Math.abs(parseFloat(firstComp.value)) : undefined

  // Build anomaly from callouts
  const anomaly = turn.anomaly_callouts.length > 0
    ? {
        text: `${turn.anomaly_callouts[0].entity}'s payment of ${formatMoney(turn.anomaly_callouts[0].value, 'INR')} is ${turn.anomaly_callouts[0].z?.toFixed(1) ?? '?'}x above their typical transaction (median ${formatMoney(turn.anomaly_callouts[0].median, 'INR')}).`,
        transactionId: '',
      }
    : undefined

  // Build chart
  const chart = buildChartFromBreakdown(turn)

  // Build source ref
  const sourceRef = turn.executed_sql
    ? `SQL query — ${turn.total_row_count ?? 0} rows`
    : turn.metric_name
      ? `Metric: ${turn.metric_name}`
      : turn.outcome === 'abstained'
        ? `Abstained: ${turn.abstention_reason_code ?? 'unknown'}`
        : 'n/a'

  // Build the answer text
  let answer: string
  if (turn.outcome === 'answered') {
    answer = turn.answer_text ?? 'Answer received.'
  } else if (turn.outcome === 'abstained') {
    answer = turn.answer_text ?? "I can't answer that from the data I have."
  } else if (turn.outcome === 'clarification_requested') {
    answer = turn.clarifying_question?.question ?? 'Could you clarify your question?'
  } else {
    answer = "Something went wrong. Please try again."
  }

  return {
    id,
    answer,
    confidence,
    confidenceNote,
    filters,
    steps,
    records,
    totalLabel,
    totalValue,
    groupBy,
    anomaly,
    chart,
    sourceRef,
    noData: turn.outcome === 'abstained' || turn.outcome === 'failed',
  }
}

// ===========================================================================
// REAL backend adapter: AgentTurnResponse (simple_pipeline) → QueryResult
// ===========================================================================

const AGENT_STAGE_META: Record<string, { kind: TraceKind; label: string }> = {
  sql_generation: { kind: 'compute', label: 'Generated SQL' },
  static_validation: { kind: 'guardrail', label: 'Validated SQL (read-only, schema-checked)' },
  reviewer_verdict: { kind: 'guardrail', label: 'Reviewer checked the query' },
  execution: { kind: 'compute', label: 'Executed query' },
  computation: { kind: 'compute', label: 'Computed figures' },
  answer_composition: { kind: 'compute', label: 'Composed the answer' },
}

const AGENT_STAGE_ORDER = [
  'sql_generation',
  'static_validation',
  'reviewer_verdict',
  'execution',
  'computation',
  'answer_composition',
]

function agentChartToChartData(c: AgentChart | null): ChartData | undefined {
  if (!c || !c.points?.length) return undefined
  const allowed = ['pie', 'bar', 'line', 'doughnut']
  const kind = (allowed.includes(c.type) ? c.type : 'bar') as ChartData['kind']
  return {
    kind,
    labels: c.points.map((p) => p.label),
    series: [{ name: c.value_field, data: c.points.map((p) => Number(p.value)) }],
    xLabel: c.label_field,
    yLabel: c.value_field,
  }
}

export function agentResponseToQueryResult(res: AgentTurnResponse): QueryResult {
  const id = `q-${Date.now()}-${Math.floor(Math.random() * 1000)}`
  const answered = res.outcome === 'answered' && !!res.answer_text

  let confidence: 'high' | 'medium' | 'low'
  if (answered && res.verdict?.verdict === 'approve') confidence = 'high'
  else if (res.verdict?.verdict === 'repair') confidence = 'medium'
  else confidence = 'low'

  const confidenceNote =
    res.verdict?.reason ??
    res.validation_reason ??
    (answered ? 'Answer produced from the executed query.' : 'The system could not produce a grounded answer.')

  // steps from trace[], sorted by canonical order, with durations
  const steps: TraceStep[] = [...res.trace]
    .sort((a, b) => {
      const ai = AGENT_STAGE_ORDER.indexOf(a.stage)
      const bi = AGENT_STAGE_ORDER.indexOf(b.stage)
      return (ai === -1 ? AGENT_STAGE_ORDER.length : ai) - (bi === -1 ? AGENT_STAGE_ORDER.length : bi)
    })
    .map((t) => {
      const meta = AGENT_STAGE_META[t.stage]
      const label = meta?.label ?? t.stage
      const kind = meta?.kind ?? 'compute'
      return { kind, label: `${label} (${t.duration_ms}ms)` }
    })

  // filters: answer_source and reviewer verdict
  const filters: { label: string; value: string }[] = []
  if (res.answer_source) {
    const sourceValue =
      res.answer_source === 'llm'
        ? 'LLM'
        : res.answer_source === 'template'
          ? 'Template'
          : 'Template (fallback)'
    filters.push({ label: 'Answer source', value: sourceValue })
  }
  if (res.verdict) {
    filters.push({ label: 'Reviewer verdict', value: res.verdict.verdict })
  }

  const chart = agentChartToChartData(res.chart)

  const answer = res.answer_text
    ?? (res.validation_reason
      ? `I couldn't answer that: ${res.validation_reason}`
      : "Something went wrong. Please try again.")

  const sourceRef = res.resolved_sql
    ? `SQL query — ${res.breakdown?.rows?.length ?? 0} rows`
    : res.validation_reason
      ? `Rejected: ${res.validation_reason}`
      : 'n/a'

  return {
    id,
    answer,
    confidence,
    confidenceNote,
    filters,
    steps,
    records: [],
    chart,
    sourceRef,
    noData: !answered,
  }
}

// ===========================================================================
// REAL streaming backend adapter: SSE frames + `completion` → QueryResult
// ===========================================================================

/** Coerce an unknown SSE field to a non-empty display string, or undefined. */
function text(value: unknown): string | undefined {
  if (value === null || value === undefined) return undefined
  const s = typeof value === 'string' ? value : String(value)
  return s.trim().length ? s : undefined
}

const ANSWER_SOURCE_LABELS: Record<string, string> = {
  llm: 'LLM',
  template: 'Template',
  template_fallback: 'Template (fallback)',
}

/** One-line human summary of an inline chart spec frame. */
function chartSummary(chart: unknown): string | undefined {
  if (!chart || typeof chart !== 'object') return undefined
  const c = chart as Record<string, unknown>
  const type = text(c.type) ?? 'chart'
  const labelField = text(c.label_field) ?? '?'
  const valueField = text(c.value_field) ?? '?'
  const points = Array.isArray(c.points) ? c.points.length : 0
  return `${type} — ${labelField} × ${valueField} (${points} points)`
}

/** The completion breakdown as an expandable table, when it carries rows. */
function breakdownTable(completion?: AgentCompletion): TraceTable | undefined {
  const b = completion?.breakdown
  if (!b?.columns?.length || !b.rows?.length) return undefined
  return {
    columns: b.columns,
    rows: b.rows,
    totalRowCount: b.total_row_count ?? undefined,
  }
}

/**
 * Turn the OBSERVED stream events into trace steps.
 *
 * Only "result" frames produce a step — `{status:'start'}` frames and the
 * terminal `completion` frame are skipped, and each stage yields at most one
 * step even if the pipeline retries it. Result frames carry the stage's
 * underlying data (SQL, reviewer reasoning, rows) as expandable `details`,
 * and `durationMs` is measured from the matching `start` frame's arrival.
 */
export function agentEventsToSteps(
  events: AgentStreamEvent[],
  completion?: AgentCompletion,
): TraceStep[] {
  const steps: TraceStep[] = []
  const seen = new Set<string>()

  // Stage → arrival time of its `{status:'start'}` frame, for client-side timing.
  const startedAt = new Map<string, number>()
  for (const evt of events) {
    const status = typeof evt.data?.status === 'string' ? evt.data.status : undefined
    if (status === 'start' && evt.receivedAt != null && !startedAt.has(evt.event)) {
      startedAt.set(evt.event, evt.receivedAt)
    }
  }

  for (const evt of events) {
    if (evt.event === 'completion') continue
    if (seen.has(evt.event)) continue

    const envelope = evt.data ?? {}
    const status = typeof envelope.status === 'string' ? envelope.status : undefined
    if (status === 'start') continue
    // Enriched backend events nest the stage payload under `detail`; older/flat events put it at
    // the top of `data`. Read detail first, fall back to the envelope.
    const d = (envelope.detail && typeof envelope.detail === 'object'
      ? { ...envelope, ...(envelope.detail as Record<string, unknown>) }
      : envelope) as Record<string, unknown>

    let step: TraceStep | undefined
    const details: TraceDetail[] = []
    let table: TraceTable | undefined

    switch (evt.event) {
      case 'intake': {
        step = { kind: 'parse', label: 'Received the question' }
        const question = text(d.question)
        if (question) details.push({ label: 'Question', value: question, format: 'text' })
        break
      }
      case 'sql_generation': {
        if (status !== 'ok' && status !== 'done') break
        step = { kind: 'compute', label: 'Generated SQL' }
        const sql = text(d.sql)
        if (sql) details.push({ label: 'Generated SQL', value: sql, format: 'sql' })
        break
      }
      case 'static_validation': {
        if (status === 'ok') {
          step = { kind: 'guardrail', label: 'Validated SQL (read-only, schema-checked)' }
          const canonical = text(d.canonical_sql)
          if (canonical) details.push({ label: 'Canonical SQL', value: canonical, format: 'sql' })
        } else if (status === 'rejected') {
          step = { kind: 'guardrail', label: 'Rejected unsafe or non-conformant SQL' }
          details.push({
            label: 'Reason',
            value: text(completion?.validation_reason) ?? 'The query failed static validation.',
            format: 'text',
          })
        }
        break
      }
      case 'reviewer_verdict': {
        const verdict = text(d.verdict)
        if (!verdict) break
        step = { kind: 'guardrail', label: `Reviewer: ${verdict}` }
        details.push({ label: 'Verdict', value: verdict, format: 'text' })
        const reason = text(d.reason)
        if (reason) details.push({ label: 'Reasoning', value: reason, format: 'text' })
        break
      }
      case 'execution': {
        if (d.row_count == null) break
        step = { kind: 'compute', label: `Executed query → ${d.row_count} rows` }
        details.push({ label: 'Rows returned', value: String(d.row_count), format: 'text' })
        const executedSql = text(completion?.resolved_sql)
        if (executedSql) details.push({ label: 'Executed SQL', value: executedSql, format: 'sql' })
        const chart = chartSummary(d.chart)
        if (chart) details.push({ label: 'Chart', value: chart, format: 'text' })
        table = breakdownTable(completion)
        break
      }
      case 'answer_composition': {
        if (d.answer == null) break
        step = { kind: 'compute', label: 'Composed the answer' }
        const answer = text(d.answer)
        if (answer) details.push({ label: 'Answer', value: answer, format: 'text' })
        const source = completion?.answer_source
        if (source) {
          details.push({
            label: 'Source',
            value: ANSWER_SOURCE_LABELS[source] ?? source,
            format: 'text',
          })
        }
        break
      }
      case 'plan_inspection': {
        if (status === 'ok') {
          step = { kind: 'guardrail', label: 'Checked query plan cost (EXPLAIN)' }
          if (d.cost != null) details.push({ label: 'Plan cost', value: String(d.cost), format: 'text' })
        } else if (status === 'rejected') {
          step = { kind: 'guardrail', label: 'Rejected — query plan too expensive' }
          if (d.cost != null) details.push({ label: 'Plan cost', value: String(d.cost), format: 'text' })
        }
        break
      }
      case 'computation': {
        step = { kind: 'compute', label: 'Ran financial calculators' }
        const tools = Array.isArray(d.tools) ? (d.tools as string[]).join(', ') : undefined
        if (tools) details.push({ label: 'Tools', value: tools, format: 'text' })
        break
      }
      case 'clarification': {
        step = { kind: 'guardrail', label: 'Asked a follow-up instead of guessing' }
        const question = text(d.question)
        if (question) details.push({ label: 'Follow-up', value: question, format: 'text' })
        break
      }
      default:
        break
    }

    if (step) {
      if (details.length) step.details = details
      if (table) step.table = table

      const start = startedAt.get(evt.event)
      if (start != null && evt.receivedAt != null) {
        step.durationMs = evt.receivedAt - start
      }

      steps.push(step)
      seen.add(evt.event)
    }
  }

  return steps
}

export function agentCompletionToQueryResult(
  res: AgentCompletion,
  events?: AgentStreamEvent[],
): QueryResult {
  const id = `q-${Date.now()}-${Math.floor(Math.random() * 1000)}`
  const clarifying = res.outcome === 'clarification_requested' || !!res.clarification
  const answered = res.outcome === 'answered' && !!res.answer_text

  let confidence: 'high' | 'medium' | 'low'
  if (answered && res.verdict?.verdict === 'approve') confidence = 'high'
  else if (clarifying) confidence = 'medium'
  else if (res.verdict?.verdict === 'repair') confidence = 'medium'
  else confidence = 'low'

  let answer: string
  if (clarifying) answer = res.clarification ?? 'Could you clarify your question?'
  else if (answered) answer = res.answer_text as string
  else answer = res.validation_reason ?? "I couldn't produce a grounded answer for that."

  const confidenceNote = clarifying
    ? 'The question was under-specified, so the assistant asked a follow-up rather than guessing.'
    : (res.verdict?.reason
      ?? res.validation_reason
      ?? (answered ? 'Answer produced from the executed query.' : 'No grounded answer was produced.'))

  // Labels must stay unique — EvidencePanel keys its chips on `label`.
  const filters: { label: string; value: string }[] = []
  if (res.answer_source) {
    const sourceValue =
      res.answer_source === 'llm'
        ? 'LLM'
        : res.answer_source === 'template'
          ? 'Template'
          : 'Template (fallback)'
    filters.push({ label: 'Answer source', value: sourceValue })
  }
  if (res.verdict) filters.push({ label: 'Reviewer', value: res.verdict.verdict })
  if (res.breakdown?.total_row_count != null) {
    filters.push({ label: 'Rows', value: String(res.breakdown.total_row_count) })
  }

  const sourceRef = res.resolved_sql
    ? `SQL query — ${res.breakdown?.total_row_count ?? 0} rows`
    : res.validation_reason
      ? `Rejected: ${res.validation_reason}`
      : 'n/a'

  return {
    id,
    answer,
    confidence,
    confidenceNote,
    filters,
    steps: events?.length ? agentEventsToSteps(events, res) : [],
    // Deliberately empty: the source-records table and groupBy list both
    // money-format via formatUSD, which is wrong for count-valued breakdowns.
    records: [],
    chart: clarifying ? undefined : agentChartToChartData(res.chart),
    sourceRef,
    noData: !answered,
  }
}
