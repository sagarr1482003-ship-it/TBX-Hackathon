import { useState } from 'react'
import { ArrowRight, ChartBar, Check, Copy, Table, TextAa } from '@phosphor-icons/react'
import type { QueryResult } from '../lib/types'
import { ConfidenceBadge } from './ConfidenceBadge'
import { ChartView } from './ChartView'
import { MetricStrip } from './MetricStrip'

export function UserBubble({ text }: { text: string }) {
  return (
    <div className="msg-in flex justify-end">
      <div className="max-w-[80%] rounded-[10px] bg-ink px-4 py-2.5 text-sm leading-relaxed text-paper dark:bg-ink-dark dark:text-paper-dark">
        {text}
      </div>
    </div>
  )
}

export function AssistantBubble({
  result,
  active,
  onSelect,
}: {
  result: QueryResult
  active: boolean
  onSelect: () => void
}) {
  const [copied, setCopied] = useState(false)
  const hasChart = !!result.chart
  const [viewMode, setViewMode] = useState<'text' | 'chart'>(hasChart ? 'chart' : 'text')



  function copyAnswer(e: React.MouseEvent) {
    e.stopPropagation()
    navigator.clipboard?.writeText(result.answer).then(() => {
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1500)
    })
  }

  return (
    <div
      className={`msg-in group w-full max-w-[88%] overflow-hidden rounded-[10px] border transition-colors ${
        active
          ? 'border-accent/40 bg-accent-soft/60 dark:border-accent-dark/30 dark:bg-accent-soft-dark/40'
          : 'border-line bg-surface hover:border-ink-faint/40 dark:border-line-dark dark:bg-surface-dark dark:hover:border-ink-faint-dark/40'
      }`}
    >
      {/* View Toggle */}
      {hasChart && (
        <div className="flex items-center gap-0.5 px-4 pt-3">
          <button
            onClick={(e) => { e.stopPropagation(); setViewMode('text') }}
            className={`flex items-center gap-1 rounded-l-[8px] border px-2.5 py-1 text-[11px] font-medium transition-colors ${
              viewMode === 'text'
                ? 'border-accent/40 bg-accent-soft text-accent-strong dark:border-accent-dark/40 dark:bg-accent-soft-dark dark:text-accent-dark'
                : 'border-line text-ink-faint hover:text-ink-muted dark:border-line-dark dark:text-ink-faint-dark'
            }`}
          >
            <TextAa size={12} />
            Text
          </button>
          <button
            onClick={(e) => { e.stopPropagation(); setViewMode('chart') }}
            className={`flex items-center gap-1 rounded-r-[8px] border border-l-0 px-2.5 py-1 text-[11px] font-medium transition-colors ${
              viewMode === 'chart'
                ? 'border-accent/40 bg-accent-soft text-accent-strong dark:border-accent-dark/40 dark:bg-accent-soft-dark dark:text-accent-dark'
                : 'border-line text-ink-faint hover:text-ink-muted dark:border-line-dark dark:text-ink-faint-dark'
            }`}
          >
            <ChartBar size={12} />
            Chart
          </button>
        </div>
      )}

      {/* Content */}
      {viewMode === 'text' ? (
        <button onClick={onSelect} className="w-full px-4 pb-1 pt-3.5 text-left">
          <p className="text-sm leading-relaxed text-ink dark:text-ink-dark">{result.answer}</p>
        </button>
      ) : (
        <div className="px-4 pt-3" onClick={(e) => e.stopPropagation()}>
          <MetricStrip result={result} />
          <div className="mt-3 overflow-hidden">
            <ChartView
              chart={result.chart!}
              dark={document.documentElement.classList.contains('dark')}
              compact
            />
          </div>
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2 px-4 pb-3 pt-1.5">
        <ConfidenceBadge confidence={result.confidence} />
        {result.records.length > 0 && (
          <span className="inline-flex items-center gap-1 text-xs text-ink-muted dark:text-ink-muted-dark">
            <Table size={13} />
            {result.records.length} record{result.records.length === 1 ? '' : 's'}
          </span>
        )}
        <button
          onClick={copyAnswer}
          aria-label="Copy answer"
          className="ml-auto flex items-center gap-1 text-xs text-ink-faint opacity-0 transition-opacity hover:text-ink-muted group-hover:opacity-100 dark:text-ink-faint-dark dark:hover:text-ink-muted-dark"
        >
          {copied ? <Check size={12} /> : <Copy size={12} />}
        </button>
        <button onClick={onSelect} className="inline-flex items-center gap-1 text-xs font-medium text-accent dark:text-accent-dark">
          View evidence
          <ArrowRight size={12} />
        </button>
      </div>
    </div>
  )
}
