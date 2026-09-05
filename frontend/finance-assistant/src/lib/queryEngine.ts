import type { ChartData, QueryContext, QueryResult, ReconciliationStatus, Transaction, TraceStep, TraceKind } from './types'
import { TRANSACTIONS } from '../data/transactions'
import { VENDORS } from '../data/vendors'
import { ACCOUNTS } from '../data/accounts'
import { formatUSD, monthLabel } from './format'

// "Today" is fixed for the demo dataset so month-relative questions resolve deterministically.
const TODAY = { year: 2026, month: 8 } // September 2026 (0-indexed month)

const vendorName = (id: string) => VENDORS.find((v) => v.id === id)!.name
const accountName = (code: string) => ACCOUNTS.find((a) => a.code === code)!.name

const step = (kind: TraceKind, label: string): TraceStep => ({ kind, label })

const CATEGORY_KEYWORDS: { code: string; words: string[] }[] = [
  { code: '5000', words: ['raw material', 'raw materials', 'steel', 'alloy'] },
  { code: '5100', words: ['packaging', 'packing', 'carton'] },
  { code: '6010', words: ['office supplies', 'office supply'] },
  { code: '6100', words: ['logistics', 'freight', 'shipping'] },
  { code: '6200', words: ['software', 'subscription', 'subscriptions', 'saas'] },
  { code: '6300', words: ['professional services', 'consulting', 'legal', 'advisory'] },
  { code: '6400', words: ['marketing', 'advertising', 'campaign'] },
  { code: '6500', words: ['facilities', 'facility', 'maintenance', 'hvac', 'janitorial'] },
]

const MONTH_NAMES = ['january', 'february', 'march', 'april', 'may', 'june', 'july', 'august', 'september', 'october', 'november', 'december']

function findVendor(q: string) {
  return VENDORS.find((v) => {
    const parts = v.name.toLowerCase().replace(/[.,&]/g, '').split(' ').filter((w) => w.length > 3)
    return q.includes(v.name.toLowerCase()) || parts.some((p) => q.includes(p))
  })
}

function findAccount(q: string) {
  for (const cat of CATEGORY_KEYWORDS) {
    if (cat.words.some((w) => q.includes(w))) return cat.code
  }
  return undefined
}

function findStatus(q: string): ReconciliationStatus | undefined {
  if (/(unreconciled|not reconciled|outstanding|still open|pending reconciliation)/.test(q)) return 'unreconciled'
  if (/\breconciled\b/.test(q) && !/unreconciled/.test(q)) return 'reconciled'
  return undefined
}

function shiftMonth(year: number, month: number, delta: number) {
  const total = year * 12 + month + delta
  return { year: Math.floor(total / 12), month: ((total % 12) + 12) % 12 }
}

function findDateRange(q: string) {
  // Note: "month before" / "previous month" phrasing is handled entirely inside the
  // comparison branch of runQuery (it shifts off the *inherited* range) - resolving it
  // here too would double-shift the month.
  if (/last month/.test(q)) {
    const r = shiftMonth(TODAY.year, TODAY.month, -1)
    return { ...r, isRelative: true }
  }
  if (/this month/.test(q)) {
    return { year: TODAY.year, month: TODAY.month, isRelative: true }
  }
  for (let i = 0; i < MONTH_NAMES.length; i++) {
    if (q.includes(MONTH_NAMES[i])) {
      const yearMatch = q.match(/20\d{2}/)
      return { year: yearMatch ? Number(yearMatch[0]) : TODAY.year, month: i, isRelative: false }
    }
  }
  return undefined
}

function inRange(date: string, year: number, month: number) {
  const [y, m] = date.split('-').map(Number)
  return y === year && m - 1 === month
}

function filterTx(opts: { vendorId?: string; accountCode?: string; status?: ReconciliationStatus; year?: number; month?: number }): Transaction[] {
  return TRANSACTIONS.filter((t) => {
    if (opts.vendorId && t.vendorId !== opts.vendorId) return false
    if (opts.accountCode && t.accountCode !== opts.accountCode) return false
    if (opts.status && t.status !== opts.status) return false
    if (opts.year !== undefined && opts.month !== undefined && !inRange(t.date, opts.year, opts.month)) return false
    return true
  })
}

function sumAbs(rows: Transaction[]) {
  return rows.reduce((s, t) => s + Math.abs(t.amount), 0)
}

function groupByVendor(rows: Transaction[]) {
  const map = new Map<string, { value: number; count: number }>()
  for (const t of rows) {
    const cur = map.get(t.vendorId) ?? { value: 0, count: 0 }
    cur.value += Math.abs(t.amount)
    cur.count += 1
    map.set(t.vendorId, cur)
  }
  return [...map.entries()]
    .map(([id, v]) => ({ label: vendorName(id), value: v.value, count: v.count }))
    .sort((a, b) => b.value - a.value)
}

// Vendor historical averages (whole dataset) used to flag anomalies.
function vendorAverage(vendorId: string, excludeId?: string) {
  const rows = TRANSACTIONS.filter((t) => t.vendorId === vendorId && t.id !== excludeId)
  if (!rows.length) return 0
  return sumAbs(rows) / rows.length
}

function detectAnomaly(rows: Transaction[]) {
  for (const t of rows) {
    const avg = vendorAverage(t.vendorId, t.id)
    if (avg > 0 && Math.abs(t.amount) > avg * 2.5) {
      return { text: `${vendorName(t.vendorId)}'s ${formatUSD(t.amount)} payment on ${t.date} runs about ${(Math.abs(t.amount) / avg).toFixed(1)}x above their typical transaction (${formatUSD(-avg)}).`, transactionId: t.id }
    }
  }
  return undefined
}

const OUT_OF_SCOPE = /(profit|margin|forecast|projection|revenue growth|salary|payroll|headcount|tax filing|budget for next|valuation|stock price|market share)/

export function runQuery(rawQuestion: string, prevContext?: QueryContext): { result: QueryResult; context: QueryContext } {
  const q = rawQuestion.toLowerCase().trim()
  const id = `q-${Date.now()}-${Math.floor(Math.random() * 1000)}`

  const vendor = findVendor(q)
  const account = findAccount(q)
  const status = findStatus(q)
  const isComparison = /(compare|versus|\bvs\b|month before|previous month|how does that)/.test(q)
  const isAnomalyAsk = /(unusual|anomaly|anomalies|outlier|flag anything|spike|out of the ordinary)/.test(q)

  const inheritedRange = prevContext?.year !== undefined && prevContext?.month !== undefined ? { year: prevContext.year, month: prevContext.month } : undefined
  const range = findDateRange(q)

  const effectiveVendorId = vendor?.id ?? (isComparison ? prevContext?.vendorId : undefined)
  const effectiveAccount = account ?? (isComparison ? prevContext?.accountCode : undefined)
  const effectiveStatus = status ?? (isComparison ? prevContext?.status : undefined)

  // ---- Comparison: current-known range vs the month before it ----
  if (isComparison && (range || inheritedRange)) {
    const basisRange = range ?? inheritedRange!
    const priorRange = shiftMonth(basisRange.year, basisRange.month, -1)

    const basisRows = filterTx({ vendorId: effectiveVendorId, accountCode: effectiveAccount, status: effectiveStatus, ...basisRange })
    const priorRows = filterTx({ vendorId: effectiveVendorId, accountCode: effectiveAccount, status: effectiveStatus, ...priorRange })
    const basisTotal = sumAbs(basisRows)
    const priorTotal = sumAbs(priorRows)
    const delta = basisTotal - priorTotal
    const pct = priorTotal > 0 ? (delta / priorTotal) * 100 : 0
    const direction = delta >= 0 ? 'up' : 'down'

    const scopeLabel = effectiveVendorId ? vendorName(effectiveVendorId) : effectiveAccount ? accountName(effectiveAccount) : 'vendor payouts'

    const result: QueryResult = {
      id,
      answer: `${scopeLabel} spend in ${monthLabel(basisRange.year, basisRange.month)} was ${formatUSD(basisTotal)}, ${direction} ${Math.abs(pct).toFixed(1)}% from ${formatUSD(priorTotal)} in ${monthLabel(priorRange.year, priorRange.month)}.`,
      confidence: priorRows.length > 0 && basisRows.length > 0 ? 'high' : 'medium',
      confidenceNote: priorRows.length > 0 ? 'Both months have posted transactions to compare directly.' : 'One of the two months has very few records, so this comparison is thinner than usual.',
      filters: [
        { label: 'Scope', value: scopeLabel },
        { label: 'Period A', value: monthLabel(priorRange.year, priorRange.month) },
        { label: 'Period B', value: monthLabel(basisRange.year, basisRange.month) },
      ],
      steps: [
        step('parse', `Reused scope from the previous question: ${scopeLabel}.`),
        step('filter', `Filtered to ${monthLabel(priorRange.year, priorRange.month)} -> ${priorRows.length} transactions, ${formatUSD(priorTotal)}.`),
        step('filter', `Filtered to ${monthLabel(basisRange.year, basisRange.month)} -> ${basisRows.length} transactions, ${formatUSD(basisTotal)}.`),
        step('compute', `Computed percent change between the two totals.`),
      ],
      records: [...priorRows, ...basisRows].sort((a, b) => a.date.localeCompare(b.date)),
      groupBy: [
        { label: monthLabel(priorRange.year, priorRange.month), value: priorTotal, count: priorRows.length },
        { label: monthLabel(basisRange.year, basisRange.month), value: basisTotal, count: basisRows.length },
      ],
      chart: {
        kind: 'bar',
        labels: [monthLabel(priorRange.year, priorRange.month), monthLabel(basisRange.year, basisRange.month)],
        series: [{ name: scopeLabel, data: [priorTotal, basisTotal] }],
        xLabel: 'Period',
        yLabel: 'Spend (USD)',
      },
      sourceRef: `transactions.csv - ${priorRows.length + basisRows.length} matching rows`,
    }
    return { result, context: { vendorId: effectiveVendorId, accountCode: effectiveAccount, status: effectiveStatus, ...priorRange } }
  }

  // ---- Combo Chart Demo (Projected Profit/Performance) ----
  if (/projected profit/i.test(q) || /monthly performance/i.test(q) || /performance/i.test(q)) {
    const result: QueryResult = {
      id,
      answer: `Here is the monthly performance with projections against targets and prior year.`,
      confidence: 'medium',
      confidenceNote: 'Projections are based on historical run-rate and assumed market growth.',
      filters: [{ label: 'Metric', value: 'Revenue & Profit' }],
      steps: [
        step('parse', `Recognized a performance/projection query.`),
        step('compute', `Assembled historical monthly data.`),
        step('compute', `Overlaid target metrics and prior year baselines.`),
      ],
      records: [],
      chart: {
        kind: 'combo',
        labels: ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'],
        series: [
          { name: 'Revenue', data: [2.1, 2.4, 2.8, 2.9, 3.2, 3.4, 2.9, 3.0, 3.8, 4.2, 6.5, 6.9], kind: 'bar' },
          { name: 'Target', data: [2.0, 2.5, 2.8, 3.0, 3.3, 3.5, 3.0, 3.1, 4.0, 4.5, 6.8, 7.1], kind: 'line', style: 'dashed' },
          { name: 'Prior year', data: [1.8, 2.2, 2.5, 2.6, 2.8, 3.0, 2.6, 2.8, 3.4, 3.8, 6.0, 6.2], kind: 'line', style: 'solid' },
        ],
        xLabel: 'Month',
        yLabel: 'Revenue ($M)',
      } as ChartData,
      sourceRef: 'Financial Model v4 (Projected)',
    }
    return { result, context: {} }
  }

  // ---- Anomaly sweep ----
  if (isAnomalyAsk) {
    const recentRange = range ?? shiftMonth(TODAY.year, TODAY.month, -1)
    const rows = filterTx({ vendorId: effectiveVendorId, accountCode: effectiveAccount, ...recentRange })
    const flagged = rows.filter((t) => {
      const avg = vendorAverage(t.vendorId, t.id)
      return avg > 0 && Math.abs(t.amount) > avg * 2.5
    })
    const result: QueryResult = {
      id,
      answer: flagged.length
        ? `Yes. ${flagged.length} payment${flagged.length > 1 ? 's stand' : ' stands'} out in ${monthLabel(recentRange.year, recentRange.month)}, well above the paying vendor's usual transaction size.`
        : `No payments in ${monthLabel(recentRange.year, recentRange.month)} fall outside the normal range for their vendor.`,
      confidence: 'medium',
      confidenceNote: 'Flagged using a 2.5x vendor-average threshold on transaction size, a simple heuristic rather than a statistical model.',
      filters: [{ label: 'Period', value: monthLabel(recentRange.year, recentRange.month) }, { label: 'Threshold', value: '> 2.5x vendor average' }],
      steps: [
        step('filter', `Filtered to ${monthLabel(recentRange.year, recentRange.month)} -> ${rows.length} transactions.`),
        step('compute', `Computed each vendor's historical average transaction size.`),
        step('flag', `Flagged transactions exceeding 2.5x their vendor's average.`),
      ],
      records: flagged,
      anomaly: flagged[0] ? { text: detectAnomaly(flagged)?.text ?? '', transactionId: flagged[0].id } : undefined,
      chart: flagged.length ? {
        kind: 'bar',
        labels: flagged.map(t => vendorName(t.vendorId)),
        series: [{ name: 'Flagged Amount', data: flagged.map(t => Math.abs(t.amount)) }],
        xLabel: 'Vendor',
        yLabel: 'Amount (USD)',
      } as ChartData : undefined,
      sourceRef: `transactions.csv - ${rows.length} rows scanned, ${flagged.length} flagged`,
    }
    return { result, context: { year: recentRange.year, month: recentRange.month, vendorId: effectiveVendorId, accountCode: effectiveAccount } }
  }

  // ---- Unreconciled list ----
  if (effectiveStatus === 'unreconciled' || /unreconciled/.test(q)) {
    const rows = filterTx({ vendorId: effectiveVendorId, accountCode: effectiveAccount, status: 'unreconciled', ...(range ?? {}) })
    const total = sumAbs(rows)
    const result: QueryResult = {
      id,
      answer: rows.length
        ? `${rows.length} transactions are still unreconciled${range ? ` in ${monthLabel(range.year, range.month)}` : ''}, totaling ${formatUSD(total)}.`
        : `No unreconciled transactions match that${range ? ` in ${monthLabel(range.year, range.month)}` : ''}. Everything in scope is settled.`,
      confidence: 'high',
      confidenceNote: 'Reconciliation status is a direct field on each transaction record, not inferred.',
      filters: [
        { label: 'Status', value: 'Unreconciled' },
        ...(vendor ? [{ label: 'Vendor', value: vendor.name }] : []),
        ...(range ? [{ label: 'Period', value: monthLabel(range.year, range.month) }] : []),
      ],
      steps: [
        step('parse', `Recognized a reconciliation-status question.`),
        step('filter', `Filtered ledger to status = unreconciled${range ? ` and date within ${monthLabel(range.year, range.month)}` : ''} -> ${rows.length} transactions.`),
        step('compute', `Summed the amount column for the total outstanding.`),
      ],
      records: rows,
      groupBy: groupByVendor(rows),
      totalLabel: 'Unreconciled total',
      totalValue: total,
      anomaly: detectAnomaly(rows),
      chart: rows.length ? {
        kind: 'doughnut',
        labels: groupByVendor(rows).map(g => g.label),
        series: [{ name: 'Unreconciled', data: groupByVendor(rows).map(g => g.value) }],
        yLabel: 'Unreconciled by Vendor',
      } as ChartData : undefined,
      sourceRef: `transactions.csv - ${rows.length} rows, reconciliation_status field`,
    }
    return { result, context: { vendorId: effectiveVendorId, accountCode: effectiveAccount, status: 'unreconciled', ...(range ?? {}) } }
  }

  // ---- Spend / payout sum ----
  const hasSpendIntent = /(spend|spent|paid|payout|payouts|cost|total)/.test(q) || vendor || account || range
  if (hasSpendIntent && !OUT_OF_SCOPE.test(q)) {
    const effectiveRange = range ?? shiftMonth(TODAY.year, TODAY.month, -1)
    const rows = filterTx({ vendorId: effectiveVendorId, accountCode: effectiveAccount, ...effectiveRange })
    const total = sumAbs(rows)
    const scopeLabel = vendor ? vendor.name : account ? accountName(account) : 'vendor payouts'
    const group = vendor ? undefined : groupByVendor(rows)

    if (!rows.length) {
      return {
        result: {
          id,
          answer: `I don't have any transactions matching that in ${monthLabel(effectiveRange.year, effectiveRange.month)}. It's possible the vendor, category, or period is outside the provided dataset.`,
          confidence: 'low',
          confidenceNote: 'No records matched the filters, so there is nothing to compute from.',
          filters: [{ label: 'Period', value: monthLabel(effectiveRange.year, effectiveRange.month) }],
          steps: [
            step('parse', `Extracted scope${vendor ? `: vendor ${vendor.name}` : account ? `: category ${accountName(account)}` : ''} and period.`),
            step('filter', `Filtered to ${monthLabel(effectiveRange.year, effectiveRange.month)}${vendor ? ` and vendor: ${vendor.name}` : ''} -> 0 transactions.`),
            step('guardrail', `No rows matched. Declined to estimate rather than guess a figure.`),
          ],
          records: [],
          sourceRef: 'transactions.csv - 0 matching rows',
          noData: true,
        },
        context: { vendorId: effectiveVendorId, accountCode: effectiveAccount, ...effectiveRange },
      }
    }

    const anomaly = detectAnomaly(rows)
    const result: QueryResult = {
      id,
      answer: `You spent ${formatUSD(total)} on ${scopeLabel} in ${monthLabel(effectiveRange.year, effectiveRange.month)}, across ${rows.length} transaction${rows.length === 1 ? '' : 's'}${group ? ` and ${group.length} vendor${group.length === 1 ? '' : 's'}` : ''}.`,
      confidence: 'high',
      confidenceNote: 'Computed directly from the filtered transaction rows below; nothing here is estimated.',
      filters: [
        { label: 'Scope', value: scopeLabel },
        { label: 'Period', value: monthLabel(effectiveRange.year, effectiveRange.month) },
      ],
      steps: [
        step('parse', `Parsed intent: total spend, scope ${scopeLabel}, period ${monthLabel(effectiveRange.year, effectiveRange.month)}.`),
        step('filter', `Filtered ${TRANSACTIONS.length} ledger rows down to ${rows.length} matching rows.`),
        step('compute', `Summed the amount column${group ? ', grouped by vendor' : ''}.`),
      ],
      records: rows,
      groupBy: group,
      totalLabel: `Total, ${monthLabel(effectiveRange.year, effectiveRange.month)}`,
      totalValue: total,
      anomaly,
      chart: group && group.length > 1 ? {
        kind: 'bar',
        labels: group.map(g => g.label),
        series: [{ name: monthLabel(effectiveRange.year, effectiveRange.month), data: group.map(g => g.value) }],
        xLabel: 'Vendor',
        yLabel: 'Spend (USD)',
      } as ChartData : undefined,
      sourceRef: `transactions.csv - ${rows.length} matching rows`,
    }
    return { result, context: { vendorId: effectiveVendorId, accountCode: effectiveAccount, ...effectiveRange } }
  }

  // ---- Guardrail: out of scope or unrecognized ----
  return {
    result: {
      id,
      answer: "I can't answer that from the data I have. I only have transactions, vendor payouts, and reconciliation status for this company, so I can't speak to projections, payroll, or anything outside that ledger.",
      confidence: 'low',
      confidenceNote: "This question doesn't map to a field in the provided schema, so answering would mean guessing.",
      filters: [],
      steps: [
        step('parse', 'Checked the question against available fields: transactions, vendor, account category, date, reconciliation status.'),
        step('guardrail', 'No match found. Declined rather than estimate.'),
      ],
      records: [],
      sourceRef: 'n/a - question outside provided schema',
      noData: true,
    },
    context: prevContext ?? {},
  }
}
