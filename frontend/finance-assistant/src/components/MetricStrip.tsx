import { TrendUp, Database, CalendarBlank } from '@phosphor-icons/react'
import { formatUSD } from '../lib/format'
import type { QueryResult } from '../lib/types'

export function MetricStrip({ result }: { result: QueryResult }) {
  const metrics: { label: string; value: string; icon: React.ReactNode }[] = []

  if (result.totalValue !== undefined) {
    metrics.push({
      label: result.totalLabel ?? 'Total',
      value: formatUSD(result.totalValue),
      icon: <TrendUp size={13} weight="bold" />,
    })
  }

  if (result.records.length > 0) {
    metrics.push({
      label: 'Records',
      value: result.records.length.toString(),
      icon: <Database size={13} />,
    })
  }

  if (result.groupBy && result.groupBy.length > 0) {
    metrics.push({
      label: 'Groups',
      value: result.groupBy.length.toString(),
      icon: <CalendarBlank size={13} />,
    })
  }

  if (result.filters.length > 0) {
    const periodFilter = result.filters.find((f) => f.label === 'Period' || f.label === 'Period B')
    if (periodFilter) {
      metrics.push({
        label: 'Period',
        value: periodFilter.value,
        icon: <CalendarBlank size={13} />,
      })
    }
  }

  if (metrics.length === 0) return null

  return (
    <div className="flex flex-wrap gap-2">
      {metrics.map((m) => (
        <div
          key={m.label}
          className="flex items-center gap-1.5 rounded-[8px] border border-line bg-sunken/50 px-2.5 py-1.5 dark:border-line-dark dark:bg-sunken-dark/50"
        >
          <span className="text-accent dark:text-accent-dark">{m.icon}</span>
          <span className="text-[11px] text-ink-faint dark:text-ink-faint-dark">{m.label}</span>
          <span className="font-mono text-xs font-medium text-ink dark:text-ink-dark">{m.value}</span>
        </div>
      ))}
    </div>
  )
}
