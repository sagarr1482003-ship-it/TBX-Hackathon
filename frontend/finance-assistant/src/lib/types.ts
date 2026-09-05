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

export interface TraceStep {
  kind: TraceKind
  label: string
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
